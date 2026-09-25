"""
End-to-end integration test for the windowed personal exam assistant pipeline.
Verifies virtual window planning, concurrent audio/visual execution,
deduplication, PDF generation, and lecture statistics engine.
"""

import tempfile
from pathlib import Path
import pytest

from pipeline.cli import run_windowed_pipeline
from pipeline.db import Database
from tests.test_e2e_synthetic import create_synthetic_video


def test_e2e_windowed_pipeline_synthetic(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        video_path = tmp_path / "synthetic_windowed.mp4"
        create_synthetic_video(video_path)
        assert video_path.exists()

        monkeypatch.setattr("pipeline.db.DB_TYPE", "sqlite")
        monkeypatch.setattr("pipeline.db.SQLITE_PATH", tmp_path / "windowed.db")
        monkeypatch.setattr("pipeline.config.OUTPUT_DIR", tmp_path / "output")

        # Mock transcribe_audio to avoid loading heavy Faster-Whisper model in CI test
        def mock_transcribe(audio_path, run_id, db, start_time_offset=0.0, resume=True):
            db.insert_audio_segments(run_id, [
                {
                    "index": 1,
                    "start": start_time_offset + 0.5,
                    "end": start_time_offset + 2.0,
                    "text": "Welcome to neural networks, remember this rule because it will be on the exam.",
                },
                {
                    "index": 2,
                    "start": start_time_offset + 2.1,
                    "end": start_time_offset + 3.0,
                    "text": "Pay close attention to how backpropagation computes gradients.",
                }
            ])
            return 2

        monkeypatch.setattr("pipeline.cli.transcribe_audio", mock_transcribe)

        # Mock call_ollama_json in summarize / knowledge to avoid external Ollama dependency
        def mock_call_ollama(prompt, system_prompt=None, model=None):
            return {
                "executive_overview": "This lecture covers machine learning fundamentals and backpropagation.",
                "core_concepts": [{"name": "Backpropagation", "explanation": "Gradient computation algorithm."}],
                "key_definitions": [{"term": "Neural Network", "definition": "A computational model of interconnected nodes."}],
                "detailed_explanations": ["Detailed walkthrough of gradient descent."],
                "important_examples": ["Linear regression with single weight update."],
                "formulas_and_rules": [{"formula": "w = w - eta * grad", "description": "Weight update rule."}],
                "comparisons": [{"topic": "Supervised vs Unsupervised", "differences": "Labels vs unlabeled."}],
                "exam_focus": ["Gradient descent and backpropagation derivation."],
                "potential_exam_questions": ["Derive the backpropagation gradient for a two-layer MLP."],
                "concepts": [
                    {
                        "name": "Backpropagation",
                        "category": "formula",
                        "definition": "Gradient computation rule",
                        "explanation": "Calculates partial derivatives",
                        "transcript_quote": "how backpropagation computes gradients",
                        "start_seconds": 1.0,
                        "end_seconds": 2.5,
                    }
                ]
            }

        def mock_call_ollama_text(prompt, system_prompt=None, model=None):
            return "## Executive Overview\nThis lecture covers machine learning fundamentals and backpropagation.\n\n## Key Takeaways\n- Gradient descent calculates optimal weights.\n\n## Detailed Study Guide\nEverything about neural networks."

        monkeypatch.setattr("pipeline.summarize.call_ollama", mock_call_ollama_text)
        monkeypatch.setattr("pipeline.knowledge.call_ollama_json", mock_call_ollama)

        db = Database()
        run_id = "test_windowed_e2e"

        # Execute windowed pipeline with short windows
        pdf_path = run_windowed_pipeline(
            video_path=str(video_path),
            run_id=run_id,
            db=db,
            window_duration_sec=3.0,
            window_overlap_sec=1.0,
            resume=False,
        )

        assert Path(pdf_path).exists()
        assert Path(pdf_path).stat().st_size > 0

        # Check database records
        run = db.get_run(run_id)
        assert run["status"] == "completed"

        windows = db.get_windows(run_id)
        assert len(windows) >= 2
        for w in windows:
            assert w["status"] == "COMPLETE"

        slides = db.get_slides(run_id)
        assert len(slides) >= 2

        exam_signals = db.get_exam_signals(run_id)
        assert len(exam_signals) >= 1

        concepts = db.get_concepts(run_id)
        assert len(concepts) >= 1

        verif_records = db.get_verification_records(run_id)
        assert len(verif_records) >= 1

        # Check statistics JSON and Markdown artifacts
        stats_json = tmp_path / "output" / run_id / "lecture_statistics.json"
        stats_md = tmp_path / "output" / run_id / "lecture_statistics.md"

        assert stats_json.exists()
        assert stats_md.exists()

        content = stats_md.read_text(encoding="utf-8")
        assert "# Lecture Processing Statistics Report" in content
        assert "Real-Time Factor" in content
