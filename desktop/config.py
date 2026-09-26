"""Build-time settings of the desktop app."""
import sys

APP_NAME = "AccidentAI"
APP_VERSION = "1.0.0"

# Online API used by the installed app. When run from source, API_URL in .env (e.g. a local server) wins.
PUBLIC_API_URL = "https://accidentai-api.onrender.com"

FROZEN = getattr(sys, "frozen", False)  # True inside the PyInstaller build
