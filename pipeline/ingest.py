"""
Stage 1: Ingestion
Extracts 16kHz mono audio WAV for Whisper and provides a streaming video frame generator.
Designed for 3+ hour videos without loading the full video or frame buffers into RAM.
"""

import json
import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, Generator, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger("pipeline.ingest")


def probe_video(video_path: str) -> Dict[str, Any]:
    """Uses ffprobe to extract video metadata (duration, resolution, fps, codecs)."""
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        video_path,
    ]
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        data = json.loads(result.stdout)
        duration = float(data.get("format", {}).get("duration", 0.0))
        video_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
        width = int(video_stream.get("width", 0)) if video_stream else 0
        height = int(video_stream.get("height", 0)) if video_stream else 0
        fps = 30.0
        if video_stream and "r_frame_rate" in video_stream:
            num, den = video_stream["r_frame_rate"].split("/")
            fps = float(num) / float(den) if float(den) > 0 else 30.0

        return {
            "duration": duration,
            "width": width,
            "height": height,
            "fps": fps,
            "has_audio": any(s.get("codec_type") == "audio" for s in data.get("streams", [])),
        }
    except Exception as e:
        logger.error(f"Error probing video {video_path}: {e}")
        # Fallback to OpenCV if ffprobe fails
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        duration = frame_count / fps if fps > 0 else 0.0
        cap.release()
        return {
            "duration": duration,
            "width": width,
            "height": height,
            "fps": fps,
            "has_audio": True,
        }


def extract_audio(
    video_path: str,
    output_wav_path: str,
    start_time: Optional[float] = None,
    duration: Optional[float] = None,
) -> str:
    """
    Extracts 16kHz mono 16-bit PCM WAV audio using ffmpeg.
    Supports seeking (-ss) and duration (-t) for virtual window extraction
    without physically re-encoding or splitting the master video.
    """
    out_path = Path(output_wav_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if out_path.exists() and out_path.stat().st_size > 1024:
        logger.info(f"Audio file already exists at {out_path}, skipping extraction.")
        return str(out_path)

    cmd = ["ffmpeg"]
    if start_time is not None and start_time > 0:
        cmd.extend(["-ss", f"{start_time:.3f}"])
    cmd.extend(["-i", video_path])
    if duration is not None and duration > 0:
        cmd.extend(["-t", f"{duration:.3f}"])

    cmd.extend([
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        "-y",
        str(out_path),
    ])
    logger.info(f"Extracting audio via ffmpeg: {' '.join(cmd)}")
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    return str(out_path)


def stream_sampled_frames(
    video_path: str,
    sample_fps: float = 1.0,
    start_time: float = 0.0,
    end_time: Optional[float] = None,
) -> Generator[Tuple[float, np.ndarray], None, None]:
    """
    Generator that samples video frames at `sample_fps` (e.g. 1 frame per second).
    Streams frames sequentially without holding more than 1 frame in memory.
    Supports resuming from `start_time` (seconds) and terminating at `end_time`.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise IOError(f"Cannot open video file {video_path}")

    video_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_interval = max(1, int(round(video_fps / sample_fps)))

    if start_time > 0:
        start_frame = int(start_time * video_fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        current_frame_idx = start_frame
    else:
        current_frame_idx = 0

    logger.info(
        f"Sampling frames from {video_path}: video_fps={video_fps:.2f}, "
        f"sampling every {frame_interval} frames (~{sample_fps} fps), "
        f"start_time={start_time:.1f}s, end_time={end_time if end_time else 'EOF'}"
    )

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        timestamp_sec = current_frame_idx / video_fps
        if end_time is not None and timestamp_sec > end_time:
            break

        if current_frame_idx % frame_interval == 0:
            yield timestamp_sec, frame

        current_frame_idx += 1

    cap.release()

