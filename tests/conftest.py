from unittest.mock import AsyncMock, patch

import pytest


class ScriptedExec:
    """Stand-in for asyncio.create_subprocess_exec that answers by matching the joined argv.

    Rules are checked in the order added; an unmatched command raises FileNotFoundError,
    which is what a missing binary does, so tests fail loudly on unexpected calls.
    """

    def __init__(self) -> None:
        self.rules: list[tuple[str, bytes, int, bytes]] = []
        self.calls: list[tuple[list[str], dict]] = []

    def add(self, needle: str, stdout: bytes | str = b"", rc: int = 0, stderr: bytes | str = b"") -> None:
        enc = lambda v: v.encode() if isinstance(v, str) else v
        self.rules.append((needle, enc(stdout), rc, enc(stderr)))

    async def __call__(self, *argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        joined = " ".join(str(a) for a in argv)
        for needle, stdout, rc, stderr in self.rules:
            if needle in joined:
                proc = AsyncMock()
                proc.returncode = rc
                proc.communicate.return_value = (stdout, stderr)
                return proc
        raise FileNotFoundError(argv[0])


@pytest.fixture
def scripted_exec():
    script = ScriptedExec()
    with patch("asyncio.create_subprocess_exec", script):
        yield script
