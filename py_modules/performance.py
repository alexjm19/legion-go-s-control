"""Power/efficiency knobs for the Legion Go S (AMD Z2 Go, amd-pstate-epp, amdgpu).

Curve Optimizer is not available: the Lenovo SMU firmware rejects set_coall,
set_cogfx and set_coper (even with a value of 0). What *is* open:

* CPU boost on/off            /sys/devices/system/cpu/cpufreq/boost
* CPU EPP                      .../cpufreq/policy*/energy_performance_preference
* GPU max shader clock (cap)   <card>/pp_od_clk_voltage (manual mode)

Lower clocks run at lower voltages on the V/F curve, so capping is the
"undervolt" that is reachable. Every knob accepts None = leave it alone, so it
doesn't fight Steam's own performance overlay.
"""

import glob
import os
import time

BOOST = "/sys/devices/system/cpu/cpufreq/boost"

# Lenovo WMI "other" firmware attributes. A single TDP value is written to all
# three limits, which is how Legion tools (e.g. SimpleDeckyTDP) define TDP.
FW_ATTRS = "/sys/class/firmware-attributes/lenovo-wmi-other-0/attributes"
TDP_ATTRS = ("ppt_pl3_fppt", "ppt_pl2_sppt", "ppt_pl1_spl")
TDP_SUSTAINED = "ppt_pl1_spl"


def _read(p):
    try:
        with open(p) as f:
            return f.read().strip()
    except OSError:
        return None


def _write(p, v):
    v = str(v)
    try:
        with open(p, "w") as f:
            f.write(v)
        return True
    except OSError:
        return False


def _policies():
    return sorted(glob.glob("/sys/devices/system/cpu/cpufreq/policy*"))


def _gpu_dev():
    p = glob.glob("/sys/class/drm/card*/device/pp_od_clk_voltage")
    return os.path.dirname(p[0]) if p else None


def _hwmon(name):
    for h in glob.glob("/sys/class/hwmon/hwmon*"):
        if _read(f"{h}/name") == name:
            return h
    return None


def gpu_od():
    """Return (current_max_mhz, range_min, range_max) from pp_od_clk_voltage."""
    dev = _gpu_dev()
    raw = _read(f"{dev}/pp_od_clk_voltage") if dev else None
    if not raw:
        return None, None, None
    cur_max = rmin = rmax = None
    section = None
    for line in raw.splitlines():
        line = line.strip()
        if line.endswith(":"):
            section = line[:-1]
            continue
        if section == "OD_SCLK" and line.startswith("1:"):
            cur_max = int(line.split()[1].lower().replace("mhz", ""))
        if section == "OD_RANGE" and line.startswith("SCLK:"):
            parts = line.split()
            rmin = int(parts[1].lower().replace("mhz", ""))
            rmax = int(parts[2].lower().replace("mhz", ""))
    return cur_max, rmin, rmax


def _int_file(path):
    value = _read(path)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _tdp_available():
    return all(
        os.path.exists(f"{FW_ATTRS}/{attr}/current_value") for attr in TDP_ATTRS
    )


def tdp_range():
    """Return the (min, max) sustained TDP in watts declared by the firmware."""
    return (
        _int_file(f"{FW_ATTRS}/{TDP_SUSTAINED}/min_value"),
        _int_file(f"{FW_ATTRS}/{TDP_SUSTAINED}/max_value"),
    )


def _platform_profile_path():
    for dev in glob.glob("/sys/class/platform-profile/*"):
        if _read(os.path.join(dev, "name")) == "lenovo-wmi-gamezone":
            path = os.path.join(dev, "profile")
            if os.path.exists(path):
                return path
    return None


