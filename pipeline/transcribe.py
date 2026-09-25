"""
Stage 3: Audio Transcription
Uses faster-whisper (large-v3 on GPU, medium on CPU) with language="en" explicitly
and vad_filter=True. Writes timestamped segments incrementally to Postgres.
"""

import logging
from typing import List, Optional

from pipeline.config import (
    WHISPER_COMPUTE_TYPE,
    WHISPER_DEVICE,
    WHISPER_LANGUAGE,
    WHISPER_MODEL,
    WHISPER_VAD_FILTER,
)
from pipeline.db import Database

logger = logging.getLogger("pipeline.transcribe")


def get_whisper_device_and_model():
    """Selects optimal device, model size, and compute type."""
    try:
        import ctranslate2

        cuda_available = ctranslate2.get_cuda_device_count() > 0
    except Exception:
        cuda_available = False

    if WHISPER_DEVICE == "cuda" or (WHISPER_DEVICE == "auto" and cuda_available):
        device = "cuda"
        model_name = WHISPER_MODEL if WHISPER_MODEL != "medium" else "large-v3"
        compute_type = WHISPER_COMPUTE_TYPE if WHISPER_COMPUTE_TYPE != "auto" else "float16"
    else:
        device = "cpu"
        model_name = WHISPER_MODEL
        compute_type = WHISPER_COMPUTE_TYPE if WHISPER_COMPUTE_TYPE != "auto" else "int8"

    logger.info(f"Whisper setup: model={model_name}, device={device}, compute_type={compute_type}")
    return model_name, device, compute_type


def transcribe_audio(
    audio_path: str,
    run_id: str,
    db: Database,
    batch_commit_size: int = 10,
    start_time_offset: float = 0.0,
    resume: bool = True,
) -> int:
    """
    Transcribes audio into timestamped segments using faster-whisper.
    Enforces language="en" and vad_filter=True.
    Applies start_time_offset to anchor all timestamps to the master lecture timeline.
    Persists segments incrementally to Postgres in batches.
    """
    from faster_whisper import WhisperModel

    model_name, device, compute_type = get_whisper_device_and_model()

    logger.info(f"Loading faster-whisper model '{model_name}' on {device} ({compute_type})...")
    model = WhisperModel(model_name, device=device, compute_type=compute_type)

    latest_transcribed_time = 0.0
    if resume:
        latest_transcribed_time = db.get_latest_transcription_time(run_id)
        if latest_transcribed_time > 0:
            logger.info(
                f"Resuming transcription for run {run_id}. "
                f"Already transcribed up to {latest_transcribed_time:.2f}s."
            )

    logger.info(
        f"Starting transcription on {audio_path}: language='{WHISPER_LANGUAGE}', vad_filter={WHISPER_VAD_FILTER}, offset={start_time_offset:.1f}s"
    )

    segments_gen, info = model.transcribe(
        audio_path,
        language=WHISPER_LANGUAGE,
        vad_filter=WHISPER_VAD_FILTER,
        vad_parameters=dict(min_silence_duration_ms=500),
        word_timestamps=False,
    )

    logger.info(
        f"Audio info: duration={info.duration:.2f}s, language='{info.language}'"
    )

    batch: List[dict] = []
    total_segments = 0
    segment_idx = 0

    for seg in segments_gen:
        segment_idx += 1
        global_start = round(start_time_offset + seg.start, 2)
        global_end = round(start_time_offset + seg.end, 2)

        # If resuming, skip segments that were already recorded
        if resume and global_end <= latest_transcribed_time:
            continue

        item = {
            "index": segment_idx,
            "start": global_start,
            "end": global_end,
            "text": seg.text.strip(),
            "words": [],
        }
        batch.append(item)
        total_segments += 1

        if len(batch) >= batch_commit_size:
            db.insert_audio_segments(run_id, batch)
            logger.info(
                f"Committed {len(batch)} segments (up to global {global_end:.1f}s) to database."
            )
            batch = []

            # Incrementally update run progress and status message in database
            run_data = db.get_run(run_id)
            total_duration = (run_data and run_data.get("total_duration")) or (getattr(info, "duration", 0.0) + start_time_offset)
            if total_duration and total_duration > 0:
                pct = min(68.0, max(5.0, 5.0 + (global_end / total_duration) * 63.0))
                elapsed_m, elapsed_s = int(global_end // 60), int(global_end % 60)
                tot_m, tot_s = int(total_duration // 60), int(total_duration % 60)
                msg = f"Transcribing audio: {elapsed_m}m{elapsed_s:02d}s / {tot_m}m{tot_s:02d}s ({total_segments} segments)"
                db.update_run_progress(run_id, round(pct, 1), msg, stage="transcription")

    # Commit remaining items
    if batch:
        db.insert_audio_segments(run_id, batch)
        logger.info(f"Committed final {len(batch)} segments to database.")

    total_in_db = len(db.get_audio_segments(run_id))
    logger.info(
        f"Transcription completed for run {run_id}. "
        f"Total segments stored in database: {total_in_db}"
    )

    run_data = db.get_run(run_id)
    total_duration = (run_data and run_data.get("total_duration")) or 0
    if total_duration and total_duration > 0 and 'global_end' in locals():
        pct = min(70.0, max(5.0, 5.0 + (global_end / total_duration) * 63.0))
        msg = f"Audio transcription complete: {total_in_db} segments recorded"
        db.update_run_progress(run_id, round(pct, 1), msg, stage="transcription")

    return total_in_db
