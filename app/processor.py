from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

import cv2
import mediapipe as mp
import numpy as np
from scipy.ndimage import gaussian_filter1d

ProgressCallback = Callable[[int, str], None]

# ─── CONFIGURATION ────────────────────────────────────────────
TARGET_RATIO = 9 / 16
SMOOTHING_SIGMA = 2.5
BASE_ZOOM_FACTOR = 1.2
MIN_CROP_SCALE = 0.70
MAX_CROP_SCALE = 0.95
ZOOM_SMOOTH_MULT = 3.0
PADDING_TOP = 0.18


def convert_to_mp4(input_path: Path, output_path: Path) -> Path:
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        str(output_path),
    ]
    subprocess.run(cmd, check=True)
    return output_path


def safe_crop_resize(frame, cx, cy, crop_w, crop_h, out_w, out_h):
    fh, fw = frame.shape[:2]

    target_ar = out_w / out_h
    crop_ar = crop_w / crop_h if crop_h > 0 else target_ar

    if crop_ar > target_ar:
        crop_w = int(crop_h * target_ar)
    else:
        crop_h = int(crop_w / target_ar)

    crop_w = min(fw, crop_w)
    crop_h = min(fh, crop_h)

    x1 = int(np.clip(cx - crop_w / 2, 0, fw - crop_w))
    y1 = int(np.clip(cy - crop_h / 2, 0, fh - crop_h))
    x2 = x1 + crop_w
    y2 = y1 + crop_h

    cropped = frame[y1:y2, x1:x2]
    if cropped.size == 0:
        cropped = frame

    return cv2.resize(cropped, (out_w, out_h), interpolation=cv2.INTER_CUBIC)


def _run_ffmpeg_merge(video_path: Path, source_input: Path, final_path: Path) -> None:
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-i",
        str(source_input),
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-shortest",
        str(final_path),
    ]
    subprocess.run(cmd, check=True)


def process_video(input_path: Path, output_path: Path, on_progress: ProgressCallback | None = None) -> Path:
    """Run face-tracked rendering.

    Input can be most common formats; it is normalized to mp4 first.
    Output is mp4 portrait with audio.
    """

    def progress(percent: int, stage: str) -> None:
        if on_progress:
            on_progress(max(0, min(100, percent)), stage)

    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="face_track_") as tmp_dir:
        tmp_dir_path = Path(tmp_dir)
        clean_input = convert_to_mp4(input_path, tmp_dir_path / "clean_input.mp4")
        temp_video = tmp_dir_path / "tracked_video.mp4"
        final_video = tmp_dir_path / "final_output.mp4"

        progress(5, "Preparing video")

        mp_face = mp.solutions.face_detection
        face_detection = mp_face.FaceDetection(model_selection=1, min_detection_confidence=0.45)

        cap = cv2.VideoCapture(str(clean_input))
        if not cap.isOpened():
            raise FileNotFoundError(f"Cannot open: {clean_input}")

        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        out_w, out_h = int(h * (9 / 16)), h
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        raw_data = []
        last_valid = [w / 2, h / 2, w * 0.15]

        frame_idx = 0
        progress(10, "Analyzing faces")
        while cap.isOpened():
            success, frame = cap.read()
            if not success:
                break

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = face_detection.process(rgb)

            if results.detections:
                bbox = results.detections[0].location_data.relative_bounding_box

                xmin = max(0.0, bbox.xmin)
                ymin = max(0.0, bbox.ymin)
                bw = min(bbox.width, 1.0 - xmin)
                bh = min(bbox.height, 1.0 - ymin)

                cx = (xmin + bw / 2) * w
                cy = (ymin + bh / 2) * h - (bh * h * PADDING_TOP)
                fw = bw * w

                entry = [cx, cy, fw]
                last_valid = entry
            else:
                entry = last_valid.copy()

            raw_data.append(entry)
            frame_idx += 1

            if total > 0 and frame_idx % 30 == 0:
                progress(10 + int((frame_idx / total) * 35), "Analyzing faces")

        raw_data = np.array(raw_data)
        smooth_x = gaussian_filter1d(raw_data[:, 0], sigma=SMOOTHING_SIGMA)
        smooth_y = gaussian_filter1d(raw_data[:, 1], sigma=SMOOTHING_SIGMA)
        smooth_fw = gaussian_filter1d(raw_data[:, 2], sigma=SMOOTHING_SIGMA * ZOOM_SMOOTH_MULT)

        warmup_frames = int(fps * 2)
        if len(smooth_x) > warmup_frames:
            smooth_x[:warmup_frames] = smooth_x[warmup_frames]
            smooth_y[:warmup_frames] = smooth_y[warmup_frames]
            smooth_fw[:warmup_frames] = smooth_fw[warmup_frames]

        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        out = cv2.VideoWriter(str(temp_video), fourcc, fps, (out_w, out_h))

        min_crop_h = int(h * MIN_CROP_SCALE)
        max_crop_h = int(h * MAX_CROP_SCALE)

        progress(50, "Rendering tracked video")
        for i in range(len(smooth_x)):
            success, frame = cap.read()
            if not success:
                break

            raw_crop_h = int(smooth_fw[i] * BASE_ZOOM_FACTOR / TARGET_RATIO)
            raw_crop_h = int(raw_crop_h * 2)

            crop_h = int(np.clip(raw_crop_h, min_crop_h, max_crop_h))
            crop_w = int(crop_h * TARGET_RATIO)

            final = safe_crop_resize(
                frame,
                cx=smooth_x[i],
                cy=smooth_y[i],
                crop_w=crop_w,
                crop_h=crop_h,
                out_w=out_w,
                out_h=out_h,
            )

            out.write(final)

            if len(smooth_x) > 0 and i % 30 == 0:
                progress(50 + int((i / len(smooth_x)) * 40), "Rendering tracked video")

        cap.release()
        out.release()

        progress(92, "Merging audio")
        _run_ffmpeg_merge(temp_video, clean_input, final_video)

        os.replace(final_video, output_path)
        progress(100, "Completed")

    return output_path
