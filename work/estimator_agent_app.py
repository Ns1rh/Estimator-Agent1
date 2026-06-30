from __future__ import annotations

import os
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

try:
    from PIL import Image, ImageTk
except Exception:  # pragma: no cover - Tkinter fallback for minimal installs
    Image = None  # type: ignore[assignment]
    ImageTk = None  # type: ignore[assignment]


APP_TITLE = "New Age Electric Estimator Assistant"
COMPANY_NAME = "New Age Electric LLC"
SUBHEADER = "First-pass electrical takeoff review assistant"
LOCATION = "Burbank, CA"
FIRST_PASS_NOTE = "This is first-pass estimator review output, not final bid output."

ROOT = Path(__file__).resolve().parents[1]
WORK_DIR = ROOT / "work"
DOCS_DIR = ROOT / "docs"
CLI = WORK_DIR / "estimating_agent_cli.py"
CREATE_DEMO = WORK_DIR / "create_demo_project.py"
CHECK_OUTPUTS = WORK_DIR / "check_demo_outputs.py"
DEMO_CHECKLIST = DOCS_DIR / "FINAL_DEMO_CHECKLIST.md"

REQUIRED_OUTPUTS = [
    "project_dashboard.md",
    "takeoff_items.csv",
    "estimator_review.csv",
    "accubid_mapping.csv",
    "marked_up_drawings.pdf",
    "validation_answer_key_template.csv",
]


def safe_name(value: str) -> str:
    name = Path(value).stem if value else "estimator-package"
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._-")
    return name or "estimator-package"


