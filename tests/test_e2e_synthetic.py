"""
End-to-end pipeline test using a synthetic lecture video generated with ffmpeg.
"""

import subprocess
import tempfile
from pathlib import Path
import pytest

from pipeline.cli import (
    run_stage_align,
    run_stage_export_pdf,
    run_stage_ingest,
    run_stage_ocr,
    run_stage_slides,
    run_stage_transcribe,
)
from pipeline.db import Database


def create_synthetic_video(output_mp4: Path):
    """
    Creates a 6-second synthetic lecture video with 2 distinct slides (3s each)
    using OpenCV for frames and ffmpeg to add audio.
    Slide 1: Navy background with 'SLIDE 1: MACHINE LEARNING'
    Slide 2: Dark red background with 'SLIDE 2: NEURAL NETWORKS'
    """
    import cv2
    import numpy as np

    temp_video = output_mp4.parent / "temp_silent.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(str(temp_video), fourcc, 10.0, (640, 360))

    # Slide 1 (30 frames = 3 sec)
    for _ in range(30):
        frame1 = np.full((360, 640, 3), (128, 0, 0), dtype=np.uint8)  # Navy
        cv2.putText(frame1, "SLIDE 1: MACHINE LEARNING", (60, 180), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
        out.write(frame1)

    # Slide 2 (30 frames = 3 sec)
    for _ in range(30):
        frame2 = np.full((360, 640, 3), (0, 0, 128), dtype=np.uint8)  # Dark red
        cv2.putText(frame2, "SLIDE 2: NEURAL NETWORKS", (60, 180), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
        out.write(frame2)

    out.release()

    # Add a short sine audio track using ffmpeg
    cmd = [
        "ffmpeg",
        "-i", str(temp_video),
        "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        "-y",
        str(output_mp4),
    ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    temp_video.unlink(missing_ok=True)


def test_e2e_synthetic_pipeline(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        video_path = tmp_path / "synthetic_lecture.mp4"
        create_synthetic_video(video_path)
        assert video_path.exists()

        monkeypatch.setattr("pipeline.db.DB_TYPE", "sqlite")
        monkeypatch.setattr("pipeline.db.SQLITE_PATH", tmp_path / "test.db")
        monkeypatch.setattr("pipeline.config.OUTPUT_DIR", tmp_path / "output")

        db = Database()
        run_id = "test_synthetic_e2e"
        db.create_or_get_run(run_id, str(video_path))

        # 1. Ingestion
        probe_info = run_stage_ingest(str(video_path), run_id, db)
        assert probe_info["duration"] >= 5.5
        audio_path = tmp_path / "output" / run_id / "audio.wav"
        assert audio_path.exists()

        # 2. Slide detection
        slide_count = run_stage_slides(str(video_path), run_id, db)
        assert slide_count >= 2

        # 3. OCR
        run_stage_ocr(run_id, db)
        slides = db.get_slides(run_id)
        assert len(slides) >= 2

        # Add sample transcript segments
        db.insert_audio_segments(run_id, [
            {"index": 1, "start": 0.5, "end": 2.5, "text": "Slide one discussion."},
            {"index": 2, "start": 3.5, "end": 5.5, "text": "Slide two discussion."},
        ])

        # 4. Alignment
        timeline_count = run_stage_align(run_id, db)
        assert timeline_count >= 2

        # 5. Add mock summary for PDF export test
        db.upsert_final_summary(
            run_id=run_id,
            overview="Comprehensive synthetic lecture covering ML fundamentals.",
            key_points=["Core architecture", "Model training dynamics"],
            summary_text="# Synthetic Lecture Notes\nDetailed notes on neural networks and optimization.",
            structured_guide={"topic": "Neural Networks"},
        )

        # 6. PDF Export
        pdf_path = run_stage_export_pdf(run_id, db)
        assert Path(pdf_path).exists()
        assert Path(pdf_path).stat().st_size > 1000

        # Check run status in DB
        run_record = db.get_run(run_id)
        assert run_record["status"] == "completed"
