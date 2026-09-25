"""Widgets and helpers shared by the pages of the desktop app."""
import os
import queue
import threading
import time

import cv2
import customtkinter as ctk
from PIL import Image

from i18n import t
from recorder import format_elapsed

APP_ICON = "./Images/app_icon.ico"
APP_LOGO = "./Images/app_logo.png"  # same eye logo, larger, for in-app use

ACCENT = "#1f6aa5"
DANGER = "#c0392b"
DANGER_HOVER = "#962d22"
SUCCESS = "#27ae60"
SUCCESS_HOVER = "#1e8449"
WARNING = "#e67e22"
WARNING_DARK = "#b85f14"
MUTED = ("gray40", "gray65")
TEXT = ("gray10", "gray90")


def fit_size(image, widget, minimum=100, upscale=True):
    """Size that fits `image` inside `widget` while keeping its aspect ratio."""
    box_w, box_h = max(widget.winfo_width(), minimum), max(widget.winfo_height(), minimum)
    scale = min(box_w / image.width, box_h / image.height)
    if not upscale:
        scale = min(scale, 1.0)
    return max(int(image.width * scale), 1), max(int(image.height * scale), 1)


def human_size(num_bytes):
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024 or unit == "GB":
            return f"{num_bytes:.0f} {unit}" if unit == "B" else f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024


def role_badge(master, text):
    """Pill badge: tinted amber background, thin border, star icon (light, dark)."""
    badge = ctk.CTkFrame(master, corner_radius=12, border_width=1,
                         fg_color=("#fff4dc", "#2e2510"), border_color=("#f0c46a", "#6b5220"))
    ctk.CTkLabel(badge, text=f"★  {text}", text_color=("#8a5a00", "#f3c555"), height=20,
                 font=ctk.CTkFont(size=11, weight="bold")).pack(padx=10, pady=2)
    return badge


def add_reveal_button(entry, mask="•"):
    """Eye button inside a password entry: click to show / hide what was typed."""
    background = entry.cget("fg_color")
    button = ctk.CTkButton(entry, text="👁", width=30, height=26, corner_radius=6, fg_color=background,
                           hover_color=("gray80", "gray30"), text_color=MUTED, font=ctk.CTkFont(size=15))

    # Own flag: while the placeholder is displayed, entry.cget("show") reports "" even for a masked field
    state = {"visible": False}

    def toggle():
        state["visible"] = not state["visible"]
        entry.configure(show="" if state["visible"] else mask)
        button.configure(text_color=ACCENT if state["visible"] else MUTED)  # colored while the password is visible

    button.configure(command=toggle)
    button.place(relx=1.0, x=-5, rely=0.5, anchor="e")
    return button


def media_item(parent, text, on_open, on_delete, image=None):
    """List entry (thumbnail + text) with a small trash button in its top-right corner. Returns the open button."""
    item = ctk.CTkFrame(parent, fg_color="transparent")
    item.pack(fill="x", pady=4)
    button = ctk.CTkButton(item, image=image, text=text, compound="top", fg_color="transparent", text_color=TEXT,
                           hover_color=("gray80", "gray25"), command=on_open)
    button.pack(fill="x")
    trash = ctk.CTkButton(item, text="🗑", width=28, height=28, corner_radius=8, fg_color=("gray85", "gray20"),
                          hover_color=DANGER, text_color=TEXT, font=ctk.CTkFont(size=13), command=on_delete)
    trash.place(relx=1.0, x=-6, y=6, anchor="ne")
    return button


def delete_all_button(parent, command):
    return ctk.CTkButton(parent, text=t("media.delete_all"), width=120, fg_color="transparent", border_width=1,
                         border_color=DANGER, text_color=DANGER, hover_color=("#f6d5d1", "#3b1d1a"), command=command)


def load_image(path):
    """Open an image fully into memory, so the file is not kept open (Windows could not delete it)."""
    with Image.open(path) as img:
        return img.copy()


class BackgroundTasks:
    """Runs slow work (network, disk) off the UI thread and hands the result back on it."""

    def __init__(self, widget):
        self.widget = widget
        self.results = queue.Queue()
        self.widget.after(50, self._drain)

    def run(self, func, on_done):
        def work():
            try:
                self.results.put((on_done, func(), None))
            except Exception as e:
                self.results.put((on_done, None, e))
        threading.Thread(target=work, daemon=True).start()

    def _drain(self):
        try:
            while True:
                on_done, result, error = self.results.get_nowait()
                on_done(result, error)
        except queue.Empty:
            pass
        if self.widget.winfo_exists():
            self.widget.after(50, self._drain)


