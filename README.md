# Legion Go S Control

A [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) plugin for the **Lenovo Legion Go S** that puts the things you used to set in Handheld Daemon (hhd) or Legion Space back into the Quick Access Menu. It works on distros that use **InputPlumber**, such as Bazzite or SteamOS.

| Section | What it does |
|---|---|
| **Battery** | One toggle for **80 % protection**. It charges slowly up to 80 %, then the device runs from the charger (bypass). You can also pick Standard or Fast charging. |
| **Server mode** | Stops the device from sleeping (idle or power button) so game servers, media servers and other services keep running. |
| **Stick LEDs** | On/off, effect (solid, breathe, chroma, rainbow), colour (presets + RGB), brightness and speed. |
| **Touchpad** | Enable/disable it and switch between *relative* (plain mouse) and *absolute* (Steam trackpad) modes. |

Your settings are saved and re-applied at boot and after resume.

## How it works

The plugin never talks to the controller over hidraw, so it doesn't fight with InputPlumber. Everything goes through the sysfs files exposed by the kernel drivers:

| Feature | Driver | sysfs |
|---|---|---|
| Charge mode | `ideapad_laptop` | `/sys/class/power_supply/BAT0/charge_types` (`Fast`, `Standard`, `Long_Life`) |
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
- Server mode does not keep the screen on. Steam still dims and turns off the screen; it just can't put the device to sleep.

## License

BSD-3-Clause. Based on the [decky-plugin-template](https://github.com/SteamDeckHomebrew/decky-plugin-template).