def open_path(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(path)
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class EstimatorAgentApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1180x820")
        self.minsize(1040, 720)

        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.project_name_var = tk.StringVar()
        self.answer_key_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Ready")
        self.progress_var = tk.StringVar(value="Select a project folder or PDF to begin.")
        self.elapsed_var = tk.StringVar(value="Elapsed: 00:00")
        self.command_running = False
        self.started_at: float | None = None
        self.log_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.output_status_labels: dict[str, ttk.Label] = {}
        self.output_buttons: dict[str, ttk.Button] = {}
        self.validation_buttons: list[ttk.Button] = []
        self.logo_image: tk.PhotoImage | None = None

        self._configure_style()
        self._build_ui()
        self.after(100, self._process_log_queue)
        self.after(500, self._tick_elapsed)
        self.refresh_output_status()

    def _configure_style(self) -> None:
        self.configure(bg="#e9eef4")
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("App.TFrame", background="#e9eef4")
        style.configure("Header.TFrame", background="#172536")
        style.configure("HeaderTitle.TLabel", background="#172536", foreground="#ffffff", font=("Segoe UI", 18, "bold"))
        style.configure("HeaderSub.TLabel", background="#172536", foreground="#d7e2ee", font=("Segoe UI", 11))
        style.configure("Logo.TLabel", background="#ffffff", foreground="#172536", font=("Segoe UI", 13, "bold"), padding=(12, 8))
        style.configure("Card.TFrame", background="#ffffff", relief="flat")
        style.configure("CardTitle.TLabel", background="#ffffff", foreground="#172536", font=("Segoe UI", 12, "bold"))
        style.configure("Body.TLabel", background="#ffffff", foreground="#253041", font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background="#ffffff", foreground="#6d7886", font=("Segoe UI", 9))
        style.configure("Info.TLabel", background="#fff7e0", foreground="#5a4214", font=("Segoe UI", 10), padding=(10, 8))
        style.configure("StatusReady.TLabel", background="#dbe7f3", foreground="#1f4b77", font=("Segoe UI", 10, "bold"), padding=(10, 4))
        style.configure("StatusRunning.TLabel", background="#fff0cc", foreground="#7a4b00", font=("Segoe UI", 10, "bold"), padding=(10, 4))
        style.configure("StatusCompleted.TLabel", background="#dff3e5", foreground="#1f6b3a", font=("Segoe UI", 10, "bold"), padding=(10, 4))
        style.configure("StatusFailed.TLabel", background="#fde2dd", foreground="#9b2f1f", font=("Segoe UI", 10, "bold"), padding=(10, 4))
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"), padding=(10, 6))
        style.configure("TButton", font=("Segoe UI", 9), padding=(8, 5))
        style.configure("TEntry", padding=(6, 4))

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = ttk.Frame(self, style="Header.TFrame", padding=(22, 16))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)

        logo_widget = self._logo_widget(header)
        logo_widget.grid(row=0, column=0, rowspan=3, sticky="w", padx=(0, 22))
        ttk.Label(header, text="Estimator Assistant", style="HeaderTitle.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Label(header, text=SUBHEADER, style="HeaderSub.TLabel").grid(row=1, column=1, sticky="w", pady=(3, 0))
        ttk.Label(header, text=LOCATION, style="HeaderSub.TLabel").grid(row=2, column=1, sticky="w", pady=(3, 0))

        main = ttk.Frame(self, style="App.TFrame", padding=(18, 16))
        main.grid(row=1, column=0, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(1, weight=1)

        ttk.Label(main, text=FIRST_PASS_NOTE, style="Info.TLabel").grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))

        left = ttk.Frame(main, style="App.TFrame")
        right = ttk.Frame(main, style="App.TFrame")
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 9))
        right.grid(row=1, column=1, sticky="nsew", padx=(9, 0))
        left.columnconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        self._build_project_input(left).grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self._build_package_section(left).grid(row=1, column=0, sticky="ew", pady=(0, 12))
        self._build_validation_section(left).grid(row=2, column=0, sticky="ew", pady=(0, 12))
        self._build_demo_section(left).grid(row=3, column=0, sticky="ew")

        self._build_status_section(right).grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self._build_log_section(right).grid(row=1, column=0, sticky="nsew")

    def _logo_widget(self, parent: ttk.Frame) -> ttk.Label:
        for logo_path in [
            ROOT / "assets" / "branding" / "new_age_electric_logo.png",
            WORK_DIR / "assets" / "branding" / "new_age_electric_logo.png",
        ]:
            if logo_path.exists():
                try:
                    image = self._load_logo_image(logo_path, max_width=320, max_height=112)
                    self.logo_image = image
                    return ttk.Label(parent, image=self.logo_image, style="Logo.TLabel", anchor="center")
                except tk.TclError:
                    break
        return ttk.Label(parent, text="NEW AGE\nELECTRIC LLC", style="Logo.TLabel", anchor="center", justify="center")

    def _load_logo_image(self, logo_path: Path, max_width: int, max_height: int) -> tk.PhotoImage:
        """Load the approved local logo with smooth scaling.

        Tk's native PhotoImage.subsample only scales by whole numbers, which
        makes letter-heavy logos look jagged. Pillow is already used by the
        estimator for drawing markup, so use it here when available.
        """
        if Image is not None and ImageTk is not None:
            source = Image.open(logo_path).convert("RGBA")
            source.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
            return ImageTk.PhotoImage(source)

        image = tk.PhotoImage(file=str(logo_path))
        while image.width() > max_width or image.height() > max_height:
            image = image.subsample(2, 2)
        return image

    def _card(self, parent: ttk.Frame, title: str) -> ttk.Frame:
        outer = ttk.Frame(parent, style="Card.TFrame", padding=(14, 12))
        outer.columnconfigure(0, weight=1)
        ttk.Label(outer, text=title, style="CardTitle.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 8))
        return outer

    def _build_project_input(self, parent: ttk.Frame) -> ttk.Frame:
        card = self._card(parent, "1. Project Input")
        card.columnconfigure(1, weight=1)

        ttk.Label(card, text="Project folder or PDF", style="Body.TLabel").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(card, textvariable=self.input_var).grid(row=1, column=1, columnspan=2, sticky="ew", padx=(10, 6))
        ttk.Button(card, text="Browse Folder", command=self.browse_input_folder).grid(row=1, column=3, padx=(0, 6))
        ttk.Button(card, text="Browse PDF", command=self.browse_input_pdf).grid(row=1, column=4)

        ttk.Label(card, text="Output folder", style="Body.TLabel").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Entry(card, textvariable=self.output_var).grid(row=2, column=1, columnspan=3, sticky="ew", padx=(10, 6))
        ttk.Button(card, text="Browse", command=self.browse_output_folder).grid(row=2, column=4)

        ttk.Label(card, text="Project name (optional)", style="Body.TLabel").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Entry(card, textvariable=self.project_name_var).grid(row=3, column=1, columnspan=4, sticky="ew", padx=(10, 0))

        run_button = ttk.Button(card, text="Run Estimate", style="Accent.TButton", command=self.run_estimate)
        run_button.grid(row=4, column=0, columnspan=5, sticky="ew", pady=(12, 0))
        return card

    def _build_status_section(self, parent: ttk.Frame) -> ttk.Frame:
        card = self._card(parent, "2. Run Status")
        card.columnconfigure(1, weight=1)
        self.status_badge = ttk.Label(card, textvariable=self.status_var, style="StatusReady.TLabel")
        self.status_badge.grid(row=1, column=0, sticky="w")
        ttk.Label(card, textvariable=self.elapsed_var, style="Muted.TLabel").grid(row=1, column=1, sticky="e")
        ttk.Label(card, textvariable=self.progress_var, style="Body.TLabel", wraplength=520).grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        return card

    def _build_log_section(self, parent: ttk.Frame) -> ttk.Frame:
        card = self._card(parent, "Live Log")
        card.rowconfigure(1, weight=1)
        card.columnconfigure(0, weight=1)
        self.log_text = tk.Text(
            card,
            height=22,
            wrap="word",
            bg="#0e1724",
            fg="#e7edf5",
            insertbackground="#ffffff",
            relief="flat",
            padx=10,
            pady=10,
            font=("Consolas", 9),
        )
        scrollbar = ttk.Scrollbar(card, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.grid(row=1, column=0, sticky="nsew")
        scrollbar.grid(row=1, column=1, sticky="ns")
        return card

    def _build_package_section(self, parent: ttk.Frame) -> ttk.Frame:
        card = self._card(parent, "3. Estimator Package")
        card.columnconfigure(0, weight=1)
        actions = [
            ("Open Output Folder", None),
            ("Open Dashboard", "project_dashboard.md"),
            ("Open Takeoff Items CSV", "takeoff_items.csv"),
            ("Open Estimator Review CSV", "estimator_review.csv"),
            ("Open Marked Drawings PDF", "marked_up_drawings.pdf"),
            ("Open Accubid Mapping CSV", "accubid_mapping.csv"),
            ("Open Validation Template CSV", "validation_answer_key_template.csv"),
        ]
        for index, (label, filename) in enumerate(actions, 1):
            button = ttk.Button(card, text=label, command=lambda f=filename: self.open_output_file(f))
            button.grid(row=index, column=0, sticky="ew", pady=2)
            self.output_buttons[label] = button

        status_frame = ttk.Frame(card, style="Card.TFrame")
        status_frame.grid(row=len(actions) + 1, column=0, sticky="ew", pady=(10, 0))
        status_frame.columnconfigure(1, weight=1)
        for row, filename in enumerate(REQUIRED_OUTPUTS):
            ttk.Label(status_frame, text=filename, style="Muted.TLabel").grid(row=row, column=0, sticky="w", pady=1)
            label = ttk.Label(status_frame, text="Missing", style="Muted.TLabel")
            label.grid(row=row, column=1, sticky="e", pady=1)
            self.output_status_labels[filename] = label
        return card

    def _build_validation_section(self, parent: ttk.Frame) -> ttk.Frame:
        card = self._card(parent, "4. Validation")
        card.columnconfigure(1, weight=1)
        ttk.Label(card, text="Answer key CSV", style="Body.TLabel").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(card, textvariable=self.answer_key_var).grid(row=1, column=1, sticky="ew", padx=(10, 6))
        ttk.Button(card, text="Browse", command=self.browse_answer_key).grid(row=1, column=2)
        ttk.Button(card, text="Run Validation", command=self.run_validation).grid(row=2, column=0, columnspan=3, sticky="ew", pady=(8, 2))
        open_folder = ttk.Button(card, text="Open Validation Folder", command=lambda: self.open_validation_file(None))
        open_summary = ttk.Button(card, text="Open Validation Summary", command=lambda: self.open_validation_file("SYMBOL_DETECTION_VALIDATION.md"))
        open_folder.grid(row=3, column=0, columnspan=3, sticky="ew", pady=2)
        open_summary.grid(row=4, column=0, columnspan=3, sticky="ew", pady=2)
        self.validation_buttons.extend([open_folder, open_summary])
        return card

    def _build_demo_section(self, parent: ttk.Frame) -> ttk.Frame:
        card = self._card(parent, "5. Demo / Health Check")
        card.columnconfigure(0, weight=1)
        ttk.Button(card, text="Run Safe Demo", command=self.run_safe_demo).grid(row=1, column=0, sticky="ew", pady=2)
        ttk.Button(card, text="Check Current Output Package", command=self.check_current_output).grid(row=2, column=0, sticky="ew", pady=2)
        ttk.Button(card, text="Open Demo Checklist", command=self.open_demo_checklist).grid(row=3, column=0, sticky="ew", pady=2)
        ttk.Label(card, text="Company files should stay local/private. No pricing is performed.", style="Muted.TLabel", wraplength=430).grid(row=4, column=0, sticky="ew", pady=(8, 0))
        return card

    def browse_input_folder(self) -> None:
        path = filedialog.askdirectory(title="Select project folder")
        if path:
            self.input_var.set(path)
            self._default_output_from_input(Path(path))

    def browse_input_pdf(self) -> None:
        path = filedialog.askopenfilename(title="Select drawing PDF", filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")])
        if path:
            self.input_var.set(path)
            self._default_output_from_input(Path(path))

    def browse_output_folder(self) -> None:
        path = filedialog.askdirectory(title="Select output folder")
        if path:
            self.output_var.set(path)
            self.refresh_output_status()

    def browse_answer_key(self) -> None:
        path = filedialog.askopenfilename(title="Select validation answer key CSV", filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if path:
            self.answer_key_var.set(path)

    def _default_output_from_input(self, path: Path) -> None:
        if not self.output_var.get().strip():
            self.output_var.set(str(ROOT / "outputs" / "estimator-package" / safe_name(path.name)))
        if not self.project_name_var.get().strip():
            self.project_name_var.set(path.stem if path.is_file() else path.name)
        self.refresh_output_status()

    def set_status(self, status: str, message: str) -> None:
        self.status_var.set(status)
        self.progress_var.set(message)
        style = {
            "Ready": "StatusReady.TLabel",
            "Running": "StatusRunning.TLabel",
            "Completed": "StatusCompleted.TLabel",
            "Failed": "StatusFailed.TLabel",
        }.get(status, "StatusReady.TLabel")
        self.status_badge.configure(style=style)

    def log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message.rstrip() + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def run_estimate(self) -> None:
        input_path = Path(self.input_var.get().strip())
        out_dir = Path(self.output_var.get().strip())
        if not self._require_path(input_path, "Choose a project folder or PDF first."):
            return
        if not str(out_dir):
            messagebox.showwarning(APP_TITLE, "Choose an output folder first.")
            return
        cmd = [
            sys.executable,
            str(CLI),
            "estimate-project",
            "--project-folder",
            str(input_path),
            "--out-dir",
            str(out_dir),
        ]
        project_name = self.project_name_var.get().strip()
        if project_name:
            cmd.extend(["--project-name", project_name])
        self._run_command(cmd, "Running estimate-project...", on_done=self._after_estimate)

    def run_validation(self) -> None:
        out_dir = Path(self.output_var.get().strip())
        answer_key = Path(self.answer_key_var.get().strip())
        detections = out_dir / "takeoff_items.csv"
        if not out_dir.exists():
            messagebox.showwarning(APP_TITLE, "Run an estimate or choose an output folder first.")
            return
        if not detections.exists():
            messagebox.showwarning(APP_TITLE, "takeoff_items.csv is missing. Run estimate-project first.")
            return
        if not self._require_path(answer_key, "Choose an answer key CSV first."):
            return
        cmd = [
            sys.executable,
            str(CLI),
            "validate-detections-csv",
            "--detections",
            str(detections),
            "--answer-key",
            str(answer_key),
            "--out-dir",
            str(out_dir / "validation"),
        ]
        self._run_command(cmd, "Running validation...", on_done=lambda code: self._after_validation(code))

    def run_safe_demo(self) -> None:
        demo_project = ROOT / "samples" / "safe_multi_scope_project"
        demo_output = ROOT / "outputs" / "estimator-package" / "safe-multi-scope-demo"
        self.input_var.set(str(demo_project))
        self.output_var.set(str(demo_output))
        self.project_name_var.set("safe-multi-scope-demo")
        commands = [
            [sys.executable, str(CREATE_DEMO), "--out-dir", str(demo_project), "--seed", "1"],
            [sys.executable, str(CLI), "estimate-project", "--project-folder", str(demo_project), "--out-dir", str(demo_output)],
        ]
        self._run_command_sequence(commands, "Running safe demo...", on_done=self._after_estimate)

    def check_current_output(self) -> None:
        out_dir = Path(self.output_var.get().strip())
        if not out_dir.exists():
            messagebox.showwarning(APP_TITLE, "Choose an existing output folder first.")
            return
        if not CHECK_OUTPUTS.exists():
            messagebox.showwarning(APP_TITLE, f"Missing health checker: {CHECK_OUTPUTS}")
            return
        cmd = [sys.executable, str(CHECK_OUTPUTS), "--out-dir", str(out_dir)]
        self._run_command(cmd, "Checking current output package...", on_done=lambda code: self._after_check(code))

    def open_demo_checklist(self) -> None:
        if DEMO_CHECKLIST.exists():
            self._safe_open(DEMO_CHECKLIST)
        else:
            messagebox.showinfo(APP_TITLE, "Demo checklist was not found yet.")

    def open_output_file(self, filename: str | None) -> None:
        out_dir = Path(self.output_var.get().strip())
        path = out_dir if filename is None else out_dir / filename
        self._safe_open(path)

    def open_validation_file(self, filename: str | None) -> None:
        validation_dir = Path(self.output_var.get().strip()) / "validation"
        path = validation_dir if filename is None else validation_dir / filename
        self._safe_open(path)

    def _safe_open(self, path: Path) -> None:
        try:
            open_path(path)
        except Exception as exc:
            messagebox.showwarning(APP_TITLE, f"Could not open:\n{path}\n\n{exc}")

    def _require_path(self, path: Path, message: str) -> bool:
        if not str(path) or not path.exists():
            messagebox.showwarning(APP_TITLE, message)
            return False
        return True

    def _run_command(self, cmd: list[str], message: str, on_done=None) -> None:
        self._run_command_sequence([cmd], message, on_done=on_done)

    def _run_command_sequence(self, commands: list[list[str]], message: str, on_done=None) -> None:
        if self.command_running:
            messagebox.showinfo(APP_TITLE, "A command is already running.")
            return
        self.clear_log()
        self.command_running = True
        self.started_at = time.time()
        self.set_status("Running", message)
        self._set_buttons_enabled(False)

        def worker() -> None:
            final_code = 0
            for index, cmd in enumerate(commands, 1):
                self.log_queue.put(("line", f"$ {' '.join(cmd)}"))
                try:
                    process = subprocess.Popen(
                        cmd,
                        cwd=str(ROOT),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                    )
                    assert process.stdout is not None
                    for line in process.stdout:
                        self.log_queue.put(("line", line))
                    final_code = process.wait()
                except Exception as exc:
                    final_code = 1
                    self.log_queue.put(("line", f"ERROR: {exc}"))
                if final_code != 0:
                    self.log_queue.put(("line", f"Command {index} failed with exit code {final_code}."))
                    break
            self.log_queue.put(("done", (final_code, on_done)))

        threading.Thread(target=worker, daemon=True).start()

    def _process_log_queue(self) -> None:
        try:
            while True:
                kind, payload = self.log_queue.get_nowait()
                if kind == "line":
                    self.log(str(payload))
                elif kind == "done":
                    code, callback = payload  # type: ignore[misc]
                    self.command_running = False
                    self._set_buttons_enabled(True)
                    if callback:
                        callback(code)
                    else:
                        self.set_status("Completed" if code == 0 else "Failed", "Command completed." if code == 0 else "Command failed.")
                    self.refresh_output_status()
        except queue.Empty:
            pass
        self.after(100, self._process_log_queue)

    def _tick_elapsed(self) -> None:
        if self.command_running and self.started_at:
            elapsed = int(time.time() - self.started_at)
            self.elapsed_var.set(f"Elapsed: {elapsed // 60:02d}:{elapsed % 60:02d}")
        self.after(500, self._tick_elapsed)

    def _after_estimate(self, code: int) -> None:
        if code == 0:
            self.set_status("Completed", "Estimate package created. Review the dashboard, takeoff CSV, and marked drawings.")
        else:
            self.set_status("Failed", "Estimate command failed. Check the log for the exact error.")
        self.refresh_output_status()

    def _after_validation(self, code: int) -> None:
        if code == 0:
            self.set_status("Completed", "Validation finished. Open the validation summary to review matches and differences.")
        else:
            self.set_status("Failed", "Validation failed. Check that the answer key CSV has usable reviewed quantities.")
        self.refresh_output_status()

    def _after_check(self, code: int) -> None:
        if code == 0:
            self.set_status("Completed", "Output package health check passed.")
        else:
            self.set_status("Failed", "Output package health check found an issue. Check the log.")
        self.refresh_output_status()

    def _set_buttons_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for child in self.winfo_children():
            self._set_button_tree_state(child, state)
        self.refresh_output_status()

    def _set_button_tree_state(self, widget: tk.Widget, state: str) -> None:
        if isinstance(widget, ttk.Button):
            widget.configure(state=state)
        for child in widget.winfo_children():
            self._set_button_tree_state(child, state)

    def refresh_output_status(self) -> None:
        output_text = self.output_var.get().strip()
        out_dir = Path(output_text) if output_text else Path("__no_output_selected__")
        package_exists = bool(output_text) and out_dir.exists() and out_dir.is_dir()
        button_state = "normal" if package_exists and not self.command_running else "disabled"
        for button in self.output_buttons.values():
            button.configure(state=button_state)
        for button in self.validation_buttons:
            button.configure(state=("normal" if (out_dir / "validation").exists() and not self.command_running else "disabled"))

        for filename, label in self.output_status_labels.items():
            path = out_dir / filename if package_exists else Path()
            if path.exists() and path.is_file():
                status = "Created"
                if filename == "marked_up_drawings.pdf" and path.stat().st_size < 1500:
                    status = "Warning: possible placeholder"
                label.configure(text=status, foreground="#1f6b3a" if status == "Created" else "#9b5b00")
            else:
                label.configure(text="Missing", foreground="#9b2f1f")


def main() -> None:
    app = EstimatorAgentApp()
    app.mainloop()


if __name__ == "__main__":
    main()
