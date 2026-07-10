"""
macOS-native Ableton Live export automation.

Vendored from GabrielTha/AbletonExporter (internal partner repo).

Approach: let Ableton's save panel save to its default location with a UUID-tagged
filename, wait for the render to finish, then locate and move the file to the
user-specified output folder. This sidesteps the fragility of programmatically
navigating the NSSavePanel directory chooser across keyboard layouts and Live
versions, while still giving the user the file in the right place.
"""

import ctypes
import ctypes.util
import os
import shutil
import subprocess
import time
import uuid

import Quartz

# macOS virtual key codes
_KEY_R   = 15
_KEY_G   = 5
_KEY_A   = 0
_KEY_V   = 9
_KEY_RET = 36   # Return / Enter

# Modifier masks
_CMD       = Quartz.kCGEventFlagMaskCommand
_SHIFT     = Quartz.kCGEventFlagMaskShift
_CMD_SHIFT = _CMD | _SHIFT

# Load ApplicationServices for AXIsProcessTrusted
_app_svc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("ApplicationServices"))
_app_svc.AXIsProcessTrusted.restype = ctypes.c_bool


# ── Permissions ────────────────────────────────────────────────────────────

def check_accessibility_permission() -> bool:
    return bool(_app_svc.AXIsProcessTrusted())


def request_accessibility_permission() -> None:
    subprocess.run([
        "open",
        "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
    ])


# ── Process ────────────────────────────────────────────────────────────────

def get_ableton_pid() -> int:
    """Return PID of the running Ableton Live process."""
    result = subprocess.run(["pgrep", "-x", "Live"], capture_output=True, text=True)
    pid_str = result.stdout.strip()
    if not pid_str:
        result = subprocess.run(["pgrep", "-f", "Ableton Live"], capture_output=True, text=True)
        pid_str = result.stdout.strip().split("\n")[0]
    if not pid_str:
        raise RuntimeError("Ableton Live is not running")
    return int(pid_str)


# ── Low-level input ────────────────────────────────────────────────────────

def _key(pid: int, keycode: int, modifiers: int = 0, delay: float = 0.05) -> None:
    """Send a key-down + key-up directly to a process by PID."""
    if not check_accessibility_permission():
        request_accessibility_permission()
        raise PermissionError(
            "Accessibility permission required. System Settings has been opened — "
            "add Terminal (or Python) to the Accessibility list, then try again."
        )
    src  = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
    down = Quartz.CGEventCreateKeyboardEvent(src, keycode, True)
    up   = Quartz.CGEventCreateKeyboardEvent(src, keycode, False)
    Quartz.CGEventSetFlags(down, modifiers)
    Quartz.CGEventSetFlags(up,   modifiers)
    Quartz.CGEventPostToPid(pid, down)
    time.sleep(delay)
    Quartz.CGEventPostToPid(pid, up)
    time.sleep(delay)


def _clipboard_set(text: str) -> None:
    subprocess.run(["pbcopy"], input=text.encode(), check=True)
    time.sleep(0.15)


# ── AppleScript helpers ────────────────────────────────────────────────────

def _osascript(script: str, timeout: float = 15.0) -> str:
    r = subprocess.run(["osascript", "-e", script],
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip())
    return r.stdout.strip()


def _window_names(process: str = "Live") -> str:
    try:
        return _osascript(f"""
tell application "System Events"
    tell process "{process}"
        return name of every window as string
    end tell
end tell
""")
    except RuntimeError:
        return ""


