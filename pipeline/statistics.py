"""
Lecture Statistics Engine.
Generates comprehensive performance, quality, and knowledge metrics after lecture processing.
Produces canonical machine-readable JSON and human-readable Markdown reports
in output/<run_id>/lecture_statistics.json and lecture_statistics.md.
"""

from datetime import datetime
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from pipeline import config
from pipeline.db import Database

logger = logging.getLogger("pipeline.statistics")


def generate_lecture_statistics(
    run_id: str,
    db: Database,
    processing_start_time: float,
    processing_end_time: float,
    stage_timings: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """
    Computes and persists the complete statistics report for a lecture run.
    """
    run = db.get_run(run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found in database.")

    video_duration = float(run.get("total_duration") or 0.0)
    total_processing_seconds = max(0.1, round(processing_end_time - processing_start_time, 2))
    real_time_factor = round(total_processing_seconds / max(1.0, video_duration), 4)

    # Windows
    windows = db.get_windows(run_id)
    completed_windows = sum(1 for w in windows if w.get("status") == "COMPLETE")
    failed_windows = sum(1 for w in windows if w.get("status") == "FAILED")

    # Audio
    audio_segments = db.get_audio_segments(run_id)

    # Visual
    slides = db.get_slides(run_id)
    unique_slides = db.get_unique_slides(run_id)
    revisits = sum(max(0, s.get("appearance_count", 1) - 1) for s in slides)

    # OCR
    tesseract_count = sum(1 for s in slides if s.get("source") == "tesseract")
    vision_count = sum(1 for s in slides if s.get("source") == "ollama_vision")
    reused_count = sum(1 for s in slides if "reused" in str(s.get("source", "")))

    # Knowledge
    sections = db.get_semantic_sections(run_id)
    concepts = db.get_concepts(run_id)
    exam_signals = db.get_exam_signals(run_id)

    def_count = sum(1 for c in concepts if c.get("category") == "definition" or c.get("definition"))
    formula_count = sum(1 for c in concepts if c.get("category") == "formula")
    example_count = sum(1 for c in concepts if c.get("category") == "example")
    comparison_count = sum(1 for c in concepts if c.get("category") == "comparison")

    # Verification
    verif_records = db.get_verification_records(run_id)
    supported_cnt = sum(1 for r in verif_records if r.get("status") == "SUPPORTED")
    partial_cnt = sum(1 for r in verif_records if r.get("status") == "PARTIALLY_SUPPORTED")
    uncertain_cnt = sum(1 for r in verif_records if r.get("status") == "UNCERTAIN")
    unsupported_cnt = sum(1 for r in verif_records if r.get("status") == "UNSUPPORTED")
    contradiction_cnt = sum(1 for r in verif_records if r.get("status") == "CONTRADICTION")

    total_claims = len(verif_records) if verif_records else len(concepts)
    coverage = round((supported_cnt + partial_cnt) / max(1, total_claims), 3) if total_claims else 1.0

    # Output file stats
    out_dir = config.OUTPUT_DIR / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_file = out_dir / "study_guide.pdf"
    pdf_size = pdf_file.stat().st_size if pdf_file.exists() else 0

    stats_report: Dict[str, Any] = {
        "lecture_id": run_id,
        "video_path": run.get("video_path", ""),
        "video_duration_seconds": round(video_duration, 2),
        "processing": {
            "started_at": datetime.fromtimestamp(processing_start_time).isoformat(),
            "completed_at": datetime.fromtimestamp(processing_end_time).isoformat(),
            "total_processing_seconds": total_processing_seconds,
            "real_time_factor": real_time_factor,
        },
        "windows": {
            "total": len(windows) if windows else 1,
            "completed": completed_windows if windows else 1,
            "failed": failed_windows,
            "overlap_seconds": config.WINDOW_OVERLAP_SEC,
        },
        "audio": {
            "transcript_segments": len(audio_segments),
            "whisper_model": config.WHISPER_MODEL,
        },
        "visual": {
            "slides_detected": len(slides),
            "unique_slides": len(unique_slides),
            "duplicate_slide_revisits": revisits,
        },
        "ocr": {
            "slides_processed": len(slides),
            "tesseract_ocr": tesseract_count,
            "vision_fallback": vision_count,
            "cluster_reused": reused_count,
        },
        "knowledge": {
            "semantic_sections": len(sections),
            "concepts_total": len(concepts),
            "definitions": def_count,
            "formulas": formula_count,
            "examples": example_count,
            "comparisons": comparison_count,
            "exam_signals": len(exam_signals),
        },
        "verification": {
            "total_claims": total_claims,
            "supported": supported_cnt,
            "partially_supported": partial_cnt,
            "uncertain": uncertain_cnt,
            "unsupported": unsupported_cnt,
            "contradictions": contradiction_cnt,
            "evidence_coverage": coverage,
        },
        "performance_timings": stage_timings or {},
        "output": {
            "pdf_path": str(pdf_file) if pdf_file.exists() else None,
            "study_guide_size_bytes": pdf_size,
        },
    }

    # Save to database
    db.upsert_lecture_statistics(run_id, stats_report, real_time_factor)

    # Write JSON artifact
    json_path = out_dir / "lecture_statistics.json"
    json_path.write_text(json.dumps(stats_report, indent=2), encoding="utf-8")

    # Write Markdown artifact
    md_path = out_dir / "lecture_statistics.md"
    md_content = f"""# Lecture Processing Statistics Report
**Lecture ID**: `{run_id}`  
**Video Duration**: {video_duration / 60:.1f} minutes ({video_duration:.1f}s)  
**Total Processing Time**: {total_processing_seconds / 60:.1f} minutes ({total_processing_seconds:.1f}s)  
**Real-Time Factor**: `{real_time_factor}` (lower is faster)  

---

## 1. Pipeline Performance & Windows
- **Processing Windows**: {stats_report['windows']['total']} total ({stats_report['windows']['completed']} completed, {stats_report['windows']['failed']} failed)
- **Window Overlap**: {config.WINDOW_OVERLAP_SEC}s

### Stage Timings
| Stage | Elapsed Seconds |
| :--- | :--- |
"""
    for stage_name, el_sec in (stage_timings or {}).items():
        md_content += f"| {stage_name} | {el_sec:.2f}s |\n"

    md_content += f"""
---

## 2. Visual & OCR Metrics
- **Slides Detected**: {len(slides)}
- **Unique Slide Stills**: {len(unique_slides)}
- **Revisited Appearances**: {revisits}
- **Tesseract OCR Passes**: {tesseract_count}
- **Vision LLM Fallbacks**: {vision_count}
- **Cluster Reused OCR**: {reused_count}

---

## 3. Knowledge Base & Evidence Verification
- **Semantic Sections**: {len(sections)}
- **Extracted Concepts**: {len(concepts)} (Definitions: {def_count}, Formulas: {formula_count}, Examples: {example_count})
- **Spoken Exam Signals**: {len(exam_signals)}
- **Evidence Coverage**: `{coverage:.1%}`
- **Claims Verified**: {supported_cnt} Supported, {partial_cnt} Partially Supported, {uncertain_cnt} Uncertain, {unsupported_cnt} Unsupported
- **Contradictions Flagged**: {contradiction_cnt}
"""
    md_path.write_text(md_content, encoding="utf-8")

    logger.info(f"Generated lecture statistics at {json_path} and {md_path}")
    return stats_report
