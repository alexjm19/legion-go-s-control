#!/usr/bin/env python3
"""Efficiency benchmark for the Legion Go S (run as root, plugged in, idle).

Measures package power (zenergy Esocket0), max Tctl and throughput for:
  A) GPU max-clock caps under a fixed vkmark scene  → perf/W curve
  B) CPU boost on/off and EPP values under light, medium and full load
  C) idle power with boost on/off
All knobs are restored at the end. Results go to /var/lib/lgsc-bench/eff.txt.
"""

import glob
import os
import re
import subprocess
import time

OUT = "/var/lib/lgsc-bench/eff.txt"
VK = ["runuser", "-u", "alexjm", "--", "env", "XDG_RUNTIME_DIR=/run/user/1000",
      "podman", "run", "--rm", "--device", "/dev/dri", "--security-opt", "label=disable",
      "lgsc-bench", "vkmark", "--winsys", "headless", "-s", "1920x1080"]


def hw(name):
    for h in glob.glob("/sys/class/hwmon/hwmon*"):
        if open(f"{h}/name").read().strip() == name:
            return h


ZEN, K10 = hw("zenergy"), hw("k10temp")
GPU = glob.glob("/sys/class/drm/card*/device/pp_od_clk_voltage")[0].rsplit("/", 1)[0]
CPUS = glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq")
BOOST = "/sys/devices/system/cpu/cpufreq/boost"


def log(m):
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    line = f"{time.strftime('%T')} {m}"
    print(line, flush=True)
    with open(OUT, "a") as f:
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())


def energy():
    for lab in glob.glob(f"{ZEN}/energy*_label"):
        if open(lab).read().strip() == "Esocket0":
            return int(open(lab.replace("_label", "_input")).read())


def tctl():
    return int(open(f"{K10}/temp1_input").read()) / 1000


def wr(p, v):
    with open(p, "w") as f:
        f.write(str(v))


def rd(p):
    return open(p).read().strip()


def run(cmd, seconds, settle=5):
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) if cmd else None
    time.sleep(settle)
    e0, t0, tmax = energy(), time.time(), 0.0
    while time.time() - t0 < seconds - settle and (p is None or p.poll() is None):
        time.sleep(1)
        tmax = max(tmax, tctl())
    w = (energy() - e0) / 1e6 / (time.time() - t0)
    out = p.communicate()[0] if p else ""
    return w, tmax, out


def gpu_cap(mhz):
    if mhz:
        wr(f"{GPU}/power_dpm_force_performance_level", "manual")
        wr(f"{GPU}/pp_od_clk_voltage", "s 0 200")
        wr(f"{GPU}/pp_od_clk_voltage", f"s 1 {mhz}")
        wr(f"{GPU}/pp_od_clk_voltage", "c")
    else:
        # OD writes are only accepted in manual mode
        wr(f"{GPU}/power_dpm_force_performance_level", "manual")
        wr(f"{GPU}/pp_od_clk_voltage", "r")
        wr(f"{GPU}/pp_od_clk_voltage", "c")
        wr(f"{GPU}/power_dpm_force_performance_level", "auto")


def score(out):
    m = re.findall(r"Score: (\d+)", out)
    return int(m[-1]) if m else 0


def bogo(out):
    m = re.search(r"cpu\s+(\d+)\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+([\d.]+)", out)
    return float(m.group(2)) if m else 0.0


def set_epp(v):
    for c in CPUS:
        wr(f"{c}/energy_performance_preference", v)


def main():
    saved = {"boost": rd(BOOST), "epp": rd(f"{CPUS[0]}/energy_performance_preference")}
    log(f"=== eff bench; saved {saved}; EPP options: {rd(CPUS[0] + '/energy_performance_available_preferences')}")
    try:
        log("--- A) GPU cap, vkmark effect2d blur 1920x1080 (GPU-bound), 45 s each")
        for mhz in (None, 1600, 1400, 1200, 1000, 800, 600):
            gpu_cap(mhz)
            w, t, out = run(VK + ["-b", "effect2d:kernel=blur:duration=45"], 45)
            s = score(out)
            sclk = [l for l in open(f"{GPU}/pp_dpm_sclk").read().splitlines() if "*" in l]
            log(f"  (last sclk {sclk})")
            log(f"  gpu_max={mhz or 'auto(2200)'} MHz: score {s}  {w:.2f} W  {s / w if w else 0:.0f} pts/W  Tmax {t:.0f}C")
            time.sleep(10)
        gpu_cap(None)

        log("--- B) CPU boost x EPP, stress-ng fft 8 threads, 40 s each")
        for load in (25, 50, 100):
            for boost in ("1", "0"):
                wr(BOOST, boost)
                for epp in ("balance_performance", "balance_power", "power"):
                    set_epp(epp)
                    cmd = ["stress-ng", "--temp-path", "/tmp", "--cpu", "8", "--cpu-method", "fft", "--cpu-load", str(load), "-t", "40", "--metrics-brief"]
                    w, t, out = run(cmd, 40)
                    b = bogo(out)
                    if not b:
                        log("  stress-ng output: " + " | ".join(out.strip().splitlines()[-4:]))
                    log(f"  load={load}% boost={boost} epp={epp}: {b:.0f} bogo/s  {w:.2f} W  {b / w if w else 0:.0f} bogo/J  Tmax {t:.0f}C")
                    time.sleep(5)

        log("--- C) idle 40 s")
        set_epp(saved["epp"])
        for boost in ("1", "0"):
            wr(BOOST, boost)
            w, t, _ = run(None, 40, settle=10)
            log(f"  idle boost={boost}: {w:.2f} W  Tmax {t:.0f}C")
    finally:
        wr(BOOST, saved["boost"])
        set_epp(saved["epp"])
        gpu_cap(None)
        log("=== end; knobs restored")


if __name__ == "__main__":
    main()
