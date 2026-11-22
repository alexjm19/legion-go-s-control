"""Power-button LED for the Lenovo Legion Go S.

Unlike the stick rings, this LED is not a Linux LED-class device: it lives in
the embedded controller. On the Go S the state is bit 6 of EC RAM 0x10
(``LPBL`` in the DSDT) and it is active low (0 = LED on, 1 = LED off).
EC RAM 0x58 bit 0 (``LEDM``) controls the breathing effect while asleep.

Two access paths, in this order:

1. ``\\_SB.GZFD.WMAF`` via ``acpi_call`` (the official Lenovo WMI method).
2. MMIO of the ECMM/ERAM window at 0xFE0B0300 with ``/dev/mem``.

The registers are only touched on a Legion Go S (DMI 83L3/83N6/83Q2/83Q3),
because writing the wrong EC byte on another machine would be a bad idea.
"""

import mmap
import os

from legion import is_legion_go_s

# EC RAM, ECMM/ERAM window (same on Legion Go and Legion Go S).
ECMM_BASE = 0xFE0B0300
ECMM_SIZE = 0x100
POWER_LED_OFFSET = 0x10
POWER_LED_BIT = 6
LED_MODE_OFFSET = 0x58
LED_MODE_BIT = 0

# Lenovo WMI method used by Legion Space / hhd.
WMI_PATH = r"\_SB.GZFD.WMAF"
LIGHTING_ID = 0x04
LED_MODE_ID = 0x24


def _parse_acpi_state(raw):
    """Parse the buffer returned by the WMAF get command.

    acpi_call returns either ``{0x01, 0x02, ...}`` or a little-endian integer
    like ``0x0002...``. Byte 1 is 0x02 when the LED is on and 0x01 when off.
    """
    if not raw:
        return None
    cleaned = raw.strip("\x00").strip()
    try:
        if cleaned.startswith("{"):
            parts = cleaned.strip("{}").split(",")
            if len(parts) < 2:
                return None
            state = int(parts[1].strip(), 0)
        elif cleaned.lower().startswith("0x"):
            state = (int(cleaned, 16) >> 8) & 0xFF
        else:
            return None
        return state == 0x02
    except (TypeError, ValueError):
        return None


class PowerLED:
    """On/off control for the Legion Go S power-button LED."""

    def __init__(self, log):
        self.log = log
        self.backend = None
        self._checked = False
        self._mm = None
        self._fd = None
        self._page_offset = 0

    # ------------------------------------------------------------- detection
    def available(self):
        if not self._checked:
            self._checked = True
            if not is_legion_go_s():
                self.log.info("power LED: not a Legion Go S, leaving it alone")
                return False
            if os.path.exists("/proc/acpi/call"):
                state = self._acpi_get()
                if state is not None:
                    self.backend = "acpi_call"
                    self.log.info("power LED: using acpi_call")
                    return True
                self.log.info("power LED: acpi_call present but no state, trying MMIO")
            if self._mmio_open():
                self.backend = "mmio"
                self.log.info("power LED: using EC MMIO")
                return True
            self.log.warning("power LED: no usable backend")
        return self.backend is not None

    # ------------------------------------------------------------- ACPI call
    def _acpi(self, command):
        try:
            with open("/proc/acpi/call", "w") as f:
                f.write(command)
            with open("/proc/acpi/call") as f:
                return f.read().strip()
        except OSError as e:
            self.log.error(f"power LED: acpi_call failed: {e}")
            return None

    def _acpi_get(self):
        raw = self._acpi(f"{WMI_PATH} 0 0x01 0x{LIGHTING_ID:02X}")
        return _parse_acpi_state(raw)

    def _acpi_set(self, enabled):
        brightness = 0x02 if enabled else 0x01
        if self._acpi(
            f"{WMI_PATH} 0 0x02 {{0x{LIGHTING_ID:02X}, 0x00, 0x{brightness:02X}}}"
        ) is None:
            return False
        # Keep the LED off while asleep when the user turns it off, and restore
        # the default breathing when it is turned back on.
        mode = 0x03 if enabled else 0x01
        self._acpi(
            f"{WMI_PATH} 0 0x02 {{0x{LED_MODE_ID:02X}, 0x00, 0x{mode:02X}}}"
        )
        return self._acpi_get() == enabled

    # ------------------------------------------------------------- MMIO / EC
    def _mmio_open(self):
        if self._mm is not None:
            return True
        try:
            page = mmap.PAGESIZE
            self._page_offset = ECMM_BASE % page
            base = ECMM_BASE - self._page_offset
            self._fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
            self._mm = mmap.mmap(
                self._fd,
                self._page_offset + ECMM_SIZE,
                mmap.MAP_SHARED,
                mmap.PROT_READ | mmap.PROT_WRITE,
                offset=base,
            )
            # Read test: fails on kernels that restrict EC MMIO.
            _ = self._mm[self._page_offset + POWER_LED_OFFSET]
            return True
        except (OSError, ValueError) as e:
            self.log.error(f"power LED: cannot map EC MMIO: {e}")
            self._mmio_close()
            return False

    def _mmio_close(self):
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

    def _mmio_get(self):
        if not self._mmio_open():
            return None
        value = self._mm[self._page_offset + POWER_LED_OFFSET]
        return ((value >> POWER_LED_BIT) & 1) == 0

    def _mmio_set(self, enabled):
        if not self._mmio_open():
            return False
        try:
            addr = self._page_offset + POWER_LED_OFFSET
            current = self._mm[addr]
            mask = 1 << POWER_LED_BIT
            new = (current & ~mask) if enabled else (current | mask)
            if new != current:
                self._mm[addr] = new
            if ((self._mm[addr] >> POWER_LED_BIT) & 1) != ((new >> POWER_LED_BIT) & 1):
                self.log.error(
                    f"power LED: EC write did not stick "
                    f"(0x{current:02X} -> 0x{new:02X}, read 0x{self._mm[addr]:02X})"
                )
                return False

            mode_addr = self._page_offset + LED_MODE_OFFSET
            mode = self._mm[mode_addr]
            mode_mask = 1 << LED_MODE_BIT
            new_mode = (mode & ~mode_mask) if enabled else (mode | mode_mask)
            if new_mode != mode:
                self._mm[mode_addr] = new_mode
            self.log.info(
                f"power LED: {'on' if enabled else 'off'} "
                f"(EC[0x{POWER_LED_OFFSET:02X}]=0x{self._mm[addr]:02X}, "
                f"EC[0x{LED_MODE_OFFSET:02X}]=0x{self._mm[mode_addr]:02X})"
            )
            return True
        except (OSError, ValueError) as e:
            self.log.error(f"power LED: EC write failed: {e}")
            return False

    # ------------------------------------------------------------- public API
    def state(self):
        """Return True if the LED is on, False if off, None if unavailable."""
        if not self.available():
            return None
        if self.backend == "acpi_call":
            state = self._acpi_get()
            if state is not None:
                return state
            # acpi_call died (module unloaded?); fall back to MMIO.
            if self._mmio_open():
                self.backend = "mmio"
            else:
                return None
        return self._mmio_get()

    def apply(self, enabled):
        """Set the LED on/off. None means leave it alone."""
        if enabled is None:
            return True
        if not self.available():
            return False
        if self.backend == "acpi_call":
            if self._acpi_set(bool(enabled)):
                return True
            self.log.warning("power LED: acpi_call set failed, falling back to MMIO")
            if not self._mmio_open():
                return False
            self.backend = "mmio"
        return self._mmio_set(bool(enabled))

    def close(self):
        self._mmio_close()
        self.backend = None
        self._checked = False
