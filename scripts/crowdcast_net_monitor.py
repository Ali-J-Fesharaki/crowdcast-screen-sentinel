#!/usr/bin/env python3
"""CrowdCast Cloud Network Health, Latency & Native D-Bus Menu Controller."""

import ast
import json
import logging
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

ENV = os.environ.copy()
ENV.setdefault("WAYLAND_DISPLAY", "wayland-0")
ENV.setdefault("XDG_RUNTIME_DIR", "/run/user/1000")
ENV.setdefault("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")
ENV.setdefault("XDG_SESSION_TYPE", "wayland")

LOGS_DIR = Path("/home/ubuntu/.local/state/agent/logs")
NET_STATUS_FILE = Path("/home/ubuntu/.local/state/crowdcast-ctl/network_health.json")
NET_STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("crowdcast-netmon")

CLOUD_ENDPOINTS = {
    "google_auth": {
        "url": "https://oauth2.googleapis.com",
        "name_fa": "احراز هویت گوگل (OAuth2)",
        "name_en": "Google Auth",
    },
    "aws_api": {
        "url": "https://ob3iugfiy2.execute-api.us-east-1.amazonaws.com",
        "name_fa": "سرور API کرودکست (AWS API Gateway)",
        "name_en": "CrowdCast API",
    },
    "aws_s3": {
        "url": "https://s3.amazonaws.com",
        "name_fa": "مخزن داده ابری (AWS S3)",
        "name_en": "AWS S3 Storage",
    },
}

PROXY_HOST = "10.5.48.1"
PROXY_PORT = 10808


def check_proxy_socket() -> Dict[str, Any]:
    """Tests if host SOCKS5 proxy port is listening and responsive."""
    t0 = time.time()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2.0)
        s.connect((PROXY_HOST, PROXY_PORT))
        s.close()
        rtt = round((time.time() - t0) * 1000, 1)
        return {"status": "ONLINE", "latency_ms": rtt, "host": PROXY_HOST, "port": PROXY_PORT}
    except Exception as e:
        return {"status": "OFFLINE", "error": str(e), "latency_ms": None}


def probe_endpoint(url: str, timeout: float = 4.0) -> Dict[str, Any]:
    """Probes an HTTPS endpoint and returns HTTP status and RTT latency in ms."""
    t0 = time.time()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CrowdCastNetProbe/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = resp.getcode()
            rtt = round((time.time() - t0) * 1000, 1)
            return {"status": "ONLINE", "http_code": code, "latency_ms": rtt}
    except urllib.error.HTTPError as e:
        # HTTP 400, 403, 307 etc. mean TCP & TLS connected successfully
        rtt = round((time.time() - t0) * 1000, 1)
        return {"status": "ONLINE", "http_code": e.code, "latency_ms": rtt}
    except Exception as e:
        return {"status": "FAILED", "error": str(e), "latency_ms": None}


def probe_all_network() -> Dict[str, Any]:
    """Probes all endpoints and assesses overall connectivity for uploads."""
    results = {}
    total_latency = 0
    online_count = 0

    proxy_health = check_proxy_socket()
    results["proxy"] = proxy_health

    for key, meta in CLOUD_ENDPOINTS.items():
        res = probe_endpoint(meta["url"])
        res["name_fa"] = meta["name_fa"]
        res["name_en"] = meta["name_en"]
        res["url"] = meta["url"]
        results[key] = res
        if res["status"] == "ONLINE" and res["latency_ms"] is not None:
            online_count += 1
            total_latency += res["latency_ms"]

    avg_latency = round(total_latency / online_count, 1) if online_count > 0 else 0.0
    can_upload = (results.get("aws_api", {}).get("status") == "ONLINE" and
                  results.get("aws_s3", {}).get("status") == "ONLINE")

    return {
        "can_upload": can_upload,
        "avg_latency_ms": avg_latency,
        "online_endpoints": f"{online_count}/{len(CLOUD_ENDPOINTS)}",
        "proxy_status": proxy_health.get("status"),
        "endpoints": results,
        "probed_at": time.time(),
    }


