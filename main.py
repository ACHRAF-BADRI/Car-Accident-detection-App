"""Entry point: show the loading screen at once, import the heavy modules behind it, then open the app."""
import sys
import threading

from desktop.paths import migrate_legacy_data
from desktop.splash import Splash


def main():
    try:  # own taskbar identity + sharp rendering on high-DPI screens (Windows)
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AccidentDetection.App")
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        pass

    migrate_legacy_data()  # user data used to live in the project folder
    splash = Splash()
    loaded = {}

    def load():
        try:
            from desktop import app  # TensorFlow, OpenCV, CustomTkinter...: the slow part
            loaded["app"] = app
        except Exception as e:  # shown after the splash closes
            loaded["error"] = e

    threading.Thread(target=load, daemon=True).start()
    splash.run_until(lambda: loaded)

    if "error" in loaded:
        raise loaded["error"]
    loaded["app"].launch_application()


if __name__ == "__main__":
    if "--self-test" in sys.argv:  # check the (installed) app without a window, see desktop/selftest.py
        from desktop.selftest import run
        sys.exit(run())
    main()
