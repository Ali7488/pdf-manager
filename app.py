"""SlideStitch: desktop dashboard to flatten, OCR and merge PDF/PowerPoint files."""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from converter import (
    ALLOWED,
    FLATTEN,
    FLATTEN_MERGE,
    MERGE,
    find_tesseract,
    process_files,
    safe_destination,
)

BG = "#1b141b"
SURFACE = "#2b1e29"
CARD = "#352431"
CARD_HOVER = "#422b39"
CARD_ACTIVE = "#4b2c3d"
BORDER = "#694557"
PINK = "#c96789"
PINK_HOVER = "#df789b"
PINK_PRESSED = "#9b4465"
TEXT = "#fff7fa"
MUTED = "#d0bbc6"
LOW = "#a58b9a"
SUCCESS = "#95d3b4"
WARNING = "#f1c381"
FONT = "Segoe UI"
APP_NAME = "SlideStitch"
APP_DIR = Path(__file__).resolve().parent
ICON_PATH = APP_DIR / f"{APP_NAME}.ico"
CONF_DIR = Path(os.getenv("LOCALAPPDATA", Path.home())) / "SlideStitch"
CONF_PATH = CONF_DIR / "settings.json"


def _rounded(
    canvas: tk.Canvas, width: int, height: int, radius: int, color: str, border: str | None = None
):
    """Draw a rounded pill using native Tk polygons; no third-party GUI library."""
    x, y = 2, 2
    r = min(radius, (height - 4) / 2)
    points = [
        x + r,
        y,
        width - x - r,
        y,
        width - x,
        y,
        width - x,
        y + r,
        width - x,
        height - y - r,
        width - x,
        height - y,
        width - x - r,
        height - y,
        x + r,
        height - y,
        x,
        height - y,
        x,
        height - y - r,
        x,
        y + r,
        x,
        y,
    ]
    canvas.create_polygon(
        points,
        fill=color,
        outline=border or color,
        width=1 if border else 0,
        smooth=True,
        splinesteps=18,
    )


class SoftButton(tk.Canvas):
    def __init__(
        self, master, title: str, command, width=150, height=42, tone="secondary", enabled=True
    ):
        super().__init__(
            master,
            width=width,
            height=height,
            bg=master.cget("bg"),
            highlightthickness=0,
            bd=0,
            takefocus=1,
            cursor="hand2" if enabled else "arrow",
        )
        self.label, self.command, self.w, self.h = title, command, width, height
        self.tone, self.enabled, self.hover, self.pressed = tone, enabled, False, False
        self.render()
        self.bind("<Enter>", self.on_enter)
        self.bind("<Leave>", self.on_leave)
        self.bind("<Button-1>", self.on_press)
        self.bind("<ButtonRelease-1>", self.on_release)
        self.bind("<Return>", lambda event: self.perform())
        self.bind("<space>", lambda event: self.perform())
        self.bind("<FocusIn>", lambda event: self.render())
        self.bind("<FocusOut>", lambda event: self.render())

    def render(self):
        self.delete("all")
        if not self.enabled:
            bg, fg, border = "#44333d", "#887784", "#493541"
        elif self.tone == "primary":
            bg = PINK_PRESSED if self.pressed else PINK_HOVER if self.hover else PINK
            fg, border = TEXT, bg
        elif self.tone == "danger":
            bg = "#6a3047" if self.hover else "#502c3b"
            fg, border = TEXT, "#80435c"
        else:
            bg = CARD_HOVER if self.hover else CARD
            fg, border = TEXT, BORDER
        _rounded(self, self.w, self.h, 14, bg, border)
        self.create_text(self.w / 2, self.h / 2, text=self.label, fill=fg, font=(FONT, 10, "bold"))

    def set_enabled(self, value):
        self.enabled = bool(value)
        self.configure(cursor="hand2" if self.enabled else "arrow")
        self.render()

    def on_enter(self, event):
        self.hover = True
        self.render()

    def on_leave(self, event):
        self.hover = False
        self.pressed = False
        self.render()

    def on_press(self, event):
        if self.enabled:
            self.focus_set()
            self.pressed = True
            self.render()

    def on_release(self, event):
        if self.pressed and self.enabled:
            self.pressed = False
            self.render()
            if 0 <= event.x <= self.w and 0 <= event.y <= self.h:
                self.perform()

    def perform(self):
        if self.enabled and self.command:
            self.command()


