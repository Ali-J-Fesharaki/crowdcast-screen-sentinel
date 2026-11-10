"""Configuration and constants for CrowdCast Screen Sentinel."""

import os
from pathlib import Path

# Base paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = PROJECT_ROOT / "web"
SCRATCH_DIR = Path(os.environ.get("TMPDIR", "/tmp")) / "crowdcast_sentinel"
SCRATCH_DIR.mkdir(parents=True, exist_ok=True)

# Incus and VM targets
DEFAULT_VM_NAME = os.environ.get("CROWDCAST_VM_NAME", "crowd-vm")
GUEST_USER = os.environ.get("CROWDCAST_GUEST_USER", "ubuntu")
GUEST_CONFIG_PATH = "/home/ubuntu/.config/agent/config.toml"
GUEST_RECORDINGS_DIR = "/tmp/crowd-cast-recordings"
GUEST_LOG_PATH = "/home/ubuntu/.local/state/crowdcast-ctl/agent.log"

# Server configuration
SERVER_HOST = os.environ.get("SENTINEL_HOST", "0.0.0.0")
SERVER_PORT = int(os.environ.get("SENTINEL_PORT", "8585"))

# Application aliases mapping
# Maps raw wm_class or binary aliases to required target_apps entries
KNOWN_WM_CLASS_ALIASES = {
    "com.microsoft.VSCode": ["com.microsoft.VSCode", "code"],
    "code": ["com.microsoft.VSCode", "code"],
    "gnome-terminal-server": ["gnome-terminal-server", "org.gnome.Terminal"],
    "org.gnome.Terminal": ["gnome-terminal-server", "org.gnome.Terminal"],
    "gnome-terminal": ["gnome-terminal-server", "org.gnome.Terminal"],
    "firefox": ["firefox"],
    "org.gnome.Nautilus": ["org.gnome.Nautilus", "nautilus"],
    "nautilus": ["org.gnome.Nautilus", "nautilus"],
    "com.anthropic.Claude": ["com.anthropic.Claude", "claude"],
    "claude": ["com.anthropic.Claude", "claude"],
    "OpenResearch": ["OpenResearch"],
    "org.gnome.TextEditor": ["org.gnome.TextEditor"],
    "google-chrome": ["google-chrome"],
    "chromium": ["chromium"],
}

# Human friendly application names and icons
APP_METADATA = {
    "com.microsoft.VSCode": {"name": "Visual Studio Code", "icon": "code", "category": "Editor"},
    "code": {"name": "Visual Studio Code", "icon": "code", "category": "Editor"},
    "gnome-terminal-server": {"name": "GNOME Terminal", "icon": "terminal", "category": "Terminal"},
    "org.gnome.Terminal": {"name": "GNOME Terminal", "icon": "terminal", "category": "Terminal"},
    "firefox": {"name": "Mozilla Firefox", "icon": "globe", "category": "Browser"},
    "org.gnome.Nautilus": {"name": "Files (Nautilus)", "icon": "folder", "category": "File Manager"},
    "com.anthropic.Claude": {"name": "Claude Desktop", "icon": "bot", "category": "AI Assistant"},
    "OpenResearch": {"name": "OpenResearch", "icon": "book-open", "category": "Research"},
    "org.gnome.TextEditor": {"name": "Text Editor", "icon": "file-text", "category": "Editor"},
}
