import os
import sys
import json
import time
import queue
import threading
import subprocess
from datetime import datetime
from urllib.parse import urlparse

import cv2
import customtkinter as ctk
from PIL import Image
from tkinter import filedialog

from admin_page import AdminPage
from profile_page import ProfilePage
from api_client import ApiClient, ApiError
from detection_service import SCREENSHOT_DIR
from i18n import LANGUAGES, t, set_language
from recorder import DEFAULT_RECORD_DIR, DURATION_UNITS, VideoRecorder, duration_limit, format_elapsed
from uploader import CloudUploader
from widgets import (ACCENT, APP_ICON, APP_LOGO, DANGER, DANGER_HOVER, MUTED, SUCCESS, TEXT, WARNING, WARNING_DARK,
                     BackgroundTasks, ConfirmDialog, StatCard, VideoPlayer, add_reveal_button, delete_all_button,
                     fit_size, load_image, media_item, role_badge)

SETTINGS_FILE = "./settings.json"
DEFAULT_SETTINGS = {
    "threshold": 86,
    "save_screenshots": True,
    "cooldown": 0,
    "camera_index": 0,
    "appearance": "Dark",
    "language": "en",
    "record_webcam": False,
    "record_dir": DEFAULT_RECORD_DIR,
    "record_unlimited": True,
    "record_duration": 1,
    "record_unit": "hours",
    "remember_username": False,
    "last_username": "",
}

APPEARANCE_MODES = ["Light", "Dark", "System"]


def load_settings():
    settings = dict(DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_FILE, "r") as f:
            settings.update(json.load(f))
    except (OSError, ValueError):
        pass
    return settings


def save_settings(settings):
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings, f, indent=2)
    except OSError:
        pass


def list_cameras():
    """Names of the DirectShow video devices, in the same order as OpenCV's CAP_DSHOW indices."""
    try:
        from pygrabber.dshow_graph import FilterGraph
        return FilterGraph().get_input_devices()
    except Exception:
        return [f"Camera {i}" for i in range(4)]


def list_recordings(folder):
    if not os.path.isdir(folder):
        return []
    files = [f for f in os.listdir(folder) if f.lower().endswith((".mp4", ".avi", ".mkv"))]
    return [os.path.join(folder, f) for f in sorted(files, reverse=True)]


def list_screenshots(folder):
    if not os.path.isdir(folder):
        return []
    files = [f for f in os.listdir(folder) if f.lower().endswith((".png", ".jpg", ".jpeg"))]
    return [os.path.join(folder, f) for f in sorted(files, reverse=True)]


def appearance_selector(master, app):
    labels = {mode: t(f"appearance.{mode}") for mode in APPEARANCE_MODES}
    modes = {label: mode for mode, label in labels.items()}
    selector = ctk.CTkSegmentedButton(master, values=list(labels.values()),
                                      command=lambda label: app.set_appearance(modes[label]))
    selector.set(labels[app.settings["appearance"]])
    return selector


def language_selector(master, app):
    codes = {label: code for code, label in LANGUAGES.items()}
    selector = ctk.CTkSegmentedButton(master, values=list(codes), command=lambda label: app.set_language(codes[label]))
    selector.set(LANGUAGES[app.settings["language"]])
    return selector


# ---------------------------------------------------------------- Login / sign up

