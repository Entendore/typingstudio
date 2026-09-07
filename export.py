"""State Machines, Orchestrators, VideoExporter, Settings Dialog, and dynamic UI modes."""
from __future__ import annotations
from enum import Enum, auto
from typing import Optional, List, Dict
from dataclasses import dataclass
import sys, os, shutil, subprocess, time

from PySide6.QtCore import Qt, QTimer, Signal, QThread
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                                QPushButton, QLabel, QComboBox, QSpinBox, QLineEdit,
                                QListWidget, QAbstractItemView, QMainWindow,
                                QFrame, QSizePolicy, QDialog, QFormLayout,
                                QSlider, QCheckBox, QGroupBox)
from PySide6.QtGui import QImage

from .core import (SettingsRepository, AppSettingsSchema, ThemeRegistry, THEMES,
                   get_process_factory, log, setup_project_logging, CWD,
                   INPUT_DIR, OUTPUT_DIR, FileScanner)
from .rendering import (PreviewWidget, TypewriterModel, PanelLayout, PreviewState, CodeRenderer)
from .audio import SimpleSoundGen, pcm_to_wav_bytes

APP_QSS = """
* { font-family: "Segoe UI", "Inter", "Helvetica", "Arial"; font-size: 13px; }
QMainWindow, QWidget { background: #0e0f1a; color: #e6e6f0; }
QLabel { background: transparent; color: #e6e6f0; }
QLabel#brand { font-size: 22px; font-weight: 700; letter-spacing: 1px; color: #bd93f9; }
QLabel#brandSub { font-size: 9px; color: #6272a4; letter-spacing: 3px; }
QLabel#modeTitle { font-size: 17px; font-weight: 700; color: #f8f8f2; }
QLabel#modeDesc { font-size: 11px; color: #8b8ba7; }
QLabel#hint { font-size: 10px; color: #6272a4; }
QLabel#section { font-size: 10px; color: #6272a4; letter-spacing: 2px; font-weight: 600; }
QFrame#header { background: #0a0b14; border-bottom: 1px solid #23263a; }
QFrame#sidebar { background: #11121d; border-right: 1px solid #23263a; }
QFrame#card { background: #161826; border-radius: 10px; border: 1px solid #23263a; }
QFrame#statusBar { background: #11121d; border-top: 1px solid #23263a; }
QDialog { background: #0e0f1a; border: 1px solid #23263a; border-radius: 10px; }
QGroupBox { border: 1px solid #23263a; border-radius: 8px; margin-top: 14px; padding: 14px; color: #bd93f9; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
QComboBox, QSpinBox, QLineEdit { background: #1c1e2e; border: 1px solid #2a2d44; border-radius: 6px; padding: 6px 10px; color: #f8f8f2; min-height: 18px; }
QComboBox:hover, QSpinBox:hover, QLineEdit:hover { border-color: #bd93f9; }
QComboBox:focus, QSpinBox:focus, QLineEdit:focus { border-color: #bd93f9; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background: #1c1e2e; border: 1px solid #2a2d44; selection-background-color: #bd93f9; selection-color: #0e0f1a; outline: 0; padding: 4px; }
QSpinBox::up-button, QSpinBox::down-button { width: 14px; }
QPushButton { background: #2a2d44; border: 1px solid #2a2d44; border-radius: 6px; padding: 6px 14px; color: #f8f8f2; }
QPushButton:hover { border-color: #bd93f9; color: #f8f8f2; }
QPushButton:disabled { color: #4a4d68; background: #1a1c2c; }
QPushButton#primary { background: #bd93f9; color: #0e0f1a; font-weight: 700; border: none; }
QPushButton#primary:hover { background: #caa7ff; }
QPushButton#primary:disabled { background: #6a5a8a; color: #2a2240; }
QPushButton#icon { background: transparent; border: 1px solid #2a2d44; border-radius: 6px; padding: 6px; min-width: 32px; max-width: 40px; }
QPushButton#icon:hover { border-color: #bd93f9; color: #bd93f9; }
QPushButton#icon:checked { background: #bd93f9; color: #0e0f1a; border-color: #bd93f9; }
QListWidget { background: #11121d; border: none; padding: 6px; outline: 0; }
QListWidget::item { padding: 10px 12px; border-radius: 6px; color: #b0b0c8; margin: 1px 0; }
QListWidget::item:hover { background: #1c1e2e; color: #f8f8f2; }
QListWidget::item:selected { background: #bd93f9; color: #0e0f1a; font-weight: 700; }
QSlider::groove:horizontal { height: 4px; background: #2a2d44; border-radius: 2px; }
QSlider::handle:horizontal { background: #bd93f9; width: 14px; height: 14px; margin: -6px 0; border-radius: 8px; }
QSlider::handle:horizontal:hover { background: #caa7ff; }
QSlider::sub-page:horizontal { background: #bd93f9; border-radius: 2px; }
QCheckBox { spacing: 8px; color: #e6e6f0; }
QCheckBox::indicator { width: 16px; height: 16px; border-radius: 4px; border: 1px solid #2a2d44; background: #1c1e2e; }
QCheckBox::indicator:checked { background: #bd93f9; border-color: #bd93f9; }
"""

class ExportState(Enum):
    IDLE = auto(); RENDERING = auto(); COMPLETED = auto(); FAILED = auto()

@dataclass(frozen=True, slots=True)
class ProjectMode:
    name: str; settings_key: str
    supported_exts: frozenset; output_suffix: str

