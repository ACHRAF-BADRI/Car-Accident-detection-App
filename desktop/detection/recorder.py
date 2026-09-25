import os
import time
from datetime import datetime

import cv2

DURATION_UNITS = {"minutes": 60, "hours": 3600, "days": 86400}


class VideoRecorder:
    """Writes frames to MP4 files, starting a new file every `segment_seconds`.

    Detection runs slower than the camera, so the playback speed is measured on the
    first frames instead of trusting the camera's nominal FPS (otherwise the video
    would play in fast-forward).
    """

    def __init__(self, folder, segment_seconds=3600, calibration_frames=15, on_segment_closed=None):
        """on_segment_closed(path, started_at, duration_seconds) is called when a file is complete."""
        self.folder = folder
        self.on_segment_closed = on_segment_closed
        self.path = None
        self.frames_in_segment = 0
        self.segment_seconds = segment_seconds
        self.calibration_frames = calibration_frames
        self.fps = None
        self.writer = None
        self.segment_start = 0.0
        self.buffer = []  # (timestamp, frame) collected until the FPS is known
        os.makedirs(folder, exist_ok=True)

    def write(self, frame):
        """Record a frame. Returns the path of a newly opened file, else None."""
        now = time.time()
        if self.fps is None:
            self.buffer.append((now, frame.copy()))
            if len(self.buffer) < self.calibration_frames:
                return None
            return self._flush_buffer()

        new_file = None
        if self.writer is None or now - self.segment_start >= self.segment_seconds:
            new_file = self._open_segment(frame, now)
        self.writer.write(frame)
        self.frames_in_segment += 1
        return new_file

    def close(self):
        """Finish the current file (and anything still buffered)."""
        new_file = self._flush_buffer() if self.buffer else None
        self._finish_segment()
        return new_file

    def _flush_buffer(self):
        first, last = self.buffer[0][0], self.buffer[-1][0]
        measured = (len(self.buffer) - 1) / (last - first) if last > first else 10.0
        self.fps = min(max(measured, 1.0), 60.0)
        new_file = self._open_segment(self.buffer[0][1], first)
        for _, frame in self.buffer:
            self.writer.write(frame)
        self.frames_in_segment += len(self.buffer)
        self.buffer = []
        return new_file

    def _finish_segment(self):
        if self.writer is None:
            return
        self.writer.release()
        self.writer = None
        if self.on_segment_closed and self.frames_in_segment:
            self.on_segment_closed(self.path, datetime.fromtimestamp(self.segment_start).astimezone(),
                                   self.frames_in_segment / self.fps)

    def _open_segment(self, frame, started_at):
        self._finish_segment()
        height, width = frame.shape[:2]
        name = datetime.fromtimestamp(started_at).strftime("rec_%Y%m%d_%H%M%S.mp4")
        self.path = os.path.join(self.folder, name)
        self.writer = cv2.VideoWriter(self.path, cv2.VideoWriter_fourcc(*"mp4v"), self.fps, (width, height))
        self.segment_start = started_at
        self.frames_in_segment = 0
        return self.path


def duration_limit(settings):
    """Recording limit in seconds from the settings, or None for no limit."""
    if settings["record_unlimited"]:
        return None
    return max(int(settings["record_duration"]), 1) * DURATION_UNITS[settings["record_unit"]]


def format_elapsed(seconds):
    seconds = int(seconds)
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    clock = f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{days}d {clock}" if days else clock