class LoginFrame(ctk.CTkFrame):
    def __init__(self, master, on_success):
        super().__init__(master, fg_color="transparent")
        self.app = master
        self.on_success = on_success
        self.tasks = BackgroundTasks(self)
        self.register_mode = False

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.place(relx=1.0, x=-20, y=20, anchor="ne")
        language_selector(top, master).pack(side="left", padx=(0, 10))
        appearance_selector(top, master).pack(side="left")

        card = ctk.CTkFrame(self, corner_radius=16, width=380)
        card.place(relx=0.5, rely=0.5, anchor="center")

        logo = Image.open(APP_LOGO)
        ctk.CTkLabel(card, text="", image=ctk.CTkImage(logo, logo, size=(84, 84))).pack(pady=(28, 10))
        ctk.CTkLabel(card, text=t("app.title"), font=ctk.CTkFont(size=24, weight="bold")).pack(padx=40)
        self.subtitle = ctk.CTkLabel(card, text=t("login.subtitle"), text_color=MUTED)
        self.subtitle.pack(pady=(0, 18))

        self.username = ctk.CTkEntry(card, placeholder_text=t("login.username"), width=280, height=38)
        self.username.pack(pady=6)
        self.password = ctk.CTkEntry(card, placeholder_text=t("login.password"), show="•", width=280, height=38)
        self.password.pack(pady=6)
        self.confirm = ctk.CTkEntry(card, placeholder_text=t("login.confirm_password"), show="•", width=280, height=38)
        add_reveal_button(self.password)
        add_reveal_button(self.confirm)

        # Only the username is remembered (settings.json), never the password
        row = ctk.CTkFrame(card, fg_color="transparent", width=280, height=28)  # same width as the fields
        row.pack(pady=(6, 0))
        row.pack_propagate(False)
        self.remember = ctk.CTkSwitch(row, text=t("login.remember"), font=ctk.CTkFont(size=12))
        if master.settings["remember_username"]:
            self.remember.select()
            self.username.insert(0, master.settings["last_username"])
        self.remember.pack(side="left")

        self.error = ctk.CTkLabel(card, text="", text_color=DANGER, wraplength=280)
        self.error.pack()

        self.submit_btn = ctk.CTkButton(card, text=t("login.submit"), width=280, height=40, command=self.submit,
                                        font=ctk.CTkFont(size=14, weight="bold"))
        self.submit_btn.pack(pady=(4, 6))
        self.switch_btn = ctk.CTkButton(card, text=t("login.to_register"), width=280, fg_color="transparent",
                                        text_color=(ACCENT, "#5ea8e8"), hover_color=("gray85", "gray25"),
                                        command=self.toggle_mode)
        self.switch_btn.pack(pady=(0, 10))
        self.server_label = ctk.CTkLabel(card, text="", font=ctk.CTkFont(size=12))
        self.server_label.pack(pady=(0, 18))

        self.username.bind("<Return>", lambda e: self.password.focus())
        self.password.bind("<Return>", lambda e: self.confirm.focus() if self.register_mode else self.submit())
        self.confirm.bind("<Return>", lambda e: self.submit())
        # Name already filled in: go straight to the password
        self.after(100, self.password.focus if self.username.get() else self.username.focus)
        self.watch_server()

    def watch_server(self):
        state = self.app.server_state
        text, color = {"checking": (t("server.checking"), WARNING), "up": (t("server.up"), SUCCESS),
                       "down": (t("server.down"), DANGER)}[state]
        self.server_label.configure(text=f"● {text}", text_color=color)
        self.after(400, self.watch_server)

    def toggle_mode(self):
        self.register_mode = not self.register_mode
        self.error.configure(text="")
        if self.register_mode:
            self.confirm.pack(pady=6, after=self.password)
            self.subtitle.configure(text=t("login.register_subtitle"))
            self.submit_btn.configure(text=t("login.register"))
            self.switch_btn.configure(text=t("login.to_login"))
        else:
            self.confirm.pack_forget()
            self.subtitle.configure(text=t("login.subtitle"))
            self.submit_btn.configure(text=t("login.submit"))
            self.switch_btn.configure(text=t("login.to_register"))

    def submit(self):
        username, password = self.username.get().strip(), self.password.get()
        if not username or not password:
            self.error.configure(text=t("api.missing_fields"))
            return
        if self.register_mode and password != self.confirm.get():
            self.error.configure(text=t("api.password_mismatch"))
            return
        api = self.app.api
        call = api.register if self.register_mode else api.login
        self.submit_btn.configure(state="disabled", text=t("login.please_wait"))
        self.error.configure(text="")
        self.tasks.run(lambda: call(username, password), self.done)

    def done(self, user, error):
        self.submit_btn.configure(state="normal", text=t("login.register" if self.register_mode else "login.submit"))
        if error:
            code = error.code if isinstance(error, ApiError) else "error"
            message = t(f"api.{code}")
            self.error.configure(text=message if message != f"api.{code}" else t("api.error"))
            self.password.delete(0, "end")
            self.confirm.delete(0, "end")
            return
        remember = bool(self.remember.get())
        self.app.settings["remember_username"] = remember
        self.app.settings["last_username"] = user["username"] if remember else ""
        save_settings(self.app.settings)
        self.on_success(user)


# ---------------------------------------------------------------- Detection page

class DetectionPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.worker = None
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.frames = queue.Queue(maxsize=1)
        self.events = queue.Queue()  # log messages from the worker; never dropped, unlike frames
        self.alerts = 0
        self.user_stopped = False

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # Toolbar
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        ctk.CTkLabel(bar, text=t("nav.detection"), font=ctk.CTkFont(size=24, weight="bold")).pack(side="left")
        self.rec_label = ctk.CTkLabel(bar, text="", text_color=DANGER, font=ctk.CTkFont(size=14, weight="bold"))
        self.rec_label.pack(side="left", padx=16)
        self.stop_btn = ctk.CTkButton(bar, text=t("detection.stop"), width=100, fg_color=DANGER, hover_color=DANGER_HOVER,
                                      command=self.confirm_stop, state="disabled")
        self.stop_btn.pack(side="right")
        self.pause_btn = ctk.CTkButton(bar, text=t("detection.pause"), width=120, fg_color=WARNING,
                                       hover_color=WARNING_DARK, command=self.toggle_pause, state="disabled")
        self.pause_btn.pack(side="right", padx=(0, 8))
        self.cam_btn = ctk.CTkButton(bar, text=t("detection.webcam"), width=120, command=self.start_webcam)
        self.cam_btn.pack(side="right", padx=8)
        self.file_btn = ctk.CTkButton(bar, text=t("detection.open_video"), width=150, command=self.start_file)
        self.file_btn.pack(side="right")

        # Stats
        stats = ctk.CTkFrame(self, fg_color="transparent")
        stats.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        for i in range(4):
            stats.grid_columnconfigure(i, weight=1, uniform="stats")
        self.status_card = StatCard(stats, t("detection.status"), t("detection.idle"))
        self.vehicles_card = StatCard(stats, t("detection.vehicles"))
        self.prob_card = StatCard(stats, t("detection.probability"))
        self.alerts_card = StatCard(stats, t("detection.alerts"), "0")
        for i, card in enumerate([self.status_card, self.vehicles_card, self.prob_card, self.alerts_card]):
            card.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 6, 0 if i == 3 else 6))

        # Video + log
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=2, column=0, sticky="nsew")
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(0, weight=1)

        self.video = ctk.CTkLabel(body, text=t("detection.placeholder"),
                                  text_color=MUTED, corner_radius=12, fg_color=("gray85", "gray14"))
        self.video.grid(row=0, column=0, sticky="nsew")

        log_box = ctk.CTkFrame(body, width=260, corner_radius=12)
        log_box.grid(row=0, column=1, sticky="ns", padx=(12, 0))
        log_box.grid_propagate(False)
        log_box.grid_rowconfigure(1, weight=1)
        log_box.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(log_box, text=t("detection.event_log"), font=ctk.CTkFont(size=14, weight="bold")).grid(row=0, column=0, sticky="w", padx=12, pady=(10, 4))
        self.log = ctk.CTkTextbox(log_box, font=ctk.CTkFont(size=12), state="disabled", wrap="word")
        self.log.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))

        self.log_event(t("log.loading_models"))

    # -- helpers
    def log_event(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", f"[{datetime.now():%H:%M:%S}] {text}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def set_running(self, running, pausable=False):
        state = "disabled" if running else "normal"
        self.file_btn.configure(state=state)
        self.cam_btn.configure(state=state)
        self.stop_btn.configure(state="normal" if running else "disabled")
        # Pause / resume only makes sense for a video file, a webcam is live
        self.pause_btn.configure(state="normal" if running and pausable else "disabled", text=t("detection.pause"))

    def toggle_pause(self):
        if self.pause_event.is_set():
            self.pause_event.clear()
            self.pause_btn.configure(text=t("detection.pause"))
            self.status_card.set(t("detection.running"), SUCCESS)
            self.log_event(t("log.resumed"))
        else:
            self.pause_event.set()
            self.pause_btn.configure(text=t("detection.resume"))
            self.status_card.set(t("detection.paused"), WARNING)
            self.log_event(t("log.paused"))

    # -- actions
    def start_file(self):
        path = filedialog.askopenfilename(title=t("detection.select_video"),
                                          filetypes=[(t("detection.video_files"), "*.mp4 *.avi *.mkv *.webm *.mov"),
                                                     (t("detection.all_files"), "*.*")])
        if path:
            self.start(path, os.path.basename(path))

    def start_webcam(self):
        if not list_cameras():
            # No webcam plugged in: send the user to Settings and point at the camera option
            self.log_event(t("log.no_camera"))
            self.app.main.show("settings")
            settings = self.app.main.pages["settings"]
            settings.refresh_cameras()
            settings.blink_camera()
            return
        self.start(int(self.app.settings["camera_index"]), "webcam")

    def start(self, source, name):
        if self.app.detector is None:
            self.log_event(t("log.models_wait"))
            return
        self.stop_event.clear()
        self.pause_event.clear()
        self.set_running(True, pausable=not isinstance(source, int))
        self.user_stopped = False
        self.reset_stats()  # fresh stats for every new video / webcam session
        self.status_card.set(t("detection.running"), SUCCESS)
        self.log_event(t("log.started", name=name))
        self.worker = threading.Thread(target=self.run, args=(source,), daemon=True)
        self.worker.start()
        self.poll()

    def stop(self):
        self.stop_event.set()

    def confirm_stop(self):
        ConfirmDialog(self, t("confirm.stop_title"), t("confirm.stop_message"), t("confirm.stop"), self.user_stop)

    def user_stop(self):
        # The screen and the stats are cleared once the worker has really stopped (see poll)
        self.user_stopped = True
        self.stop()

    def reset_stats(self):
        self.alerts = 0
        self.alerts_card.set("0")
        self.vehicles_card.set("—")
        self.prob_card.set("—")
        self.rec_label.configure(text="")
        self.status_card.set(t("detection.idle"))

    def clear_video(self):
        # CTkLabel cannot drop an image once set, so put a fresh placeholder in its place
        body = self.video.master
        self.video.destroy()
        self.video = ctk.CTkLabel(body, text=t("detection.placeholder"),
                                  text_color=MUTED, corner_radius=12, fg_color=("gray85", "gray14"))
        self.video.grid(row=0, column=0, sticky="nsew")

    def run(self, source):
        # Webcams go through DirectShow so the index matches the names listed in Settings
        video = cv2.VideoCapture(source, cv2.CAP_DSHOW) if isinstance(source, int) else cv2.VideoCapture(source)
        if not video.isOpened():
            self.frames.put(("error", t("log.open_failed")))
            return
        recorder, limit, rec_start = self.start_recording(source)
        # A file must play at its real speed even though detection is slower than its frame rate:
        # skip the frames we fell behind on and only analyse the current one (a webcam is live already)
        is_file = not isinstance(source, int)
        video_fps = video.get(cv2.CAP_PROP_FPS) or 25.0
        started = last = time.time()
        frame_index = 0
        while not self.stop_event.is_set():
            if self.pause_event.is_set():
                paused_at = time.time()
                while self.pause_event.is_set() and not self.stop_event.is_set():
                    time.sleep(0.05)
                # Resume where we paused instead of jumping ahead by the paused time
                started += time.time() - paused_at
                last = time.time()
                continue
            if is_file:
                target = int((time.time() - started) * video_fps)
                while frame_index < target and video.grab():
                    frame_index += 1
            ret, frame = video.read()
            if not ret:
                break
            frame_index += 1
            s = self.app.settings
            frame, info = self.app.detector.process_frame(
                frame, threshold=float(s["threshold"]), save_screenshots=s["save_screenshots"], cooldown=float(s["cooldown"]),
                screenshot_dir=self.app.user_dir(SCREENSHOT_DIR))
            if info["screenshot"]:
                self.app.uploader.add(info["screenshot"], "image", probability=info["probability"])
            now = time.time()
            info["fps"] = 1.0 / max(now - last, 1e-6)
            last = now
            info["recording"] = None
            if recorder is not None:
                new_file = recorder.write(frame)
                if new_file:
                    self.events.put(t("log.record_file", file=os.path.basename(new_file)))
                info["recording"] = now - rec_start
                if limit is not None and now - rec_start >= limit:
                    self.events.put(t("log.record_limit", duration=format_elapsed(limit)))
                    break
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            self.send("frame", (Image.fromarray(rgb), info))
        video.release()
        if recorder is not None:
            new_file = recorder.close()
            if new_file:
                self.events.put(t("log.record_file", file=os.path.basename(new_file)))
            self.events.put(t("log.record_saved"))
        self.send("done", None)

    def start_recording(self, source):
        """Returns (recorder, limit in seconds or None, start time) for a webcam session, else Nones."""
        s = self.app.settings
        if not isinstance(source, int) or not s["record_webcam"]:
            return None, None, None
        folder = self.app.user_dir(s["record_dir"])
        # Every finished file (one per hour, or the last one at stop) goes to the cloud
        upload = lambda path, started, duration: self.app.uploader.add(path, "video", captured_at=started, duration=duration)
        try:
            recorder = VideoRecorder(folder, on_segment_closed=upload)
        except OSError as e:
            self.events.put(t("log.record_failed", error=e))
            return None, None, None
        limit = duration_limit(s)
        duration = format_elapsed(limit) if limit else t("settings.record_no_limit")
        self.events.put(t("log.record_started", folder=os.path.abspath(folder), duration=duration))
        return recorder, limit, time.time()

    def send(self, kind, payload):
        # Only the latest frame matters: drop the one the UI has not shown yet
        try:
            self.frames.get_nowait()
        except queue.Empty:
            pass
        self.frames.put((kind, payload))

    def poll(self):
        while not self.events.empty():
            self.log_event(self.events.get_nowait())
        try:
            kind, payload = self.frames.get_nowait()
        except queue.Empty:
            self.after(15, self.poll)
            return

        if kind == "frame":
            self.show_frame(*payload)
            self.after(15, self.poll)
        else:
            if kind == "error":
                self.log_event(payload)
            self.log_event(t("log.stopped"))
            self.rec_label.configure(text="")
            self.status_card.set(t("detection.idle"))
            self.set_running(False)
            if self.user_stopped:
                self.clear_video()
                self.reset_stats()

    def show_frame(self, image, info):
        box_w, box_h = max(self.video.winfo_width(), 1), max(self.video.winfo_height(), 1)
        scale = min(box_w / image.width, box_h / image.height)
        size = (max(int(image.width * scale), 1), max(int(image.height * scale), 1))
        photo = ctk.CTkImage(image, image, size=size)
        self.video.configure(image=photo, text="")
        self.video.image = photo

        self.vehicles_card.set(str(info["vehicles"]))
        if info["recording"] is not None:
            self.rec_label.configure(text=f"● REC  {format_elapsed(info['recording'])}")
        if info["accident"]:
            self.status_card.set(t("detection.accident"), DANGER)
            self.prob_card.set(f"{info['probability']:.1f}%", DANGER)
        else:
            self.prob_card.set(f"{info['probability']:.1f}%")
            if not self.pause_event.is_set():  # a frame still in flight must not hide "Paused"
                self.status_card.set(t("detection.running_fps", fps=info["fps"]), SUCCESS)
        if info["screenshot"]:
            self.alerts += 1
            self.alerts_card.set(str(self.alerts), DANGER)
            self.log_event(t("log.accident", prob=info["probability"], file=os.path.basename(info["screenshot"])))


# ---------------------------------------------------------------- Gallery page

class LocalMediaPage(ctk.CTkFrame):
    """Shared by the image and recording pages: toolbar, per-item and "delete all" deletion.
    Deleting removes the file from this PC and its uploaded copy from the cloud."""

    kind = "image"
    title_key = count_key = empty_key = ""

    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.tasks = BackgroundTasks(self)
        self.thumbs = []
        self.paths = []

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        ctk.CTkLabel(bar, text=t(self.title_key), font=ctk.CTkFont(size=24, weight="bold")).pack(side="left")
        self.count = ctk.CTkLabel(bar, text="", text_color=MUTED)
        self.count.pack(side="left", padx=12)
        self.status = ctk.CTkLabel(bar, text="")
        self.status.pack(side="left")
        ctk.CTkButton(bar, text=t("gallery.open_folder"), width=130, fg_color="transparent", border_width=1,
                      text_color=TEXT, command=self.open_folder).pack(side="right")
        ctk.CTkButton(bar, text=t("gallery.refresh"), width=110, command=self.refresh).pack(side="right", padx=8)
        self.delete_all_btn = delete_all_button(bar, self.confirm_delete_all)
        self.delete_all_btn.pack(side="right")

        self.list = ctk.CTkScrollableFrame(self, width=self.THUMB[0] + 30, corner_radius=12)
        self.list.grid(row=1, column=0, sticky="ns")

    def open_folder(self):
        os.makedirs(self.folder(), exist_ok=True)
        os.startfile(os.path.abspath(self.folder()))

    def fill(self, paths):
        """Rebuild the list; returns False when there is nothing to show."""
        for w in self.list.winfo_children():
            w.destroy()
        self.thumbs, self.paths = [], paths
        self.count.configure(text=t(self.count_key, count=len(paths)))
        self.delete_all_btn.configure(state="normal" if paths else "disabled")
        if not paths:
            ctk.CTkLabel(self.list, text=t(self.empty_key), text_color=MUTED).pack(pady=20)
            return False
        for path in paths:
            thumb, text = self.describe(path)
            self.thumbs.append(thumb)
            media_item(self.list, text, lambda p=path: self.open(p), lambda p=path: self.confirm_delete(p), image=thumb)
        return True

    # -- deletion
    def confirm_delete(self, path):
        ConfirmDialog(self, t(f"confirm.delete_{self.kind}_title"), t(f"confirm.delete_{self.kind}"),
                      t("media.delete"), lambda: self.delete([path]))

    def confirm_delete_all(self):
        ConfirmDialog(self, t(f"confirm.delete_all_{self.kind}_title"),
                      t(f"confirm.delete_all_{self.kind}", count=len(self.paths)), t("media.delete_all"),
                      lambda: self.delete(list(self.paths)))

    def delete(self, paths):
        self.release_files()
        kind, api = self.kind, self.app.api

        def work():
            removed, failed = [], 0
            for path in paths:
                try:
                    os.remove(path)
                    removed.append(os.path.basename(path))
                except FileNotFoundError:
                    removed.append(os.path.basename(path))
                except OSError:
                    failed += 1  # e.g. the video currently being recorded
            cloud_ok = True
            if removed:
                try:
                    api.delete_many(kind=kind, filenames=removed)
                except ApiError:
                    cloud_ok = False
            return len(removed), failed, cloud_ok

        self.tasks.run(work, self.deleted)

    def deleted(self, result, error):
        self.refresh()
        if error:
            self.status.configure(text=str(error), text_color=DANGER)
            return
        removed, failed, cloud_ok = result
        parts = [t("media.deleted", count=removed)]
        if failed:
            parts.append(t("media.delete_failed", count=failed))
        if not cloud_ok:
            parts.append(t("media.cloud_failed"))
        self.status.configure(text="  ·  ".join(parts), text_color=DANGER if failed or not cloud_ok else SUCCESS)
        self.after(6000, lambda: self.status.winfo_exists() and self.status.configure(text=""))

    def release_files(self):
        """Close anything that keeps a file open (Windows refuses to delete an open file)."""


class GalleryPage(LocalMediaPage):
    THUMB = (200, 130)
    kind = "image"
    title_key, count_key, empty_key = "nav.gallery", "gallery.count", "gallery.empty"

    def __init__(self, master, app):
        super().__init__(master, app)
        self.current = None
        preview = ctk.CTkFrame(self, corner_radius=12)
        preview.grid(row=1, column=1, sticky="nsew", padx=(12, 0))
        preview.grid_columnconfigure(0, weight=1)
        preview.grid_rowconfigure(0, weight=1)
        self.preview_box = preview
        self.preview = None
        self.caption = ctk.CTkLabel(preview, text="", text_color=MUTED)
        self.caption.grid(row=1, column=0, pady=(0, 12))
        self.reset_preview()

    def folder(self):
        return self.app.user_dir(SCREENSHOT_DIR)

    def reset_preview(self):
        # CTkLabel cannot drop an image once set, so start from a fresh label
        if self.preview is not None:
            self.preview.destroy()
        self.current = None
        self.preview = ctk.CTkLabel(self.preview_box, text=t("gallery.select"), text_color=MUTED)
        self.preview.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        self.preview.bind("<Configure>", lambda *e: self.show(self.current) if self.current else None)
        self.caption.configure(text="")

    def refresh(self):
        self.reset_preview()
        paths = list_screenshots(self.folder())
        if self.fill(paths):
            self.show(paths[0])

    def describe(self, path):
        img = load_image(path)
        img.thumbnail(self.THUMB)
        return ctk.CTkImage(img, img, size=img.size), self.label_for(path)

    def open(self, path):
        self.show(path)

    @staticmethod
    def label_for(path):
        stamp = os.path.basename(path).replace("screenshot_", "").rsplit(".", 1)[0].split("_")[0]  # drop the milliseconds
        try:
            return datetime.strptime(stamp, "%Y%m%d%H%M%S").strftime("%d/%m/%Y · %H:%M:%S")
        except ValueError:
            return os.path.basename(path)

    def show(self, path):
        if not os.path.exists(path):
            return
        self.current = path
        img = load_image(path)
        box_w, box_h = max(self.preview.winfo_width(), 100), max(self.preview.winfo_height(), 100)
        scale = min(box_w / img.width, box_h / img.height, 1.0)
        size = (int(img.width * scale), int(img.height * scale))
        photo = ctk.CTkImage(img, img, size=size)
        self.preview.configure(image=photo, text="")
        self.preview.image = photo
        self.caption.configure(text=f"{os.path.basename(path)}  ·  {self.label_for(path)}")


# ---------------------------------------------------------------- Recordings page

class RecordingsPage(LocalMediaPage):
    THUMB = (200, 120)
    kind = "video"
    title_key, count_key, empty_key = "nav.recordings", "recordings.count", "recordings.empty"

    def __init__(self, master, app):
        super().__init__(master, app)
        self.player = VideoPlayer(self, t("recordings.select"))
        self.player.grid(row=1, column=1, sticky="nsew", padx=(12, 0))

    def folder(self):
        return self.app.user_dir(self.app.settings["record_dir"])

    def refresh(self):
        self.player.unload()
        paths = list_recordings(self.folder())
        if self.fill(paths):
            self.player.load(paths[0])
        else:
            self.player.show_message(t("recordings.select"))

    def open(self, path):
        self.player.load(path)

    def release_files(self):
        self.player.unload()  # the player keeps the video file open

    def describe(self, path):
        """Thumbnail and 'date / duration · size' text for a video file."""
        cap = cv2.VideoCapture(path)
        ok, frame = cap.read()
        fps = cap.get(cv2.CAP_PROP_FPS) or 0
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        cap.release()
        size_mb = os.path.getsize(path) / (1024 * 1024)
        if ok:
            img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            img.thumbnail(self.THUMB)
        else:
            img = Image.new("RGB", self.THUMB, (40, 40, 40))
        duration = format_elapsed(frames / fps) if ok and fps > 0 and frames > 0 else t("recordings.in_progress")
        return ctk.CTkImage(img, img, size=img.size), f"{self.label_for(path)}\n{duration} · {size_mb:.1f} MB"

    @staticmethod
    def label_for(path):
        name = os.path.basename(path).rsplit(".", 1)[0].replace("rec_", "")
        try:
            return datetime.strptime(name, "%Y%m%d_%H%M%S").strftime("%d/%m/%Y · %H:%M:%S")
        except ValueError:
            return os.path.basename(path)

    def on_hide(self):
        self.player.pause()


# ---------------------------------------------------------------- Settings page

class SettingsPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self._blink_job = None
        s = app.settings

        ctk.CTkLabel(self, text=t("nav.settings"), font=ctk.CTkFont(size=24, weight="bold")).pack(anchor="w", pady=(0, 12))
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.pack(fill="both", expand=True)
        card = ctk.CTkFrame(scroll, corner_radius=12)
        card.pack(fill="x")
        card.grid_columnconfigure(1, weight=1)

        def row(r, title, subtitle, card=card):
            box = ctk.CTkFrame(card, fg_color="transparent")
            box.grid(row=r, column=0, sticky="w", padx=18, pady=12)
            label = ctk.CTkLabel(box, text=title, font=ctk.CTkFont(size=14, weight="bold"))
            label.pack(anchor="w")
            ctk.CTkLabel(box, text=subtitle, text_color=MUTED, font=ctk.CTkFont(size=12)).pack(anchor="w")
            return label

        row(0, t("settings.threshold"), t("settings.threshold_help"))
        self.threshold_label = ctk.CTkLabel(card, text=f"{int(s['threshold'])}%", width=50)
        self.threshold_label.grid(row=0, column=2, padx=18)
        slider = ctk.CTkSlider(card, from_=50, to=100, number_of_steps=50, command=self.on_threshold)
        slider.set(s["threshold"])
        slider.grid(row=0, column=1, sticky="ew")

        row(1, t("settings.save"), t("settings.save_help"))
        self.save_switch = ctk.CTkSwitch(card, text="", command=self.on_save)
        if s["save_screenshots"]:
            self.save_switch.select()
        self.save_switch.grid(row=1, column=2, padx=18)

        row(2, t("settings.cooldown"), t("settings.cooldown_help"))
        self.cooldown_label = ctk.CTkLabel(card, text=f"{int(s['cooldown'])} s", width=50)
        self.cooldown_label.grid(row=2, column=2, padx=18)
        cooldown = ctk.CTkSlider(card, from_=0, to=10, number_of_steps=10, command=self.on_cooldown)
        cooldown.set(s["cooldown"])
        cooldown.grid(row=2, column=1, sticky="ew")

        self.cam_title = row(3, t("settings.camera"), t("settings.camera_help"))
        self.cam = ctk.CTkOptionMenu(card, values=[""], width=280, dynamic_resizing=False, command=self.on_camera)
        self.cam.grid(row=3, column=1, sticky="e")
        self.cam_refresh = ctk.CTkButton(card, text="⟳", width=36, command=self.refresh_cameras)
        self.cam_refresh.grid(row=3, column=2, padx=18)
        self.refresh_cameras()

        row(4, t("settings.appearance"), t("settings.appearance_help"))
        appearance_selector(card, app).grid(row=4, column=1, columnspan=2, sticky="e", padx=18)

        row(5, t("settings.language"), t("settings.language_help"))
        language_selector(card, app).grid(row=5, column=1, columnspan=2, sticky="e", padx=18)

        # Recording
        ctk.CTkLabel(scroll, text=t("settings.recording"), font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="w", pady=(20, 8))
        rec = ctk.CTkFrame(scroll, corner_radius=12)
        rec.pack(fill="x")
        rec.grid_columnconfigure(1, weight=1)

        row(0, t("settings.record_webcam"), t("settings.record_webcam_help"), card=rec)
        self.record_switch = ctk.CTkSwitch(rec, text="", command=self.on_record)
        if s["record_webcam"]:
            self.record_switch.select()
        self.record_switch.grid(row=0, column=2, padx=18)

        row(1, t("settings.record_dir"), t("settings.record_dir_help"), card=rec)
        self.dir_label = ctk.CTkLabel(rec, text="", text_color=MUTED, anchor="e")
        self.dir_label.grid(row=1, column=1, sticky="ew", padx=(0, 10))
        ctk.CTkButton(rec, text=t("settings.browse"), width=100, command=self.on_browse).grid(row=1, column=2, padx=18)
        self.show_record_dir()

        row(2, t("settings.record_duration"), t("settings.record_duration_help"), card=rec)
        duration = ctk.CTkFrame(rec, fg_color="transparent")
        duration.grid(row=2, column=1, columnspan=2, sticky="e", padx=18)
        self.duration_entry = ctk.CTkEntry(duration, width=70, justify="center")
        self.duration_entry.insert(0, str(s["record_duration"]))
        self.duration_entry.pack(side="left")
        self.duration_entry.bind("<KeyRelease>", self.on_duration)
        self.unit_labels = {unit: t(f"settings.unit_{unit}") for unit in DURATION_UNITS}
        self.unit_menu = ctk.CTkOptionMenu(duration, values=list(self.unit_labels.values()), width=110,
                                           command=self.on_unit)
        self.unit_menu.set(self.unit_labels[s["record_unit"]])
        self.unit_menu.pack(side="left", padx=8)
        self.unlimited_switch = ctk.CTkSwitch(duration, text=t("settings.record_no_limit"), command=self.on_unlimited)
        if s["record_unlimited"]:
            self.unlimited_switch.select()
        self.unlimited_switch.pack(side="left", padx=(8, 0))
        self.update_duration_state()

    def update(self, key, value):
        self.app.settings[key] = value
        save_settings(self.app.settings)

    def refresh_cameras(self):
        self.cameras = list_cameras()
        if not self.cameras:
            self.cam.configure(values=[t("settings.no_camera")], state="disabled")
            self.cam.set(t("settings.no_camera"))
            return
        self.cam.configure(values=self.cameras, state="normal")
        index = int(self.app.settings["camera_index"])
        self.cam.set(self.cameras[index] if index < len(self.cameras) else self.cameras[0])

    def blink_camera(self, duration=4000, interval=250):
        """Flash the camera option so the user sees it has to be set up."""
        if self._blink_job is None:
            # Remember the real colors (not the ones of a blink already in progress)
            self._cam_colors = {
                "title": self.cam_title.cget("text_color"),
                "menu": (self.cam.cget("fg_color"), self.cam.cget("button_color"),
                         self.cam.cget("text_color_disabled")),
                "refresh": self.cam_refresh.cget("fg_color"),
            }
        else:
            self.after_cancel(self._blink_job)
        normal = self._cam_colors

        def flash(remaining, on):
            self._blink_job = None
            if not self.winfo_exists():
                return
            if remaining <= 0:
                on = False
            self.cam_title.configure(text_color=WARNING if on else normal["title"])
            self.cam.configure(fg_color=WARNING if on else normal["menu"][0],
                               button_color=WARNING_DARK if on else normal["menu"][1],
                               text_color_disabled="white" if on else normal["menu"][2])
            self.cam_refresh.configure(fg_color=WARNING if on else normal["refresh"])
            if remaining > 0:
                self._blink_job = self.after(interval, flash, remaining - interval, not on)

        flash(duration, True)

    def on_camera(self, name):
        self.update("camera_index", self.cameras.index(name))

    def on_threshold(self, v):
        self.threshold_label.configure(text=f"{int(v)}%")
        self.update("threshold", int(v))

    def on_cooldown(self, v):
        self.cooldown_label.configure(text=f"{int(v)} s")
        self.update("cooldown", int(v))

    def on_save(self):
        self.update("save_screenshots", bool(self.save_switch.get()))

    def on_record(self):
        self.update("record_webcam", bool(self.record_switch.get()))

    def show_record_dir(self):
        path = os.path.abspath(self.app.settings["record_dir"])
        self.dir_label.configure(text=path if len(path) <= 45 else "…" + path[-44:])

    def on_browse(self):
        folder = filedialog.askdirectory(title=t("settings.record_dir"),
                                         initialdir=os.path.abspath(self.app.settings["record_dir"]))
        if folder:
            self.update("record_dir", folder)
            self.show_record_dir()

    def on_duration(self, _event=None):
        text = self.duration_entry.get().strip()
        if text.isdigit() and int(text) > 0:
            self.duration_entry.configure(border_color=("#979DA2", "#565B5E"))
            self.update("record_duration", int(text))
        else:
            self.duration_entry.configure(border_color=DANGER)

    def on_unit(self, label):
        units = {text: unit for unit, text in self.unit_labels.items()}
        self.update("record_unit", units[label])

    def on_unlimited(self):
        self.update("record_unlimited", bool(self.unlimited_switch.get()))
        self.update_duration_state()

    def update_duration_state(self):
        state = "disabled" if self.app.settings["record_unlimited"] else "normal"
        self.duration_entry.configure(state=state)
        self.unit_menu.configure(state=state)



# ---------------------------------------------------------------- Main window

class MainFrame(ctk.CTkFrame):
    def __init__(self, master, app, user):
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        side = ctk.CTkFrame(self, width=220, corner_radius=0)
        side.grid(row=0, column=0, sticky="ns")
        side.grid_propagate(False)
        side.grid_columnconfigure(0, weight=1)
        side.grid_rowconfigure(20, weight=1)

        logo = Image.open(APP_LOGO)
        ctk.CTkLabel(side, text="  AccidentAI", image=ctk.CTkImage(logo, logo, size=(26, 26)), compound="left",
                     font=ctk.CTkFont(size=20, weight="bold")).grid(row=0, column=0, padx=20, pady=(24, 4), sticky="w")
        who = ctk.CTkFrame(side, fg_color="transparent")
        who.grid(row=1, column=0, padx=20, pady=(0, 20), sticky="w")
        self.identity = ctk.CTkLabel(who, text="", text_color=MUTED)
        self.identity.pack(anchor="w")
        if user["role"] == "admin":  # normal users get no role label, admins a badge
            role_badge(who, t("admin.role_admin")).pack(anchor="w", pady=(6, 0))

        content = ctk.CTkFrame(self, fg_color="transparent")
        content.grid(row=0, column=1, sticky="nsew", padx=24, pady=24)
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(0, weight=1)

        self.detection = DetectionPage(content, app)
        self.pages = {
            "detection": self.detection,
            "gallery": GalleryPage(content, app),
            "recordings": RecordingsPage(content, app),
            "profile": ProfilePage(content, app),
            "settings": SettingsPage(content, app),
        }
        if user["role"] == "admin":
            self.pages["admin"] = AdminPage(content, app)
        self.nav = {}
        for i, name in enumerate(self.pages):
            btn = ctk.CTkButton(side, text=t(f"nav.{name}"), anchor="w", height=40, corner_radius=8,
                                fg_color="transparent", text_color=("gray10", "gray90"),
                                hover_color=("gray75", "gray25"), command=lambda n=name: self.show(n))
            btn.grid(row=2 + i, column=0, padx=12, pady=3, sticky="ew")
            self.nav[name] = btn

        self.model_status = ctk.CTkLabel(side, text=t("models.loading"), text_color=WARNING)
        self.model_status.grid(row=21, column=0, padx=20, pady=6, sticky="w")
        ctk.CTkButton(side, text=t("sidebar.logout"), height=36, fg_color="transparent", border_width=1,
                      text_color=TEXT, command=app.confirm_logout).grid(row=22, column=0, padx=12, pady=(6, 0), sticky="ew")
        ctk.CTkButton(side, text=t("sidebar.exit"), height=36, fg_color=DANGER, hover_color=DANGER_HOVER,
                      command=app.confirm_exit).grid(row=23, column=0, padx=12, pady=(8, 20), sticky="ew")
        self.app = app
        self.show_identity()
        self.after(500, self.show_upload_messages)

    def show_identity(self):
        user = self.app.api.user
        self.identity.configure(text=t("sidebar.signed_in", user=user.get("full_name") or user["username"]))

    def show_upload_messages(self):
        uploader = self.app.uploader
        while uploader is not None and not uploader.messages.empty():
            self.detection.log_event(uploader.messages.get_nowait())
        self.after(500, self.show_upload_messages)


    def show(self, name):
        for n, page in self.pages.items():
            if n != name and page.winfo_ismapped() and hasattr(page, "on_hide"):
                page.on_hide()
            page.grid_forget()
            self.nav[n].configure(fg_color="transparent", text_color=("gray10", "gray90"))
        self.pages[name].grid(row=0, column=0, sticky="nsew")
        self.nav[name].configure(fg_color=ACCENT, text_color=("gray95", "gray95"))
        if name in ("gallery", "recordings", "admin"):
            self.pages[name].refresh()

    def models_ready(self, error=None):
        # Both the loader poll and the login can report it; only log it once
        if getattr(self, "_models_reported", False):
            return
        self._models_reported = True
        if error:
            self.model_status.configure(text=t("models.error"), text_color=DANGER)
            self.detection.log_event(t("log.models_failed", error=error))
        else:
            self.model_status.configure(text=t("models.ready"), text_color=SUCCESS)
            self.detection.log_event(t("log.models_ready"))


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        ctk.set_appearance_mode(self.settings["appearance"])
        ctk.set_default_color_theme("blue")
        set_language(self.settings["language"])

        self.title(t("app.title"))
        # Same logo as next to "AccidentAI" in the sidebar
        self.iconbitmap(APP_ICON)
        self.geometry("1200x760")
        self.minsize(1000, 640)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.detector = None
        self.model_error = None
        self.main = None
        self.user = None
        self.uploader = None
        self.api = ApiClient()
        self.server_process = None
        self.server_state = "checking"
        threading.Thread(target=self.connect_server, daemon=True).start()
        self.models_loaded = threading.Event()
        threading.Thread(target=self.load_models, daemon=True).start()
        self.after(200, self.check_models)

        self.login = LoginFrame(self, self.on_login)
        self.login.pack(fill="both", expand=True)

    def connect_server(self):
        """Use the API if it runs; if it is this PC's own server and it is off, start it."""
        if self.api.is_up():
            self.server_state = "up"
            return
        host = urlparse(self.api.base_url).hostname
        if host in ("127.0.0.1", "localhost"):
            port = str(urlparse(self.api.base_url).port or 8000)
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            self.server_process = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "server.main:app", "--host", host, "--port", port],
                cwd=os.path.dirname(os.path.abspath(__file__)), creationflags=flags,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(60):
                if self.api.is_up():
                    self.server_state = "up"
                    return
                if self.server_process.poll() is not None:
                    break
                time.sleep(0.5)
        self.server_state = "down"

    def user_dir(self, base):
        """Screenshots and recordings are kept per account on this PC."""
        return os.path.join(base, self.user["username"])

    def load_models(self):
        try:
            from detection_service import AccidentDetector
            self.detector = AccidentDetector()
        except Exception as e:  # surface the error in the UI instead of crashing
            self.model_error = str(e)
        self.models_loaded.set()

    def check_models(self):
        if self.models_loaded.is_set():
            self.notify_models()
        else:
            self.after(200, self.check_models)

    def notify_models(self):
        if self.main is not None:
            self.main.models_ready(self.model_error)

    def on_login(self, user):
        self.user = user
        self.uploader = CloudUploader(self.api, user["username"])
        self.login.destroy()
        self.show_main()

    def confirm_exit(self):
        ConfirmDialog(self, t("confirm.exit_title"), t("confirm.exit_message"), t("sidebar.exit"), self.on_close)

    def confirm_logout(self):
        ConfirmDialog(self, t("confirm.logout_title"), t("confirm.logout_message"), t("sidebar.logout"), self.logout)

    def logout(self):
        self.stop_detection()
        self.uploader.stop()  # unsent files stay pending until this user signs in again
        self.uploader = None
        self.api.logout()
        self.user = None
        self.main.destroy()
        self.main = None
        self.login = LoginFrame(self, self.on_login)
        self.login.pack(fill="both", expand=True)

    def show_main(self, page="detection"):
        self.main = MainFrame(self, self, self.user)
        self.main.pack(fill="both", expand=True)
        self.main.show(page)
        if self.models_loaded.is_set():
            self.notify_models()

    def set_appearance(self, mode):
        ctk.set_appearance_mode(mode)
        self.settings["appearance"] = mode
        save_settings(self.settings)

    def set_language(self, lang):
        if lang == self.settings["language"]:
            return
        self.settings["language"] = lang
        save_settings(self.settings)
        set_language(lang)
        self.title(t("app.title"))
        # Rebuild the current screen so every text is redrawn in the new language
        if self.main is not None:
            self.main.detection.stop()
            self.main.destroy()
            self.show_main("settings")
        else:
            self.login.destroy()
            self.login = LoginFrame(self, self.on_login)
            self.login.pack(fill="both", expand=True)

    def stop_detection(self):
        if self.main is not None:
            self.main.detection.stop()
            worker = self.main.detection.worker
            if worker is not None and worker.is_alive():
                worker.join(timeout=10)  # lets the recorder finish its MP4 file

    def on_close(self):
        self.stop_detection()
        if self.server_process is not None:
            self.server_process.terminate()  # we started it, so we stop it
        self.destroy()


# Run the application
def launch_application():
    # Give the app its own taskbar identity so Windows shows our icon instead of Python's
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AccidentDetection.App")
    except (AttributeError, OSError):
        pass
    App().mainloop()
