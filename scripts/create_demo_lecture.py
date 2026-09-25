"""
Generates a realistic demo lecture video with 3 slides and audio.
"""

import subprocess
from pathlib import Path
import cv2
import numpy as np

def generate_demo_lecture():
    output_dir = Path(__file__).resolve().parent.parent / "sample_data"
    output_dir.mkdir(parents=True, exist_ok=True)
    final_video = output_dir / "demo_lecture.mp4"
    temp_silent = output_dir / "temp_silent.mp4"

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    fps = 10.0
    width, height = 800, 450
    out = cv2.VideoWriter(str(temp_silent), fourcc, fps, (width, height))

    # Slide 1: Deep Learning Foundations (4 seconds = 40 frames)
    for _ in range(40):
        frame = np.full((height, width, 3), (40, 20, 15), dtype=np.uint8)  # Deep Slate Navy
        cv2.putText(frame, "MODULE 1: ARTIFICIAL INTELLIGENCE", (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (100, 200, 255), 2)
        cv2.putText(frame, "Deep Learning Foundations & Architectures", (50, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
        cv2.putText(frame, "- Gradient Descent & Backpropagation", (70, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (200, 220, 240), 1)
        cv2.putText(frame, "- Loss Functions & Optimization Dynamics", (70, 280), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (200, 220, 240), 1)
        out.write(frame)

    # Slide 2: Convolutional Networks (4 seconds = 40 frames)
    for _ in range(40):
        frame = np.full((height, width, 3), (25, 40, 20), dtype=np.uint8)  # Forest Green Slate
        cv2.putText(frame, "MODULE 2: CONVOLUTIONAL NETWORKS", (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (120, 255, 180), 2)
        cv2.putText(frame, "Feature Maps & Spatial Invariance", (50, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
        cv2.putText(frame, "- Receptive Fields and Kernels", (70, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (220, 245, 220), 1)
        cv2.putText(frame, "- Pooling Layers and Downsampling", (70, 280), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (220, 245, 220), 1)
        out.write(frame)

    # Slide 3: Attention & Transformers (4 seconds = 40 frames)
    for _ in range(40):
        frame = np.full((height, width, 3), (20, 15, 45), dtype=np.uint8)  # Purple Slate
        cv2.putText(frame, "MODULE 3: ATTENTION & TRANSFORMERS", (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (220, 150, 255), 2)
        cv2.putText(frame, "Self-Attention Mechanism & Scaling", (50, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
        cv2.putText(frame, "- Query, Key, and Value Projections", (70, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (240, 220, 255), 1)
        cv2.putText(frame, "- Multi-Head Attention Formulations", (70, 280), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (240, 220, 255), 1)
        out.write(frame)

    out.release()

    # Merge with audio tone
    cmd = [
        "ffmpeg",
        "-i", str(temp_silent),
        "-f", "lavfi", "-i", "sine=frequency=440:duration=12",
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        "-y",
        str(final_video),
    ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    temp_silent.unlink(missing_ok=True)
    print(f"Generated demo video: {final_video}")
    return str(final_video)

if __name__ == "__main__":
    generate_demo_lecture()
