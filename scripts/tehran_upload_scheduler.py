#!/usr/bin/env python3
"""Tehran Timezone Upload Gater & Scheduler for Crowd-Cast.

Enforces:
1. Upload window: Strictly 03:05:00 to 06:50:00 Tehran time (Asia/Tehran).
2. Continuous recording: Recording is never paused or interrupted by upload schedules.
3. Internet Time Synchronization: Verifies accurate time against trusted external HTTP/NTP
   servers to prevent system clock drift / timezone desynchronization.
4. Auto-gating: Sets ~/.local/share/agent/uploads_paused to 'true' outside the window
   and 'false' inside the window.
5. Emits real-time telemetry JSON for sentinel dashboard integration.
"""

import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
import zoneinfo
from datetime import datetime, time as dt_time, timedelta, timezone
from pathlib import Path

# Paths
STATE_DIR = Path(os.path.expanduser("~/.local/state/crowdcast-ctl"))
AGENT_SHARE_DIR = Path(os.path.expanduser("~/.local/share/agent"))
UPLOADS_PAUSED_FILE = AGENT_SHARE_DIR / "uploads_paused"
PENDING_UPLOADS_FILE = AGENT_SHARE_DIR / "pending_uploads.json"
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
                        logger.info(
                            f"Internet time verified via {url} | Clock offset: {self.clock_offset:+.2f}s"
                        )
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


def get_pending_uploads_count() -> int:
    """Reads number of segments currently waiting in queue."""
    if not PENDING_UPLOADS_FILE.exists():
        return 0
    try:
        with open(PENDING_UPLOADS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return len(data)
    except Exception:
        pass
    return 0


def set_uploads_paused(paused: bool):
    """Updates uploads_paused state flag read by crowd-cast-agent."""
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


def calculate_window_status(dt_tehran: datetime):
    """Determines whether current Tehran time is within the allowed window."""
    cur_time = dt_tehran.time()
    is_open = WINDOW_START <= cur_time <= WINDOW_END

    # Calculate time to next window opening or closing
    today = dt_tehran.date()
    start_dt = datetime.combine(today, WINDOW_START, tzinfo=TEHRAN_TZ)
    end_dt = datetime.combine(today, WINDOW_END, tzinfo=TEHRAN_TZ)

    if is_open:
        seconds_remaining = (end_dt - dt_tehran).total_seconds()
        next_event = f"پنجره تا {WINDOW_END.strftime('%H:%M:%S')} باز است ({int(seconds_remaining // 60)} دقیقه باقی‌مانده)"
        next_event_en = f"Window open until {WINDOW_END.strftime('%H:%M:%S')} ({int(seconds_remaining // 60)}m remaining)"
    else:
        if dt_tehran < start_dt:
            seconds_until = (start_dt - dt_tehran).total_seconds()
        else:
            # Tomorrow at 03:05
            tomorrow_start = start_dt + timedelta(days=1)
            seconds_until = (tomorrow_start - dt_tehran).total_seconds()

        hours = int(seconds_until // 3600)
        minutes = int((seconds_until % 3600) // 60)
        next_event = f"پنجره بعدی در {WINDOW_START.strftime('%H:%M:%S')} باز می‌شود ({hours} ساعت و {minutes} دقیقه دیگر)"
        next_event_en = f"Next window opens at {WINDOW_START.strftime('%H:%M:%S')} ({hours}h {minutes}m)"

    return is_open, next_event, next_event_en


def run_scheduler_loop():
    logger.info("=== Tehran Timezone Upload Scheduler Started ===")
    logger.info(f"Target upload window: {WINDOW_START.strftime('%H:%M:%S')} to {WINDOW_END.strftime('%H:%M:%S')} (Asia/Tehran)")

    time_sync = TehranTimeSync()
    time_sync.sync_with_internet()

    last_logged_state = None

    while True:
        try:
            dt_tehran = time_sync.get_current_tehran_datetime()
            is_open, next_event_fa, next_event_en = calculate_window_status(dt_tehran)
            pending_count = get_pending_uploads_count()

            # Enforce gating
            # When window is open: uploads_paused = false
            # When window is closed: uploads_paused = true
            should_pause = not is_open
            set_uploads_paused(should_pause)

            # State transition notification
            if is_open != last_logged_state:
                if is_open:
                    logger.info(
                        f"🟢 [WINDOW OPENED] Tehran Time: {dt_tehran.strftime('%H:%M:%S')}. "
                        f"Resuming uploads! Queue has {pending_count} pending segments."
                    )
                else:
                    logger.info(
                        f"⏸️ [WINDOW CLOSED] Tehran Time: {dt_tehran.strftime('%H:%M:%S')}. "
                        f"Pausing uploads. Queue has {pending_count} pending segments."
                    )
                last_logged_state = is_open

            # Write status JSON for Sentinel web dashboard
            status_data = {
                "tehran_time": dt_tehran.strftime("%Y-%m-%d %H:%M:%S %Z"),
                "tehran_time_iso": dt_tehran.isoformat(),
                "is_window_open": is_open,
                "window_start": WINDOW_START.strftime("%H:%M:%S"),
                "window_end": WINDOW_END.strftime("%H:%M:%S"),
                "status_fa": "در حال آپلود (پنجره فعال)" if is_open else "آپلودها متوقف (خارج از پنجره مجاز)",
                "status_en": "Uploading (Window Open)" if is_open else "Uploads Paused (Outside Window)",
                "next_event_fa": next_event_fa,
                "next_event_en": next_event_en,
                "pending_segments": pending_count,
                "time_sync_source": time_sync.last_source,
                "clock_offset_seconds": round(time_sync.clock_offset, 2),
                "last_sync_timestamp": time_sync.last_sync_time,
                "updated_at": time.time(),
            }

            with open(STATUS_JSON, "w", encoding="utf-8") as f:
                json.dump(status_data, f, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.error(f"Error in scheduler iteration: {e}")

        time.sleep(5)


if __name__ == "__main__":
    run_scheduler_loop()
