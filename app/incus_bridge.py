"""Incus Bridge: Executes host-to-guest operations, D-Bus window inspection, and config updates."""

import ast
import json
import logging
import re
import subprocess
import tomllib
from typing import Any, Dict, List, Optional, Tuple

from app.config import (
    DEFAULT_VM_NAME,
    GUEST_CONFIG_PATH,
    GUEST_LOG_PATH,
    GUEST_USER,
)

logger = logging.getLogger(__name__)


class IncusBridge:
    def __init__(self, vm_name: str = DEFAULT_VM_NAME):
        self.vm_name = vm_name

    def run_incus_cmd(self, cmd_args: List[str], timeout: int = 25) -> Tuple[int, str, str]:
        """Runs an incus command elevated via sg incus-admin."""
        full_cmd = ["sg", "incus-admin", "-c", " ".join(f"'{arg}'" if " " in arg else arg for arg in cmd_args)]
        try:
            res = subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return res.returncode, res.stdout.strip(), res.stderr.strip()
        except subprocess.TimeoutExpired:
            return 124, "", f"Command timed out after {timeout}s: {' '.join(cmd_args)}"
        except Exception as e:
            return 1, "", str(e)

    def exec_guest(self, bash_script: str, as_user: str = GUEST_USER, timeout: int = 30) -> Tuple[int, str, str]:
        """Executes a bash script inside the guest VM as the designated user."""
        wrapped = (
            f"export WAYLAND_DISPLAY=wayland-0 XDG_RUNTIME_DIR=/run/user/1000 "
            f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus XDG_SESSION_TYPE=wayland; "
            f"{bash_script}"
        )
        cmd = [
            "incus",
            "exec",
            self.vm_name,
            "--",
            "su",
            "-l",
            as_user,
            "-c",
            wrapped,
        ]
        return self.run_incus_cmd(cmd, timeout=timeout)

    def get_instances(self) -> List[Dict[str, Any]]:
        """Returns all incus instances with status."""
        code, stdout, _ = self.run_incus_cmd(["incus", "list", "--format=json"])
        if code != 0 or not stdout:
            return []
        try:
            data = json.loads(stdout)
            result = []
            for item in data:
                result.append({
                    "name": item.get("name"),
                    "status": item.get("status"),
                    "type": item.get("type"),
                    "ipv4": [
                        addr.get("address")
                        for net in item.get("state", {}).get("network", {}).values()
                        for addr in net.get("addresses", [])
                        if addr.get("family") == "inet"
                    ]
                })
            return result
        except Exception as e:
            logger.error(f"Failed to parse incus list: {e}")
            return []

    def get_open_windows(self) -> List[Dict[str, Any]]:
        """Queries org.crowdcast.FocusProvider.ListWindows over D-Bus inside the VM."""
        cmd = "gdbus call --session --dest org.crowdcast.FocusProvider --object-path /org/crowdcast/FocusProvider --method org.crowdcast.FocusProvider.ListWindows"
        code, stdout, stderr = self.exec_guest(cmd)
        if code != 0:
            logger.warning(f"ListWindows D-Bus call returned {code}: {stderr}")
            return []

        try:
            # Clean gdbus syntax (strip uint64) to valid python expression
            cleaned = re.sub(r'uint64\s+', '', stdout)
            data = ast.literal_eval(cleaned)
            raw_list = data[0] if data and isinstance(data, tuple) else []
            windows = []
            for item in raw_list:
                if len(item) >= 4:
                    windows.append({
                        "window_id": int(item[0]),
                        "pid": int(item[1]),
                        "wm_class": str(item[2]),
                        "title": str(item[3]),
                    })
            return windows
        except Exception as e:
            logger.error(f"Failed to parse ListWindows output: {e} | Raw: {stdout}")
            return []

    def get_focused_window(self) -> Optional[Dict[str, Any]]:
        """Queries org.crowdcast.FocusProvider.GetFocused over D-Bus inside the VM."""
        cmd = "gdbus call --session --dest org.crowdcast.FocusProvider --object-path /org/crowdcast/FocusProvider --method org.crowdcast.FocusProvider.GetFocused"
        code, stdout, stderr = self.exec_guest(cmd)
        if code != 0:
            return None

        try:
            cleaned = re.sub(r'uint64\s+', '', stdout)
            data = ast.literal_eval(cleaned)
            if data and len(data) >= 4:
                return {
                    "window_id": int(data[0]),
                    "pid": int(data[1]),
                    "wm_class": str(data[2]),
                    "title": str(data[3]),
                }
            return None
        except Exception as e:
            logger.error(f"Failed to parse GetFocused output: {e} | Raw: {stdout}")
            return None

    def focus_window(self, wm_class: str) -> bool:
        """Attempts to raise and focus the window in GNOME Wayland."""
        # Common desktop file mapping
        desktop_map = {
            "com.microsoft.VSCode": "com.microsoft.VSCode",
            "code": "code",
            "firefox": "firefox",
            "gnome-terminal-server": "org.gnome.Terminal",
            "org.gnome.Terminal": "org.gnome.Terminal",
            "org.gnome.Nautilus": "org.gnome.Nautilus",
            "com.anthropic.Claude": "com.anthropic.Claude",
            "OpenResearch": "openresearch",
        }
        desktop_id = desktop_map.get(wm_class, wm_class)
        cmd = f"gtk-launch {desktop_id} || true"
        code, _, _ = self.exec_guest(cmd)
        return code == 0

    def read_config_raw(self) -> str:
        """Reads raw config.toml content from the guest VM."""
        cmd = ["incus", "exec", self.vm_name, "--", "cat", GUEST_CONFIG_PATH]
        code, stdout, _ = self.run_incus_cmd(cmd)
        if code != 0:
            return ""
        return stdout

    def read_config(self) -> Dict[str, Any]:
        """Parses guest config.toml into a Python dict."""
        raw = self.read_config_raw()
        if not raw:
            return {}
        try:
            return tomllib.loads(raw)
        except Exception as e:
            logger.error(f"Failed to parse TOML config: {e}")
            return {}

    def write_config_raw(self, content: str) -> bool:
        """Writes raw config.toml back into the guest VM."""
        cmd = [
            "sg", "incus-admin", "-c",
            f"incus exec {self.vm_name} -- su -l {GUEST_USER} -c 'cat > {GUEST_CONFIG_PATH}'"
        ]
        try:
            p = subprocess.Popen(cmd, stdin=subprocess.PIPE, text=True)
            p.communicate(input=content, timeout=10)
            return p.returncode == 0
        except Exception as e:
            logger.error(f"Failed to write guest config: {e}")
            return False

    def read_user_whitelist(self) -> List[str]:
        """Reads user whitelist overrides from the guest VM."""
        cmd = ["incus", "exec", self.vm_name, "--", "cat", "/home/ubuntu/.config/agent/user_whitelist.json"]
        code, stdout, _ = self.run_incus_cmd(cmd)
        if code != 0 or not stdout:
            return []
        try:
            return json.loads(stdout)
        except Exception:
            return []

    def write_user_whitelist(self, apps: List[str]) -> bool:
        """Writes user whitelist overrides into the guest VM."""
        unique_apps = sorted(list(set(apps)))
        content = json.dumps(unique_apps, indent=2)
        cmd = [
            "sg", "incus-admin", "-c",
            f"incus exec {self.vm_name} -- su -l {GUEST_USER} -c 'cat > /home/ubuntu/.config/agent/user_whitelist.json'"
        ]
        try:
            p = subprocess.Popen(cmd, stdin=subprocess.PIPE, text=True)
            p.communicate(input=content, timeout=5)
            return p.returncode == 0
        except Exception as e:
            logger.error(f"Failed to write user whitelist: {e}")
            return False

    def get_upload_schedule_status(self) -> Dict[str, Any]:
        """Reads real-time Tehran upload schedule status from the VM."""
        cmd = ["incus", "exec", self.vm_name, "--", "cat", "/home/ubuntu/.local/state/crowdcast-ctl/tehran_upload_status.json"]
        code, stdout, _ = self.run_incus_cmd(cmd)
        if code != 0 or not stdout:
            return {}
        try:
            return json.loads(stdout)
        except Exception:
            return {}

    def start_manual_upload(self) -> Tuple[bool, str]:
        """Forces manual upload start regardless of schedule."""
        cmd = "touch /home/ubuntu/.local/state/crowdcast-ctl/manual_upload.flag && echo -n 'false' > /home/ubuntu/.local/share/agent/uploads_paused"
        code, stdout, stderr = self.exec_guest(cmd)
        return code == 0, stdout or stderr

    def pause_manual_upload(self) -> Tuple[bool, str]:
        """Pauses manual upload and returns to strict schedule."""
        cmd = "rm -f /home/ubuntu/.local/state/crowdcast-ctl/manual_upload.flag && echo -n 'true' > /home/ubuntu/.local/share/agent/uploads_paused"
        code, stdout, stderr = self.exec_guest(cmd)
        return code == 0, stdout or stderr

    def get_agent_status(self) -> Dict[str, Any]:
        """Checks if crowd-cast-agent is running and inspects recent logs."""
        cmd = "~/.local/bin/crowdcast-ctl status"
        code, stdout, _ = self.exec_guest(cmd)
        is_running = "RUNNING" in stdout

        pid = None
        for line in stdout.splitlines():
            parts = line.strip().split()
            if len(parts) >= 2 and parts[0].isdigit() and "crowd-cast-agent" in parts[1]:
                pid = int(parts[0])
                break

        # Read last 15 log lines
        log_cmd = f"tail -n 15 {GUEST_LOG_PATH} 2>/dev/null || true"
        _, log_out, _ = self.exec_guest(log_cmd)

        return {
            "running": is_running,
            "pid": pid,
            "raw_status": stdout,
            "recent_logs": log_out.splitlines(),
        }

    def restart_agent(self) -> Tuple[bool, str]:
        """Restarts crowd-cast-agent via crowdcast-ctl."""
        cmd = "~/.local/bin/crowdcast-ctl restart"
        code, stdout, stderr = self.exec_guest(cmd, timeout=25)
        success = "Started" in stdout or code == 0
        return success, stdout or stderr
