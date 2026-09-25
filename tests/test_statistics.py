"""
Unit tests for Lecture Statistics Generation.
"""

import json
from pathlib import Path
import tempfile

from pipeline.db import Database
from pipeline.statistics import generate_lecture_statistics


def test_generate_lecture_statistics(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        monkeypatch.setattr("pipeline.db.DB_TYPE", "sqlite")
        monkeypatch.setattr("pipeline.db.SQLITE_PATH", tmp_path / "stats_test.db")
        monkeypatch.setattr("pipeline.config.OUTPUT_DIR", tmp_path / "output")

        db = Database()
        run_id = "test_stats_run"
        db.create_or_get_run(run_id, "mock_video.mp4")
        db.update_run_stage(run_id, "completed", total_duration=1800.0)

        # Insert sample slides and segments
        db.insert_slide(run_id=run_id, slide_index=1, timestamp=10.0, frame_path="slide1.jpg")
        db.insert_audio_segments(run_id, [{"index": 1, "start": 0.0, "end": 10.0, "text": "Welcome"}])

        t_start = 1000.0
        t_end = 1300.0  # 300 seconds processing

        stats = generate_lecture_statistics(
            run_id=run_id,
            db=db,
            processing_start_time=t_start,
            processing_end_time=t_end,
            stage_timings={"audio_seconds": 120.0, "visual_seconds": 180.0},
        )

        assert stats["lecture_id"] == run_id
        assert stats["video_duration_seconds"] == 1800.0
        assert stats["processing"]["total_processing_seconds"] == 300.0
        # real-time factor: 300 / 1800 = 0.1667
        assert round(stats["processing"]["real_time_factor"], 2) == 0.17

        # Confirm JSON and Markdown files were created on disk
        out_dir = tmp_path / "output" / run_id
        assert (out_dir / "lecture_statistics.json").exists()
        assert (out_dir / "lecture_statistics.md").exists()

        loaded_json = json.loads((out_dir / "lecture_statistics.json").read_text(encoding="utf-8"))
        assert loaded_json["processing"]["real_time_factor"] == stats["processing"]["real_time_factor"]
