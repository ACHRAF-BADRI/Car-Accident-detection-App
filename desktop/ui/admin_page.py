"""Admin area: dashboard of the whole platform, and every user's images and videos."""
import io
import os
import tempfile
import tkinter as tk
from datetime import datetime

import customtkinter as ctk
from PIL import Image

from desktop.cloud.api_client import ApiError, parse_time
from desktop.detection.recorder import format_elapsed
from desktop.i18n import t
from desktop.ui.widgets import (ACCENT, APP_ICON, DANGER, DANGER_HOVER, MUTED, SUCCESS, SUCCESS_HOVER, TEXT, WARNING, WARNING_DARK,
                     BackgroundTasks, ConfirmDialog, StatCard, VideoPlayer, add_reveal_button, delete_all_button,
                     fit_size, human_size, media_item)

CACHE_DIR = os.path.join(tempfile.gettempdir(), "accident_detection_cache")
ATLAS_FREE_TIER = 512 * 1024 * 1024

# Categorical slots 1-2 of the validated chart palette, stepped per mode
SERIES = {"images": {"Light": "#2a78d6", "Dark": "#3987e5"},
          "videos": {"Light": "#eb6834", "Dark": "#d95926"}}


def fmt_date(value, with_time=True):
    moment = parse_time(value) if isinstance(value, str) else value
    if moment is None:
        return t("admin.never")
    return moment.strftime("%d/%m/%Y · %H:%M" if with_time else "%d/%m/%Y")


def error_text(error):
    code = error.code if isinstance(error, ApiError) else str(error)
    return t(f"api.{code}") if t(f"api.{code}") != f"api.{code}" else t("admin.load_failed", error=code)


class AdminPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.tasks = BackgroundTasks(self)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        ctk.CTkLabel(bar, text=t("nav.admin"), font=ctk.CTkFont(size=24, weight="bold")).pack(side="left")
        self.tab_labels = {"dashboard": t("admin.dashboard"), "users": t("admin.users")}
        self.tabs = ctk.CTkSegmentedButton(bar, values=list(self.tab_labels.values()), command=self.on_tab)
        self.tabs.pack(side="left", padx=20)
        ctk.CTkButton(bar, text=t("gallery.refresh"), width=110, command=self.refresh).pack(side="right")

        self.views = {"dashboard": DashboardView(self, app, self.tasks), "users": UsersView(self, app, self.tasks)}
        self.current = "dashboard"
        self.tabs.set(self.tab_labels["dashboard"])
        self.views["dashboard"].grid(row=1, column=0, sticky="nsew")

    def on_tab(self, label):
        name = next(k for k, v in self.tab_labels.items() if v == label)
        self.views[self.current].grid_forget()
        self.views["users"].player.pause()
        self.current = name
        self.views[name].grid(row=1, column=0, sticky="nsew")
        self.views[name].refresh()

    def refresh(self):
        self.views[self.current].refresh()

    def on_hide(self):
        self.views["users"].player.pause()


# ---------------------------------------------------------------- Dashboard

