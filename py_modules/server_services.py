"""Background services that only run in server mode.

A handheld is a console first: when server mode is off, the configured services
are stopped (RAM freed); while a game is running they can be frozen with the
cgroup freezer (``systemctl freeze``), so the game gets the whole CPU, and
thawed when it exits.

Two kinds of entries, both optional and skipped when absent on the system:

* ``units``: system units, e.g. ``hermes.service`` (a Podman Quadlet).
* ``users``: service accounts whose whole user manager (``user@UID.service``,
  rootless containers included) is stopped/frozen with them.

Nothing here touches units that are not listed in the settings.
"""

import pwd
import subprocess

TIMEOUT_S = 20


def _systemctl(*args):
    try:
        r = subprocess.run(
            ["systemctl", *args], capture_output=True, text=True, timeout=TIMEOUT_S
        )
    except subprocess.TimeoutExpired:
        return None
    return r


class ServerServices:
    def __init__(self, logger):
        self.log = logger
        self.game_running = False

    # ------------------------------------------------------------ discovery
    @staticmethod
    def _targets(cfg):
        """[(unit, label)] for the configured entries that exist here."""
        out = []
        for unit in (cfg or {}).get("units") or []:
            r = _systemctl("show", "-p", "LoadState", "--value", unit)
            if r and r.stdout.strip() == "loaded":
                out.append((unit, unit.removesuffix(".service")))
        for user in (cfg or {}).get("users") or []:
            try:
                uid = pwd.getpwnam(user).pw_uid
            except KeyError:
                continue
            out.append((f"user@{uid}.service", user))
        return out

    @staticmethod
    def _status(unit):
        r = _systemctl("show", "-p", "ActiveState", "-p", "FreezerState", unit)
        props = {}
        for line in (r.stdout if r else "").splitlines():
            k, _, v = line.partition("=")
            props[k] = v
        return props.get("ActiveState", "unknown"), props.get("FreezerState", "running")

    def _run(self, *args):
        r = _systemctl(*args)
        if r is None or r.returncode != 0:
            err = r.stderr.strip() if r else "timeout"
            self.log.error(f"systemctl {' '.join(args)} failed: {err}")
            return False
        return True

    # ------------------------------------------------------------ apply
    def apply(self, cfg, server_on, start=False):
        """Bring the services in line with server mode and the game state.

        ``start`` is only set on an explicit change (toggle, plugin load): the
        periodic re-apply never starts anything, so a unit that keeps failing
        is not restarted every few seconds.
        """
        pause = bool((cfg or {}).get("pause_in_game", True)) and self.game_running
        for unit, _ in self._targets(cfg):
            active, freezer = self._status(unit)
            frozen = freezer != "running"
            if not server_on:
                if frozen:
                    self._run("thaw", unit)
                if active in ("active", "activating", "reloading"):
                    self.log.info(f"server mode off: stopping {unit}")
                    self._run("stop", "--no-block", unit)
                continue
            if start and active in ("inactive", "failed"):
                self.log.info(f"server mode on: starting {unit}")
                self._run("start", "--no-block", unit)
                active = "activating"
            if active not in ("active", "activating", "reloading"):
                continue
            if pause and not frozen:
                self.log.info(f"game running: freezing {unit}")
                self._run("freeze", unit)
            elif not pause and frozen:
                self.log.info(f"no game: thawing {unit}")
                self._run("thaw", unit)

    def thaw_all(self, cfg):
        for unit, _ in self._targets(cfg):
            if self._status(unit)[1] != "running":
                self._run("thaw", unit)

    def state(self, cfg):
        items = []
        for unit, label in self._targets(cfg):
            active, freezer = self._status(unit)
            items.append({
                "unit": unit,
                "label": label,
                "active": active,
                "frozen": freezer != "running",
            })
        return {
            "available": bool(items),
            "items": items,
            "game_running": self.game_running,
            "pause_in_game": bool((cfg or {}).get("pause_in_game", True)),
        }
