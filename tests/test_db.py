"""
Unit tests for Database state persistence and incremental checkpointing.
"""

import tempfile
from pathlib import Path
import pytest

from pipeline.db import Database


def test_db_run_lifecycle(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db_path = Path(tmpdir) / "test.db"
        monkeypatch.setattr("pipeline.db.DB_TYPE", "sqlite")
        monkeypatch.setattr("pipeline.db.SQLITE_PATH", test_db_path)

        db = Database()
        run_id = "test_run_001"
        video_path = "/path/to/lecture.mp4"

        # 1. Create run
        run = db.create_or_get_run(run_id, video_path)
        assert run["id"] == run_id
        assert run["video_path"] == video_path
        assert run["status"] == "in_progress"

        # 2. Update stage
        db.update_run_stage(run_id, stage="ingestion", status="in_progress", duration=120.5)
        run_updated = db.get_run(run_id)
        assert run_updated["current_stage"] == "ingestion"
        assert run_updated["total_duration"] == 120.5

        # 3. Incremental audio segments
        seg_batch_1 = [
            {"index": 1, "start": 0.0, "end": 4.5, "text": "Welcome to class."},
            {"index": 2, "start": 4.5, "end": 9.2, "text": "Today we cover algorithms."},
        ]
        db.insert_audio_segments(run_id, seg_batch_1)
        assert db.get_latest_transcription_time(run_id) == 9.2

        seg_batch_2 = [
            {"index": 3, "start": 9.2, "end": 14.8, "text": "Let us look at slide one."},
        ]
        db.insert_audio_segments(run_id, seg_batch_2)
        assert db.get_latest_transcription_time(run_id) == 14.8

        segments = db.get_audio_segments(run_id)
        assert len(segments) == 3

        # 4. Incremental slides
        db.insert_slide(run_id, slide_index=1, timestamp=0.0, frame_path="/tmp/s1.jpg")
        db.insert_slide(run_id, slide_index=2, timestamp=45.0, frame_path="/tmp/s2.jpg")
        assert db.get_latest_slide_timestamp(run_id) == 45.0

        slides = db.get_slides(run_id)
        assert len(slides) == 2

        # 5. Slide OCR update
        db.update_slide_ocr(slide_id=slides[0]["id"], ocr_text="Introduction to Algorithms", confidence=92.5)
        slides_updated = db.get_slides(run_id)
        assert slides_updated[0]["ocr_text"] == "Introduction to Algorithms"
        assert slides_updated[0]["ocr_confidence"] == 92.5

        # 6. Chunk summaries and final summary
        db.upsert_chunk_summary(
            run_id=run_id,
            chunk_index=0,
            start_time=0.0,
            end_time=60.0,
            summary_data={"title": "Introduction", "summary_markdown": "Intro content"},
        )
        assert db.get_completed_chunk_indices(run_id) == [0]

        db.upsert_final_summary(
            run_id=run_id,
            overview="Lecture overview",
            key_points=["Point 1", "Point 2"],
            summary_text="Full summary markdown",
            structured_guide={"topic": "Algorithms"},
            pdf_path="/tmp/guide.pdf",
        )
        final = db.get_final_summary(run_id)
        assert final["overview"] == "Lecture overview"
        assert len(final["key_points"]) == 2
        assert final["pdf_path"] == "/tmp/guide.pdf"
