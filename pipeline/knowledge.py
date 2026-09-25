"""
Structured Knowledge Extraction Engine.
Extracts evidence-grounded concepts, definitions, examples, formulas, comparisons,
lecturer emphasis cues, and potential exam questions from semantic lecture sections.
Uses local Llama 3 via Ollama with strict JSON schema enforcement and deterministic cue scanning.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional

import requests

from pipeline.config import OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT
from pipeline.db import Database

logger = logging.getLogger("pipeline.knowledge")

# Deterministic regex patterns for spoken lecturer cues
EXAM_PATTERNS = [
    r"\b(on the exam|in the midterm|in the final|test question|graded on this|guaranteed exam question)\b",
    r"\b(will ask this on the test|asked on the quiz|exam-relevant|likely exam question)\b",
]

IMPORTANCE_PATTERNS = [
    r"\b(pay (close )?attention|crucial to understand|most important takeaway|don't forget this|remember this)\b",
    r"\b(keep this in mind|fundamental concept|you should know this|vital to note|take note of this)\b",
    r"\b(students always get this wrong|common trap|classic mistake|pitfall)\b",
]


def detect_lecturer_emphasis(transcript_segments: List[Dict[str, Any]], window_index: int = 0) -> List[Dict[str, Any]]:
    """
    Scans transcript segments for explicit spoken lecturer emphasis and exam alerts.
    Distinguishes EXAM_SIGNAL and IMPORTANCE_SIGNAL without guessing.
    """
    signals: List[Dict[str, Any]] = []

    for seg in transcript_segments:
        text = seg.get("text", "")
        ts = float(seg.get("start") or seg.get("start_time") or 0.0)
        source_id = f"seg_{seg.get('index') or seg.get('id') or int(ts)}"

        # Check for exam signal first
        is_exam = False
        for pat in EXAM_PATTERNS:
            if re.search(pat, text, re.IGNORECASE):
                signals.append({
                    "window_index": window_index,
                    "signal_type": "EXAM_SIGNAL",
                    "text": text.strip(),
                    "timestamp": round(ts, 2),
                    "source_id": source_id,
                })
                is_exam = True
                break

        # Only check importance signal if not an explicit exam signal
        if not is_exam:
            for pat in IMPORTANCE_PATTERNS:
                if re.search(pat, text, re.IGNORECASE):
                    signals.append({
                        "window_index": window_index,
                        "signal_type": "IMPORTANCE_SIGNAL",
                        "text": text.strip(),
                        "timestamp": round(ts, 2),
                        "source_id": source_id,
                    })
                    break

    return signals


def call_ollama_json(prompt: str, system_prompt: Optional[str] = None, model: str = OLLAMA_MODEL) -> Dict[str, Any]:
    """
    Calls local Ollama with JSON format constraint and parses response.
    """
    url = f"{OLLAMA_BASE_URL}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0.2,
            "num_ctx": 8192,
        },
    }
    if system_prompt:
        payload["system"] = system_prompt

    resp = requests.post(url, json=payload, timeout=OLLAMA_TIMEOUT)
    if resp.status_code != 200:
        raise RuntimeError(f"Ollama JSON API failed ({resp.status_code}): {resp.text}")

    raw_text = resp.json().get("response", "{}").strip()
    try:
        return json.loads(raw_text)
    except Exception as e:
        logger.warning(f"Failed to parse Ollama JSON response: {e}. Raw: {raw_text[:200]}")
        # Try extracting JSON object from backticks if present
        m = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        return {}


def extract_knowledge_from_section(
    section: Dict[str, Any],
    timeline_entries: List[Dict[str, Any]],
    window_index: int = 0,
    model: str = OLLAMA_MODEL,
) -> List[Dict[str, Any]]:
    """
    Extracts structured knowledge items (concepts, definitions, formulas, examples, comparisons)
    from a semantic section by querying Ollama with structured context.
    """
    sec_start = section["start_seconds"]
    sec_end = section["end_seconds"]

    # Filter timeline entries that intersect with this section
    relevant_entries = [
        e for e in timeline_entries
        if not (e["end_time"] < sec_start or e["start_time"] > sec_end)
    ]

    if not relevant_entries:
        return []

    # Compile slides context and transcript context
    slides_context: List[str] = []
    transcript_context: List[str] = []

    for e in relevant_entries:
        meta = e.get("metadata", {})
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        s_idx = meta.get("slide_index", "?")
        ocr = meta.get("slide_ocr_text", "").strip()
        if ocr:
            slides_context.append(f"[Slide {s_idx} @ {e['start_time']:.1f}s]: {ocr}")

        chunk = e.get("transcript_chunk", "").strip()
        if chunk:
            transcript_context.append(f"[{e['start_time']:.1f}s - {e['end_time']:.1f}s]: {chunk}")

    prompt = f"""