class Performance:
    def __init__(self, logger):
        self.log = logger
        self._e_last = None  # (energy_uj, t)
        self.watts = None

    # -------------------------------------------------------------- telemetry
    def _energy_uj(self):
        h = _hwmon("zenergy")
        if not h:
            return None
        for lab in glob.glob(f"{h}/energy*_label"):
            if _read(lab) == "Esocket0":
                v = _read(lab.replace("_label", "_input"))
                return int(v) if v else None
        return None

    def sample(self):
        e, t = self._energy_uj(), time.monotonic()
        if e is not None and self._e_last is not None:
            de, dt = e - self._e_last[0], t - self._e_last[1]
            if dt > 0.5 and de >= 0:
                self.watts = round(de / 1e6 / dt, 1)
        if e is not None:
            self._e_last = (e, t)

    def state(self):
        self.sample()
        pol = _policies()
        epp = _read(f"{pol[0]}/energy_performance_preference") if pol else None
        epps = (_read(f"{pol[0]}/energy_performance_available_preferences") or "").split() if pol else []
        k10 = _hwmon("k10temp")
        tctl = _read(f"{k10}/temp1_input") if k10 else None
        cur, rmin, rmax = gpu_od()
        dev = _gpu_dev()
        tdp_min, tdp_max = tdp_range()
        profile_path = _platform_profile_path()
        return {
            "available": bool(pol),
            "boost": _read(BOOST) == "1" if os.path.exists(BOOST) else None,
            "epp": epp,
            "epps": [e for e in epps if e in ("performance", "balance_performance", "balance_power", "power")],
            "gpu_level": _read(f"{dev}/power_dpm_force_performance_level") if dev else None,
            "gpu_max": cur,
            "gpu_range": [rmin, rmax],
            "tdp": _int_file(f"{FW_ATTRS}/{TDP_SUSTAINED}/current_value"),
            "tdp_range": [tdp_min, tdp_max],
            "tdp_available": _tdp_available(),
            "tdp_profile": _read(profile_path) if profile_path else None,
            "watts": self.watts,
            "temp": round(int(tctl) / 1000) if tctl else None,
        }

    # -------------------------------------------------------------- apply
    def apply(self, cfg, apply_tdp=True):
        """cfg keys: boost (bool|None), epp (str|None), gpu_max (int|None),
        tdp (int|None).

        ``apply_tdp=False`` is used by the periodic re-apply loop: Steam and
        PowerStation also write the TDP, and re-asserting it every few seconds
        would make their sliders unusable. The user change and plugin load do
        apply it.
        """
        if not cfg:
            return
        if cfg.get("boost") is not None and os.path.exists(BOOST):
            want = "1" if cfg["boost"] else "0"
            if _read(BOOST) != want:
                _write(BOOST, want)
        epp = cfg.get("epp")
        if epp:
            for p in _policies():
                f = f"{p}/energy_performance_preference"
                if _read(f) != epp:
                    _write(f, epp)
        self._apply_gpu(cfg.get("gpu_max"))
        if apply_tdp and cfg.get("tdp") is not None:
            self.set_tdp(cfg["tdp"])

    def set_tdp(self, watts):
        """Set one TDP for the whole APU: PL1 = PL2 = PL3.

        Lenovo's firmware only honours these attributes in the ``custom``
        platform profile, so switch to it first. Returns True when all three
        values read back as requested.
        """
        if not _tdp_available():
            self.log.warning("TDP: firmware attributes not available")
            return False
        target = int(watts)
        lo, hi = tdp_range()
        if lo is not None:
            target = max(lo, target)
        if hi is not None:
            target = min(hi, target)
        profile = _platform_profile_path()
        if profile and _read(profile) != "custom":
            if not _write(profile, "custom"):
                self.log.warning("TDP: could not switch platform profile to custom")
            time.sleep(0.2)
        for attempt in range(2):
            for attr in TDP_ATTRS:
                amin = _int_file(f"{FW_ATTRS}/{attr}/min_value")
                amax = _int_file(f"{FW_ATTRS}/{attr}/max_value")
                value = target
                if amin is not None:
                    value = max(amin, value)
                if amax is not None:
                    value = min(amax, value)
                _write(f"{FW_ATTRS}/{attr}/current_value", value)
                time.sleep(0.2)
            time.sleep(0.35)
            got = {
                attr: _int_file(f"{FW_ATTRS}/{attr}/current_value")
                for attr in TDP_ATTRS
            }
            if all(value == target for value in got.values()):
                self.log.info(
                    f"TDP set to {target} W (PL1=PL2=PL3, custom profile)"
                )
                return True
            if attempt == 0:
                self.log.info(f"TDP: firmware not settled yet ({got}), retrying")
        self.log.warning(f"TDP: could not set {target} W, read {got}")
        return False

    def _apply_gpu(self, mhz):
        dev = _gpu_dev()
        if not dev:
            return
        level = f"{dev}/power_dpm_force_performance_level"
        od = f"{dev}/pp_od_clk_voltage"
        cur, rmin, rmax = gpu_od()
        if mhz:
            mhz = max(rmin or 200, min(rmax or 2200, int(mhz)))
            if _read(level) == "manual" and cur == mhz:
                return
            _write(level, "manual")
            _write(od, f"s 0 {rmin or 200}")
            _write(od, f"s 1 {mhz}")
            _write(od, "c")
            self.log.info(f"GPU max clock capped at {mhz} MHz")

    def release_cpu(self, boost_was_set, epp_was_set):
        """Back to the system defaults when a knob goes back to 'don't touch'."""
        if boost_was_set and os.path.exists(BOOST):
            _write(BOOST, "1")
        if epp_was_set:
            for p in _policies():
                _write(f"{p}/energy_performance_preference", "balance_performance")

    def release_gpu(self):
        """Undo our GPU cap (used when the user goes back to 'don't touch')."""
        dev = _gpu_dev()
        if not dev:
            return
        cur, _, rmax = gpu_od()
        level = f"{dev}/power_dpm_force_performance_level"
        if _read(level) == "manual" and cur is not None and rmax is not None and cur < rmax:
            _write(f"{dev}/pp_od_clk_voltage", "r")
            _write(f"{dev}/pp_od_clk_voltage", "c")
            _write(level, "auto")
            self.log.info("GPU clock cap released")
