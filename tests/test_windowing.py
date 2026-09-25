"""
Unit tests for Virtual Windowing Engine and global timestamp anchoring.
"""

from pipeline.windowing import LectureWindow, plan_lecture_windows


def test_plan_lecture_windows_3_hour():
    # 3-hour lecture: 10,800 seconds
    windows = plan_lecture_windows(10800, window_duration=1800, overlap=180)
    assert len(windows) == 6

    # Window 0
    assert windows[0].window_index == 0
    assert windows[0].start_seconds == 0.0
    assert windows[0].end_seconds == 1980.0  # 30m + 3m
    assert windows[0].effective_start_seconds == 0.0
    assert windows[0].effective_end_seconds == 1800.0

    # Window 1
    assert windows[1].window_index == 1
    assert windows[1].start_seconds == 1620.0  # 30m - 3m
    assert windows[1].end_seconds == 3780.0  # 60m + 3m
    assert windows[1].effective_start_seconds == 1800.0
    assert windows[1].effective_end_seconds == 3600.0

    # Window 5 (final)
    assert windows[5].window_index == 5
    assert windows[5].start_seconds == 8820.0  # 150m - 3m
    assert windows[5].end_seconds == 10800.0  # clipped to duration
    assert windows[5].effective_start_seconds == 9000.0
    assert windows[5].effective_end_seconds == 10800.0


def test_timestamp_conversions():
    # Window starting at 1620s (27:00)
    window = LectureWindow(
        window_index=1,
        start_seconds=1620.0,
        end_seconds=3780.0,
        effective_start_seconds=1800.0,
        effective_end_seconds=3600.0,
    )

    # Local 271s in window 1 -> global 1891s (31:31)
    global_ts = window.local_to_global_timestamp(271.0)
    assert global_ts == 1891.0

    # Global 1891s -> local 271s
    local_ts = window.global_to_local_timestamp(1891.0)
    assert local_ts == 271.0

    # Effective range test
    assert not window.is_in_effective_range(1700.0)  # in overlap, belongs to window 0
    assert window.is_in_effective_range(1800.0)
    assert window.is_in_effective_range(2500.0)
    assert not window.is_in_effective_range(3600.0)  # belongs to window 2


def test_short_video_windowing():
    # 15-minute video should yield 1 window without overlap
    windows = plan_lecture_windows(900, window_duration=1800, overlap=180)
    assert len(windows) == 1
    assert windows[0].start_seconds == 0.0
    assert windows[0].end_seconds == 900.0
    assert windows[0].effective_start_seconds == 0.0
    assert windows[0].effective_end_seconds == 900.0
