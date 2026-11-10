#!/usr/bin/env python3
"""Incus VM CLI Client for CrowdCast Screen Sentinel."""

import json
import sys
import urllib.error
import urllib.request

API_URL = "http://127.0.0.1:8585/api"


def api_call(endpoint, method="GET", payload=None):
    url = f"{API_URL}/{endpoint}"
    data = json.dumps(payload).encode("utf-8") if payload else None
    headers = {"Content-Type": "application/json"} if payload else {}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        print(f"❌ Error connecting to Sentinel API ({url}): {e}")
        print("Ensure the dashboard service is running (systemctl status sentinel-bridge).")
        sys.exit(1)


def cmd_list():
    data = api_call("status")
    print(f"\n==========================================================================")
    print(f"🛡️  CrowdCast Screen Sentinel (Inside Incus: {data.get('vm_name')})")
    print(f"==========================================================================")
    status_str = f"🟢 RUNNING (PID: {data.get('agent_pid')})" if data.get('agent_running') else "🔴 STOPPED"
    print(f"Recorder Status : {status_str}")
    print(f"Total Windows   : {data.get('total_windows')} | Blackout Issues/Risk: {data.get('blackout_windows_count')}")
    print("-" * 80)
    fmt = "{:<10} {:<8} {:<24} {:<18} {:<20}"
    print(fmt.format("WIN_ID", "PID", "WM_CLASS", "FOCUS", "BLACKOUT STATUS"))
    print("-" * 80)
    for w in data.get("windows", []):
        f = "🎯 IN FOCUS" if w.get("is_focused") else "Background"
        st = w.get("blackout_status")
        if st == "ACTIVE_BLACKOUT":
            st_desc = "🔴 ACTIVE BLACKOUT"
        elif st == "BLACKOUT_RISK":
            st_desc = "🟡 RISK (Untracked)"
        else:
            st_desc = "🟢 MONITORED SAFE"
        print(fmt.format(str(w.get("window_id")), str(w.get("pid")), w.get("wm_class", "")[:23], f, st_desc))
    print("=" * 80 + "\n")


def cmd_fix(wm_class):
    print(f"Executing 1-Click Fix for '{wm_class}'...")
    res = api_call("windows/fix", method="POST", payload={"wm_class": wm_class})
    if res.get("success"):
        print(f"✅ {res.get('message_fa')}")
        print(f"   {res.get('message_en')}")
        for r in res.get("remediations", []):
            print(f"  - {r}")
    else:
        print(f"❌ Failed: {res.get('error')}")


def cmd_whitelist_all():
    print("Whitelisting all open windows...")
    res = api_call("windows/whitelist-all", method="POST", payload={})
    if res.get("success"):
        print(f"✅ {res.get('message_fa')}")
        print(f"   Added: {res.get('added_apps')}")
    else:
        print(f"❌ Failed: {res.get('error')}")


def cmd_status():
    data = api_call("status")
    cfg = data.get("config", {})
    print("\n=== CrowdCast Status & Safeguards ===")
    print(f"VM Target             : {data.get('vm_name')}")
    print(f"Agent Running         : {data.get('agent_running')} (PID: {data.get('agent_pid')})")
    print(f"capture_all           : {cfg.get('capture_all')} (Must be False on Wayland)")
    print(f"blank_on_untracked    : {cfg.get('blank_video_on_untracked_app')}")
    print(f"idle_timeout_secs     : {cfg.get('idle_timeout_secs')}s")
    print(f"target_apps           : {cfg.get('target_apps')}")
    if data.get("luma", {}).get("success"):
        luma = data["luma"]
        print(f"Luma Mean             : {luma.get('mean')} (Min {luma.get('min')}, Max {luma.get('max')})")
        print(f"Blackout Detected     : {'🚨 YES' if luma.get('is_black') else '🟢 NO'}")
    print("====================================\n")


def main():
    args = sys.argv[1:]
    if not args or args[0] == "list":
        cmd_list()
    elif args[0] == "fix" and len(args) > 1:
        cmd_fix(args[1])
    elif args[0] == "whitelist-all":
        cmd_whitelist_all()
    elif args[0] == "status":
        cmd_status()
    else:
        print("Usage: sentinel [list | fix <wm_class> | whitelist-all | status]")


if __name__ == "__main__":
    main()
