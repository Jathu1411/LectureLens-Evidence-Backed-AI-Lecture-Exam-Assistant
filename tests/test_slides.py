"""
Unit tests for slide detection and perceptual similarity.
"""

import numpy as np
import pytest

from pipeline.slides import compute_ssim_fast


def test_compute_ssim_identical_images():
    img = np.random.randint(0, 255, (480, 640), dtype=np.uint8)
    sim = compute_ssim_fast(img, img)
    assert sim >= 0.99


def test_compute_ssim_distinct_images():
    img1 = np.zeros((480, 640), dtype=np.uint8)
    img2 = np.ones((480, 640), dtype=np.uint8) * 255
    sim = compute_ssim_fast(img1, img2)
    assert sim < 0.2
