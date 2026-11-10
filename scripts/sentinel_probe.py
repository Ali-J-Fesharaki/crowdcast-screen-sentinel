#!/usr/bin/env python3
"""Single-shot guest telemetry probe for CrowdCast Screen Sentinel.

Runs inside the VM and returns ALL telemetry in a single JSON payload in < 40ms:
1. Open windows from D-Bus
2. Focused window from D-Bus
3. Agent config (target_apps, capture_all, blank_video_on_untracked_app, idle_timeout_secs)
4. Agent process status & PID
5. Tehran upload schedule status
6. Recent agent log lines
"""

import ast
import json
import os
import re
import subprocess
import sys
import time
import tomllib
from pathlib import Path

ENV = os.environ.copy()
ENV["WAYLAND_DISPLAY"] = "wayland-0"
ENV["XDG_RUNTIME_DIR"] = "/run/user/1000"
ENV["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/run/user/1000/bus"
ENV["XDG_SESSION_TYPE"] = "wayland"

CONFIG_PATH = Path("/home/ubuntu/.config/agent/config.toml")
UPLOAD_STATUS_PATH = Path("/home/ubuntu/.local/state/crowdcast-ctl/tehran_upload_status.json")
NETWORK_HEALTH_PATH = Path("/home/ubuntu/.local/state/crowdcast-ctl/network_health.json")
LOG_PATH = Path("/home/ubuntu/.local/state/crowdcast-ctl/agent.log")


def probe_all():
    t0 = time.time()

    # 1. Open windows & Focus
    windows = []
    try:
        cmd_list = [
            "gdbus", "call", "--session",
            "--dest", "org.crowdcast.FocusProvider",
            "--object-path", "/org/crowdcast/FocusProvider",
            "--method", "org.crowdcast.FocusProvider.ListWindows"
        ]
        res_list = subprocess.run(cmd_list, env=ENV, capture_output=True, text=True, timeout=2)
        if res_list.returncode == 0 and res_list.stdout.strip():
            cleaned = re.sub(r'uint64\s+', '', res_list.stdout.strip())
            data = ast.literal_eval(cleaned)
            raw_list = data[0] if data and isinstance(data, tuple) else []
            for item in raw_list:
                if len(item) >= 4:
                    windows.append({
                        "window_id": int(item[0]),
                        "pid": int(item[1]),
                        "wm_class": str(item[2]),
                        "title": str(item[3]),
                    })
    except Exception:
        pass

    focused = None
    try:
        cmd_foc = [
            "gdbus", "call", "--session",
            "--dest", "org.crowdcast.FocusProvider",
            "--object-path", "/org/crowdcast/FocusProvider",
            "--method", "org.crowdcast.FocusProvider.GetFocused"
        ]
        res_foc = subprocess.run(cmd_foc, env=ENV, capture_output=True, text=True, timeout=2)
        if res_foc.returncode == 0 and res_foc.stdout.strip():
            cleaned_foc = re.sub(r'uint64\s+', '', res_foc.stdout.strip())
            data_foc = ast.literal_eval(cleaned_foc)
            if data_foc and len(data_foc) >= 4:
                focused = {
                    "window_id": int(data_foc[0]),
                    "pid": int(data_foc[1]),
                    "wm_class": str(data_foc[2]),
                    "title": str(data_foc[3]),
                }
    except Exception:
        pass

    # 2. Config
    raw_config = ""
    config_dict = {}
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                raw_config = f.read()
            config_dict = tomllib.loads(raw_config)
        except Exception:
            pass

    # 3. Agent status
    agent_running = False
    agent_pid = None
    try:
        pg = subprocess.run(["pgrep", "-f", "(^|/)crowd-cast-agent( |$)"], capture_output=True, text=True, timeout=1)
        if pg.returncode == 0 and pg.stdout.strip():
            agent_running = True
            parts = pg.stdout.strip().split()
            if parts and parts[0].isdigit():
                agent_pid = int(parts[0])
    except Exception:
        pass

    # 4. Upload status
    upload_status = {}
    if UPLOAD_STATUS_PATH.exists():
        try:
            with open(UPLOAD_STATUS_PATH, "r", encoding="utf-8") as f:
                upload_status = json.load(f)
        except Exception:
            pass

    # 4.1 Network health
    network_health = {}
    if NETWORK_HEALTH_PATH.exists():
        try:
            with open(NETWORK_HEALTH_PATH, "r", encoding="utf-8") as f:
                network_health = json.load(f)
        except Exception:
            pass

    # 5. Recent logs
    recent_logs = []
    if LOG_PATH.exists():
        try:
            with open(LOG_PATH, "r", encoding="utf-8", errors="ignore") as f:
                recent_logs = [line.strip() for line in f.readlines()[-15:]]
        except Exception:
            pass

    t1 = time.time()

    payload = {
        "probe_duration_ms": round((t1 - t0) * 1000, 2),
        "windows": windows,
        "focused_window": focused,
        "raw_config": raw_config,
        "config": config_dict,
        "agent_running": agent_running,
        "agent_pid": agent_pid,
        "upload_schedule": upload_status,
        "network_health": network_health,
        "recent_logs": recent_logs,
        "timestamp": t1,
    }

    return payload


if __name__ == "__main__":
    data = probe_all()
    print(json.dumps(data, ensure_ascii=False))
