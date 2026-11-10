#!/usr/bin/env python3
"""Tehran Timezone Upload Gater, Scheduler & Progress Tracker for Crowd-Cast.

Features:
1. Schedule: Strictly 03:05:00 to 06:50:00 Tehran time (Asia/Tehran).
2. Internet Time Sync: Verifies real time against google.com / cloudflare.com to cancel clock drift.
3. Manual Override: 'Force Upload Now' button starts upload immediately regardless of time.
4. Auto-Queueing: Scans recording directory for completed un-uploaded segments and populates pending_uploads.json.
5. Real-Time Progress Bar: Tracks completed vs pending segments, upload percent (0-100%), and active chunk.
6. Zero Recording Interruption: Capture is 100% continuous and never stopped.
"""

import ast
import json
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.request
import zoneinfo
from datetime import datetime, time as dt_time, timedelta, timezone
from pathlib import Path

# Add ~/.local/bin for crowdcast_net_monitor import
if "/home/ubuntu/.local/bin" not in sys.path:
    sys.path.append("/home/ubuntu/.local/bin")

try:
    from crowdcast_net_monitor import (
        get_full_network_and_upload_telemetry,
        trigger_native_upload_toggle,
    )
except ImportError:
    trigger_native_upload_toggle = lambda act: {"success": False}
    get_full_network_and_upload_telemetry = lambda: {}

# Paths inside crowd-vm
STATE_DIR = Path("/home/ubuntu/.local/state/crowdcast-ctl")
AGENT_SHARE_DIR = Path("/home/ubuntu/.local/share/agent")
RECORDINGS_DIR = Path("/home/ubuntu/shared-recordings/crowd-cast-recordings")
LOGS_DIR = Path("/home/ubuntu/.local/state/agent/logs")

UPLOADS_PAUSED_FILE = AGENT_SHARE_DIR / "uploads_paused"
PENDING_UPLOADS_FILE = AGENT_SHARE_DIR / "pending_uploads.json"
MANUAL_OVERRIDE_FLAG = STATE_DIR / "manual_upload.flag"
STATUS_JSON = STATE_DIR / "tehran_upload_status.json"
LOG_FILE = STATE_DIR / "tehran_upload_scheduler.log"

STATE_DIR.mkdir(parents=True, exist_ok=True)
AGENT_SHARE_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(str(LOG_FILE)),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("tehran-uploader")

# Schedule constraints (Asia/Tehran)
WINDOW_START = dt_time(3, 5, 0)   # 03:05:00 AM Tehran
WINDOW_END = dt_time(6, 50, 0)    # 06:50:00 AM Tehran
TEHRAN_TZ = zoneinfo.ZoneInfo("Asia/Tehran")

TIME_SERVERS = [
    "https://www.google.com",
    "https://cloudflare.com",
    "https://www.wikipedia.org",
]


class TehranTimeSync:
    def __init__(self):
        self.clock_offset = 0.0  # real_utc_ts - local_system_ts
        self.last_sync_time = 0.0
        self.sync_interval = 600.0  # re-sync with internet every 10 minutes
        self.last_source = "uninitialized"

    def sync_with_internet(self) -> bool:
        """Fetches authoritative UTC time from HTTP Date headers and computes clock offset."""
        for url in TIME_SERVERS:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (SentinelTimeSync/1.0)"})
                t_send = time.time()
                with urllib.request.urlopen(req, timeout=5) as resp:
                    t_recv = time.time()
                    date_header = resp.headers.get("Date")
                    if date_header:
                        dt_utc = datetime.strptime(date_header, "%a, %d %b %Y %H:%M:%S GMT").replace(tzinfo=timezone.utc)
                        real_utc_ts = dt_utc.timestamp()
                        local_midpoint = (t_send + t_recv) / 2.0
                        self.clock_offset = real_utc_ts - local_midpoint
                        self.last_sync_time = time.time()
                        self.last_source = url
                        logger.info(f"Internet time verified via {url} | Clock offset: {self.clock_offset:+.2f}s")
                        return True
            except Exception as e:
                logger.debug(f"Time sync check failed for {url}: {e}")

        logger.warning("Internet time sync failed across all endpoints; falling back to local system clock.")
        self.last_source = "local_system_clock (unverified)"
        return False

    def get_current_tehran_datetime(self) -> datetime:
        """Returns verified current datetime in Asia/Tehran."""
        now_local = time.time()
        if now_local - self.last_sync_time > self.sync_interval:
            self.sync_with_internet()

        adjusted_utc_ts = now_local + self.clock_offset
        dt_utc = datetime.fromtimestamp(adjusted_utc_ts, tz=timezone.utc)
        return dt_utc.astimezone(TEHRAN_TZ)


