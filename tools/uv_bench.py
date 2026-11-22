#!/usr/bin/env python3
"""Curve Optimizer sweep for the Legion Go S (AMD Z2 Go / Rembrandt). Run as root.

  uv_bench.py cpu  0 -5 -10 ...     # all-core CO sweep (ryzenadj --set-coall)
  uv_bench.py gpu  0 -5 -10 ...     # iGPU CO sweep    (ryzenadj --set-cogfx)
  uv_bench.py soak cpu=-20 gpu=-10 MINUTES   # long mixed CPU+GPU soak at fixed values

For every step it measures package power at a fixed frequency (so only voltage
changes between steps) and then runs stability tests. It stops at the first
failure (stress-ng verify error, machine-check error, amdgpu fault, or a crash,
which shows up in the log as a START line without a matching result) and resets
CO to 0. The log is fsynced line by line so it survives a hard crash.
"""

import glob
import os
import re
import subprocess
import sys
import time

LOG = "/var/lib/lgsc-bench/log.txt"
VKMARK = ["podman", "run", "--rm", "--device", "/dev/dri", "--security-opt", "label=disable",
          "lgsc-bench", "vkmark", "--winsys", "headless", "-s", "1920x1080"]
CPU_FIX_KHZ = 2400000
GPU_FIX_MHZ = 1200


def log(msg):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    line = f"{time.strftime('%F %T')} {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())


def sh(cmd, timeout=None):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def co_arg(v):
    v = int(v)
    return str(0x100000 + v if v < 0 else v)


def set_co(kind, v):
    flag = {"cpu": "--set-coall", "gpu": "--set-cogfx"}[kind]
    r = sh(["ryzenadj", f"{flag}={co_arg(v)}"])
    if r.returncode != 0:
        raise RuntimeError(f"ryzenadj failed: {r.stderr.strip()} {r.stdout.strip()}")


def hwmon(name):
    for h in glob.glob("/sys/class/hwmon/hwmon*"):
        if open(f"{h}/name").read().strip() == name:
            return h
    return None


ZEN = hwmon("zenergy")
K10 = hwmon("k10temp")
GPU_DEV = glob.glob("/sys/class/drm/card*/device/pp_od_clk_voltage")[0].rsplit("/", 1)[0]


def socket_energy_uj():
    for lab in glob.glob(f"{ZEN}/energy*_label"):
        if open(lab).read().strip() == "Esocket0":
            return int(open(lab.replace("_label", "_input")).read())
    raise RuntimeError("no Esocket0")


def tctl():
    return int(open(f"{K10}/temp1_input").read()) / 1000


def kernel_errors():
    out = sh(["dmesg"]).stdout
    pat = re.compile(r"(Hardware Error|mce: \[|amdgpu.*(timeout|hang|reset|fault|error))", re.I)
    return sum(1 for l in out.splitlines() if pat.search(l) and "decoding enabled" not in l)


def set_cpu_max(khz):
    for f in glob.glob("/sys/devices/system/cpu/cpu*/cpufreq/scaling_max_freq"):
        open(f, "w").write(str(khz))


def cpu_max_hw():
    return int(open("/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq").read())


def gpu_fix(mhz):
    if mhz:
        open(f"{GPU_DEV}/power_dpm_force_performance_level", "w").write("manual")
        od = f"{GPU_DEV}/pp_od_clk_voltage"
        open(od, "w").write(f"s 0 {mhz}\n")
        open(od, "w").write(f"s 1 {mhz}\n")
        open(od, "w").write("c\n")
    else:
        open(f"{GPU_DEV}/pp_od_clk_voltage", "w").write("r\n")
        open(f"{GPU_DEV}/pp_od_clk_voltage", "w").write("c\n")
        open(f"{GPU_DEV}/power_dpm_force_performance_level", "w").write("auto")


def measure(cmd, seconds):
    """Run cmd for `seconds`, return (avg package W, max Tctl, stdout)."""
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    time.sleep(5)  # settle
    e0, t0, tmax = socket_energy_uj(), time.time(), 0.0
    while time.time() - t0 < seconds - 5 and p.poll() is None:
        time.sleep(1)
        tmax = max(tmax, tctl())
    e1, t1 = socket_energy_uj(), time.time()
    out = p.communicate()[0]
    return (e1 - e0) / 1e6 / (t1 - t0), tmax, out


def stress_ok(out):
    m = re.search(r"failed: (\d+)", out)
    return m is not None and int(m.group(1)) == 0 and "untrustworthy: 0" in out


def bogo(out):
    m = re.search(r"cpu\s+(\d+)\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+([\d.]+)", out)
    return float(m.group(2)) if m else None


