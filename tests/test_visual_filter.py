"""
Unit tests for Advanced Visual Filtering (pHash, ROI, quality, clustering).
"""

import numpy as np
import cv2

from pipeline.visual_filter import (
    calculate_frame_quality,
    compute_phash,
    crop_to_roi,
    find_matching_slide_cluster,
    hamming_distance,
    is_noise_frame,
)


def test_phash_identical_and_distinct():
    # Identical frames
    f1 = np.full((360, 640), 100, dtype=np.uint8)
    cv2.putText(f1, "SLIDE A", (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 255, 2)
    h1 = compute_phash(f1)

    f2 = f1.copy()
    h2 = compute_phash(f2)
    assert h1 == h2
    assert hamming_distance(h1, h2) == 0

    # Distinct slide
    f3 = np.zeros((360, 640), dtype=np.uint8)
    cv2.circle(f3, (300, 180), 80, 255, -1)
    h3 = compute_phash(f3)
    dist = hamming_distance(h1, h3)
    assert dist > 10


def test_frame_quality():
    # Sharp image with high contrast
    sharp_img = np.full((360, 640, 3), 40, dtype=np.uint8)
    cv2.putText(sharp_img, "HIGH CONTRAST SHARP TEXT", (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 3)
    sharp_score = calculate_frame_quality(sharp_img)

    # Blurry image
    blurred_img = cv2.GaussianBlur(sharp_img, (35, 35), 10.0)
    blur_score = calculate_frame_quality(blurred_img)

    assert sharp_score > blur_score


def test_crop_to_roi():
    img = np.zeros((1000, 1000, 3), dtype=np.uint8)
    roi = {"x": 100, "y": 100, "width": 800, "height": 600, "confidence": 0.9}
    cropped = crop_to_roi(img, roi)
    assert cropped.shape == (600, 800, 3)

    # Low confidence ROI falls back to full image
    low_conf_roi = {"x": 100, "y": 100, "width": 800, "height": 600, "confidence": 0.4}
    not_cropped = crop_to_roi(img, low_conf_roi)
    assert not_cropped.shape == (1000, 1000, 3)


def test_noise_frame():
    black_frame = np.zeros((360, 640, 3), dtype=np.uint8)
    assert is_noise_frame(black_frame) is True

    valid_frame = np.full((360, 640, 3), 100, dtype=np.uint8)
    cv2.putText(valid_frame, "LECTURE SLIDE", (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
    assert is_noise_frame(valid_frame) is False


def test_find_matching_slide_cluster():
    hash1 = "0123456789abcdef"
    existing_slides = [
        {"id": 1, "slide_index": 1, "cluster_id": 1, "phash": hash1},
    ]

    # Identical hash matches cluster 1
    matched = find_matching_slide_cluster(hash1, existing_slides)
    assert matched is not None
    assert matched["cluster_id"] == 1

    # Completely different hash does not match
    diff_hash = "fedcba9876543210"
    matched_diff = find_matching_slide_cluster(diff_hash, existing_slides)
    assert matched_diff is None
