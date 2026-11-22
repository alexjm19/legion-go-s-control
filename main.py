"""Legion Go S Control — Decky backend (runs as root).

Everything is done through the sysfs files that the mainline/OGC kernel drivers
expose for the Lenovo Legion Go S:

* ``hid-lenovo-go-s``  → stick RGB rings (LED class) and touchpad settings.
* ``ideapad_laptop``   → battery ``charge_types`` (Fast / Standard / Long_Life).

The only hidraw access is a read-only touchpad bridge (see
``py_modules/touchpad_bridge.py``); hidraw supports several readers, so it
coexists with InputPlumber.
"""

import asyncio
import glob
import json
import os
import subprocess

import decky
from performance import Performance
from touchpad_bridge import TouchpadBridge

LED_GLOB = "/sys/class/leds/go_s:rgb:joystick_rings"
BAT_GLOB = "/sys/class/power_supply/BAT*"
SLEEP_UNITS = [
    "sleep.target",
    "suspend.target",
    "hibernate.target",
    "hybrid-sleep.target",
    "suspend-then-hibernate.target",
]
REAPPLY_EVERY_S = 15

DEFAULTS = {
    "charge_mode": None,  # None = don't touch what the firmware has
    "server_mode": False,
    "led": None,  # None = don't touch; otherwise dict, see set_led
    # Absolute mode sends no data on some units, and nothing consumes the
    # relative report, hence the bridge (see py_modules/touchpad_bridge.py).
    "touchpad": {"enabled": True, "mode": "relative", "bridge": True, "sensitivity": 1.0},
    # None in any key = leave that knob to Steam / the system.
    "perf": {"boost": None, "epp": None, "gpu_max": None},
}


# ---------------------------------------------------------------- sysfs helpers
def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def _write(path, value):
    value = str(value)
    if _read(path) == value:
        return True
    try:
        with open(path, "w") as f:
            f.write(value)
        return True
    except OSError as e:
        decky.logger.error(f"write {path}={value!r} failed: {e}")
        return False


def _choice(path):
    """Parse a sysfs choice file like ``[Fast] Standard Long_Life``."""
    raw = _read(path)
    if raw is None:
        return None, []
    options, current = [], None
    for tok in raw.split():
        if tok.startswith("[") and tok.endswith("]"):
            tok = tok[1:-1]
            current = tok
        options.append(tok)
    return current, options


def _led_dir():
    p = glob.glob(LED_GLOB)
    return p[0] if p else None


def _hid_dir():
    led = _led_dir()
    return os.path.realpath(os.path.join(led, "device")) if led else None


def _bat_dir():
    for p in sorted(glob.glob(BAT_GLOB)):
        if os.path.exists(os.path.join(p, "charge_types")):
            return p
    p = sorted(glob.glob(BAT_GLOB))
    return p[0] if p else None


def _split_index(path):
    raw = _read(path)
    return raw.split() if raw else []


# ---------------------------------------------------------------- sleep control
def _sleep_masked():
    out = subprocess.run(
        ["systemctl", "is-enabled", SLEEP_UNITS[1]],
        capture_output=True, text=True,
    ).stdout.strip()
    return out.startswith("masked")


def _set_sleep_masked(masked):
    cmd = ["systemctl", "mask" if masked else "unmask", "--runtime", *SLEEP_UNITS]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        decky.logger.error(f"{' '.join(cmd)} failed: {r.stderr.strip()}")
        return False
    return True


