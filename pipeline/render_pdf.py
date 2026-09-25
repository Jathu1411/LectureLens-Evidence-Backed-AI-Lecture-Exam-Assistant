"""
Stage 7: Output (PDF Generation)
Renders the final structured summary and slide references into a publication-grade PDF
via WeasyPrint using an HTML/CSS template.
"""

import html
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# Ensure macOS homebrew library paths (/opt/homebrew/lib) are accessible for Pango/Cairo
if sys.platform == "darwin":
    brew_lib = "/opt/homebrew/lib"
    if os.path.exists(brew_lib):
        curr = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
        if brew_lib not in curr:
            os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = f"{curr}:{brew_lib}" if curr else brew_lib

from jinja2 import Environment, FileSystemLoader

from pipeline import config
from pipeline.config import BASE_DIR, TEMPLATES_DIR
from pipeline.db import Database

logger = logging.getLogger("pipeline.render_pdf")


def markdown_to_html_simple(md_text: str) -> str:
    """
    Lightweight, local markdown-to-HTML converter for lecture notes.
    Converts headings, lists, bold/italic, blockquotes, code blocks.
    No external network calls or heavy parsers needed.
    """
    lines = md_text.splitlines()
    html_lines = []
    in_list = False
    in_code_block = False
    code_buffer = []

    for line in lines:
        stripped = line.strip()

        # Code block toggle
        if stripped.startswith("```"):
            if in_code_block:
                in_code_block = False
                escaped_code = html.escape("\n".join(code_buffer))
                html_lines.append(f"<pre><code>{escaped_code}</code></pre>")
                code_buffer = []
            else:
                in_code_block = True
            continue

        if in_code_block:
            code_buffer.append(line)
            continue

        # Close list if no longer on list item
        if in_list and not (stripped.startswith("- ") or stripped.startswith("* ") or (len(stripped) > 2 and stripped[:2].isdigit() and stripped[2] in ".) ")):
            html_lines.append("</ul>")
            in_list = False

        if not stripped:
            continue

        # Headings
        if stripped.startswith("### "):
            html_lines.append(f"<h3>{html.escape(stripped[4:])}</h3>")
        elif stripped.startswith("## "):
            html_lines.append(f"<h2>{html.escape(stripped[3:])}</h2>")
        elif stripped.startswith("# "):
            html_lines.append(f"<h1>{html.escape(stripped[2:])}</h1>")
        # Blockquote
        elif stripped.startswith("> "):
            html_lines.append(f"<blockquote>{html.escape(stripped[2:])}</blockquote>")
        # Unordered or ordered list item
        elif stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            item_text = html.escape(stripped[2:])
            # Inline bold/italic formatting
            item_text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", item_text)
            item_text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", item_text)
            item_text = re.sub(r"`(.+?)`", r"<code>\1</code>", item_text)
            html_lines.append(f"<li>{item_text}</li>")
        elif len(stripped) > 2 and stripped[:2].isdigit() and stripped[2] in ".) ":
            if not in_list:
                html_lines.append("<ol>")
                in_list = True
            item_text = html.escape(stripped[3:].strip())
            item_text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", item_text)
            item_text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", item_text)
            item_text = re.sub(r"`(.+?)`", r"<code>\1</code>", item_text)
            html_lines.append(f"<li>{item_text}</li>")
        else:
            # Paragraph
            p_text = html.escape(stripped)
            p_text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", p_text)
            p_text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", p_text)
            p_text = re.sub(r"`(.+?)`", r"<code>\1</code>", p_text)
            html_lines.append(f"<p>{p_text}</p>")

    if in_list:
        html_lines.append("</ul>")

    return "\n".join(html_lines)


def format_seconds_to_hms(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h}h {m}m {s}s"
    return f"{m}m {s}s"


def render_study_guide_pdf(run_id: str, db: Database) -> str:
    """
    Renders the study guide to PDF using WeasyPrint.
    Writes the PDF to output/<run_id>/study_guide.pdf and updates Postgres.
    """
    from weasyprint import HTML

    run = db.get_run(run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found in database.")

    summary_row = db.get_final_summary(run_id)
    if not summary_row:
        raise ValueError(f"Final summary for run {run_id} not found. Run summarization first.")

    slides = db.get_slides(run_id)
    for s in slides:
        s["timestamp_formatted"] = format_seconds_to_hms(s["timestamp"])

    output_run_dir = config.OUTPUT_DIR / run_id
    output_run_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = output_run_dir / "study_guide.pdf"

    # Setup Jinja2 template
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("study_guide.html")

    raw_summary_md = summary_row.get("summary_text", "")
    guide_html = markdown_to_html_simple(raw_summary_md)

    duration_str = format_seconds_to_hms(run.get("total_duration") or 0.0)
    date_str = datetime.now().strftime("%B %d, %Y")

    css_path = TEMPLATES_DIR / "style.css"

    concepts = db.get_concepts(run_id)
    for c in concepts:
        c["timestamp_hms"] = format_seconds_to_hms(c.get("start_seconds", 0.0))

    exam_signals = db.get_exam_signals(run_id)
    for sig in exam_signals:
        sig["timestamp_hms"] = format_seconds_to_hms(sig.get("timestamp", 0.0))

    verif_records = db.get_verification_records(run_id)
    verif_stats = None
    if verif_records or concepts:
        total_c = len(verif_records) if verif_records else len(concepts)
        supp = sum(1 for r in verif_records if r.get("status") == "SUPPORTED")
        part = sum(1 for r in verif_records if r.get("status") == "PARTIALLY_SUPPORTED")
        uncert = sum(1 for r in verif_records if r.get("status") == "UNCERTAIN")
        cov = (supp + part) / max(1, total_c) if total_c else 1.0
        verif_stats = {
            "total_claims": total_c,
            "supported": supp,
            "partially_supported": part,
            "uncertain": uncert,
            "evidence_coverage": cov,
        }

    rendered_html = template.render(
        title=f"Lecture Study Guide - {Path(run['video_path']).stem}",
        overview=summary_row.get("overview", ""),
        key_points=summary_row.get("key_points", []),
        guide_html=guide_html,
        concepts=concepts,
        exam_signals=exam_signals,
        verification_stats=verif_stats,
        evidence_coverage=verif_stats["evidence_coverage"] if verif_stats else 1.0,
        slides=slides,
        duration_str=duration_str,
        date_str=date_str,
        run_id=run_id,
        css_path=str(css_path),
    )


    # Save debug HTML alongside PDF
    html_debug_path = output_run_dir / "study_guide.html"
    html_debug_path.write_text(rendered_html, encoding="utf-8")

    logger.info(f"Rendering PDF with WeasyPrint: {pdf_path}...")
    HTML(string=rendered_html, base_url=str(BASE_DIR)).write_pdf(str(pdf_path))

    # Update database with PDF path
    db.upsert_final_summary(
        run_id=run_id,
        overview=summary_row.get("overview", ""),
        key_points=summary_row.get("key_points", []),
        summary_text=summary_row.get("summary_text", ""),
        structured_guide=summary_row.get("structured_guide", {}),
        pdf_path=str(pdf_path),
    )

    logger.info(f"Successfully generated PDF study guide at {pdf_path}")
    return str(pdf_path)
