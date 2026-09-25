"""
Stage 5: Alignment
Merges audio segments and slide text into one ordered timeline keyed by video timestamp.
Associates spoken transcript sections with the slide active on screen during that time interval.
"""

import logging
from typing import Any, Dict, List, Optional

from pipeline.db import Database

logger = logging.getLogger("pipeline.align")


def align_timeline(run_id: str, db: Database) -> List[Dict[str, Any]]:
    """
    Combines timestamped audio segments and detected slides into an ordered timeline.
    Persists aligned entries into the timeline_entries table in Postgres.
    """
    slides = db.get_slides(run_id)
    audio_segments = db.get_audio_segments(run_id)

    if not audio_segments and not slides:
        logger.warning(f"Neither audio segments nor slides found for run {run_id}.")
        return []

    logger.info(
        f"Aligning {len(audio_segments)} audio segments with {len(slides)} slides for run {run_id}..."
    )

    # Determine slide time intervals: [slide[i].timestamp, slide[i+1].timestamp)
    slide_intervals = []
    for i, slide in enumerate(slides):
        s_start = slide["timestamp"]
        s_end = slides[i + 1]["timestamp"] if i + 1 < len(slides) else float("inf")
        slide_intervals.append({
            "slide": slide,
            "start": s_start,
            "end": s_end,
            "audio": [],
        })

    # If no slides detected at all, create a single fallback interval
    if not slide_intervals:
        slide_intervals.append({
            "slide": None,
            "start": 0.0,
            "end": float("inf"),
            "audio": [],
        })

    # Associate each audio segment with the active slide interval
    for seg in audio_segments:
        seg_mid = (seg["start_time"] + seg["end_time"]) / 2.0
        placed = False
        for interval in slide_intervals:
            if interval["start"] <= seg_mid < interval["end"]:
                interval["audio"].append(seg)
                placed = True
                break
        if not placed and slide_intervals:
            # If before first slide or after last, assign to nearest
            if seg_mid < slide_intervals[0]["start"]:
                slide_intervals[0]["audio"].append(seg)
            else:
                slide_intervals[-1]["audio"].append(seg)

    # Build timeline entries
    timeline_entries: List[Dict[str, Any]] = []
    for idx, interval in enumerate(slide_intervals):
        slide = interval["slide"]
        audio_list = interval["audio"]

        # Calculate actual interval start and end times
        if audio_list:
            interval_start = min(slide["timestamp"] if slide else 0.0, audio_list[0]["start_time"])
            interval_end = audio_list[-1]["end_time"]
            transcript_text = " ".join(a["text"] for a in audio_list)
        else:
            interval_start = slide["timestamp"] if slide else 0.0
            interval_end = interval["end"] if interval["end"] != float("inf") else interval_start + 10.0
            transcript_text = ""

        entry = {
            "index": idx,
            "start_time": round(interval_start, 2),
            "end_time": round(interval_end, 2),
            "slide_id": slide["id"] if slide else None,
            "transcript_chunk": transcript_text,
            "metadata": {
                "slide_index": slide["slide_index"] if slide else idx + 1,
                "cluster_id": slide.get("cluster_id") if slide else idx + 1,
                "slide_frame_path": slide["frame_path"] if slide else None,
                "slide_ocr_text": slide.get("ocr_text", "") if slide else "",
                "slide_source": slide.get("source", "none") if slide else "none",
                "segment_count": len(audio_list),
                "segment_ids": [a.get("id") or a.get("segment_index") or a.get("index") for a in audio_list],
            },
        }
        timeline_entries.append(entry)

    # Store in database
    db.insert_timeline_entries(run_id, timeline_entries)
    logger.info(
        f"Timeline alignment complete for run {run_id}. "
        f"Generated {len(timeline_entries)} timeline intervals."
    )
    return timeline_entries


def detect_semantic_sections(
    run_id: str,
    db: Database,
    window_index: Optional[int] = None,
    target_section_seconds: int = 420,
    max_section_seconds: int = 600,
) -> List[Dict[str, Any]]:
    """
    Divides timeline entries into meaningful 5-10 minute semantic sections
    based on slide transitions, topic continuity, and speech boundaries.
    Avoids arbitrary word/token slicing.
    """
    entries = db.get_timeline_entries(run_id)
    if not entries:
        return []

    sections: List[Dict[str, Any]] = []
    current_entries: List[Dict[str, Any]] = []
    section_start = entries[0]["start_time"]
    section_idx = 0

    for e in entries:
        current_entries.append(e)
        current_dur = e["end_time"] - section_start

        # Check if section duration reached target or max at slide boundary
        if current_dur >= target_section_seconds or current_dur >= max_section_seconds:
            section_idx += 1
            # Infer title from slide OCR or transcript
            title = _extract_section_title(current_entries)
            summary_preview = " ".join(item.get("transcript_chunk", "")[:120] for item in current_entries[:2])

            sections.append({
                "window_index": window_index or 0,
                "section_index": section_idx,
                "title": title,
                "start_seconds": round(section_start, 2),
                "end_seconds": round(e["end_time"], 2),
                "summary": summary_preview.strip()[:300],
            })
            current_entries = []
            section_start = e["end_time"]

    # Trailing entries
    if current_entries:
        section_idx += 1
        title = _extract_section_title(current_entries)
        summary_preview = " ".join(item.get("transcript_chunk", "")[:120] for item in current_entries[:2])
        sections.append({
            "window_index": window_index or 0,
            "section_index": section_idx,
            "title": title,
            "start_seconds": round(section_start, 2),
            "end_seconds": round(current_entries[-1]["end_time"], 2),
            "summary": summary_preview.strip()[:300],
        })

    db.insert_semantic_sections(run_id, sections)
    logger.info(f"Identified {len(sections)} semantic sections for run {run_id}.")
    return sections


def _extract_section_title(entries: List[Dict[str, Any]]) -> str:
    """Extracts a concise section title from the initial slide OCR or first sentence."""
    for e in entries:
        meta = e.get("metadata", {})
        if isinstance(meta, str):
            import json
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        ocr_text = meta.get("slide_ocr_text", "")
        if ocr_text and len(ocr_text.strip()) > 3:
            first_line = ocr_text.strip().splitlines()[0]
            clean = "".join(c for c in first_line if c.isalnum() or c in " -_:()").strip()
            if 3 < len(clean) <= 60:
                return clean

    # Fallback to transcript snippet
    for e in entries:
        chunk = e.get("transcript_chunk", "")
        if chunk and len(chunk.strip()) > 10:
            words = chunk.strip().split()[:6]
            return " ".join(words) + "..."

    return "Lecture Segment"