PROJECT_MODES: Dict[str, ProjectMode] = {
    "1: Jr vs Sr Dev Studio":       ProjectMode("Jr vs Sr Dev Studio",       "project1_jr_vs_sr",      frozenset({".json"}),                              "_jr_vs_sr.mp4"),
    "2: MultiWindow Studio":        ProjectMode("MultiWindow Studio",        "project2_multi_window",  frozenset({".py", ".js", ".cpp"}),                  "_multiwindow.mp4"),
    "3: YouTube Optimised Studio":  ProjectMode("YouTube Optimised Studio",  "project3_codetyping",     frozenset({".py", ".js", ".cpp"}),                  "_youtube.mp4"),
    "4: Text Typing Studio":        ProjectMode("Text Typing Studio",        "project4_text",           frozenset({".txt", ".csv", ".md"}),                 "_text.mp4"),
    "5: Emoji & ASCII Art Studio":  ProjectMode("Emoji & ASCII Art Studio",  "project5_emoji_ascii",    frozenset({".emoji", ".emo", ".asc", ".ascii", ".art"}), "_emoji.mp4"),
}

MODE_DESCRIPTIONS = {
    "1: Jr vs Sr Dev Studio":      "Side-by-side comparison — junior on the left, senior on the right, with different typing speeds.",
    "2: MultiWindow Studio":       "2×2 grid rendering multiple files simultaneously with staggered typing.",
    "3: YouTube Optimised Studio":  "Single large 16:9 panel with title bar and channel HUD — ready for YouTube.",
    "4: Text Typing Studio":        "Clean document-style typography with word wrap.",
    "5: Emoji & ASCII Art Studio":  "Large monospace rendering for ASCII art and emoji compositions.",
}

class VideoExporter(QThread):
    progress = Signal(int, int, str) 
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, mode, model, theme_name, resolution, sound_preset, render_config, parent=None):
        super().__init__(parent)
        self.mode = mode; self.model = model; self.theme_name = theme_name
        self.resolution = resolution; self.sound_preset = sound_preset
        self.render_config = render_config
        
    def run(self):
        out_path = str(OUTPUT_DIR / f"output{self.mode.output_suffix}")
        temp_wav = str(CWD / "temp_audio.wav")
        
        self.progress.emit(0, 100, "Generating Audio...")
        gen = SimpleSoundGen(44100, self.sound_preset)
        panels_data = [{'text': p.text, 'speed_factor': p.speed_factor, 'delay': p.delay} for p in self.model.panels]
        pcm = gen.generate_full_track(panels_data, self.model.target_duration, 44100)
        with open(temp_wav, "wb") as f: f.write(pcm_to_wav_bytes(pcm, 44100))
        
        self.progress.emit(1, 100, "Initializing FFmpeg...")
        res_map = {"720p": (1280, 720), "1080p": (1920, 1080), "1440p": (2560, 1440)}
        w, h = res_map.get(self.resolution, (1920, 1080))
        renderer = CodeRenderer(w, h, self.theme_name, self.mode.settings_key)
        renderer.text_font_size = self.render_config.get("text_font_size", 17)
        renderer.ascii_font_size = self.render_config.get("ascii_font_size", 14)
        renderer.ascii_color_mode = self.render_config.get("ascii_color_mode", "Rainbow")
        renderer.build_layout(self.model)
        renderer.reset_caret_easing()
        
        ffmpeg_exe = shutil.which("ffmpeg")
        if not ffmpeg_exe:
            self.error.emit("FFmpeg not found in system PATH. Please install it.")
            if os.path.exists(temp_wav): os.remove(temp_wav)
            return
            
        fps = 30
        total_frames = int(self.model.target_duration * fps)
        
        cmd = [
            ffmpeg_exe, "-y",
            "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
            "-i", temp_wav,
            "-map", "0:v", "-map", "1:a",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            out_path
        ]
        
        proc = get_process_factory().create_popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        start_time = time.time()
        for i in range(total_frames):
            progress = (i + 1) / total_frames
            img = renderer.render_frame(progress, self.model)
            rgba_img = img.convertToFormat(QImage.Format_RGBA8888)
            data = bytes(rgba_img.constBits())
            try: proc.stdin.write(data)
            except Exception:
                stderr = proc.stderr.read().decode()
                self.error.emit(f"FFmpeg crashed: {stderr}")
                proc.kill()
                if os.path.exists(temp_wav): os.remove(temp_wav)
                return
            elapsed = time.time() - start_time
            fps_done = (i + 1) / max(0.001, elapsed)
            eta_sec = (total_frames - (i + 1)) / max(1.0, fps_done)
            eta_str = f"{int(eta_sec)//60:02d}:{int(eta_sec)%60:02d}"
            self.progress.emit(i + 1, total_frames, f"Frame {i+1}/{total_frames} (ETA: {eta_str})")
            
        proc.stdin.close(); proc.wait()
        if os.path.exists(temp_wav): os.remove(temp_wav)
        if proc.returncode == 0: self.finished.emit(out_path)
        else: self.error.emit(f"FFmpeg exited with code {proc.returncode}")

class AudioVisualizerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(30); self.setFixedHeight(24)
        self._levels = [0.2, 0.5, 0.8]; self._decay = 0.85
        self._timer = QTimer(self); self._timer.setInterval(80)
        self._timer.timeout.connect(self.update); self._timer.start()
    def ping(self): self._levels = [0.8, 1.0, 0.6]
    def paintEvent(self, event):
        from PySide6.QtGui import QPainter, QColor, QRectF
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); p.setPen(Qt.NoPen)
        for i, lvl in enumerate(self._levels):
            self._levels[i] = max(0.15, lvl * self._decay)
            h = self.height() * self._levels[i]; x = i * 8 + 2; y = (self.height() - h) / 2
            p.setBrush(QColor("#bd93f9") if lvl > 0.3 else QColor("#2a2d44"))
            p.drawRoundedRect(QRectF(x, y, 6, h), 2, 2)