def find_agent_status_notifier_dest() -> Optional[str]:
    """Finds the D-Bus destination for crowd-cast-agent's StatusNotifierItem."""
    try:
        cmd = ["pgrep", "-f", "(^|/)crowd-cast-agent( |$)"]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=1)
        if res.returncode != 0 or not res.stdout.strip():
            return None
        pid = int(res.stdout.strip().split()[0])
        return f"org.kde.StatusNotifierItem-{pid}-1"
    except Exception:
        return None


def get_native_dbus_menu_items() -> Tuple[Optional[str], Dict[int, str]]:
    """Inspects com.canonical.dbusmenu on crowd-cast-agent and returns {id: label}."""
    dest = find_agent_status_notifier_dest()
    if not dest:
        return None, {}

    cmd = [
        "gdbus", "call", "--session",
        "--dest", dest,
        "--object-path", "/MenuBar",
        "--method", "com.canonical.dbusmenu.GetLayout",
        "0", "3", "['label']"
    ]
    try:
        res = subprocess.run(cmd, env=ENV, capture_output=True, text=True, timeout=2)
        if res.returncode != 0:
            return dest, {}

        # Parse labels and IDs
        # Pattern: <(id, {'label': <'text'>}, @av [])>
        matches = re.findall(r"<\((\d+),\s*\{[^}]*'label':\s*<'([^']*)'>", res.stdout)
        items = {int(m[0]): m[1] for m in matches}
        return dest, items
    except Exception:
        return dest, {}


def trigger_native_upload_toggle(target_action: str) -> Dict[str, Any]:
    """Triggers native Pause Uploads or Resume Uploads via com.canonical.dbusmenu.Event."""
    dest, items = get_native_dbus_menu_items()
    if not dest or not items:
        return {"success": False, "error": "crowd-cast-agent StatusNotifierItem menu is not accessible on D-Bus"}

    # Find the upload toggle item
    upload_item_id = None
    current_label = None

    for item_id, label in items.items():
        if "Uploads" in label or "upload" in label.lower():
            upload_item_id = item_id
            current_label = label
            break

    if upload_item_id is None:
        return {"success": False, "error": f"Upload toggle menu item not found in items: {items}"}

    # Desired transition:
    # target_action == "resume": we want it to be uploading.
    #   If current_label == 'Resume Uploads', click it to resume!
    #   If current_label == 'Pause Uploads', it is already uploading!
    # target_action == "pause": we want it to be paused.
    #   If current_label == 'Pause Uploads', click it to pause!
    #   If current_label == 'Resume Uploads', it is already paused!

    already_in_state = False
    clicked = False

    if target_action == "resume":
        if current_label == "Resume Uploads":
            clicked = True
        elif current_label == "Pause Uploads":
            already_in_state = True
    elif target_action == "pause":
        if current_label == "Pause Uploads":
            clicked = True
        elif current_label == "Resume Uploads":
            already_in_state = True

    if clicked:
        ts = int(time.time())
        cmd = [
            "gdbus", "call", "--session",
            "--dest", dest,
            "--object-path", "/MenuBar",
            "--method", "com.canonical.dbusmenu.Event",
            str(upload_item_id), "clicked", "<int32 0>", str(ts)
        ]
        res = subprocess.run(cmd, env=ENV, capture_output=True, text=True, timeout=2)
        if res.returncode == 0:
            time.sleep(0.5)
            # Re-read layout to get updated label
            _, new_items = get_native_dbus_menu_items()
            new_label = new_items.get(upload_item_id, "unknown")
            return {
                "success": True,
                "action": target_action,
                "clicked_id": upload_item_id,
                "previous_label": current_label,
                "new_label": new_label,
                "message_fa": f"دستور بومی {target_action} با موفقیت به منوی crowd-cast ارسال شد.",
            }
        else:
            return {"success": False, "error": f"D-Bus Event call failed: {res.stderr}"}

    return {
        "success": True,
        "action": target_action,
        "already_in_state": True,
        "current_label": current_label,
        "message_fa": f"وضعیت آپلود قبلاً در حالت {target_action} قرار دارد.",
    }


