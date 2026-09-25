"""
Unit tests for WeasyPrint PDF rendering and HTML conversion.
"""

import tempfile
from pathlib import Path
import pytest

from pipeline.db import Database
from pipeline.render_pdf import markdown_to_html_simple, render_study_guide_pdf


def test_markdown_to_html_simple():
    md = "# Heading 1\n## Heading 2\n- Item 1\n- Item 2\n\nParagraph text with **bold**."
    res = markdown_to_html_simple(md)
    assert "<h1>Heading 1</h1>" in res
    assert "<h2>Heading 2</h2>" in res
    assert "<li>Item 1</li>" in res
    assert "<strong>bold</strong>" in res


def test_render_study_guide_pdf(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        monkeypatch.setattr("pipeline.db.DB_TYPE", "sqlite")
        monkeypatch.setattr("pipeline.db.SQLITE_PATH", tmp_path / "test.db")
        monkeypatch.setattr("pipeline.config.OUTPUT_DIR", tmp_path / "output")

        db = Database()
        run_id = "test_pdf_run"
        db.create_or_get_run(run_id, video_path="/fake/lecture.mp4")
        db.update_run_stage(run_id, stage="summarization", status="in_progress", duration=300.0)

        # Add mock slide
        db.insert_slide(run_id, slide_index=1, timestamp=0.0, frame_path="")
        slide_row = db.get_slides(run_id)[0]
        db.update_slide_ocr(slide_row["id"], ocr_text="Slide 1: Foundations", confidence=95.0)

        # Add mock summary
        db.upsert_final_summary(
            run_id=run_id,
            overview="Test lecture on foundations of machine learning.",
            key_points=["Key takeaway A", "Key takeaway B"],
            summary_text="# Foundations\nDiscussion of core algorithms and principles.",
            structured_guide={"topic": "ML"},
        )

        pdf_path = render_study_guide_pdf(run_id, db)
        assert Path(pdf_path).exists()
        assert Path(pdf_path).stat().st_size > 1000