class Plugin:
    settings = dict(DEFAULTS)
    bridge = None
    perf = None

    # ------------------------------------------------------------ persistence
    def _settings_path(self):
        return os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "settings.json")

    def _load(self):
        try:
            with open(self._settings_path()) as f:
                self.settings = {**DEFAULTS, **json.load(f)}
            self.settings["perf"] = {**DEFAULTS["perf"], **(self.settings.get("perf") or {})}
            if self.settings.get("touchpad") is not None:
                self.settings["touchpad"] = {**DEFAULTS["touchpad"], **self.settings["touchpad"]}
        except (OSError, ValueError):
            self.settings = dict(DEFAULTS)

    def _save(self):
        os.makedirs(decky.DECKY_PLUGIN_SETTINGS_DIR, exist_ok=True)
        tmp = self._settings_path() + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.settings, f, indent=2)
        os.replace(tmp, self._settings_path())

    # ------------------------------------------------------------ apply
    def _apply_charge(self):
        mode = self.settings.get("charge_mode")
        bat = _bat_dir()
        if mode and bat:
            _write(os.path.join(bat, "charge_types"), mode)

    def _apply_led(self):
        cfg = self.settings.get("led")
        led = _led_dir()
        if not cfg or not led:
            return
        _write(os.path.join(led, "enabled"), "true" if cfg["enabled"] else "false")
        if not cfg["enabled"]:
            return
        _write(os.path.join(led, "effect"), cfg["effect"])
        r, g, b = cfg["color"]
        _write(os.path.join(led, "multi_intensity"), f"{r} {g} {b}")
        _write(os.path.join(led, "brightness"), cfg["brightness"])
        _write(os.path.join(led, "speed"), cfg["speed"])

    def _apply_touchpad(self):
        cfg = self.settings.get("touchpad")
        hid = _hid_dir()
        if not cfg or not hid:
            return
        tp = os.path.join(hid, "touchpad")
        _write(os.path.join(tp, "linux_mode"), cfg["mode"])
        _write(os.path.join(tp, "enabled"), "true" if cfg["enabled"] else "false")
        want = cfg["enabled"] and cfg["mode"] == "relative" and cfg.get("bridge", True)
        if self.bridge is None:
            self.bridge = TouchpadBridge(decky.logger)
        self.bridge.sensitivity = float(cfg.get("sensitivity", 1.0))
        if want and not self.bridge.running:
            self.bridge.start()
        elif not want and self.bridge.running:
            self.bridge.stop()

    def _apply_server(self):
        want = bool(self.settings.get("server_mode"))
        if _sleep_masked() != want:
            _set_sleep_masked(want)

    def _apply_perf(self):
        if self.perf is None:
            self.perf = Performance(decky.logger)
        self.perf.apply(self.settings.get("perf"))

    def _apply_all(self):
        for fn in (self._apply_charge, self._apply_led, self._apply_touchpad, self._apply_server, self._apply_perf):
            try:
                fn()
            except Exception as e:  # never let one subsystem break the others
                decky.logger.exception(f"{fn.__name__}: {e}")

    # ------------------------------------------------------------ API (frontend)
    async def get_state(self):
        bat = _bat_dir()
        led = _led_dir()
        hid = _hid_dir()
        state = {"settings": self.settings}

        if bat:
            cur, opts = _choice(os.path.join(bat, "charge_types"))
            power_uw = _read(os.path.join(bat, "power_now"))
            ac = None
            for acp in glob.glob("/sys/class/power_supply/AC*"):
                ac = _read(os.path.join(acp, "online")) == "1"
            state["battery"] = {
                "available": cur is not None,
                "mode": cur,
                "modes": opts,
                "capacity": int(_read(os.path.join(bat, "capacity")) or 0),
                "status": _read(os.path.join(bat, "status")),
                "power_w": round(int(power_uw) / 1e6, 1) if power_uw else None,
                "ac": ac,
            }
        else:
            state["battery"] = {"available": False}

        if led:
            mi = (_read(os.path.join(led, "multi_intensity")) or "0 0 0").split()
            state["led"] = {
                "available": True,
                "enabled": _read(os.path.join(led, "enabled")) == "true",
                "effect": _read(os.path.join(led, "effect")),
                "effects": _split_index(os.path.join(led, "effect_index")),
                "color": [int(x) for x in mi[:3]],
                "brightness": int(_read(os.path.join(led, "brightness")) or 0),
                "speed": int(_read(os.path.join(led, "speed")) or 0),
            }
        else:
            state["led"] = {"available": False}

        tp = os.path.join(hid, "touchpad") if hid else None
        if tp and os.path.isdir(tp):
            state["touchpad"] = {
                "available": True,
                "enabled": _read(os.path.join(tp, "enabled")) == "true",
                "mode": _read(os.path.join(tp, "linux_mode")),
                "modes": _split_index(os.path.join(tp, "linux_mode_index")),
                "bridge": bool(self.bridge and self.bridge.running),
                "bridge_hidraw": self.bridge.hidraw if self.bridge else None,
            }
        else:
            state["touchpad"] = {"available": False}

        state["server"] = {"sleep_blocked": _sleep_masked()}
        if self.perf is None:
            self.perf = Performance(decky.logger)
        state["perf"] = self.perf.state()
        return state

    async def set_charge_mode(self, mode):
        self.settings["charge_mode"] = mode
        self._save()
        self._apply_charge()
        return await self.get_state()

    async def set_server_mode(self, enabled):
        self.settings["server_mode"] = bool(enabled)
        self._save()
        self._apply_server()
        return await self.get_state()

    async def set_led(self, enabled, effect, color, brightness, speed):
        self.settings["led"] = {
            "enabled": bool(enabled),
            "effect": str(effect),
            "color": [max(0, min(100, int(c))) for c in color][:3],
            "brightness": max(0, min(100, int(brightness))),
            "speed": max(0, min(100, int(speed))),
        }
        self._save()
        self._apply_led()
        return await self.get_state()

    async def set_perf(self, boost=None, epp=None, gpu_max=None):
        old = self.settings.get("perf") or {}
        self.settings["perf"] = {
            "boost": None if boost is None else bool(boost),
            "epp": epp or None,
            "gpu_max": int(gpu_max) if gpu_max else None,
        }
        self._save()
        new = self.settings["perf"]
        if old.get("gpu_max") and not new["gpu_max"]:
            self.perf.release_gpu()
        self.perf.release_cpu(
            old.get("boost") is not None and new["boost"] is None,
            bool(old.get("epp")) and not new["epp"],
        )
        self._apply_perf()
        return await self.get_state()

    async def set_touchpad(self, enabled, mode, bridge=True, sensitivity=1.0):
        self.settings["touchpad"] = {
            "enabled": bool(enabled),
            "mode": str(mode),
            "bridge": bool(bridge),
            "sensitivity": max(0.2, min(4.0, float(sensitivity))),
        }
        self._save()
        self._apply_touchpad()
        return await self.get_state()

    # ------------------------------------------------------------ lifecycle
    async def _reapply_loop(self):
        # Settings can be lost after suspend/resume or when the controller MCU
        # re-enumerates; writes are skipped when the value already matches.
        while True:
            await asyncio.sleep(REAPPLY_EVERY_S)
            self._apply_all()

    async def _main(self):
        self._load()
        decky.logger.info(f"Legion Go S Control loaded: {self.settings}")
        self._apply_all()
        self._task = asyncio.get_event_loop().create_task(self._reapply_loop())

    async def _unload(self):
        task = getattr(self, "_task", None)
        if task:
            task.cancel()
        if self.bridge:
            self.bridge.stop()
        # Never leave the machine unable to sleep once the plugin is gone.
        if _sleep_masked():
            _set_sleep_masked(False)

    async def _uninstall(self):
        if _sleep_masked():
            _set_sleep_masked(False)
