"""Reactive State Reducers, Pre-computed Layouts, Auto-Scroll, Audio Sync, and RAII UI Rendering."""
from __future__ import annotations
from dataclasses import dataclass, replace, field
from contextlib import contextmanager
from typing import Optional, Tuple, List, Dict, Any
import re, math, time

from PySide6.QtCore import Qt, QTimer, QElapsedTimer, Signal, QObject, QPointF, QRectF, QIODevice
from PySide6.QtGui import (QImage, QColor, QPainter, QFont, QFontMetrics, QPen, QBrush,
                          QLinearGradient, QPixmap, QRadialGradient, QPainterPath)
from PySide6.QtWidgets import QWidget, QLabel, QSizePolicy

from .core import THEMES, Theme, log
from .audio import SimpleSoundGen

class TypingAudioPlayer:
    def __init__(self, sr: int = 44100):
        self.sr = sr
        self.enabled = False
        self.gen = SimpleSoundGen(sr=sr)
        self._volume = 0.8
        try:
            from PySide6.QtMultimedia import QAudioSink, QAudioFormat
            self.format = QAudioFormat()
            self.format.setSampleRate(sr); self.format.setChannelCount(1)
            try: self.format.setSampleFormat(QAudioFormat.Int16)
            except AttributeError:
                self.format.setSampleSize(16)
                self.format.setSampleType(QAudioFormat.SignedInt)
                self.format.setByteOrder(QAudioFormat.LittleEndian)
            self.audio_sink = QAudioSink(self.format)
            self.audio_sink.setVolume(self._volume)
            self.output_io = self.audio_sink.start()
            self.enabled = True
        except Exception as e:
            log.warning("Audio playback disabled: %s", e)
            self.enabled = False
            
    def set_preset(self, preset: str): self.gen.set_preset(preset)
    def set_volume(self, vol: int):
        self._volume = max(0.0, min(1.0, vol / 100.0))
        if self.enabled: self.audio_sink.setVolume(self._volume)
        
    def play_keystroke(self, char: str = ''):
        if not self.enabled or self.output_io is None: return
        try:
            pcm = self.gen.generate_keystroke(char)
            if pcm.size > 0: self.output_io.write(pcm.tobytes())
        except Exception: pass

@dataclass(slots=True)
class TokenDraw:
    text: str; color: QColor; x_offset: float; char_count: int

@dataclass(slots=True)
class VisualLine:
    y_offset: float; tokens: List[TokenDraw]; total_chars: int

@dataclass(slots=True)
class PanelLayout:
    title: str = "main.py"; text: str = ""; lang: str = "py"
    speed_factor: float = 1.0; accent: str = "#bd93f9"
    visual_lines: List[VisualLine] = field(default_factory=list); total_chars: int = 0
    delay: float = 0.0

@dataclass(slots=True)
class TypewriterModel:
    panels: List[PanelLayout] = field(default_factory=list)
    target_duration: float = 5.0
    hud_title: str = ""
    hud_channel: str = ""
    
    @property
    def total_chars(self) -> int:
        return sum(p.total_chars for p in self.panels) or 1
        
    def get_char_at_progress(self, progress: float) -> str:
        if not self.panels: return ''
        p = self.panels[0]
        eff = max(0.0, min(1.0, progress * p.speed_factor))
        n_chars = int(eff * len(p.text))
        if n_chars > 0 and n_chars <= len(p.text):
            return p.text[n_chars - 1]
        return ''

KEYWORDS: Dict[str, set] = {
    "py": {"def","class","return","if","elif","else","for","while","import","from","as","try","except","finally","with","lambda","yield","pass","break","continue","raise","in","is","not","and","or","None","True","False","self","async","await","global","nonlocal","del","assert"},
    "js": {"function","return","if","else","for","while","const","let","var","class","extends","new","await","async","import","export","from","try","catch","finally","typeof","instanceof","this","null","undefined","true","false","of","in","yield"},
    "cpp": {"int","float","double","char","void","bool","auto","const","static","class","struct","public","private","protected","return","if","else","for","while","switch","case","break","continue","new","delete","namespace","using","template","typename","virtual","override","true","false","nullptr","unsigned","long","short"},
}