class UploadProgressTracker:
    def __init__(self):
        self.initial_batch_total = 0
        self.initial_batch_bytes = 0
        self.session_uploaded_count = 0
        self.session_uploaded_bytes = 0
        self.session_start_time = 0.0
        self.last_known_uploaded_segments = set()
        self._init_history()

    def _init_history(self):
        """Loads historical successfully uploaded segments from agent logs."""
        self.last_known_uploaded_segments = self.get_uploaded_segments_from_logs()

    def get_uploaded_segments_from_logs(self):
        """Scans agent logs for Successfully uploaded segment."""
        uploaded = set()
        for p in LOGS_DIR.glob("crowd-cast.log.*"):
            try:
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if "Successfully uploaded segment" in line:
                            m = re.search(r"Successfully uploaded segment\s+([\w-]+)", line)
                            if m:
                                uploaded.add(m.group(1))
            except Exception:
                pass
        return uploaded

    def get_current_uploading_chunk(self):
        """Checks agent logs for the most recently started chunk upload."""
        for p in sorted(LOGS_DIR.glob("crowd-cast.log.*"), key=lambda x: x.stat().st_mtime, reverse=True)[:1]:
            try:
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()[-40:]
                    for line in reversed(lines):
                        if "Uploading chunk" in line:
                            m = re.search(r"Uploading chunk\s+([\w-]+)", line)
                            if m:
                                return m.group(1)
            except Exception:
                pass
        return None

    def scan_unuploaded_disk_segments(self):
        """Finds completed segments on disk that have not yet been uploaded."""
        all_uploaded = self.get_uploaded_segments_from_logs()
        unuploaded = []

        for mp4 in sorted(RECORDINGS_DIR.glob("recording_*.mp4"), key=lambda x: x.stat().st_mtime):
            base = mp4.stem  # recording_<sess>_seg<num>
            seg_name = base.replace("recording_", "")
            size = mp4.stat().st_size
            if size > 15000 and seg_name not in all_uploaded:
                # Find matching msgpack
                sess_match = re.match(r"(.*)_seg(\d+)", seg_name)
                input_file = None
                if sess_match:
                    cand = RECORDINGS_DIR / f"input_{sess_match.group(1)}_seg{sess_match.group(2)}.msgpack"
                    if cand.exists():
                        input_file = cand

                unuploaded.append({
                    "segment_name": seg_name,
                    "session_id": sess_match.group(1) if sess_match else seg_name,
                    "video_path": str(mp4),
                    "input_path": str(input_file) if input_file else "",
                    "size_bytes": size + (input_file.stat().st_size if input_file else 0),
                    "mtime": mp4.stat().st_mtime,
                })
        return unuploaded

    def sync_pending_uploads_file(self):
        """Ensures all unuploaded segments are present in pending_uploads.json."""
        unuploaded = self.scan_unuploaded_disk_segments()
        existing_entries = []
        if PENDING_UPLOADS_FILE.exists():
            try:
                with open(PENDING_UPLOADS_FILE, "r", encoding="utf-8") as f:
                    existing_entries = json.load(f)
                    if not isinstance(existing_entries, list):
                        existing_entries = []
            except Exception:
                existing_entries = []

        existing_videos = {e.get("video_path") for e in existing_entries}
        added = 0
        for item in unuploaded:
            if item["video_path"] not in existing_videos:
                existing_entries.append({
                    "session_id": item["session_id"],
                    "video_path": item["video_path"],
                    "input_path": item["input_path"],
                    "buffered_at_epoch_s": int(item["mtime"]),
                })
                added += 1

        if added > 0:
            try:
                with open(PENDING_UPLOADS_FILE, "w", encoding="utf-8") as f:
                    json.dump(existing_entries, f, indent=2)
                logger.info(f"Synchronized {added} unuploaded segments into pending_uploads.json")
            except Exception as e:
                logger.error(f"Failed to update pending_uploads.json: {e}")

        return len(existing_entries), sum(item["size_bytes"] for item in unuploaded)

    def update_progress(self, is_uploading_active: bool):
        """Computes current upload progress percentage and metrics."""
        current_uploaded_set = self.get_uploaded_segments_from_logs()
        new_uploaded = current_uploaded_set - self.last_known_uploaded_segments
        if new_uploaded:
            self.session_uploaded_count += len(new_uploaded)
            self.last_known_uploaded_segments = current_uploaded_set
            logger.info(f"Detected {len(new_uploaded)} newly completed upload(s) in this session!")

        # Read pending entries
        pending_count = 0
        if PENDING_UPLOADS_FILE.exists():
            try:
                with open(PENDING_UPLOADS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        pending_count = len(data)
            except Exception:
                pass

        # If upload just started, set batch baseline
        if is_uploading_active and self.session_start_time == 0.0:
            self.session_start_time = time.time()
            self.initial_batch_total = pending_count + self.session_uploaded_count

        if not is_uploading_active:
            self.session_start_time = 0.0

        # Calculate progress percentage
        total_items = max(self.initial_batch_total, pending_count + self.session_uploaded_count)
        if total_items > 0:
            pct = round((self.session_uploaded_count / total_items) * 100.0, 1)
            if pending_count == 0 and self.session_uploaded_count > 0:
                pct = 100.0
        else:
            pct = 100.0 if pending_count == 0 else 0.0

        active_chunk = self.get_current_uploading_chunk() if is_uploading_active else None

        return {
            "pending_count": pending_count,
            "session_uploaded": self.session_uploaded_count,
            "total_items": total_items,
            "progress_percent": pct,
            "active_chunk": active_chunk,
        }


def set_uploads_paused(paused: bool):
    """Updates uploads_paused state flag read by crowd-cast-agent and native D-Bus menu."""
    val_str = "true" if paused else "false"
    current_val = ""
    if UPLOADS_PAUSED_FILE.exists():
        try:
            with open(UPLOADS_PAUSED_FILE, "r", encoding="utf-8") as f:
                current_val = f.read().strip()
        except Exception:
            pass

    if current_val != val_str:
        try:
            with open(UPLOADS_PAUSED_FILE, "w", encoding="utf-8") as f:
                f.write(val_str)
            logger.info(f"Updated uploads_paused flag to: '{val_str}'")
        except Exception as e:
            logger.error(f"Failed to write uploads_paused file: {e}")

        # Dispatch native D-Bus menu event to crowd-cast tray thread
        try:
            action = "pause" if paused else "resume"
            res = trigger_native_upload_toggle(action)
            logger.info(f"Native D-Bus upload toggle ({action}) triggered: {res.get('message_fa')}")
        except Exception as e:
            logger.warning(f"Could not trigger native D-Bus upload toggle: {e}")


def calculate_window_status(dt_tehran: datetime, manual_override: bool):
    """Determines whether upload is allowed."""
    cur_time = dt_tehran.time()
    is_scheduled_open = WINDOW_START <= cur_time <= WINDOW_END
    is_active = is_scheduled_open or manual_override

    today = dt_tehran.date()
    start_dt = datetime.combine(today, WINDOW_START, tzinfo=TEHRAN_TZ)
    end_dt = datetime.combine(today, WINDOW_END, tzinfo=TEHRAN_TZ)

    if manual_override:
        next_event_fa = "آپلود دستی فعال است (با کلیک شما شروع شده)"
        next_event_en = "Manual Upload Active (Override initiated by user)"
    elif is_scheduled_open:
        seconds_remaining = (end_dt - dt_tehran).total_seconds()
        next_event_fa = f"پنجره تا {WINDOW_END.strftime('%H:%M:%S')} باز است ({int(seconds_remaining // 60)} دقیقه باقی‌مانده)"
        next_event_en = f"Window open until {WINDOW_END.strftime('%H:%M:%S')} ({int(seconds_remaining // 60)}m remaining)"
    else:
        if dt_tehran < start_dt:
            seconds_until = (start_dt - dt_tehran).total_seconds()
        else:
            tomorrow_start = start_dt + timedelta(days=1)
            seconds_until = (tomorrow_start - dt_tehran).total_seconds()

        hours = int(seconds_until // 3600)
        minutes = int((seconds_until % 3600) // 60)
        next_event_fa = f"پنجره بعدی در {WINDOW_START.strftime('%H:%M:%S')} باز می‌شود ({hours} ساعت و {minutes} دقیقه دیگر)"
        next_event_en = f"Next window opens at {WINDOW_START.strftime('%H:%M:%S')} ({hours}h {minutes}m)"

    return is_active, is_scheduled_open, next_event_fa, next_event_en


def run_scheduler_loop():
    logger.info("=== Tehran Timezone Upload Scheduler & Progress Engine Started ===")
    logger.info(f"Target upload window: {WINDOW_START.strftime('%H:%M:%S')} to {WINDOW_END.strftime('%H:%M:%S')} (Asia/Tehran)")

    time_sync = TehranTimeSync()
    time_sync.sync_with_internet()

    tracker = UploadProgressTracker()
    tracker.sync_pending_uploads_file()

    last_logged_state = None
    last_net_probe = 0.0

    while True:
        try:
            now = time.time()
            if now - last_net_probe > 20:
                last_net_probe = now
                try:
                    get_full_network_and_upload_telemetry()
                except Exception:
                    pass

            dt_tehran = time_sync.get_current_tehran_datetime()
            manual_override = MANUAL_OVERRIDE_FLAG.exists()
            is_active, is_sched_open, next_event_fa, next_event_en = calculate_window_status(dt_tehran, manual_override)

            # Keep unuploaded segments synced in pending queue
            tracker.sync_pending_uploads_file()

            # Enforce gating
            should_pause = not is_active
            set_uploads_paused(should_pause)

            # Update progress metrics
            prog = tracker.update_progress(is_active)

            # If manual override and queue reached 0, auto-release override after completion
            if manual_override and prog["pending_count"] == 0 and prog["session_uploaded"] > 0:
                logger.info("Manual upload queue is fully empty and completed! Disengaging override...")
                try:
                    MANUAL_OVERRIDE_FLAG.unlink(missing_ok=True)
                except Exception:
                    pass

            # State transition notification
            if is_active != last_logged_state:
                if is_active:
                    mode = "دستی (Manual)" if manual_override else "زمان‌بندی شده (Scheduled)"
                    logger.info(
                        f"🟢 [UPLOAD STARTED - {mode}] Tehran Time: {dt_tehran.strftime('%H:%M:%S')}. "
                        f"Queue has {prog['pending_count']} pending segments."
                    )
                else:
                    logger.info(
                        f"⏸️ [UPLOAD PAUSED] Tehran Time: {dt_tehran.strftime('%H:%M:%S')}. "
                        f"Queue has {prog['pending_count']} pending segments."
                    )
                last_logged_state = is_active

            # Format status badge text
            if manual_override:
                status_fa = "🚀 آپلود دستی در حال اجرا (Manual Override)"
                status_en = "Manual Upload Active"
            elif is_sched_open:
                status_fa = "🟢 آپلود خودکار فعال (پنجره ۳:۰۵ تا ۶:۵۰)"
                status_en = "Scheduled Upload Active"
            else:
                status_fa = "⏸️ آپلود متوقف (خارج از پنجره مجاز)"
                status_en = "Uploads Paused (Outside Window)"

            status_data = {
                "tehran_time": dt_tehran.strftime("%Y-%m-%d %H:%M:%S %Z"),
                "tehran_time_iso": dt_tehran.isoformat(),
                "is_active": is_active,
                "is_window_open": is_sched_open,
                "manual_override": manual_override,
                "window_start": WINDOW_START.strftime("%H:%M:%S"),
                "window_end": WINDOW_END.strftime("%H:%M:%S"),
                "status_fa": status_fa,
                "status_en": status_en,
                "next_event_fa": next_event_fa,
                "next_event_en": next_event_en,
                "pending_segments": prog["pending_count"],
                "uploaded_segments": prog["session_uploaded"],
                "total_batch_segments": prog["total_items"],
                "progress_percent": prog["progress_percent"],
                "active_chunk": prog["active_chunk"],
                "time_sync_source": time_sync.last_source,
                "clock_offset_seconds": round(time_sync.clock_offset, 2),
                "last_sync_timestamp": time_sync.last_sync_time,
                "updated_at": time.time(),
            }

            with open(STATUS_JSON, "w", encoding="utf-8") as f:
                json.dump(status_data, f, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.error(f"Error in scheduler iteration: {e}")

        time.sleep(3)


if __name__ == "__main__":
    run_scheduler_loop()
