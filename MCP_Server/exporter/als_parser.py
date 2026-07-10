"""
Read tempo, time signature, and arrangement length directly from an .als
(gzipped XML) without opening Ableton.

Vendored from GabrielTha/AbletonExporter (internal partner repo).
"""

import gzip
import xml.etree.ElementTree as ET


def parse_duration(als_path: str) -> dict:
    """Return tempo, total beats, and duration in seconds for an ALS project."""
    with gzip.open(als_path, "rb") as f:
        data = f.read()

    root = ET.fromstring(data)
    liveset = root.find("LiveSet")
    if liveset is None:
        raise ValueError("Not a valid ALS file: <LiveSet> element missing")

    # Tempo
    tempo_el = liveset.find(".//Tempo/Manual")
    tempo = float(tempo_el.get("Value", 120)) if tempo_el is not None else 120.0

    # Time signature
    num_el = liveset.find(".//TimeSignature/TimeSignatures/RemoteableTimeSignature/Numerator")
    den_el = liveset.find(".//TimeSignature/TimeSignatures/RemoteableTimeSignature/Denominator")
    numerator = int(num_el.get("Value", 4)) if num_el is not None else 4
    denominator = int(den_el.get("Value", 4)) if den_el is not None else 4

    # Arrangement end = max(clip_start + clip_length) across all tracks
    max_end_beats = 0.0
    tracks = liveset.find("Tracks")
    if tracks is not None:
        for track in tracks:
            for aa in track.iter("ArrangerAutomation"):
                events = aa.find("Events")
                if events is None:
                    continue
                for clip in events:
                    try:
                        start = float(clip.get("Time", 0))
                        current_start_el = clip.find("CurrentStart")
                        current_end_el = clip.find("CurrentEnd")
                        if current_end_el is not None:
                            clip_start = float(current_start_el.get("Value", 0)) if current_start_el is not None else 0.0
                            clip_end = float(current_end_el.get("Value", 0))
                            abs_end = start + (clip_end - clip_start)
                            if abs_end > max_end_beats:
                                max_end_beats = abs_end
                    except (TypeError, ValueError):
                        continue

    duration_seconds = (max_end_beats / tempo) * 60.0 if tempo > 0 else 0.0

    return {
        "tempo": tempo,
        "time_signature": f"{numerator}/{denominator}",
        "beats": max_end_beats,
        "duration_seconds": round(duration_seconds, 2),
        "duration_minutes": round(duration_seconds / 60, 3),
    }
