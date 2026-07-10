"""
Keystroke-driven 'Save Live Set As' for the currently open Ableton project.

Strategy:
  Cmd+Shift+S → wait for Save dialog
  Cmd+Shift+G → wait for Go-to-folder sheet
  Set folder path text field via AppleScript → Enter
  Set filename text field via AppleScript → Enter
  Verify the title via HTTPBridge /song/name

Uses CGEventPostToPid (via export_automation._key) so Ableton stays
backgrounded — no focus steal.
"""

import os
import subprocess
import time

from ..exporter import export_automation as ea
from . import _http


KEY_S = 1


def _osascript(script: str, timeout: float = 15.0) -> str:
    r = subprocess.run(["osascript", "-e", script],
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip())
    return r.stdout.strip()


def _set_goto_path(path: str) -> str:
    """Fill the macOS 'Go to Folder' sheet text field with `path`."""
    safe = path.replace('"', '\\"')
    script = f"""
tell application "System Events"
    tell process "Live"
        set _target to missing value
        repeat 30 times
            try
                set _target to sheet 1 of window 1
                exit repeat
            end try
            try
                set _target to window "Go to Folder"
                exit repeat
            end try
            delay 0.15
        end repeat
        if _target is missing value then return "no-sheet"
        try
            set value of text field 1 of _target to "{safe}"
            return "ok-text"
        end try
        try
            set value of combo box 1 of _target to "{safe}"
            return "ok-combo"
        end try
        return "no-field"
    end tell
end tell
"""
    return _osascript(script)


def _set_save_filename(filename: str) -> str:
    """Fill the save panel's filename text field with `filename`."""
    safe = filename.replace('"', '\\"')
    script = f"""
tell application "System Events"
    tell process "Live"
        set _panel to missing value
        repeat 30 times
            try
                set _panel to window 1
                if name of _panel contains "Save" then exit repeat
            end try
            delay 0.15
        end repeat
        if _panel is missing value then return "no-panel"
        try
            set value of text field 1 of _panel to "{safe}"
            return "ok"
        on error
            try
                set value of text field 1 of group 1 of _panel to "{safe}"
                return "ok-group"
            end try
        end try
        return "no-field"
    end tell
end tell
"""
    return _osascript(script)


def save_project_as(folder: str, name: str, dialog_timeout: float = 15.0,
                    verify_via_bridge: bool = True) -> dict:
    """
    Save the currently open Ableton project to <folder>/<name> Project/<name>.als
    via Cmd+Shift+S keystroke automation. Ableton stays in the background.

    Parameters:
    - folder: Destination folder (~ expanded; created if missing)
    - name: Project name (with or without .als suffix; .als is stripped if present)
    - dialog_timeout: Seconds to wait for the save dialog to appear
    - verify_via_bridge: If True, GET /song/name after save to confirm the title

    Returns:
    - status: "ok" | "error" | "warning"
    - project_dir, project_path, song_name (when status == "ok")
    """
    pid = ea.get_ableton_pid()
    folder = os.path.expanduser(folder)
    os.makedirs(folder, exist_ok=True)
    base_name = name[:-4] if name.lower().endswith(".als") else name

    # Step 1: open Save As
    ea._key(pid, KEY_S, ea._CMD_SHIFT)
    if not ea._wait_for_window_containing("Save", timeout=dialog_timeout):
        return {"status": "error", "message": "Save dialog did not appear"}
    time.sleep(0.5)

    # Step 2: Cmd+Shift+G → Go to Folder
    ea._key(pid, ea._KEY_G, ea._CMD_SHIFT)
    time.sleep(0.8)

    # Step 3: type folder path into Go-to-folder sheet, then Enter
    goto_result = _set_goto_path(folder)
    if "ok" not in goto_result:
        return {"status": "error", "message": f"Could not fill go-to-folder sheet: {goto_result}"}
    time.sleep(0.3)
    ea._key(pid, ea._KEY_RET, 0)
    time.sleep(1.0)  # navigation + focus return to filename field

    # Step 4: type filename, Enter
    fname_result = _set_save_filename(base_name)
    if "ok" not in fname_result:
        return {"status": "error", "message": f"Could not fill filename field: {fname_result}"}
    time.sleep(0.3)
    ea._key(pid, ea._KEY_RET, 0)
    time.sleep(2.0)  # save dialog to dismiss + project rename to settle

    project_dir = os.path.join(folder, f"{base_name} Project")
    project_path = os.path.join(project_dir, f"{base_name}.als")

    if not verify_via_bridge:
        return {"status": "ok", "project_dir": project_dir, "project_path": project_path,
                "song_name": base_name}

    # Step 5: verify via HTTPBridge
    try:
        sn = _http.get("/song/name", timeout=5.0)
        verified = sn.get("result", "")
        if base_name.lower() not in verified.lower():
            return {"status": "warning", "message": f"Save may not have completed — expected '{base_name}' in song name, got '{verified}'",
                    "project_dir": project_dir, "project_path": project_path,
                    "song_name": verified}
        return {"status": "ok", "project_dir": project_dir, "project_path": project_path,
                "song_name": verified}
    except Exception as e:
        return {"status": "warning", "message": f"Save fired but bridge verify failed: {e}",
                "project_dir": project_dir, "project_path": project_path,
                "song_name": base_name}