class SettingsDialog(QDialog):
    def __init__(self, current_settings: AppSettingsSchema, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Studio Settings"); self.setFixedSize(420, 540)
        self._settings = current_settings; self._build_ui()

    def _build_ui(self):
        v = QVBoxLayout(self); v.setContentsMargins(24, 24, 24, 24); v.setSpacing(16)
        lbl = QLabel("Configure Studio Defaults"); lbl.setStyleSheet("font-size: 16px; font-weight: 700; color: #f8f8f2;")
        v.addWidget(lbl)

        app_group = QGroupBox("Appearance & Resolution"); app_layout = QFormLayout(app_group)
        self.theme_cb = QComboBox(); self.theme_cb.addItems(ThemeRegistry.names()); self.theme_cb.setCurrentText(self._settings.theme)
        self.res_cb = QComboBox(); self.res_cb.addItems(["720p", "1080p", "1440p"]); self.res_cb.setCurrentText(self._settings.resolution)
        self.fmt_cb = QComboBox(); self.fmt_cb.addItems(["YouTube (16:9)", "TikTok (9:16)", "Square (1:1)"]); self.fmt_cb.setCurrentText(self._settings.fmt)
        app_layout.addRow("Theme", self.theme_cb); app_layout.addRow("Resolution", self.res_cb); app_layout.addRow("Format", self.fmt_cb)
        v.addWidget(app_group)

        audio_group = QGroupBox("Audio Feedback"); audio_layout = QFormLayout(audio_group)
        self.sound_cb = QComboBox()
        self.sound_cb.addItems(["Mechanical", "Vintage", "Bubble", "Cyberpunk", "ASMR Desk", "Buckling Spring", "None"])
        self.sound_cb.setCurrentText(self._settings.sound)
        self.vol_slider = QSlider(Qt.Horizontal); self.vol_slider.setRange(0, 100); self.vol_slider.setValue(self._settings.volume)
        self.vol_lbl = QLabel(f"{self._settings.volume}%"); self.vol_slider.valueChanged.connect(lambda v: self.vol_lbl.setText(f"{v}%"))
        audio_layout.addRow("Preset", self.sound_cb); audio_layout.addRow("Volume", self.vol_slider); audio_layout.addRow("", self.vol_lbl)
        v.addWidget(audio_group)

        wpm_group = QGroupBox("Typing Speed (WPM)"); wpm_layout = QFormLayout(wpm_group)
        self.base_sp = QSpinBox(); self.base_sp.setRange(10, 500); self.base_sp.setValue(self._settings.wpm)
        self.j_sp = QSpinBox(); self.j_sp.setRange(10, 500); self.j_sp.setValue(self._settings.j_wpm)
        self.s_sp = QSpinBox(); self.s_sp.setRange(10, 500); self.s_sp.setValue(self._settings.s_wpm)
        wpm_layout.addRow("Base WPM", self.base_sp); wpm_layout.addRow("Junior WPM", self.j_sp); wpm_layout.addRow("Senior WPM", self.s_sp)
        v.addWidget(wpm_group)

        play_group = QGroupBox("Playback & Speed"); play_layout = QFormLayout(play_group)
        self.speed_cb = QComboBox()
        self.speed_cb.addItems(["0.5×", "0.75×", "1×", "1.5×", "2×"]); self.speed_cb.setCurrentText(f"{self._settings.speed}×")
        self.loop_chk = QCheckBox("Loop preview continuously"); self.loop_chk.setChecked(self._settings.loop)
        play_layout.addRow("Default Speed", self.speed_cb); play_layout.addRow("Behavior", self.loop_chk)
        v.addWidget(play_group)

        btn_row = QHBoxLayout(); btn_row.addStretch()
        cancel_btn = QPushButton("Cancel"); cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Save"); save_btn.setObjectName("primary"); save_btn.clicked.connect(self.accept)
        btn_row.addWidget(cancel_btn); btn_row.addWidget(save_btn); v.addLayout(btn_row)

    def get_settings(self) -> AppSettingsSchema:
        return AppSettingsSchema(
            theme=self.theme_cb.currentText(), resolution=self.res_cb.currentText(), fmt=self.fmt_cb.currentText(),
            sound=self.sound_cb.currentText(), volume=self.vol_slider.value(),
            speed=float(self.speed_cb.currentText().replace("×", "")), loop=self.loop_chk.isChecked(),
            wpm=self.base_sp.value(), j_wpm=self.j_sp.value(), s_wpm=self.s_sp.value(),
            yt_title=self._settings.yt_title, yt_channel=self._settings.yt_channel,
            multi_stagger=self._settings.multi_stagger, text_font_size=self._settings.text_font_size,
            ascii_font_size=self._settings.ascii_font_size, ascii_color_mode=self._settings.ascii_color_mode
        )

LANG_MAP = {
    ".py":"py", ".js":"js", ".cpp":"cpp", ".cc":"cpp", ".cxx":"cpp", ".h":"cpp",
    ".txt":"text", ".md":"text", ".csv":"text", ".json":"py",
    ".emoji":"ascii", ".emo":"ascii", ".asc":"ascii", ".ascii":"ascii", ".art":"ascii",
}

SAMPLES = {
    "project1_jr_vs_sr": ("sample.json", '{\n  "name": "demo"\n}\n'),
    "project2_multi_window": ("main.py", 'def greet():\n    pass\n'),
    "project3_codetyping": ("fibonacci.py", 'def fib(n):\n    return n\n'),
    "project4_text": ("welcome.txt", "Welcome to TypingAnimStudio.\n"),
    "project5_emoji_ascii": ("cat.ascii", " /\\_/\\\n( o.o )\n"),
}

class BaseCodeExportWidget(QWidget):
    def __init__(self, mode_name: str, parent=None):
        super().__init__(parent)
        self.mode = PROJECT_MODES[mode_name]
        self.settings_repo = SettingsRepository(CWD / "settings.json")
        self._settings = self.settings_repo.get(self.mode.settings_key)
        self.exporter: Optional[VideoExporter] = None
        
        self._build_ui()
        self.preview.set_mode_key(self.mode.settings_key)
        self._apply_settings(self._settings)
        
        self.scanner = FileScanner(INPUT_DIR, self)
        self.scanner.files_changed.connect(self._update_file_list)

    def _build_ui(self):
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        header = QFrame(); header.setObjectName("card")
        h = QHBoxLayout(header); h.setContentsMargins(20, 14, 20, 14); h.setSpacing(12)
        title_box = QVBoxLayout(); title_box.setSpacing(2)
        self.mode_title = QLabel(self.mode.name); self.mode_title.setObjectName("modeTitle")
        self.mode_desc = QLabel(MODE_DESCRIPTIONS.get(self._mode_key_name(), "")); self.mode_desc.setObjectName("modeDesc")
        title_box.addWidget(self.mode_title); title_box.addWidget(self.mode_desc)
        h.addLayout(title_box); h.addStretch()

        self._build_mode_controls(h)

        self.export_btn = QPushButton("Export Video"); self.export_btn.setObjectName("primary")
        h.addWidget(self.export_btn)
        root.addWidget(header)

        body = QHBoxLayout(); body.setContentsMargins(0, 0, 0, 0); body.setSpacing(0)

        sidebar = QFrame(); sidebar.setObjectName("sidebar"); sidebar.setFixedWidth(280)
        sb = QVBoxLayout(sidebar); sb.setContentsMargins(14, 16, 14, 14); sb.setSpacing(8)
        sb_head = QHBoxLayout(); sb_head.addWidget(self._section_label("FILES")); sb_head.addStretch()
        self.refresh_btn = QPushButton("⟳"); self.refresh_btn.setObjectName("icon")
        self.refresh_btn.setToolTip("Rescan input/"); self.refresh_btn.clicked.connect(self._manual_scan)
        sb_head.addWidget(self.refresh_btn); sb.addLayout(sb_head)

        self.file_list = QListWidget(); self.file_list.setSelectionMode(QAbstractItemView.SingleSelection)
        sb.addWidget(self.file_list, 1)

        self.sample_btn = QPushButton("+ Add sample file"); self.sample_btn.clicked.connect(self._create_sample)
        sb.addWidget(self.sample_btn)

        hint = QLabel("Drop files in /input to use them. List updates automatically."); hint.setObjectName("hint"); hint.setWordWrap(True)
        sb.addWidget(hint); body.addWidget(sidebar)

        main_col = QVBoxLayout(); main_col.setContentsMargins(20, 20, 20, 16); main_col.setSpacing(12)
        self.preview = PreviewWidget(); self.preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.preview.audio_activity.connect(self._on_audio_activity)
        main_col.addWidget(self.preview, 1)

        ctrl = QFrame(); ctrl.setObjectName("card")
        cl = QHBoxLayout(ctrl); cl.setContentsMargins(14, 10, 14, 10); cl.setSpacing(10)

        self.play_btn = QPushButton("▶"); self.play_btn.setObjectName("icon")
        self.play_btn.setFixedWidth(40); self.play_btn.setToolTip("Play / Pause")
        self.play_btn.clicked.connect(lambda: self.preview.controller.dispatch(("PLAY_PAUSE", None)))
        cl.addWidget(self.play_btn)

        self.restart_btn = QPushButton("⏮"); self.restart_btn.setObjectName("icon")
        self.restart_btn.setFixedWidth(40); self.restart_btn.setToolTip("Restart")
        self.restart_btn.clicked.connect(lambda: self.preview.controller.dispatch(("RESTART", None)))
        cl.addWidget(self.restart_btn)

        self.slider = QSlider(Qt.Horizontal); self.slider.setRange(0, 1000)
        self.slider.valueChanged.connect(lambda v: self.preview.controller.dispatch(("SEEK", v / 1000.0)))
        cl.addWidget(self.slider, 1)

        self.time_lbl = QLabel("00:00 / 00:00"); self.time_lbl.setObjectName("modeDesc")
        self.time_lbl.setMinimumWidth(110); self.time_lbl.setAlignment(Qt.AlignCenter)
        cl.addWidget(self.time_lbl)

        cl.addWidget(self._section_label("SPEED"))
        self.speed_cb = QComboBox()
        self.speed_cb.addItems(["0.5×", "0.75×", "1×", "1.5×", "2×"])
        self.speed_cb.setCurrentText("1×"); self.speed_cb.setFixedWidth(80)
        self.speed_cb.currentTextChanged.connect(self._on_speed_change)
        cl.addWidget(self.speed_cb)

        self.loop_btn = QPushButton("🔁"); self.loop_btn.setObjectName("icon")
        self.loop_btn.setCheckable(True); self.loop_btn.setFixedWidth(40)
        self.loop_btn.setToolTip("Loop playback")
        self.loop_btn.toggled.connect(lambda b: self.preview.controller.dispatch(("SET_LOOP", b)))
        cl.addWidget(self.loop_btn)

        self.audio_viz = AudioVisualizerWidget(); cl.addWidget(self.audio_viz)
        main_col.addWidget(ctrl); body.addLayout(main_col, 1); root.addLayout(body, 1)

        status = QFrame(); status.setObjectName("statusBar"); status.setFixedHeight(32)
        sh = QHBoxLayout(status); sh.setContentsMargins(16, 0, 16, 0)
        self.status_lbl = QLabel("Ready"); self.status_lbl.setObjectName("hint")
        sh.addWidget(self.status_lbl); sh.addStretch()
        self.chars_lbl = QLabel("0 chars"); self.chars_lbl.setObjectName("hint")
        sh.addWidget(self.chars_lbl); sh.addSpacing(16)
        self.progress_lbl = QLabel("0.0%"); self.progress_lbl.setObjectName("hint")
        sh.addWidget(self.progress_lbl); root.addWidget(status)

        self.file_list.currentItemChanged.connect(self._on_file_selected)
        self.export_btn.clicked.connect(self._start_export)
        self.preview.controller.state_changed.connect(self._on_preview_state)

    def _build_mode_controls(self, h_layout):
        h_layout.addWidget(self._section_label("WPM"))
        self.wpm_sp = QSpinBox(); self.wpm_sp.setRange(10, 500); self.wpm_sp.setSingleStep(5)
        self.wpm_sp.setFixedWidth(80); h_layout.addWidget(self.wpm_sp); h_layout.addSpacing(12)
        self.wpm_sp.valueChanged.connect(self._on_wpm_changed)

    def _on_audio_activity(self): self.audio_viz.ping()

    @staticmethod
    def _section_label(text: str) -> QLabel:
        lbl = QLabel(text); lbl.setObjectName("section"); return lbl

    def _mode_key_name(self) -> str:
        for k, v in PROJECT_MODES.items():
            if v is self.mode or v.settings_key == self.mode.settings_key: return k
        return ""

    def _manual_scan(self): self.scanner._scan()

    def _update_file_list(self, files: list):
        self.file_list.blockSignals(True); self.file_list.clear()
        for f in files:
            if os.path.splitext(f)[1].lower() in self.mode.supported_exts: self.file_list.addItem(f)
        self.file_list.blockSignals(False)
        if self.file_list.count() > 0: self.file_list.setCurrentRow(0)
        else: self.preview.set_model(TypewriterModel())

    def _create_sample(self):
        fname, content = SAMPLES.get(self.mode.settings_key, ("sample.txt", "Hello, World!\n"))
        path = INPUT_DIR / fname
        if not path.exists():
            try: path.write_text(content, encoding="utf-8")
            except Exception as e: log.warning("Could not write sample: %s", e)
        self.scanner._scan()
        for i in range(self.file_list.count()):
            if self.file_list.item(i).text() == fname: self.file_list.setCurrentRow(i); break

    def _on_file_selected(self, current, _previous):
        if not current: return
        fname = current.text(); path = INPUT_DIR / fname
        try: text = path.read_text(encoding="utf-8")
        except Exception as e:
            log.warning("Could not read %s: %s", fname, e); return
        self._load_text(text, fname)

    def _load_text(self, text: str, fname: str):
        ext = os.path.splitext(fname)[1].lower(); lang = LANG_MAP.get(ext, "py")
        model = TypewriterModel()
        model.panels = [PanelLayout(title=fname, text=text, lang=lang, speed_factor=1.0, accent="#bd93f9")]
        words = model.total_chars / 5
        model.target_duration = max(2.0, words / max(self._settings.wpm, 1) * 60.0)
        self.preview.set_model(model)

    def _on_wpm_changed(self, wpm: int):
        if not self.preview.model.panels: return
        words = self.preview.model.total_chars / 5
        duration = max(2.0, words / max(wpm, 1) * 60.0)
        self.preview.controller.dispatch(("SET_DURATION", duration))

    def _on_speed_change(self, txt: str):
        self.preview.controller.dispatch(("SET_SPEED", float(txt.replace("×", ""))))

    def _on_preview_state(self, state: PreviewState):
        total = state.target_duration; cur = state.progress * total
        self.time_lbl.setText(f"{self._fmt(cur)} / {self._fmt(total)}")
        self.play_btn.setText("⏸" if state.animating else "▶")
        self.slider.blockSignals(True); self.slider.setValue(int(state.progress * 1000)); self.slider.blockSignals(False)
        chars = int(state.progress * self.preview.model.total_chars)
        self.chars_lbl.setText(f"{chars} / {self.preview.model.total_chars} chars")
        self.progress_lbl.setText(f"{state.progress * 100:5.1f}%")
        if state.animating:        self.status_lbl.setText("Playing…")
        elif state.progress >= 1.0:self.status_lbl.setText("Completed")
        elif state.progress == 0:  self.status_lbl.setText("Ready")
        else:                      self.status_lbl.setText("Paused")

    @staticmethod
    def _fmt(s: float) -> str:
        m = int(s) // 60; sec = int(s) - m * 60; return f"{m:02d}:{sec:02d}"

    def _start_export(self):
        if self.exporter and self.exporter.isRunning(): return
        self.export_btn.setText("Exporting…"); self.export_btn.setEnabled(False)
        self.status_lbl.setText("Starting export...")
        
        render_config = {
            "text_font_size": self.preview._renderer.text_font_size,
            "ascii_font_size": self.preview._renderer.ascii_font_size,
            "ascii_color_mode": self.preview._renderer.ascii_color_mode
        }
        
        self.exporter = VideoExporter(
            self.mode, self.preview.model, self.preview._theme_name, 
            self._settings.resolution, self.preview.audio_player.gen.preset,
            render_config
        )
        self.exporter.progress.connect(self._on_export_progress)
        self.exporter.finished.connect(self._on_export_finished)
        self.exporter.error.connect(self._on_export_error)
        self.exporter.start()

    def _on_export_progress(self, cur, total, msg):
        pct = int((cur / total) * 100) if total > 0 else 0
        self.status_lbl.setText(msg)
        self.progress_lbl.setText(f"{pct}%")

    def _on_export_finished(self, path):
        self.export_btn.setText("Export Video"); self.export_btn.setEnabled(True)
        self.status_lbl.setText(f"Saved → {os.path.basename(path)}")
        self.exporter = None

    def _on_export_error(self, msg):
        self.export_btn.setText("Export Video"); self.export_btn.setEnabled(True)
        self.status_lbl.setText(f"Error: {msg}")
        self.exporter = None

    def _apply_settings(self, s: AppSettingsSchema):
        self.speed_cb.setCurrentText(f"{s.speed}×")
        self.loop_btn.setChecked(s.loop)
        self.preview.set_theme(s.theme)
        self.preview.set_audio_preset(s.sound)
        self.preview.set_audio_volume(s.volume)
        self.preview.controller.dispatch(("SET_SPEED", s.speed))
        self.preview.controller.dispatch(("SET_LOOP", s.loop))
        
        res_map = {"720p": (1280, 720), "1080p": (1920, 1080), "1440p": (2560, 1440)}
        w, h = res_map.get(s.resolution, (1920, 1080))
        self.preview._init_renderer(w, h)
        if self.preview.model.panels:
            self.preview._renderer.build_layout(self.preview.model)
            self.preview._repaint_preview()

    def cleanup(self):
        self.settings_repo.save(self.mode.settings_key, AppSettingsSchema(
            theme=self.preview._theme_name, wpm=self._settings.wpm,
            sound=self.preview.audio_player.gen.preset, volume=int(self.preview.audio_player._volume * 100),
            resolution=self._settings.resolution, fmt=self._settings.fmt,
            speed=float(self.speed_cb.currentText().replace("×", "")), loop=self.loop_btn.isChecked(),
            j_wpm=self._settings.j_wpm, s_wpm=self._settings.s_wpm,
            yt_title=self._settings.yt_title, yt_channel=self._settings.yt_channel,
            multi_stagger=self._settings.multi_stagger, text_font_size=self._settings.text_font_size,
            ascii_font_size=self._settings.ascii_font_size, ascii_color_mode=self._settings.ascii_color_mode
        ))

class JrVsSrWidget(BaseCodeExportWidget):
    def _build_mode_controls(self, h):
        h.addWidget(self._section_label("JUNIOR WPM"))
        self.j_wpm_sp = QSpinBox(); self.j_wpm_sp.setRange(10, 500); self.j_wpm_sp.setFixedWidth(80)
        h.addWidget(self.j_wpm_sp); h.addSpacing(8)
        h.addWidget(self._section_label("SENIOR WPM"))
        self.s_wpm_sp = QSpinBox(); self.s_wpm_sp.setRange(10, 500); self.s_wpm_sp.setFixedWidth(80)
        h.addWidget(self.s_wpm_sp)
        self.j_wpm_sp.valueChanged.connect(self._update_jr_sr_speeds)
        self.s_wpm_sp.valueChanged.connect(self._update_jr_sr_speeds)

    def _apply_settings(self, s):
        super()._apply_settings(s)
        self.j_wpm_sp.setValue(s.j_wpm)
        self.s_wpm_sp.setValue(s.s_wpm)

    def _update_jr_sr_speeds(self):
        j_wpm = self.j_wpm_sp.value()
        s_wpm = self.s_wpm_sp.value()
        base = max(1, (j_wpm + s_wpm) / 2)
        if not self.preview.model.panels: return
        self.preview.model.panels[0].speed_factor = j_wpm / base
        self.preview.model.panels[1].speed_factor = s_wpm / base
        words = self.preview.model.total_chars / 5
        self.preview.model.target_duration = max(2.0, words / max(base, 1) * 60.0)
        self.preview.controller.dispatch(("SET_DURATION", self.preview.model.target_duration))

    def _load_text(self, text, fname):
        ext = os.path.splitext(fname)[1].lower(); lang = LANG_MAP.get(ext, "py")
        model = TypewriterModel()
        j_wpm = self._settings.j_wpm; s_wpm = self._settings.s_wpm
        base = max(1, (j_wpm + s_wpm) / 2)
        model.panels = [
            PanelLayout(title=f"junior_{fname}", text=text, lang=lang, speed_factor=j_wpm/base, accent="#ff5f56"),
            PanelLayout(title=f"senior_{fname}",  text=text, lang=lang, speed_factor=s_wpm/base, accent="#27c93f"),
        ]
        words = model.total_chars / 5
        model.target_duration = max(2.0, words / max(base, 1) * 60.0)
        self.preview.set_model(model)

class MultiWindowWidget(BaseCodeExportWidget):
    def _build_mode_controls(self, h):
        h.addWidget(self._section_label("WPM"))
        self.wpm_sp = QSpinBox(); self.wpm_sp.setRange(10, 500); self.wpm_sp.setSingleStep(5)
        self.wpm_sp.setFixedWidth(80); h.addWidget(self.wpm_sp); h.addSpacing(12)
        h.addWidget(self._section_label("STAGGER"))
        self.stagger_s = QSlider(Qt.Horizontal); self.stagger_s.setRange(0, 50); self.stagger_s.setFixedWidth(100)
        h.addWidget(self.stagger_s)
        self.wpm_sp.valueChanged.connect(self._on_wpm_changed)
        self.stagger_s.valueChanged.connect(self._update_stagger)

    def _apply_settings(self, s):
        super()._apply_settings(s)
        self.wpm_sp.setValue(s.wpm)
        self.stagger_s.setValue(int(s.multi_stagger * 100))

    def _update_stagger(self, val):
        stagger = val / 100.0
        if not self.preview.model.panels: return
        for i, p in enumerate(self.preview.model.panels):
            p.delay = min(0.9, stagger * i)
        self.preview._repaint_preview()

    def _load_text(self, text, fname):
        ext = os.path.splitext(fname)[1].lower(); lang = LANG_MAP.get(ext, "py")
        model = TypewriterModel()
        n = max(1, (len(text) + 3) // 4)
        chunks = [text[i:i+n] for i in range(0, len(text), n)]
        while len(chunks) < 4: chunks.append("")
        accents = ["#bd93f9", "#8be9fd", "#ffb86c", "#50fa7b"]
        stagger = self._settings.multi_stagger
        model.panels = [
            PanelLayout(title=f"panel_{i+1}.py", text=chunks[i], lang=lang, speed_factor=1.0 + i * 0.25, accent=accents[i], delay=min(0.9, stagger * i))
            for i in range(4)
        ]
        words = model.total_chars / 5
        model.target_duration = max(2.0, words / max(self._settings.wpm, 1) * 60.0)
        self.preview.set_model(model)

class YouTubeWidget(BaseCodeExportWidget):
    def _build_mode_controls(self, h):
        h.addWidget(self._section_label("WPM"))
        self.wpm_sp = QSpinBox(); self.wpm_sp.setRange(10, 500); self.wpm_sp.setSingleStep(5)
        self.wpm_sp.setFixedWidth(80); h.addWidget(self.wpm_sp); h.addSpacing(12)
        h.addWidget(self._section_label("TITLE"))
        self.title_edit = QLineEdit(); self.title_edit.setFixedWidth(180)
        h.addWidget(self.title_edit); h.addSpacing(8)
        h.addWidget(self._section_label("CHANNEL"))
        self.channel_edit = QLineEdit(); self.channel_edit.setFixedWidth(120)
        h.addWidget(self.channel_edit)
        self.wpm_sp.valueChanged.connect(self._on_wpm_changed)
        self.title_edit.textChanged.connect(self._update_hud)
        self.channel_edit.textChanged.connect(self._update_hud)

    def _apply_settings(self, s):
        super()._apply_settings(s)
        self.wpm_sp.setValue(s.wpm)
        self.title_edit.setText(s.yt_title)
        self.channel_edit.setText(s.yt_channel)

    def _update_hud(self):
        if not self.preview.model.panels: return
        self.preview.model.hud_title = self.title_edit.text()
        self.preview.model.hud_channel = self.channel_edit.text()
        self.preview._repaint_preview()

    def _load_text(self, text, fname):
        ext = os.path.splitext(fname)[1].lower(); lang = LANG_MAP.get(ext, "py")
        model = TypewriterModel()
        model.hud_title = self.title_edit.text() if hasattr(self, 'title_edit') else self._settings.yt_title
        model.hud_channel = self.channel_edit.text() if hasattr(self, 'channel_edit') else self._settings.yt_channel
        model.panels = [PanelLayout(title=fname, text=text, lang=lang, speed_factor=1.0, accent="#bd93f9")]
        words = model.total_chars / 5
        model.target_duration = max(2.0, words / max(self._settings.wpm, 1) * 60.0)
        self.preview.set_model(model)

class TextWidget(BaseCodeExportWidget):
    def _build_mode_controls(self, h):
        h.addWidget(self._section_label("WPM"))
        self.wpm_sp = QSpinBox(); self.wpm_sp.setRange(10, 500); self.wpm_sp.setSingleStep(5)
        self.wpm_sp.setFixedWidth(80); h.addWidget(self.wpm_sp); h.addSpacing(12)
        h.addWidget(self._section_label("FONT"))
        self.font_sp = QSpinBox(); self.font_sp.setRange(12, 32); self.font_sp.setFixedWidth(60)
        h.addWidget(self.font_sp)
        self.wpm_sp.valueChanged.connect(self._on_wpm_changed)
        self.font_sp.valueChanged.connect(self._update_font_size)

    def _apply_settings(self, s):
        super()._apply_settings(s)
        self.wpm_sp.setValue(s.wpm)
        self.font_sp.setValue(s.text_font_size)

    def _update_font_size(self, size):
        if self.preview._renderer:
            self.preview._renderer.text_font_size = size
            if self.preview.model.panels:
                self.preview._renderer.build_layout(self.preview.model)
                self.preview._repaint_preview()

    def _load_text(self, text, fname):
        ext = os.path.splitext(fname)[1].lower(); lang = LANG_MAP.get(ext, "py")
        model = TypewriterModel()
        model.panels = [PanelLayout(title=fname, text=text, lang=lang, speed_factor=1.0, accent="#bd93f9")]
        words = model.total_chars / 5
        model.target_duration = max(2.0, words / max(self._settings.wpm, 1) * 60.0)
        self.preview.set_model(model)

class EmojiWidget(BaseCodeExportWidget):
    def _build_mode_controls(self, h):
        h.addWidget(self._section_label("WPM"))
        self.wpm_sp = QSpinBox(); self.wpm_sp.setRange(10, 500); self.wpm_sp.setSingleStep(5)
        self.wpm_sp.setFixedWidth(80); h.addWidget(self.wpm_sp); h.addSpacing(12)
        h.addWidget(self._section_label("FONT"))
        self.font_sp = QSpinBox(); self.font_sp.setRange(8, 24); self.font_sp.setFixedWidth(60)
        h.addWidget(self.font_sp); h.addSpacing(8)
        h.addWidget(self._section_label("COLOR"))
        self.color_cb = QComboBox(); self.color_cb.addItems(["Rainbow", "Solid"])
        self.color_cb.setFixedWidth(100); h.addWidget(self.color_cb)
        self.wpm_sp.valueChanged.connect(self._on_wpm_changed)
        self.font_sp.valueChanged.connect(self._update_ascii_settings)
        self.color_cb.currentTextChanged.connect(self._update_ascii_settings)

    def _apply_settings(self, s):
        super()._apply_settings(s)
        self.wpm_sp.setValue(s.wpm)
        self.font_sp.setValue(s.ascii_font_size)
        self.color_cb.setCurrentText(s.ascii_color_mode)

    def _update_ascii_settings(self):
        if self.preview._renderer:
            self.preview._renderer.ascii_font_size = self.font_sp.value()
            self.preview._renderer.ascii_color_mode = self.color_cb.currentText()
            if self.preview.model.panels:
                self.preview._renderer.build_layout(self.preview.model)
                self.preview._repaint_preview()

    def _load_text(self, text, fname):
        ext = os.path.splitext(fname)[1].lower(); lang = LANG_MAP.get(ext, "py")
        model = TypewriterModel()
        model.panels = [PanelLayout(title=fname, text=text, lang="ascii", speed_factor=1.0, accent="#bd93f9")]
        words = model.total_chars / 5
        model.target_duration = max(2.0, words / max(self._settings.wpm, 1) * 60.0)
        self.preview.set_model(model)

MODE_WIDGETS = {
    "project1_jr_vs_sr": JrVsSrWidget,
    "project2_multi_window": MultiWindowWidget,
    "project3_codetyping": YouTubeWidget,
    "project4_text": TextWidget,
    "project5_emoji_ascii": EmojiWidget,
}

def launch_studio_app() -> int:
    setup_project_logging("studio_launcher")
    log.info("Starting TypingAnimStudio Launcher…")

    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(APP_QSS)

    main_win = QMainWindow()
    main_win.setWindowTitle("TypingAnimStudio")
    main_win.resize(1440, 920)
    main_win.setMinimumSize(1100, 700)

    central = QWidget()
    main_win.setCentralWidget(central)
    layout = QVBoxLayout(central)
    layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(0)

    header = QFrame(); header.setObjectName("header"); header.setFixedHeight(64)
    hl = QHBoxLayout(header); hl.setContentsMargins(24, 10, 24, 10)
    brand_box = QVBoxLayout(); brand_box.setSpacing(0)
    brand = QLabel("TypingAnimStudio"); brand.setObjectName("brand")
    sub = QLabel("EXPERT TYPOGRAPHIC VIDEO GENERATION"); sub.setObjectName("brandSub")
    brand_box.addWidget(brand); brand_box.addWidget(sub)
    hl.addLayout(brand_box); hl.addStretch()
    hl.addWidget(QLabel("Project Mode"))
    mode_selector = QComboBox(); mode_selector.addItems(list(PROJECT_MODES.keys()))
    mode_selector.setMinimumWidth(280); hl.addWidget(mode_selector)
    
    settings_btn = QPushButton("⚙ Settings"); settings_btn.setObjectName("primary")
    hl.addWidget(settings_btn); layout.addWidget(header)

    def get_widget_class(mode_name):
        key = PROJECT_MODES[mode_name].settings_key
        return MODE_WIDGETS.get(key, BaseCodeExportWidget)

    studio_widget = get_widget_class(mode_selector.currentText())(mode_selector.currentText())
    layout.addWidget(studio_widget, 1)

    def on_mode_change(new_mode: str):
        nonlocal studio_widget
        studio_widget.cleanup(); studio_widget.deleteLater()
        new_settings_key = PROJECT_MODES[new_mode].settings_key
        setup_project_logging(new_settings_key); log.info("Switched to mode: %s", new_mode)
        cls = get_widget_class(new_mode)
        studio_widget = cls(new_mode)
        layout.addWidget(studio_widget, 1)
        main_win.setWindowTitle(f"TypingAnimStudio · {new_mode}")

    def on_settings_click():
        dlg = SettingsDialog(studio_widget._settings, main_win)
        if dlg.exec() == QDialog.Accepted:
            new_s = dlg.get_settings()
            studio_widget._settings = new_s
            studio_widget._apply_settings(new_s)
            studio_widget.cleanup()

    mode_selector.currentTextChanged.connect(on_mode_change)
    settings_btn.clicked.connect(on_settings_click)
    main_win.show()

    def on_close(event):
        studio_widget.cleanup(); event.accept()
    main_win.closeEvent = on_close
    return app.exec()
