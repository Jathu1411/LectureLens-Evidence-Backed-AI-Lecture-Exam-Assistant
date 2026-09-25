"""
Unit tests for slide-aware chunking and alignment.
"""

from pipeline.summarize import format_timestamp, partition_timeline_chunks


def test_format_timestamp():
    assert format_timestamp(0) == "00:00:00"
    assert format_timestamp(65) == "00:01:05"
    assert format_timestamp(3661) == "01:01:01"


def test_partition_timeline_chunks_slide_boundaries():
    # 20 entries, each 60 seconds (total 1200 seconds / 20 minutes)
    timeline_entries = [
        {"start_time": i * 60.0, "end_time": (i + 1) * 60.0, "slide_id": i + 1, "transcript_chunk": f"Speech {i}"}
        for i in range(20)
    ]

    # Target 600 seconds (10 mins) per chunk
    chunks = partition_timeline_chunks(timeline_entries, min_sec=500, target_sec=600, max_sec=900)

    # Should partition into 2 chunks of ~10 minutes each
    assert len(chunks) == 2
    assert chunks[0]["start_time"] == 0.0
    assert chunks[0]["end_time"] == 600.0
    assert chunks[1]["start_time"] == 600.0
    assert chunks[1]["end_time"] == 1200.0