_TOKEN_RE = re.compile(
    r'(?P<comment>\#[^\n]*|//[^\n]*)'
    r'|(?P<string>"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|`(?:[^`\\]|\\.)*`)'
    r'|(?P<number>\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b)'
    r'|(?P<ident>[A-Za-z_][A-Za-z0-9_]*)'
    r'|(?P<other>[^\w\s])'
    r'|(?P<ws>\s+)',
)

def _dim(color: QColor, alpha: int = 180) -> QColor:
    c = QColor(color); c.setAlpha(alpha); return c

def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))

def tokenize_line(line: str, lang: str, theme: Theme) -> List[Tuple[str, QColor]]:
    out: List[Tuple[str, QColor]] = []
    kw = KEYWORDS.get(lang, KEYWORDS["py"])
    fg = QColor(theme.foreground)
    for m in _TOKEN_RE.finditer(line):
        kind = m.lastgroup; text = m.group()
        if kind == "comment": out.append((text, _dim(QColor("#6272a4"))))
        elif kind == "string": out.append((text, QColor(theme.string)))
        elif kind == "number": out.append((text, QColor(theme.function)))
        elif kind == "ident":
            if text in kw: out.append((text, QColor(theme.keyword)))
            else:
                rest = line[m.end():].lstrip()
                out.append((text, QColor(theme.function) if rest.startswith("(") else fg))
        elif kind == "other": out.append((text, _dim(fg, 220)))
        else: out.append((text, fg))
    return out

@dataclass(frozen=True, slots=True)
class PreviewState:
    progress: float = 0.0; anim_t: float = 0.0; animating: bool = False
    loop: bool = False; speed: float = 1.0; target_duration: float = 5.0

def preview_reducer(state: PreviewState, action: Tuple[str, Any]) -> PreviewState:
    action_type, payload = action
    match action_type:
        case "TICK":
            if not state.animating: return state
            dt = payload; total = state.target_duration
            new_t = state.anim_t + (dt * state.speed)
            if new_t >= total:
                if state.loop: return replace(state, anim_t=0.0, progress=0.0)
                return replace(state, anim_t=total, progress=1.0, animating=False)
            return replace(state, anim_t=new_t, progress=new_t / total if total > 0 else 0.0)
        case "SEEK":
            p = _clamp(payload)
            return replace(state, progress=p, anim_t=p * state.target_duration, animating=False)
        case "PLAY_PAUSE":
            if state.progress >= 1.0: return replace(state, progress=0.0, anim_t=0.0, animating=True)
            return replace(state, animating=not state.animating)
        case "RESTART": return replace(state, progress=0.0, anim_t=0.0, animating=True)
        case "SET_SPEED": return replace(state, speed=_clamp(payload, 0.25, 4.0))
        case "SET_LOOP": return replace(state, loop=bool(payload))
        case "SET_DURATION": return replace(state, target_duration=max(0.5, float(payload)))
    return state

@contextmanager
def qt_painter_context(target: QImage):
    p = QPainter(target)
    try:
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.save()
        yield p
    finally:
        p.restore()
        p.end()

def _pick_font(families: List[str], point_size: int, mono: bool = True) -> QFont:
    f = QFont()
    try: f.setFamilies(list(families))
    except Exception: f.setFamily(families[0])
    f.setPointSize(point_size)
    f.setStyleStrategy(QFont.PreferAntialias)
    if mono:
        f.setStyleHint(QFont.Monospace)
        f.setFixedPitch(True)
    return f

