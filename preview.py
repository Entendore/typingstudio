from __future__ import annotations
from typing import Optional
from PySide6.QtCore import Qt, QTimer, QElapsedTimer, QUrl, QBuffer, QIODevice, Signal, QObject, QPointF
from PySide6.QtGui import QImage, QPixmap, QColor, QKeyEvent, QPainter, QFont
from PySide6.QtWidgets import QWidget, QLabel, QHBoxLayout, QVBoxLayout, QPushButton, QSlider, QSizePolicy, QGraphicsDropShadowEffect, QFrame, QComboBox
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from .core import _format_eta
from .rendering import MultiPaneRenderer
from .audio import SimpleSoundGen, _pcm_to_wav_bytes
from .core import log

def _fmt_dur(s: float) -> str:
    if s is None or s < 0 or s != s: return "--:--"
    total = int(round(s)); h, rem = divmod(total, 3600); m, sec = divmod(rem, 60)
    if h > 0: return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"

class PreviewImageLabel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap: Optional[QPixmap] = None
        self._zoom: float = 1.0
        self._pan: QPointF = QPointF(0, 0)
        self._dragging: bool = False
        self._last_pos = QPointF()
        self.setMinimumSize(480, 270)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet("background: #11111b; border-radius: 8px;")
    def set_preview_image(self, qimg: QImage) -> None:
        self._pixmap = QPixmap.fromImage(qimg); self.update()
    def reset_view(self):
        self._zoom = 1.0; self._pan = QPointF(0, 0); self.update()
    def paintEvent(self, event) -> None:
        p = QPainter(self); p.setRenderHint(QPainter.SmoothPixmapTransform)
        if self._pixmap is None:
            p.setPen(QColor("#585b70")); p.setFont(QFont("Arial", 12))
            p.drawText(self.rect(), Qt.AlignCenter, "Select a file to preview\nor drop files into the batch panel"); return
        base_w, base_h = self.width(), self.height()
        pix_w, pix_h = self._pixmap.width(), self._pixmap.height()
        scale = min(base_w / pix_w, base_h / pix_h)
        render_w, render_h = int(pix_w * scale), int(pix_h * scale)
        render_x, render_y = (base_w - render_w) // 2, (base_h - render_h) // 2
        p.translate(self._pan); p.scale(self._zoom, self._zoom)
        p.drawPixmap(render_x, render_y, render_w, render_h, self._pixmap)
    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y() / 120.0
            self._zoom = max(1.0, min(5.0, self._zoom + delta * 0.2))
            if self._zoom == 1.0: self._pan = QPointF(0, 0)
            self.update()
        else: super().wheelEvent(event)
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._zoom > 1.0:
            self._dragging = True; self._last_pos = event.position(); self.setCursor(Qt.ClosedHandCursor)
        else: super().mousePressEvent(event)
    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            self._pan += event.position() - self._last_pos; self._last_pos = event.position(); self.update()
        else: super().mouseMoveEvent(event)
    def mouseReleaseEvent(self, event) -> None:
        if self._dragging: self._dragging = False; self.setCursor(Qt.ArrowCursor)
        else: super().mouseReleaseEvent(event)
    def mouseDoubleClickEvent(self, event) -> None: self.reset_view()

