"""
CLI Orchestrator for the Lecture Video to Study Guide Pipeline.
Enables running the entire end-to-end pipeline or any individual stage independently.
"""

import argparse
import hashlib
import logging
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from pipeline import config
from pipeline.align import align_timeline, detect_semantic_sections
from pipeline.concurrency import PipelineConcurrencyManager
from pipeline.db import Database
from pipeline.ingest import extract_audio, probe_video
from pipeline.knowledge import detect_lecturer_emphasis, extract_knowledge_from_section
from pipeline.ocr import run_ocr_on_slides
from pipeline.render_pdf import render_study_guide_pdf
from pipeline.slides import detect_slides
from pipeline.statistics import generate_lecture_statistics
from pipeline.summarize import run_map_step, run_reduce_step
from pipeline.transcribe import transcribe_audio
from pipeline.verification import verify_all_concepts
from pipeline.visual_filter import detect_presentation_roi
from pipeline.windowing import plan_lecture_windows
from pipeline.file_picker import pick_video_file, get_video_file_info

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pipeline.cli")



def generate_run_id(video_path: str) -> str:
    """Generates a deterministic or short unique run ID for the video."""
    video_name = Path(video_path).stem
    clean_name = "".join(c for c in video_name if c.isalnum() or c in "_-")[:20]
    path_hash = hashlib.md5(str(Path(video_path).resolve()).encode()).hexdigest()[:8]
    return f"{clean_name}_{path_hash}"


# --- Individual Stage Runners ---

def run_stage_ingest(video_path: str, run_id: str, db: Database) -> dict:
    logger.info(f"=== Stage 1: Ingestion for {video_path} ===")
    if not Path(video_path).exists():
        db.update_run_stage(run_id=run_id, stage="ingestion", status="failed", progress_percent=0.0, progress_message=f"File not found: {video_path}")
        raise FileNotFoundError(f"Video file does not exist: {video_path}")

    db.update_run_progress(run_id, 3.0, "Probing video dimensions and audio stream...", stage="ingestion")
    probe_info = probe_video(video_path)
    logger.info(f"Video duration: {probe_info['duration']:.1f}s, Resolution: {probe_info['width']}x{probe_info['height']}")

    db.update_run_progress(run_id, 6.0, "Extracting 16kHz mono audio via FFmpeg...", stage="ingestion")
    audio_path = str(config.OUTPUT_DIR / run_id / "audio.wav")
    extract_audio(video_path, audio_path)

    db.update_run_stage(
        run_id=run_id,
        stage="ingestion",
        status="in_progress",
        audio_path=audio_path,
        duration=probe_info["duration"],
        progress_percent=10.0,
        progress_message="Audio extraction complete",
    )
    return probe_info


def run_stage_slides(video_path: str, run_id: str, db: Database, resume: bool = True) -> int:
    logger.info(f"=== Stage 2: Slide Detection for run {run_id} ===")
    db.update_run_progress(run_id, 12.0, "Scanning frames with SSIM perceptual diff...", stage="slide_detection")
    count = detect_slides(video_path, run_id, db, resume=resume)
    db.update_run_stage(
        run_id=run_id,
        stage="slide_detection",
        status="in_progress",
        progress_percent=25.0,
        progress_message=f"Slide detection complete: {count} distinct slides identified",
    )
    return count


def run_stage_transcribe(run_id: str, db: Database, resume: bool = True) -> int:
    logger.info(f"=== Stage 3: Audio Transcription for run {run_id} ===")
    run = db.get_run(run_id)
    if not run or not run.get("audio_path"):
        raise ValueError(f"No audio file found for run {run_id}. Run ingestion first.")

    db.update_run_progress(run_id, 28.0, "Loading Faster-Whisper ASR model...", stage="transcription")
    count = transcribe_audio(run["audio_path"], run_id, db, resume=resume)
    db.update_run_stage(
        run_id=run_id,
        stage="transcription",
        status="in_progress",
        progress_percent=55.0,
        progress_message=f"Transcription complete: {count} segments recorded",
    )
    return count