class ConfirmDialog(ctk.CTkToplevel):
    """Small modal yes/no window centered on the main window."""

    def __init__(self, master, title, message, confirm_text, on_confirm, danger=True):
        super().__init__(master)
        self.on_confirm = on_confirm
        self.title(title)
        self.resizable(False, False)
        self.transient(master.winfo_toplevel())

        ctk.CTkLabel(self, text=title, font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=24, pady=(20, 4))
        ctk.CTkLabel(self, text=message, text_color=MUTED, wraplength=320, justify="left").pack(anchor="w", padx=24)
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(fill="x", padx=24, pady=(20, 20))
        ctk.CTkButton(buttons, text=confirm_text, width=110, command=self.confirm,
                      fg_color=DANGER if danger else ACCENT, hover_color=DANGER_HOVER if danger else None).pack(side="right")
        ctk.CTkButton(buttons, text=t("confirm.cancel"), width=110, command=self.destroy, fg_color="transparent",
                      border_width=1, text_color=TEXT).pack(side="right", padx=(0, 8))

        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self.confirm())

        # Center on the main window, then make it modal
        self.update_idletasks()
        top = master.winfo_toplevel()
        x = top.winfo_rootx() + (top.winfo_width() - self.winfo_reqwidth()) // 2
        y = top.winfo_rooty() + (top.winfo_height() - self.winfo_reqheight()) // 2
        self.geometry(f"+{x}+{y}")
        self.after(250, lambda: self.iconbitmap(APP_ICON))  # CTkToplevel sets its own icon after ~200 ms
        self.after(10, self.grab_and_focus)

    def grab_and_focus(self):
        self.grab_set()
        self.focus_force()

    def confirm(self):
        self.destroy()
        self.on_confirm()


class StatCard(ctk.CTkFrame):
    def __init__(self, master, title, value="—"):
        super().__init__(master, corner_radius=12)
        ctk.CTkLabel(self, text=title, text_color=MUTED, font=ctk.CTkFont(size=12)).pack(anchor="w", padx=14, pady=(10, 0))
        self.value = ctk.CTkLabel(self, text=value, font=ctk.CTkFont(size=22, weight="bold"))
        self.value.pack(anchor="w", padx=14, pady=(0, 10))

    def set(self, text, color=None):
        self.value.configure(text=text, text_color=color or TEXT)


