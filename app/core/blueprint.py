"""Declarative blueprint module for serializing and deserializing package lists across backends."""

from typing import Dict, List
import yaml


class BlueprintManager:
    """Manager class for serializing and deserializing package blueprints."""

    @staticmethod
    def generate_blueprint(installed_packages: dict[str, list[str]]) -> str:
        """Serialize package lists across backends to a clean YAML string.

        Args:
            installed_packages (dict[str, list[str]]): A dictionary mapping backend names
                to lists of package names.

        Returns:
            str: A clean YAML string representation.
        """
        if not isinstance(installed_packages, dict):
            raise TypeError("installed_packages must be a dictionary")

        # Clean/standardize input to ensure it is structured correctly
        cleaned: dict[str, list[str]] = {}
        for backend, packages in installed_packages.items():
            if not isinstance(backend, str):
                raise TypeError("Backend keys must be strings")
            if not isinstance(packages, list):
                raise TypeError("Package lists must be lists of strings")
            if not all(isinstance(p, str) for p in packages):
                raise TypeError("Package lists must contain only strings")
            cleaned[backend] = list(packages)

        return yaml.safe_dump(cleaned, default_flow_style=False, sort_keys=True)

    @staticmethod
    def parse_blueprint(content: str) -> dict[str, list[str]]:
        """Deserialize a YAML string back to a dictionary of package lists per backend.

        Handles parsing exceptions and structural invalidity gracefully by returning an
        empty dictionary.

        Args:
            content (str): The YAML string content to parse.

        Returns:
            dict[str, list[str]]: Dictionary mapping backend names to package lists.
        """
        if not content or not isinstance(content, str) or not content.strip():
            return {}

        try:
            data = yaml.safe_load(content)
            if not isinstance(data, dict):
                return {}

            sanitized: dict[str, list[str]] = {}
            for backend, packages in data.items():
                if not isinstance(backend, str):
                    return {}
                if not isinstance(packages, list):
                    return {}
                if not all(isinstance(p, str) for p in packages):
                    return {}
                sanitized[backend] = list(packages)

            return sanitized
        except Exception:
            return {}