def run_stage_ocr(run_id: str, db: Database, resume: bool = True) -> int:
    logger.info(f"=== Stage 4: Visual Path (OCR) for run {run_id} ===")
    db.update_run_progress(run_id, 58.0, "Extracting slide text with Tesseract & Ollama Vision...", stage="ocr")
    count = run_ocr_on_slides(run_id, db, resume=resume)
    db.update_run_stage(
        run_id=run_id,
        stage="ocr",
        status="in_progress",
        progress_percent=70.0,
        progress_message=f"OCR complete: {count} slide frames processed",
    )
    return count


def run_stage_align(run_id: str, db: Database) -> int:
    logger.info(f"=== Stage 5: Timeline Alignment for run {run_id} ===")
    db.update_run_progress(run_id, 72.0, "Synchronizing audio segments with active slide intervals...", stage="alignment")
    entries = align_timeline(run_id, db)
    db.update_run_stage(
        run_id=run_id,
        stage="alignment",
        status="in_progress",
        progress_percent=75.0,
        progress_message=f"Alignment complete: {len(entries)} synchronized timeline blocks",
    )
    return len(entries)


def run_stage_summarize(run_id: str, db: Database, resume: bool = True) -> dict:
    logger.info(f"=== Stage 6: Map-Reduce Summarization for run {run_id} ===")
    db.update_run_progress(run_id, 78.0, "Running Map step: Summarizing 10-15 min slide chunks with Llama 3...", stage="summarization")
    run_map_step(run_id, db, resume=resume)
    db.update_run_progress(run_id, 90.0, "Running Reduce step: Synthesizing final study guide with Llama 3...", stage="summarization")
    final_guide = run_reduce_step(run_id, db)
    db.update_run_stage(
        run_id=run_id,
        stage="summarization",
        status="in_progress",
        progress_percent=95.0,
        progress_message="Map-Reduce summarization complete",
    )
    return final_guide


def run_stage_export_pdf(run_id: str, db: Database) -> str:
    logger.info(f"=== Stage 7: PDF Export for run {run_id} ===")
    db.update_run_progress(run_id, 96.0, "Compiling publication PDF with WeasyPrint...", stage="export-pdf")
    pdf_path = render_study_guide_pdf(run_id, db)
    db.update_run_stage(
        run_id=run_id,
        stage="completed",
        status="completed",
        progress_percent=100.0,
        progress_message="Completed • PDF Study Guide Ready",
    )
    return pdf_path


def run_full_pipeline(video_path: str, run_id: str, db: Database, resume: bool = True):
    logger.info(f"Starting End-to-End Pipeline for {video_path} [Run ID: {run_id}]")
    if not Path(video_path).exists():
        db.create_or_get_run(run_id, video_path)
        db.update_run_stage(run_id=run_id, stage="ingestion", status="failed", progress_percent=0.0, progress_message=f"File not found: {video_path}")
        logger.error(f"Cannot run pipeline: Video file not found at '{video_path}'")
        raise FileNotFoundError(f"Video file not found: {video_path}")

    db.create_or_get_run(run_id, video_path)
    db.update_run_progress(run_id, 1.0, "Initializing pipeline...", stage="created")

    try:
        # 1. Ingestion
        run_stage_ingest(video_path, run_id, db)

        # 2. Slide detection
        run_stage_slides(video_path, run_id, db, resume=resume)

        # 3. Transcription
        run_stage_transcribe(run_id, db, resume=resume)

        # 4. OCR
        run_stage_ocr(run_id, db, resume=resume)

        # 5. Alignment
        run_stage_align(run_id, db)

        # 6. Summarization
        run_stage_summarize(run_id, db, resume=resume)

        # 7. PDF Export
        pdf_path = run_stage_export_pdf(run_id, db)

        logger.info(f"=== Pipeline Finished Successfully! ===")
        logger.info(f"PDF Study Guide: {pdf_path}")
        return pdf_path
    except Exception as e:
        logger.error(f"Pipeline error for run {run_id}: {e}", exc_info=True)
        db.update_run_stage(run_id=run_id, stage=db.get_run(run_id).get("current_stage", "failed"), status="failed", progress_message=f"Failed: {str(e)[:100]}")
        raise


