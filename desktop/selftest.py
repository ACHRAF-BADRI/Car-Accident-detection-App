"""`AccidentAI.exe --self-test`: checks the installed app without opening a window.

Loads YOLO + the accident classifier, analyses a real traffic frame and pings the online API.
The report is written to %TEMP%\\AccidentAI-selftest.json (a windowed .exe has no console) and the
exit code is 0 when everything works.
"""
import json
import os
import sys
import tempfile
import time
import traceback

REPORT = os.path.join(tempfile.gettempdir(), "AccidentAI-selftest.json")


def run():
    report = {"ok": False, "frozen": getattr(sys, "frozen", False), "checks": {}}
    t0 = time.time()
    try:
        import cv2
        from desktop.config import APP_VERSION
        from desktop.paths import ROOT, asset
        report.update(version=APP_VERSION, root=ROOT)

        from desktop.detection.detector import AccidentDetector
        detector = AccidentDetector()
        report["checks"]["models_loaded"] = {"ok": True, "classifier": os.path.basename(detector.model.source),
                                             "seconds": round(time.time() - t0, 1)}

        frame = cv2.imread(asset("images", "selftest_frame.jpg"))
        _, info = detector.process_frame(frame, save_screenshots=False)
        report["checks"]["detection"] = {"ok": info["vehicles"] > 0, "vehicles": info["vehicles"],
                                         "accident_probability": info["probability"]}

        from desktop.cloud.api_client import ApiClient
        api = ApiClient()
        up = any(api.is_up() or time.sleep(3) for _ in range(30))  # up to ~90 s if Render is asleep
        report["checks"]["server"] = {"ok": up, "url": api.base_url}

        report["ok"] = all(c["ok"] for c in report["checks"].values())
    except Exception:
        report["error"] = traceback.format_exc()
    report["seconds"] = round(time.time() - t0, 1)
    with open(REPORT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1
