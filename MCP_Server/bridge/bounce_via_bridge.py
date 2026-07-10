"""
Trigger an Ableton bounce-in-place via the max-http-bridge /bounce/workflow
endpoint. The bridge orchestrates FreezeReceiver device select → dummy clip
creation → bounce keystroke → wait. We then locate the bounced wav in the
project's Samples/Bounces folder and move it to the project root, renamed
to <song>.als.wav.
"""

import glob
import os
import shutil
import time

from . import _http


def _find_latest_wav(search_dirs: list[str], since_epoch: float, timeout: float = 30.0,
                     stable_for: float = 1.5) -> str | None:
    """
    Poll `search_dirs` for a .wav modified after `since_epoch`, and return the
    newest one once its size stops changing for `stable_for` seconds (file
    write is finished). Returns None on timeout.
    """
    deadline = time.time() + timeout
    last_size = -1
    last_size_at = 0.0
    candidate = None

    while time.time() < deadline:
        latest_path = None
        latest_mtime = since_epoch
        for d in search_dirs:
            if not os.path.isdir(d):
                continue
            for f in glob.glob(os.path.join(d, "*.wav")):
                try:
                    m = os.path.getmtime(f)
                except OSError:
                    continue
                if m > latest_mtime:
                    latest_mtime = m
                    latest_path = f

        if latest_path is None:
            time.sleep(0.5)
            continue

        if latest_path != candidate:
            candidate = latest_path
            last_size = -1
            last_size_at = 0.0

        try:
            size = os.path.getsize(candidate)
        except OSError:
            time.sleep(0.5)
            continue

        if size == last_size and size > 0:
            if time.time() - last_size_at >= stable_for:
                return candidate
        else:
            last_size = size
            last_size_at = time.time()

        time.sleep(0.5)

    return candidate  # may be None or unstable; caller decides


def bounce_via_bridge(project_dir: str | None = None, bounce_wait_ms: int = 5000,
                      bridge_url: str = "http://127.0.0.1:7500",
                      move_to_project_root: bool = True,
                      file_wait_timeout: float = 30.0) -> dict:
    """
    Trigger /bounce/workflow on the max-http-bridge, then locate the resulting
    wav and (optionally) move + rename it to <project_dir>/<song>.als.wav.

    Parameters:
    - project_dir: Project folder (the one containing the .als + Samples/).
      If None, the file-locate + rename step is skipped and the raw bridge
      response is returned.
    - bounce_wait_ms: Forwarded to the bridge; how long it waits after sending
      the bounce keystroke before returning (default 5000).
    - bridge_url: Override the default http://127.0.0.1:7500 if needed.
    - move_to_project_root: If True and project_dir is given, move the bounced
      file to project_dir/<song>.als.wav. If False, leave it where Ableton wrote it.
    - file_wait_timeout: Seconds to wait for the .wav to appear and stop growing.
    """
    # Precondition: bridge alive
    try:
        ping_result = _http.ping(bridge_url)
        if ping_result.get("status") != "ok":
            return {"status": "error", "message": f"Bridge ping returned: {ping_result}"}
    except Exception as e:
        return {"status": "error", "message": f"Bridge unreachable at {bridge_url}: {e}"}

    # Capture pre-bounce timestamp so we can identify the new file
    pre_bounce_ts = time.time()

    # Song name for the rename
    try:
        sn = _http.get("/song/name", base_url=bridge_url)
        song_name = sn.get("result", "")
    except Exception:
        song_name = ""

    # Trigger the workflow (bridge blocks until step 7 of its workflow finishes)
    try:
        workflow = _http.post("/bounce/workflow", body={"bounce_wait": bounce_wait_ms},
                              base_url=bridge_url,
                              timeout=max(60.0, (bounce_wait_ms / 1000) + 60))
    except Exception as e:
        return {"status": "error", "message": f"/bounce/workflow failed: {e}"}

    if workflow.get("status") != "ok":
        return {"status": "error", "message": "Bridge bounce workflow failed",
                "bridge_response": workflow}

    if project_dir is None:
        return {"status": "ok", "message": "Bounce fired; project_dir not provided so file not moved",
                "song_name": song_name, "bridge_response": workflow}

    project_dir = os.path.expanduser(project_dir)
    search_dirs = [
        os.path.join(project_dir, "Samples", "Bounces"),
        os.path.join(project_dir, "Samples", "Recorded"),
        os.path.join(project_dir, "Samples", "Processed", "Consolidate"),
    ]

    bounced = _find_latest_wav(search_dirs, since_epoch=pre_bounce_ts,
                               timeout=file_wait_timeout)
    if not bounced:
        return {"status": "warning",
                "message": "Bridge reported success but no new .wav found in Samples/{Bounces,Recorded,Processed/Consolidate}",
                "song_name": song_name, "bridge_response": workflow,
                "searched": search_dirs}

    if not move_to_project_root:
        return {"status": "ok", "song_name": song_name, "output_path": bounced,
                "bridge_response": workflow}

    # Move + rename: <project_dir>/<song>.als.wav
    target_name = f"{song_name}.als.wav" if song_name else os.path.basename(bounced)
    target = os.path.join(project_dir, target_name)

    i = 1
    while os.path.exists(target):
        stem = f"{song_name}.als" if song_name else os.path.splitext(os.path.basename(bounced))[0]
        target = os.path.join(project_dir, f"{stem} ({i}).wav")
        i += 1

    try:
        shutil.move(bounced, target)
    except OSError as e:
        return {"status": "warning", "message": f"Bounce found at {bounced} but move failed: {e}",
                "song_name": song_name, "source_path": bounced,
                "bridge_response": workflow}

    return {"status": "ok", "song_name": song_name,
            "output_path": target, "source_path": bounced,
            "bridge_response": workflow}
