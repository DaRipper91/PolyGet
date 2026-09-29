"""PolyGet settings — alias maps, UI preferences, and scan policies."""

import json
from pathlib import Path
from typing import Any

_SETTINGS_PATH = Path.home() / ".config" / "polyget" / "settings.json"


class SettingsStore:
    """JSON-backed settings store with versioned schema."""

    SCHEMA_VERSION = 1

    def __init__(self, path: Path = _SETTINGS_PATH) -> None:
        self._path = path
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return self._defaults()
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            # Migration if needed
            if data.get("schema_version", 0) < self.SCHEMA_VERSION:
                data = self._migrate(data)
            return data
        except Exception:
            return self._defaults()

    def _defaults(self) -> dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "alias_map": {},  # { "normalized_name": { "NPM": "pkg1", "Pacman": "pkg2" } }
            "version_scan": {
                "include_ignored": False,
                "show_suppressed": False,
                "strict_matching": True,  # exact normalized-name only, no aliases
                # Distro-vs-runtime version comparisons span two independent version
                # schemes and can be wrong (Arch ships protobuf 36.1, the Ruby gem is
                # 4.36.1 — same release, different numbering). Set False to restrict
                # results to managers that share a version scheme.
                "include_cross_ecosystem": True,
                # Extra manager pairs whose version numbers are not reliably
                # comparable, as [[managerA, managerB], ...]. Pairs known to be bad are
                # already excluded in code (RubyGems vs any distro, npm/pnpm/yarn vs
                # each other); add entries here for pairs you hit in the wild instead
                # of waiting for a code change.
                "untrusted_pairs": [],
            },
            "ui": {
                "show_version_check_badge": True,
                "compact_mode": False,
            },
        }

    def _migrate(self, data: dict[str, Any]) -> dict[str, Any]:
        defaults = self._defaults()
        # Merge missing keys from defaults
        for key, value in defaults.items():
            if key not in data:
                data[key] = value
            elif isinstance(value, dict) and isinstance(data.get(key), dict):
                for sub_key, sub_value in value.items():
                    if sub_key not in data[key]:
                        data[key][sub_key] = sub_value
        data["schema_version"] = self.SCHEMA_VERSION
        return data

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")

    # --- Accessors ---

    def get(self, key: str, default: Any = None) -> Any:
        """Get a nested key using dot notation (e.g., 'version_scan.strict_matching')."""
        parts = key.split(".")
        cur = self._data
        for part in parts:
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return default
        return cur

    def set(self, key: str, value: Any) -> None:
        """Set a nested key using dot notation."""
        parts = key.split(".")
        cur = self._data
        for part in parts[:-1]:
            if part not in cur:
                cur[part] = {}
            cur = cur[part]
        cur[parts[-1]] = value
        self._save()

    # --- Alias map helpers ---

    def get_alias_map(self) -> dict[str, dict[str, str]]:
        """Return the alias map: {normalized_name: {manager: actual_name}}."""
        return self._data.get("alias_map", {})

    def set_alias(self, normalized_name: str, manager: str, actual_name: str) -> None:
        """Add an alias mapping for a package name on a specific manager."""
        alias_map = self._data.setdefault("alias_map", {})
        if normalized_name not in alias_map:
            alias_map[normalized_name] = {}
        alias_map[normalized_name][manager] = actual_name
        self._save()

    def remove_alias(self, normalized_name: str, manager: str | None = None) -> None:
        """Remove an alias. If manager is None, remove the entire normalized_name entry."""
        alias_map = self._data.get("alias_map", {})
        if normalized_name in alias_map:
            if manager is None:
                del alias_map[normalized_name]
            elif manager in alias_map[normalized_name]:
                del alias_map[normalized_name][manager]
                if not alias_map[normalized_name]:
                    del alias_map[normalized_name]
            self._save()

    def resolve_name(self, manager: str, actual_name: str) -> str:
        """Resolve an actual package name to its normalized form (for matching).

        Checks the alias map first; if the actual_name is an alias target for the
        given manager, returns the normalized key. Otherwise returns the
        standard normalized form (lowercase + prefix strip).
        """
        from app.core.version_scan import _normalize_name

        alias_map = self.get_alias_map()
        for norm_name, managers in alias_map.items():
            if managers.get(manager) == actual_name:
                return norm_name
        return _normalize_name(actual_name)

    def reverse_resolve(self, normalized_name: str, manager: str) -> str | None:
        """Given a normalized name, return the actual name for a specific manager if aliased."""
        alias_map = self.get_alias_map()
        if normalized_name in alias_map and manager in alias_map[normalized_name]:
            return alias_map[normalized_name][manager]
        return None

    # --- Version scan settings ---

    def get_version_scan_settings(self) -> dict[str, Any]:
        return self._data.get("version_scan", self._defaults()["version_scan"])

    def set_version_scan_setting(self, key: str, value: Any) -> None:
        self.set(f"version_scan.{key}", value)

    # --- UI settings ---

    def get_ui_settings(self) -> dict[str, Any]:
        return self._data.get("ui", self._defaults()["ui"])

    def set_ui_setting(self, key: str, value: Any) -> None:
        self.set(f"ui.{key}", value)


# Global instance for convenience
_settings_instance: SettingsStore | None = None


def get_settings() -> SettingsStore:
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = SettingsStore()
    return _settings_instance