class DashboardView(ctk.CTkFrame):
    def __init__(self, master, app, tasks):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.tasks = tasks
        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        cards = ctk.CTkFrame(self, fg_color="transparent")
        cards.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        for i in range(4):
            cards.grid_columnconfigure(i, weight=1, uniform="cards")
        self.cards = {key: StatCard(cards, t(f"admin.card_{key}")) for key in ("users", "images", "videos", "storage")}
        for i, card in enumerate(self.cards.values()):
            card.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 6, 0 if i == 3 else 6))

        self.chart = BarChart(self)
        self.chart.grid(row=1, column=0, sticky="nsew", padx=(0, 12))

        top = ctk.CTkFrame(self, corner_radius=12)
        top.grid(row=1, column=1, sticky="nsew")
        ctk.CTkLabel(top, text=t("admin.top_users"), font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=16, pady=(14, 8))
        self.top_list = ctk.CTkFrame(top, fg_color="transparent")
        self.top_list.pack(fill="both", expand=True, padx=16)

    def refresh(self):
        for card in self.cards.values():
            card.set("…")
        self.tasks.run(self.app.api.admin_stats, self.on_stats)

    def on_stats(self, stats, error):
        if error:
            for card in self.cards.values():
                card.set("—")
            self.chart.show_message(error_text(error))
            return
        self.cards["users"].set(f"{stats['users']}  ({stats['admins']} admin)")
        self.cards["images"].set(str(stats["images"]))
        self.cards["videos"].set(str(stats["videos"]))
        used = stats["db_storage_bytes"]
        # Atlas free clusters stop accepting writes at 512 MB: warn well before
        self.cards["storage"].set(f"{human_size(used)} / 512 MB", DANGER if used > 0.8 * ATLAS_FREE_TIER else None)
        self.chart.set_data(stats["timeline"])

        for w in self.top_list.winfo_children():
            w.destroy()
        if not stats["top_users"]:
            ctk.CTkLabel(self.top_list, text=t("admin.no_data"), text_color=MUTED).pack(anchor="w")
        for i, row in enumerate(stats["top_users"], start=1):
            line = ctk.CTkFrame(self.top_list, fg_color="transparent")
            line.pack(fill="x", pady=4)
            ctk.CTkLabel(line, text=f"{i}. {row['username']}", font=ctk.CTkFont(weight="bold")).pack(side="left")
            ctk.CTkLabel(line, text=t("admin.top_counts", images=row["images"], videos=row["videos"]),
                         text_color=MUTED).pack(side="right")


