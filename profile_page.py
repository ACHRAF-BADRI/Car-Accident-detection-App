"""My profile: name and email, and changing one's own password."""
import customtkinter as ctk

from admin_page import error_text, fmt_date
from i18n import t
from widgets import DANGER, MUTED, SUCCESS, BackgroundTasks, add_reveal_button, role_badge


class ProfilePage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.tasks = BackgroundTasks(self)
        user = app.api.user

        ctk.CTkLabel(self, text=t("nav.profile"), font=ctk.CTkFont(size=24, weight="bold")).pack(anchor="w", pady=(0, 12))
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        # Identity header
        head = ctk.CTkFrame(scroll, corner_radius=12)
        head.pack(fill="x")
        top = ctk.CTkFrame(head, fg_color="transparent")
        top.pack(anchor="w", padx=18, pady=(14, 0))
        self.display_name = ctk.CTkLabel(top, text="", font=ctk.CTkFont(size=20, weight="bold"))
        self.display_name.pack(side="left")
        if user["role"] == "admin":
            role_badge(top, t("admin.role_admin")).pack(side="left", padx=12)
        ctk.CTkLabel(head, text=f"@{user['username']}  ·  {t('profile.member_since', date=fmt_date(user['created_at'], with_time=False))}",
                     text_color=MUTED).pack(anchor="w", padx=18, pady=(0, 14))
        self.show_name()

        # Personal information
        ctk.CTkLabel(scroll, text=t("profile.info"), font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="w", pady=(20, 8))
        info = ctk.CTkFrame(scroll, corner_radius=12)
        info.pack(fill="x")
        info.grid_columnconfigure(1, weight=1)
        username = self.field(info, 0, t("profile.username"), t("profile.username_help"))
        username.insert(0, user["username"])
        username.configure(state="disabled")
        self.full_name = self.field(info, 1, t("profile.full_name"))
        self.full_name.insert(0, user.get("full_name", ""))
        self.email = self.field(info, 2, t("profile.email"))
        self.email.insert(0, user.get("email", ""))
        self.info_status, self.save_btn = self.action_row(info, 3, t("profile.save"), self.save_info)

        # Password
        ctk.CTkLabel(scroll, text=t("profile.password"), font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="w", pady=(20, 8))
        pw = ctk.CTkFrame(scroll, corner_radius=12)
        pw.pack(fill="x")
        pw.grid_columnconfigure(1, weight=1)
        self.current = self.field(pw, 0, t("profile.current_password"), secret=True)
        self.new = self.field(pw, 1, t("profile.new_password"), secret=True)
        self.confirm = self.field(pw, 2, t("profile.confirm_password"), secret=True)
        self.pw_status, self.pw_btn = self.action_row(pw, 3, t("profile.change_password"), self.save_password)

    # -- layout helpers
    def field(self, card, row, label, help_text=None, secret=False):
        box = ctk.CTkFrame(card, fg_color="transparent")
        box.grid(row=row, column=0, sticky="w", padx=18, pady=10)
        ctk.CTkLabel(box, text=label, font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w")
        if help_text:
            ctk.CTkLabel(box, text=help_text, text_color=MUTED, font=ctk.CTkFont(size=12)).pack(anchor="w")
        entry = ctk.CTkEntry(card, width=320, height=36, show="•" if secret else "")
        entry.grid(row=row, column=1, sticky="e", padx=18)
        if secret:
            add_reveal_button(entry)
        return entry

    def action_row(self, card, row, text, command):
        status = ctk.CTkLabel(card, text="", wraplength=360, justify="right")
        status.grid(row=row, column=0, columnspan=2, sticky="e", padx=(18, 170), pady=(4, 14))
        button = ctk.CTkButton(card, text=text, width=150, command=command)
        button.grid(row=row, column=1, sticky="e", padx=18, pady=(4, 14))
        return status, button

    def show_name(self):
        user = self.app.api.user
        self.display_name.configure(text=user.get("full_name") or user["username"])

    # -- actions
    def save_info(self):
        full_name, email = self.full_name.get(), self.email.get()
        self.save_btn.configure(state="disabled")
        self.info_status.configure(text="")
        self.tasks.run(lambda: self.app.api.update_profile(full_name, email), self.info_done)

    def info_done(self, _user, error):
        self.save_btn.configure(state="normal")
        if error:
            self.info_status.configure(text=error_text(error), text_color=DANGER)
            return
        self.info_status.configure(text=f"✓ {t('profile.saved')}", text_color=SUCCESS)
        for entry, key in ((self.full_name, "full_name"), (self.email, "email")):  # show what was stored
            entry.delete(0, "end")
            entry.insert(0, self.app.api.user.get(key, ""))
        self.show_name()
        self.app.main.show_identity()

    def save_password(self):
        current, new = self.current.get(), self.new.get()
        if not current or not new:
            self.pw_status.configure(text=t("api.missing_fields"), text_color=DANGER)
            return
        if new != self.confirm.get():
            self.pw_status.configure(text=t("api.password_mismatch"), text_color=DANGER)
            return
        self.pw_btn.configure(state="disabled")
        self.pw_status.configure(text="")
        self.tasks.run(lambda: self.app.api.change_password(current, new), self.password_done)

    def password_done(self, _result, error):
        self.pw_btn.configure(state="normal")
        if error:
            self.pw_status.configure(text=error_text(error), text_color=DANGER)
            return
        for entry in (self.current, self.new, self.confirm):
            entry.delete(0, "end")
        self.pw_status.configure(text=f"✓ {t('profile.password_changed')}", text_color=SUCCESS)