class ModeCard(tk.Canvas):
    def __init__(self, master, title: str, subtitle: str, mode: str, selected, callback):
        super().__init__(
            master,
            width=217,
            height=84,
            bg=master.cget("bg"),
            highlightthickness=0,
            bd=0,
            takefocus=1,
            cursor="hand2",
        )
        self.title, self.subtitle, self.mode = title, subtitle, mode
        self.is_selected, self.callback, self.hover = selected, callback, False
        self.paint()
        self.bind("<Enter>", lambda event: self.hovered(True))
        self.bind("<Leave>", lambda event: self.hovered(False))
        self.bind("<Button-1>", lambda event: self.callback(self.mode))
        self.bind("<Return>", lambda event: self.callback(self.mode))
        self.bind("<space>", lambda event: self.callback(self.mode))

    def hovered(self, state):
        self.hover = state
        self.paint()

    def paint(self):
        self.delete("all")
        active = self.is_selected
        background = CARD_ACTIVE if active else CARD_HOVER if self.hover else CARD
        _rounded(self, 217, 84, 16, background, PINK if active else BORDER)
        self.create_text(17, 22, anchor="w", text=self.title, fill=TEXT, font=(FONT, 11, "bold"))
        self.create_text(17, 55, anchor="w", text=self.subtitle, fill=MUTED, font=(FONT, 8))
        self.create_oval(
            183,
            13,
            199,
            29,
            outline=PINK if active else LOW,
            fill=PINK if active else background,
            width=2,
        )
        if active:
            self.create_oval(188, 18, 194, 24, fill=TEXT, outline=TEXT)