class CodeRenderer:
    def __init__(self, width: int, height: int, theme_name: str = "Dracula", mode_key: str = "project3_codetyping"):
        self.w, self.h = width, height
        self.theme_name = theme_name; self.theme = THEMES[theme_name]
        self.mode_key = mode_key
        self.font = _pick_font(["JetBrains Mono","Fira Code","Cascadia Code","Consolas","Menlo","DejaVu Sans Mono","Monospace"], 16)
        self.title_font = _pick_font(["Inter","Segoe UI","SF Pro Display","Helvetica","Arial"], 11, mono=False)
        self.fm = QFontMetrics(self.font)
        self.line_height = self.fm.height() + 6
        self._smooth_cx = -1.0; self._smooth_cy = -1.0
        self.text_font_size = 17
        self.ascii_font_size = 14
        self.ascii_color_mode = "Rainbow"

    def update_theme(self, theme_name: str):
        self.theme_name = theme_name; self.theme = THEMES[theme_name]

    def reset_caret_easing(self):
        self._smooth_cx = -1.0; self._smooth_cy = -1.0

    def build_layout(self, model: TypewriterModel):
        for panel in model.panels:
            layout: List[VisualLine] = []
            cy = 14 + self.fm.ascent()
            if self.mode_key == "project4_text":
                font = _pick_font(["Inter","Segoe UI","Helvetica","Arial"], self.text_font_size, mono=False)
                fm = QFontMetrics(font); line_h = fm.height() + 10; inner_w = self.w - 124
                cy = 30 + fm.ascent()
                for raw in panel.text.split("\n"):
                    if not raw:
                        layout.append(VisualLine(y_offset=cy, tokens=[], total_chars=1)); cy += line_h; continue
                    cur = ""
                    for word in raw.split(" "):
                        test = cur + (" " if cur else "") + word
                        if fm.horizontalAdvance(test) > inner_w:
                            if cur: layout.append(self._map_text_line(cur, cy, font, True, 0))
                            cur = word; cy += line_h
                        else: cur = test
                    if cur: layout.append(self._map_text_line(cur, cy, font, True, 0)); cy += line_h
            elif self.mode_key == "project5_emoji_ascii":
                font = _pick_font(["JetBrains Mono","Cascadia Code","Consolas","Menlo","Monospace"], self.ascii_font_size)
                fm = QFontMetrics(font); line_h = fm.height() + 4
                cy = 20 + fm.ascent()
                for line in panel.text.split("\n"):
                    layout.append(self._map_text_line(line, cy, font, False, 0)); cy += line_h
            else:
                for li, line in enumerate(panel.text.split("\n")):
                    layout.append(self._map_text_line(line, cy, self.font, False, 44)); cy += self.line_height
            panel.visual_lines = layout; panel.total_chars = len(panel.text)

    def _map_text_line(self, text: str, y: float, font: QFont, is_text_mode: bool, line_no_w: int) -> VisualLine:
        fm = QFontMetrics(font); text_x = (32 if is_text_mode or self.mode_key == "project5_emoji_ascii" else 10 + line_no_w)
        toks = tokenize_line(text, "text" if is_text_mode else "py", self.theme)
        vdtoks = []; tx = text_x
        for tok_text, tok_col in toks:
            vdtoks.append(TokenDraw(tok_text, tok_col, tx, len(tok_text)))
            tx += fm.horizontalAdvance(tok_text)
        return VisualLine(y_offset=y, tokens=vdtoks, total_chars=len(text) + 1)

    def _draw_background(self, p: QPainter):
        bg = QColor(self.theme.background)
        grad = QLinearGradient(0, 0, 0, self.h)
        grad.setColorAt(0.0, bg.lighter(112)); grad.setColorAt(1.0, bg.darker(110))
        p.fillRect(0, 0, self.w, self.h, QBrush(grad))
        rg = QRadialGradient(self.w / 2, self.h / 2, max(self.w, self.h) * 0.7)
        rg.setColorAt(0.0, QColor(0, 0, 0, 0)); rg.setColorAt(1.0, QColor(0, 0, 0, 90))
        p.fillRect(0, 0, self.w, self.h, QBrush(rg))

    def _draw_card(self, p: QPainter, x: float, y: float, w: float, h: float, radius: float = 10.0):
        p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, 110))
        p.drawRoundedRect(QRectF(x + 6, y + 8, w, h), radius + 2, radius + 2)
        card = QColor(self.theme.background).lighter(116)
        p.setBrush(card); p.setPen(QPen(QColor(255, 255, 255, 18), 1))
        p.drawRoundedRect(QRectF(x, y, w, h), radius, radius)

    def _draw_header(self, p: QPainter, x: float, y: float, w: float, h: float, title: str, accent: str = "#bd93f9"):
        for i, c in enumerate(["#ff5f56", "#ffbd2e", "#27c93f"]):
            p.setBrush(QColor(c)); p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(x + 16 + i * 16, y + h / 2), 5.5, 5.5)
        p.setPen(_dim(QColor(self.theme.foreground), 230)); p.setFont(self.title_font)
        p.drawText(QRectF(x + 70, y, w - 80, h), Qt.AlignVCenter | Qt.AlignLeft, title)
        p.setPen(Qt.NoPen); p.setBrush(QColor(accent)); p.drawRect(QRectF(x, y + h - 1, w, 2))

    def _draw_code(self, p: QPainter, x: float, y: float, w: float, h: float, panel: PanelLayout, progress: float, with_line_numbers: bool = True) -> Optional[Tuple[float, float, float, float]]:
        if panel.delay > 0.0 and progress < panel.delay:
            return None
        eff_progress = (progress - panel.delay) / (1.0 - panel.delay) if panel.delay > 0.0 else progress
        eff = _clamp(eff_progress * panel.speed_factor); n_chars = int(eff * panel.total_chars)
        
        font = self.font
        if self.mode_key == "project4_text": font = _pick_font(["Inter"], self.text_font_size, mono=False)
        elif self.mode_key == "project5_emoji_ascii": font = _pick_font(["JetBrains Mono"], self.ascii_font_size)
        
        p.setFont(font); p.setClipRect(QRectF(x, y, w, h))
        caret_y = y; chars_consumed = 0
        fm = QFontMetrics(font)
        
        for vline in panel.visual_lines:
            if chars_consumed + vline.total_chars <= n_chars:
                chars_consumed += vline.total_chars; caret_y = vline.y_offset
            else:
                caret_y = vline.y_offset; break
                
        scroll_offset = 0.0; bottom_margin = y + h - 50
        if caret_y > bottom_margin: scroll_offset = caret_y - bottom_margin
        p.translate(0, -scroll_offset)

        tx = x
        for li, vline in enumerate(panel.visual_lines):
            line_y = vline.y_offset
            if line_y - fm.ascent() + scroll_offset > y + h: break
            if line_y + fm.height() + scroll_offset < y: continue
            if with_line_numbers and self.mode_key not in ["project4_text", "project5_emoji_ascii"]:
                p.setPen(_dim(QColor(self.theme.foreground), 60))
                p.drawText(QRectF(x + 6, line_y - fm.ascent(), 36, self.line_height), Qt.AlignVCenter | Qt.AlignRight, str(li + 1))
            tx = x + (10 + 44 if with_line_numbers and self.mode_key not in ["project4_text", "project5_emoji_ascii"] else 32)
            
            if self.mode_key == "project5_emoji_ascii" and self.ascii_color_mode == "Rainbow":
                hue = (li * 13) % 360
                line_fg = QColor.fromHsl(hue, 110, 200)
                for tok in vline.tokens: tok.color = line_fg

            for tok in vline.tokens:
                if chars_consumed + tok.char_count <= n_chars:
                    p.setPen(tok.color); p.drawText(QPointF(tx + tok.x_offset, line_y), tok.text); chars_consumed += tok.char_count
                else:
                    remaining = n_chars - chars_consumed
                    if remaining > 0:
                        partial = tok.text[:remaining]
                        p.setPen(tok.color); p.drawText(QPointF(tx + tok.x_offset, line_y), partial); chars_consumed += remaining
                        cx = tx + tok.x_offset + fm.horizontalAdvance(partial); cy = line_y
                        caret_pos = (cx + 1, cy - fm.ascent() + 2, fm.height() - 4, scroll_offset)
                    break
            else:
                chars_consumed += 1; continue
        p.translate(0, scroll_offset); p.setClipping(False)
        if chars_consumed >= n_chars and panel.visual_lines:
            last = panel.visual_lines[-1]
            return (tx + 1, last.y_offset - fm.ascent() + 2, fm.height() - 4, scroll_offset)
        return caret_pos

    def _draw_caret(self, p: QPainter, pos: Optional[Tuple[float, float, float, float]]):
        if pos is None: return
        tx, ty, h, scroll = pos
        if self._smooth_cx < 0:
            self._smooth_cx = tx; self._smooth_cy = ty
        else:
            self._smooth_cx += (tx - self._smooth_cx) * 0.3
            self._smooth_cy += (ty - self._smooth_cy) * 0.3
        if (time.time() % 1.0) >= 0.6: return
        p.setPen(Qt.NoPen)
        for i, alpha in enumerate([20, 40, 80]):
            p.setBrush(QColor(255, 255, 255, alpha))
            p.drawRoundedRect(QRectF(self._smooth_cx - (3-i), self._smooth_cy, 2 + (2*i), h), 2, 2)
        p.setBrush(QColor(self.theme.foreground))
        p.drawRect(QRectF(self._smooth_cx, self._smooth_cy, 2, h))

    def _draw_hud(self, p: QPainter, title: str, channel: str):
        bar = QRectF(0, self.h - 76, self.w, 76)
        grad = QLinearGradient(0, bar.top(), 0, bar.bottom())
        grad.setColorAt(0, QColor(0, 0, 0, 0)); grad.setColorAt(1, QColor(0, 0, 0, 180))
        p.fillRect(bar, QBrush(grad))
        p.setPen(QColor(255, 255, 255, 235)); p.setFont(_pick_font(["Inter","Segoe UI","Helvetica"], 18, mono=False))
        p.drawText(QRectF(20, self.h - 56, self.w - 220, 30), Qt.AlignVCenter | Qt.AlignLeft, title)
        p.setFont(_pick_font(["Inter","Segoe UI","Helvetica"], 11, mono=False)); p.setPen(QColor(220, 220, 220, 200))
        p.drawText(QRectF(20, self.h - 28, self.w - 220, 20), Qt.AlignVCenter | Qt.AlignLeft, channel)
        p.setPen(QColor(255, 255, 255, 60))
        p.drawText(QRectF(self.w - 200, self.h - 36, 180, 20), Qt.AlignVCenter | Qt.AlignRight, "TypingAnimStudio")

    def _draw_empty_state(self, p: QPainter, msg: str):
        p.setPen(_dim(QColor(self.theme.foreground), 120)); p.setFont(_pick_font(["Inter","Segoe UI","Helvetica"], 16, mono=False))
        p.drawText(QRectF(0, 0, self.w, self.h), Qt.AlignCenter, msg)

    def _layout_youtube(self, p: QPainter, m: TypewriterModel, progress: float):
        pad = 24; x, y, w, h = pad, pad, self.w - pad * 2, self.h - pad * 2 - 60
        panel = m.panels[0]
        self._draw_card(p, x, y, w, h); self._draw_header(p, x + 8, y + 8, w - 16, 32, panel.title, panel.accent)
        caret = self._draw_code(p, x + 8, y + 48, w - 16, h - 56, panel, progress, True)
        self._draw_caret(p, caret)
        self._draw_hud(p, m.hud_title, m.hud_channel)

    def _layout_jr_vs_sr(self, p: QPainter, m: TypewriterModel, progress: float):
        pad, gap = 24, 20; pw = (self.w - pad * 2 - gap) / 2
        meta = [("JUNIOR DEV", "#ff5f56", 1.0), ("SENIOR DEV", "#27c93f", 1.6)]
        p.setFont(_pick_font(["Inter","Segoe UI","Helvetica"], 12, mono=False))
        for i, (lbl, col, _) in enumerate(meta):
            x = pad + i * (pw + gap)
            p.setPen(Qt.NoPen); p.setBrush(QColor(col)); p.drawRoundedRect(QRectF(x, 12, 6, 24), 3, 3)
            p.setPen(_dim(QColor(self.theme.foreground), 230))
            p.drawText(QRectF(x + 14, 8, pw - 14, 28), Qt.AlignVCenter | Qt.AlignLeft, lbl)
        y_top = 48; h = self.h - y_top - pad
        for i, (lbl, col, _) in enumerate(meta):
            x = pad + i * (pw + gap)
            self._draw_card(p, x, y_top, pw, h)
            self._draw_header(p, x + 8, y_top + 8, pw - 16, 32, m.panels[i].title if i < len(m.panels) else "—", col)
            caret = self._draw_code(p, x + 8, y_top + 48, pw - 16, h - 56, m.panels[i] if i < len(m.panels) else PanelLayout(), progress, True)
            self._draw_caret(p, caret)

    def _layout_multi(self, p: QPainter, m: TypewriterModel, progress: float):
        pad, gap = 20, 16; cw = (self.w - pad * 2 - gap) / 2; ch = (self.h - pad * 2 - gap) / 2
        accents = ["#bd93f9", "#8be9fd", "#ffb86c", "#50fa7b"]
        for i in range(min(4, len(m.panels))):
            r, c = i // 2, i % 2; x = pad + c * (cw + gap); y = pad + r * (ch + gap)
            self._draw_card(p, x, y, cw, ch); self._draw_header(p, x + 8, y + 8, cw - 16, 28, m.panels[i].title, accents[i])
            caret = self._draw_code(p, x + 8, y + 42, cw - 16, ch - 50, m.panels[i], progress, True)
            self._draw_caret(p, caret)

    def _layout_text(self, p: QPainter, m: TypewriterModel, progress: float):
        pad = 60; x, y, w, h = pad, pad, self.w - pad * 2, self.h - pad * 2
        self._draw_card(p, x, y, w, h, radius=14)
        caret = self._draw_code(p, x, y, w, h, m.panels[0], progress, False)
        self._draw_caret(p, caret)

    def _layout_emoji(self, p: QPainter, m: TypewriterModel, progress: float):
        pad = 24; x, y, w, h = pad, pad, self.w - pad * 2, self.h - pad * 2
        self._draw_card(p, x, y, w, h)
        caret = self._draw_code(p, x, y, w, h, m.panels[0], progress, False)
        self._draw_caret(p, caret)

    def render_frame(self, progress: float, model: TypewriterModel, target: Optional[QImage] = None) -> QImage:
        img = target if target is not None else QImage(self.w, self.h, QImage.Format_RGB32)
        with qt_painter_context(img) as p:
            self._draw_background(p)
            if not model.panels or not model.panels[0].visual_lines:
                self._draw_empty_state(p, "Select a file to preview"); return img
            mk = self.mode_key
            if mk == "project1_jr_vs_sr":    self._layout_jr_vs_sr(p, model, progress)
            elif mk == "project2_multi_window": self._layout_multi(p, model, progress)
            elif mk == "project3_codetyping":   self._layout_youtube(p, model, progress)
            elif mk == "project4_text":         self._layout_text(p, model, progress)
            elif mk == "project5_emoji_ascii":  self._layout_emoji(p, model, progress)
            else:                               self._layout_youtube(p, model, progress)
        return img