def _wait_for_window_containing(text: str, process: str = "Live", timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if text.lower() in _window_names(process).lower():
            return True
        time.sleep(0.3)
    return False


# ── Export steps ───────────────────────────────────────────────────────────

def _open_export_dialog(pid: int) -> None:
    _key(pid, _KEY_R, _CMD_SHIFT)


def _set_export_option(option_desc: str, enabled: bool, process: str = "Live") -> None:
    """Toggle an On/Off button in the Export Audio/Video dialog by its accessibility description."""
    desired = "On" if enabled else "Off"
    script = f"""
tell application "System Events"
    tell process "{process}"
        set w to window "Export Audio/Video"
        set allEls to entire contents of w
        repeat with el in allEls
            try
                if role of el is "AXButton" and description of el is "{option_desc}" then
                    if value of el is not "{desired}" then
                        click el
                    end if
                    return "ok"
                end if
            end try
        end repeat
        return "not-found"
    end tell
end tell
"""
    try:
        _osascript(script)
    except RuntimeError:
        pass


def _set_export_popup(option_desc: str, value: str, process: str = "Live") -> None:
    """Select a value in a popup-button (Sample Rate, Bit Depth, etc.) in the Export dialog."""
    safe_value = value.replace('"', '\\"')
    safe_desc  = option_desc.replace('"', '\\"')
    script = f"""
tell application "System Events"
    tell process "{process}"
        set w to window "Export Audio/Video"
        set allEls to entire contents of w
        repeat with el in allEls
            try
                if role of el is "AXPopUpButton" and description of el is "{safe_desc}" then
                    if value of el is "{safe_value}" then return "already"
                    click el
                    delay 0.4
                    try
                        click menu item "{safe_value}" of menu 1 of el
                    on error
                        key code 53
                        return "no-item"
                    end try
                    return "ok"
                end if
            end try
        end repeat
        return "not-found"
    end tell
end tell
"""
    try:
        _osascript(script)
    except RuntimeError:
        pass
    time.sleep(0.15)


def _click_export_button(pid: int, process: str = "Live") -> None:
    """Click Export in the Export Audio/Video dialog by accessibility description."""
    try:
        _osascript(f"""
tell application "System Events"
    tell process "{process}"
        set w to window "Export Audio/Video"
        set allEls to entire contents of w
        repeat with el in allEls
            try
                if role of el is "AXButton" and description of el is "Export" then
                    click el
                    return
                end if
            end try
        end repeat
        -- fallback
        click button 1 of window 1
    end tell
end tell
""")
    except RuntimeError:
        _key(pid, _KEY_RET)


_KEY_ESC = 53


def _save_with_filename(pid: int, tagged_filename: str) -> None:
    """Set the save panel's filename and click Save. The file goes to whatever
    location Ableton's panel defaults to — we'll find and move it afterwards."""
    safe_filename = tagged_filename.replace('"', '\\"')
    time.sleep(1.5)

    # Dismiss any leftover dialog (e.g. New Folder from a prior aborted run)
    _key(pid, _KEY_ESC, 0)
    time.sleep(0.3)

    script = f"""
tell application "System Events"
    tell process "Live"
        set frontmost to true
        delay 0.4

        set _panel to missing value
        repeat 20 times
            try
                set _panel to window "Save"
                exit repeat
            end try
            delay 0.3
        end repeat

        if _panel is missing value then return "no-panel"

        try
            set value of text field 1 of _panel to "{safe_filename}"
        on error
            try
                set value of text field 1 of group 1 of _panel to "{safe_filename}"
            end try
        end try

        delay 0.3

        try
            click button "Save" of _panel
        on error
            keystroke return
        end try

        return "ok"
    end tell
end tell
"""
    try:
        _osascript(script, timeout=15)
    except RuntimeError:
        _key(pid, _KEY_RET, 0)
    time.sleep(0.5)


_SEARCH_DIRS = [
    "~/Downloads",
    "~/Desktop",
    "~/Documents",
    "~/Music",
]


def _find_exported_files(token: str, timeout: float = 8.0) -> list:
    """Find files containing the unique token in common save-panel locations."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        for raw in _SEARCH_DIRS:
            loc = os.path.expanduser(raw)
            if not os.path.isdir(loc):
                continue
            try:
                hits = [os.path.join(loc, f) for f in os.listdir(loc) if token in f]
            except OSError:
                continue
            if hits:
                return hits
        time.sleep(0.5)
    return []


def _wait_for_export_complete(process: str = "Live", timeout: float = 600.0) -> None:
    """Block until the render/progress indicator disappears from Ableton's windows."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        names = _window_names(process).lower()
        if "rendering" not in names and "exporting" not in names:
            return
        time.sleep(1.0)


# ── Public API ─────────────────────────────────────────────────────────────

def export_song(
    output_dir: str = "~/Desktop",
    filename: str = "export",
    wait_for_completion: bool = True,
    dialog_timeout: float = 12.0,
    pcm: bool = True,
    sample_rate: str | None = None,
    bit_depth: str | None = None,
) -> dict:
    """
    Export the currently open Ableton session to an audio file.

    Steps:
      1. Cmd+Shift+R  →  open Export Audio/Video dialog  (no focus steal)
      2. Set PCM export toggle
      3. Click Export
      4. Save with a UUID-tagged filename to the panel's default location
      5. Wait for render to finish
      6. Find the file by UUID tag and move it to `output_dir` with the real filename
    """
    pid     = get_ableton_pid()
    abs_dir = os.path.expanduser(output_dir)
    os.makedirs(abs_dir, exist_ok=True)

    # Unique tag lets us find Ableton's output even if it lands in Downloads
    token           = f"abletonexport{uuid.uuid4().hex[:8]}"
    tagged_filename = f"{token}_{filename}"

    _open_export_dialog(pid)
    if not _wait_for_window_containing("Export", timeout=dialog_timeout):
        return {"status": "error", "message": "Export dialog did not appear — is Ableton open with a project loaded?"}
    time.sleep(0.4)

    _set_export_option("Encode PCM", pcm)
    time.sleep(0.2)

    if sample_rate:
        _set_export_popup("Sample Rate", sample_rate)
    if pcm and bit_depth:
        _set_export_popup("Recording Bit Depth", bit_depth)

    _click_export_button(pid)
    time.sleep(0.6)

    _save_with_filename(pid, tagged_filename)

    if not wait_for_completion:
        return {
            "status":      "ok",
            "output_path": os.path.join(abs_dir, filename),
            "message":     "Export started (not waiting for completion)",
        }

    time.sleep(1.0)
    _wait_for_export_complete()

    # Locate exported file(s) and move into the user's chosen folder
    sources = _find_exported_files(token)
    if not sources:
        return {
            "status":  "error",
            "message": "Export finished but the file was not found in ~/Downloads, ~/Desktop, ~/Documents, or ~/Music.",
        }

    moved = []
    for src in sources:
        ext = os.path.splitext(src)[1]
        dst = os.path.join(abs_dir, f"{filename}{ext}")
        # Avoid clobbering an existing file
        i = 1
        while os.path.exists(dst):
            dst = os.path.join(abs_dir, f"{filename} ({i}){ext}")
            i += 1
        try:
            shutil.move(src, dst)
            moved.append(dst)
        except OSError as e:
            return {
                "status":  "error",
                "message": f"Render saved to {src} but moving to {dst} failed: {e}",
            }

    return {
        "status":      "ok",
        "output_path": moved[0],
        "message":     f"Export complete → {moved[0]}" + (f" (+{len(moved)-1} more)" if len(moved) > 1 else ""),
    }
