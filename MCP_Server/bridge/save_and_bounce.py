"""
Save the current Ableton project to a chosen folder, then trigger a bounce
via the max-http-bridge and move the resulting wav into the project root.
"""

from .save_project_as import save_project_as
from .bounce_via_bridge import bounce_via_bridge


def save_and_bounce(folder: str, name: str, bounce_wait_ms: int = 5000,
                    dialog_timeout: float = 15.0,
                    bridge_url: str = "http://127.0.0.1:7500") -> dict:
    """
    Save-as → bounce → file-into-project-root, end to end.

    Parameters:
    - folder: Destination folder for the project (~ expanded; created if missing)
    - name: Project name (with or without .als suffix)
    - bounce_wait_ms: Forwarded to /bounce/workflow
    - dialog_timeout: Save dialog appearance timeout
    - bridge_url: max-http-bridge base URL

    Returns a dict with both the save_result and bounce_result blocks plus an
    overall status.
    """
    save_result = save_project_as(folder=folder, name=name,
                                  dialog_timeout=dialog_timeout,
                                  verify_via_bridge=True)
    if save_result.get("status") == "error":
        return {"status": "error", "stage": "save", "save_result": save_result}

    project_dir = save_result.get("project_dir")
    bounce_result = bounce_via_bridge(project_dir=project_dir,
                                      bounce_wait_ms=bounce_wait_ms,
                                      bridge_url=bridge_url)

    overall = "ok"
    if bounce_result.get("status") == "error":
        overall = "error"
    elif "warning" in (save_result.get("status"), bounce_result.get("status")):
        overall = "warning"

    return {"status": overall, "save_result": save_result, "bounce_result": bounce_result}
