"""Package manager driver for pnpm (Node.js, global installs)."""

import asyncio
import shutil
from typing import Any
from app.core.manager import PackageManager, register_manager, describe_error


@register_manager
class PnpmManager(PackageManager):
    name: str = "pnpm"
    category: str = "Language/Dev"

    def __init__(self) -> None:
        super().__init__()
        self._pnpm_path: str | None = None
        self._shell_fallback: bool | None = None

    def is_available(self) -> bool:
        return shutil.which("pnpm") is not None

    def _resolve(self) -> str:
        if self._pnpm_path is None:
            self._pnpm_path = shutil.which("pnpm") or "pnpm"
        return self._pnpm_path

    def _needs_shell_fallback(self) -> bool:
        """Detect pnpm's shebang-less placeholder shim.

        pnpm 11+ ships its `pnpm` bin entry as a shebang-less `sh` script until
        its install script places the native binary. Interactive shells retry
        such files under `sh`, but a direct `execve` (what asyncio and Qt use)
        fails with `[Errno 8] Exec format error` — so the command works in a
        terminal yet fails from PolyGet. Detect the placeholder once per
        instance and route through `sh` explicitly via an argv list (never a
        shell string).
        """
        if self._shell_fallback is None:
            path = shutil.which("pnpm")
            needs = False
            if path:
                try:
                    with open(path, "rb") as f:
                        magic = f.read(2)
                    # Executables start with a `#!` shebang or an ELF/Mach-O
                    # magic byte; anything else (e.g. pnpm's `# ...` comment
                    # placeholder) needs the explicit `sh` hop.
                    needs = magic != b"#!" and magic[:1] != b"\x7f" and magic != b"\xcf\xfa"
                except OSError:
                    needs = False
            self._shell_fallback = needs
        return self._shell_fallback

    def _pnpm_argv(self, *args: str) -> list[str]:
        if self._needs_shell_fallback():
            return ["sh", self._resolve(), *args]
        return ["pnpm", *args]

    async def _run(self, argv: list[str], timeout: float):
        """Run argv capturing output, killing a hung child instead of hanging."""
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
            raise
        return proc, stdout

    async def check_updates(self) -> list[dict[str, Any]]:
        try:
            _, stdout = await self._run(
                self._pnpm_argv("outdated", "--global", "--format", "json"), timeout=15.0
            )
            import json
            data = json.loads(stdout.decode(errors="ignore") or "{}")
            return [{"name": name, "current": info.get("current", ""), "new": info.get("latest", "")}
                    for name, info in data.items()]
        except Exception as e:
            raise RuntimeError(f"{self.name} update check failed: {describe_error(e)}") from e

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        if packages:
            return self._pnpm_argv("add", "--global", *packages)
        return self._pnpm_argv("update", "--global")

    async def list_installed(self) -> list[str]:
        try:
            _, stdout = await self._run(
                self._pnpm_argv("list", "--global", "--depth=0", "--json"), timeout=10.0
            )
            import json
            data = json.loads(stdout.decode(errors="ignore") or "[]")
            deps = data[0].get("dependencies", {}) if data else {}
            return list(deps.keys())
        except Exception:
            return []

    def get_install_command(self, package: str) -> list[str]:
        return self._pnpm_argv("add", "--global", package)

    async def search_packages(self, query: str) -> list[dict[str, Any]]:
        # Same reasoning as Yarn — pnpm has no native search, shares npm's registry.
        try:
            _, stdout = await self._run(["npm", "search", "--json", query], timeout=15.0)
            import json
            data = json.loads(stdout.decode(errors="ignore"))
            return [{"name": i.get("name", ""), "id": i.get("name", ""),
                     "description": i.get("description", ""), "version": i.get("version", "")}
                    for i in data[:20]] if isinstance(data, list) else []
        except Exception:
            return []