def cpu_step(v):
    # 1) power at fixed frequency (same work rate at every step)
    set_cpu_max(CPU_FIX_KHZ)
    w, t, out = measure(["stress-ng", "--cpu", "8", "--cpu-method", "matrixprod",
                         "-t", "60", "--metrics-brief"], 60)
    set_cpu_max(cpu_max_hw())
    log(f"  power@2.4GHz: {w:.2f} W  Tmax {t:.0f}C  ok={stress_ok(out)}")
    if not stress_ok(out):
        return False
    # 2) stability, full boost
    tests = [
        ("all-core verify", ["stress-ng", "--cpu", "8", "--cpu-method", "all", "--verify", "-t", "150", "--metrics-brief"]),
        ("light-load transitions", ["stress-ng", "--cpu", "8", "--cpu-load", "25", "--cpu-method", "fft", "--verify", "-t", "45", "--metrics-brief"]),
    ] + [
        (f"single-core boost cpu{c}", ["stress-ng", "--cpu", "1", "--taskset", str(c), "--cpu-method", "fft", "--verify", "-t", "20", "--metrics-brief"])
        for c in (0, 2, 4, 6)
    ]
    for name, cmd in tests:
        w, t, out = measure(cmd, int(cmd[cmd.index("-t") + 1]))
        ok = stress_ok(out)
        log(f"  {name}: {w:.2f} W  Tmax {t:.0f}C  bogo/s {bogo(out)}  ok={ok}")
        if not ok:
            log("  stress-ng output tail: " + " | ".join(out.strip().splitlines()[-6:]))
            return False
    return True


def score(out):
    m = re.findall(r"Score: (\d+)", out)
    return int(m[-1]) if m else None


def vkmark(seconds, scene="shading:shading=phong"):
    return VKMARK + ["-b", f"{scene}:duration={seconds}"]


def gpu_step(v):
    gpu_fix(GPU_FIX_MHZ)
    w, t, out = measure(vkmark(60), 60)
    gpu_fix(None)
    ok = "Score" in out
    log(f"  power@{GPU_FIX_MHZ}MHz: {w:.2f} W  Tmax {t:.0f}C  score {score(out)} ok={ok}")
    if not ok:
        return False
    for scene in ("shading:shading=phong", "effect2d", "cube", "texture", "vertex"):
        w, t, out = measure(vkmark(40, scene), 40)
        ok = "Score" in out
        log(f"  {scene}: {w:.2f} W  Tmax {t:.0f}C  score score {score(out)} ok={ok}")
        if not ok:
            log("  vkmark output tail: " + " | ".join(out.strip().splitlines()[-6:]))
            return False
    return True


def sweep(kind, values):
    base_err = kernel_errors()
    log(f"=== sweep {kind} {values} (kernel errors before: {base_err})")
    last_ok = None
    try:
        for v in values:
            log(f"START {kind} co={v}")
            set_co(kind, v)
            time.sleep(3)
            ok = (cpu_step if kind == "cpu" else gpu_step)(v)
            err = kernel_errors() - base_err
            if err:
                log(f"  new kernel errors: {err}")
                ok = False
            log(f"{'PASS' if ok else 'FAIL'} {kind} co={v}")
            if not ok:
                break
            last_ok = v
            time.sleep(20)  # cool down between steps
    finally:
        set_co(kind, 0)
        set_cpu_max(cpu_max_hw())
        gpu_fix(None)
        log(f"=== end {kind}: last passing co={last_ok}; CO reset to 0")


def soak(cpu_v, gpu_v, minutes):
    base_err = kernel_errors()
    log(f"=== soak cpu={cpu_v} gpu={gpu_v} {minutes} min")
    log(f"START soak cpu={cpu_v} gpu={gpu_v}")
    try:
        set_co("cpu", cpu_v)
        set_co("gpu", gpu_v)
        end = time.time() + minutes * 60
        ok = True
        while ok and time.time() < end:
            g = subprocess.Popen(vkmark(120, "shading:shading=phong"), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            w, t, out = measure(["stress-ng", "--cpu", "8", "--cpu-method", "all", "--verify", "-t", "120", "--metrics-brief"], 120)
            gout = g.communicate()[0]
            ok = stress_ok(out) and "Score" in gout and kernel_errors() == base_err
            log(f"  mixed 120s: {w:.2f} W  Tmax {t:.0f}C  ok={ok}")
            for c in (0, 3, 5, 7):  # boost / idle transitions
                w, t, out = measure(["stress-ng", "--cpu", "1", "--taskset", str(c), "--cpu-method", "fft", "--verify", "-t", "15", "--metrics-brief"], 15)
                ok = ok and stress_ok(out)
            time.sleep(10)  # idle
        log(f"{'PASS' if ok else 'FAIL'} soak cpu={cpu_v} gpu={gpu_v}")
    finally:
        set_co("cpu", 0)
        set_co("gpu", 0)
        log("=== end soak; CO reset to 0")


if __name__ == "__main__":
    if sys.argv[1] == "soak":
        kv = dict(a.split("=") for a in sys.argv[2:4])
        soak(int(kv["cpu"]), int(kv["gpu"]), float(sys.argv[4]))
    else:
        sweep(sys.argv[1], [int(x) for x in sys.argv[2:]])
