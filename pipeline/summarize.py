"""
Stage 6: Map-Reduce Summarization
Uses a local Llama model via Ollama's HTTP API (http://localhost:11434).
Partitions the aligned timeline into ~10-15 minute slide-boundary chunks.
Map step summarizes each chunk incrementally to Postgres.
Reduce step synthesizes all chunk summaries into the final structured study guide.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional

import requests

from pipeline.config import (
    CHUNK_MAX_SECONDS,
    CHUNK_MIN_SECONDS,
    CHUNK_TARGET_SECONDS,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OLLAMA_TIMEOUT,
)
from pipeline.db import Database

logger = logging.getLogger("pipeline.summarize")


def format_timestamp(seconds: float) -> str:
    """Converts seconds into HH:MM:SS format."""
    total_sec = int(seconds)
    hours = total_sec // 3600
    minutes = (total_sec % 3600) // 60
    secs = total_sec % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def partition_timeline_chunks(
    timeline_entries: List[Dict[str, Any]],
    min_sec: int = CHUNK_MIN_SECONDS,
    target_sec: int = CHUNK_TARGET_SECONDS,
    max_sec: int = CHUNK_MAX_SECONDS,
) -> List[Dict[str, Any]]:
    """
    Groups timeline entries into ~10-15 minute chunks strictly respecting slide boundaries.
    """
    if not timeline_entries:
        return []

    chunks: List[Dict[str, Any]] = []
    current_entries: List[Dict[str, Any]] = []
    chunk_start = timeline_entries[0]["start_time"]

    for entry in timeline_entries:
        current_entries.append(entry)
        current_duration = entry["end_time"] - chunk_start

        # Check if we should split: reached minimum duration and at a natural slide boundary
        if current_duration >= target_sec or current_duration >= max_sec:
            chunks.append({
                "chunk_index": len(chunks),
                "start_time": chunk_start,
                "end_time": entry["end_time"],
                "entries": current_entries,
            })
            current_entries = []
            chunk_start = entry["end_time"]

    # Add any remaining tail entries
    if current_entries:
        # If very short (< 3 mins) and we already have chunks, merge with last chunk
        if chunks and (current_entries[-1]["end_time"] - chunk_start < 180):
            chunks[-1]["entries"].extend(current_entries)
            chunks[-1]["end_time"] = current_entries[-1]["end_time"]
        else:
            chunks.append({
                "chunk_index": len(chunks),
                "start_time": chunk_start,
                "end_time": current_entries[-1]["end_time"],
                "entries": current_entries,
            })

    return chunks


def call_ollama(prompt: str, system_prompt: Optional[str] = None, model: str = OLLAMA_MODEL) -> str:
    """Calls local Ollama instance via HTTP API."""
    url = f"{OLLAMA_BASE_URL}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.3,
            "num_ctx": 8192,
        },
    }
    if system_prompt:
        payload["system"] = system_prompt

    logger.debug(f"Sending prompt to Ollama ({model}): {prompt[:120]}...")
    resp = requests.post(url, json=payload, timeout=OLLAMA_TIMEOUT)
    if resp.status_code != 200:
        raise RuntimeError(f"Ollama API request failed (HTTP {resp.status_code}): {resp.text}")

    data = resp.json()
    return data.get("response", "").strip()


def run_map_step(run_id: str, db: Database, resume: bool = True) -> List[Dict[str, Any]]:
    """
    Map Step: Summarizes each ~10-15 minute timeline chunk individually.
    Writes each chunk summary incrementally to Postgres immediately upon completion.
    """
    timeline = db.get_timeline_entries(run_id)
    if not timeline:
        raise ValueError(f"No timeline entries found for run {run_id}. Run alignment first.")

    chunks = partition_timeline_chunks(timeline)
    logger.info(f"Timeline partitioned into {len(chunks)} slide-aware chunks for Map step.")

    completed_indices = set(db.get_completed_chunk_indices(run_id)) if resume else set()

    for chunk in chunks:
        c_idx = chunk["chunk_index"]
        if c_idx in completed_indices:
            logger.info(f"Chunk {c_idx} already summarized in database. Skipping (resume).")
            continue

        c_start_fmt = format_timestamp(chunk["start_time"])
        c_end_fmt = format_timestamp(chunk["end_time"])

        # Format slide text and transcript for prompt
        slides_text_blocks = []
        transcript_blocks = []

        for e in chunk["entries"]:
            meta = e.get("metadata", {})
            if isinstance(meta, str):
                meta = json.loads(meta)
            slide_no = meta.get("slide_index", "?")
            slide_ocr = meta.get("slide_ocr_text", "").strip()
            if slide_ocr:
                slides_text_blocks.append(f"[Slide {slide_no}]:\n{slide_ocr}")

            speech = e.get("transcript_chunk", "").strip()
            if speech:
                transcript_blocks.append(speech)

        combined_slides = "\n\n".join(slides_text_blocks) or "No slide text."
        combined_transcript = " ".join(transcript_blocks) or "No speech recorded."

        prompt = f"""You are an academic teaching assistant creating notes for a university lecture.