class Dashboard:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.geometry("735x540")
        self.root.minsize(710, 545)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        if ICON_PATH.is_file():
            try:
                self.root.iconbitmap(str(ICON_PATH))
            except tk.TclError:
                pass
        self.files: list[Path] = []
        self.mode = FLATTEN
        self.cards: dict[str, ModeCard] = {}
        self.events: queue.Queue = queue.Queue()
        self.busy = False
        self.temp: tempfile.TemporaryDirectory | None = None
        self.config = self.load_config()
        self.ocr_path = self.config.get("tesseract_path")
        self.status = tk.StringVar(value="Select your files, choose an option, then create PDFs.")
        self.engine_text = tk.StringVar()
        self.layout()
        self.refresh_engine()
        self.root.after(100, self.poll)

    @staticmethod
    def load_config():
        try:
            return json.loads(CONF_PATH.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {}

    def save_config(self):
        CONF_DIR.mkdir(parents=True, exist_ok=True)
        CONF_PATH.write_text(json.dumps(self.config, indent=2), encoding="utf-8")

    def layout(self):
        wrapper = tk.Frame(self.root, bg=BG)
        wrapper.pack(fill="both", expand=True, padx=21, pady=(12, 9))

        heading = tk.Frame(wrapper, bg=BG)
        heading.pack(fill="x")
        tk.Label(heading, text=APP_NAME, bg=BG, fg=TEXT, font=(FONT, 21, "bold")).pack(
            anchor="w"
        )
        tk.Label(
            heading,
            text="Flatten, OCR and merge PDFs and PowerPoints",
            bg=BG,
            fg=MUTED,
            font=(FONT, 10),
        ).pack(anchor="w", pady=(2, 0))

        self._section(wrapper, "CHOOSE AN ACTION", top=11)
        modes = tk.Frame(wrapper, bg=BG)
        modes.pack(fill="x")
        rows = (
            (FLATTEN, "Flatten", "Separate searchable PDFs"),
            (FLATTEN_MERGE, "Flatten + Merge", "One searchable PDF"),
            (MERGE, "Merge", "Keep original PDF text"),
        )
        for i, (value, title, explanation) in enumerate(rows):
            card = ModeCard(modes, title, explanation, value, value == self.mode, self.change_mode)
            card.grid(row=0, column=i, padx=(0, 13 if i < 2 else 0), sticky="w")
            self.cards[value] = card

        self._section(wrapper, "FILES", top=9)
        file_row = tk.Frame(wrapper, bg=BG)
        file_row.pack(fill="x", pady=(0, 8))
        SoftButton(file_row, "+ Add files", self.add_files, 128, 39, "primary").pack(side="left")
        SoftButton(file_row, "Remove", self.remove_selected, 97, 39).pack(side="left", padx=7)
        SoftButton(file_row, "Clear all", self.clear_files, 98, 39).pack(side="left")
        tk.Label(file_row, text="PDF · PPTX · PPT", fg=LOW, bg=BG, font=(FONT, 9)).pack(
            side="right", padx=6
        )

        file_pane = tk.Frame(wrapper, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
        file_pane.pack(fill="both", expand=True)
        self.listbox = tk.Listbox(
            file_pane,
            font=(FONT, 10),
            height=4,
            bg=SURFACE,
            fg=TEXT,
            selectbackground=CARD_ACTIVE,
            selectforeground=TEXT,
            highlightthickness=0,
            relief="flat",
            borderwidth=0,
            activestyle="none",
            exportselection=False,
        )
        self.listbox.pack(side="left", fill="both", expand=True, padx=(12, 4), pady=7)
        controls = tk.Frame(file_pane, bg=SURFACE)
        controls.pack(side="right", padx=8, pady=13)
        SoftButton(controls, "Move up", lambda: self.move(-1), 94, 34).pack(pady=(0, 5))
        SoftButton(controls, "Move down", lambda: self.move(1), 94, 34).pack()

        tk.Label(
            wrapper,
            text="Speaker notes are included automatically for PowerPoints. "
            "Use Move up/down to choose the merge order.",
            bg=BG,
            fg=MUTED,
            font=(FONT, 9),
            wraplength=690,
            anchor="w",
            justify="left",
        ).pack(fill="x", pady=(5, 2))

        separator = tk.Frame(wrapper, bg=BORDER, height=1)
        separator.pack(fill="x", pady=(4, 7))

        bottom = tk.Frame(wrapper, bg=BG)
        bottom.pack(fill="x")
        self.convert = SoftButton(
            bottom, "Create PDF(s)", self.begin, 190, 49, "primary", enabled=False
        )
        self.convert.pack(side="left")
        engine_row = tk.Frame(bottom, bg=BG)
        engine_row.pack(side="right", fill="y")
        tk.Label(engine_row, textvariable=self.engine_text, bg=BG, fg=LOW, font=(FONT, 9)).pack(
            anchor="e"
        )
        engine_buttons = tk.Frame(engine_row, bg=BG)
        engine_buttons.pack(anchor="e", pady=(1, 0))
        SoftButton(engine_buttons, "Find OCR", self.locate_ocr, 91, 30).pack(
            side="left", padx=(0, 5)
        )
        self.install = SoftButton(engine_buttons, "Install OCR", self.install_ocr, 100, 30)
        self.install.pack(side="left")

        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "App.Horizontal.TProgressbar",
            troughcolor=SURFACE,
            background=PINK,
            bordercolor=SURFACE,
            lightcolor=PINK,
            darkcolor=PINK,
        )
        self.progress = ttk.Progressbar(
            wrapper, style="App.Horizontal.TProgressbar", mode="determinate"
        )
        self.progress.pack(fill="x", pady=(7, 3))
        tk.Label(
            wrapper,
            textvariable=self.status,
            bg=BG,
            fg=MUTED,
            font=(FONT, 9),
            anchor="w",
            justify="left",
            wraplength=680,
        ).pack(fill="x")
        tk.Label(
            wrapper,
            text="Choose the save folder after processing. Originals stay untouched.",
            bg=BG,
            fg=LOW,
            font=(FONT, 9),
            anchor="w",
        ).pack(fill="x", pady=(2, 0))

    def _section(self, master, title: str, top: int = 12):
        tk.Label(master, text=title, fg=PINK_HOVER, bg=BG, font=(FONT, 9, "bold")).pack(
            anchor="w", pady=(top, 5)
        )

    def refresh_engine(self):
        engine = find_tesseract(self.ocr_path)
        self.engine_text.set("OCR ready" if engine else "OCR not found")
        self.install.set_enabled(engine is None and not self.busy)
        if engine:
            self.ocr_path = str(engine)

    def change_mode(self, value: str):
        if self.busy:
            return
        self.mode = value
        for code, card in self.cards.items():
            card.is_selected = code == value
            card.paint()
        self.refresh_engine()
        self.status.set(
            {
                FLATTEN: "One searchable PDF for each selected file.",
                FLATTEN_MERGE: "Flatten all files and combine in the displayed order.",
                MERGE: "Combine files without flattening the original PDFs. OCR not needed.",
            }[value]
        )

    def add_files(self):
        if self.busy:
            return
        chosen = filedialog.askopenfilenames(
            parent=self.root,
            title="Choose PDFs or PowerPoints",
            filetypes=[("PDF and PowerPoint files", "*.pdf *.pptx *.ppt"), ("All files", "*.*")],
        )
        if not chosen:
            return
        prior = {str(item).casefold() for item in self.files}
        for item in chosen:
            p = Path(item)
            if p.suffix.lower() in ALLOWED and str(p).casefold() not in prior:
                self.files.append(p)
                prior.add(str(p).casefold())
        self.draw_list()

    def draw_list(self, select: int | None = None):
        self.listbox.delete(0, tk.END)
        for index, file in enumerate(self.files, 1):
            self.listbox.insert(tk.END, f"{index:02d}   {file.name}")
        if select is not None and self.files:
            select = min(max(select, 0), len(self.files) - 1)
            self.listbox.selection_set(select)
            self.listbox.see(select)
        self.convert.set_enabled(bool(self.files) and not self.busy)

    def remove_selected(self):
        if self.busy:
            return
        indices = self.listbox.curselection()
        if indices:
            for index in sorted(indices, reverse=True):
                del self.files[index]
            self.draw_list()

    def clear_files(self):
        if not self.busy:
            self.files.clear()
            self.draw_list()

    def move(self, offset: int):
        if self.busy:
            return
        indices = self.listbox.curselection()
        if not indices:
            return
        idx = indices[0]
        new = idx + offset
        if not 0 <= new < len(self.files):
            return
        self.files[idx], self.files[new] = self.files[new], self.files[idx]
        self.draw_list(select=new)

    def locate_ocr(self):
        if self.busy:
            return
        path = filedialog.askopenfilename(
            parent=self.root,
            title="Find Tesseract OCR (tesseract.exe)",
            filetypes=[("Tesseract OCR", "tesseract.exe"), ("Applications", "*.exe")],
        )
        if not path:
            return
        candidate = Path(path)
        if candidate.name.casefold() != "tesseract.exe" or not candidate.is_file():
            messagebox.showerror(
                "Wrong program", "Select a file named tesseract.exe.", parent=self.root
            )
            return
        self.ocr_path = str(candidate)
        self.config["tesseract_path"] = self.ocr_path
        try:
            self.save_config()
        except OSError as exc:
            messagebox.showwarning(
                "Settings", f"OCR selected but not saved: {exc}", parent=self.root
            )
        self.refresh_engine()
        messagebox.showinfo(
            "OCR ready", "English OCR engine found. You can flatten PDFs now.", parent=self.root
        )

    def install_ocr(self):
        if self.busy:
            return
        if os.name != "nt" or shutil.which("winget") is None:
            webbrowser.open("https://github.com/UB-Mannheim/tesseract/wiki")
            messagebox.showinfo(
                "Install OCR",
                "The Tesseract installer page has opened. "
                "After installation, use 'Find OCR' if it isn't detected automatically.",
                parent=self.root,
            )
            return
        if not messagebox.askyesno(
            "Install OCR",
            "Install free Tesseract OCR with Windows Package Manager?\n\n"
            "Windows may request permission. The install runs locally on this computer.",
            parent=self.root,
        ):
            return
        self.set_busy(True)
        self.status.set("Installing Tesseract OCR. Windows may ask for permission...")
        threading.Thread(target=self.ocr_worker, daemon=True).start()

    def ocr_worker(self):
        try:
            options = {"capture_output": True, "text": True, "timeout": 1200}
            if os.name == "nt":
                options["creationflags"] = subprocess.CREATE_NO_WINDOW
            p = subprocess.run(
                [
                    "winget",
                    "install",
                    "--id",
                    "UB-Mannheim.TesseractOCR",
                    "-e",
                    "--silent",
                    "--accept-source-agreements",
                    "--accept-package-agreements",
                ],
                **options,
            )
            if p.returncode:
                self.events.put(
                    (
                        "ocr_done",
                        False,
                        (p.stderr or p.stdout or "Unknown installation error")[-700:],
                    )
                )
            else:
                self.events.put(("ocr_done", True, ""))
        except Exception as exc:
            self.events.put(("ocr_done", False, str(exc)))

    def set_busy(self, active: bool):
        self.busy = active
        self.convert.set_enabled(bool(self.files) and not active)
        self.install.set_enabled(not active and find_tesseract(self.ocr_path) is None)
        if active:
            self.progress.configure(mode="indeterminate")
            self.progress.start(11)
        else:
            self.progress.stop()
            self.progress.configure(mode="determinate", value=0)

    def begin(self):
        if self.busy or not self.files:
            return
        if self.mode != MERGE and not find_tesseract(self.ocr_path):
            messagebox.showerror(
                "OCR needed",
                "Flattening needs Tesseract OCR.\n\n"
                "Click 'Install OCR' to install it, or 'Find OCR' if already installed.",
                parent=self.root,
            )
            return
        current = list(self.files)
        missing = [str(path) for path in current if not path.is_file()]
        if missing:
            messagebox.showerror(
                "Missing input", "The following file is missing:\n" + missing[0], parent=self.root
            )
            return
        # Antivirus/PDF renderer locks can linger briefly on Windows.
        # Cleanup is best effort: never turn a successful conversion into a
        # failure just because one scratch file is temporarily locked.
        self.temp = tempfile.TemporaryDirectory(
            prefix="slidestitch-", ignore_cleanup_errors=True
        )
        self.set_busy(True)
        self.status.set("Converting files. Keep this window open...")
        threading.Thread(
            target=self.worker,
            args=(current, self.mode, Path(self.temp.name), self.ocr_path),
            daemon=True,
        ).start()

    def worker(self, files, mode, scratch, engine):
        try:
            results = process_files(
                files, mode, scratch, lambda msg: self.events.put(("status", msg)), engine=engine
            )
            self.events.put(("complete", results, None))
        except Exception as exc:
            self.events.put(("complete", None, str(exc)))

    def poll(self):
        try:
            while True:
                event, *payload = self.events.get_nowait()
                if event == "status":
                    self.status.set(payload[0])
                elif event == "ocr_done":
                    ok, error = payload
                    self.set_busy(False)
                    self.refresh_engine()
                    if ok and find_tesseract(self.ocr_path):
                        self.status.set("OCR installed and ready.")
                        messagebox.showinfo(
                            "OCR installed", "Tesseract OCR is ready!", parent=self.root
                        )
                    else:
                        self.status.set("OCR installation needs attention.")
                        messagebox.showwarning(
                            "OCR setup",
                            "Automatic installation could not be verified.\n\n"
                            + (
                                error
                                or "Try 'Find OCR' and select tesseract.exe, or restart the app."
                            )[:500],
                            parent=self.root,
                        )
                elif event == "complete":
                    self.complete(*payload)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def complete(self, results, error):
        try:
            if error is not None:
                self.status.set("Conversion failed. Original files were not changed.")
                messagebox.showerror("Conversion failed", error, parent=self.root)
                return
            self.status.set("Conversion finished. Choose the save folder now.")
            folder = filedialog.askdirectory(
                parent=self.root, title="Choose where to save the PDF(s)", mustexist=True
            )
            if not folder:
                self.status.set("Save canceled. Originals are unchanged. Convert again when ready.")
                return
            taken: set[str] = set()
            saved = []
            for name, generated in results:
                target = safe_destination(Path(folder), name, taken)
                shutil.copy2(generated, target)
                saved.append(target)
            self.status.set(f"Saved {len(saved)} PDF(s) in {folder}")
            messagebox.showinfo(
                "Finished!", f"Saved {len(saved)} PDF(s) to:\n{folder}", parent=self.root
            )
        except Exception as exc:
            self.status.set("Could not save all the PDFs.")
            messagebox.showerror(
                "Save failed",
                f"The destination folder could not be written to:\n{exc}",
                parent=self.root,
            )
        finally:
            try:
                if self.temp:
                    self.temp.cleanup()
            except OSError:
                # Scratch is inside the Windows Temp directory; output was
                # already copied to the folder the user selected.
                pass
            finally:
                self.temp = None
                self.set_busy(False)
                self.refresh_engine()

    def close(self):
        if self.busy:
            messagebox.showwarning(
                "Operation in progress",
                "Close the application after the current task finishes.",
                parent=self.root,
            )
            return
        self.root.destroy()


if __name__ == "__main__":
    Dashboard().root.mainloop()