class PreviewController(QObject):
    state_changed = Signal(float, float)
    audio_failed = Signal(str)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.multi_pane: Optional[MultiPaneRenderer] = None
        self.scratch_image: Optional[QImage] = None
        self.sound_gen: Optional[SimpleSoundGen] = None
        self.audio_volume: float = 0.5
        self.progress: float = 0.0
        self.anim_t: float = 0.0
        self.animating: bool = False
        self.loop: bool = False
        self.target_duration: float = 0.0
        self.speed: float = 1.0
        self._cached_pcm: Optional[np.ndarray] = None
        self._cached_pcm_hash: Optional[tuple] = None
        self._timer = QTimer(self); self._timer.setTimerType(Qt.PreciseTimer); self._timer.setInterval(16); self._timer.timeout.connect(self._advance)
        self._clock = QElapsedTimer()
        self._audio_player: Optional[QMediaPlayer] = None
        self._audio_out: Optional[QAudioOutput] = None
        self._audio_buf: Optional[QBuffer] = None
    def attach_audio(self, player: QMediaPlayer, output: QAudioOutput) -> None:
        self._audio_player = player; self._audio_out = output
    def set_renderer(self, mp: MultiPaneRenderer, scratch: Optional[QImage] = None) -> None:
        self.multi_pane = mp
        self.scratch_image = scratch or QImage(mp.frame_w, mp.frame_h, QImage.Format_RGB32)
    def set_sound(self, sg: Optional[SimpleSoundGen], volume: float = 0.5) -> None:
        self.sound_gen = sg; self.audio_volume = max(0.0, min(1.0, volume))
        self._cached_pcm = None; self._cached_pcm_hash = None
    def total_duration(self) -> float:
        if self.multi_pane is None: return 0.0
        if self.target_duration > 0: return self.target_duration
        return self.multi_pane.duration()
    def play(self) -> None:
        if self.multi_pane is None: return
        total = self.total_duration()
        if self.progress >= 0.999: self.progress, self.anim_t = 0.0, 0.0
        else: self.anim_t = total * self.progress
        self.animating = True; self._clock.start(); self._maybe_start_audio(); self._timer.start()
    def pause(self) -> None:
        self.animating = False; self._timer.stop(); self._stop_audio()
    def toggle(self) -> bool:
        if self.animating: self.pause(); return False
        self.play(); return True
    def seek(self, progress: float) -> None:
        self.pause(); self.progress = max(0.0, min(1.0, progress)); self.anim_t = self.total_duration() * self.progress
        self.state_changed.emit(self.anim_t, self.total_duration())
    def seek_delta(self, delta_seconds: float) -> None:
        total = self.total_duration()
        new_t = max(0.0, min(total, total * self.progress + delta_seconds))
        self.anim_t = new_t; self.progress = new_t / total if total > 0 else 0.0
        self.state_changed.emit(self.anim_t, total)
    def reset(self) -> None:
        self.pause(); self.progress = 0.0; self.anim_t = 0.0
        self.state_changed.emit(0.0, self.total_duration())
    def set_loop(self, enabled: bool) -> None: self.loop = enabled
    def set_speed(self, speed: float) -> None:
        self.speed = speed
        if self._audio_player is not None: self._audio_player.setPlaybackRate(speed)
    def render_frame_at(self, progress: float) -> Optional[QImage]:
        if self.multi_pane is None: return None
        total = self.total_duration()
        t = min(progress * total, self.multi_pane.duration())
        state = self.multi_pane.compute_state(t)
        return self.multi_pane.render_frame(t, self.scratch_image, precomputed_state=state)
    def _advance(self) -> None:
        dt = min(self._clock.restart() / 1000.0, 0.1)
        self.anim_t += dt * self.speed
        total = self.total_duration()
        if self.anim_t >= total:
            if self.loop: self.anim_t = 0.0; self._maybe_start_audio()
            else: self.anim_t = total; self.pause()
        self.progress = min(1.0, self.anim_t / total) if total > 0 else 0.0
        self.state_changed.emit(self.anim_t, total)
    def _maybe_start_audio(self) -> None:
        if self.sound_gen is None or self._audio_player is None: return
        try:
            ts = self.multi_pane.char_timestamps_all() if self.multi_pane else []
            if not ts: return
            cache_key = (id(self.sound_gen), len(ts), self.audio_volume)
            if self._cached_pcm_hash != cache_key or self._cached_pcm is None:
                self._cached_pcm = self.sound_gen.generate_pcm(ts, self.audio_volume)
                self._cached_pcm_hash = cache_key
            pcm = self._cached_pcm
            if len(pcm) == 0: return
            channels = 2 if self.sound_gen.stereo else 1
            wav_bytes = _pcm_to_wav_bytes(pcm, self.sound_gen.sr, channels)
            self._stop_audio()
            self._audio_buf = QBuffer(); self._audio_buf.setData(wav_bytes); self._audio_buf.open(QIODevice.ReadOnly)
            self._audio_out.setVolume(self.audio_volume)
            self._audio_player.setSourceDevice(self._audio_buf, QUrl())
            self._audio_player.setPlaybackRate(self.speed)
            self._audio_player.play()
        except Exception as e:
            log.warning("Preview audio failed: %s", e)
            self.audio_failed.emit(str(e))
    def _stop_audio(self) -> None:
        if self._audio_player is not None:
            self._audio_player.stop(); self._audio_player.setSource(QUrl())
        if self._audio_buf is not None:
            try: self._audio_buf.close()
            except Exception: pass
            self._audio_buf = None

