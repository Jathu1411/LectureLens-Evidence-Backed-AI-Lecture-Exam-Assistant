"""
Stage 2: Slide Detection & Visual Filtering
Combines Presentation ROI auto-detection, fast 64-bit perceptual hashing (pHash),
temporal persistence validation (2.5s stability), SSIM confirmation, and visual clustering.
Saves only one high-quality representative frame per distinct slide, checkpointing to Postgres.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from pipeline import config
from pipeline.config import (
    FRAME_SAMPLE_FPS,
    MIN_SLIDE_DURATION_SEC,
    PHASH_THRESHOLD,
    SLIDE_SSIM_THRESHOLD,
    TEMPORAL_PERSISTENCE_SEC,
)
from pipeline.db import Database
from pipeline.ingest import stream_sampled_frames
from pipeline.visual_filter import (
    calculate_frame_quality,
    compute_phash,
    crop_to_roi,
    detect_presentation_roi,
    find_matching_slide_cluster,
    hamming_distance,
    is_noise_frame,
)

logger = logging.getLogger("pipeline.slides")


def compute_ssim_fast(gray1: np.ndarray, gray2: np.ndarray) -> float:
    """
    Computes Structural Similarity Index (SSIM) between two grayscale images.
    Uses downsampled arrays for fast real-time processing of long videos.
    """
    target_size = (320, 180)
    g1 = cv2.resize(gray1, target_size).astype(np.float32)
    g2 = cv2.resize(gray2, target_size).astype(np.float32)

    C1 = (0.01 * 255) ** 2
    C2 = (0.03 * 255) ** 2

    mu1 = cv2.GaussianBlur(g1, (11, 11), 1.5)
    mu2 = cv2.GaussianBlur(g2, (11, 11), 1.5)

    mu1_sq = mu1 * mu1
    mu2_sq = mu2 * mu2
    mu1_mu2 = mu1 * mu2

    sigma1_sq = cv2.GaussianBlur(g1 * g1, (11, 11), 1.5) - mu1_sq
    sigma2_sq = cv2.GaussianBlur(g2 * g2, (11, 11), 1.5) - mu2_sq
    sigma12 = cv2.GaussianBlur(g1 * g2, (11, 11), 1.5) - mu1_mu2

    numerator = (2 * mu1_mu2 + C1) * (2 * sigma12 + C2)
    denominator = (mu1_sq + mu2_sq + C1) * (sigma1_sq + sigma2_sq + C2)
    ssim_map = numerator / denominator
    return float(np.mean(ssim_map))


def detect_slides(
    video_path: str,
    run_id: str,
    db: Database,
    sample_fps: float = FRAME_SAMPLE_FPS,
    threshold: float = SLIDE_SSIM_THRESHOLD,
    min_slide_duration: float = MIN_SLIDE_DURATION_SEC,
    start_time: float = 0.0,
    end_time: Optional[float] = None,
    roi_bbox: Optional[Dict[str, Any]] = None,
    resume: bool = True,
) -> int:
    """
    Runs multi-tier slide detection on the video stream.
    Applies ROI cropping -> pHash pre-filter -> temporal stability check -> SSIM confirmation -> visual clustering.
    Persists distinct slides incrementally to the database and file system.
    Returns the total number of detected slides.
    """
    slides_dir = config.OUTPUT_DIR / run_id / "slides"
    slides_dir.mkdir(parents=True, exist_ok=True)

    scan_start = start_time
    slide_index = 0

    if resume:
        existing_slides = db.get_slides(run_id)
        if existing_slides:
            slide_index = len(existing_slides)
            latest_time = db.get_latest_slide_timestamp(run_id)
            if latest_time > scan_start:
                scan_start = latest_time + min_slide_duration
                logger.info(
                    f"Resuming slide detection for run {run_id}: "
                    f"{slide_index} slides found. Scanning from {scan_start:.1f}s."
                )

    # Detect presentation ROI if not provided
    if roi_bbox is None:
        roi_bbox = detect_presentation_roi(video_path)

    last_saved_slide_gray: Optional[np.ndarray] = None
    last_saved_phash: Optional[str] = None
    last_saved_timestamp: float = -1.0

    # Temporal persistence tracking: candidate frame waiting to be confirmed
    pending_candidate_frame: Optional[np.ndarray] = None
    pending_candidate_gray: Optional[np.ndarray] = None
    pending_candidate_time: float = -1.0
    pending_candidate_phash: Optional[str] = None

    frame_generator = stream_sampled_frames(
        video_path, sample_fps=sample_fps, start_time=scan_start, end_time=end_time
    )

    existing_clusters = db.get_slides(run_id)

    def commit_slide(candidate_frame: np.ndarray, timestamp: float, phash: str):
        nonlocal slide_index, last_saved_slide_gray, last_saved_phash, last_saved_timestamp
        slide_index += 1
        filename = f"slide_{slide_index:04d}_{int(timestamp):06d}s.jpg"
        save_path = slides_dir / filename

        # Compute quality score
        quality = calculate_frame_quality(candidate_frame)

        # Check for matching visual cluster
        matching = find_matching_slide_cluster(phash, existing_clusters, threshold=PHASH_THRESHOLD)
        if matching:
            cluster_id = matching.get("cluster_id") or matching["id"]
            app_count = matching.get("appearance_count", 1) + 1
            db.update_slide_appearance(matching["id"], timestamp, app_count)
            logger.info(
                f"Slide {slide_index} matched existing cluster #{cluster_id} "
                f"(revisit at {timestamp:.1f}s, appearance #{app_count})"
            )
        else:
            cluster_id = slide_index

        # Save high-res JPEG image
        cv2.imwrite(str(save_path), candidate_frame, [cv2.IMWRITE_JPEG_QUALITY, 90])

        # Persist incrementally to database
        new_slide_id = db.insert_slide(
            run_id=run_id,
            slide_index=slide_index,
            timestamp=timestamp,
            frame_path=str(save_path),
            phash=phash,
            cluster_id=cluster_id,
            roi_bbox=roi_bbox,
            quality_score=quality,
            is_diagram=False,
            first_seen=timestamp,
            last_seen=timestamp,
            appearance_count=1,
        )

        existing_clusters.append({
            "id": new_slide_id,
            "cluster_id": cluster_id,
            "phash": phash,
            "appearance_count": 1,
            "timestamp": timestamp,
        })

        last_saved_slide_gray = cv2.cvtColor(crop_to_roi(candidate_frame, roi_bbox), cv2.COLOR_BGR2GRAY)
        last_saved_phash = phash
        last_saved_timestamp = timestamp
        logger.info(f"Saved slide {slide_index} (timestamp={timestamp:.1f}s, quality={quality}) to {save_path.name}")

    for timestamp, raw_frame_bgr in frame_generator:
        # 1. Filter pure noise / blank frames
        if is_noise_frame(raw_frame_bgr):
            continue

        # 2. Presentation ROI crop
        cropped_bgr = crop_to_roi(raw_frame_bgr, roi_bbox)
        gray = cv2.cvtColor(cropped_bgr, cv2.COLOR_BGR2GRAY)
        current_phash = compute_phash(gray)

        # First frame of scan is always accepted
        if last_saved_slide_gray is None:
            commit_slide(raw_frame_bgr, timestamp, current_phash)
            continue

        # Check temporal persistence buffer if a candidate is pending
        if pending_candidate_frame is not None:
            time_since_candidate = timestamp - pending_candidate_time
            # Compare current frame to the candidate frame
            candidate_similarity = compute_ssim_fast(pending_candidate_gray, gray)

            if candidate_similarity >= 0.92:
                # Frame remained stable across persistence window
                if time_since_candidate >= TEMPORAL_PERSISTENCE_SEC:
                    commit_slide(pending_candidate_frame, pending_candidate_time, pending_candidate_phash)
                    pending_candidate_frame = None
                    pending_candidate_gray = None
                    pending_candidate_time = -1.0
            else:
                # Still animating or transitioning, reset candidate to current frame
                pending_candidate_frame = raw_frame_bgr.copy()
                pending_candidate_gray = gray
                pending_candidate_time = timestamp
                pending_candidate_phash = current_phash
            continue

        # Fast Filter: pHash distance check (filters out frames with <= 3 bit diff instantly)
        time_since_last = timestamp - last_saved_timestamp
        if time_since_last >= min_slide_duration:
            h_dist = hamming_distance(current_phash, last_saved_phash or "")
            if h_dist >= 4:
                # Potential change detected via pHash -> confirm with SSIM
                ssim_val = compute_ssim_fast(last_saved_slide_gray, gray)
                if ssim_val < threshold:
                    logger.debug(
                        f"Candidate slide change at {timestamp:.1f}s: pHash dist={h_dist}, SSIM={ssim_val:.3f}"
                    )
                    # Start temporal persistence buffer
                    pending_candidate_frame = raw_frame_bgr.copy()
                    pending_candidate_gray = gray
                    pending_candidate_time = timestamp
                    pending_candidate_phash = current_phash

    # Flush any remaining settled candidate at end of stream
    if pending_candidate_frame is not None:
        commit_slide(pending_candidate_frame, pending_candidate_time, pending_candidate_phash)

    total_slides = len(db.get_slides(run_id))
    logger.info(f"Slide detection complete for run {run_id}. Total slides in DB: {total_slides}")
    return total_slides
