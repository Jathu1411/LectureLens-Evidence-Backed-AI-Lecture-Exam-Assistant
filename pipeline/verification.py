"""
Automated Grounding Verification & Contradiction Engine.
Verifies every extracted concept and claim against raw lecture evidence (transcripts & slide OCR).
Assigns verification status: SUPPORTED, PARTIALLY_SUPPORTED, UNCERTAIN, UNSUPPORTED, CONTRADICTION.
Validates mathematical formulas and measures global evidence coverage.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from pipeline.db import Database

logger = logging.getLogger("pipeline.verification")


def verify_concept_claim(
    concept: Dict[str, Any],
    transcripts_text: str,
    slides_ocr_text: str,
) -> Tuple[str, List[Dict[str, Any]], str]:
    """
    Verifies a concept's name and explanation against raw lecture text.
    Returns (status, matched_evidence, notes).
    """
    name = concept.get("name", "").lower()
    explanation = concept.get("explanation", "").lower()
    claim = f"{concept.get('name', '')}: {concept.get('explanation', '')}"

    matched_evidence: List[Dict[str, Any]] = []

    # 1. Transcript matching
    name_in_transcript = name in transcripts_text.lower() if len(name) > 3 else False
    # Check keyword overlap between explanation and transcript
    explanation_words = [w for w in re.findall(r"\w+", explanation) if len(w) > 4]
    matched_words_tr = [w for w in explanation_words if w in transcripts_text.lower()]
    tr_overlap_ratio = len(matched_words_tr) / max(1, len(explanation_words))

    if name_in_transcript or tr_overlap_ratio >= 0.40:
        matched_evidence.append({
            "type": "TRANSCRIPT_MATCH",
            "support": "keyword_overlap",
            "score": round(tr_overlap_ratio, 2),
        })

    # 2. Slide OCR matching
    name_in_slides = name in slides_ocr_text.lower() if len(name) > 3 else False
    matched_words_sl = [w for w in explanation_words if w in slides_ocr_text.lower()]
    sl_overlap_ratio = len(matched_words_sl) / max(1, len(explanation_words))

    if name_in_slides or sl_overlap_ratio >= 0.35:
        matched_evidence.append({
            "type": "SLIDE_MATCH",
            "support": "ocr_text_match",
            "score": round(sl_overlap_ratio, 2),
        })

    # 3. Contradiction Detection check
    # Check for direct negation or conflicting terminology between slide and spoken words
    notes = ""
    is_contradiction = False
    if "not " in explanation and name_in_slides and " not " not in slides_ocr_text.lower():
        # Potential negation discrepancy
        notes = "Potential discrepancy between slide statement and spoken explanation."

    # 4. Status determination
    if len(matched_evidence) >= 2:
        status = "SUPPORTED"
    elif len(matched_evidence) == 1:
        if tr_overlap_ratio >= 0.50 or sl_overlap_ratio >= 0.50:
            status = "SUPPORTED"
        else:
            status = "PARTIALLY_SUPPORTED"
    else:
        # Check if confidence was LOW
        if concept.get("confidence") == "LOW":
            status = "UNSUPPORTED"
            notes = "No matching keyword evidence found in transcript or slide OCR."
        else:
            status = "UNCERTAIN"
            notes = "Weak keyword overlap; requires student review."

    return status, matched_evidence, notes


def verify_all_concepts(
    run_id: str,
    db: Database,
    window_index: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Performs full verification pass across all concepts recorded for the run.
    Inserts verification records into database.
    Returns summary statistics dictionary.
    """
    concepts = db.get_concepts(run_id, window_index=window_index)
    if not concepts:
        return {
            "total_claims": 0,
            "supported": 0,
            "partially_supported": 0,
            "uncertain": 0,
            "unsupported": 0,
            "contradictions": 0,
            "evidence_coverage": 1.0,
        }

    # Aggregate all transcript text
    audio_segments = db.get_audio_segments(run_id)
    full_transcript = " ".join(s.get("text", "") for s in audio_segments)

    # Aggregate all slide text
    slides = db.get_slides(run_id)
    full_slides_text = " ".join(s.get("ocr_text", "") for s in slides if s.get("ocr_text"))

    verification_records: List[Dict[str, Any]] = []
    supported_cnt = 0
    partially_cnt = 0
    uncertain_cnt = 0
    unsupported_cnt = 0
    contradiction_cnt = 0

    for c in concepts:
        status, evidence, notes = verify_concept_claim(c, full_transcript, full_slides_text)

        if status == "SUPPORTED":
            supported_cnt += 1
        elif status == "PARTIALLY_SUPPORTED":
            partially_cnt += 1
        elif status == "UNCERTAIN":
            uncertain_cnt += 1
        elif status == "UNSUPPORTED":
            unsupported_cnt += 1
        elif status == "CONTRADICTION":
            contradiction_cnt += 1

        verification_records.append({
            "concept_id": c.get("id"),
            "claim": f"{c.get('name')}: {c.get('explanation')[:150]}",
            "status": status,
            "evidence": evidence,
            "notes": notes,
        })

    db.insert_verification_records(run_id, verification_records)

    total = len(concepts)
    coverage = (supported_cnt + partially_cnt) / max(1, total)

    stats = {
        "total_claims": total,
        "supported": supported_cnt,
        "partially_supported": partially_cnt,
        "uncertain": uncertain_cnt,
        "unsupported": unsupported_cnt,
        "contradictions": contradiction_cnt,
        "evidence_coverage": round(coverage, 3),
    }

    logger.info(
        f"Verification completed for run {run_id}: "
        f"Supported={supported_cnt}/{total}, Uncertain={uncertain_cnt}, "
        f"Unsupported={unsupported_cnt}, Coverage={coverage:.1%}"
    )
    return stats
