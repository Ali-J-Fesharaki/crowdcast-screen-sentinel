"""Core Sentinel logic: Blackout detection, status evaluation, and 1-click remediation."""

import logging
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from app.config import APP_METADATA, KNOWN_WM_CLASS_ALIASES
from app.incus_bridge import IncusBridge
from app.luma_sampler import LumaSampler

logger = logging.getLogger(__name__)


def update_toml_target_apps(toml_text: str, new_apps: List[str]) -> str:
    """Updates target_apps in TOML string cleanly preserving other sections."""
    unique_apps = sorted(list(set(new_apps)))
    formatted = ",\n".join(f'  "{app}"' for app in unique_apps)
    replacement = f"target_apps = [\n{formatted}\n]"
    if re.search(r"target_apps\s*=\s*\[[^\]]*\]", toml_text):
        return re.sub(r"target_apps\s*=\s*\[[^\]]*\]", replacement, toml_text, count=1)
    # If not present in capture section, insert it
    return re.sub(r"(\[capture\]\s*)", rf"\g<1>{replacement}\n", toml_text, count=1)


def update_toml_bool(toml_text: str, key: str, val: bool) -> str:
    """Updates a boolean key in TOML string."""
    val_str = "true" if val else "false"
    if re.search(rf"({key}\s*=\s*)(true|false)", toml_text):
        return re.sub(rf"({key}\s*=\s*)(true|false)", rf"\g<1>{val_str}", toml_text)
    # Insert under [capture] if not present
    return re.sub(r"(\[capture\]\s*)", rf"\g<1>{key} = {val_str}\n", toml_text, count=1)


def update_toml_int(toml_text: str, key: str, val: int) -> str:
    """Updates an integer key in TOML string."""
    if re.search(rf"({key}\s*=\s*)(\d+)", toml_text):
        return re.sub(rf"({key}\s*=\s*)(\d+)", rf"\g<1>{val}", toml_text)
    return re.sub(r"(\[capture\]\s*)", rf"\g<1>{key} = {val}\n", toml_text, count=1)