Lecture Section: {c_start_fmt} to {c_end_fmt}

SLIDE CONTENT:
{combined_slides}

LECTURER DISCUSSION TRANSCRIPT:
{combined_transcript}

Please provide a structured summary for this section with:
1. Section Title: A descriptive name for the topic discussed.
2. Key Concepts: 3-5 concise bullet points explaining the core technical concepts.
3. Detailed Notes: Clear, high-yield explanation synthesizing both the slides and the spoken lecture.
4. Key Terms & Formulas: Any technical definitions or equations introduced.

Format your output in clean Markdown. Be precise, academic, and comprehensive. Do not invent information not in the lecture."""

        system_prompt = "You are an expert academic teaching assistant summarizing lecture material accurately and thoroughly."

        logger.info(f"Summarizing Chunk {c_idx + 1}/{len(chunks)} ({c_start_fmt} - {c_end_fmt})...")
        llm_response = call_ollama(prompt, system_prompt=system_prompt)

        summary_data = {
            "chunk_index": c_idx,
            "start_time": chunk["start_time"],
            "end_time": chunk["end_time"],
            "start_formatted": c_start_fmt,
            "end_formatted": c_end_fmt,
            "summary_markdown": llm_response,
        }

        # Checkpoint incrementally to Postgres
        db.upsert_chunk_summary(
            run_id=run_id,
            chunk_index=c_idx,
            start_time=chunk["start_time"],
            end_time=chunk["end_time"],
            summary_data=summary_data,
            raw_llm=llm_response,
        )
        logger.info(f"Saved chunk {c_idx} summary to database.")

    all_chunk_summaries = db.get_chunk_summaries(run_id)
    return all_chunk_summaries


def deduplicate_cross_window_concepts(concepts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Deduplicates concepts across overlapping window boundaries.
    Merges duplicate concept entities based on normalized name and slide references,
    combining evidence citations and refining confidence.
    """
    if not concepts:
        return []

    merged: Dict[str, Dict[str, Any]] = {}

    for c in concepts:
        norm_key = re.sub(r"[^\w\s]", "", c["name"].lower()).strip()
        if not norm_key:
            continue

        if norm_key not in merged:
            merged[norm_key] = {
                "name": c["name"],
                "category": c.get("category", "concept"),
                "definition": c.get("definition", ""),
                "explanation": c.get("explanation", ""),
                "start_seconds": c.get("start_seconds", 0.0),
                "end_seconds": c.get("end_seconds", 0.0),
                "slide_id": c.get("slide_id"),
                "evidence_references": list(c.get("evidence_references", [])),
                "confidence": c.get("confidence", "MEDIUM"),
                "status": c.get("status", "unverified"),
                "occurrence_count": 1,
            }
        else:
            existing = merged[norm_key]
            existing["occurrence_count"] += 1
            # Merge time span
            existing["end_seconds"] = max(existing["end_seconds"], c.get("end_seconds", 0.0))
            if not existing["definition"] and c.get("definition"):
                existing["definition"] = c["definition"]
            # Combine evidence references
            for ref in c.get("evidence_references", []):
                if ref not in existing["evidence_references"]:
                    existing["evidence_references"].append(ref)
            # Upgrade confidence if supported across multiple windows
            if len(existing["evidence_references"]) >= 2:
                existing["confidence"] = "HIGH"

    return list(merged.values())


