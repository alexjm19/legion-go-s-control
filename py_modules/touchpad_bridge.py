"""Touchpad → virtual mouse bridge for the Legion Go S.

With ``touchpad/linux_mode = relative`` the touchpad sends a plain HID boot-style
mouse report on USB interface 2 (report id 0x01: buttons, dx, dy, wheel, pan).
Newer kernels bind that interface to ``hid-lenovo-go-s`` without creating an
input device, and InputPlumber only parses the absolute digitizer report (0x31),
so the movement is lost. This bridge reads the hidraw node (hidraw allows
several readers, so InputPlumber is unaffected) and replays it on a uinput
mouse that both KDE and gamescope pick up.

Pure Python, no dependencies.
"""

import fcntl
import glob
import os
import select
import struct
import threading
import time

VENDOR = "1A86"
PRODUCTS = ("E310", "E311")
IFACE = "02"

# linux/input-event-codes.h
EV_SYN, EV_KEY, EV_REL = 0x00, 0x01, 0x02
SYN_REPORT = 0
REL_X, REL_Y, REL_HWHEEL, REL_WHEEL = 0x00, 0x01, 0x06, 0x08
BTN_LEFT, BTN_RIGHT, BTN_MIDDLE = 0x110, 0x111, 0x112
BUS_VIRTUAL = 0x06

# linux/uinput.h ioctls
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502
UI_DEV_SETUP = 0x405C5503
UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_SET_RELBIT = 0x40045566

DEVICE_NAME = b"Legion Go S Touchpad (LGSC)"
BUTTONS = ((0x01, BTN_LEFT), (0x02, BTN_RIGHT), (0x04, BTN_MIDDLE))


def find_hidraw():
    """Return /dev/hidrawN for the touchpad mouse interface, or None."""
    for node in glob.glob("/sys/class/hidraw/hidraw*"):
        dev = os.path.realpath(os.path.join(node, "device"))
        name = os.path.basename(dev).upper()  # 0003:1A86:E310.0002
        parts = name.split(":")
        if len(parts) < 3 or parts[1] != VENDOR or parts[2][:4] not in PRODUCTS:
            continue
        iface = os.path.join(os.path.dirname(dev), "bInterfaceNumber")
        try:
            with open(iface) as f:
                if f.read().strip() == IFACE:
                    return "/dev/" + os.path.basename(node)
        except OSError:
            continue
    return None


def _s8(b):
    return b - 256 if b > 127 else b


class _UInputMouse:
    def __init__(self):
        self.fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_KEY)
        fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_REL)
        for _, code in BUTTONS:
            fcntl.ioctl(self.fd, UI_SET_KEYBIT, code)
        for code in (REL_X, REL_Y, REL_WHEEL, REL_HWHEEL):
            fcntl.ioctl(self.fd, UI_SET_RELBIT, code)
        setup = struct.pack("HHHH80sI", BUS_VIRTUAL, 0x4C47, 0x5343, 1, DEVICE_NAME, 0)
        fcntl.ioctl(self.fd, UI_DEV_SETUP, setup)
        fcntl.ioctl(self.fd, UI_DEV_CREATE)

    def emit(self, events):
        now = time.time()
        sec, usec = int(now), int((now % 1) * 1e6)
        buf = b"".join(struct.pack("qqHHi", sec, usec, t, c, v) for t, c, v in events)
        buf += struct.pack("qqHHi", sec, usec, EV_SYN, SYN_REPORT, 0)
        os.write(self.fd, buf)

    def close(self):
        try:
            fcntl.ioctl(self.fd, UI_DEV_DESTROY)
        finally:
            os.close(self.fd)


class TouchpadBridge:
    def __init__(self, logger, sensitivity=1.0):
        self.log = logger
        self.sensitivity = sensitivity
        self._stop = threading.Event()
        self._thread = None
        self.hidraw = None

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="lgsc-touchpad", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None

    def _run(self):
        mouse = None
        try:
            mouse = _UInputMouse()
            self.log.info("touchpad bridge: uinput mouse created")
            while not self._stop.is_set():
                path = find_hidraw()
                if not path:
                    self._stop.wait(3)
                    continue
                self.hidraw = path
                try:
                    self._pump(path, mouse)
                except OSError as e:  # device re-enumerated (suspend, MCU reset)
                    self.log.warning(f"touchpad bridge: {path}: {e}; retrying")
                    self._stop.wait(1)
        except Exception as e:
            self.log.exception(f"touchpad bridge crashed: {e}")
        finally:
            if mouse:
                mouse.close()
            self.log.info("touchpad bridge stopped")

    def _pump(self, path, mouse):
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        self.log.info(f"touchpad bridge: reading {path}")
        buttons = 0
        acc_x = acc_y = 0.0
        try:
            while not self._stop.is_set():
                r, _, _ = select.select([fd], [], [], 0.5)
                if not r:
                    continue
                data = os.read(fd, 64)
                if len(data) < 4 or data[0] != 0x01:
                    continue
                ev = []
                b = data[1]
                if b != buttons:
                    for mask, code in BUTTONS:
                        if (b ^ buttons) & mask:
                            ev.append((EV_KEY, code, 1 if b & mask else 0))
                    buttons = b
                acc_x += _s8(data[2]) * self.sensitivity
                acc_y += _s8(data[3]) * self.sensitivity
                dx, dy = int(acc_x), int(acc_y)
                acc_x -= dx
                acc_y -= dy
                if dx:
                    ev.append((EV_REL, REL_X, dx))
                if dy:
                    ev.append((EV_REL, REL_Y, dy))
                if len(data) > 4 and data[4]:
                    ev.append((EV_REL, REL_WHEEL, _s8(data[4])))
                if len(data) > 5 and data[5]:
                    ev.append((EV_REL, REL_HWHEEL, _s8(data[5])))
                if ev:
                    mouse.emit(ev)
        finally:
            os.close(fd)