class SentinelManager:
    def __init__(self, bridge: IncusBridge):
        self.bridge = bridge
        self.luma_sampler = LumaSampler(bridge)
        self._lock = threading.Lock()
        self.cached_state = self._build_empty_state()
        self._worker_thread = threading.Thread(target=self._telemetry_worker, daemon=True)
        self._worker_thread.start()

    def _build_empty_state(self) -> Dict[str, Any]:
        return {
            "vm_name": self.bridge.vm_name,
            "agent_running": False,
            "agent_pid": None,
            "agent_logs": [],
            "has_active_blackout": False,
            "blackout_windows_count": 0,
            "total_windows": 0,
            "windows": [],
            "focused_window": None,
            "config": {
                "target_apps": [],
                "capture_all": False,
                "blank_video_on_untracked_app": False,
                "idle_timeout_secs": 600,
            },
            "luma": {"success": False, "mean": 0.0, "is_black": True},
            "upload_schedule": {},
        }

    def _telemetry_worker(self):
        """Dedicated background thread continuously updating state cache every 1.5s."""
        logger.info("Sentinel background telemetry worker thread started.")
        while True:
            try:
                state = self._fetch_live_state()
                with self._lock:
                    self.cached_state = state
            except Exception as e:
                logger.error(f"Error in telemetry worker loop: {e}")
            time.sleep(1.5)

    def get_full_state(self, force: bool = False) -> Dict[str, Any]:
        """Returns cached state instantly (<1ms). If force=True, evaluates live."""
        if not force:
            with self._lock:
                if self.cached_state and self.cached_state.get("windows"):
                    return self.cached_state
        return self._fetch_live_state()

    def _fetch_live_state(self) -> Dict[str, Any]:
        """Gathers complete real-time state using fast unified single-shot probe."""
        probe = self.bridge.probe_guest_all()
        if probe:
            config = probe.get("config", {})
            capture_cfg = config.get("capture", {})
            target_apps = capture_cfg.get("target_apps", [])
            capture_all = capture_cfg.get("capture_all", False)
            blank_on_untracked = capture_cfg.get("blank_video_on_untracked_app", False)
            idle_timeout = capture_cfg.get("idle_timeout_secs", 600)

            open_windows = probe.get("windows", [])
            focused = probe.get("focused_window")
            agent_running = probe.get("agent_running", False)
            agent_pid = probe.get("agent_pid")
            agent_logs = probe.get("recent_logs", [])
            upload_schedule = probe.get("upload_schedule", {})
            network_health = probe.get("network_health", {})
        else:
            # Fallback to granular calls
            config = self.bridge.read_config()
            capture_cfg = config.get("capture", {})
            target_apps = capture_cfg.get("target_apps", [])
            capture_all = capture_cfg.get("capture_all", False)
            blank_on_untracked = capture_cfg.get("blank_video_on_untracked_app", False)
            idle_timeout = capture_cfg.get("idle_timeout_secs", 600)

            agent_status = self.bridge.get_agent_status()
            open_windows = self.bridge.get_open_windows()
            focused = self.bridge.get_focused_window()
            agent_running = agent_status.get("running", False)
            agent_pid = agent_status.get("pid")
            agent_logs = agent_status.get("recent_logs", [])
            upload_schedule = self.bridge.get_upload_schedule_status()
            network_health = self.bridge.get_network_health()

        focused_wid = focused.get("window_id") if focused else None
        focused_class = focused.get("wm_class") if focused else None

        evaluated_windows = []
        has_active_blackout = False
        blackout_count = 0

        for w in open_windows:
            wm_class = w.get("wm_class", "")
            wid = w.get("window_id")
            title = w.get("title", "")
            is_focused = (wid == focused_wid) or (wm_class == focused_class)

            aliases = KNOWN_WM_CLASS_ALIASES.get(wm_class, [wm_class])
            is_monitored = any(app in target_apps for app in aliases)

            if capture_all:
                status = "ACTIVE_BLACKOUT"
                reason_fa = "خطای بحرانی: حالت capture_all در ویلند باعث ضبط صفحه کاملاً سیاه می‌شود!"
                reason_en = "Critical: capture_all causes Wayland portal denial and 100% black recording."
                has_active_blackout = True
                blackout_count += 1
            elif is_focused and not is_monitored:
                status = "ACTIVE_BLACKOUT"
                reason_fa = "صفحه هم‌اکنون در حال ضبط سیاه است! این برنامه در لیست نظارت مجاز نیست."
                reason_en = "Currently recording black frames! Application is focused but not in target_apps."
                has_active_blackout = True
                blackout_count += 1
            elif not is_monitored:
                status = "BLACKOUT_RISK"
                reason_fa = "خطر صفحه سیاه: با سوییچ روی این پنجره، ضبط ویدیویی سیاه خواهد شد."
                reason_en = "Blackout risk: switching to this window will record black frames."
                blackout_count += 1
            else:
                status = "SAFE"
                reason_fa = "در حال نظارت و ایمن: ضبط با وضوح و بدون سیاهی انجام می‌شود."
                reason_en = "Monitored and safe: recording proceeds normally."

            meta = APP_METADATA.get(wm_class, {})
            evaluated_windows.append({
                "window_id": wid,
                "pid": w.get("pid"),
                "wm_class": wm_class,
                "title": title,
                "display_name": meta.get("name", wm_class),
                "icon": meta.get("icon", "window"),
                "category": meta.get("category", "Application"),
                "is_focused": is_focused,
                "is_monitored": is_monitored,
                "blackout_status": status,
                "blackout_reason_fa": reason_fa,
                "blackout_reason_en": reason_en,
                "can_one_click_fix": (status in ["ACTIVE_BLACKOUT", "BLACKOUT_RISK"]),
            })

        luma_info = self.luma_sampler.sample_latest_frame()

        return {
            "vm_name": self.bridge.vm_name,
            "agent_running": agent_running,
            "agent_pid": agent_pid,
            "agent_logs": agent_logs,
            "has_active_blackout": has_active_blackout,
            "blackout_windows_count": blackout_count,
            "total_windows": len(evaluated_windows),
            "windows": evaluated_windows,
            "focused_window": focused,
            "config": {
                "target_apps": target_apps,
                "capture_all": capture_all,
                "blank_video_on_untracked_app": blank_on_untracked,
                "idle_timeout_secs": idle_timeout,
            },
            "luma": luma_info,
            "upload_schedule": upload_schedule,
            "network_health": network_health,
            "last_updated_at": time.time(),
        }

    def add_to_monitoring(self, wm_class: str) -> Dict[str, Any]:
        """Adds a window class (and required aliases) to target_apps."""
        raw_cfg = self.bridge.read_config_raw()
        if not raw_cfg:
            return {"success": False, "error": "Unable to read guest config.toml"}

        config = self.bridge.read_config()
        current_apps = list(config.get("capture", {}).get("target_apps", []))

        aliases = KNOWN_WM_CLASS_ALIASES.get(wm_class, [wm_class])
        to_add = [a for a in aliases if a not in current_apps]
        new_apps = current_apps + to_add

        # Synchronize user whitelist override
        current_whitelist = self.bridge.read_user_whitelist()
        self.bridge.write_user_whitelist(current_whitelist + to_add)

        updated_cfg = update_toml_target_apps(raw_cfg, new_apps)
        if not self.bridge.write_config_raw(updated_cfg):
            return {"success": False, "error": "Failed to write updated config into VM"}

        # Restart agent to apply immediately
        self.bridge.restart_agent()

        return {
            "success": True,
            "added_aliases": to_add,
            "target_apps": new_apps,
            "message_fa": f"برنامه {wm_class} با موفقیت به لیست نظارت اضافه شد.",
            "message_en": f"Application {wm_class} successfully added to monitoring.",
        }

    def remove_from_monitoring(self, wm_class: str) -> Dict[str, Any]:
        """Removes a window class (and its aliases) from target_apps."""
        raw_cfg = self.bridge.read_config_raw()
        if not raw_cfg:
            return {"success": False, "error": "Unable to read guest config.toml"}

        config = self.bridge.read_config()
        current_apps = list(config.get("capture", {}).get("target_apps", []))

        aliases = set(KNOWN_WM_CLASS_ALIASES.get(wm_class, [wm_class]))
        new_apps = [app for app in current_apps if app not in aliases and app != wm_class]

        # Update user whitelist
        current_whitelist = self.bridge.read_user_whitelist()
        updated_whitelist = [app for app in current_whitelist if app not in aliases and app != wm_class]
        self.bridge.write_user_whitelist(updated_whitelist)

        updated_cfg = update_toml_target_apps(raw_cfg, new_apps)
        if not self.bridge.write_config_raw(updated_cfg):
            return {"success": False, "error": "Failed to write updated config into VM"}

        self.bridge.restart_agent()

        return {
            "success": True,
            "removed": list(aliases),
            "target_apps": new_apps,
            "message_fa": f"برنامه {wm_class} از نظارت خارج شد.",
            "message_en": f"Application {wm_class} removed from monitoring.",
        }

    def whitelist_all_open(self) -> Dict[str, Any]:
        """Adds all currently open windows to target_apps in one click."""
        raw_cfg = self.bridge.read_config_raw()
        if not raw_cfg:
            return {"success": False, "error": "Unable to read guest config.toml"}

        config = self.bridge.read_config()
        current_apps = set(config.get("capture", {}).get("target_apps", []))

        open_windows = self.bridge.get_open_windows()
        added = []
        for w in open_windows:
            wm_class = w.get("wm_class", "")
            aliases = KNOWN_WM_CLASS_ALIASES.get(wm_class, [wm_class])
            for a in aliases:
                if a not in current_apps:
                    current_apps.add(a)
                    added.append(a)

        # Synchronize user whitelist
        current_whitelist = set(self.bridge.read_user_whitelist())
        current_whitelist.update(current_apps)
        self.bridge.write_user_whitelist(list(current_whitelist))

        updated_cfg = update_toml_target_apps(raw_cfg, list(current_apps))
        updated_cfg = update_toml_bool(updated_cfg, "capture_all", False)
        updated_cfg = update_toml_bool(updated_cfg, "blank_video_on_untracked_app", False)

        if not self.bridge.write_config_raw(updated_cfg):
            return {"success": False, "error": "Failed to write updated config"}

        self.bridge.restart_agent()

        return {
            "success": True,
            "added_count": len(added),
            "added_apps": added,
            "message_fa": f"تمام {len(added)} برنامه باز به لیست نظارت اضافه شدند و تنظیمات ایمن شد.",
            "message_en": f"Added {len(added)} open applications to monitoring and secured config.",
        }

    def fix_blackout(self, wm_class: str) -> Dict[str, Any]:
        """Executes the full 1-Click Black Screen Fix for the specified window class.
        
        Remediations performed:
        1. Adds wm_class and all required aliases into target_apps
        2. Sets capture_all = false (Wayland portal fix)
        3. Sets blank_video_on_untracked_app = false (prevents black frames on background clicks)
        4. Ensures idle_timeout_secs >= 600 (prevents idle timeout blackout)
        5. Saves configuration inside the VM
        6. Restarts crowd-cast-agent cleanly
        7. Focuses the target window via gtk-launch so Mutter/PipeWire binds the live texture
        8. Returns full diagnostic result
        """
        raw_cfg = self.bridge.read_config_raw()
        if not raw_cfg:
            return {"success": False, "error": "Unable to read guest config.toml"}

        config = self.bridge.read_config()
        current_apps = list(config.get("capture", {}).get("target_apps", []))

        aliases = KNOWN_WM_CLASS_ALIASES.get(wm_class, [wm_class])
        to_add = [a for a in aliases if a not in current_apps]
        new_apps = current_apps + to_add

        # Synchronize user whitelist override
        current_whitelist = set(self.bridge.read_user_whitelist())
        current_whitelist.update(to_add)
        self.bridge.write_user_whitelist(list(current_whitelist))

        # Apply all defensive safeguards
        content = update_toml_target_apps(raw_cfg, new_apps)
        content = update_toml_bool(content, "capture_all", False)
        content = update_toml_bool(content, "blank_video_on_untracked_app", False)
        content = update_toml_int(content, "idle_timeout_secs", 600)

        if not self.bridge.write_config_raw(content):
            return {"success": False, "error": "Failed to write fixed configuration to VM"}

        # Restart crowdcast daemon to load new whitelisted targets
        restart_ok, restart_msg = self.bridge.restart_agent()

        # Focus window
        focus_ok = self.bridge.focus_window(wm_class)

        return {
            "success": True,
            "wm_class": wm_class,
            "added_aliases": to_add,
            "remediations": [
                f"افزودن {aliases} به target_apps",
                "غیرفعال‌سازی capture_all برای رفع خطای مجوز پورتال ویلند",
                "تنظیم blank_video_on_untracked_app = false جهت جلوگیری از سیاه شدن تصویر",
                "افزایش زمان تایم‌اوت بیکاری به ۶۰۰ ثانیه (idle_timeout_secs = 600)",
                "راه‌اندازی مجدد سرویس ضبط (crowdcast-ctl restart)",
                f"فوکوس خودکار روی پنجره ({wm_class}) جهت ارسال بافر ویدیو به پایپ‌وایر",
            ],
            "message_fa": f"مشکل صفحه سیاه برای {wm_class} با موفقیت در یک کلیک حل شد!",
            "message_en": f"Black screen issue for {wm_class} resolved in 1 click!",
            "restart_ok": restart_ok,
            "focus_ok": focus_ok,
        }

    def update_settings(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Updates global configuration settings safely."""
        raw_cfg = self.bridge.read_config_raw()
        if not raw_cfg:
            return {"success": False, "error": "Unable to read guest config.toml"}

        content = raw_cfg
        if "blank_video_on_untracked_app" in settings:
            content = update_toml_bool(
                content, "blank_video_on_untracked_app", bool(settings["blank_video_on_untracked_app"])
            )
        if "capture_all" in settings:
            content = update_toml_bool(content, "capture_all", bool(settings["capture_all"]))
        if "idle_timeout_secs" in settings:
            content = update_toml_int(content, "idle_timeout_secs", int(settings["idle_timeout_secs"]))

        if not self.bridge.write_config_raw(content):
            return {"success": False, "error": "Failed to update configuration"}

        self.bridge.restart_agent()
        return {"success": True, "message": "Settings updated successfully."}
