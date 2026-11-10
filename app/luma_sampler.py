"""Luma Sampler: Extracts recent recording frames and measures pixel luminance to detect blackouts."""

import logging
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
from PIL import Image

from app.config import GUEST_RECORDINGS_DIR, HOST_RECORDINGS_DIR, SCRATCH_DIR
from app.incus_bridge import IncusBridge

logger = logging.getLogger(__name__)


class LumaSampler:
    def __init__(self, bridge: IncusBridge):
        self.bridge = bridge
        self.cached_result: Optional[Dict[str, Any]] = None
        self.last_sample_time: float = 0
        self.sample_interval: float = 2.0  # seconds

    def sample_latest_frame(self, force: bool = False) -> Dict[str, Any]:
        """Pulls the latest recording from the guest VM or host shared mount, extracts a frame and evaluates luminance."""
        now = time.time()
        if not force and self.cached_result and (now - self.last_sample_time) < self.sample_interval:
            return self.cached_result

        local_mp4_path = SCRATCH_DIR / "current_segment.mp4"
        local_frame_path = SCRATCH_DIR / "latest_preview.png"
        guest_mp4_path = ""

        # Direct Host Shared Recordings check (fastest, zero incus pull overhead)
        if HOST_RECORDINGS_DIR.exists():
            host_mp4s = sorted(
                list(HOST_RECORDINGS_DIR.glob("*.mp4")),
                key=lambda p: p.stat().st_mtime,
                reverse=True
            )
            if host_mp4s and host_mp4s[0].stat().st_size > 4096:
                latest_host_file = host_mp4s[0]
                guest_mp4_path = f"{GUEST_RECORDINGS_DIR}/{latest_host_file.name}"
                local_mp4_path = latest_host_file

        if not guest_mp4_path:
            # Fallback to querying guest VM
            find_cmd = f"ls -t {GUEST_RECORDINGS_DIR}/*.mp4 2>/dev/null | head -n 1"
            code, stdout, _ = self.bridge.exec_guest(find_cmd)
            if code != 0 or not stdout:
                res = {
                    "success": False,
                    "error": "No recording segments found in guest recordings directory.",
                    "min": 0,
                    "max": 0,
                    "mean": 0.0,
                    "is_black": True,
                    "frame_path": None,
                    "timestamp": now,
                }
                self.cached_result = res
                self.last_sample_time = now
                return res

            guest_mp4_path = stdout.strip()
            pull_code, _, pull_err = self.bridge.run_incus_cmd([
                "incus", "file", "pull", f"{self.bridge.vm_name}{guest_mp4_path}", str(local_mp4_path)
            ])
            if pull_code != 0 or not local_mp4_path.exists():
                res = {
                    "success": False,
                    "error": f"Failed to pull {guest_mp4_path}: {pull_err}",
                    "min": 0,
                    "max": 0,
                    "mean": 0.0,
                    "is_black": True,
                    "frame_path": None,
                    "timestamp": now,
                }
                self.cached_result = res
                self.last_sample_time = now
                return res

        # Extract frame using ffmpeg
        # Try seeking to 2s, fallback to start of video
        cmd_extract = [
            "ffmpeg", "-ss", "00:00:02", "-i", str(local_mp4_path),
            "-vframes", "1", str(local_frame_path), "-y"
        ]
        ffmpeg_res = subprocess.run(cmd_extract, capture_output=True, text=True)
        if ffmpeg_res.returncode != 0 or not local_frame_path.exists():
            # Retry at 0.5s for brand-new segments
            cmd_retry = [
                "ffmpeg", "-ss", "00:00:00.5", "-i", str(local_mp4_path),
                "-vframes", "1", str(local_frame_path), "-y"
            ]
            subprocess.run(cmd_retry, capture_output=True)

        if not local_frame_path.exists():
            res = {
                "success": False,
                "error": "Failed to extract frame from video file.",
                "min": 0,
                "max": 0,
                "mean": 0.0,
                "is_black": True,
                "frame_path": None,
                "timestamp": now,
            }
            self.cached_result = res
            self.last_sample_time = now
            return res

        try:
            with Image.open(local_frame_path) as img:
                arr = np.array(img.convert("L"))
                val_min = int(arr.min())
                val_max = int(arr.max())
                val_mean = round(float(arr.mean()), 2)

                # Pure black is Max == 0 and Mean == 0.0
                is_black = (val_max == 0) or (val_mean < 1.0)

                res = {
                    "success": True,
                    "video_source": guest_mp4_path,
                    "min": val_min,
                    "max": val_max,
                    "mean": val_mean,
                    "is_black": is_black,
                    "frame_path": str(local_frame_path),
                    "timestamp": now,
                }
                self.cached_result = res
                self.last_sample_time = now
                return res
        except Exception as e:
            logger.error(f"Error computing image luma: {e}")
            res = {
                "success": False,
                "error": str(e),
                "min": 0,
                "max": 0,
                "mean": 0.0,
                "is_black": True,
                "frame_path": None,
                "timestamp": now,
            }
            self.cached_result = res
            self.last_sample_time = now
            return res
