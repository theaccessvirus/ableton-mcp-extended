"""
Utility to auto-detect Ableton Live paths from its config files.
Reads ~/Library/Preferences/Ableton/Live X.X.X/Library.cfg (XML)
to find the User Library location — works regardless of whether it's
on a local drive, Dropbox, or any other cloud storage.

Vendored from GabrielTha/AbletonExporter (internal partner repo).
"""

import xml.etree.ElementTree as ET
from pathlib import Path


def _ableton_prefs_versions() -> list[Path]:
    """Return all Ableton Live version folders, newest first."""
    base = Path.home() / "Library" / "Preferences" / "Ableton"
    dirs = sorted(base.glob("Live *"), reverse=True)
    return [d for d in dirs if d.is_dir()]


def get_user_library_path() -> Path | None:
    """
    Parse Ableton's Library.cfg to find the User Library folder.
    Returns the Path if found, None otherwise.
    """
    for version_dir in _ableton_prefs_versions():
        cfg = version_dir / "Library.cfg"
        if not cfg.exists():
            continue
        try:
            tree = ET.parse(cfg)
            root = tree.getroot()
            el = root.find(".//UserLibrary/LibraryProject/ProjectPath")
            if el is not None:
                project_path = el.get("Value", "").strip()
                if project_path:
                    return Path(project_path)
        except ET.ParseError:
            continue
    return None


def get_remote_scripts_path() -> Path | None:
    """Return the Remote Scripts folder inside Ableton's User Library."""
    lib = get_user_library_path()
    if lib is None:
        return None
    return lib / "User Library" / "Remote Scripts"


def get_ableton_version() -> str | None:
    """Return the most recent Ableton Live version string (e.g. '12.2.7')."""
    dirs = _ableton_prefs_versions()
    if not dirs:
        return None
    name = dirs[0].name  # e.g. "Live 12.2.7"
    return name.replace("Live ", "")


if __name__ == "__main__":
    print("User Library :", get_user_library_path())
    print("Remote Scripts:", get_remote_scripts_path())
    print("Live version  :", get_ableton_version())