def run_windowed_pipeline(
    video_path: str,
    run_id: str,
    db: Database,
    window_minutes: int = 30,
    overlap_minutes: int = 3,
    window_duration_sec: Optional[float] = None,
    window_overlap_sec: Optional[float] = None,
    resume: bool = True,
) -> str:
    """
    Executes the upgraded virtual-windowed lecture processing pipeline:
    30-minute virtual windows -> concurrent audio & visual processing ->
    presentation ROI -> pHash -> temporal validation -> visual clustering ->
    representative frame OCR -> evidence timeline -> semantic sections ->
    structured knowledge extraction -> grounding verification ->
    cross-window deduplication & synthesis -> publication PDF -> statistics report.
    """
    start_time = time.time()
    stage_timings: Dict[str, float] = {}

    logger.info(f"Starting Windowed Pipeline for {video_path} [Run ID: {run_id}]")
    if not Path(video_path).exists():
        db.create_or_get_run(run_id, video_path)
        db.update_run_stage(run_id=run_id, stage="ingestion", status="failed", progress_percent=0.0, progress_message=f"File not found: {video_path}")
        raise FileNotFoundError(f"Video file not found: {video_path}")

    db.create_or_get_run(run_id, video_path)
    db.update_run_progress(run_id, 1.0, "Probing video dimensions and audio stream...", stage="created")

    t0 = time.time()
    probe_info = probe_video(video_path)
    duration = probe_info["duration"]
    stage_timings["video_probe_seconds"] = round(time.time() - t0, 2)

    db.update_run_stage(
        run_id=run_id,
        stage="created",
        status="in_progress",
        duration=duration,
        progress_percent=3.0,
        progress_message="Video probe complete",
    )

    # 1. Plan Virtual Windows
    window_sec = window_duration_sec if window_duration_sec is not None else window_minutes * 60
    overlap_sec = window_overlap_sec if window_overlap_sec is not None else overlap_minutes * 60
    windows = plan_lecture_windows(duration, window_duration=window_sec, overlap=overlap_sec)
    db.create_or_get_windows(run_id, [w.to_dict() for w in windows])
    logger.info(f"Planned {len(windows)} virtual windows (duration={window_sec}s, overlap={overlap_sec}s).")

    # 2. Detect Presentation ROI once for the entire lecture
    t0 = time.time()
    roi_bbox = detect_presentation_roi(video_path)
    stage_timings["roi_detection_seconds"] = round(time.time() - t0, 2)

    concurrency = PipelineConcurrencyManager()

    # 3. Process Windows
    total_whisper_time = 0.0
    total_slide_time = 0.0
    total_ocr_time = 0.0
    total_knowledge_time = 0.0

    for i, w in enumerate(windows):
        w_idx = w.window_index
        db_win = db.get_window(run_id, w_idx)
        if resume and db_win and db_win.get("status") == "COMPLETE":
            logger.info(f"[WINDOW {w_idx + 1}/{len(windows)}] Already completed (resume). Skipping.")
            continue

        logger.info(
            f"=== [WINDOW {w_idx + 1}/{len(windows)}] Range: {w.start_seconds:.1f}s -> {w.end_seconds:.1f}s "
            f"(Effective: {w.effective_start_seconds:.1f}s -> {w.effective_end_seconds:.1f}s) ==="
        )
        db.update_window_status(run_id, w_idx, "PROCESSING")
        w_progress_base = 5.0 + (i / max(1, len(windows))) * 70.0
        db.update_run_progress(run_id, w_progress_base, f"Processing Window {w_idx + 1}/{len(windows)}...", stage="processing_windows")

        # Audio Worker: virtual seek extract + transcribe
        audio_window_path = str(config.OUTPUT_DIR / run_id / f"audio_win_{w_idx:02d}.wav")
        def audio_task():
            nonlocal total_whisper_time
            t_a = time.time()
            extract_audio(
                video_path=video_path,
                output_wav_path=audio_window_path,
                start_time=w.start_seconds,
                duration=w.duration_seconds,
            )
            transcribe_audio(
                audio_path=audio_window_path,
                run_id=run_id,
                db=db,
                start_time_offset=w.start_seconds,
                resume=resume,
            )
            total_whisper_time += time.time() - t_a

        # Visual Worker: frame stream within window + slide detection
        def visual_task():
            nonlocal total_slide_time
            t_v = time.time()
            detect_slides(
                video_path=video_path,
                run_id=run_id,
                db=db,
                start_time=w.start_seconds,
                end_time=w.end_seconds,
                roi_bbox=roi_bbox,
                resume=resume,
            )
            total_slide_time += time.time() - t_v

        # Run Audio and Visual pipelines concurrently
        concurrency.run_audio_and_visual_concurrently(audio_task, visual_task)

        # Run OCR on newly detected slides for this window
        t_ocr = time.time()
        run_ocr_on_slides(run_id, db, resume=resume)
        total_ocr_time += time.time() - t_ocr

        # Align timeline up to current window
        align_timeline(run_id, db)

        # Detect semantic sections in this window
        sections = detect_semantic_sections(run_id, db, window_index=w_idx)

        # Knowledge Extraction for each section
        t_k = time.time()
        timeline_entries = db.get_timeline_entries(run_id)
        for sec in sections:
            concepts = extract_knowledge_from_section(
                section=sec,
                timeline_entries=timeline_entries,
                window_index=w_idx,
            )
            if concepts:
                db.insert_concepts(run_id, concepts)

        # Lecturer emphasis detection on audio segments
        audio_segs = db.get_audio_segments(run_id)
        signals = detect_lecturer_emphasis(audio_segs, window_index=w_idx)
        if signals:
            db.insert_exam_signals(run_id, signals)

        # Grounding verification
        verify_all_concepts(run_id, db, window_index=w_idx)
        total_knowledge_time += time.time() - t_k

        # Mark window complete
        db.update_window_status(run_id, w_idx, "COMPLETE")
        logger.info(f"[WINDOW {w_idx + 1}/{len(windows)}] Window processing COMPLETE.")

    stage_timings["audio_transcription_seconds"] = round(total_whisper_time, 2)
    stage_timings["slide_detection_seconds"] = round(total_slide_time, 2)
    stage_timings["ocr_seconds"] = round(total_ocr_time, 2)
    stage_timings["knowledge_extraction_seconds"] = round(total_knowledge_time, 2)

    # 4. Final Map-Reduce Summarization with cross-window concept deduplication
    t_sum = time.time()
    db.update_run_progress(run_id, 80.0, "Synthesizing full lecture study guide...", stage="summarization")
    run_stage_summarize(run_id, db, resume=resume)
    stage_timings["summarization_seconds"] = round(time.time() - t_sum, 2)

    # 5. Publication PDF Generation
    t_pdf = time.time()
    db.update_run_progress(run_id, 94.0, "Rendering publication PDF with WeasyPrint...", stage="export-pdf")
    pdf_path = run_stage_export_pdf(run_id, db)
    stage_timings["pdf_generation_seconds"] = round(time.time() - t_pdf, 2)

    # 6. Lecture Statistics Generation
    end_time = time.time()
    stage_timings["total_seconds"] = round(end_time - start_time, 2)
    generate_lecture_statistics(
        run_id=run_id,
        db=db,
        processing_start_time=start_time,
        processing_end_time=end_time,
        stage_timings=stage_timings,
    )

    db.update_run_stage(
        run_id=run_id,
        stage="completed",
        status="completed",
        progress_percent=100.0,
        progress_message="Completed • Study Guide & Statistics Ready",
    )
    logger.info(f"=== Windowed Pipeline Finished Successfully! ===")
    logger.info(f"PDF Study Guide: {pdf_path}")
    logger.info(f"Statistics: {config.OUTPUT_DIR / run_id / 'lecture_statistics.json'}")
    return pdf_path


