#!/usr/bin/env python3
"""CrowdCast Screen Sentinel CLI & Entrypoint."""

import argparse
import sys
from pathlib import Path

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.config import DEFAULT_VM_NAME, SERVER_HOST, SERVER_PORT
from app.incus_bridge import IncusBridge
from app.sentinel_core import SentinelManager
from app.server import run_server


def cmd_serve(args):
    print(f"Starting CrowdCast Screen Sentinel Web Dashboard on {args.host}:{args.port}...")
    run_server(host=args.host, port=args.port)


def cmd_list(args):
    bridge = IncusBridge(args.vm)
    sentinel = SentinelManager(bridge)
    state = sentinel.get_full_state()

    print(f"\n==========================================================================")
    print(f"🛡️  CrowdCast Screen Sentinel — Open Windows in '{state['vm_name']}'")
    print(f"==========================================================================")
    print(f"Agent Status : {'🟢 RUNNING (PID: ' + str(state['agent_pid']) + ')' if state['agent_running'] else '🔴 STOPPED'}")
    print(f"Total Windows: {state['total_windows']} | Blackout Issues/Risk: {state['blackout_windows_count']}")
    print(f"--------------------------------------------------------------------------")
    fmt = "{:<10} {:<8} {:<24} {:<18} {:<20}"
    print(fmt.format("WIN_ID", "PID", "WM_CLASS", "FOCUS", "BLACKOUT STATUS"))
    print("-" * 84)

    for w in state["windows"]:
        focus_mark = "🎯 IN FOCUS" if w["is_focused"] else "Background"
        status_mark = w["blackout_status"]
        if status_mark == "ACTIVE_BLACKOUT":
            status_desc = "🔴 ACTIVE BLACKOUT"
        elif status_mark == "BLACKOUT_RISK":
            status_desc = "🟡 RISK (Untracked)"
        else:
            status_desc = "🟢 MONITORED SAFE"

        print(fmt.format(
            str(w["window_id"]),
            str(w["pid"]),
            w["wm_class"][:23],
            focus_mark,
            status_desc,
        ))
    print(f"==========================================================================\n")


def cmd_fix(args):
    bridge = IncusBridge(args.vm)
    sentinel = SentinelManager(bridge)
    print(f"Executing 1-Click Black Screen Fix for: '{args.wm_class}'...")
    res = sentinel.fix_blackout(args.wm_class)
    if res.get("success"):
        print(f"✅ Success! {res['message_en']}")
        print(f"   Persian: {res['message_fa']}")
        print("   Actions applied:")
        for r in res.get("remediations", []):
            print(f"    - {r}")
    else:
        print(f"❌ Failed: {res.get('error')}")
        sys.exit(1)


def cmd_add(args):
    bridge = IncusBridge(args.vm)
    sentinel = SentinelManager(bridge)
    res = sentinel.add_to_monitoring(args.wm_class)
    if res.get("success"):
        print(f"✅ {res['message_en']}")
    else:
        print(f"❌ {res.get('error')}")
        sys.exit(1)


def cmd_remove(args):
    bridge = IncusBridge(args.vm)
    sentinel = SentinelManager(bridge)
    res = sentinel.remove_from_monitoring(args.wm_class)
    if res.get("success"):
        print(f"✅ {res['message_en']}")
    else:
        print(f"❌ {res.get('error')}")
        sys.exit(1)


def cmd_whitelist_all(args):
    bridge = IncusBridge(args.vm)
    sentinel = SentinelManager(bridge)
    res = sentinel.whitelist_all_open()
    if res.get("success"):
        print(f"✅ {res['message_en']}")
        print(f"   Added apps: {res.get('added_apps')}")
    else:
        print(f"❌ {res.get('error')}")
        sys.exit(1)


def cmd_status(args):
    bridge = IncusBridge(args.vm)
    sentinel = SentinelManager(bridge)
    state = sentinel.get_full_state()
    cfg = state["config"]

    print("\n=== CrowdCast Recording Status ===")
    print(f"VM Target               : {state['vm_name']}")
    print(f"Agent Running           : {state['agent_running']} (PID: {state['agent_pid']})")
    print(f"Capture All (Dangerous) : {cfg.get('capture_all')}")
    print(f"Blank on Untracked      : {cfg.get('blank_video_on_untracked_app')}")
    print(f"Idle Timeout            : {cfg.get('idle_timeout_secs')}s")
    print(f"Target Apps Whitelist   : {cfg.get('target_apps')}")
    if state.get("luma", {}).get("success"):
        luma = state["luma"]
        print(f"Latest Video Luma       : Mean {luma['mean']:.2f} (Min {luma['min']}, Max {luma['max']})")
        print(f"Blackout Detected       : {'🚨 YES' if luma['is_black'] else '🟢 NO'}")
    if state.get("upload_schedule"):
        sched = state["upload_schedule"]
        print(f"Tehran Time             : {sched.get('tehran_time')}")
        print(f"Upload Status           : {sched.get('status_fa')} ({sched.get('status_en')})")
        print(f"Upload Progress         : {sched.get('progress_percent', 0)}% (Pending: {sched.get('pending_segments', 0)})")
    print("==================================\n")