class PreviewWidget(QWidget):
    progress_changed = Signal(float)
    play_toggled = Signal(bool)
    prev_file_requested = Signal()
    next_file_requested = Signal()
    def __init__(self, parent=None):
        super().__init__(parent)
        self.controller = PreviewController(self)
        self._build_ui()
        self.controller.state_changed.connect(self._on_state_changed)
        self.controller.audio_failed.connect(lambda e: log.warning("Preview audio: %s", e))
        self.setFocusPolicy(Qt.StrongFocus)
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self); layout.setContentsMargins(12, 12, 12, 12); layout.setSpacing(8)
        info_bar = QHBoxLayout(); info_bar.setSpacing(6)
        self.prev_preview_btn = QPushButton("◀"); self.prev_preview_btn.setFixedWidth(24); self.prev_preview_btn.setToolTip("Preview previous file (↑)"); self.prev_preview_btn.setEnabled(False); self.prev_preview_btn.clicked.connect(self.prev_file_requested.emit); info_bar.addWidget(self.prev_preview_btn)
        self.info_label = QLabel("No file selected"); self.info_label.setStyleSheet("color: #f9e2af; font-size: 11px; font-weight: bold; font-family: monospace;"); info_bar.addWidget(self.info_label)
        self.preview_idx_label = QLabel(""); self.preview_idx_label.setStyleSheet("color: #cdd6f4; font-size: 11px; font-family: monospace;"); info_bar.addWidget(self.preview_idx_label)
        self.next_preview_btn = QPushButton("▶"); self.next_preview_btn.setFixedWidth(24); self.next_preview_btn.setToolTip("Preview next file (↓)"); self.next_preview_btn.setEnabled(False); self.next_preview_btn.clicked.connect(self.next_file_requested.emit); info_bar.addWidget(self.next_preview_btn)
        info_bar.addStretch()
        self.batch_label = QLabel("📦 Batch: 0 files"); self.batch_label.setStyleSheet("color: #a6e3a1; font-size: 11px; font-weight: bold; font-family: monospace;"); info_bar.addWidget(self.batch_label)
        layout.addLayout(info_bar)
        video_frame = QFrame(); video_frame.setStyleSheet("QFrame { background: #11111b; border-radius: 8px; }")
        v_layout = QVBoxLayout(video_frame); v_layout.setContentsMargins(0, 0, 0, 0)
        self.image_label = PreviewImageLabel()
        shadow = QGraphicsDropShadowEffect(); shadow.setBlurRadius(20); shadow.setOffset(0, 4); shadow.setColor(QColor(0, 0, 0, 120))
        self.image_label.setGraphicsEffect(shadow); v_layout.addWidget(self.image_label, 1); layout.addWidget(video_frame, 1)
        stats = QHBoxLayout()
        self.time_label = QLabel("0:00 / 0:00"); self.time_label.setStyleSheet("color: #a6e3a1; font-size: 13px; font-weight: bold; font-family: monospace; padding-left: 4px;"); stats.addWidget(self.time_label)
        self.stats_label = QLabel(""); self.stats_label.setStyleSheet("color: #a6adc8; font-size: 11px; font-family: monospace;"); stats.addWidget(self.stats_label); stats.addStretch()
        self.pct_label = QLabel("0%"); self.pct_label.setStyleSheet("color: #89b4fa; font-size: 11px; font-weight: bold; font-family: monospace; padding-right: 4px;"); stats.addWidget(self.pct_label); layout.addLayout(stats)
        ctrl = QHBoxLayout(); ctrl.setSpacing(4)
        self.frame_back_btn = QPushButton("⏮"); self.frame_back_btn.setFixedWidth(36); self.frame_back_btn.setToolTip("Previous Frame (Shift+Left)"); self.frame_back_btn.clicked.connect(lambda: self.controller.seek_delta(-1 / 30)); ctrl.addWidget(self.frame_back_btn)
        self.slider = QSlider(Qt.Horizontal); self.slider.setRange(0, 1000); self.slider.setToolTip("Seek"); self.slider.valueChanged.connect(self._on_slider); ctrl.addWidget(self.slider, 1)
        self.frame_fwd_btn = QPushButton("⏭"); self.frame_fwd_btn.setFixedWidth(36); self.frame_fwd_btn.setToolTip("Next Frame (Shift+Right)"); self.frame_fwd_btn.clicked.connect(lambda: self.controller.seek_delta(1 / 30)); ctrl.addWidget(self.frame_fwd_btn)
        self.speed_cb = QComboBox(); self.speed_cb.addItems(["1.0x", "0.5x", "0.75x", "1.5x", "2.0x"]); self.speed_cb.setFixedWidth(65); self.speed_cb.setToolTip("Playback Speed"); self.speed_cb.currentTextChanged.connect(lambda txt: self.controller.set_speed(float(txt.replace('x', '')))); ctrl.addWidget(self.speed_cb)
        self.loop_btn = QPushButton("🔁"); self.loop_btn.setFixedWidth(36); self.loop_btn.setCheckable(True); self.loop_btn.setToolTip("Loop (L)"); self.loop_btn.toggled.connect(self.controller.set_loop); ctrl.addWidget(self.loop_btn)
        self.play_btn = QPushButton("▶ Animate"); self.play_btn.setFixedWidth(100); self.play_btn.setToolTip("Play/Pause (Space)")
        self.play_btn.setStyleSheet("QPushButton { background: #a6e3a1; color: #1e1e2e; font-weight: bold; border: none; border-radius: 6px; padding: 6px; } QPushButton:hover { background: #94e2d5; } QPushButton:pressed { background: #89b4fa; }")
        self.play_btn.clicked.connect(self._toggle_play); ctrl.addWidget(self.play_btn); layout.addLayout(ctrl)
        help_label = QLabel("Space: Play/Pause  ·  ←/→: Seek 1s (Shift=1 frame)  ·  L: Loop  ·  R: Reset  ·  ↑/↓: Change File  ·  Ctrl+Wheel: Zoom")
        help_label.setStyleSheet("color: #585b70; font-size: 10px;"); help_label.setAlignment(Qt.AlignCenter); layout.addWidget(help_label)
    def set_info(self, file_name: str, file_est: float, batch_idx: int, batch_count: int, batch_est: float, min_est: float = 0.0, max_est: float = 0.0) -> None:
        self.info_label.setText(f"📄 {file_name}  |  Est: {_fmt_dur(file_est)}")
        if batch_count > 0:
            self.preview_idx_label.setText(f"({batch_idx}/{batch_count})")
            self.batch_label.setText(f"📦 {batch_count} files | Total: {_fmt_dur(batch_est)} | Min: {_fmt_dur(min_est)} | Max: {_fmt_dur(max_est)}")
        else: self.preview_idx_label.setText(""); self.batch_label.setText("📦 Batch: 0 files")
        has_multiple = batch_count > 1
        self.prev_preview_btn.setEnabled(has_multiple); self.next_preview_btn.setEnabled(has_multiple)
    def set_multi_pane(self, mp: MultiPaneRenderer, sound_gen: Optional[SimpleSoundGen] = None, volume: float = 0.5) -> None:
        self.controller.set_renderer(mp); self.controller.set_sound(sound_gen, volume); self.controller.reset(); self.image_label.reset_view(); self._render_current()
    def attach_audio(self, player: QMediaPlayer, output: QAudioOutput) -> None: self.controller.attach_audio(player, output)
    def set_target_duration(self, seconds: float) -> None:
        self.controller.target_duration = max(0.0, seconds); self.controller.reset(); self._render_current()
    def stop(self) -> None: self.controller.pause()
    def _toggle_play(self) -> None:
        playing = self.controller.toggle()
        self.play_btn.setText("⏸ Pause" if playing else "▶ Animate")
        self.play_toggled.emit(playing)
    def _on_slider(self, value: int) -> None:
        self.controller.seek(value / 1000.0); self._render_current()
    def _on_state_changed(self, t: float, total: float) -> None:
        self._render_current()
        cur_m, cur_s = divmod(int(t), 60); tot_m, tot_s = divmod(int(total), 60)
        self.time_label.setText(f"{cur_m}:{cur_s:02d} / {tot_m}:{tot_s:02d}")
        self.pct_label.setText(f"{int(self.controller.progress * 100)}%")
        self.slider.blockSignals(True); self.slider.setValue(int(self.controller.progress * 1000)); self.slider.blockSignals(False)
        self.progress_changed.emit(self.controller.progress)
    def _render_current(self) -> None:
        qimg = self.controller.render_frame_at(self.controller.progress)
        if qimg is not None: self.image_label.set_preview_image(qimg)
    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key(); mod = event.modifiers()
        if key in (Qt.Key_Space, Qt.Key_Play, Qt.Key_MediaPlay):
            if not event.isAutoRepeat(): self._toggle_play()
        elif key == Qt.Key_Left:
            delta = 1.0/30.0 if (mod & Qt.ShiftModifier) else 1.0
            self.controller.seek_delta(-delta); self._render_current()
        elif key == Qt.Key_Right:
            delta = 1.0/30.0 if (mod & Qt.ShiftModifier) else 1.0
            self.controller.seek_delta(delta); self._render_current()
        elif key == Qt.Key_L:
            if not event.isAutoRepeat(): self.loop_btn.toggle()
        elif key == Qt.Key_R:
            if not event.isAutoRepeat(): self.controller.reset(); self.image_label.reset_view(); self._render_current()
        elif key == Qt.Key_Up:
            if not event.isAutoRepeat(): self.prev_file_requested.emit()
        elif key == Qt.Key_Down:
            if not event.isAutoRepeat(): self.next_file_requested.emit()
        elif (mod & Qt.ControlModifier) and key in (Qt.Key_Plus, Qt.Key_Equal):
            self.image_label._zoom = min(5.0, self.image_label._zoom + 0.2); self.image_label.update()
        elif (mod & Qt.ControlModifier) and key == Qt.Key_Minus:
            self.image_label._zoom = max(1.0, self.image_label._zoom - 0.2)
            if self.image_label._zoom == 1.0: self.image_label._pan = QPointF(0, 0)
            self.image_label.update()
        elif key == Qt.Key_0: self.image_label.reset_view()
        else: super().keyPressEvent(event)
