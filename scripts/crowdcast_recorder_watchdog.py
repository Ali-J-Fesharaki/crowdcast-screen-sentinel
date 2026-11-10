#!/usr/bin/env python3
"""Crowd-Cast Autonomous Recorder Watchdog & Assurance Daemon.

Ensures:
1. crowd-cast-agent is always running and actively recording.
2. Recordings are saved to the persistent shared directory (/home/ubuntu/shared-recordings/crowd-cast-recordings).
3. /tmp/crowd-cast-recordings symlinks to shared-recordings.
4. capture_all=false & blank_video_on_untracked_app=false to prevent black screen recordings.
5. All open windows are whitelisted dynamically.
6. Recording files are actively growing; stalled streams are cleanly auto-recovered.
"""

import ast
import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# Paths inside crowd-vm
CONFIG_PATH = Path("/home/ubuntu/.config/agent/config.toml")
SHARED_RECORDINGS_DIR = Path("/home/ubuntu/shared-recordings/crowd-cast-recordings")
TMP_RECORDINGS_DIR = Path("/tmp/crowd-cast-recordings")
CTL_PATH = Path("/home/ubuntu/.local/bin/crowdcast-ctl")
LOG_PATH = Path("/home/ubuntu/.local/state/crowdcast-ctl/agent.log")
WATCHDOG_LOG = Path("/home/ubuntu/.local/state/crowdcast-ctl/watchdog.log")
USER_WHITELIST_PATH = Path("/home/ubuntu/.config/agent/user_whitelist.json")

# Ensure state directory exists
WATCHDOG_LOG.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(str(WATCHDOG_LOG)),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("crowdcast-watchdog")

# Core applications that should always be allowed
ALWAYS_ALLOWED = {
    "com.microsoft.VSCode",
    "code",
    "firefox",
    "gnome-terminal-server",
    "org.gnome.Terminal",
    "org.gnome.Nautilus",
    "nautilus",
    "com.anthropic.Claude",
    "OpenResearch",
    "apport-gtk",
    "org.gnome.TextEditor",
}


