"""Model check shared by the EC-backed features.

The power-button LED and the fan-curve table live in Lenovo EC registers whose
layout is only known to be correct on the Legion Go S. Writing them on another
machine could touch unrelated hardware, so both modules refuse to run unless
DMI says this is a Go S.
"""

DMI_PRODUCTS = {"83L3", "83N6", "83Q2", "83Q3"}


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def is_legion_go_s():
    product = _read("/sys/class/dmi/id/product_name") or ""
    version = _read("/sys/class/dmi/id/product_version") or ""
    return product in DMI_PRODUCTS or "legion go s" in version.lower()
