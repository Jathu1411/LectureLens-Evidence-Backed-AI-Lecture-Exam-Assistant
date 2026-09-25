"""
Controlled Concurrency Manager.
Orchestrates parallel execution between independent audio and visual processing stages
using bounded thread pools to maximize throughput without GPU VRAM exhaustion.
"""

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from pipeline.config import MAX_AUDIO_WORKERS, MAX_OCR_WORKERS, MAX_VISUAL_WORKERS

logger = logging.getLogger("pipeline.concurrency")


class PipelineConcurrencyManager:
    """Manages worker thread pools for audio and visual pipeline tasks."""

    def __init__(
        self,
        max_audio_workers: int = MAX_AUDIO_WORKERS,
        max_visual_workers: int = MAX_VISUAL_WORKERS,
        max_ocr_workers: int = MAX_OCR_WORKERS,
    ):
        self.audio_pool = ThreadPoolExecutor(max_workers=max_audio_workers, thread_name_prefix="AudioWorker")
        self.visual_pool = ThreadPoolExecutor(max_workers=max_visual_workers, thread_name_prefix="VisualWorker")
        self.ocr_pool = ThreadPoolExecutor(max_workers=max_ocr_workers, thread_name_prefix="OCRWorker")

    def run_audio_and_visual_concurrently(
        self,
        audio_fn: Callable[[], Any],
        visual_fn: Callable[[], Any],
    ) -> Tuple[Any, Any]:
        """
        Executes an audio task (e.g. extraction + transcription) and a visual task
        (e.g. frame sampling + slide detection) simultaneously in separate worker threads.
        Waits for both to complete and returns (audio_result, visual_result).
        Raises any exception raised by either task.
        """
        logger.info("Spawning concurrent Audio and Visual workers...")
        audio_future = self.audio_pool.submit(audio_fn)
        visual_future = self.visual_pool.submit(visual_fn)

        # Wait for both to finish
        audio_res = None
        visual_res = None
        errors: List[Exception] = []

        for future in [audio_future, visual_future]:
            try:
                res = future.result()
                if future is audio_future:
                    audio_res = res
                else:
                    visual_res = res
            except Exception as e:
                logger.error(f"Worker encountered error: {e}", exc_info=True)
                errors.append(e)

        if errors:
            raise errors[0]

        logger.info("Both Audio and Visual workers completed successfully.")
        return audio_res, visual_res

    def shutdown(self, wait: bool = True):
        self.audio_pool.shutdown(wait=wait)
        self.visual_pool.shutdown(wait=wait)
        self.ocr_pool.shutdown(wait=wait)
