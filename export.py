from __future__ import annotations
from typing import Optional, List, Tuple, Any
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, Future
import os, math, threading, subprocess, shutil, numpy as np, wave
from PySide6.QtCore import (Qt, QTimer, QElapsedTimer, QUrl, QBuffer, QIODevice, Signal, Slot, QObject, QThread, QPointF)
from PySide6.QtGui import (QImage, QPixmap, QColor, QKeyEvent, QPainter, QFont)
from PySide6.QtWidgets import (QWidget, QLabel, QHBoxLayout, QVBoxLayout, QPushButton, QSlider, QSizePolicy, QGraphicsDropShadowEffect, QFrame, QComboBox, QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog, QMessageBox, QFormLayout, QGroupBox, QMainWindow, QScrollArea)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from .core import (EXPORT_FORMATS, ENCODERS, RenderingError, FFmpegError, log, _subprocess_startup_info, temp_directory, THEMES, SETTINGS_FILE, INPUT_DIR, OUTPUT_DIR, format_duration)
from .rendering import (Tokenizer, TypingProfile, TypingAnimator, KeyboardOverlay, CodeRenderer, MultiPaneRenderer, TextTypingAnimator, TextRenderer)
from .audio import SimpleSoundGen, _pcm_to_wav_bytes

@dataclass(slots=True)
class ExportConfig:
    junior_code: str; senior_code: str; name: str; fmt: str; res: str; theme: str; j_font: str; s_font: str; font_size_auto: bool; font_size: int; chrome: bool; ln: bool; cursor_glow: bool; watermark: bool; bg_image_path: str; show_kb: bool; kb_layout: str; kb_pos: str; kb_op: float; j_wpm: int; j_pause: float; s_wpm: int; s_pause: float; start_pause: float; end_pause: float; lang: str; pane_layout: str; pad: int; gap: int; target_duration: float = 0.0

class ExportConfigBuilder:
    def __init__(self): self._fields: dict = {}
    def junior_code(self, code: str) -> "ExportConfigBuilder": self._fields["junior_code"] = code; return self
    def senior_code(self, code: str) -> "ExportConfigBuilder": self._fields["senior_code"] = code; return self
    def name(self, n: str) -> "ExportConfigBuilder": self._fields["name"] = n; return self
    def fmt(self, f: str) -> "ExportConfigBuilder": self._fields["fmt"] = f; return self
    def res(self, r: str) -> "ExportConfigBuilder": self._fields["res"] = r; return self
    def theme(self, t: str) -> "ExportConfigBuilder": self._fields["theme"] = t; return self
    def j_font(self, f: str) -> "ExportConfigBuilder": self._fields["j_font"] = f; return self
    def s_font(self, f: str) -> "ExportConfigBuilder": self._fields["s_font"] = f; return self
    def font_size_auto(self, v: bool) -> "ExportConfigBuilder": self._fields["font_size_auto"] = v; return self
    def font_size(self, s: int) -> "ExportConfigBuilder": self._fields["font_size"] = s; return self
    def chrome(self, c: bool) -> "ExportConfigBuilder": self._fields["chrome"] = c; return self
    def ln(self, l: bool) -> "ExportConfigBuilder": self._fields["ln"] = l; return self
    def cursor_glow(self, g: bool) -> "ExportConfigBuilder": self._fields["cursor_glow"] = g; return self
    def watermark(self, w: bool) -> "ExportConfigBuilder": self._fields["watermark"] = w; return self
    def watermark_text(self, w: str) -> "ExportConfigBuilder": self._fields["watermark_text"] = w; return self
    def bg_image_path(self, p: str) -> "ExportConfigBuilder": self._fields["bg_image_path"] = p; return self
    def show_kb(self, s: bool) -> "ExportConfigBuilder": self._fields["show_kb"] = s; return self
    def kb_layout(self, l: str) -> "ExportConfigBuilder": self._fields["kb_layout"] = l; return self
    def kb_pos(self, p: str) -> "ExportConfigBuilder": self._fields["kb_pos"] = p; return self
    def kb_op(self, o: float) -> "ExportConfigBuilder": self._fields["kb_op"] = o; return self
    def j_wpm(self, w: int) -> "ExportConfigBuilder": self._fields["j_wpm"] = w; return self
    def j_pause(self, p: float) -> "ExportConfigBuilder": self._fields["j_pause"] = p; return self
    def s_wpm(self, w: int) -> "ExportConfigBuilder": self._fields["s_wpm"] = w; return self
    def s_pause(self, p: float) -> "ExportConfigBuilder": self._fields["s_pause"] = p; return self
    def start_pause(self, s: float) -> "ExportConfigBuilder": self._fields["start_pause"] = s; return self
    def end_pause(self, e: float) -> "ExportConfigBuilder": self._fields["end_pause"] = e; return self
    def lang(self, l: str) -> "ExportConfigBuilder": self._fields["lang"] = l; return self
    def pane_layout(self, p: str) -> "ExportConfigBuilder": self._fields["pane_layout"] = p; return self
    def pad(self, p: int) -> "ExportConfigBuilder": self._fields["pad"] = p; return self
    def gap(self, g: int) -> "ExportConfigBuilder": self._fields["gap"] = g; return self
    def target_duration(self, t: float) -> "ExportConfigBuilder": self._fields["target_duration"] = t; return self
    def build(self) -> ExportConfig: return ExportConfig(**self._fields)