def get_guest_env():
    env = os.environ.copy()
    env["WAYLAND_DISPLAY"] = "wayland-0"
    env["XDG_RUNTIME_DIR"] = "/run/user/1000"
    env["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/run/user/1000/bus"
    env["XDG_SESSION_TYPE"] = "wayland"
    return env


def ensure_symlinks_and_dirs():
    SHARED_RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

    # If /tmp/crowd-cast-recordings is a real directory (not a symlink), migrate files
    if TMP_RECORDINGS_DIR.exists() and not TMP_RECORDINGS_DIR.is_symlink():
        logger.info("Migrating files from /tmp/crowd-cast-recordings to shared directory...")
        for p in TMP_RECORDINGS_DIR.glob("*"):
            target = SHARED_RECORDINGS_DIR / p.name
            if not target.exists():
                try:
                    subprocess.run(["cp", "-u", str(p), str(target)], check=False)
                except Exception:
                    pass
        try:
            subprocess.run(["rm", "-rf", str(TMP_RECORDINGS_DIR)], check=False)
            TMP_RECORDINGS_DIR.symlink_to(SHARED_RECORDINGS_DIR)
            logger.info(f"Created symlink: {TMP_RECORDINGS_DIR} -> {SHARED_RECORDINGS_DIR}")
        except Exception as e:
            logger.warning(f"Could not symlink tmp directory: {e}")
    elif not TMP_RECORDINGS_DIR.exists():
        try:
            TMP_RECORDINGS_DIR.symlink_to(SHARED_RECORDINGS_DIR)
        except Exception:
            pass


def get_open_windows():
    """Queries FocusProvider for all open windows."""
    cmd = [
        "gdbus", "call", "--session",
        "--dest", "org.crowdcast.FocusProvider",
        "--object-path", "/org/crowdcast/FocusProvider",
        "--method", "org.crowdcast.FocusProvider.ListWindows"
    ]
    try:
        res = subprocess.run(cmd, env=get_guest_env(), capture_output=True, text=True, timeout=3)
        if res.returncode == 0 and res.stdout.strip():
            cleaned = re.sub(r'uint64\s+', '', res.stdout.strip())
            data = ast.literal_eval(cleaned)
            return data[0] if data and isinstance(data, tuple) else []
    except Exception:
        pass
    return []


def get_focused_window():
    """Queries FocusProvider for currently focused window."""
    cmd = [
        "gdbus", "call", "--session",
        "--dest", "org.crowdcast.FocusProvider",
        "--object-path", "/org/crowdcast/FocusProvider",
        "--method", "org.crowdcast.FocusProvider.GetFocused"
    ]
    try:
        res = subprocess.run(cmd, env=get_guest_env(), capture_output=True, text=True, timeout=3)
        if res.returncode == 0 and res.stdout.strip():
            cleaned = re.sub(r'uint64\s+', '', res.stdout.strip())
            data = ast.literal_eval(cleaned)
            if data and len(data) >= 4:
                return {"window_id": data[0], "pid": data[1], "wm_class": data[2], "title": data[3]}
    except Exception:
        pass
    return None


def focus_first_tracked_window(apps):
    """Brings a known tracked window to front so recording leaves blank_scene."""
    desktop_map = {
        "firefox": "firefox",
        "com.microsoft.VSCode": "com.microsoft.VSCode",
        "code": "code",
        "org.gnome.Terminal": "org.gnome.Terminal",
        "gnome-terminal-server": "org.gnome.Terminal",
        "org.gnome.Nautilus": "org.gnome.Nautilus",
        "com.anthropic.Claude": "com.anthropic.Claude",
    }
    for app in apps:
        if app in desktop_map:
            cmd = ["gtk-launch", desktop_map[app]]
            subprocess.run(cmd, env=get_guest_env(), capture_output=True, check=False)
            time.sleep(1)
            break


def sanitize_config(open_window_classes):
    """Enforces zero-blackout configuration and target_apps whitelist."""
    if not CONFIG_PATH.exists():
        return False, []

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        orig_content = content

        # 1. Enforce output_directory = "/home/ubuntu/shared-recordings/crowd-cast-recordings"
        target_dir_str = str(SHARED_RECORDINGS_DIR)
        content = re.sub(
            r'output_directory\s*=\s*"[^"]*"',
            f'output_directory = "{target_dir_str}"',
            content
        )

        # 2. Enforce capture_all = false (Prevents 100% black screen portal trap)
        content = re.sub(r'capture_all\s*=\s*(true|false)', 'capture_all = false', content)

        # 3. Enforce blank_video_on_untracked_app = false
        content = re.sub(r'blank_video_on_untracked_app\s*=\s*(true|false)', 'blank_video_on_untracked_app = false', content)

        # 4. Enforce idle_timeout_secs = 600 or 0
        content = re.sub(r'idle_timeout_secs\s*=\s*\d+', 'idle_timeout_secs = 600', content)

        # 5. Extract current target_apps and merge with open windows
        current_apps = set(ALWAYS_ALLOWED)
        match = re.search(r'target_apps\s*=\s*\[(.*?)\]', content, re.DOTALL)
        if match:
            found = re.findall(r'"([^"]+)"', match.group(1))
            current_apps.update(found)

        # Add all open windows
        current_apps.update(open_window_classes)

        # Read user whitelist if present
        if USER_WHITELIST_PATH.exists():
            try:
                with open(USER_WHITELIST_PATH, "r", encoding="utf-8") as wf:
                    current_apps.update(json.load(wf))
            except Exception:
                pass

        formatted = ",\n  ".join(f'"{a}"' for a in sorted(current_apps))
        replacement = f'target_apps = [\n  {formatted}\n]'
        content = re.sub(r'target_apps\s*=\s*\[.*?\]', replacement, content, flags=re.DOTALL)

        if content != orig_content:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                f.write(content)
            logger.info("Updated configuration with persistent directory and safe flags.")
            return True, list(current_apps)

        return False, list(current_apps)
    except Exception as e:
        logger.error(f"Error sanitizing config: {e}")
        return False, []


def is_agent_running():
    try:
        res = subprocess.run(["pgrep", "-f", "(^|/)crowd-cast-agent( |$)"], capture_output=True, text=True)
        return res.returncode == 0
    except Exception:
        return False


def start_agent():
    logger.info("Starting crowd-cast-agent via crowdcast-ctl...")
    cmd = [str(CTL_PATH), "start"]
    res = subprocess.run(cmd, env=get_guest_env(), capture_output=True, text=True)
    logger.info(f"Start output: {res.stdout.strip()}")
    time.sleep(2)


def restart_agent():
    logger.info("Restarting crowd-cast-agent...")
    cmd = [str(CTL_PATH), "restart"]
    res = subprocess.run(cmd, env=get_guest_env(), capture_output=True, text=True)
    logger.info(f"Restart output: {res.stdout.strip()}")
    time.sleep(2)


def check_recording_health():
    """Checks if recording files in shared directory are growing."""
    mp4_files = sorted(
        list(SHARED_RECORDINGS_DIR.glob("*.mp4")),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )
    if not mp4_files:
        return False, "No MP4 files found in recordings directory."

    latest = mp4_files[0]
    size = latest.stat().st_size
    mtime = latest.stat().st_mtime
    age = time.time() - mtime

    return True, f"Latest: {latest.name} ({size / 1024 / 1024:.2f} MB, modified {age:.1f}s ago)"


def run_watchdog_loop():
    logger.info("=== Crowd-Cast Recorder Watchdog Service Started ===")
    ensure_symlinks_and_dirs()

    last_health_check = time.time()
    last_file_size = -1
    stall_count = 0

    while True:
        try:
            # 1. Discover open windows
            windows = get_open_windows()
            open_classes = [w[2] for w in windows if len(w) >= 3 and w[2]]

            # 2. Keep config sanitized and aligned
            config_changed, target_apps = sanitize_config(open_classes)

            # 3. Check agent status
            if not is_agent_running():
                logger.warning("crowd-cast-agent is NOT running! Launching...")
                start_agent()
                focus_first_tracked_window(target_apps)
                stall_count = 0

            # 4. Check if config changed and restart agent if needed
            elif config_changed:
                logger.info("Configuration updated; refreshing capture...")
                restart_agent()
                focus_first_tracked_window(target_apps)

            # 5. Check recording health every 15s
            now = time.time()
            if now - last_health_check >= 15:
                last_health_check = now
                has_files, status_msg = check_recording_health()
                logger.info(f"[HEALTH] {status_msg}")

                # Check if current video file is stalled (no byte growth for > 45s while agent is running)
                mp4_files = sorted(
                    list(SHARED_RECORDINGS_DIR.glob("*.mp4")),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True
                )
                if mp4_files:
                    latest_size = mp4_files[0].stat().st_size
                    if latest_size == last_file_size and latest_size > 0:
                        stall_count += 1
                        logger.warning(f"Recording file size unchanged ({latest_size} bytes, stall_count={stall_count})")
                        if stall_count >= 3:  # 45 seconds of no growth
                            logger.warning("Stream appears stalled! Restarting recorder...")
                            restart_agent()
                            focus_first_tracked_window(target_apps)
                            stall_count = 0
                    else:
                        stall_count = 0
                        last_file_size = latest_size

        except Exception as e:
            logger.error(f"Error in watchdog iteration: {e}")

        time.sleep(5)


if __name__ == "__main__":
    run_watchdog_loop()
