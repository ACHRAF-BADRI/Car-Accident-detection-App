"""Uploads accident images and finished video files to the API in the background.

Pending uploads are kept in uploads_pending.json, so a file that could not be sent
(no network, app closed mid-upload) is retried at the owner's next login.
"""
import json
import os
import queue
import threading
import time
from datetime import datetime

from desktop.cloud.api_client import ApiError
from desktop.i18n import t
from desktop.paths import PENDING_FILE
RETRY_DELAYS = (5, 30, 120)  # seconds between attempts before leaving it for the next login
_file_lock = threading.Lock()


def _read_pending():
    try:
        with open(PENDING_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def _write_pending(items):
    tmp = PENDING_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=1)
    os.replace(tmp, PENDING_FILE)


class CloudUploader:
    def __init__(self, api, username):
        self.api = api
        self.username = username
        self.items = queue.Queue()
        self.messages = queue.Queue()  # texts for the event log, read by the UI thread
        self.stopped = threading.Event()
        for item in _read_pending():
            if item["username"] == username:
                self.items.put(item)
        threading.Thread(target=self._work, daemon=True).start()

    def add(self, path, kind, captured_at=None, probability=None, duration=None):
        item = {"path": os.path.abspath(path), "kind": kind, "username": self.username,
                "captured_at": (captured_at or datetime.now().astimezone()).isoformat(),
                "probability": probability, "duration": duration}
        with _file_lock:
            _write_pending(_read_pending() + [item])
        self.items.put(item)

    def stop(self):
        """Stop after the current file (logout); what is left stays pending for next time."""
        self.stopped.set()

    def pending_count(self):
        return self.items.qsize()

    def _forget(self, item):
        with _file_lock:
            _write_pending([i for i in _read_pending() if i != item])

    def _work(self):
        while not self.stopped.is_set():
            try:
                item = self.items.get(timeout=0.5)
            except queue.Empty:
                continue
            name = os.path.basename(item["path"])
            if not os.path.exists(item["path"]):
                self._forget(item)  # deleted locally before it could be sent
                continue
            for attempt, delay in enumerate((0,) + RETRY_DELAYS):
                if self.stopped.wait(delay):
                    return
                try:
                    self.api.upload(item["path"], item["kind"],
                                    captured_at=datetime.fromisoformat(item["captured_at"]),
                                    probability=item["probability"], duration=item["duration"])
                    self._forget(item)
                    self.messages.put(t("log.upload_done", file=name))
                    break
                except (ApiError, OSError) as e:
                    if isinstance(e, ApiError) and e.status in (400, 401, 403):
                        self.messages.put(t("log.upload_failed", file=name, error=getattr(e, "code", e)))
                        break  # will not get better by retrying now; kept for next login
                    if attempt == len(RETRY_DELAYS):
                        self.messages.put(t("log.upload_later", file=name))