def print_status(run_id: str, db: Database):
    run = db.get_run(run_id)
    if not run:
        print(f"Run '{run_id}' not found.")
        return

    slides = db.get_slides(run_id)
    unique_slides = db.get_unique_slides(run_id)
    segments = db.get_audio_segments(run_id)
    timeline = db.get_timeline_entries(run_id)
    chunks = db.get_chunk_summaries(run_id)
    summary = db.get_final_summary(run_id)
    windows = db.get_windows(run_id)
    concepts = db.get_concepts(run_id)
    verif = db.get_verification_records(run_id)
    stats = db.get_lecture_statistics(run_id)

    print("\n" + "=" * 55)
    print(f"PIPELINE RUN STATUS: {run_id}")
    print("=" * 55)
    print(f"Status:            {run.get('status')}")
    print(f"Current Stage:     {run.get('current_stage')}")
    print(f"Video Path:        {run.get('video_path')}")
    print(f"Total Duration:    {run.get('total_duration', 0):.1f} seconds")
    print("-" * 55)
    if windows:
        comp_w = sum(1 for w in windows if w.get('status') == 'COMPLETE')
        print(f"Virtual Windows:   {len(windows)} total ({comp_w} completed)")
    print(f"Slides Detected:   {len(slides)} total ({len(unique_slides)} unique)")
    print(f"Audio Segments:    {len(segments)} (Transcribed to: {db.get_latest_transcription_time(run_id):.1f}s)")
    print(f"Timeline Blocks:   {len(timeline)}")
    if concepts:
        supp = sum(1 for v in verif if v.get('status') == 'SUPPORTED')
        print(f"Extracted Concepts: {len(concepts)} ({supp}/{len(verif)} verified)")
    print(f"Summarized Chunks: {len(chunks)}")
    print(f"Final Study Guide: {'Present' if summary else 'Not Generated'}")
    if summary and summary.get("pdf_path"):
        print(f"PDF File:          {summary['pdf_path']}")
    if stats:
        print(f"Real-Time Factor:  {stats.get('real_time_factor')} (lower is faster)")
    print("=" * 55 + "\n")


