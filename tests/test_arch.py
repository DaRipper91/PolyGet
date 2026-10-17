import json
from unittest.mock import patch

import pytest

import app.cli as cli
from app.core import arch
from app.core.catalog import CatalogEntry, load_catalog


@pytest.fixture(autouse=True)
def fresh_arch_cache():
    arch.get_machine_arch.cache_clear()
    yield
    arch.get_machine_arch.cache_clear()


def entry(**kw) -> CatalogEntry:
    base = dict(id="t", name="T", category="Language/Dev", description="", icon="", binary="t", has_driver=False)
    return CatalogEntry(**{**base, **kw})


@pytest.mark.parametrize("raw,expected", [
    ("x86_64", "x86_64"), ("AMD64", "x86_64"), ("x64", "x86_64"),
    ("aarch64", "aarch64"), ("arm64", "aarch64"), ("ARM64", "aarch64"),
    ("  aarch64\n", "aarch64"), ("riscv64", "riscv64"),
])
def test_normalize_arch_folds_aliases(raw, expected):
    assert arch.normalize_arch(raw) == expected


@pytest.mark.parametrize("machine,expected", [
    ("x86_64", "x86_64"),      # CachyOS desktop
    ("aarch64", "aarch64"),    # Asahi Linux on the M1
    ("arm64", "aarch64"),      # macOS reports the same CPU under another name
    ("", "unknown"),           # platform.machine() can return an empty string
])
def test_get_machine_arch_normalizes_what_the_platform_reports(machine, expected):
    with patch.object(arch.platform, "machine", return_value=machine):
        assert arch.get_machine_arch() == expected


def test_get_machine_arch_is_read_once():
    with patch.object(arch.platform, "machine", return_value="aarch64") as m:
        arch.get_machine_arch(); arch.get_machine_arch()
    assert m.call_count == 1


def test_describe_system_has_arch_distro_and_platform():
    with patch.object(arch.platform, "machine", return_value="aarch64"), \
         patch("app.core.distro.get_distro_family", return_value="fedora"):
        assert arch.describe_system() == {"arch": "aarch64", "distro_family": "fedora", "platform": arch.sys.platform}


def _on(machine: str, family: str):
    return patch("app.core.catalog.get_machine_arch", return_value=machine), \
           patch("app.core.catalog.get_distro_family", return_value=family)


def test_arch_qualified_install_key_beats_the_plain_family_key():
    e = entry(self_install={"fedora": ["dnf", "install", "tool"], "fedora:aarch64": ["dnf", "install", "tool-arm"]})
    for machine, expected in (("aarch64", ["dnf", "install", "tool-arm"]), ("x86_64", ["dnf", "install", "tool"])):
        m, f = _on(machine, "fedora")
        with m, f:
            assert e.get_self_install_command() == expected


def test_plain_family_key_still_works_when_no_arch_key_exists():
    e = entry(self_install={"arch": ["pacman", "-S", "tool"]})
    m, f = _on("aarch64", "arch")
    with m, f:
        assert e.get_self_install_command() == ["pacman", "-S", "tool"]


def test_entry_that_excludes_this_architecture_offers_no_install_command():
    e = entry(arch=["x86_64"], self_install={"fedora": ["dnf", "install", "tool"]})
    m, f = _on("aarch64", "fedora")
    with m, f:
        assert not e.supports_this_arch()
        assert e.get_self_install_command() is None


def test_unspecified_arch_means_assumed_supported_not_verified():
    m, f = _on("aarch64", "fedora")
    with m, f:
        assert entry().supports_this_arch()


def test_listed_arch_aliases_match_the_normalized_machine():
    m, f = _on("aarch64", "fedora")
    with m, f:
        assert entry(arch=["arm64"]).supports_this_arch()
        assert entry(arch=["AMD64", "arm64"]).supports_this_arch()
        assert not entry(arch=["amd64"]).supports_this_arch()


def test_real_catalog_loads_with_the_new_optional_field():
    entries = load_catalog()
    assert len(entries) >= 37
    assert all(isinstance(e.arch, list) for e in entries)


def run_json(capsys, *argv):
    code = cli.main(["--json", *argv])
    return code, json.loads(capsys.readouterr().out)


def test_cli_system_reports_detected_arch(capsys):
    with patch.object(arch.platform, "machine", return_value="arm64"):
        code, data = run_json(capsys, "system")
    assert code == cli.EXIT_OK
    assert data["arch"] == "aarch64" and {"distro_family", "platform"} <= set(data)


def test_cli_catalog_flags_entries_unsupported_on_this_arch(capsys):
    fake = [entry(id="only-x86", name="X", arch=["x86_64"]), entry(id="anywhere", name="A")]
    with patch("app.core.catalog.load_catalog", return_value=fake), \
         patch("app.core.catalog.get_machine_arch", return_value="aarch64"):
        code, rows = run_json(capsys, "catalog")
    flags = {r["id"]: r["supported_on_this_arch"] for r in rows}
    assert code == cli.EXIT_OK and flags == {"only-x86": False, "anywhere": True}
