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
        return {
            "available": bool(pol),
            "boost": _read(BOOST) == "1" if os.path.exists(BOOST) else None,
            "epp": epp,
            "epps": [e for e in epps if e in ("performance", "balance_performance", "balance_power", "power")],
            "gpu_level": _read(f"{dev}/power_dpm_force_performance_level") if dev else None,
            "gpu_max": cur,
            "gpu_range": [rmin, rmax],
            "watts": self.watts,
            "temp": round(int(tctl) / 1000) if tctl else None,
        }

    # -------------------------------------------------------------- apply
    def apply(self, cfg):
        """cfg keys: boost (bool|None), epp (str|None), gpu_max (int|None)."""
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
