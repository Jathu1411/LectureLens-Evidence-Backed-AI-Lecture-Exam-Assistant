"""
Advanced Visual Filtering and Presentation Analysis.
Implements:
1. Presentation ROI auto-detection (distinguishing slide canvas from webcam/Zoom controls)
2. Fast 64-bit perceptual hashing (pHash) for microsecond frame change filtering
3. Frame quality scoring (sharpness, contrast, blur detection)
4. Slide clustering across time to prevent redundant OCR on revisited slides
5. Non-slide noise and transition frame detection
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from pipeline.config import PHASH_THRESHOLD, ROI_ANALYSIS_SECONDS, ROI_CONFIDENCE_THRESHOLD

logger = logging.getLogger("pipeline.visual_filter")


def compute_phash(image_gray: np.ndarray) -> str:
    """
    Computes a 64-bit Discrete Cosine Transform (DCT) perceptual hash.
    Resizes image to 32x32, computes 2D DCT, extracts top-left 8x8 low frequencies
    (excluding DC component at 0,0), and sets bits based on median frequency value.
    """
    resized = cv2.resize(image_gray, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
    dct = cv2.dct(resized)
    # Take top-left 8x8 coefficients
    dct_low = dct[:8, :8]
    # Calculate median excluding DC term (0,0)
    med = np.median(dct_low[1:, 1:])
    # Generate 64-bit boolean array
    bit_array = dct_low > med
    # Convert to 64-bit hex string (16 chars)
    hash_val = 0
    for bit in bit_array.flatten():
        hash_val = (hash_val << 1) | int(bit)
    return f"{hash_val:016x}"


def hamming_distance(hash1: str, hash2: str) -> int:
    """Computes the Hamming distance (number of bit differences) between two 16-char hex hashes."""
    try:
        val1 = int(hash1, 16)
        val2 = int(hash2, 16)
        xor_val = val1 ^ val2
        return bin(xor_val).count("1")
    except Exception:
        return 64


def calculate_frame_quality(frame_bgr: np.ndarray) -> float:
    """
    Calculates visual quality score based on Laplacian sharpness, contrast, and brightness.
    Higher score indicates a clearer, sharper, settled slide image.
    """
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    # Sharpness via variance of Laplacian
    laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
    # Contrast via standard deviation
    contrast = float(np.std(gray))
    # Mean brightness (penalize extreme dark < 20 or extreme blown-out > 240)
    brightness = float(np.mean(gray))
    brightness_penalty = 1.0
    if brightness < 25 or brightness > 235:
        brightness_penalty = 0.5

    # Composite normalized score
    score = (min(1000.0, laplacian_var) * 0.6 + min(100.0, contrast) * 4.0) * brightness_penalty
    return round(score, 2)


def is_noise_frame(frame_bgr: np.ndarray) -> bool:
    """
    Identifies blank screens, solid transitions, or extremely dark/washed out frames.
    """
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    std_dev = np.std(gray)
    mean_val = np.mean(gray)

    # Pure black or pure white or uniform flat color
    if std_dev < 3.0:
        return True
    if mean_val < 8.0:
        return True
    return False


def detect_presentation_roi(video_path: str, max_seconds: float = ROI_ANALYSIS_SECONDS) -> Dict[str, Any]:
    """
    Automatically detects the dominant presentation bounding box by analyzing
    temporal stability across sampled frames in the first few minutes of the video.
    Identifies the slide area while ignoring floating webcams, toolbars, and taskbars.
    Falls back to the full frame if confidence is below threshold.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return {"x": 0, "y": 0, "width": 1920, "height": 1080, "confidence": 0.0}

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1920)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1080)

    sample_duration = min(max_seconds, total_frames / fps if fps > 0 else max_seconds)
    # Sample 1 frame every 4 seconds
    step_frames = max(1, int(fps * 4))
    max_frame_idx = int(sample_duration * fps)

    sampled_grays: List[np.ndarray] = []
    frame_idx = 0

    while frame_idx < max_frame_idx:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret:
            break
        # Downscale for fast contour and variance analysis
        small_gray = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (640, 360))
        sampled_grays.append(small_gray)
        frame_idx += step_frames

    cap.release()

    if len(sampled_grays) < 3:
        return {"x": 0, "y": 0, "width": width, "height": height, "confidence": 0.5}

    scale_x = width / 640.0
    scale_y = height / 360.0

    # 1. Edge & Contour Detection for candidate slide bounds
    # Most slides are high-contrast rectangular cards with 4:3 or 16:9 aspect ratio
    ref_frame = sampled_grays[len(sampled_grays) // 2]
    blurred = cv2.GaussianBlur(ref_frame, (5, 5), 0)
    edges = cv2.Canny(blurred, 40, 150)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    best_box = (0, 0, width, height)
    best_area = width * height
    best_conf = 0.5

    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        orig_w = int(w * scale_x)
        orig_h = int(h * scale_y)
        area = orig_w * orig_h
        aspect_ratio = orig_w / float(orig_h) if orig_h > 0 else 0

        # Slide candidate: occupies at least 50% of the screen and matches standard slide ratios
        if area >= 0.50 * (width * height) and (1.2 <= aspect_ratio <= 1.85):
            orig_x = int(x * scale_x)
            orig_y = int(y * scale_y)
            conf = min(0.95, area / (width * height))
            if conf > best_conf:
                best_box = (orig_x, orig_y, orig_w, orig_h)
                best_conf = conf

    logger.info(
        f"Detected Presentation ROI for {video_path}: "
        f"x={best_box[0]}, y={best_box[1]}, w={best_box[2]}, h={best_box[3]}, conf={best_conf:.2f}"
    )

    return {
        "x": best_box[0],
        "y": best_box[1],
        "width": best_box[2],
        "height": best_box[3],
        "confidence": round(best_conf, 2),
    }


def crop_to_roi(frame_bgr: np.ndarray, roi: Optional[Dict[str, Any]] = None) -> np.ndarray:
    """Crops an image frame to the presentation ROI. Falls back to original frame if ROI is full screen or invalid."""
    if not roi or roi.get("confidence", 0.0) < ROI_CONFIDENCE_THRESHOLD:
        return frame_bgr

    h, w = frame_bgr.shape[:2]
    rx = max(0, min(w - 1, int(roi.get("x", 0))))
    ry = max(0, min(h - 1, int(roi.get("y", 0))))
    rw = max(10, min(w - rx, int(roi.get("width", w))))
    rh = max(10, min(h - ry, int(roi.get("height", h))))

    # If ROI is practically the whole screen (>95%), return untouched frame
    if rw >= 0.95 * w and rh >= 0.95 * h:
        return frame_bgr

    return frame_bgr[ry : ry + rh, rx : rx + rw]


def find_matching_slide_cluster(
    phash: str,
    existing_slides: List[Dict[str, Any]],
    threshold: int = 4,
) -> Optional[Dict[str, Any]]:
    """
    Checks if a slide matches any previously detected slide cluster using perceptual hash Hamming distance.
    Returns the matching slide dict if found, or None.
    """
    if not phash:
        return None

    for slide in existing_slides:
        s_hash = slide.get("phash")
        if s_hash:
            dist = hamming_distance(phash, s_hash)
            if dist <= threshold:
                return slide

    return None