def get_recent_upload_speed() -> Dict[str, Any]:
    """Calculates recent upload speed and chunk stats from crowd-cast.log."""
    log_files = sorted(LOGS_DIR.glob("crowd-cast.log.*"), key=lambda x: x.stat().st_mtime, reverse=True)
    if not log_files:
        return {"recent_speed_mbps": 0.0, "last_upload_time": None}

    latest_log = log_files[0]
    last_speed_mbps = 0.0
    last_chunk_name = None
    last_chunk_size_mb = 0.0
    last_chunk_time = None

    try:
        with open(latest_log, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()[-100:]

        # Look for upload chunk start and finish lines
        # Pattern:
        # 2026-11-10T02:09:41.839025Z  INFO crowd_cast_agent::upload::presigned: Uploading chunk cb52fb2c...
        # 2026-11-10T02:09:45.772772Z  INFO crowd_cast_agent::upload::presigned: Uploaded video for chunk cb52fb2c... (0.60 MB)
        start_time = None
        for line in lines:
            if "Uploading chunk" in line:
                m_start = re.search(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z).*Uploading chunk\s+([\w-]+)", line)
                if m_start:
                    try:
                        start_time = datetime.fromisoformat(m_start.group(1).replace("Z", "+00:00"))
                        last_chunk_name = m_start.group(2)
                    except Exception:
                        pass
            elif "Uploaded video for chunk" in line:
                m_end = re.search(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z).*Uploaded video for chunk\s+([\w-]+)\s+\(([\d.]+)\s+MB\)", line)
                if m_end and start_time:
                    try:
                        end_time = datetime.fromisoformat(m_end.group(1).replace("Z", "+00:00"))
                        size_mb = float(m_end.group(3))
                        dur = (end_time - start_time).total_seconds()
                        if dur > 0.1:
                            last_speed_mbps = round((size_mb * 8) / dur, 2)
                        last_chunk_size_mb = size_mb
                        last_chunk_time = end_time.isoformat()
                    except Exception:
                        pass
    except Exception:
        pass

    return {
        "recent_speed_mbps": last_speed_mbps,
        "recent_speed_kb_s": round(last_speed_mbps * 125, 1) if last_speed_mbps > 0 else 0.0,
        "last_chunk_name": last_chunk_name,
        "last_chunk_size_mb": last_chunk_size_mb,
        "last_chunk_time": last_chunk_time,
    }


def get_full_network_and_upload_telemetry() -> Dict[str, Any]:
    """Generates complete network health, speed, and native D-Bus menu status."""
    net_probe = probe_all_network()
    speed_info = get_recent_upload_speed()
    dest, menu_items = get_native_dbus_menu_items()

    native_upload_label = None
    for label in menu_items.values():
        if "Uploads" in label or "upload" in label.lower():
            native_upload_label = label
            break

    is_native_uploading = (native_upload_label == "Pause Uploads")

    payload = {
        "network": net_probe,
        "speed": speed_info,
        "native_dbus": {
            "dest": dest,
            "has_menu": bool(menu_items),
            "upload_menu_label": native_upload_label,
            "is_native_uploading": is_native_uploading,
        },
        "timestamp": time.time(),
    }

    try:
        with open(NET_STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except Exception:
        pass

    return payload


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ["resume", "pause"]:
        action = sys.argv[1]
        res = trigger_native_upload_toggle(action)
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        telemetry = get_full_network_and_upload_telemetry()
        print(json.dumps(telemetry, ensure_ascii=False, indent=2))
