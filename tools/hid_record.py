# Records raw hidraw + evdev. Phase A (absolute) then phase B (relative), line-buffered.
import os, select, sys, time, glob, struct
dur=float(sys.argv[1]); switch=float(sys.argv[2]); out=open(sys.argv[3],"w",buffering=1)
tpdir=os.path.realpath("/sys/class/leds/go_s:rgb:joystick_rings/device")+"/touchpad/linux_mode"
orig=open(tpdir).read().strip()
devs={}
def open_all():
    for p in glob.glob("/dev/hidraw*")+glob.glob("/dev/input/event*"):
        if p in devs.values(): continue
        try: devs[os.open(p,os.O_RDONLY|os.O_NONBLOCK)]=p
        except OSError: pass
open_all(); last={}; t0=time.time(); switched=False
out.write(f"# orig={orig}\n")
while time.time()-t0<dur:
    t=time.time()-t0
    if not switched and t>=switch:
        open(tpdir,"w").write("relative"); switched=True; out.write(f"{t:.2f} SWITCH relative\n"); time.sleep(1); open_all()
    r,_,_=select.select(list(devs),[],[],0.5)
    for fd in r:
        try: d=os.read(fd,4096)
        except OSError: continue
        p=devs[fd]
        if "event" in p:
            for i in range(0,len(d)-23,24):
                _,_,ty,co,va=struct.unpack("qqHHi",d[i:i+24])
                if ty in (1,2,3): out.write(f"{t:.2f} {os.path.basename(p)} ev {ty} {co} {va}\n")
        elif last.get(p)!=d:
            out.write(f"{t:.2f} {os.path.basename(p)} {d.hex()}\n"); last[p]=d
open(tpdir,"w").write(orig); out.write(f"END restored {orig}\n")
