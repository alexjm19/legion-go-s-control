# Legion Go S Control

A [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) plugin for the **Lenovo Legion Go S** that puts the things you used to set in Handheld Daemon (hhd) or Legion Space back into the Quick Access Menu. It works on distros that use **InputPlumber**, such as Bazzite or SteamOS.

> **Tested on Bazzite only.** The tested machine is a Legion Go S 83Q2 running Bazzite `bazzite-deck` F45 with the OGC kernel `7.3.4-ogc8.1`. SteamOS and other distros/kernels are untested. The power-button LED, TDP and fan-curve paths are model/firmware-specific; the fan curve additionally enforces Lenovo's minimum safe values.

| Section | What it does |
|---|---|
| **Battery** | One toggle for **80 % protection**. It charges slowly up to 80 %, then the device runs from the charger (bypass). You can also pick Standard or Fast charging. |
| **Server mode** | Stops the device from sleeping (idle or power button) so game servers, media servers and other services keep running. |
| **Performance** | CPU boost, EPP, GPU clock cap, a **TDP slider** (PL1 = PL2 = PL3, custom platform profile) and a **10-point fan curve**. Safety minimums are on by default and can be disabled after a confirmation (then only 90 °C → 100 % is enforced). |
| **Power button LED** | Turns the power-button LED on or off. Turning it off also stops the breathing effect while asleep. |
| **Stick LEDs** | On/off, effect (solid, breathe, chroma, rainbow), colour (presets + RGB), brightness and speed. |
| **Touchpad** | Enable/disable it and switch between *relative* (plain mouse) and *absolute* (Steam trackpad) modes. |

Your settings are saved and re-applied at boot and after resume.

## How it works

The plugin never talks to the controller over hidraw, so it doesn't fight with InputPlumber. Everything goes through the sysfs files exposed by the kernel drivers:

| Feature | Driver | sysfs |
|---|---|---|
| Charge mode | `ideapad_laptop` | `/sys/class/power_supply/BAT0/charge_types` (`Fast`, `Standard`, `Long_Life`) |
| TDP | `lenovo-wmi-other` | `/sys/class/firmware-attributes/lenovo-wmi-other-0/attributes/ppt_pl{1,2,3}_*/current_value` + `lenovo-wmi-gamezone` platform profile `custom` |
| Fan curve | EC (same path as the firmware `WMAB` method) | EC window: values at `0xFE0B0A06..0F`, commit bit `0xFE0B0316` bit 6 (`/dev/mem`) |
| Power button LED | Lenovo WMI / EC | `\_SB.GZFD.WMAF` through `acpi_call`, or MMIO of `0xFE0B0300 + 0x10` bit 6 (`/dev/mem`) |
| LEDs | `hid-lenovo-go-s` | `/sys/class/leds/go_s:rgb:joystick_rings/` |
| Touchpad | `hid-lenovo-go-s` | `<hid device>/touchpad/{enabled,linux_mode}` |
| Server mode | systemd | `systemctl mask --runtime sleep.target suspend.target …` (undone automatically on reboot, when the toggle is turned off, and when the plugin is unloaded) |

### Requirements

- A kernel that includes `hid-lenovo-go-s`. This is the case for Bazzite's OGC kernel (7.3 or newer, November 2026). Check with `ls /sys/class/leds/go_s:rgb:joystick_rings`.
- Decky Loader v3 or newer. The plugin needs **root**, which it gets through the `root` flag.

If a sysfs file is missing, that section shows "Not available" instead of failing.

## Install

**From a release zip:** Decky → Settings → Developer → *Install plugin from URL*, then paste the `.zip` URL from the [latest release](https://github.com/alexjm19/legion-go-s-control/releases/latest).

**From source:**
```bash
./scripts/package.sh                       # produces out/legion-go-s-control-vX.Y.Z.zip
scp out/*.zip deck@handheld:/tmp/          # then install it from Decky (Developer → Install from zip)
```

## Notes

- The 80 % threshold and the bypass come from the Lenovo firmware (*conservation mode*). The plugin only turns the mode on. While it is active and the charger is plugged in, the battery status reads `Not charging`.
- The TDP slider writes the same value to PL1, PL2 and PL3 and switches Lenovo's platform profile to `custom` (the same mapping other Legion TDP tools use). Steam and PowerStation can also write the TDP, so if you use Steam's slider, the last writer wins. The plugin re-applies the TDP when you change it or when it loads, not on every periodic re-apply.
- The fan-curve table is written to the same EC shared-memory window that Lenovo's firmware `WMAB` method uses: ten values for 10..100 °C and a commit bit. The plugin enforces hhd's minimum safe curve and a non-decreasing curve, so a point cannot leave the fan below a safe speed. "Restore factory curve" writes an empty table and clears the commit bit, which returns control to the firmware. On uninstall the factory table is restored.
- The power-button LED is not a Linux LED-class device; it is an EC register. The plugin controls it only on a Legion Go S (DMI 83L3/83N6/83Q2/83Q3), through the official WMI method when `acpi_call` is loaded and through EC MMIO otherwise. Turning it off also disables the sleep breathing. On uninstall the LED is turned back on.
- Server mode does not keep the screen on. Steam still dims and turns off the screen; it just can't put the device to sleep.

## Fan-curve disclaimer

The fan curve is a firmware/EC setting. By default the plugin enforces Lenovo's minimum safe curve (the same values hhd uses) and a non-decreasing table. You can disable those minimums from the plugin after confirming a destructive-action warning; from then on **only the 90 °C → 100 % guard is enforced**. Custom curves are used entirely at your own risk: running the fan too low can overheat, throttle or damage the device, and the author is not responsible for any damage. Use **Apply safe minimum** or **Restore factory curve** if in doubt.

## License

BSD-3-Clause. Based on the [decky-plugin-template](https://github.com/SteamDeckHomebrew/decky-plugin-template).