def _build_panes_from_config(cfg: ExportConfig) -> MultiPaneRenderer:
    fmt_data = EXPORT_FORMATS.get(cfg.fmt, EXPORT_FORMATS["YouTube (16:9)"]); w, h = fmt_data["resolutions"].get(cfg.res, (1920, 1080)); theme = THEMES[cfg.theme]
    jp = TypingProfile(name="Junior Dev", wpm=cfg.j_wpm, pause_freq=cfg.j_pause, start_pause=cfg.start_pause, end_pause=cfg.end_pause, error_chance=0.04)
    sp = TypingProfile(name="Senior Dev", wpm=cfg.s_wpm, pause_freq=cfg.s_pause, start_pause=cfg.start_pause, end_pause=cfg.end_pause, error_chance=0.01)
    if cfg.target_duration > 0:
        for profile, code in [(jp, cfg.junior_code), (sp, cfg.senior_code)]:
            req_wpm = TypingAnimator.find_wpm_for_target_duration(code, cfg.target_duration, profile.start_pause, profile.end_pause, profile.error_chance); profile.wpm = max(10, min(500, req_wpm))
    panes: List[Tuple[CodeRenderer, TypingAnimator]] = []
    for i, (code, profile, title, accent_key) in enumerate([(cfg.junior_code, jp, f"👶 Junior Dev — {cfg.name}", "junior_accent"), (cfg.senior_code, sp, f"🧓 Senior Dev — {cfg.name}", "senior_accent")]):
        match cfg.pane_layout:
            case "Side by Side (50/50)": pw, ph = (w - cfg.gap) // 2, h
            case "Stacked (50/50)": pw, ph = w, (h - cfg.gap) // 2
            case "Junior Big (70/30)": pw = int((w - cfg.gap) * 0.7) if i == 0 else (w - cfg.gap) - int((w - cfg.gap) * 0.7); ph = h
            case "Senior Big (70/30)": pw = int((w - cfg.gap) * 0.3) if i == 0 else (w - cfg.gap) - int((w - cfg.gap) * 0.3); ph = h
            case _: pw, ph = (w - cfg.gap) // 2, h
        language = cfg.lang
        if language == "Auto": ext = os.path.splitext(cfg.name)[1].lower(); ext_map = {".py": "Python", ".js": "JavaScript", ".cpp": "CFamily", ".cs": "CSharp"}; language = ext_map.get(ext, "Text")
        code_lines = code.count("\n") + 1; kb_overlay = None; kb_h = 0
        if cfg.show_kb: kb_overlay = KeyboardOverlay(pw, ph, cfg.kb_layout, theme, cfg.kb_op, (ph - 2 * cfg.pad) // 3, cfg.kb_pos); kb_h = kb_overlay.height_needed()
        current_font = cfg.j_font if i == 0 else cfg.s_font
        font_size = (CodeRenderer.auto_font_size(code_lines, pw, ph, cfg.pad, cfg.chrome, cfg.ln, 4, code, current_font, kb_h) if cfg.font_size_auto else max(8, int(cfg.font_size)))
        renderer = CodeRenderer(width=pw, height=ph, theme_name=cfg.theme, font_family=current_font, font_size=font_size, title_text=title, language=language, keyboard_overlay=kb_overlay, padding=cfg.pad, show_window_chrome=cfg.chrome, show_line_numbers=cfg.ln, bg_image_path=cfg.bg_image_path if i == 0 else None, total_code_lines=code_lines, cursor_glow=cfg.cursor_glow, show_watermark=cfg.watermark and i == 0, accent_color=getattr(theme, accent_key, "#7aa2f7"), code=code)
        animator = TypingAnimator(code, profile, seed=i * 1000 + 42); panes.append((renderer, animator))
    return MultiPaneRenderer(panes=panes, frame_w=w, frame_h=h, num_panes=2, pane_layout=cfg.pane_layout, gap=cfg.gap)

class VideoExporter(QThread):
    progress = Signal(int); status = Signal(str); finished_ok = Signal(str); error = Signal(str); shorts_ready = Signal(bool, float)
    CHUNK_DURATION: float = 300.0
    def __init__(self, export_config: ExportConfig, output: str, fps: int = 30, sound_params: Optional[Tuple[str, bool, float]] = None, sound_gens: Optional[List[SimpleSoundGen]] = None, volume: float = 0.5, encoder_name: str = "YouTube Pro (H.264/AAC)", bgm_path: Optional[str] = None, bgm_volume: float = 0.3, bgm_duck: float = 0.6, generate_thumbnail: bool = True, generate_chapters: bool = True, parent=None):
        super().__init__(parent); self.setObjectName("VideoExporter"); self.config = export_config; self.output = output; self.fps = fps; self.sound_params = sound_params; self.sound_gens = sound_gens; self.volume = volume; self.encoder_name = encoder_name; self.bgm_path = bgm_path; self.bgm_volume = bgm_volume; self.bgm_duck = bgm_duck; self.generate_thumbnail = generate_thumbnail; self.generate_chapters = generate_chapters; self.multi_pane = _build_panes_from_config(self.config); self._cancel = threading.Event(); self._last_duration = 0.0; self.finished.connect(self.deleteLater)
    def cancel(self) -> None: self._cancel.set()
    def is_cancelled(self) -> bool: return self._cancel.is_set()
    def run(self) -> None:
        audio_executor: Optional[ThreadPoolExecutor] = None
        try:
            anim_dur = self.multi_pane.duration(); self._last_duration = anim_dur; total_dur = self.config.target_duration if self.config.target_duration > 0 else anim_dur; num_chunks = max(1, math.ceil(total_dur / self.CHUNK_DURATION))
            with temp_directory() as tmp_dir:
                audio_executor = ThreadPoolExecutor(max_workers=1) if self.sound_params or self.sound_gens else None; audio_future: Optional[Future] = None; final_audio = os.path.join(tmp_dir, "final_audio.wav")
                if audio_executor:
                    self.status.emit("Starting audio generation...")
                    if self.sound_gens: audio_future = audio_executor.submit(self._gen_full_audio_per_pane, self.multi_pane, final_audio)
                    else:
                        all_ts = self.multi_pane.char_timestamps_all()
                        if all_ts: audio_future = audio_executor.submit(self._gen_full_audio, all_ts, final_audio)
                video_chunks: List[str] = []
                for c_idx in range(num_chunks):
                    if self._cancel.is_set(): break
                    start_t = c_idx * self.CHUNK_DURATION; end_t = min(total_dur, start_t + self.CHUNK_DURATION); start_frame = int(start_t * self.fps); n_chunk = math.ceil(end_t * self.fps) - start_frame
                    self.status.emit(f"Rendering Video Chunk {c_idx + 1}/{num_chunks}..."); chunk_vid = os.path.join(tmp_dir, f"vid_{c_idx}.mp4")
                    if not self._render_chunk_video(start_frame, n_chunk, chunk_vid): raise RenderingError(f"Failed to render video for chunk {c_idx + 1}")
                    video_chunks.append(chunk_vid); self.progress.emit(int(((c_idx + 1) / num_chunks) * 80))
                if self._cancel.is_set(): self.error.emit("Cancelled"); return
                self.status.emit("Stitching video chunks..."); final_video = os.path.join(tmp_dir, "final_video.mp4"); self._concat_files(video_chunks, final_video)
                if audio_future:
                    self.status.emit("Waiting for audio generation to finish..."); audio_ok = audio_future.result()
                    if audio_ok: self.status.emit("Muxing final video and audio..."); self._mux_final(final_video, final_audio, self.output)
                    else: shutil.move(final_video, self.output)
                else: shutil.move(final_video, self.output)
                self.progress.emit(100); self.status.emit(f"Done → {self.output}"); self.finished_ok.emit(self.output)
        except Exception as e: self.error.emit(str(e))
        finally:
            if audio_executor: audio_executor.shutdown(wait=True)
    def _gen_full_audio(self, ts: List[Tuple[float, str]], filepath: str) -> bool:
        try:
            preset, stereo, reverb_amt = self.sound_params; sg = SimpleSoundGen(sr=44100, preset=preset, stereo=stereo, reverb_amt=reverb_amt); sg.generate_track(ts, filepath, self.volume)
            return os.path.exists(filepath) and os.path.getsize(filepath) > 44
        except Exception: return False
    def _gen_full_audio_per_pane(self, mp: MultiPaneRenderer, filepath: str) -> bool:
        try:
            pcm_tracks = []
            is_stereo = any(g.stereo for g in self.sound_gens if g)
            for pane_idx, (renderer, animator) in enumerate(mp.panes):
                gen = self.sound_gens[pane_idx] if pane_idx < len(self.sound_gens) else self.sound_gens[0]
                if gen:
                    pane_ts = animator.char_timestamps()
                    if pane_ts: pcm = gen.generate_pcm(pane_ts, self.volume); pcm_tracks.append(pcm)
            if not pcm_tracks: return False
            max_len = max(len(t) for t in pcm_tracks)
            if is_stereo:
                n_l = (max_len + 1) // 2
                mixed_l = np.zeros(n_l, dtype=np.float32); mixed_r = np.zeros(n_l, dtype=np.float32)
                for pane_idx, f in enumerate(pcm_tracks):
                    gen = self.sound_gens[pane_idx] if pane_idx < len(self.sound_gens) else self.sound_gens[0]
                    if gen and gen.stereo and len(f) > 1:
                        l = f[0::2]; r = f[1::2]
                        mixed_l[:len(l)] += l; mixed_r[:len(r)] += r
                    else:
                        mixed_l[:len(f)] += f; mixed_r[:len(f)] += f
                pk = max(float(np.max(np.abs(mixed_l))), float(np.max(np.abs(mixed_r))))
                if pk > 0: mixed_l *= 0.95 / pk; mixed_r *= 0.95 / pk
                out = np.empty(max_len, dtype=np.int16)
                out[0::2] = np.clip(mixed_l * 32767, -32768, 32767).astype(np.int16); out[1::2] = np.clip(mixed_r * 32767, -32768, 32767).astype(np.int16)
            else:
                mixed = np.zeros(max_len, dtype=np.float32)
                for pane_idx, f in enumerate(pcm_tracks):
                    gen = self.sound_gens[pane_idx] if pane_idx < len(self.sound_gens) else self.sound_gens[0]
                    if gen and gen.stereo and len(f) > 1:
                        half = len(f) // 2
                        mixed[:half] += (f[0::2] + f[1::2]) * 0.5
                    else: mixed[:len(f)] += f
                pk = float(np.max(np.abs(mixed)))
                if pk > 0: mixed *= 0.95 / pk
                out = np.clip(mixed * 32767, -32768, 32767).astype(np.int16)
            with wave.open(filepath, "w") as wf: wf.setnchannels(2 if is_stereo else 1); wf.setsampwidth(2); wf.setframerate(self.sound_gens[0].sr); wf.writeframes(out.tobytes())
            return os.path.exists(filepath) and os.path.getsize(filepath) > 44
        except Exception as e: log.error("Per-pane audio failed: %s", e); return False
    def _concat_files(self, paths: List[str], out_path: str) -> None:
        concat_path = os.path.join(os.path.dirname(out_path), "concat_list.txt")
        with open(concat_path, "w", encoding="utf-8") as f:
            for p in paths: f.write(f"file '{p}'\n")
        cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_path, "-c", "copy", out_path]
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, startupinfo=_subprocess_startup_info())
        _, stderr = proc.communicate(timeout=max(120, len(paths) * 60))
        if proc.returncode != 0: raise FFmpegError(f"Concat failed: {stderr.decode(errors='ignore')[-400:]}")
    def _mux_final(self, vid_path: str, aud_path: str, out_path: str) -> None:
        if self.bgm_path and os.path.exists(self.bgm_path):
            cmd = ["ffmpeg", "-y", "-i", vid_path, "-i", aud_path, "-i", self.bgm_path, "-c:v", "copy", "-filter_complex", f"[2:a]highpass=f=60,lowpass=f=5500,volume={self.bgm_volume},afade=t=in:st=0:d=2[bgm_eq];[bgm_eq][1:a]sidechaincompress=threshold=0.05:ratio=10:attack=0.015:release=0.3:makeup=2[bgm_duck];[1:a][bgm_duck]amix=inputs=2:duration=longest:normalize=0,alimiter=limit=0.95[aout]", "-map", "0:v", "-map", "[aout]", "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-movflags", "+faststart", out_path]
        else:
            cmd = ["ffmpeg", "-y", "-i", vid_path, "-i", aud_path, "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-movflags", "+faststart", out_path]
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, startupinfo=_subprocess_startup_info())
        _, stderr = proc.communicate(timeout=max(120, os.path.getsize(vid_path) // (1024 * 1024) * 2))
        if proc.returncode != 0: raise FFmpegError(f"Final mux failed: {stderr.decode(errors='ignore')[-400:]}")
    def _render_chunk_video(self, start_frame: int, n_frames: int, out_path: str, allow_fallback: bool = True) -> bool:
        w, h, fps = self.multi_pane.frame_w, self.multi_pane.frame_h, self.fps
        cmd = ["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "bgra", "-s", f"{w}x{h}", "-r", str(fps), "-i", "pipe:0"]
        enc_cfg = ENCODERS.get(self.encoder_name, ENCODERS["YouTube Pro (H.264/AAC)"]); cmd += enc_cfg["base"]
        if enc_cfg.get("use_dynamic_gop", False): gop = int(fps * 2); cmd += ["-g", str(gop), "-keyint_min", str(gop), "-sc_threshold", "0"]
        if enc_cfg.get("use_dynamic_vbv", False): pixels = w * h; maxrate = int((pixels / 2073600.0) * 12000000); cmd += ["-maxrate", f"{maxrate}", "-bufsize", f"{maxrate * 2}"]
        if enc_cfg.get("color_tags", False): cmd += ["-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]
        cmd += ["-an", out_path]
        try: proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, startupinfo=_subprocess_startup_info())
        except FileNotFoundError: self.error.emit("FFmpeg not found on PATH."); return False
        scratch = QImage(w, h, QImage.Format_RGB32)
        for fi in range(n_frames):
            if self._cancel.is_set(): break
            t = (start_frame + fi) / self.fps; state = self.multi_pane.compute_state(t); qimg = self.multi_pane.render_frame(t, scratch, precomputed_state=state); ptr = qimg.constBits()
            try: img_bytes = bytes(ptr)
            except TypeError: img_bytes = ptr.tobytes()
            except AttributeError: ptr.setsize(qimg.sizeInBytes()); img_bytes = bytes(ptr)
            try: proc.stdin.write(img_bytes); proc.stdin.flush()
            except BrokenPipeError:
                proc.kill(); proc.wait(timeout=5); return False
        proc.stdin.close()
        try: proc.wait(timeout=600)
        except subprocess.TimeoutExpired:
            proc.kill(); proc.wait(timeout=5); return False
        if proc.returncode != 0:
            if allow_fallback and self.encoder_name != "x264 (CPU, Fast)":
                self.encoder_name = "x264 (CPU, Fast)"; self.status.emit("Hardware encoder failed. Retrying with CPU fallback..."); return self._render_chunk_video(start_frame, n_frames, out_path, allow_fallback=False)
            return False
        return True

# =========================================================
# Abstracted Batch Export Window
# =========================================================
class BatchTableWidget(QTableWidget):
    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if event.button() != Qt.LeftButton: return
        pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        item = self.itemAt(pos)
        if not item: return
        if item.column() != 0:
            ci = self.item(item.row(), 0)
            if ci is not None:
                ns = Qt.CheckState.Checked if ci.checkState() == Qt.CheckState.Unchecked else Qt.CheckState.Unchecked
                ci.setCheckState(ns)

class BatchExportWindowBase(QMainWindow):
    SETTINGS_KEY = "base"
    def __init__(self, title: str, supported_exts: frozenset):
        super().__init__()
        self.setWindowTitle(title)
        self.setMinimumSize(1200, 800); self.resize(1400, 900)
        self._items = []; self._item_paths = set(); self._exporter = None
        self._loading_settings = False
        self._batch_queue = []; self._batch_total = 0; self._batch_done = 0
        self._batch_cancel = False; self._current_item = None; self._preview_idx = 0
        self._audio_player = QMediaPlayer(self); self._audio_out = QAudioOutput(self)
        self._audio_player.setAudioOutput(self._audio_out)
        self.SUPPORTED_EXTS = supported_exts
        self._build_ui()
        self._connect_signals()
        self._load_settings()
        self._scan_input_dir()
        QTimer.singleShot(300, self._rebuild_preview)

    def _build_ui(self):
        central = QWidget(); self.setCentralWidget(central); root = QHBoxLayout(central); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        left = QWidget(); left.setFixedWidth(360); ll = QVBoxLayout(left); ll.setContentsMargins(0,0,0,0); ll.setSpacing(0)
        br1 = QHBoxLayout()
        self.scan_btn = QPushButton("🔄 Scan"); self.scan_btn.clicked.connect(self._scan_input_dir); br1.addWidget(self.scan_btn)
        self.add_btn = QPushButton("➕ Add..."); self.add_btn.clicked.connect(self._add_files); br1.addWidget(self.add_btn)
        br1.addStretch()
        self.all_btn = QPushButton("✅ All"); self.all_btn.setFixedWidth(52); self.all_btn.clicked.connect(self._select_all); br1.addWidget(self.all_btn)
        self.none_btn = QPushButton("❌ None"); self.none_btn.setFixedWidth(58); self.none_btn.clicked.connect(self._select_none); br1.addWidget(self.none_btn)
        ll.addLayout(br1)
        self.file_table = BatchTableWidget(0, 5)
        self.file_table.setHorizontalHeaderLabels(["", "File", "Lang", "Est", "Status"])
        self.file_table.setSelectionBehavior(QTableWidget.SelectRows); self.file_table.setEditTriggers(QTableWidget.NoEditTriggers); self.file_table.verticalHeader().setVisible(False)
        hdr = self.file_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Fixed); hdr.resizeSection(0, 32)
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.Fixed); hdr.resizeSection(2, 55)
        hdr.setSectionResizeMode(3, QHeaderView.Fixed); hdr.resizeSection(3, 55)
        hdr.setSectionResizeMode(4, QHeaderView.Fixed); hdr.resizeSection(4, 90)
        self.file_table.itemChanged.connect(self._on_item_changed); ll.addWidget(self.file_table)
        self.stats_label = QLabel("0 files · 0 selected · 0:00 total")
        self.stats_label.setStyleSheet("color: #a6adc8; font-size: 11px; padding: 6px 10px; background: #181825; border-top: 1px solid #11111b;")
        ll.addWidget(self.stats_label)
        root.addWidget(left)
        right = QWidget(); rl = QVBoxLayout(right); rl.setContentsMargins(0,0,0,0); rl.setSpacing(0)
        self.preview = PreviewWidget(); self.preview.attach_audio(self._audio_player, self._audio_out)
        self.preview.prev_file_requested.connect(self._preview_prev_file)
        self.preview.next_file_requested.connect(self._preview_next_file)
        rl.addWidget(self.preview, 1)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); container = QWidget(); cl = QVBoxLayout(container)
        self.settings_grp = QGroupBox(self._settings_group_title()); fl = QFormLayout(self.settings_grp)
        self._build_settings_ui(fl)
        cl.addWidget(self.settings_grp)
        btn_row = QHBoxLayout()
        self.export_btn = QPushButton("🎬 Export Checked"); self.export_btn.setStyleSheet("QPushButton { background: #a6e3a1; color: #1e1e2e; font-weight: bold; border: none; border-radius: 6px; padding: 10px; } QPushButton:hover { background: #94e2d5; }"); self.export_btn.clicked.connect(self._start_export); btn_row.addWidget(self.export_btn, 1)
        self.cancel_btn = QPushButton("⏹ Cancel Batch"); self.cancel_btn.setStyleSheet("QPushButton { background: #f38ba8; color: #1e1e2e; font-weight: bold; border: none; border-radius: 6px; padding: 10px; } QPushButton:hover { background: #eba0ac; }"); self.cancel_btn.clicked.connect(self._cancel_export); self.cancel_btn.hide(); btn_row.addWidget(self.cancel_btn, 1)
        cl.addLayout(btn_row)
        scroll.setWidget(container); rl.addWidget(scroll); root.addWidget(right, 1)

    def _settings_group_title(self) -> str: return "Appearance & Export"
    def _build_settings_ui(self, form: QFormLayout) -> None: pass
    def _get_settings_dict(self) -> dict: return {}
    def _apply_settings(self, s: dict) -> None: pass
    def _load_item(self, path: str): return None
    def _recompute_est(self, item) -> None: pass
    def _get_lang_for_item(self, item) -> str: return "Text"
    def _get_est_tooltip(self, item) -> str: return f"Est: {item.est_duration:.1f}s"
    def _get_output_name(self, item) -> str: return f"{os.path.splitext(os.path.basename(item.path))[0]}.mp4"
    def _build_panes(self): pass
    def _rebuild_preview(self, *_) -> None: pass
    def _make_exporter(self, item, output_path): return None
    def _connect_signals(self) -> None: pass
    def _on_param_changed(self, *_) -> None:
        self._update_est_durations(); self._rebuild_preview()

    def _scan_input_dir(self) -> None:
        self._items.clear(); self._item_paths.clear(); self._preview_idx = 0
        if not os.path.isdir(str(INPUT_DIR)): return
        for fname in sorted(os.listdir(str(INPUT_DIR))):
            if os.path.splitext(fname)[1].lower() not in self.SUPPORTED_EXTS: continue
            p = os.path.join(str(INPUT_DIR), fname)
            item = self._load_item(p)
            if item: self._items.append(item); self._item_paths.add(p)
        self._refresh_table(); self._update_stats(); self._rebuild_preview()

    def _add_files(self) -> None:
        es = " ".join(f"*{e}" for e in sorted(self.SUPPORTED_EXTS))
        paths, _ = QFileDialog.getOpenFileNames(self, "Select Files", "", f"Files ({es})")
        added = False
        for p in paths:
            if p in self._item_paths: continue
            item = self._load_item(p)
            if item: self._items.append(item); self._item_paths.add(p); added = True
        if added: self._preview_idx = 0; self._refresh_table(); self._update_stats(); self._rebuild_preview()

    def _select_all(self) -> None:
        for it in self._items: it.checked = True
        self._preview_idx = 0; self._refresh_table(); self._update_stats(); self._rebuild_preview()

    def _select_none(self) -> None:
        for it in self._items: it.checked = False
        self._preview_idx = 0; self._refresh_table(); self._update_stats(); self._rebuild_preview()

    def _update_est_durations(self) -> None:
        for it in self._items: self._recompute_est(it)
        self._refresh_table(); self._update_stats()

    def _refresh_table(self) -> None:
        self.file_table.blockSignals(True); self.file_table.setRowCount(len(self._items))
        for i, item in enumerate(self._items):
            chk = QTableWidgetItem(); chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled); chk.setCheckState(Qt.CheckState.Checked if item.checked else Qt.CheckState.Unchecked); self.file_table.setItem(i, 0, chk)
            self.file_table.setItem(i, 1, QTableWidgetItem(os.path.basename(item.path)))
            self.file_table.setItem(i, 2, QTableWidgetItem(self._get_lang_for_item(item)[:8]))
            est_item = QTableWidgetItem(format_duration(item.est_duration))
            est_item.setToolTip(self._get_est_tooltip(item))
            self.file_table.setItem(i, 3, est_item)
            self.file_table.setItem(i, 4, QTableWidgetItem(item.status))
        self.file_table.blockSignals(False)

    def _update_stats(self) -> None:
        total = len(self._items); sel = sum(1 for it in self._items if it.checked)
        sel_dur = sum(it.est_duration for it in self._items if it.checked)
        self.stats_label.setText(f"{total} files · {sel} selected · {format_duration(sel_dur)} total")

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() == 0 and 0 <= item.row() < len(self._items):
            self._items[item.row()].checked = (item.checkState() == Qt.CheckState.Checked)
            self._preview_idx = 0; self._update_stats(); self._rebuild_preview()

    def _preview_prev_file(self):
        checked = [it for it in self._items if it.checked]
        if len(checked) < 2: return
        self._preview_idx = (self._preview_idx - 1) % len(checked); self._rebuild_preview()

    def _preview_next_file(self):
        checked = [it for it in self._items if it.checked]
        if len(checked) < 2: return
        self._preview_idx = (self._preview_idx + 1) % len(checked); self._rebuild_preview()

    def _start_export(self) -> None:
        checked = [it for it in self._items if it.checked]
        if not checked: QMessageBox.information(self, "Nothing Selected", "Check at least one file."); return
        for item in self._items:
            item.status = "Queued" if item in checked else "Pending"; item.output_path = None
        self._refresh_table()
        self._batch_queue = list(checked); self._batch_total = len(checked); self._batch_done = 0; self._batch_cancel = False
        self.export_btn.hide(); self.cancel_btn.show()
        self._process_next_in_batch()

    def _process_next_in_batch(self) -> None:
        if self._batch_cancel: self._on_batch_complete(True); return
        if not self._batch_queue: self._on_batch_complete(False); return
        item = self._batch_queue.pop(0); self._batch_done += 1; self._current_item = item
        item.status = f"Rendering 0% ({self._batch_done}/{self._batch_total})"; self._refresh_table()
        output_path = os.path.join(str(OUTPUT_DIR), self._get_output_name(item))
        self._exporter = self._make_exporter(item, output_path)
        self._exporter.progress.connect(lambda p: self._update_progress(item, p))
        self._exporter.status.connect(lambda s: log.info(s))
        self._exporter.finished_ok.connect(lambda p: self._on_export_done(item, p))
        self._exporter.error.connect(lambda e: self._on_export_failed(item, e))
        self._exporter.start()

    def _update_progress(self, item, val: int) -> None:
        item.status = f"Rendering {val}% ({self._batch_done}/{self._batch_total})"; self._refresh_table()

    def _on_export_done(self, item, path: str) -> None:
        item.status = "Done"; item.output_path = path; self._refresh_table(); self._process_next_in_batch()

    def _on_export_failed(self, item, err: str) -> None:
        item.status = "Failed"; self._refresh_table(); QMessageBox.warning(self, "Export Failed", f"{os.path.basename(item.path)}:\n{err}"); self._process_next_in_batch()

    def _cancel_export(self) -> None:
        self._batch_cancel = True
        if self._exporter: self._exporter.cancel()
        self._batch_queue.clear()
        if self._current_item: self._current_item.status = "Cancelled"; self._refresh_table()

    def _on_batch_complete(self, was_cancelled: bool) -> None:
        self.export_btn.show(); self.cancel_btn.hide(); self._current_item = None
        done = sum(1 for it in self._items if it.status == "Done"); failed = sum(1 for it in self._items if it.status == "Failed")
        msg = f"Done: {done}, Failed: {failed}" + (f", Cancelled: {self._batch_total - done - failed}" if was_cancelled else "")
        QMessageBox.information(self, "Batch Cancelled" if was_cancelled else "Batch Complete", msg)

    def _load_settings(self) -> None:
        import json
        self._loading_settings = True
        try:
            if os.path.exists(str(SETTINGS_FILE)):
                with open(str(SETTINGS_FILE), "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._apply_settings(data.get(self.SETTINGS_KEY, {}))
        except Exception as e:
            log.warning("Failed to load settings: %s", e)
        self._loading_settings = False

    def _save_settings(self) -> None:
        import json
        data = {}
        if os.path.exists(str(SETTINGS_FILE)):
            try:
                with open(str(SETTINGS_FILE), "r", encoding="utf-8") as f: data = json.load(f)
            except Exception: pass
        data[self.SETTINGS_KEY] = self._get_settings_dict()
        try:
            with open(str(SETTINGS_FILE), "w", encoding="utf-8") as f: json.dump(data, f, indent=2)
        except Exception as e:
            log.warning("Failed to save settings: %s", e)

    def closeEvent(self, event) -> None:
        if self._exporter: self._exporter.cancel()
        self._save_settings(); self.preview.stop(); super().closeEvent(event)

# =========================================================
# Text / Emoji Typing Window (For Project 4 & 5)
# =========================================================
class TextTypingWindow(BatchExportWindowBase):
    def __init__(self, title: str, supported_exts: frozenset, examples_key: str):
        self.examples_key = examples_key
        super().__init__(title, supported_exts)
        ensure_examples_for_project(examples_key)

    def _settings_group_title(self) -> str: return "Text & Emoji Typing Settings"

    def _build_settings_ui(self, form: QFormLayout) -> None:
        self.theme_cb = QComboBox(); self.theme_cb.addItems(list(THEMES.keys())); self.theme_cb.setCurrentText("Dracula"); form.addRow("Theme:", self.theme_cb)
        self.export_format_cb = QComboBox(); self.export_format_cb.addItems(list(EXPORT_FORMATS.keys())); form.addRow("Format:", self.export_format_cb)
        self.sound_preset_cb = QComboBox(); self.sound_preset_cb.addItems(list(SOUND_PRESETS.keys())); form.addRow("Audio Preset:", self.sound_preset_cb)
        self.encoder_cb = QComboBox(); self.encoder_cb.addItems(list(ENCODERS.keys())); form.addRow("Encoder:", self.encoder_cb)
        self.kb_chk = QCheckBox("Show Keyboard"); self.kb_chk.setChecked(True); form.addRow(self.kb_chk)
        self.watermark_chk = QCheckBox("Watermark"); form.addRow(self.watermark_chk)
        self.watermark_edit = QLineEdit(); self.watermark_edit.setPlaceholderText("Watermark Text"); form.addRow("WM Text:", self.watermark_edit)
        self.wpm_sp = QSpinBox(); self.wpm_sp.setRange(30, 300); self.wpm_sp.setValue(100); form.addRow("WPM:", self.wpm_sp)
        self.auto_speed_chk = QCheckBox("Auto-Adjust Speed (< 3 min Shorts)"); self.auto_speed_chk.setChecked(False); form.addRow(self.auto_speed_chk)
        self.target_dur_sp = QDoubleSpinBox(); self.target_dur_sp.setRange(5.0, 600.0); self.target_dur_sp.setValue(59.0); self.target_dur_sp.setSuffix("s"); self.target_dur_sp.setSingleStep(1.0); form.addRow("Shorts Target:", self.target_dur_sp)
        for w in [self.theme_cb, self.export_format_cb, self.sound_preset_cb, self.encoder_cb, self.wpm_sp, self.target_dur_sp, self.watermark_edit]:
            if hasattr(w, 'currentTextChanged'): w.currentTextChanged.connect(self._on_param_changed)
            if hasattr(w, 'valueChanged'): w.valueChanged.connect(self._on_param_changed)
        self.kb_chk.toggled.connect(self._on_param_changed)
        self.watermark_chk.toggled.connect(self._on_param_changed)
        self.auto_speed_chk.toggled.connect(self._on_param_changed)

    def _load_item(self, path: str) -> Optional[FileItem]:
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f: code = f.read()
        except Exception: return None
        item = FileItem(path=path, checked=True, code=code, size_bytes=os.path.getsize(path))
        self._recompute_est(item)
        return item

    def _recompute_est(self, item: FileItem) -> None:
        if self.auto_speed_chk.isChecked() and "Shorts" in self.export_format_cb.currentText():
            est_wpm = max(30, min(300, int(len(item.code) / max(0.1, self.target_dur_sp.value() * 5 / 60))))
            item.est_duration = TextTypingAnimator.estimate_duration(item.code, est_wpm, 0.5, 1.5, 0.01)
        else:
            item.est_duration = TextTypingAnimator.estimate_duration(item.code, self.wpm_sp.value(), 0.5, 1.5, 0.01)

    def _get_lang_for_item(self, item: FileItem) -> str: return EXT_TO_LANGUAGE.get(os.path.splitext(item.path)[1].lower(), "Text")
    def _get_est_tooltip(self, item: FileItem) -> str: return f"Est: {item.est_duration:.1f}s\nLines: {item.code.count(chr(10))+1}"
    def _get_output_name(self, item: FileItem) -> str: return f"{os.path.splitext(os.path.basename(item.path))[0]}_text.mp4"

    def _build_panes(self):
        fmt = self.export_format_cb.currentText(); fmt_data = EXPORT_FORMATS.get(fmt, EXPORT_FORMATS["YouTube (16:9)"]); res_name = "1080x1920" if "Shorts" in fmt else "1920x1080"; w, h = fmt_data["resolutions"].get(res_name, (1920, 1080)); theme = THEMES[self.theme_cb.currentText()]
        checked = [it for it in self._items if it.checked]
        if not checked: code = "# No files selected."; filename = "empty.txt"
        else: cur_item = checked[self._preview_idx]; code = cur_item.code; filename = os.path.basename(cur_item.path)
        lang = EXT_TO_LANGUAGE.get(os.path.splitext(filename)[1].lower(), "Text")
        wpm = self.wpm_sp.value()
        if self.auto_speed_chk.isChecked() and "Shorts" in fmt:
            wpm = TextTypingAnimator.find_wpm_for_target_duration(code, self.target_dur_sp.value(), 0.5, 1.5, 0.0)
        pw, ph = w, h
        kb_overlay = KeyboardOverlay(pw, ph, "QWERTY", theme, 0.82, (ph - 48) // 3, "bottom_center") if self.kb_chk.isChecked() else None
        fs = TextRenderer.auto_font_size(code.count("\n")+1, pw, ph, 24, True, True, 4, code, "Consolas", kb_overlay.height_needed() if kb_overlay else 0)
        wm_text = self.watermark_edit.text() if self.watermark_edit.text() else "Code Typing Studio"
        renderer = TextRenderer(pw, ph, self.theme_cb.currentText(), "Consolas", fs, True, True, 24, 4, filename, lang, kb_overlay, None, code.count("\n")+1, True, self.watermark_chk.isChecked())
        animator = TextTypingAnimator(code, wpm=wpm, start_pause=0.5, end_pause=1.5, typo_rate=0.0)
        return MultiPaneRenderer(panes=[(renderer, animator)], frame_w=w, frame_h=h, num_panes=1, pane_layout="Side by Side (50/50)")

    def _rebuild_preview(self, *_) -> None:
        if self._loading_settings: return
        checked = [it for it in self._items if it.checked]
        if not checked: self.preview.set_info("No files selected", 0.0, 0, 0, 0.0, 0.0, 0.0); return
        if self._preview_idx >= len(checked): self._preview_idx = 0
        cur_item = checked[self._preview_idx]
        self.preview.set_info(os.path.basename(cur_item.path), cur_item.est_duration, self._preview_idx + 1, len(checked), sum(i.est_duration for i in checked), min(i.est_duration for i in checked), max(i.est_duration for i in checked))
        mp = self._build_panes()
        self.preview.set_multi_pane(mp, SimpleSoundGen(sr=44100, preset=self.sound_preset_cb.currentText(), stereo=True, reverb_amt=0.1, target_lufs=-14.0), 0.5)

    def _make_exporter(self, item: FileItem, output_path: str) -> VideoExporter:
        fmt = self.export_format_cb.currentText(); res_name = "1080x1920" if "Shorts" in fmt else "1920x1080"
        lang = EXT_TO_LANGUAGE.get(os.path.splitext(item.path)[1].lower(), "Text")
        j_wpm = self.wpm_sp.value()
        if self.auto_speed_chk.isChecked() and "Shorts" in fmt:
            j_wpm = TextTypingAnimator.find_wpm_for_target_duration(item.code, self.target_dur_sp.value(), 0.5, 1.5, 0.0)
        wm_text = self.watermark_edit.text() if self.watermark_edit.text() else "Code Typing Studio"
        cfg = (ExportConfigBuilder().junior_code(item.code).senior_code(item.code).name(os.path.basename(item.path)).fmt(fmt).res(res_name).theme(self.theme_cb.currentText()).j_font("Consolas").s_font("Consolas").font_size_auto(True).font_size(22).chrome(True).ln(True).cursor_glow(True).watermark(self.watermark_chk.isChecked()).watermark_text(wm_text).bg_image_path("").show_kb(self.kb_chk.isChecked()).kb_layout("QWERTY").kb_pos("bottom_center").kb_op(0.82).j_wpm(j_wpm).j_pause(0.15).s_wpm(j_wpm).s_pause(0.05).start_pause(0.5).end_pause(1.5).lang(lang).pane_layout("Side by Side (50/50)").pad(24).gap(20).build())
        return VideoExporter(cfg, output_path, 30, (self.sound_preset_cb.currentText(), True, 0.1), None, 0.5, self.encoder_cb.currentText(), generate_thumbnail=True, generate_chapters=True)

    def _get_settings_dict(self) -> dict:
        return {"theme": self.theme_cb.currentText(), "fmt": self.export_format_cb.currentText(), "audio": self.sound_preset_cb.currentText(), "encoder": self.encoder_cb.currentText(), "kb": self.kb_chk.isChecked(), "wm": self.watermark_chk.isChecked(), "wm_text": self.watermark_edit.text(), "wpm": self.wpm_sp.value(), "auto_speed": self.auto_speed_chk.isChecked(), "target_dur": self.target_dur_sp.value()}
        
    def _apply_settings(self, s: dict) -> None:
        if "theme" in s: self.theme_cb.setCurrentText(s["theme"])
        if "fmt" in s: self.export_format_cb.setCurrentText(s["fmt"])
        if "audio" in s: self.sound_preset_cb.setCurrentText(s["audio"])
        if "encoder" in s: self.encoder_cb.setCurrentText(s["encoder"])
        if "kb" in s: self.kb_chk.setChecked(s["kb"])
        if "wm" in s: self.watermark_chk.setChecked(s["wm"])
        if "wm_text" in s: self.watermark_edit.setText(s["wm_text"])
        if "wpm" in s: self.wpm_sp.setValue(s["wpm"])
        if "auto_speed" in s: self.auto_speed_chk.setChecked(s["auto_speed"])
        if "target_dur" in s: self.target_dur_sp.setValue(s["target_dur"])