def cmd_upload(args):
    bridge = IncusBridge(args.vm)
    if args.action == "start":
        ok, msg = bridge.start_manual_upload()
        if ok:
            print("🚀 فرایند آپلود دستی با موفقیت آغاز شد (Manual upload started).")
        else:
            print(f"❌ Failed: {msg}")
    elif args.action == "pause":
        ok, msg = bridge.pause_manual_upload()
        if ok:
            print("⏸️ آپلود متوقف شد و به زمان‌بندی تهران بازگشت (Upload paused).")
        else:
            print(f"❌ Failed: {msg}")
    elif args.action == "status":
        sched = bridge.get_upload_schedule_status()
        print("\n=== Tehran Upload Status & Progress ===")
        print(f"Tehran Time      : {sched.get('tehran_time')}")
        print(f"Status           : {sched.get('status_fa')} ({sched.get('status_en')})")
        print(f"Progress         : {sched.get('progress_percent', 0)}%")
        print(f"Pending Segments : {sched.get('pending_segments', 0)}")
        print(f"Next Event       : {sched.get('next_event_fa')}")
        print(f"Active Chunk     : {sched.get('active_chunk') or 'None'}")
        print("=======================================\n")


def cmd_luma(args):
    bridge = IncusBridge(args.vm)
    sentinel = SentinelManager(bridge)
    luma = sentinel.luma_sampler.sample_latest_frame(force=True)
    print("\n=== Luma Sampling Result ===")
    print(f"Success    : {luma.get('success')}")
    if luma.get("success"):
        print(f"Source     : {luma.get('video_source')}")
        print(f"Min Luma   : {luma.get('min')}")
        print(f"Max Luma   : {luma.get('max')}")
        print(f"Mean Luma  : {luma.get('mean')}")
        print(f"Is Black   : {luma.get('is_black')}")
        print(f"Frame Path : {luma.get('frame_path')}")
    else:
        print(f"Error      : {luma.get('error')}")
    print("============================\n")


def main():
    parser = argparse.ArgumentParser(
        description="CrowdCast Screen Sentinel: Monitor and resolve black screen recordings in Incus VMs"
    )
    parser.add_argument("--vm", default=DEFAULT_VM_NAME, help="Incus VM name (default: crowd-vm)")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # serve
    p_serve = subparsers.add_parser("serve", help="Run the Web Dashboard HTTP server")
    p_serve.add_argument("--host", default=SERVER_HOST, help="Host to bind (default: 0.0.0.0)")
    p_serve.add_argument("-p", "--port", type=int, default=SERVER_PORT, help="Port to bind (default: 8585)")
    p_serve.set_defaults(func=cmd_serve)

    # list
    p_list = subparsers.add_parser("list", help="List all open windows and their blackout status")
    p_list.set_defaults(func=cmd_list)

    # fix
    p_fix = subparsers.add_parser("fix", help="Execute 1-Click Black Screen Fix for a window class")
    p_fix.add_argument("wm_class", help="Window class (e.g. org.gnome.Nautilus, com.microsoft.VSCode)")
    p_fix.set_defaults(func=cmd_fix)

    # add
    p_add = subparsers.add_parser("add", help="Add window class to monitoring target_apps")
    p_add.add_argument("wm_class", help="Window class to whitelist")
    p_add.set_defaults(func=cmd_add)

    # remove
    p_remove = subparsers.add_parser("remove", help="Remove window class from monitoring")
    p_remove.add_argument("wm_class", help="Window class to remove")
    p_remove.set_defaults(func=cmd_remove)

    # whitelist-all
    p_wall = subparsers.add_parser("whitelist-all", help="Add all currently open windows to target_apps")
    p_wall.set_defaults(func=cmd_whitelist_all)

    # status
    p_status = subparsers.add_parser("status", help="Show crowd-cast agent and config status")
    p_status.set_defaults(func=cmd_status)

    # luma
    p_luma = subparsers.add_parser("luma", help="Sample latest frame and check brightness")
    p_luma.set_defaults(func=cmd_luma)

    # upload
    p_upload = subparsers.add_parser("upload", help="Control manual upload and view progress")
    p_upload.add_argument("action", choices=["start", "pause", "status"], help="Upload action: start | pause | status")
    p_upload.set_defaults(func=cmd_upload)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
