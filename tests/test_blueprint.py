"""Unit tests for the BlueprintManager class."""

import pytest
from app.core.blueprint import BlueprintManager


def test_generate_blueprint_success():
    """Verify that a valid dictionary of packages is successfully serialized to YAML."""
    packages = {
        "dnf": ["curl", "git", "tmux"],
        "npm": ["typescript", "eslint"],
        "pipx": ["black", "poetry"],
    }
    yaml_str = BlueprintManager.generate_blueprint(packages)
    
    # Verify the generated YAML string contains the expected elements
    assert "dnf:" in yaml_str
    assert "- curl" in yaml_str
    assert "- git" in yaml_str
    assert "- tmux" in yaml_str
    assert "npm:" in yaml_str
    assert "- typescript" in yaml_str
    assert "pipx:" in yaml_str
    assert "- black" in yaml_str


def test_generate_blueprint_type_validation():
    """Verify that type errors are raised for invalid inputs in generate_blueprint."""
    # Input is not a dict
    with pytest.raises(TypeError):
        BlueprintManager.generate_blueprint(["not", "a", "dict"])  # type: ignore

    # Backend key is not a string
    with pytest.raises(TypeError):
        BlueprintManager.generate_blueprint({123: ["pkg"]})  # type: ignore

    # Package list is not a list
    with pytest.raises(TypeError):
        BlueprintManager.generate_blueprint({"dnf": "not-a-list"})  # type: ignore

    # Package list contains non-string items
    with pytest.raises(TypeError):
        BlueprintManager.generate_blueprint({"dnf": ["git", 123]})  # type: ignore


def test_parse_blueprint_success():
    """Verify that a valid YAML string is successfully parsed back to a dict."""
    yaml_str = """
dnf:
  - curl
  - git
  - tmux
npm:
  - typescript
  - eslint
"""
    parsed = BlueprintManager.parse_blueprint(yaml_str)
    assert parsed == {
        "dnf": ["curl", "git", "tmux"],
        "npm": ["typescript", "eslint"],
    }


def test_parse_blueprint_invalid_inputs():
    """Verify that invalid inputs and structures return an empty dictionary."""
    # Empty string
    assert BlueprintManager.parse_blueprint("") == {}
    assert BlueprintManager.parse_blueprint("   ") == {}

    # None or non-string inputs
    assert BlueprintManager.parse_blueprint(None) == {}  # type: ignore
    assert BlueprintManager.parse_blueprint(12345) == {}  # type: ignore

    # Invalid YAML syntax
    invalid_yaml = "dnf: [curl, git, tmux"
    assert BlueprintManager.parse_blueprint(invalid_yaml) == {}

    # Valid YAML but not a dictionary structure (e.g., a list)
    yaml_list = """
- dnf
- npm
"""
    assert BlueprintManager.parse_blueprint(yaml_list) == {}

    # Backend key is not a string (e.g. integer key in YAML)
    yaml_int_key = """
123:
  - curl
"""
    assert BlueprintManager.parse_blueprint(yaml_int_key) == {}

    # Package list is not a list
    yaml_not_list = """
dnf: curl
"""
    assert BlueprintManager.parse_blueprint(yaml_not_list) == {}

    # Package list contains non-string items
    yaml_non_string_items = """
dnf:
  - curl
  - 123
"""
    assert BlueprintManager.parse_blueprint(yaml_non_string_items) == {}


def test_round_trip():
    """Verify serialization followed by deserialization restores the original dictionary."""
    original = {
        "cargo": ["ripgrep", "fd-find"],
        "dnf": ["htop"],
    }
    yaml_str = BlueprintManager.generate_blueprint(original)
    parsed = BlueprintManager.parse_blueprint(yaml_str)
    assert parsed == original