You are an expert exam study assistant analyzing an academic lecture segment ({sec_start:.1f}s - {sec_end:.1f}s).
Extract all verifiable knowledge items taught in this segment. Every item MUST be directly grounded in the provided lecture evidence.

SLIDES IN THIS SEGMENT:
{chr(10).join(slides_context) if slides_context else "None"}

LECTURER TRANSCRIPT IN THIS SEGMENT:
{chr(10).join(transcript_context) if transcript_context else "None"}

Return a single valid JSON object strictly matching this schema:
{{
  "concepts": [
    {{
      "name": "Concept name",
      "category": "concept" | "definition" | "formula" | "example" | "comparison",
      "definition": "Precise formal definition if applicable",
      "explanation": "Clear explanation of how it works",
      "start_seconds": {sec_start},
      "end_seconds": {sec_end},
      "slide_index": integer or null,
      "transcript_quote": "Exact short quote from transcript supporting this",
      "slide_quote": "Exact slide text supporting this if on slide",
      "confidence": "HIGH" | "MEDIUM" | "LOW"
    }}
  ],
  "exam_questions": [
    {{
      "question": "Potential exam question testing this concept",
      "expected_answer": "Short summary of the correct answer based on lecture",
      "concept_name": "Concept name"
    }}
  ]
}}
Do NOT invent topics not discussed in the transcript or slides.
"""
    system_prompt = "You are a precise, evidence-grounded academic assistant. Only output valid JSON."

    extracted_concepts: List[Dict[str, Any]] = []
    try:
        data = call_ollama_json(prompt, system_prompt=system_prompt, model=model)
        raw_concepts = data.get("concepts", [])

        for rc in raw_concepts:
            if not rc.get("name") or not rc.get("explanation"):
                continue

            evidence_refs = []
            if rc.get("transcript_quote"):
                evidence_refs.append({
                    "type": "TRANSCRIPT",
                    "timestamp": rc.get("start_seconds", sec_start),
                    "evidence_text": rc["transcript_quote"],
                })
            if rc.get("slide_quote"):
                evidence_refs.append({
                    "type": "SLIDE",
                    "timestamp": rc.get("start_seconds", sec_start),
                    "slide_index": rc.get("slide_index"),
                    "evidence_text": rc["slide_quote"],
                })

            conf = rc.get("confidence", "MEDIUM")
            if len(evidence_refs) >= 2:
                conf = "HIGH"
            elif len(evidence_refs) == 0:
                conf = "LOW"

            extracted_concepts.append({
                "window_index": window_index,
                "name": rc["name"],
                "category": rc.get("category", "concept"),
                "definition": rc.get("definition", ""),
                "explanation": rc.get("explanation", ""),
                "start_seconds": float(rc.get("start_seconds", sec_start)),
                "end_seconds": float(rc.get("end_seconds", sec_end)),
                "slide_id": rc.get("slide_index"),
                "evidence_references": evidence_refs,
                "confidence": conf,
                "status": "unverified",
            })
    except Exception as e:
        logger.warning(f"Ollama knowledge extraction failed for section ({sec_start}s - {sec_end}s): {e}")
        # Deterministic fallback: extract title from section
        extracted_concepts.append({
            "window_index": window_index,
            "name": section.get("title", "Lecture Topic"),
            "category": "concept",
            "definition": "",
            "explanation": section.get("summary", ""),
            "start_seconds": sec_start,
            "end_seconds": sec_end,
            "slide_id": None,
            "evidence_references": [{
                "type": "TRANSCRIPT",
                "timestamp": sec_start,
                "evidence_text": section.get("summary", ""),
            }],
            "confidence": "MEDIUM",
            "status": "unverified",
        })

    return extracted_concepts
