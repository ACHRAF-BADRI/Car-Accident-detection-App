"""Where the app reads its resources and writes the user's data.

Resources (models, images) ship with the app: next to the project when run from source, inside the
bundle when frozen into an .exe. User data (settings, snapshots, recordings, pending uploads) goes to
%APPDATA%\\AccidentAI, because an installed app cannot write in Program Files.
"""
import json
import os
import shutil
import sys

if getattr(sys, "frozen", False):  # PyInstaller build
    ROOT = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
else:
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the project folder


def asset(*parts):
    return os.path.join(ROOT, "assets", *parts)


USER_DATA = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "AccidentAI")
SETTINGS_FILE = os.path.join(USER_DATA, "settings.json")
PENDING_FILE = os.path.join(USER_DATA, "uploads_pending.json")
SCREENSHOT_DIR = os.path.join(USER_DATA, "Accidents_Screen")
RECORD_DIR = os.path.join(USER_DATA, "Recordings")
ENV_FILE = os.path.join(ROOT, ".env")

APP_ICON = asset("images", "app_icon.ico")
APP_LOGO = asset("images", "app_logo.png")


def migrate_legacy_data():
    """Before this layout, user data lived in the project folder: move it once to USER_DATA."""
    os.makedirs(USER_DATA, exist_ok=True)
    moved = {}  # old absolute path -> new one, to fix the pending uploads list
    for name in ("Accidents_Screen", "Recordings"):
        old_dir, new_dir = os.path.join(ROOT, name), os.path.join(USER_DATA, name)
        if not os.path.isdir(old_dir):
            continue
        for entry in os.listdir(old_dir):
            src, dst = os.path.join(old_dir, entry), os.path.join(new_dir, entry)
            if os.path.isdir(src) and not os.path.exists(dst):  # one folder per account
                os.makedirs(new_dir, exist_ok=True)
                shutil.move(src, dst)
                moved[os.path.abspath(src)] = dst
        if not os.listdir(old_dir):
            os.rmdir(old_dir)

    old_settings = os.path.join(ROOT, "settings.json")
    if os.path.exists(old_settings) and not os.path.exists(SETTINGS_FILE):
        with open(old_settings, encoding="utf-8") as f:
            settings = json.load(f)
        if settings.get("record_dir") in ("./Recordings", "Recordings"):
            settings["record_dir"] = RECORD_DIR  # the old default, relative to the project
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
        os.remove(old_settings)

    old_pending = os.path.join(ROOT, "uploads_pending.json")
    if os.path.exists(old_pending) and not os.path.exists(PENDING_FILE):
        with open(old_pending, encoding="utf-8") as f:
            items = json.load(f)
        for item in items:  # files that moved above must still be found by the uploader
            for old, new in moved.items():
                if item["path"].startswith(old):
                    item["path"] = new + item["path"][len(old):]
        with open(PENDING_FILE, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=1)
        os.remove(old_pending)
