"""
Virtual Windowing Engine for Lecture Video Processing.
Enables virtual time-window slicing (e.g. 30-minute windows with 3-minute overlap)
using direct FFmpeg and OpenCV seeking without creating physical split video files.
Maintains absolute temporal anchoring to the master lecture timeline.
"""

from dataclasses import asdict, dataclass
import math
from typing import Any, Dict, List


@dataclass
class LectureWindow:
    window_index: int
    start_seconds: float
    end_seconds: float
    effective_start_seconds: float
    effective_end_seconds: float

    @property
    def duration_seconds(self) -> float:
        return max(0.0, self.end_seconds - self.start_seconds)

    def local_to_global_timestamp(self, local_sec: float) -> float:
        """Converts window-local seconds into global lecture seconds."""
        return round(self.start_seconds + local_sec, 2)

    def global_to_local_timestamp(self, global_sec: float) -> float:
        """Converts global lecture seconds into window-local seconds."""
        return round(global_sec - self.start_seconds, 2)

    def is_in_effective_range(self, global_sec: float) -> bool:
        """Checks if a global timestamp falls into this window's primary non-overlapping range."""
        return self.effective_start_seconds <= global_sec < self.effective_end_seconds

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def plan_lecture_windows(
    total_duration: float,
    window_duration: int = 1800,
    overlap: int = 180,
) -> List[LectureWindow]:
    """
    Plans virtual processing windows for a lecture.
    
    For a 3-hour video with 30m (1800s) windows and 3m (180s) overlap:
    - Window 0: 00:00 -> 33:00 (effective: 00:00 -> 30:00)
    - Window 1: 27:00 -> 63:00 (effective: 30:00 -> 60:00)
    - Window 2: 57:00 -> 93:00 (effective: 60:00 -> 90:00)
    - etc.
    """
    if total_duration <= 0:
        return []

    # If duration is short, return a single window without overlap
    if total_duration <= window_duration:
        return [
            LectureWindow(
                window_index=0,
                start_seconds=0.0,
                end_seconds=round(total_duration, 2),
                effective_start_seconds=0.0,
                effective_end_seconds=round(total_duration, 2),
            )
        ]

    windows: List[LectureWindow] = []
    current_effective_start = 0.0
    window_index = 0

    while current_effective_start < total_duration:
        current_effective_end = min(total_duration, current_effective_start + window_duration)

        # Apply overlap: start earlier if not first window, end later if not last window
        w_start = max(0.0, current_effective_start - overlap) if window_index > 0 else 0.0
        w_end = min(total_duration, current_effective_end + overlap) if current_effective_end < total_duration else total_duration

        windows.append(
            LectureWindow(
                window_index=window_index,
                start_seconds=round(w_start, 2),
                end_seconds=round(w_end, 2),
                effective_start_seconds=round(current_effective_start, 2),
                effective_end_seconds=round(current_effective_end, 2),
            )
        )

        current_effective_start = current_effective_end
        window_index += 1

    return windows
