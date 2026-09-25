"""
Unit tests for the laptop file picker utility.
"""

import os
import subprocess
import sys
from pathlib import Path
import pytest

from pipeline.file_picker import (
    clean_file_path,
    format_file_size,
    get_video_file_info,
)


def test_clean_file_path_plain():
    res = clean_file_path("/tmp/test_video.mp4")
    assert res == "/tmp/test_video.mp4"


def test_clean_file_path_quotes():
    res_double = clean_file_path('"/tmp/my lecture.mp4"')
    assert res_double == "/tmp/my lecture.mp4"

    res_single = clean_file_path("'/tmp/my lecture.mp4'")
    assert res_single == "/tmp/my lecture.mp4"


def test_clean_file_path_escaped_spaces():
    # Terminal drag-and-drop on macOS often pastes: /tmp/My\ Videos/Lecture\ 1.mp4
    raw = r"/tmp/My\ Videos/Lecture\ 1.mp4"
    cleaned = clean_file_path(raw)
    assert cleaned == "/tmp/My Videos/Lecture 1.mp4"


def test_clean_file_path_tilde():
    res = clean_file_path("~/Movies/lecture.mp4")
    assert not res.startswith("~")
    assert res.endswith("Movies/lecture.mp4")


def test_format_file_size():
    assert format_file_size(0) == "0 Bytes"
    assert "KB" in format_file_size(2048)
    assert "MB" in format_file_size(10 * 1024 * 1024)
    assert "GB" in format_file_size(2 * 1024 * 1024 * 1024)


def test_get_video_file_info(tmp_path):
    dummy_video = tmp_path / "sample_test.mp4"
    dummy_video.write_bytes(b"dummy video content 12345")

    info = get_video_file_info(str(dummy_video))
    assert info["success"] is True
    assert info["fileName"] == "sample_test.mp4"
    assert info["fileSize"] == 25
    assert info["extension"] == ".mp4"
    assert os.path.isabs(info["filePath"])


def test_get_video_file_info_nonexistent():
    with pytest.raises(FileNotFoundError):
        get_video_file_info("/path/that/does/not/exist/video.mp4")


def test_file_picker_cli_help():
    venv_python = sys.executable
    res = subprocess.run(
        [venv_python, "-m", "pipeline.file_picker", "--help"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    assert "--json" in res.stdout
    assert "--prompt" in res.stdout


def test_main_cli_commands_help():
    venv_python = sys.executable
    # Process help
    res_proc = subprocess.run(
        [venv_python, "main.py", "process", "--help"],
        capture_output=True,
        text=True,
    )
    assert res_proc.returncode == 0
    assert "--pick" in res_proc.stdout

    # Pick help
    res_pick = subprocess.run(
        [venv_python, "main.py", "pick", "--help"],
        capture_output=True,
        text=True,
    )
    assert res_pick.returncode == 0
    assert "--process" in res_pick.stdout