def print_stats(run_id: str, db: Database):
    stats = db.get_lecture_statistics(run_id)
    if not stats:
        print(f"No statistics found for run '{run_id}'.")
        return
    import json
    print(json.dumps(stats.get("stats_json", stats), indent=2, default=str))


def main():
    parser = argparse.ArgumentParser(description="Offline Lecture Video to PDF Study Guide Pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Process (Windowed Pipeline - New Standard)
    process_parser = subparsers.add_parser("process", help="Run windowed pipeline with evidence grounding")
    process_parser.add_argument("video", nargs="?", default=None, help="Path to lecture video file (opens laptop file picker if omitted)")
    process_parser.add_argument("--pick", action="store_true", help="Open native file picker to select a video file")
    process_parser.add_argument("--run-id", default=None, help="Optional custom run ID")
    process_parser.add_argument("--window-minutes", type=int, default=30, help="Window duration in minutes (default: 30)")
    process_parser.add_argument("--overlap-minutes", type=int, default=3, help="Overlap duration in minutes (default: 3)")
    process_parser.add_argument("--no-resume", action="store_true", help="Do not resume; overwrite from start")

    # Pick Video from Laptop
    pick_parser = subparsers.add_parser("pick", help="Open native file picker to select a video file from your laptop")
    pick_parser.add_argument("--process", action="store_true", help="Immediately run windowed pipeline on the chosen file")
    pick_parser.add_argument("--run-full", action="store_true", help="Immediately run full pipeline on the chosen file")
    pick_parser.add_argument("--run-id", default=None, help="Optional custom run ID")

    # Stats
    stats_parser = subparsers.add_parser("stats", help="Display performance and quality statistics JSON")
    stats_parser.add_argument("run_id", help="Run ID")

    # Full Run
    run_parser = subparsers.add_parser("run", help="Run full pipeline end-to-end")
    run_parser.add_argument("--video", default=None, help="Path to lecture video file (opens laptop file picker if omitted)")
    run_parser.add_argument("--pick", action="store_true", help="Open native file picker to select a video file")
    run_parser.add_argument("--run-id", default=None, help="Optional custom run ID")
    run_parser.add_argument("--no-resume", action="store_true", help="Do not resume; overwrite from start")

    # Ingest
    ingest_parser = subparsers.add_parser("ingest", help="Run Stage 1: Ingestion & audio extraction")
    ingest_parser.add_argument("--video", default=None, help="Path to video file (opens laptop file picker if omitted)")
    ingest_parser.add_argument("--pick", action="store_true", help="Open native file picker to select a video file")
    ingest_parser.add_argument("--run-id", default=None, help="Run ID")

    # Slide detection
    slides_parser = subparsers.add_parser("slides", help="Run Stage 2: Slide-change detection")
    slides_parser.add_argument("--run-id", required=True, help="Run ID")
    slides_parser.add_argument("--video", default=None, help="Video path (if not in DB)")

    # Transcribe
    trans_parser = subparsers.add_parser("transcribe", help="Run Stage 3: Faster-Whisper transcription")
    trans_parser.add_argument("--run-id", required=True, help="Run ID")

    # OCR
    ocr_parser = subparsers.add_parser("ocr", help="Run Stage 4: Tesseract OCR on detected slides")
    ocr_parser.add_argument("--run-id", required=True, help="Run ID")

    # Align
    align_parser = subparsers.add_parser("align", help="Run Stage 5: Timeline alignment")
    align_parser.add_argument("--run-id", required=True, help="Run ID")

    # Summarize
    sum_parser = subparsers.add_parser("summarize", help="Run Stage 6: Map-Reduce Ollama summarization")
    sum_parser.add_argument("--run-id", required=True, help="Run ID")

    # Export PDF
    pdf_parser = subparsers.add_parser("export-pdf", help="Run Stage 7: PDF export via WeasyPrint")
    pdf_parser.add_argument("--run-id", required=True, help="Run ID")

    # Status
    status_parser = subparsers.add_parser("status", help="Display run progress and stage status")
    status_parser.add_argument("--run-id", required=True, help="Run ID")

    # Delete Run
    del_parser = subparsers.add_parser("delete", help="Delete a run from database and remove its artifacts")
    del_parser.add_argument("--run-id", required=True, help="Run ID to delete")

    # Cancel Run
    cancel_parser = subparsers.add_parser("cancel", help="Cancel an in-progress run")
    cancel_parser.add_argument("--run-id", required=True, help="Run ID to cancel")

    # JSON export commands for Next.js API
    subparsers.add_parser("runs-json", help="Export all runs as JSON")
    detail_parser = subparsers.add_parser("run-details-json", help="Export single run details as JSON")
    detail_parser.add_argument("--run-id", required=True, help="Run ID")

    args = parser.parse_args()
    db = Database()

    if args.command == "delete":
        success = db.delete_run(args.run_id)
        if success:
            print(f"Run '{args.run_id}' successfully deleted.")
        else:
            sys.exit(f"Failed to delete run '{args.run_id}'.")

    elif args.command == "cancel":
        db.cancel_run(args.run_id)
        print(f"Run '{args.run_id}' cancelled.")

    elif args.command == "runs-json":
        runs = db.list_runs()
        import json
        print(json.dumps(runs, default=str))

    elif args.command == "run-details-json":
        run = db.get_run(args.run_id)
        if not run:
            import json
            print(json.dumps({"error": "not found"}))
            return
        slides = db.get_slides(args.run_id)
        timeline = db.get_timeline_entries(args.run_id)
        chunks = db.get_chunk_summaries(args.run_id)
        summary = db.get_final_summary(args.run_id)
        import json
        payload = {
            "run": run,
            "slides": slides,
            "timeline": timeline,
            "chunks": chunks,
            "summary": summary,
        }
        print(json.dumps(payload, default=str))

    elif args.command == "pick":
        print("\n🔍 Opening laptop file picker...")
        selected_file = pick_video_file(prompt="Select Lecture Video:")
        if not selected_file:
            sys.exit("No video file selected.")
        info = get_video_file_info(selected_file)
        print("\n" + "=" * 55)
        print("SELECTED LECTURE VIDEO")
        print("=" * 55)
        print(f"File Name: {info['fileName']}")
        print(f"File Size: {info['formattedSize']}")
        print(f"Full Path: {info['filePath']}")
        print("=" * 55 + "\n")
        if args.process:
            run_id = args.run_id or generate_run_id(selected_file)
            run_windowed_pipeline(
                video_path=selected_file,
                run_id=run_id,
                db=db,
                resume=True,
            )
        elif args.run_full:
            run_id = args.run_id or generate_run_id(selected_file)
            run_full_pipeline(video_path=selected_file, run_id=run_id, db=db, resume=True)
        else:
            print("To process this lecture:")
            print(f"  python main.py process \"{selected_file}\"\n")

    elif args.command == "process":
        video_path = args.video
        if not video_path or args.pick:
            print("\n🔍 No video path specified. Opening laptop file picker...")
            video_path = pick_video_file(prompt="Select Lecture Video for Windowed Processing:")
            if not video_path:
                sys.exit("No video file selected. Exiting.")
            print(f"📁 Selected: {video_path}\n")

        run_id = args.run_id or generate_run_id(video_path)
        resume = not args.no_resume
        run_windowed_pipeline(
            video_path=video_path,
            run_id=run_id,
            db=db,
            window_minutes=args.window_minutes,
            overlap_minutes=args.overlap_minutes,
            resume=resume,
        )

    elif args.command == "stats":
        print_stats(args.run_id, db)

    elif args.command == "run":
        video_path = args.video
        if not video_path or args.pick:
            print("\n🔍 No video path specified. Opening laptop file picker...")
            video_path = pick_video_file(prompt="Select Lecture Video for Full Pipeline:")
            if not video_path:
                sys.exit("No video file selected. Exiting.")
            print(f"📁 Selected: {video_path}\n")

        run_id = args.run_id or generate_run_id(video_path)
        resume = not args.no_resume
        run_full_pipeline(video_path, run_id, db, resume=resume)

    elif args.command == "ingest":
        video_path = args.video
        if not video_path or args.pick:
            print("\n🔍 No video path specified. Opening laptop file picker...")
            video_path = pick_video_file(prompt="Select Lecture Video for Ingestion:")
            if not video_path:
                sys.exit("No video file selected. Exiting.")
            print(f"📁 Selected: {video_path}\n")

        run_id = args.run_id or generate_run_id(video_path)
        db.create_or_get_run(run_id, video_path)
        run_stage_ingest(video_path, run_id, db)

    elif args.command == "slides":
        run = db.get_run(args.run_id)
        video_path = args.video or (run["video_path"] if run else None)
        if not video_path:
            sys.exit("Video path required or run must exist in database.")
        run_stage_slides(video_path, args.run_id, db)

    elif args.command == "transcribe":
        run_stage_transcribe(args.run_id, db)

    elif args.command == "ocr":
        run_stage_ocr(args.run_id, db)

    elif args.command == "align":
        run_stage_align(args.run_id, db)

    elif args.command == "summarize":
        run_stage_summarize(args.run_id, db)

    elif args.command == "export-pdf":
        run_stage_export_pdf(args.run_id, db)

    elif args.command == "status":
        print_status(args.run_id, db)

    elif args.command == "list":
        runs = db.list_runs()
        print(f"\nTotal Runs: {len(runs)}")
        for r in runs:
            print(f" - [{r['id']}] Status: {r['status']}, Stage: {r['current_stage']}, Video: {r['video_path']}")
        print()


if __name__ == "__main__":
    main()
