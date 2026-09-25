"""
Cross-platform file picker utility for the Lecture Video to Study Guide Pipeline.
Supports:
1. Native macOS Finder file dialog via AppleScript (osascript).
2. Tkinter file dialog fallback for Linux / Windows / generic desktop.
3. Interactive terminal prompt with drag-and-drop path normalization.
4. CLI execution mode (`python -m pipeline.file_picker --json`) for web UI integration.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

VIDEO_EXTENSIONS = {
    ".mp4",
    ".mkv",
    ".mov",
    ".webm",
    ".avi",
    ".m4v",
    ".flv",
    ".wmv",
    ".ts",
    ".mts",
}


def clean_file_path(raw_path: str) -> str:
    """
    Cleans and normalizes a file path string.
    Handles terminal drag-and-drop artifacts like wrapping quotes or escaped spaces.
    """
    if not raw_path:
        return ""

    path_str = raw_path.strip()

    # Strip surrounding single or double quotes
    if (path_str.startswith('"') and path_str.endswith('"')) or (
        path_str.startswith("'") and path_str.endswith("'")
    ):
        path_str = path_str[1:-1].strip()

    # Unescape escaped spaces and backslashes common in terminal drag-and-drop
    # e.g., /Users/jathu/My\ Videos/Lecture\ 1.mp4 -> /Users/jathu/My Videos/Lecture 1.mp4
    path_str = re.sub(r"\\(.)", r"\1", path_str)

    # Expand user home directory (~)
    path_str = os.path.expanduser(path_str)

    return os.path.abspath(path_str)


def format_file_size(size_bytes: int) -> str:
    """Formats bytes into human-readable string."""
    if size_bytes == 0:
        return "0 Bytes"
    for unit in ["Bytes", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"


def pick_file_macos(prompt: str = "Select a Lecture Video:") -> Tuple[Optional[str], bool]:
    """
    Opens the native macOS Finder file selection dialog using AppleScript.
    Returns (path, was_cancelled).
    """
    if sys.platform != "darwin" or not shutil.which("osascript"):
        return None, False

    # AppleScript to open Cocoa choose file panel
    apple_script = f"""
    try
        set chosenFile to choose file of type {{"public.movie", "public.audio", "mp4", "mkv", "mov", "webm", "avi", "m4v"}} with prompt "{prompt}"
        return POSIX path of chosenFile
    on error number -128
        return "CANCELLED"
    end try
    """

    try:
        proc = subprocess.run(
            ["osascript", "-e", apple_script],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        output = proc.stdout.strip()
        if output == "CANCELLED":
            return None, True
        if proc.returncode == 0 and output:
            cleaned = clean_file_path(output)
            if os.path.isfile(cleaned):
                return cleaned, False
    except Exception:
        pass

    return None, False


def pick_file_tkinter(prompt: str = "Select a Lecture Video") -> Tuple[Optional[str], bool]:
    """
    Fallback GUI file picker using Tkinter.
    Returns (path, was_cancelled).
    """
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)

        file_types = [
            ("Video Files", "*.mp4 *.mkv *.mov *.webm *.avi *.m4v *.flv *.wmv *.ts *.mts"),
            ("All Files", "*.*"),
        ]
        selected = filedialog.askopenfilename(title=prompt, filetypes=file_types)
        root.destroy()

        if not selected:
            return None, True

        cleaned = clean_file_path(selected)
        if os.path.isfile(cleaned):
            return cleaned, False
    except Exception:
        pass

    return None, False


def pick_video_file_gui(prompt: str = "Select a Lecture Video") -> Tuple[Optional[str], bool]:
    """
    Attempts to open a GUI file picker (macOS native first, then Tkinter).
    Returns (selected_file_path, was_cancelled).
    """
    # 1. Try macOS native AppleScript
    if sys.platform == "darwin":
        path, cancelled = pick_file_macos(prompt)
        if path or cancelled:
            return path, cancelled

    # 2. Try Tkinter
    path, cancelled = pick_file_tkinter(prompt)
    if path or cancelled:
        return path, cancelled

    return None, False


def pick_video_file_terminal(prompt: str = "Enter lecture video file path (or drag & drop here): ") -> Optional[str]:
    """
    Interactive command-line prompt asking the user for a path.
    Supports drag-and-drop right onto the terminal window.
    """
    while True:
        try:
            user_input = input(f"\n📁 {prompt}").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nOperation cancelled by user.")
            return None

        if not user_input:
            print("No path provided.")
            return None

        cleaned = clean_file_path(user_input)
        if os.path.isfile(cleaned):
            return cleaned

        print(f"❌ File not found at: '{cleaned}'. Please try again (or press Ctrl+C to cancel).")


def pick_video_file(
    prompt: str = "Select a Lecture Video",
    allow_terminal_fallback: bool = True,
) -> Optional[str]:
    """
    Primary entrypoint to pick a video file from the laptop.
    1. Attempts native GUI picker (Finder on Mac, Tkinter on others).
    2. If cancelled by user in the GUI, returns None.
    3. If GUI is unavailable and terminal fallback is allowed, prompts in the console.
    """
    path, cancelled = pick_video_file_gui(prompt)
    if path:
        return path
    if cancelled:
        print("File selection cancelled.")
        return None

    if allow_terminal_fallback and sys.stdin.isatty():
        return pick_video_file_terminal()

    return None


def get_video_file_info(file_path: str) -> Dict[str, any]:
    """Inspects a selected video file and returns basic metadata."""
    p = Path(file_path).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    size_bytes = p.stat().st_size
    return {
        "success": True,
        "filePath": str(p),
        "fileName": p.name,
        "fileSize": size_bytes,
        "formattedSize": format_file_size(size_bytes),
        "extension": p.suffix.lower(),
    }


def main():
    parser = argparse.ArgumentParser(description="Laptop File Picker Helper for Lecture Guide Pipeline")
    parser.add_argument("--json", action="store_true", help="Output result as JSON payload for web UI")
    parser.add_argument("--prompt", default="Select a Lecture Video:", help="Custom picker prompt")
    parser.add_argument("--no-terminal", action="store_true", help="Do not fall back to terminal input")
    args = parser.parse_args()

    selected_path, cancelled = pick_video_file_gui(args.prompt)

    if cancelled:
        if args.json:
            print(json.dumps({"success": False, "cancelled": True}))
        else:
            print("File selection was cancelled.")
        sys.exit(0)

    if not selected_path and not args.no_terminal and sys.stdin.isatty():
        selected_path = pick_video_file_terminal()

    if selected_path:
        info = get_video_file_info(selected_path)
        if args.json:
            print(json.dumps(info))
        else:
            print(f"\n✅ Selected Video: {info['fileName']} ({info['formattedSize']})")
            print(f"Path: {info['filePath']}\n")
    else:
        if args.json:
            print(json.dumps({"success": False, "cancelled": True, "error": "No file selected"}))
        else:
            print("No video file selected.")
        sys.exit(1)


if __name__ == "__main__":
    main()
