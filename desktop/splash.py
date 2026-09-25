"""Loading screen shown the instant the app is launched.

Loading TensorFlow, OpenCV and the rest takes several seconds before the main window can exist.
This window only needs plain tkinter (fast to import), so it appears immediately and animates
while the heavy modules are imported in a background thread.
"""
import json
import math
import tkinter as tk

BG = "#0f1629"
CARD = "#141d33"
TEXT = "#e8ecf6"
MUTED = "#8b97b5"
ARC_COLORS = ("#3b82f6", "#8b5cf6")
from desktop.paths import APP_LOGO as LOGO, SETTINGS_FILE
MESSAGES = {
    "fr": ("Détection d'accidents", ["Chargement des modules…", "Préparation de la détection…", "Ouverture de l'interface…"]),
    "en": ("Accident detection", ["Loading modules…", "Preparing detection…", "Opening the interface…"]),
}


def interface_language():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            return json.load(f).get("language", "en")
    except (OSError, ValueError):
        return "en"


class Splash:
    WIDTH, HEIGHT = 420, 300

    def __init__(self):
        subtitle, self.steps = MESSAGES.get(interface_language(), MESSAGES["en"])
        self.root = tk.Tk()
        self.root.overrideredirect(True)  # no title bar: a clean card
        self.root.configure(bg=BG)
        self.root.attributes("-topmost", True)
        x = (self.root.winfo_screenwidth() - self.WIDTH) // 2
        y = (self.root.winfo_screenheight() - self.HEIGHT) // 2
        self.root.geometry(f"{self.WIDTH}x{self.HEIGHT}+{x}+{y}")

        c = self.canvas = tk.Canvas(self.root, width=self.WIDTH, height=self.HEIGHT, bg=BG, highlightthickness=1,
                                    highlightbackground="#26314f")
        c.pack()
        try:
            logo = tk.PhotoImage(file=LOGO)
            self.logo = logo.subsample(max(1, logo.width() // 76))  # keep a reference, ~76 px
            c.create_image(self.WIDTH // 2, 78, image=self.logo)
        except tk.TclError:
            pass
        c.create_text(self.WIDTH // 2, 146, text="AccidentAI", fill=TEXT, font=("Segoe UI", 20, "bold"))
        c.create_text(self.WIDTH // 2, 174, text=subtitle, fill=MUTED, font=("Segoe UI", 10))

        # Spinner: two arcs turning in opposite directions
        cx, cy, r = self.WIDTH // 2, 222, 19
        self.arcs = [c.create_arc(cx - r, cy - r, cx + r, cy + r, start=0, extent=100, style="arc",
                                  outline=ARC_COLORS[0], width=4),
                     c.create_arc(cx - r + 8, cy - r + 8, cx + r - 8, cy + r - 8, start=180, extent=100, style="arc",
                                  outline=ARC_COLORS[1], width=4)]
        self.status = c.create_text(self.WIDTH // 2, 266, text=self.steps[0], fill=MUTED, font=("Segoe UI", 9))
        self.angle = 0
        self.ticks = 0
        self.root.update()

    def _animate(self):
        self.angle = (self.angle + 9) % 360
        extent = 100 + 60 * math.sin(math.radians(self.angle * 2))  # arcs breathe while turning
        self.canvas.itemconfigure(self.arcs[0], start=self.angle, extent=extent)
        self.canvas.itemconfigure(self.arcs[1], start=-self.angle * 1.5, extent=extent)
        self.ticks += 1
        if self.ticks % 70 == 0:  # next message every ~1.4 s
            step = min(self.ticks // 70, len(self.steps) - 1)
            self.canvas.itemconfigure(self.status, text=self.steps[step])

    def run_until(self, done):
        """Animate until done() returns True, then close the window."""
        def tick():
            if done():
                self.root.quit()
                return
            self._animate()
            self.root.after(20, tick)
        tick()
        self.root.mainloop()
        self.root.destroy()