class VideoPlayer(ctk.CTkFrame):
    """Plays a local video file: play/pause, seek bar, speed 0.5x-16x, open in the system player."""

    SPEEDS = {"0.5×": 0.5, "1×": 1, "2×": 2, "4×": 4, "8×": 8, "16×": 16}
    MIN_INTERVAL_MS = 30  # the screen can't usefully refresh faster; skip frames instead

    def __init__(self, master, placeholder):
        super().__init__(master, corner_radius=12)
        self.placeholder = placeholder
        self.current = None
        self.capture = None
        self.fps = 10.0
        self.total = 0
        self.playing = False
        self.job = None
        self.speed = 1

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.screen = None
        self.reset_screen(placeholder)

        self.play_btn = ctk.CTkButton(self, text="▶", width=44, command=self.toggle, state="disabled")
        self.play_btn.grid(row=1, column=0, padx=(12, 8))
        self.slider = ctk.CTkSlider(self, from_=0, to=1, command=self.on_seek, state="disabled")
        self.slider.set(0)
        self.slider.grid(row=1, column=1, sticky="ew")
        self.time_label = ctk.CTkLabel(self, text="00:00:00 / 00:00:00", width=150)
        self.time_label.grid(row=1, column=2, padx=12)

        # Two short rows rather than one long one, so the player also fits narrow panels
        options = ctk.CTkFrame(self, fg_color="transparent")
        options.grid(row=2, column=0, columnspan=3, sticky="ew", padx=12, pady=(6, 0))
        ctk.CTkLabel(options, text=t("recordings.speed"), text_color=MUTED).pack(side="left")
        speeds = ctk.CTkSegmentedButton(options, values=list(self.SPEEDS), command=self.on_speed)
        speeds.set("1×")
        speeds.pack(side="left", padx=(8, 0))
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=3, column=0, columnspan=3, sticky="ew", padx=12, pady=(6, 12))
        self.external_btn = ctk.CTkButton(bottom, text=t("recordings.open_external"), width=0, state="disabled",
                                          command=lambda: os.startfile(os.path.abspath(self.current)))
        self.external_btn.pack(side="right")
        self.caption = ctk.CTkLabel(bottom, text="", text_color=MUTED, anchor="w")
        self.caption.pack(side="left", fill="x", expand=True, padx=(0, 8))

    def reset_screen(self, text):
        # CTkLabel cannot drop an image once set, so start from a fresh label
        if self.screen is not None:
            self.screen.destroy()
        self.screen = ctk.CTkLabel(self, text=text, text_color=MUTED)
        self.screen.grid(row=0, column=0, columnspan=3, sticky="nsew", padx=12, pady=12)

    def show_message(self, text):
        self.unload()
        self.reset_screen(text)
        self.caption.configure(text="")

    def load(self, path, caption=None):
        self.unload()
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            self.reset_screen(t("recordings.unreadable"))
            return False
        self.capture = cap
        self.current = path
        self.fps = cap.get(cv2.CAP_PROP_FPS) or 10.0
        self.total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        self.slider.configure(state="normal", from_=0, to=max(self.total - 1, 1), number_of_steps=max(self.total - 1, 1))
        self.play_btn.configure(state="normal", text="▶")
        self.external_btn.configure(state="normal")
        self.caption.configure(text=caption or os.path.basename(path))
        self.update_idletasks()  # the screen may have just been recreated: let it take its real size first
        self.show_next_frame()
        return True

    def unload(self):
        self.pause()
        if self.capture is not None:
            self.capture.release()
            self.capture = None
        self.current = None
        self.slider.set(0)
        self.time_label.configure(text="00:00:00 / 00:00:00")
        self.slider.configure(state="disabled")
        self.play_btn.configure(state="disabled", text="▶")
        self.external_btn.configure(state="disabled")

    def show_next_frame(self):
        ok, frame = self.capture.read()
        if not ok:
            return False
        image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        photo = ctk.CTkImage(image, image, size=fit_size(image, self.screen))
        self.screen.configure(image=photo, text="")
        self.screen.image = photo
        position = int(self.capture.get(cv2.CAP_PROP_POS_FRAMES)) - 1
        self.slider.set(position)
        self.time_label.configure(text=f"{format_elapsed(position / self.fps)} / {format_elapsed(self.total / self.fps)}")
        return True

    def toggle(self):
        if self.playing:
            self.pause()
            return
        if self.capture is None:
            return
        if int(self.capture.get(cv2.CAP_PROP_POS_FRAMES)) >= self.total:
            self.capture.set(cv2.CAP_PROP_POS_FRAMES, 0)  # replay from the start
        self.playing = True
        self.play_btn.configure(text="⏸")
        self.sync_clock()
        self.tick()

    def sync_clock(self):
        """Playback follows the wall clock from here, so slow drawing never slows the video down."""
        self.clock_start = time.time()
        self.clock_frame = int(self.capture.get(cv2.CAP_PROP_POS_FRAMES))

    def tick(self):
        self.job = None
        if not self.playing:
            return
        target = self.clock_frame + int((time.time() - self.clock_start) * self.fps * self.speed)
        behind = target - int(self.capture.get(cv2.CAP_PROP_POS_FRAMES))
        if behind >= 1:
            # Skip the frames we have no time to draw (at 8x/16x most of them)
            for _ in range(behind - 1):
                self.capture.grab()
            if not self.show_next_frame():
                self.pause()
                return
        interval = max(1000 / (self.fps * self.speed), self.MIN_INTERVAL_MS)
        self.job = self.after(int(interval), self.tick)

    def on_speed(self, label):
        self.speed = self.SPEEDS[label]
        if self.playing:
            self.sync_clock()

    def pause(self):
        self.playing = False
        if self.job is not None:
            self.after_cancel(self.job)
            self.job = None
        self.play_btn.configure(text="▶")

    def on_seek(self, value):
        if self.capture is None:
            return
        self.capture.set(cv2.CAP_PROP_POS_FRAMES, int(value))
        self.show_next_frame()
        if self.playing:
            self.sync_clock()