class BarChart(ctk.CTkFrame):
    """Grouped bars: images and videos uploaded per day, with a legend and hover tooltips."""

    PAD_L, PAD_R, PAD_T, PAD_B = 44, 16, 56, 34

    def __init__(self, master):
        super().__init__(master, corner_radius=12)
        self.data = []
        self.message = t("admin.loading")
        self.canvas = tk.Canvas(self, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True, padx=12, pady=12)
        self.canvas.bind("<Configure>", lambda e: self.draw())
        self.canvas.bind("<Motion>", self.on_hover)
        self.canvas.bind("<Leave>", lambda e: self.canvas.delete("tip"))
        self.hit_boxes = []

    def _set_appearance_mode(self, mode_string):
        super()._set_appearance_mode(mode_string)
        self.after(10, self.draw)  # theme switched: redraw with that mode's colors

    def mode(self):
        return "Dark" if ctk.get_appearance_mode() == "Dark" else "Light"

    def colors(self):
        dark = self.mode() == "Dark"
        return {"bg": self._apply_appearance_mode_raw(self.cget("fg_color")),
                "text": "#e6e6e6" if dark else "#1a1a1a", "muted": "#9a9a9a" if dark else "#6b6b6b",
                "grid": "#3a3a3a" if dark else "#dcdcdc", "tip_bg": "#101010" if dark else "#ffffff"}

    def _apply_appearance_mode_raw(self, color):
        if isinstance(color, (list, tuple)):
            return color[1] if self.mode() == "Dark" else color[0]
        return color

    def show_message(self, text):
        self.data, self.message = [], text
        self.draw()

    def set_data(self, timeline):
        self.data, self.message = timeline, None
        self.draw()

    def draw(self):
        c = self.canvas
        c.delete("all")
        self.hit_boxes = []
        col = self.colors()
        c.configure(bg=col["bg"])
        w, h = c.winfo_width(), c.winfo_height()
        if w < 50 or h < 50:
            return
        mode = self.mode()
        c.create_text(4, 4, anchor="nw", text=t("admin.chart_title"), fill=col["text"], font=("Segoe UI", 12, "bold"))
        # Legend (two series): swatch + label in text color
        x = 4
        for key in ("images", "videos"):
            c.create_rectangle(x, 32, x + 12, 44, fill=SERIES[key][mode], width=0)
            label = t(f"admin.series_{key}")
            c.create_text(x + 18, 38, anchor="w", text=label, fill=col["muted"], font=("Segoe UI", 10))
            x += 30 + 8 * len(label)
        if self.message or not self.data:
            c.create_text(w / 2, h / 2, text=self.message or t("admin.no_data"), fill=col["muted"], font=("Segoe UI", 11))
            return

        top = max(max(d["images"], d["videos"]) for d in self.data)
        step = max(1, -(-top // 4))  # about four gridlines, whole numbers
        y_max = max(step * 4, 1)
        plot_w, plot_h = w - self.PAD_L - self.PAD_R, h - self.PAD_T - self.PAD_B
        base = self.PAD_T + plot_h

        for i in range(5):
            value = step * i
            y = base - plot_h * value / y_max
            c.create_line(self.PAD_L, y, w - self.PAD_R, y, fill=col["grid"])
            c.create_text(self.PAD_L - 8, y, anchor="e", text=str(value), fill=col["muted"], font=("Segoe UI", 9))

        slot = plot_w / len(self.data)
        bar_w = max(min(slot * 0.32, 18), 2)
        for i, day in enumerate(self.data):
            x0 = self.PAD_L + slot * i + (slot - (2 * bar_w + 2)) / 2
            for j, key in enumerate(("images", "videos")):
                value = day[key]
                if value:
                    bx = x0 + j * (bar_w + 2)  # 2px gap between the two bars
                    y = base - plot_h * value / y_max
                    c.create_rectangle(bx, y, bx + bar_w, base, fill=SERIES[key][mode], width=0)
            if (len(self.data) - 1 - i) % 2 == 0 or len(self.data) <= 7:  # always label the latest day
                label = datetime.strptime(day["day"], "%Y-%m-%d").strftime("%d/%m")
                c.create_text(self.PAD_L + slot * (i + 0.5), base + 14, text=label, fill=col["muted"], font=("Segoe UI", 9))
            # Hover target: the whole day column, larger than the bars
            self.hit_boxes.append((self.PAD_L + slot * i, self.PAD_L + slot * (i + 1), day))

    def on_hover(self, event):
        c = self.canvas
        c.delete("tip")
        for x0, x1, day in self.hit_boxes:
            if x0 <= event.x < x1 and self.PAD_T <= event.y <= c.winfo_height() - self.PAD_B:
                col, mode = self.colors(), self.mode()
                lines = [(datetime.strptime(day["day"], "%Y-%m-%d").strftime("%d/%m/%Y"), None),
                         (f"{t('admin.series_images')} : {day['images']}", SERIES["images"][mode]),
                         (f"{t('admin.series_videos')} : {day['videos']}", SERIES["videos"][mode])]
                tx = min(event.x + 14, c.winfo_width() - 170)
                ty = max(event.y - 70, 4)
                c.create_rectangle(tx, ty, tx + 160, ty + 66, fill=col["tip_bg"], outline=col["grid"], tags="tip")
                for k, (text, swatch) in enumerate(lines):
                    y = ty + 12 + k * 20
                    if swatch:
                        c.create_rectangle(tx + 10, y - 5, tx + 20, y + 5, fill=swatch, width=0, tags="tip")
                    c.create_text(tx + (26 if swatch else 10), y, anchor="w", text=text, fill=col["text"],
                                  font=("Segoe UI", 10, "bold" if k == 0 else "normal"), tags="tip")
                return


# ---------------------------------------------------------------- Users

class UsersView(ctk.CTkFrame):
    THUMB = (170, 105)

    def __init__(self, master, app, tasks):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.tasks = tasks
        self.users = []
        self.selected = None
        self.select_after_refresh = None
        self.media = {"image": [], "video": []}
        self.generation = 0  # bumps when the selection changes, so late downloads are ignored
        self.kind = "image"

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        left = ctk.CTkFrame(self, fg_color="transparent")
        left.grid(row=0, column=0, sticky="ns")
        ctk.CTkButton(left, text=t("admin.new_user"), height=36, command=lambda: CreateUserDialog(self)).pack(fill="x", pady=(0, 8))
        self.user_list = ctk.CTkScrollableFrame(left, width=215, corner_radius=12)
        self.user_list.pack(fill="both", expand=True)

        detail = ctk.CTkFrame(self, fg_color="transparent")
        detail.grid(row=0, column=1, sticky="nsew", padx=(12, 0))
        detail.grid_columnconfigure(0, weight=1)
        detail.grid_rowconfigure(2, weight=1)
        self.detail = detail

        head = ctk.CTkFrame(detail, corner_radius=12)
        head.grid(row=0, column=0, sticky="ew")
        head.grid_columnconfigure(0, weight=1)
        self.name_label = ctk.CTkLabel(head, text=t("admin.select_user"), font=ctk.CTkFont(size=18, weight="bold"))
        self.name_label.grid(row=0, column=0, sticky="w", padx=16, pady=(12, 0))
        self.meta_label = ctk.CTkLabel(head, text="", text_color=MUTED, justify="left")
        self.meta_label.grid(row=1, column=0, sticky="w", padx=16, pady=(0, 12))
        self.actions = ctk.CTkFrame(head, fg_color="transparent")
        self.actions.grid(row=2, column=0, sticky="w", padx=16, pady=(0, 14))  # own row: the details keep the full width
        self.edit_btn = ctk.CTkButton(self.actions, text=t("admin.edit"), width=90, fg_color="transparent", border_width=1,
                                      text_color=TEXT, command=lambda: EditUserDialog(self, self.selected))
        self.role_btn = ctk.CTkButton(self.actions, text="", width=120, command=self.confirm_role)
        self.status_btn = ctk.CTkButton(self.actions, text="", width=110, command=self.confirm_status)
        self.delete_btn = ctk.CTkButton(self.actions, text=t("admin.delete"), width=100, fg_color=DANGER,
                                        hover_color=DANGER_HOVER, command=self.confirm_delete)
        self.actions.grid_remove()

        self.tabs_row = ctk.CTkFrame(detail, fg_color="transparent")
        self.tabs_row.grid(row=1, column=0, sticky="ew", pady=10)
        self.kind_tabs = ctk.CTkSegmentedButton(self.tabs_row, values=["image", "video"], command=self.on_kind)  # labels set per user
        self.kind_tabs.pack(side="left")
        self.delete_all_btn = delete_all_button(self.tabs_row, self.confirm_delete_all_media)
        self.delete_all_btn.pack(side="right")
        self.tabs_row.grid_remove()

        body = ctk.CTkFrame(detail, fg_color="transparent")
        body.grid(row=2, column=0, sticky="nsew")
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)
        self.media_list = ctk.CTkScrollableFrame(body, width=self.THUMB[0] + 30, corner_radius=12)
        self.media_list.grid(row=0, column=0, sticky="ns")

        self.image_view = ctk.CTkFrame(body, corner_radius=12)
        self.image_view.grid_columnconfigure(0, weight=1)
        self.image_view.grid_rowconfigure(0, weight=1)
        self.image_label = None
        self.image_caption = ctk.CTkLabel(self.image_view, text="", text_color=MUTED, wraplength=380)
        self.image_caption.grid(row=1, column=0, pady=(0, 12))
        self.reset_image(t("gallery.select"))
        self.player = VideoPlayer(body, t("recordings.select"))
        self.show_viewer()

    # -- users
    def refresh(self):
        self.tasks.run(self.app.api.admin_users, self.on_users)

    def on_users(self, users, error):
        for w in self.user_list.winfo_children():
            w.destroy()
        if error:
            ctk.CTkLabel(self.user_list, text=error_text(error), text_color=DANGER, wraplength=220).pack(pady=20)
            return
        self.users = users
        self.user_buttons = {}
        for user in users:
            me = t("admin.you") if user["id"] == self.app.api.user["id"] else ""
            role = t(f"admin.role_{user['role']}")
            if not user["active"]:
                role += f"  ·  ⏸ {t('admin.suspended')}"
            text = f"{user['username']} {me}\n{role}\n{t('admin.user_counts', images=user['images'], videos=user['videos'])}"
            btn = ctk.CTkButton(self.user_list, text=text, anchor="w", height=64, fg_color="transparent",
                                text_color=TEXT, hover_color=("gray80", "gray25"),
                                command=lambda u=user: self.select(u["id"]))
            btn.pack(fill="x", pady=2)
            self.user_buttons[user["id"]] = btn
        if self.select_after_refresh:
            username, self.select_after_refresh = self.select_after_refresh, None
            new = next((u for u in users if u["username"] == username), None)
            if new:
                self.select(new["id"])
                return
        if self.selected and any(u["id"] == self.selected["id"] for u in users):
            self.select(self.selected["id"], reload_media=False)
        elif self.selected:
            self.clear_detail()  # the selected account was deleted

    def select(self, user_id, reload_media=True):
        user = next(u for u in self.users if u["id"] == user_id)
        self.selected = user
        for uid, btn in self.user_buttons.items():
            btn.configure(fg_color=ACCENT if uid == user_id else "transparent",
                          text_color=("gray95", "gray95") if uid == user_id else TEXT)
        full_name = user.get("full_name")
        self.name_label.configure(text=f"{user['username']}  ·  {full_name}" if full_name else user["username"])
        role = t(f"admin.role_{user['role']}")
        if not user["active"]:
            role += f"  ·  ⏸ {t('admin.suspended')}"
        self.meta_label.configure(text_color=WARNING if not user["active"] else MUTED, text=(
            f"{role}  ·  {t('admin.joined', date=fmt_date(user['created_at'], with_time=False))}\n"
            f"{t('admin.last_login', date=fmt_date(user['last_login']))}  ·  {t('admin.storage', size=human_size(user['bytes']))}"
            + (f"\n{user['email']}" if user.get("email") else "")))
        is_admin = user["role"] == "admin"
        self.role_btn.configure(text=t("admin.remove_admin") if is_admin else t("admin.make_admin"),
                                fg_color=DANGER if is_admin else SUCCESS)
        self.status_btn.configure(text=t("admin.suspend") if user["active"] else t("admin.reactivate"),
                                  fg_color=WARNING if user["active"] else SUCCESS,
                                  hover_color=WARNING_DARK if user["active"] else SUCCESS_HOVER)
        # An admin cannot suspend or delete their own account
        is_me = user["id"] == self.app.api.user["id"]
        for btn in (self.edit_btn, self.role_btn, self.status_btn, self.delete_btn):
            btn.pack_forget()
        self.edit_btn.pack(side="left", padx=(0, 8))
        self.role_btn.pack(side="left")
        if not is_me:
            self.status_btn.pack(side="left", padx=(8, 0))
            self.delete_btn.pack(side="left", padx=(8, 0))
        self.actions.grid()
        if reload_media:
            self.load_media()

    def clear_detail(self):
        self.selected = None
        self.generation += 1
        self.name_label.configure(text=t("admin.select_user"))
        self.meta_label.configure(text="", text_color=MUTED)
        self.actions.grid_remove()
        self.tabs_row.grid_remove()
        self.player.show_message(t("recordings.select"))
        self.reset_image(t("gallery.select"))
        self.fill_list([], "")

    def confirm_status(self):
        user = self.selected
        active = not user["active"]
        key = "reactivate" if active else "suspend"
        ConfirmDialog(self, t(f"admin.confirm_{key}_title"), t(f"admin.confirm_{key}", user=user["username"]),
                      t(f"admin.{key}"), lambda: self.tasks.run(lambda: self.app.api.set_active(user["id"], active),
                                                                 self.on_role),
                      danger=not active)

    def confirm_delete(self):
        user = self.selected
        ConfirmDialog(self, t("admin.confirm_delete_title"), t("admin.confirm_delete", user=user["username"]),
                      t("admin.delete"), lambda: self.tasks.run(lambda: self.app.api.delete_user(user["id"]), self.on_role))

    def user_created(self, username):
        self.select_after_refresh = username
        self.refresh()

    def confirm_role(self):
        user = self.selected
        new_role = "user" if user["role"] == "admin" else "admin"
        message = t("admin.confirm_make_admin" if new_role == "admin" else "admin.confirm_remove_admin", user=user["username"])
        ConfirmDialog(self, t("admin.confirm_role_title"), message, t("admin.confirm_change"),
                      lambda: self.tasks.run(lambda: self.app.api.set_role(user["id"], new_role), self.on_role),
                      danger=new_role == "user")

    def on_role(self, _result, error):
        if error:
            self.meta_label.configure(text=error_text(error), text_color=DANGER)
            return
        self.meta_label.configure(text_color=MUTED)
        self.refresh()

    # -- media of the selected user
    def load_media(self):
        self.generation += 1
        generation = self.generation
        self.player.show_message(t("recordings.select"))
        self.reset_image(t("gallery.select"))
        self.fill_list([], t("admin.loading"))
        user_id = self.selected["id"]
        self.tasks.run(lambda: self.app.api.list_media(owner_id=user_id),
                       lambda items, error: self.on_media(items, error, generation))

    def on_media(self, items, error, generation):
        if generation != self.generation:
            return
        if error:
            self.fill_list([], error_text(error))
            return
        self.media = {"image": [m for m in items if m["kind"] == "image"],
                      "video": [m for m in items if m["kind"] == "video"]}
        self.kind_labels = {"image": t("admin.images_tab", count=len(self.media["image"])),
                            "video": t("admin.videos_tab", count=len(self.media["video"]))}
        self.kind_tabs.configure(values=list(self.kind_labels.values()))
        self.kind_tabs.set(self.kind_labels[self.kind])
        self.tabs_row.grid()
        self.show_kind()

    def on_kind(self, label):
        self.kind = next(k for k, v in self.kind_labels.items() if v == label)
        self.player.pause()
        self.show_kind()

    def show_viewer(self):
        if self.kind == "image":
            self.player.grid_forget()
            self.image_view.grid(row=0, column=1, sticky="nsew", padx=(12, 0))
        else:
            self.image_view.grid_forget()
            self.player.grid(row=0, column=1, sticky="nsew", padx=(12, 0))

    def show_kind(self):
        self.show_viewer()
        self.show_kind_count()
        items = self.media[self.kind]
        self.fill_list(items, t("admin.no_images" if self.kind == "image" else "admin.no_videos"))
        if items:
            (self.show_image if self.kind == "image" else self.play_video)(items[0])
        if self.kind == "image":
            self.load_thumbs(0, self.generation)

    def fill_list(self, items, empty_text):
        for w in self.media_list.winfo_children():
            w.destroy()
        self.media_buttons = []
        if not items:
            ctk.CTkLabel(self.media_list, text=empty_text, text_color=MUTED, wraplength=200).pack(pady=20)
            return
        for item in items:
            when = fmt_date(item["captured_at"])
            if item["kind"] == "image":
                prob = f"  ·  {item['probability']:.0f}%" if item.get("probability") else ""
                text, command = f"{when}{prob}", lambda m=item: self.show_image(m)
            else:
                duration = format_elapsed(item["duration"]) if item.get("duration") else "—"
                text, command = f"{when}\n{duration} · {human_size(item['size'])}", lambda m=item: self.play_video(m)
            self.media_buttons.append(media_item(self.media_list, text, command,
                                                 lambda m=item: self.confirm_delete_media(m)))

    def show_kind_count(self):
        self.delete_all_btn.configure(state="normal" if self.media[self.kind] else "disabled")

    def confirm_delete_media(self, item):
        key = "image" if item["kind"] == "image" else "video"
        ConfirmDialog(self, t(f"confirm.delete_{key}_title"), t(f"admin.confirm_delete_{key}", user=self.selected["username"]),
                      t("media.delete"), lambda: self.tasks.run(lambda: self.app.api.delete_media(item["id"]), self.media_deleted))

    def confirm_delete_all_media(self):
        user, kind = self.selected, self.kind
        ConfirmDialog(self, t(f"confirm.delete_all_{kind}_title"),
                      t(f"admin.confirm_delete_all_{kind}", count=len(self.media[kind]), user=user["username"]),
                      t("media.delete_all"),
                      lambda: self.tasks.run(lambda: self.app.api.delete_many(kind=kind, owner_id=user["id"]), self.media_deleted))

    def media_deleted(self, _result, error):
        if error:
            self.meta_label.configure(text=error_text(error), text_color=DANGER)
            return
        self.player.unload()
        self.refresh()      # counts in the user list
        self.load_media()   # this user's images / videos

    def load_thumbs(self, index, generation):
        """One thumbnail at a time, so a user with many images doesn't open dozens of connections."""
        items = self.media["image"]
        if generation != self.generation or self.kind != "image" or index >= len(items):
            return
        media_id = items[index]["id"]

        def done(data, error):
            if generation != self.generation or self.kind != "image" or index >= len(self.media_buttons):
                return
            if not error:
                img = Image.open(io.BytesIO(data))
                thumb = ctk.CTkImage(img, img, size=img.size)
                self.media_buttons[index].configure(image=thumb)
                self.media_buttons[index].image = thumb
            self.load_thumbs(index + 1, generation)

        self.tasks.run(lambda: self.app.api.thumbnail(media_id), done)

    def reset_image(self, text):
        if self.image_label is not None:
            self.image_label.destroy()
        self.image_label = ctk.CTkLabel(self.image_view, text=text, text_color=MUTED)
        self.image_label.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        self.image_caption.configure(text="")

    def show_image(self, item):
        generation = self.generation
        self.reset_image(t("admin.loading"))

        def done(data, error):
            if generation != self.generation:
                return
            if error:
                self.reset_image(error_text(error))
                return
            img = Image.open(io.BytesIO(data))
            photo = ctk.CTkImage(img, img, size=fit_size(img, self.image_label, upscale=False))
            self.image_label.configure(image=photo, text="")
            self.image_label.image = photo
            prob = t("admin.probability", prob=item["probability"]) if item.get("probability") else ""
            self.image_caption.configure(text="   ·   ".join(x for x in (fmt_date(item["captured_at"]), prob) if x))

        self.tasks.run(lambda: self.app.api.request("GET", f"/media/{item['id']}/file").content, done)

    def play_video(self, item):
        """Videos are downloaded once into a local cache, then played with the normal player."""
        os.makedirs(CACHE_DIR, exist_ok=True)
        path = os.path.join(CACHE_DIR, f"{item['id']}.mp4")
        caption = f"{item['owner']}  ·  {fmt_date(item['captured_at'])}"
        if os.path.exists(path) and os.path.getsize(path) == item["size"]:
            self.player.load(path, caption)
            return
        generation = self.generation
        progress = {"value": 0.0}
        self.player.show_message(t("admin.downloading", pct=0))

        def tick():
            if generation == self.generation and progress["value"] < 1:
                self.player.screen.configure(text=t("admin.downloading", pct=int(progress["value"] * 100)))
                self.after(200, tick)

        def done(_result, error):
            progress["value"] = 1
            if generation != self.generation:
                return
            if error:
                self.player.show_message(error_text(error))
            else:
                self.player.load(path, caption)

        self.tasks.run(lambda: self.app.api.download(item["id"], path, lambda f: progress.update(value=f)), done)
        tick()


class CreateUserDialog(ctk.CTkToplevel):
    """Modal form: username, password, role. Server errors are shown inside the form."""

    def __init__(self, users_view):
        super().__init__(users_view)
        self.view = users_view
        self.title(t("admin.create_title"))
        self.resizable(False, False)
        self.transient(users_view.winfo_toplevel())

        ctk.CTkLabel(self, text=t("admin.create_title"), font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=24, pady=(20, 12))
        self.username = ctk.CTkEntry(self, placeholder_text=t("login.username"), width=300, height=36)
        self.username.pack(padx=24, pady=4)
        self.password = ctk.CTkEntry(self, placeholder_text=t("login.password"), show="•", width=300, height=36)
        self.password.pack(padx=24, pady=4)
        add_reveal_button(self.password)

        role_row = ctk.CTkFrame(self, fg_color="transparent")
        role_row.pack(fill="x", padx=24, pady=(10, 0))
        ctk.CTkLabel(role_row, text=t("admin.role_label"), text_color=MUTED).pack(side="left")
        self.roles = {t("admin.role_user"): "user", t("admin.role_admin"): "admin"}
        self.role = ctk.CTkSegmentedButton(role_row, values=list(self.roles))
        self.role.set(t("admin.role_user"))
        self.role.pack(side="right")

        self.error = ctk.CTkLabel(self, text="", text_color=DANGER, wraplength=300)
        self.error.pack(padx=24, pady=(8, 0))
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(fill="x", padx=24, pady=(8, 20))
        self.create_btn = ctk.CTkButton(buttons, text=t("admin.create"), width=110, command=self.create)
        self.create_btn.pack(side="right")
        ctk.CTkButton(buttons, text=t("confirm.cancel"), width=110, command=self.destroy, fg_color="transparent",
                      border_width=1, text_color=TEXT).pack(side="right", padx=(0, 8))

        self.bind("<Escape>", lambda e: self.destroy())
        self.username.bind("<Return>", lambda e: self.password.focus())
        self.password.bind("<Return>", lambda e: self.create())

        self.update_idletasks()
        top = users_view.winfo_toplevel()
        x = top.winfo_rootx() + (top.winfo_width() - self.winfo_reqwidth()) // 2
        y = top.winfo_rooty() + (top.winfo_height() - self.winfo_reqheight()) // 2
        self.geometry(f"+{x}+{y}")
        self.after(250, lambda: self.iconbitmap(APP_ICON))  # CTkToplevel sets its own icon after ~200 ms
        self.after(10, self.grab_and_focus)

    def grab_and_focus(self):
        self.grab_set()
        self.username.focus_set()

    def create(self):
        username, password = self.username.get().strip(), self.password.get()
        if not username or not password:
            self.error.configure(text=t("api.missing_fields"))
            return
        role = self.roles[self.role.get()]
        self.create_btn.configure(state="disabled")
        self.view.tasks.run(lambda: self.view.app.api.create_user(username, password, role), self.done)

    def done(self, user, error):
        if not self.winfo_exists():
            return
        self.create_btn.configure(state="normal")
        if error:
            self.error.configure(text=error_text(error))
            return
        self.destroy()
        self.view.user_created(user["username"])


class EditUserDialog(ctk.CTkToplevel):
    """Admin edits someone's name / email, and can set a new password without knowing the old one."""

    def __init__(self, users_view, user):
        super().__init__(users_view)
        self.view = users_view
        self.user = user
        self.title(t("admin.edit_title", user=user["username"]))
        self.resizable(False, False)
        self.transient(users_view.winfo_toplevel())

        ctk.CTkLabel(self, text=t("admin.edit_title", user=user["username"]),
                     font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=24, pady=(20, 12))
        self.full_name = self.labeled_entry(t("profile.full_name"), user.get("full_name", ""))
        self.email = self.labeled_entry(t("profile.email"), user.get("email", ""))
        self.password = self.labeled_entry(t("admin.reset_password"), "", secret=True)

        self.error = ctk.CTkLabel(self, text="", text_color=DANGER, wraplength=300)
        self.error.pack(padx=24, pady=(8, 0))
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(fill="x", padx=24, pady=(8, 20))
        self.save_btn = ctk.CTkButton(buttons, text=t("admin.save"), width=110, command=self.save)
        self.save_btn.pack(side="right")
        ctk.CTkButton(buttons, text=t("confirm.cancel"), width=110, command=self.destroy, fg_color="transparent",
                      border_width=1, text_color=TEXT).pack(side="right", padx=(0, 8))
        self.bind("<Escape>", lambda e: self.destroy())

        self.update_idletasks()
        top = users_view.winfo_toplevel()
        x = top.winfo_rootx() + (top.winfo_width() - self.winfo_reqwidth()) // 2
        y = top.winfo_rooty() + (top.winfo_height() - self.winfo_reqheight()) // 2
        self.geometry(f"+{x}+{y}")
        self.after(250, lambda: self.iconbitmap(APP_ICON))  # CTkToplevel sets its own icon after ~200 ms
        self.after(10, self.grab_set)

    def labeled_entry(self, label, value, secret=False):
        ctk.CTkLabel(self, text=label, text_color=MUTED).pack(anchor="w", padx=24, pady=(6, 0))
        entry = ctk.CTkEntry(self, width=300, height=36, show="•" if secret else "")
        entry.pack(padx=24, pady=(2, 0))
        if value:
            entry.insert(0, value)
        if secret:
            add_reveal_button(entry)
        return entry

    def save(self):
        full_name, email, password = self.full_name.get(), self.email.get(), self.password.get()
        self.save_btn.configure(state="disabled")
        self.view.tasks.run(
            lambda: self.view.app.api.admin_update_profile(self.user["id"], full_name, email, password or None), self.done)

    def done(self, _user, error):
        if not self.winfo_exists():
            return
        self.save_btn.configure(state="normal")
        if error:
            self.error.configure(text=error_text(error))
            return
        self.destroy()
        self.view.refresh()