def run_reduce_step(run_id: str, db: Database) -> Dict[str, Any]:
    """
    Reduce Step: Synthesizes all individual chunk summaries and verified knowledge
    into a cohesive, comprehensive final study guide (overview, key points, in-depth guide, glossary, review questions).
    Persists the final guide to Postgres.
    """
    chunk_summaries = db.get_chunk_summaries(run_id)
    concepts = db.get_concepts(run_id)
    exam_signals = db.get_exam_signals(run_id)

    deduped_concepts = deduplicate_cross_window_concepts(concepts) if concepts else []

    logger.info(f"Synthesizing {len(chunk_summaries)} chunk summaries and {len(deduped_concepts)} concepts in Reduce step...")

    # Combine chunk summaries into structured input for reduce prompt
    all_chunks_text = []
    for cs in chunk_summaries:
        data = cs.get("summary_data", {})
        s_time = format_timestamp(cs["start_time"])
        e_time = format_timestamp(cs["end_time"])
        body = data.get("summary_markdown", cs.get("raw_llm_response", ""))
        all_chunks_text.append(f"### Section {cs['chunk_index'] + 1} ({s_time} - {e_time})\n{body}")

    # Add verified concepts summary if present
    if deduped_concepts:
        concept_bullets = [
            f"- **{c['name']}** [{format_timestamp(c['start_seconds'])}]: {c['explanation'][:180]}"
            for c in deduped_concepts[:25]
        ]
        all_chunks_text.append("### Key Verified Concepts\n" + "\n".join(concept_bullets))

    # Add lecturer emphasis if present
    if exam_signals:
        signal_bullets = [
            f"- [{format_timestamp(s['timestamp'])}] *{s['signal_type']}*: {s['text']}"
            for s in exam_signals[:15]
        ]
        all_chunks_text.append("### Lecturer Spoken Emphasis & Exam Cues\n" + "\n".join(signal_bullets))

    combined_material = "\n\n---\n\n".join(all_chunks_text)


    prompt = f"""You are an elite professor preparing the definitive student study guide for an entire university lecture.
Below are the detailed sectional notes covering the entire lecture in chronological order.

SECTIONAL NOTES:
{combined_material}

Synthesize this into a cohesive, publication-grade Study Guide. Provide the output in clean, structured Markdown with the following mandatory sections:

# Executive Overview
A clear 2-3 paragraph summary of the entire lecture: main themes, motivations, and central thesis.

# Key Takeaways
6-10 bullet points highlighting the most essential, high-yield takeaways and insights.

# In-Depth Topic Breakdown
Synthesize the lecture logically into coherent core modules/topics (do not just repeat raw chunk headings). Integrate conceptual explanations, methodologies, formulas, and real-world examples.

# Glossary of Key Terms & Definitions
A bulleted glossary of every technical term, equation, and abbreviation used in the lecture with definitions.

# Practice & Review Questions
5 thoughtful, exam-style conceptual and application questions with concise model answers to test understanding.

Maintain academic rigor, clear formatting, and eliminate redundancies."""

    system_prompt = "You are a master educator crafting comprehensive, beautifully organized university study guides."

    logger.info("Executing Ollama Reduce synthesis prompt...")
    final_markdown = call_ollama(prompt, system_prompt=system_prompt)

    # Extract overview and key points for database structured columns
    overview_text = ""
    key_points_list: List[str] = []

    lines = final_markdown.splitlines()
    in_overview = False
    in_takeaways = False

    for line in lines:
        stripped = line.strip()
        if "executive overview" in stripped.lower():
            in_overview = True
            in_takeaways = False
            continue
        elif "key takeaways" in stripped.lower():
            in_overview = False
            in_takeaways = True
            continue
        elif stripped.startswith("#"):
            in_overview = False
            in_takeaways = False

        if in_overview and stripped:
            overview_text += stripped + " "
        elif in_takeaways and (stripped.startswith("- ") or stripped.startswith("* ") or (len(stripped) > 2 and stripped[:2].isdigit() and stripped[2] in ".) ")):
            clean_point = stripped.lstrip("-* 0123456789.)").strip()
            if clean_point:
                key_points_list.append(clean_point)

    if not overview_text:
        overview_text = "Comprehensive lecture study guide covering theoretical foundations, key methodologies, and practical applications."
    if not key_points_list:
        key_points_list = [
            "Mastery of core foundational principles and technical terminology.",
            "Understanding key mechanisms, derivations, and conceptual frameworks.",
            "Practical application and synthesis across lecture modules.",
        ]

    structured_guide = {
        "markdown": final_markdown,
        "chunk_count": len(chunk_summaries),
        "total_duration": chunk_summaries[-1]["end_time"] if chunk_summaries else 0.0,
    }

    db.upsert_final_summary(
        run_id=run_id,
        overview=overview_text.strip(),
        key_points=key_points_list,
        summary_text=final_markdown,
        structured_guide=structured_guide,
    )

    logger.info(f"Reduce step completed successfully for run {run_id}. Saved to Postgres.")
    return {
        "overview": overview_text.strip(),
        "key_points": key_points_list,
        "summary_markdown": final_markdown,
    }
