# PolyGet

A PySide6-based graphical software store and package upgrader designed to query, install, and perform package upgrades across multiple system and development package managers (DNF, Flatpak, NPM, Pipx, Cargo) in a single unified interface.


## Project Structure
- `run.py`: Entry point launcher.
- `requirements.txt`: Python package requirements.
- `app/`: Source package.
  - `core/`: Reusable package manager drivers and base class (adapted from `upgrader-tui`).
  - `ui/`: PySide6 window layouts, styling, and thread workers.

## Environment Setup
To setup a local virtual environment:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```
