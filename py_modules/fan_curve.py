"""Firmware fan curve for the Lenovo Legion Go S.

The ten-point table lives in the EC, not in a hwmon device. From the DSDT:

* EC shared-memory window (``SMA2``, SystemMemory 0xFE0B0A00):
  ``F9F0``..``F9F9`` at offsets 6..15 hold the fan values for 10..100 °C.
* ``CMFT`` is ERAM 0xFE0B0316 bit 6; setting it commits a new table.

The kernel in this image does not ship ``lenovo-wmi-fan-method``, and there is
no ``acpi_call``, so the table is written through the EC window with
``/dev/mem`` exactly like the firmware's own ``WMAB`` method does. The method
writes the ten bytes with 2 ms between them and sets ``CMFT`` last; this module
mirrors that sequence.

The values are 0..115 in the firmware; 0..100 is used here because 115 is
Lenovo's "full speed" ceiling. The manufacturer's minimum curve is enforced so
a mistyped point cannot leave the fan below a safe speed, and the table is
forced to be non-decreasing with temperature.
"""

import mmap
import os
import time

from legion import is_legion_go_s

BASE = 0xFE0B0000
SIZE = 0x1000
SMA2_OFFSET = 0xA00
CURVE_OFFSET = 6
POINTS = 10
ERAM_OFFSET = 0x300
CMFT_OFFSET = 0x16
CMFT_BIT = 6
MAX_VALUE = 100
TEMPERATURES = (10, 20, 30, 40, 50, 60, 70, 80, 90, 100)

# hhd's minimum safe curve for Lenovo handhelds, in the same 0..100 scale.
MIN_CURVE = (44, 48, 55, 60, 71, 79, 87, 87, 100, 100)


class FanCurve:
    """Write/read the Legion Go S firmware fan curve through EC MMIO."""

    def __init__(self, log):
        self.log = log
        self._mm = None
        self._fd = None
        self._checked = False

    # ------------------------------------------------------------- mapping
    def _open(self):
        if self._mm is not None:
            return True
        fd = None
        mm = None
        try:
            fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
            mm = mmap.mmap(
                fd,
                SIZE,
                mmap.MAP_SHARED,
                mmap.PROT_READ | mmap.PROT_WRITE,
                offset=BASE,
            )
            # Read test before keeping the mapping.
            _ = mm[SMA2_OFFSET + CURVE_OFFSET]
            _ = mm[ERAM_OFFSET + CMFT_OFFSET]
            self._fd, self._mm = fd, mm
            return True
        except (OSError, ValueError) as e:
            self.log.error(f"fan curve: cannot map EC window: {e}")
            if mm is not None:
                try:
                    mm.close()
                except (BufferError, ValueError):
                    pass
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            return False

    def available(self):
        if not self._checked:
            self._checked = True
            if not is_legion_go_s():
                self.log.info("fan curve: not a Legion Go S, leaving it alone")
                return False
            if not self._open():
                return False
            self.log.info("fan curve: using EC MMIO")
        return self._mm is not None

    # ------------------------------------------------------------- state
    def _points(self):
        start = SMA2_OFFSET + CURVE_OFFSET
        return list(self._mm[start:start + POINTS])

    def _active(self):
        return ((self._mm[ERAM_OFFSET + CMFT_OFFSET] >> CMFT_BIT) & 1) == 1

    def _set_active(self, active):
        addr = ERAM_OFFSET + CMFT_OFFSET
        current = self._mm[addr]
        mask = 1 << CMFT_BIT
        self._mm[addr] = (current | mask) if active else (current & ~mask)

    def state(self):
        if not self.available():
            return {"available": False}
        return {
            "available": True,
            "active": self._active(),
            "points": self._points(),
            "temperatures": list(TEMPERATURES),
            "min": list(MIN_CURVE),
            "max": MAX_VALUE,
        }

    # ------------------------------------------------------------- apply
    @staticmethod
    def sanitize(points):
        """Enforce length, range, safety minimum and monotonic increase."""
        if not points or len(points) != POINTS:
            return None
        try:
            values = [int(v) for v in points]
        except (TypeError, ValueError):
            return None
        result, previous = [], 0
        for i, value in enumerate(values):
            value = max(MIN_CURVE[i], min(MAX_VALUE, value))
            value = max(previous, value)
            result.append(value)
            previous = value
        return result

    def apply(self, points):
        values = self.sanitize(points)
        if values is None:
            self.log.warning("fan curve: invalid curve, not writing")
            return None
        if not self.available():
            return None
        start = SMA2_OFFSET + CURVE_OFFSET
        for i, value in enumerate(values):
            self._mm[start + i] = value
            time.sleep(0.002)
        self._set_active(True)
        time.sleep(0.05)
        readback = self._points()
        if readback != values or not self._active():
            self.log.error(f"fan curve: write did not stick (read {readback})")
            return None
        self.log.info(f"fan curve: applied {values}")
        return values

    def reset(self):
        """Return control to the firmware default table."""
        if not self.available():
            return False
        start = SMA2_OFFSET + CURVE_OFFSET
        for i in range(POINTS):
            self._mm[start + i] = 0
            time.sleep(0.002)
        self._set_active(False)
        time.sleep(0.05)
        if any(self._points()) or self._active():
            self.log.error("fan curve: could not restore the factory table")
            return False
        self.log.info("fan curve: restored the factory table")
        return True

    def close(self):
        if self._mm is not None:
            try:
                self._mm.close()
            except (BufferError, ValueError):
                pass
            self._mm = None
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        self._checked = False