class PreviewController(QObject):
    state_changed = Signal(PreviewState)
    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = PreviewState(target_duration=5.0)
        self._timer = QTimer(self); self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(16); self._timer.timeout.connect(self._on_tick)
        self._clock = QElapsedTimer()

    def dispatch(self, action: Tuple[str, Any]):
        self._state = preview_reducer(self._state, action)
        if self._state.animating:
            if not self._clock.isValid(): self._clock.start()
            self._timer.start()
        else: self._timer.stop()
        self.state_changed.emit(self._state)

    def _on_tick(self):
        dt = min(self._clock.restart() / 1000.0, 0.1); self.dispatch(("TICK", dt))

class PreviewWidget(QWidget):
    audio_activity = Signal(bool)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.controller = PreviewController(self)
        self.model: TypewriterModel = TypewriterModel()
        self._theme_name = "Dracula"; self._mode_key = "project3_codetyping"
        self._renderer: Optional[CodeRenderer] = None; self._scratch: Optional[QImage] = None
        self._init_renderer(1920, 1080); self._build_ui()
        self.audio_player = TypingAudioPlayer(); self.audio_player.set_volume(80)
        self._last_char_count = 0
        self._blink_timer = QTimer(self); self._blink_timer.setInterval(80)
        self._blink_timer.timeout.connect(self._repaint_preview); self._blink_timer.start()
        self.controller.state_changed.connect(self._on_state_changed)

    def _build_ui(self):
        v = QVBoxLayout(self); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(0)
        self.label = QLabel(); self.label.setAlignment(Qt.AlignCenter)
        self.label.setMinimumHeight(360); self.label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.label.setStyleSheet("background: #0a0b14; border-radius: 10px;")
        v.addWidget(self.label, 1)

    def _init_renderer(self, w, h):
        self._renderer = CodeRenderer(w, h, self._theme_name, self._mode_key)
        self._scratch = QImage(w, h, QImage.Format_RGB32)

    def set_model(self, model: TypewriterModel):
        self.model = model; self._renderer.build_layout(model); self._renderer.reset_caret_easing()
        self._last_char_count = 0
        self.controller.dispatch(("SEEK", 0.0)); self.controller.dispatch(("SET_DURATION", model.target_duration))
        self._repaint_preview()

    def set_theme(self, theme_name: str):
        self._theme_name = theme_name
        if self._renderer:
            self._renderer.update_theme(theme_name); self._renderer.build_layout(self.model)
        self._repaint_preview()

    def set_mode_key(self, mode_key: str):
        self._mode_key = mode_key
        if self._renderer:
            self._renderer.mode_key = mode_key; self._renderer.build_layout(self.model)
        self._repaint_preview()
        
    def set_audio_preset(self, preset: str): self.audio_player.set_preset(preset)
    def set_audio_volume(self, vol: int): self.audio_player.set_volume(vol)

    def _on_state_changed(self, state):
        self._repaint_preview()
        chars_typed = int(state.progress * self.model.total_chars)
        if state.progress < 0.01: self._last_char_count = 0
        if state.animating and chars_typed > self._last_char_count:
            diff = chars_typed - self._last_char_count
            if diff == 1:
                char = self.model.get_char_at_progress(state.progress)
                self.audio_player.play_keystroke(char=char)
            else:
                for _ in range(min(diff, 3)): self.audio_player.play_keystroke(char='')
            self.audio_activity.emit(True)
            self._last_char_count = chars_typed
        elif chars_typed < self._last_char_count:
            self._last_char_count = chars_typed

    def _repaint_preview(self):
        if self._renderer is None or self._scratch is None: return
        state = self.controller._state
        qimg = self._renderer.render_frame(state.progress, self.model, self._scratch)
        pix = QPixmap.fromImage(qimg); sz = self.label.size()
        if sz.width() > 4 and sz.height() > 4:
            pix = pix.scaled(sz, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.label.setPixmap(pix)

    def resizeEvent(self, event):
        super().resizeEvent(event); self._repaint_preview()
