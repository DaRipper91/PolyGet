import asyncio

import pytest

from app.core.manager import DriverError, fetch_json, run_capture


def test_run_capture_returns_stdout(scripted_exec):
    scripted_exec.add("echo", stdout="hello\n")
    assert asyncio.run(run_capture(["echo", "hi"], label="t")) == "hello\n"


def test_run_capture_bad_status_raises_with_stderr_detail(scripted_exec):
    scripted_exec.add("tool", rc=3, stderr="boom: registry down\nmore")
    with pytest.raises(DriverError, match=r"t failed: `tool` exited with status 3: boom: registry down"):
        asyncio.run(run_capture(["tool"], label="t"))


def test_run_capture_ok_codes_accept_nonzero(scripted_exec):
    scripted_exec.add("tool", stdout="x", rc=1)
    assert asyncio.run(run_capture(["tool"], label="t", ok_codes=(0, 1))) == "x"


def test_run_capture_missing_binary_is_driver_error(scripted_exec):
    with pytest.raises(DriverError, match="FileNotFoundError|failed"):
        asyncio.run(run_capture(["nope"], label="t"))


def test_run_capture_passes_cwd(scripted_exec):
    scripted_exec.add("tool", stdout="")
    asyncio.run(run_capture(["tool"], label="t", cwd="/some/dir"))
    assert scripted_exec.calls[0][1]["cwd"] == "/some/dir"


def test_fetch_json_parses_and_rejects_garbage(scripted_exec):
    scripted_exec.add("good.example", stdout='{"a": 1}')
    scripted_exec.add("bad.example", stdout="<html>")
    assert asyncio.run(fetch_json("https://good.example/x", label="t")) == {"a": 1}
    with pytest.raises(DriverError, match="not valid JSON"):
        asyncio.run(fetch_json("https://bad.example/x", label="t"))
