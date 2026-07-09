"""Package manager driver implementations.

Importing this module auto-discovers and registers every driver module in this package,
so adding a new driver file here is sufficient - no manual import needed.
"""
import importlib
import pkgutil

# Iterate over and import all modules inside this package directory to trigger registration decorators
for _, module_name, _ in pkgutil.iter_modules(__path__):
    importlib.import_module(f"{__name__}.{module_name}")
