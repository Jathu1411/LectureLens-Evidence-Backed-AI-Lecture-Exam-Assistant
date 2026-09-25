"""
Stage 4: Visual Path (OCR & Vision Fallback)
Extracts slide text using Tesseract OCR.
Falls back to a local vision-LLM via Ollama (e.g. llama3.2-vision or llava)
if plain OCR output looks unreliable (equations, diagrams, handwriting, low confidence).
Persists slide text incrementally to Postgres.
"""

import base64
import logging
from pathlib import Path
from typing import Dict, Optional, Tuple

import cv2
import numpy as np
import pytesseract
import requests

from pipeline.config import (
    OCR_MIN_ALPHA_RATIO,
    OCR_MIN_CHARS,
    OLLAMA_BASE_URL,
    OLLAMA_TIMEOUT,
    OLLAMA_VISION_MODEL,
    TESSERACT_CMD,
)
from pipeline.db import Database

logger = logging.getLogger("pipeline.ocr")

# Configure tesseract executable if customized
pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD


def preprocess_for_ocr(image_bgr: np.ndarray) -> np.ndarray:
    """Applies grayscale and adaptive thresholding for cleaner OCR."""
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    # Contrast adjustment
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    return enhanced


def assess_ocr_quality(text: str, avg_conf: float) -> bool:
    """
    Returns True if OCR output is reliable.
    Returns False if unreliable (e.g. equations, diagrams, handwriting, garbage characters).
    """
    clean_text = text.strip()
    if len(clean_text) < OCR_MIN_CHARS:
        return False

    alpha_count = sum(1 for c in clean_text if c.isalnum() or c.isspace())
    alpha_ratio = alpha_count / max(1, len(clean_text))
    if alpha_ratio < OCR_MIN_ALPHA_RATIO:
        return False

    if avg_conf < 45.0:
        return False

    return True


def call_ollama_vision(image_path: str, model: str = OLLAMA_VISION_MODEL) -> Optional[str]:
    """
    Sends the slide image to a local Ollama vision model to transcribe complex visuals,
    diagrams, charts, and equations.
    """
    try:
        with open(image_path, "rb") as f:
            b64_image = base64.b64encode(f.read()).decode("utf-8")

        prompt = (
            "Analyze this lecture slide. Transcribe all text, code snippets, "
            "mathematical equations, labels, and bullet points. If there are diagrams, "
            "charts, or workflows, briefly describe their structure and key takeaways. "
            "Provide clean, structured markdown."
        )

        payload = {
            "model": model,
            "prompt": prompt,
            "images": [b64_image],
            "stream": False,
        }

        logger.info(f"Calling Ollama vision fallback ({model}) for {Path(image_path).name}...")
        resp = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json=payload,
            timeout=OLLAMA_TIMEOUT,
        )
        if resp.status_code == 200:
            result = resp.json().get("response", "").strip()
            logger.info(f"Ollama vision returned {len(result)} chars.")
            return result
        else:
            logger.warning(f"Ollama vision request failed with code {resp.status_code}: {resp.text}")
            return None
    except Exception as e:
        logger.warning(f"Failed to query Ollama vision fallback: {e}")
        return None


def run_ocr_on_slides(run_id: str, db: Database, resume: bool = True) -> int:
    """
    Processes all detected slides for run_id that do not yet have OCR text.
    Reuses OCR results across recurring slide clusters without re-running Tesseract.
    Updates each slide incrementally in Postgres.
    """
    slides = db.get_slides(run_id)
    if not slides:
        logger.warning(f"No slides found for run {run_id}. Run slide detection first.")
        return 0

    processed_count = 0
    reused_cluster_count = 0
    tesseract_count = 0
    vision_count = 0

    # Build cluster OCR cache from existing slides that already have OCR text
    cluster_ocr_cache: Dict[int, Tuple[str, float, str]] = {}
    for s in slides:
        cid = s.get("cluster_id") or s["slide_index"]
        if s.get("ocr_text") and len(s["ocr_text"].strip()) > 0:
            cluster_ocr_cache[cid] = (s["ocr_text"], float(s.get("ocr_confidence") or 0.0), s.get("source", "tesseract"))

    for slide in slides:
        slide_id = slide["id"]
        frame_path = slide["frame_path"]
        existing_text = slide.get("ocr_text")
        cid = slide.get("cluster_id") or slide["slide_index"]

        if resume and existing_text is not None and len(existing_text.strip()) > 0:
            continue

        # Cluster Deduplication Check: if another appearance of this slide was already OCR'd, reuse it
        if cid in cluster_ocr_cache:
            cached_text, cached_conf, cached_src = cluster_ocr_cache[cid]
            db.update_slide_ocr(
                slide_id=slide_id,
                ocr_text=cached_text,
                confidence=cached_conf,
                source=f"{cached_src}_reused",
            )
            reused_cluster_count += 1
            processed_count += 1
            logger.info(f"Slide {slide['slide_index']} inherited OCR from cluster #{cid} ({len(cached_text)} chars)")
            continue

        if not Path(frame_path).exists():
            logger.warning(f"Slide frame image not found: {frame_path}")
            continue

        img_bgr = cv2.imread(frame_path)
        if img_bgr is None:
            continue

        # 1. Plain Tesseract OCR
        ocr_text = ""
        avg_conf = 0.0
        source = "tesseract"

        try:
            preprocessed = preprocess_for_ocr(img_bgr)
            data = pytesseract.image_to_data(
                preprocessed, output_type=pytesseract.Output.DICT
            )
            confidences = [
                float(c) for c in data["conf"] if str(c).replace(".", "", 1).isdigit() and float(c) >= 0
            ]
            avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
            ocr_text = pytesseract.image_to_string(preprocessed).strip()
            tesseract_count += 1
        except Exception as e:
            logger.warning(f"Tesseract OCR failed on {frame_path}: {e}")
            ocr_text = ""
            avg_conf = 0.0

        # 2. Check reliability
        is_reliable = assess_ocr_quality(ocr_text, avg_conf)

        # 3. Vision-LLM Fallback if unreliable
        if not is_reliable:
            logger.info(
                f"Slide {slide['slide_index']} OCR deemed unreliable "
                f"(chars={len(ocr_text)}, conf={avg_conf:.1f}). Attempting vision LLM fallback..."
            )
            vision_result = call_ollama_vision(frame_path)
            if vision_result:
                ocr_text = vision_result
                source = "ollama_vision"
                avg_conf = 95.0
                vision_count += 1

        # 4. Incremental Postgres update
        db.update_slide_ocr(
            slide_id=slide_id,
            ocr_text=ocr_text,
            confidence=avg_conf,
            source=source,
        )
        cluster_ocr_cache[cid] = (ocr_text, avg_conf, source)
        processed_count += 1
        logger.info(
            f"Processed slide {slide['slide_index']} ({source}, {len(ocr_text)} chars, conf={avg_conf:.1f})"
        )

    logger.info(
        f"OCR stage complete for run {run_id}. Processed: {processed_count}, "
        f"Tesseract: {tesseract_count}, Vision Fallback: {vision_count}, Cluster Reused: {reused_cluster_count}"
    )
    return processed_count

