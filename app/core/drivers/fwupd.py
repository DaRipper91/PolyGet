"""Package manager driver for fwupd (device firmware from the LVFS: UEFI, SSDs, docks, peripherals)."""

import json
import shutil
from typing import Any
from app.core.manager import DriverError, PackageManager, register_manager, run_capture

# fwupdmgr exits 2 ("nothing to do") when no device has an update.
_NOTHING_TO_DO = 2


def _devices(out: str, label: str, allow_empty: bool) -> list[dict[str, Any]]:
    if not out.strip() and allow_empty:
        return []
    try:
        data = json.loads(out)
    except ValueError as e:
        if allow_empty:
            return []
        raise DriverError(f"{label} failed: output was not valid JSON") from e
    devices = data.get("Devices", []) if isinstance(data, dict) else []
    return [d for d in devices if isinstance(d, dict)]


@register_manager
class FwupdManager(PackageManager):
    """Firmware updates through fwupd. "Packages" are devices, shown by name.

    fwupdmgr acts on device IDs, so names seen in the last update check are mapped back to IDs
    when building the upgrade command. The daemon authorizes updates through polkit itself, so
    commands are not wrapped in pkexec but still prompt for the admin password.

    Asahi note: Apple Silicon firmware is not distributed through the LVFS; on Asahi this driver
    only covers peripherals that fwupd supports.
    """

    name: str = "Firmware"
    category: str = "System"
    asks_for_password = True

    def __init__(self):
        self._device_ids: dict[str, str] = {}

    def is_available(self) -> bool:
        return shutil.which("fwupdmgr") is not None

    async def get_self_version(self) -> str | None:
        try:
            out = await run_capture(["fwupdmgr", "--version"], label=f"{self.name} version query", timeout=10.0)
        except DriverError:
            return None
        # Prints e.g. "runtime   org.freedesktop.fwupd   1.9.16" among other components.
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[1] == "org.freedesktop.fwupd":
                return f"fwupd {parts[2]}"
        return out.strip().splitlines()[0] if out.strip() else None

    async def check_updates(self) -> list[dict[str, Any]]:
        label = f"{self.name} update check"
        out = await run_capture(
            ["fwupdmgr", "get-updates", "--json", "--no-unreported-check", "--no-metadata-check"],
            label=label, timeout=60.0, ok_codes=(0, _NOTHING_TO_DO),
        )
        updates, seen = [], set()
        for dev in _devices(out, label, allow_empty=True):
            releases = [r for r in dev.get("Releases", []) if isinstance(r, dict)]
            if not releases or not dev.get("DeviceId"):
                continue
            name = dev.get("Name") or dev["DeviceId"]
            if name in seen:  # two identical devices (e.g. a pair of docks) need distinct names
                name = f"{name} ({dev['DeviceId'][:8]})"
            seen.add(name)
            self._device_ids[name] = dev["DeviceId"]
            # fwupd lists releases newest first.
            updates.append({"name": name, "current": dev.get("Version", "?"), "new": releases[0].get("Version", "?")})
        return updates

    async def list_installed_versions(self) -> dict[str, str]:
        label = f"{self.name} device query"
        out = await run_capture(["fwupdmgr", "get-devices", "--json"], label=label, timeout=30.0,
                                ok_codes=(0, _NOTHING_TO_DO))
        return {d["Name"]: d.get("Version", "") for d in _devices(out, label, allow_empty=True) if d.get("Name")}

    async def list_installed(self) -> list[str]:
        return list(await self.list_installed_versions())

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        # No --assume-yes: when firmware needs a reboot fwupdmgr asks "Restart now?", and a blanket
        # yes would reboot the machine in the middle of a batch.
        ids = [self._device_ids.get(p, p) for p in (packages or [])]
        return ["fwupdmgr", "update"] + ids

    def get_sync_command(self) -> list[str] | None:
        return ["fwupdmgr", "refresh"]
