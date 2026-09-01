from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Union, Final
from collections import OrderedDict
import bisect, math, random, re, threading, os
from PySide6.QtCore import Qt, QRect, QPoint
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QFontMetrics, QImage, QLinearGradient, QPainter, QPen, QBrush, QRadialGradient)
from .core import THEMES, Theme, _split_graphemes

_LANG_DATA: Dict[str, dict] = {
    "Python": {"keywords": {"def","class","return","if","else","elif","for","while","import","from","as","try","except","finally","with","raise","pass","break","continue","yield","lambda","None","True","False","and","or","not","in","is","global","nonlocal","assert","del","async","await"}, "builtins": {"print","len","range","int","str","float","list","dict","set","tuple","bool","type","isinstance","enumerate","zip","map","filter","sorted","reversed","open","super","property","staticmethod","classmethod","abs","max","min","sum","any","all","hash","id","input","format","hex","oct","bin","round","pow","divmod","chr","ord","repr","vars","dir","getattr","setattr","hasattr","delattr","callable","iter","next"}, "extra_patterns": [("decorator", r"@\w+(\.\w+)*")], "comment": r"#[^\n]*", "string": r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'', "number": r"\b\d+\.?\d*(?:e[+-]?\d+)?\b|0x[0-9a-fA-F]+\b"},
    "JavaScript": {"keywords": {"var","let","const","function","return","if","else","for","while","do","switch","case","break","continue","new","delete","typeof","instanceof","in","of","class","extends","super","this","async","await","yield","import","export","from","as","null","undefined","true","false"}, "builtins": {"console","Math","JSON","Array","Object","String","Number","Boolean","Date","RegExp","Error","Map","Set","Promise","Symbol","Proxy","Reflect","parseInt","parseFloat","isNaN","isFinite","encodeURI","decodeURI","setTimeout","setInterval","clearTimeout","clearInterval","fetch","document","window","require","module","process","Buffer"}, "extra_patterns": [], "comment": r"//[^\n]*|/\*[\s\S]*?\*/", "string": r'`(?:[^`\\]|\\.)*`|"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'', "number": r"\b\d+\.?\d*(?:e[+-]?\d+)?\b|0x[0-9a-fA-F]+\b"},
    "Text": {"keywords": set(), "builtins": set(), "extra_patterns": [], "comment": r"(?!x)x", "string": r"(?!x)x", "number": r"(?!x)x", "plain": True},
    "Markdown": {"keywords": set(), "builtins": set(), "extra_patterns": [("keyword", r"^\s*#{1,6}\s.*$|^\s*[-*+]\s|^\s*\d+\.\s|^\s*>"), ("decorator", r"\*\*[^*]*\*\*|__[^_]*__|`[^`]*`|\*[^*]*\*|_[^_]*_")], "comment": r"<!--[\s\S]*?-->", "string": r"\[.*?\]\(.*?\)|!\[.*?\]\(.*?\)", "number": r"(?!x)x"},
    "ASCII Art": {"keywords": set(), "builtins": set(), "extra_patterns": [], "comment": r"(?!x)x", "string": r"(?!x)x", "number": r"(?!x)x", "plain": True},
    "Emoji Art": {"keywords": set(), "builtins": set(), "extra_patterns": [], "comment": r"(?!x)x", "string": r"(?!x)x", "number": r"(?!x)x", "plain": True}
}
for _k, _v in list(_LANG_DATA.items()):
    if isinstance(_v, str) and _v in _LANG_DATA: _LANG_DATA[_k] = _LANG_DATA[_v]

class Tokenizer:
    _COMPILED: Dict[str, re.Pattern] = {}; _LOCK = threading.Lock()
    @classmethod
    def _compile(cls, lang: str) -> re.Pattern:
        if lang not in cls._COMPILED:
            with cls._LOCK:
                if lang not in cls._COMPILED:
                    data = _LANG_DATA.get(lang, _LANG_DATA["Text"])
                    patterns = list(data.get("extra_patterns", []))
                    if data.get("plain"):
                        patterns.extend([("whitespace", r"\s+"), ("other", r".")])
                    else:
                        patterns.extend([("comment", data["comment"]), ("string", data["string"]), ("number", data["number"])])
                        if data.get("keywords"): patterns.append(("keyword", r"\b(?:" + "|".join(data["keywords"]) + r")\b"))
                        if data.get("builtins"): patterns.append(("builtin", r"\b(?:" + "|".join(data["builtins"]) + r")\b"))
                        patterns.extend([("function", r"\b([a-zA-Z_]\w*)\s*(?=\()"), ("identifier", r"\b[a-zA-Z_]\w*\b"), ("operator", r"[+\-*/%=<>!&|^~]+"), ("bracket", r"[(){}\[\]]"), ("punctuation", r"[;:,.]"), ("whitespace", r"\s+"), ("other", r".")])
                    pat_str = "|".join(f"(?P<{n}>{p})" for n, p in patterns if p)
                    cls._COMPILED[lang] = re.compile(pat_str, re.MULTILINE | re.DOTALL)
        return cls._COMPILED[lang]
    @classmethod
    def tokenize(cls, text: str, lang: str) -> List[Tuple[str, str]]:
        compiled = cls._COMPILED.get(lang) or cls._compile(lang)
        return [(m.lastgroup, m.group()) for m in compiled.finditer(text)]

_US_SHIFT: Dict[str, str] = {"~":"`","!":"1","@":"2","#":"3","$":"4","%":"5","^":"6","&":"7","*":"8","(":"9",")":"0","_":"-","+=":"=","{":"[","}":"]","|":"\\",":":";",'"':"'","<":",",">":".","?":"/"}
_QWERTY_ROWS = [[("`",1),("1",1),("2",1),("3",1),("4",1),("5",1),("6",1),("7",1),("8",1),("9",1),("0",1),("-",1),("=",1),("Bksp",2)],[("Tab",1.5),("Q",1),("W",1),("E",1),("R",1),("T",1),("Y",1),("U",1),("I",1),("O",1),("P",1),("[",1),("]",1),("\\",1.5)],[("Caps",1.75),("A",1),("S",1),("D",1),("F",1),("G",1),("H",1),("J",1),("K",1),("L",1),(";",1),("'",1),("Enter",2.25)],[("Shift",2.25),("Z",1),("X",1),("C",1),("V",1),("B",1),("N",1),("M",1),(",",1),(".",1),("/",1),("Shift",2.75)],[("Ctrl",1.25),("Win",1.25),("Alt",1.25),("",6.25),("Alt",1.25),("Fn",1.25),("Menu",1.25),("Ctrl",1.25)]]
KEYBOARD_LAYOUTS: Dict[str, Dict] = {
    "QWERTY": {"description": "Standard US QWERTY layout", "rows": _QWERTY_ROWS, "shift_map": _US_SHIFT},
    "AZERTY": {"description": "French AZERTY layout", "rows": [[("²",1),("&",1),("é",1),("\"",1),("'",1),("(",1),("-",1),("è",1),("_",1),("ç",1),("à",1),(")",1),("=",1),("Bksp",2)],[("Tab",1.5),("A",1),("Z",1),("E",1),("R",1),("T",1),("Y",1),("U",1),("I",1),("O",1),("P",1),("^",1),("$",1),("Enter",1.5)],[("Caps",1.75),("Q",1),("S",1),("D",1),("F",1),("G",1),("H",1),("J",1),("K",1),("L",1),("M",1),("ù",1),("*",1),("Enter",2.25)],[("Shift",1.25),("<",1),("W",1),("X",1),("C",1),("V",1),("B",1),("N",1),(",",1),(";",1),(":",1),("!",1),("Shift",2.75)],[("Ctrl",1.25),("Win",1.25),("Alt",1.25),(" ",6.25),("Alt",1.25),("Win",1.25),("Menu",1.25),("Ctrl",1.25)]], "shift_map": {"&":"1","é":"2","\"":"3","'":"4","(":"5","-":"6","è":"7","_":"8","ç":"9","à":"0",")":"°","=":"+","^":"¨","$":"£","ù":"%","*":"µ","<":">",",":"?",";":".",":":"/","!":"§"}},
    "QWERTZ": {"description": "German QWERTZ layout", "rows": [[("^",1),("1",1),("2",1),("3",1),("4",1),("5",1),("6",1),("7",1),("8",1),("9",1),("0",1),("ß",1),("´",1),("Bksp",2)],[("Tab",1.5),("Q",1),("W",1),("E",1),("R",1),("T",1),("Z",1),("U",1),("I",1),("O",1),("P",1),("Ü",1),("+",1),("Enter",1.5)],[("Caps",1.75),("A",1),("S",1),("D",1),("F",1),("G",1),("H",1),("J",1),("K",1),("L",1),("Ö",1),("Ä",1),("#",1),("Enter",2.25)],[("Shift",1.25),("<",1),("Y",1),("X",1),("C",1),("V",1),("B",1),("N",1),(",",1),(".",1),("-",1),("Shift",2.75)],[("Ctrl",1.25),("Win",1.25),("Alt",1.25),(" ",6.25),("Alt",1.25),("Win",1.25),("Menu",1.25),("Ctrl",1.25)]], "shift_map": {"1":"!","2":"\"","3":"§","4":"$","5":"%","6":"&","7":"/","8":"(","9":")","0":"=","ß":"?","´":"`","Ü":"{","+":"}","Ö":";","Ä":":","#":"'","<":">",",":";",".":":","-":"_"}},
    "Dvorak": {"description": "Dvorak Simplified Keyboard", "rows": [[("`",1),("1",1),("2",1),("3",1),("4",1),("5",1),("6",1),("7",1),("8",1),("9",1),("0",1),("[",1),("]",1),("Bksp",2)],[("Tab",1.5),("'",1),(",",1),(".",1),("P",1),("Y",1),("F",1),("G",1),("C",1),("R",1),("L",1),("/",1),("=",1),("\\",1.5)],[("Caps",1.75),("A",1),("O",1),("E",1),("U",1),("I",1),("D",1),("H",1),("T",1),("N",1),("S",1),("-",1),("Enter",2.25)],[("Shift",2.25),(";",1),("Q",1),("J",1),("K",1),("X",1),("B",1),("M",1),("W",1),("V",1),("Z",1),("Shift",2.75)],[("Ctrl",1.25),("Win",1.25),("Alt",1.25),(" ",6.25),("Alt",1.25),("Win",1.25),("Menu",1.25),("Ctrl",1.25)]], "shift_map": {"'":"\"","-":"_","[":"{","]":"}","/":"?","=":"+","#":"~","\\":"|",";":":","`":"~"}},
    "Compact (60%)": {"description": "60% mechanical keyboard", "rows": [[("`",1),("1",1),("2",1),("3",1),("4",1),("5",1),("6",1),("7",1),("8",1),("9",1),("0",1),("-",1),("=",1),("Bksp",2)],[("Tab",1.5),("Q",1),("W",1),("E",1),("R",1),("T",1),("Y",1),("U",1),("I",1),("O",1),("P",1),("[",1),("]",1),("\\",1.5)],[("Caps",1.75),("A",1),("S",1),("D",1),("F",1),("G",1),("H",1),("J",1),("K",1),("L",1),(";",1),("'",1),("Enter",2.25)],[("Shift",2.25),("Z",1),("X",1),("C",1),("V",1),("B",1),("N",1),("M",1),(",",1),(".",1),("/",1),("Shift",2.75)],[("Ctrl",1.25),("Win",1.25),("Alt",1.25),(" ",6.25),("Alt",1.25),("Fn",1.25),("Menu",1.25),("Ctrl",1.25)]], "shift_map": _US_SHIFT}
}

def _build_char_map(layout_name: str) -> Dict[str, Tuple[int, int]]:
    ld = KEYBOARD_LAYOUTS[layout_name]; cm: Dict[str, Tuple[int, int]] = {}
    for ri, row in enumerate(ld["rows"]):
        for ci, (label, w) in enumerate(row):
            ll = label.lower()
            if len(label) == 1: cm[label] = cm[ll] = cm[label.upper()] = (ri, ci)
            if ll == "space" or (label == "" and w >= 4): cm[" "] = (ri, ci)
            elif "enter" in ll: cm["\n"] = (ri, ci)
            elif "tab" in ll: cm["\t"] = (ri, ci)
            elif "bksp" in ll: cm["\x08"] = (ri, ci)
    for shifted, base in ld.get("shift_map", {}).items():
        if base in cm: cm[shifted] = cm[base]
    return cm

class KeyboardOverlay:
    __slots__ = ("video_w", "video_h", "layout_name", "theme", "opacity", "rows", "char_map", "num_rows", "position", "key_unit", "key_gap", "key_h", "_max_units", "_max_keys", "_kb_width", "_kb_height", "_kb_x", "_kb_y", "key_rects", "_bg_cache")
    def __init__(self, video_w: int, video_h: int, layout_name: str = "QWERTY", theme: Optional[Theme] = None, opacity: float = 0.82, max_height: Optional[int] = None, position: str = "bottom_center"):
        self.video_w = video_w; self.video_h = video_h; self.layout_name = layout_name
        self.theme = theme if isinstance(theme, dict) else (vars(theme) if theme else vars(THEMES["Dracula"]))
        self.opacity = opacity; self.rows = KEYBOARD_LAYOUTS[layout_name]["rows"]; self.char_map = _build_char_map(layout_name); self.num_rows = len(self.rows); self.position = position
        self.key_unit = max(20, int(video_w * 0.028)); self.key_gap = max(2, self.key_unit // 14); self.key_h = int(self.key_unit * 0.82)
        if max_height and max_height > 0:
            natural_h = self.num_rows * self.key_h + (self.num_rows - 1) * self.key_gap
            if natural_h > max_height:
                lo, hi = 10, self.key_unit
                for _ in range(30):
                    mid = (lo + hi) / 2; tg = max(2, int(mid) // 14); th = self.num_rows * int(mid * 0.82) + (self.num_rows - 1) * tg
                    if th > max_height: hi = mid
                    else: lo = mid
                self.key_unit = max(10, int(lo)); self.key_gap = max(2, self.key_unit // 14); self.key_h = int(self.key_unit * 0.82)
        self._max_units = max(sum(w for _, w in row) for row in self.rows); self._max_keys = max(len(row) for row in self.rows)
        self._kb_width = int(self._max_units * self.key_unit + (self._max_keys - 1) * self.key_gap); self._kb_height = int(len(self.rows) * self.key_h + (len(self.rows) - 1) * self.key_gap)
        self._kb_x = (video_w - self._kb_width) // 2; self._kb_y = video_h - self._kb_height - max(8, video_h // 60); self._apply_position()
        self.key_rects: Dict[Tuple[int, int], QRect] = {}; self._rebuild_key_rects(); self._bg_cache = None; self._build_bg_cache()
    def height_needed(self) -> int: return self._kb_height + max(8, self.video_h // 60) + max(6, self.video_h // 90)
    def _apply_position(self) -> None:
        m = max(8, self.video_h // 60); vw, vh, kw, kh = self.video_w, self.video_h, self._kb_width, self._kb_height
        match self.position:
            case "bottom_center": self._kb_x, self._kb_y = (vw - kw) // 2, vh - kh - m
            case "bottom_right": self._kb_x, self._kb_y = vw - kw - m, vh - kh - m
            case "bottom_left": self._kb_x, self._kb_y = m, vh - kh - m
            case "top_center": self._kb_x, self._kb_y = (vw - kw) // 2, m
            case "top_right": self._kb_x, self._kb_y = vw - kw - m, m
            case "top_left": self._kb_x, self._kb_y = m, m
            case "center_left": self._kb_x, self._kb_y = m, (vh - kh) // 2
            case "center_right": self._kb_x, self._kb_y = vw - kw - m, (vh - kh) // 2
    def _rebuild_key_rects(self) -> None:
        self.key_rects = {}
        for ri, row in enumerate(self.rows):
            x = self._kb_x
            for ci, (_, w) in enumerate(row):
                kw = int(w * self.key_unit) - self.key_gap; y = self._kb_y + ri * (self.key_h + self.key_gap)
                self.key_rects[(ri, ci)] = QRect(x, y, kw, self.key_h); x += int(w * self.key_unit)
        self._bg_cache = None
    def reposition(self, y_below: int = 0) -> None: self._apply_position(); self._rebuild_key_rects()
    def resolve_key(self, ch: str) -> Optional[Tuple[int, int]]: return self.char_map.get(ch)
    def _build_bg_cache(self) -> None:
        pad = max(6, self.key_unit // 4); w = self._kb_width + 2 * pad; h = self._kb_height + 2 * pad
        self._bg_cache = QImage(w, h, QImage.Format_ARGB32_Premultiplied); self._bg_cache.fill(Qt.transparent)
        p = QPainter(self._bg_cache); p.setRenderHint(QPainter.Antialiasing); th = self.theme; radius = max(3, self.key_unit // 8)
        p.setPen(QPen(QColor(th["window_border"]), max(1, self.key_unit // 20))); p.setBrush(QColor(th["background"])); p.drawRoundedRect(0, 0, w, h, radius * 2, radius * 2)
        p.setFont(QFont("Arial", max(7, int(self.key_unit * 0.30))))
        for (ri, ci), rect in self.key_rects.items():
            label = self.rows[ri][ci][0]; cache_rect = QRect(rect.x() - self._kb_x + pad, rect.y() - self._kb_y + pad, rect.width(), rect.height())
            p.setBrush(QColor(th["title_bar"])); p.setPen(QColor(th["window_border"])); p.drawRoundedRect(cache_rect, radius, radius)
            if label:
                is_mod = len(label) > 1
                p.setPen(QColor(th["line_number"] if is_mod else th.get("foreground", "#f8f8f2"))); p.drawText(cache_rect, Qt.AlignCenter, label)
        p.end()
    def draw(self, painter: QPainter, active_key: Optional[Tuple[int, int]] = None, flash: float = 0.0) -> None:
        painter.save(); painter.setOpacity(self.opacity)
        if self._bg_cache is None: self._build_bg_cache()
        pad = max(6, self.key_unit // 4); painter.drawImage(self._kb_x - pad, self._kb_y - pad, self._bg_cache)
        if flash > 0 and active_key is not None:
            th = self.theme
            try: hl_base = QColor(th["cursor"])
            except KeyError: hl_base = QColor("#89b4fa")
            key_bg = QColor(th["title_bar"]); flash_eased = 1.0 - (1.0 - flash) ** 2
            hl_fill = QColor(int(key_bg.red() + (hl_base.red() - key_bg.red()) * flash_eased), int(key_bg.green() + (hl_base.green() - key_bg.green()) * flash_eased), int(key_bg.blue() + (hl_base.blue() - key_bg.blue()) * flash_eased))
            hl_glow = QColor(hl_base); hl_glow.setAlpha(int(60 * flash_eased)); hl_expand = max(3, int(self.key_unit * 0.12 * flash_eased))
            rect = self.key_rects[active_key]; radius = max(3, self.key_unit // 8)
            painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(hl_glow); painter.drawRoundedRect(rect.adjusted(-hl_expand, -hl_expand, hl_expand, hl_expand), radius, radius)
            painter.setBrush(hl_fill); painter.setPen(QColor(th["window_border"])); painter.drawRoundedRect(rect, radius, radius)
            label = self.rows[active_key[0]][active_key[1]][0]
            if label:
                is_mod = len(label) > 1
                painter.setPen(QColor(th["line_number"] if is_mod else th.get("foreground", "#f8f8f2"))); painter.setFont(QFont("Arial", max(7, int(self.key_unit * 0.30)))); painter.drawText(rect, Qt.AlignCenter, label)
        painter.restore()

Event = Tuple[float, int, str]
_QWERTY_POS: Dict[str, Tuple[int, int]] = {}
for _r, _row in enumerate(("`1234567890-=", "qwertyuiop[]\\", "asdfghjkl;'", "zxcvbnm,./")):
    for _c, _ch in enumerate(_row): _QWERTY_POS[_ch] = (_r, _c)
for _ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ": _QWERTY_POS[_ch] = _QWERTY_POS.get(_ch.lower(), (2, 0))
_QWERTY_NEARBY: Dict[str, str] = {'a': 'qwsz', 'b': 'vghn', 'c': 'xdfv', 'd': 'serfcx', 'e': 'wrsdf', 'f': 'drtgvc', 'g': 'ftyhbv', 'h': 'gyujnb', 'i': 'ujklo', 'j': 'huikmn', 'k': 'jilpm', 'l': 'kop', 'm': 'njk', 'n': 'bhjm', 'o': 'iklp', 'p': 'ol', 'q': 'wa', 'r': 'edft', 's': 'awedz', 't': 'rfgy', 'u': 'yhji', 'v': 'cfgb', 'w': 'qasde', 'x': 'zsdc', 'y': 'tghu', 'z': 'asx', ' ': ' '}

@dataclass
class TypingProfile:
    name: str = "junior"; wpm: int = 90; pause_freq: float = 0.15; start_pause: float = 0.5; end_pause: float = 1.5; auto_indent: bool = True; error_chance: float = 0.03; burstiness: float = 0.2

class TypingAnimator:
    __slots__ = ("code", "profile", "base_delay", "display_chars", "text_snapshots", "error_snapshots", "timeline", "_timestamps")
    def __init__(self, code: str, profile: TypingProfile, seed: Optional[int] = None):
        self.code = code; self.profile = profile; self.base_delay = 1.0 / ((profile.wpm * 5) / 60); self.display_chars: List[str] = []; self.text_snapshots: List[str] = []; self.error_snapshots: List[List[bool]] = []
        self.timeline: List[Event] = self._build(seed if seed is not None else 42); self._timestamps = [ts for ts, _, _ in self.timeline]
    def _get_typo(self, ch: str, rng: random.Random) -> str:
        if rng.random() < 0.15: return ch
        lower = ch.lower()
        if lower in _QWERTY_NEARBY:
            typo = rng.choice(_QWERTY_NEARBY[lower])
            return typo.upper() if ch.isupper() else typo
        return ch
    def _build(self, seed: int) -> List[Event]:
        rng = random.Random(seed); t = self.profile.start_pause; events: List[Event] = []; p = self.profile; i = 0; current_text: List[str] = []; current_errors: List[bool] = []
        self.text_snapshots.append(""); self.error_snapshots.append([])
        def take_snapshot(): self.text_snapshots.append("".join(current_text)); self.error_snapshots.append(list(current_errors))
        burst_len = 0; burst_mult = 1.0
        while i < len(self.code):
            ch = self.code[i]
            if burst_len <= 0:
                if rng.random() < p.burstiness: burst_len = rng.randint(4, 10); burst_mult = rng.uniform(0.4, 0.7)
                else: burst_mult = rng.uniform(0.8, 1.2)
            else: burst_len -= 1
            d = self.base_delay * burst_mult * rng.uniform(0.6, 1.4)
            match ch:
                case "\n": d *= rng.uniform(2.0, 4.0)
                case " ": d *= rng.uniform(0.7, 1.3)
                case "\t": d *= rng.uniform(1.2, 1.8)
                case _:
                    if ch in "([{": d *= rng.uniform(1.1, 1.8)
                    elif ch in ")]}": d *= rng.uniform(0.9, 1.5)
                    elif ch in ",;:": d *= rng.uniform(1.3, 2.2)
            if i >= 1:
                pa = _QWERTY_POS.get(self.code[i - 1].lower()); pb = _QWERTY_POS.get(ch.lower())
                if pa and pb:
                    dist = math.hypot(pa[0] - pb[0], pa[1] - pb[1])
                    if dist < 0.5: d *= 0.7
                    elif dist > 4: d *= 1.15
            if ch == ":" and i > 0:
                if "def " in self.code[max(0, i - 10):i] or "class " in self.code[max(0, i - 10):i]:
                    if rng.random() < 0.6: d += rng.uniform(2.0, 5.0)
                elif rng.random() < 0.2: d += rng.uniform(1.0, 2.5)
            if ch in ("\n", ":"):
                if rng.random() < p.pause_freq: d += rng.uniform(0.4, 1.2)
            elif rng.random() < (p.pause_freq * 0.2): d += rng.uniform(0.3, 0.8)
            if rng.random() < 0.012: d += rng.uniform(0.4, 1.4)
            if ch.isalpha() and rng.random() < p.error_chance and i + 1 < len(self.code):
                typo_ch = self._get_typo(ch, rng)
                if typo_ch == ch:
                    current_text.append(typo_ch); current_errors.append(True); self.display_chars.append(typo_ch); events.append((t, len(self.display_chars) - 1, typo_ch)); take_snapshot()
                    t += max(d * 0.3, 0.02)
                    current_text.append("\b"); current_errors.append(False); self.display_chars.append("\b"); events.append((t, len(self.display_chars) - 1, "\b")); take_snapshot()
                    t += max(d * 0.2, 0.01)
                else:
                    current_text.append(typo_ch); current_errors.append(True); self.display_chars.append(typo_ch); events.append((t, len(self.display_chars) - 1, typo_ch)); take_snapshot()
                    t += max(d * 0.5, 0.05) + rng.uniform(0.1, 0.3)
                    current_text.append("\b"); current_errors.append(False); self.display_chars.append("\b"); events.append((t, len(self.display_chars) - 1, "\b")); take_snapshot()
                    t += max(d * 0.2, 0.01)
            current_text.append(ch); current_errors.append(False); self.display_chars.append(ch); events.append((t, len(self.display_chars) - 1, ch)); take_snapshot()
            t += max(d, 0.012); i += 1
            if p.auto_indent and ch == "\n" and i < len(self.code):
                indent = ""
                while i < len(self.code) and self.code[i] in (' ', '\t'): indent += self.code[i]; i += 1
                if indent:
                    for ind_ch in indent:
                        current_text.append(ind_ch); current_errors.append(False); self.display_chars.append(ind_ch); events.append((t, len(self.display_chars) - 1, ind_ch)); take_snapshot()
                        t += max(d * 0.3, 0.008)
        return events
    def duration(self) -> float: return (self.timeline[-1][0] + self.profile.end_pause if self.timeline else self.profile.start_pause + self.profile.end_pause)
    def visible_at(self, t: float) -> int:
        if t < self.profile.start_pause: return 0
        idx = bisect.bisect_right(self._timestamps, t)
        return self.timeline[idx - 1][1] + 1 if idx > 0 else 0
    def char_timestamps(self) -> List[Tuple[float, str]]: return [(ts, ch) for ts, _, ch in self.timeline if ch != "\b"]
    def active_key_at(self, t: float, flash_duration: float = 0.18) -> Tuple[Optional[str], float]:
        if not self._timestamps: return (None, 0.0)
        idx = bisect.bisect_right(self._timestamps, t)
        if idx == 0: return (None, 0.0)
        char = self.timeline[idx - 1][2]; dt = t - self.timeline[idx - 1][0]
        return (char, max(0.0, 1.0 - dt / flash_duration)) if dt < flash_duration else (None, 0.0)
    @staticmethod
    def estimate_duration(code: str, wpm: int, start_pause: float = 0.5, end_pause: float = 1.5, pause_freq: float = 0.15, error_chance: float = 0.03, burstiness: float = 0.2) -> float:
        n = len(code)
        if n == 0: return start_pause + end_pause
        base = 12.0 / max(10, wpm)
        nl = code.count("\n"); co = code.count(":"); tab = code.count("\t")
        bo = sum(1 for c in code if c in "([{"); bc = sum(1 for c in code if c in ")]}"); pu = sum(1 for c in code if c in ",;:")
        extra_special = (nl * 2.0 + tab * 0.5 + bo * 0.45 + bc * 0.2 + pu * 0.75) * base
        pause_structural = (nl + co) * pause_freq * 0.8
        pause_other = n * (pause_freq * 0.2) * 0.55
        pause_micro = n * 0.012 * 0.9
        burst_savings = n * burstiness * 0.3 * base
        error_time = n * error_chance * (2.8 * base + 0.2)
        return (start_pause + end_pause + n * base + extra_special + pause_structural + pause_other + pause_micro + error_time - burst_savings)
    @staticmethod
    def find_wpm_for_target_duration(code: str, target: float, start_pause: float, end_pause: float, error_chance: float = 0.0, burstiness: float = 0.2) -> int:
        if target <= 0: return 1000
        safe_target = target * 0.95
        if TypingAnimator(code, TypingProfile(wpm=30, start_pause=start_pause, end_pause=end_pause, error_chance=error_chance, burstiness=burstiness), seed=123).duration() <= safe_target: return 30
        n = len(code)
        if n == 0: return 100
        nl = code.count("\n"); co = code.count(":"); tab = code.count("\t")
        bo = sum(1 for c in code if c in "([{"); bc = sum(1 for c in code if c in ")]}"); pu = sum(1 for c in code if c in ",;:")
        pause_freq = 0.15
        K = (start_pause + end_pause + (nl + co) * pause_freq * 0.8 + n * (pause_freq * 0.2) * 0.55 + n * 0.012 * 0.9)
        L = (n + nl * 2.0 + tab * 0.5 + bo * 0.45 + bc * 0.2 + pu * 0.75 + n * error_chance * 2.8 - n * burstiness * 0.3)
        denom = target - K
        initial = max(30, min(1000, int(L * 12.0 / denom))) if denom > 0.1 else 1000
        lo, hi, best = 30, 1000, initial
        d_init = TypingAnimator(code, TypingProfile(wpm=initial, start_pause=start_pause, end_pause=end_pause, error_chance=error_chance, burstiness=burstiness), seed=123).duration()
        if d_init <= safe_target: best = initial; hi = initial
        else: lo = initial
        while lo <= hi:
            mid = (lo + hi) // 2
            d = TypingAnimator(code, TypingProfile(wpm=mid, start_pause=start_pause, end_pause=end_pause, error_chance=error_chance, burstiness=burstiness), seed=123).duration()
            if d <= safe_target: best = mid; hi = mid - 1
            else: lo = mid + 1
        return max(10, min(500, best))

class TextTypingAnimator:
    def __init__(self, text: str, wpm: int = 100, start_pause: float = 0.5, end_pause: float = 1.5, typo_rate: float = 0.0):
        self.text = text; self.wpm = wpm; self.start_pause = start_pause; self.end_pause = end_pause; self.typo_rate = typo_rate
        seed = sum(ord(c) for c in text); self._rng = random.Random(seed)
        self.display_chars: List[str] = []; self._timestamps: List[float] = []; self.timeline: List[Tuple[float, str]] = []
        self._build_timeline()
    def _build_timeline(self):
        t = self.start_pause; base_interval = 60.0 / max(1, self.wpm) / 5.0
        for char in _split_graphemes(self.text):
            if char != '\n' and char != ' ' and self._rng.random() < self.typo_rate:
                import string
                typo_char = self._rng.choice(string.ascii_letters + string.digits)
                self.timeline.append((t, typo_char)); self.display_chars.append(typo_char); self._timestamps.append(t)
                t += base_interval * self._rng.uniform(0.5, 1.0)
                self.timeline.append((t, '\b')); self.display_chars.append('\b'); self._timestamps.append(t)
                t += base_interval * self._rng.uniform(0.5, 1.0)
            self.timeline.append((t, char)); self.display_chars.append(char); self._timestamps.append(t)
            if char in ".!?": t += base_interval * self._rng.uniform(4.0, 6.0)
            elif char in ",;:": t += base_interval * self._rng.uniform(2.0, 3.5)
            elif char == '\n': t += base_interval * self._rng.uniform(3.0, 5.0)
            elif char == ' ': t += base_interval * self._rng.uniform(1.2, 1.8)
            else: t += base_interval * self._rng.uniform(0.7, 1.3)
        self._duration = t + self.end_pause
    def duration(self) -> float: return self._duration
    def visible_at(self, t: float) -> int:
        if t <= 0: return 0
        return bisect.bisect_right(self._timestamps, t)
    def active_key_at(self, t: float) -> Tuple[Optional[str], float]:
        if not self.timeline or t < self.timeline[0][0]: return None, 0.0
        idx = bisect.bisect_right(self._timestamps, t)
        if idx == 0: return None, 0.0
        last_ts, last_char = self.timeline[idx - 1]; elapsed = t - last_ts
        flash_dur = 0.15
        if elapsed < flash_dur: return last_char, max(0.0, (1.0 - elapsed / flash_dur) ** 1.5)
        return None, 0.0
    def char_timestamps(self) -> List[Tuple[float, str]]: return self.timeline
    @staticmethod
    def find_wpm_for_target_duration(text: str, target_dur: float, start_pause: float, end_pause: float, typo_rate: float) -> int:
        available_time = target_dur - start_pause - end_pause
        if available_time <= 0 or not text: return 300
        grapheme_count = len(_split_graphemes(text))
        base_interval = available_time / max(1, grapheme_count * 1.2)
        wpm = int(60.0 / max(0.01, base_interval) / 5.0)
        return max(30, min(300, wpm))

class CodeRenderer:
    TOKEN_COLOR_MAP: Final[Dict[str, str]] = {"keyword":"keyword","builtin":"builtin","string":"string","number":"number","comment":"comment","decorator":"decorator","function":"function","class_name":"class_name","operator":"operator","boolean":"number","constant":"number","preprocessor":"decorator","variable":"function","symbol":"string","macro":"function","tag":"keyword","attr":"builtin","selector":"keyword","property":"builtin","value":"string","hex_color":"number","heading":"keyword","bold":"keyword","italic":"keyword","code":"string","link":"function","punctuation":"comment","fstring":"string","lifetime":"constant","annotation":"decorator"}
    CURSOR_BLINK: Final[float] = 0.53
    def __init__(self, width: int, height: int, theme_name: str = "Dracula", font_family: str = "Consolas", font_size: int = 22, show_line_numbers: bool = True, show_window_chrome: bool = True, padding: int = 24, tab_size: int = 4, title_text: str = "main.py", language: str = "Python", keyboard_overlay: Optional[KeyboardOverlay] = None, bg_image_path: Optional[str] = None, total_code_lines: int = 0, cursor_glow: bool = True, show_watermark: bool = False, watermark_text: str = "", accent_color: Optional[str] = None, code: str = ""):
        self.width = width; self.height = height; self.theme = THEMES.get(theme_name, THEMES["Dracula"]); self.theme_name = theme_name; self.font_family = font_family; self.font_size = font_size; self.show_line_numbers = show_line_numbers; self.show_window_chrome = show_window_chrome; self.padding = padding; self.tab_size = tab_size; self.title_text = title_text; self.language = language; self.keyboard_overlay = keyboard_overlay; self.total_code_lines = total_code_lines; self.cursor_glow = cursor_glow; self.show_watermark = show_watermark; self.watermark_text = watermark_text or "Code Typing Studio"; self.accent_color = accent_color or getattr(self.theme, "junior_accent", "#7aa2f7")
        self.code = code
        _families = [font_family, "JetBrains Mono", "DejaVu Sans Mono", "Liberation Mono", "Courier New", "monospace"]; _available = QFontDatabase.families(); chosen = "monospace"
        for f in _families:
            if f in _available: chosen = f; break
        self.font = QFont(chosen, font_size); self.font.setFamilies(_families); self.font.setFixedPitch(True); self.fm = QFontMetrics(self.font); self.char_w = self.fm.horizontalAdvance("M"); self.line_h = self.fm.height()
        self._qcolors = {f.name: QColor(getattr(self.theme, f.name)) for f in self.theme.__dataclass_fields__ if isinstance(getattr(self.theme, f.name), str) and getattr(self.theme, f.name).startswith("#")}; self._qc_fg = self._qcolors.get("foreground", QColor("#f8f8f2")); self._qc_ln = self._qcolors.get("line_number", QColor("#6272a4"))
        self._qc_ln_active = QColor(self._qc_fg); self._qc_ln_active.setAlpha(200)
        self._qc_cursor = self._qcolors.get("cursor", QColor("#f8f8f2")); self._qc_current_line = self._qcolors.get("current_line", QColor("#44475a")); self._qc_accent = QColor(self.accent_color)
        self._qc_error = QColor("#f38ba8")
        self.bg_image = (QImage(bg_image_path) if bg_image_path and os.path.exists(bg_image_path) else None); self._build_bg_cache()
        self._layout_nv: Union[str, int] = -1; self._layout_lines: List[str] = []; self._layout_offsets: List[int] = []; self._layout_cursor_line: int = 0
        self._line_cache: "OrderedDict[str, List[int]]" = OrderedDict(); self._tab_advance = self.char_w * self.tab_size
        self._tok_cache: "OrderedDict[str, List[str]]" = OrderedDict()
        self._full_colors = self._tokenize_to_colors(self.code) if self.code else []
    @staticmethod
    def auto_font_size(code_lines: int, width: int, height: int, padding: int = 24, show_chrome: bool = True, show_ln: bool = True, tab_size: int = 4, code: Optional[str] = None, font_family: str = "Consolas", keyboard_h: int = 0) -> int:
        chrome_h = 42 if show_chrome else 0; kb_used = min(keyboard_h, (height - 2 * padding) // 3) if keyboard_h > 0 else 0; rect_h = height - 2 * padding - kb_used - chrome_h; rect_w = width - 2 * padding - 8
        if rect_h < 20 or rect_w < 40 or code_lines < 1: return 14
        max_chars = 80
        if code: max_chars = max(max(len(line.replace("\t", " " * tab_size)) for line in code.split("\n")), 1)
        def _ln_w(cw: int) -> int: return (len(str(code_lines)) * cw + 16) if show_ln else 0
        max_font = max(14, min(48, int(width / 80))); target_vis = min(code_lines, 35); max_check = min(max_chars, 120); lo, hi, best = 8, max_font, 14
        while lo <= hi:
            mid = (lo + hi) // 2; fm = QFontMetrics(QFont(font_family, mid)); lh = fm.height()
            if target_vis * lh <= rect_h:
                cw = fm.horizontalAdvance("M")
                if max_check * cw + _ln_w(cw) <= rect_w: best = mid; lo = mid + 1
                else: hi = mid - 1
            else: hi = mid - 1
        return max(8, best)
    def _get_line_layout(self, line: str) -> List[int]:
        cached = self._line_cache.get(line)
        if cached is not None: return cached
        char_x: List[int] = []; x = 0; tab = self._tab_advance; ham = self.fm.horizontalAdvance
        for ch in line: char_x.append(x); x += tab if ch == "\t" else ham(ch)
        if len(self._line_cache) >= 512: self._line_cache.popitem(last=False)
        self._line_cache[line] = char_x; return char_x
    def _tokenize_to_colors(self, text: str) -> List[str]:
        cached = self._tok_cache.get(text)
        if cached is not None: return cached
        tokens = Tokenizer.tokenize(text, self.language); colors = ["foreground"] * len(text); pos = 0; get = self.TOKEN_COLOR_MAP.get; n = len(colors)
        for ttype, ttxt in tokens:
            ckey = get(ttype, "foreground"); end = min(pos + len(ttxt), n); colors[pos:end] = [ckey] * (end - pos); pos = end
        if len(self._tok_cache) > 256: self._tok_cache.popitem(last=False)
        self._tok_cache[text] = colors; return colors
    def _build_bg_cache(self) -> None:
        self._bg = QImage(self.width, self.height, QImage.Format_RGB32); self._bg.fill(QColor(self.theme.background)); p = QPainter(self._bg); p.setRenderHint(QPainter.Antialiasing)
        if self.bg_image: scaled = self.bg_image.scaled(self.width, self.height, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation); p.drawImage((self.width - scaled.width()) // 2, (self.height - scaled.height()) // 2, scaled); p.fillRect(0, 0, self.width, self.height, QColor(0, 0, 0, 130))
        else: bg = self._qcolors.get("background", QColor("#282a36")); g = QLinearGradient(0, 0, 0, self.height); g.setColorAt(0, bg.lighter(105)); g.setColorAt(1, bg); p.fillRect(0, 0, self.width, self.height, g)
        w, h, pad = self.width, self.height, self.padding; chrome_h = 42 if self.show_window_chrome else 0; kb_reserve = (min(self.keyboard_overlay.height_needed(), (h - 2 * pad) // 3) if self.keyboard_overlay else 0); wx, wy, ww, wh = pad, pad, w - 2 * pad, h - 2 * pad - kb_reserve
        p.setPen(Qt.PenStyle.NoPen)
        for s in range(6, 0, -1): p.setBrush(QColor(0, 0, 0, int(40 - s * 5))); p.drawRoundedRect(wx - s, wy - s + (s // 2), ww + 2 * s, wh + 2 * s, 12 + s, 12 + s)
        p.setPen(QColor(self.theme.window_border)); p.setBrush(QColor(self.theme.background)); p.drawRoundedRect(wx, wy, ww, wh, 12, 12)
        if self.show_window_chrome:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(self.theme.title_bar)); p.drawRoundedRect(wx, wy, ww, chrome_h, 12, 12); p.drawRect(wx, wy + chrome_h - 12, ww, 12)
            for i, color in enumerate(["#ff5f56", "#ffbd2e", "#27c93f"]): p.setBrush(QColor(color)); p.setPen(Qt.PenStyle.NoPen); p.drawEllipse(QPoint(wx + 20 + i * 24, wy + 19), 7, 7)
            p.setPen(QColor(self.theme.title_text)); p.setFont(QFont(self.font_family, max(8, self.font_size // 3))); p.drawText(QRect(wx, wy, ww, chrome_h), Qt.AlignCenter, self.title_text)
            p.setPen(QPen(self._qc_accent, 2)); p.drawLine(wx, wy + chrome_h, wx + ww, wy + chrome_h); code_top = wy + chrome_h
        else: code_top = wy
        self._code_rect = QRect(wx + 4, code_top, ww - 8, wh - (code_top - wy))
        if self.keyboard_overlay: self.keyboard_overlay.reposition(wy + wh + max(8, h // 60))
        p.end()
    def render_frame(self, visible_text: str, vis_err: List[bool], cursor_visible: bool = True, target: Optional[QImage] = None, active_char: Optional[str] = None, key_flash: float = 0.0) -> QImage:
        img = target if target is not None else QImage(self.width, self.height, QImage.Format_RGB32)
        if target is None: img.fill(QColor(self.theme.background))
        p = QPainter(img); p.setRenderHint(QPainter.TextAntialiasing); p.drawImage(0, 0, self._bg); cr = self._code_rect
        vis_len = len(visible_text)
        if self._full_colors and vis_len <= len(self._full_colors): colors = self._full_colors[:vis_len]
        else: colors = self._tokenize_to_colors(visible_text)
        fg = self._qc_fg; qc = self._qcolors
        if visible_text != self._layout_nv:
            self._layout_lines = visible_text.split("\n"); offsets: List[int] = []; off = 0
            for ln in self._layout_lines: offsets.append(off); off += len(ln) + 1
            self._layout_offsets = offsets; self._layout_cursor_line = visible_text.count("\n"); self._layout_nv = visible_text
        lines = self._layout_lines; line_offsets = self._layout_offsets; cursor_line = self._layout_cursor_line; total_lines = len(self._layout_lines)
        cr_h, cr_top = cr.height(), cr.top(); max_vis = max(1, -(-cr.height() // self.line_h)); lh_base = self.line_h
        scroll = 0; margin_bottom = max(3, max_vis // 4); margin_top = 3
        if cursor_line >= scroll + max_vis - margin_bottom: scroll = max(0, cursor_line - max_vis + margin_bottom + 1)
        if cursor_line < scroll + margin_top: scroll = max(0, cursor_line - margin_top)
        if scroll > max(0, total_lines - max_vis): scroll = max(0, total_lines - max_vis)
        ln_width = (len(str(total_lines + scroll)) * self.char_w + 16) if self.show_line_numbers else 0
        current_scroll_line = cursor_line - scroll
        line_y_arr: List[int] = []; line_h_arr: List[int] = []; y_acc = cr_top
        for si in range(max_vis):
            li = scroll + si
            if li >= total_lines: break
            line_y_arr.append(y_acc); line_h_arr.append(lh_base); y_acc += lh_base
        n_drawn = len(line_y_arr)
        if 0 <= current_scroll_line < n_drawn:
            grad = QLinearGradient(cr.left(), 0, cr.right(), 0)
            c1 = QColor(self._qc_current_line); c1.setAlpha(180)
            c2 = QColor(self._qc_current_line); c2.setAlpha(40)
            grad.setColorAt(0, c1); grad.setColorAt(1, c2)
            p.fillRect(cr.left(), line_y_arr[current_scroll_line], cr.width(), line_h_arr[current_scroll_line], QBrush(grad))
            p.setPen(QPen(self._qc_accent, 2)); p.drawLine(cr.left(), line_y_arr[current_scroll_line], cr.left(), line_y_arr[current_scroll_line] + line_h_arr[current_scroll_line])
        if self.show_line_numbers and ln_width > 0:
            sep_x = cr.left() + ln_width; sc = QColor(self._qc_ln); sc.setAlpha(60); p.setPen(QPen(sc, 1)); p.drawLine(sep_x, cr.top(), sep_x, cr.top() + max_vis * lh_base)
        if total_lines > max_vis:
            track_w = 6; track_x = cr.right() - track_w - 2; track_y = cr.top(); track_h = cr.height()
            track_color = QColor(self._qc_ln); track_color.setAlpha(40)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(track_color); p.drawRoundedRect(track_x, track_y, track_w, track_h, 3, 3)
            thumb_h = max(20, int(track_h * max_vis / total_lines))
            max_thumb_y = track_h - thumb_h
            thumb_y = track_y + int((scroll / max(1, total_lines - max_vis)) * max_thumb_y)
            thumb_color = QColor(self._qc_ln); thumb_color.setAlpha(120)
            p.setBrush(thumb_color); p.drawRoundedRect(track_x, thumb_y, track_w, thumb_h, 3, 3)
        guide_color = QColor(self._qc_ln); guide_color.setAlpha(15)
        p.setPen(QPen(guide_color, 1, Qt.SolidLine))
        x0 = cr.left() + ln_width
        for i in range(1, 12):
            gx = int(x0 + i * self._tab_advance)
            if gx < cr.right() - 10: p.drawLine(gx, cr.top(), gx, cr.bottom())
        p.setClipRect(cr); p.setFont(self.font)
        n_vis_chars = len(visible_text)
        for si in range(n_drawn):
            li = scroll + si; lh = line_h_arr[si]; y = line_y_arr[si]; global_off = line_offsets[li]
            if self.show_line_numbers:
                if 0 <= current_scroll_line < n_drawn and li == cursor_line:
                    pill_rect = QRect(cr.left() + 2, y + 2, ln_width - 4, lh - 4)
                    p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(self._qc_accent)); p.setOpacity(0.15); p.drawRoundedRect(pill_rect, 4, 4); p.setOpacity(1.0)
                    p.setPen(self._qc_ln_active)
                else: p.setPen(self._qc_ln)
                p.drawText(QRect(cr.left(), y, ln_width, lh), Qt.AlignRight | Qt.AlignVCenter, str(li + 1))
            line = lines[li]
            if not line:
                if cursor_visible and li == cursor_line: self._draw_caret(p, int(x0), int(y + lh * 0.15), max(4, lh - 10))
                continue
            char_x = self._get_line_layout(line)
            cur_key = colors[global_off] if global_off < n_vis_chars else "foreground"
            cur_qc = qc.get(cur_key, fg)
            cur_err = vis_err[global_off] if global_off < len(vis_err) else False
            run_start = 0
            for j in range(1, len(line) + 1):
                next_qc = fg; next_err = False
                if j < len(line):
                    gp = global_off + j
                    next_key = colors[gp] if gp < n_vis_chars else "foreground"
                    next_qc = qc.get(next_key, fg)
                    next_err = vis_err[gp] if gp < len(vis_err) else False
                if j == len(line) or next_qc is not cur_qc or next_err != cur_err:
                    run_text = line[run_start:j].replace("\t", " " * self.tab_size)
                    if cur_err:
                        start_x = int(x0 + char_x[run_start]); end_x = int(x0 + char_x[j-1] + (self._tab_advance if line[j-1]=='\t' else self.fm.horizontalAdvance(line[j-1])))
                        if end_x > start_x:
                            err_bg = QColor(self._qc_error); err_bg.setAlpha(40)
                            p.setPen(Qt.PenStyle.NoPen); p.setBrush(err_bg); p.drawRoundedRect(start_x, y, end_x - start_x, lh, 2, 2)
                    p.setPen(self._qc_error if cur_err else cur_qc)
                    p.drawText(QPoint(int(x0 + char_x[run_start]), int(y + lh * 0.78)), run_text)
                    if cur_err:
                        start_x = int(x0 + char_x[run_start]); end_x = int(x0 + char_x[j-1] + (self._tab_advance if line[j-1]=='\t' else self.fm.horizontalAdvance(line[j-1])))
                        if end_x > start_x:
                            p.setPen(QPen(self._qc_error, 1, Qt.SolidLine)); y_under = int(y + lh * 0.88); p.drawLine(start_x, y_under, end_x, y_under)
                    cur_qc = next_qc; cur_err = next_err; run_start = j
            if cursor_visible and li == cursor_line:
                n_ch = len(line); is_err = False
                if n_ch > 0 and global_off + n_ch - 1 < len(vis_err): is_err = vis_err[global_off + n_ch - 1]
                if n_ch < len(char_x): self._draw_caret(p, int(x0 + char_x[n_ch]), int(y + lh * 0.15), max(4, lh - 10), is_err=is_err)
                else:
                    last_x = char_x[-1] if char_x else 0; last_char = line[-1] if line else " "; last_w = self._tab_advance if last_char == "\t" else self.fm.horizontalAdvance(last_char)
                    self._draw_caret(p, int(x0 + last_x + last_w), int(y + lh * 0.15), max(4, lh - 10), char=last_char, is_err=is_err)
        p.setClipping(False)
        if self.keyboard_overlay:
            ak = None; kf = 0.0
            if active_char is not None and key_flash > 0: ak = self.keyboard_overlay.resolve_key(active_char); kf = key_flash
            self.keyboard_overlay.draw(p, active_key=ak, flash=kf)
        if self.show_watermark and self.watermark_text:
            wm_font = QFont(self.font_family, max(10, int(self.font_size * 0.5)))
            p.setFont(wm_font)
            fm = QFontMetrics(wm_font)
            wm = self.watermark_text
            p.setPen(QPen(QColor(0, 0, 0, 150), 1))
            p.drawText(self.width - fm.horizontalAdvance(wm) - 18 + 1, self.height - 12 + 1, wm)
            p.setPen(QPen(QColor(255, 255, 255, 180), 1))
            p.drawText(self.width - fm.horizontalAdvance(wm) - 18, self.height - 12, wm)
        p.end(); return img
    def _draw_caret(self, p: QPainter, x: int, y: int, h: int, char: str = " ", is_err: bool = False) -> None:
        cw = max(2, self.fm.horizontalAdvance(char)); ch = max(4, h - 2)
        caret_color = self._qc_error if is_err else self._qc_cursor
        if self.cursor_glow: 
            gc = QColor(caret_color); gc.setAlpha(40); p.fillRect(x - 5, y - 4, cw + 10, ch + 8, gc)
            gc.setAlpha(90); p.fillRect(x - 2, y - 1, cw + 4, ch + 2, gc)
        p.fillRect(x, y, cw, ch, caret_color)
        if char not in (" ", "\t"): p.setPen(QColor(self.theme.background)); p.drawText(QRect(int(x), int(y), int(cw), int(ch)), Qt.AlignCenter, char)

class MultiPaneRenderer:
    __slots__ = ("panes", "frame_w", "frame_h", "num_panes", "pane_layout", "gap", "bg_color", "pane_rects")
    def __init__(self, panes: List[Tuple[CodeRenderer, TypingAnimator]], frame_w: int, frame_h: int, num_panes: int = 2, pane_layout: str = "Side by Side (50/50)", gap: int = 20, bg_color: str = "#0d0d12"):
        self.panes = panes; self.frame_w = frame_w; self.frame_h = frame_h; self.num_panes = max(1, min(num_panes, len(panes))); self.pane_layout = pane_layout; self.gap = gap; self.bg_color = bg_color; self.pane_rects = self._compute_pane_rects()
    def _compute_pane_rects(self) -> List[QRect]:
        W, H, g, n = self.frame_w, self.frame_h, self.gap, self.num_panes
        if n == 1: return [QRect(0, 0, W, H)]
        if n == 2:
            l = self.pane_layout
            match l:
                case "Stacked (50/50)": ph = (H - g) // 2; y_start = (H - (2 * ph + g)) // 2; return [QRect(0, y_start, W, ph), QRect(0, y_start + ph + g, W, ph)]
                case "Junior Big (70/30)": pw_l = int((W - g) * 0.7); return [QRect(0, 0, pw_l, H), QRect(pw_l + g, 0, W - g - pw_l, H)]
                case "Senior Big (70/30)": pw_l = int((W - g) * 0.3); return [QRect(0, 0, pw_l, H), QRect(pw_l + g, 0, W - g - pw_l, H)]
                case _: pw = (W - g) // 2; return [QRect(0, 0, pw, H), QRect(pw + g, 0, pw, H)]
        pw, ph = (W - g) // 2, (H - g) // 2
        return [QRect(0, 0, pw, ph), QRect(pw + g, 0, pw, ph), QRect(0, ph + g, pw, H - ph - g), QRect(pw + g, ph + g, pw, H - ph - g)]
    def duration(self) -> float: return max(anim.duration() for _, anim in self.panes) if self.panes else 0.0
    def char_timestamps_all(self) -> List[Tuple[float, str]]:
        all_ts: List[Tuple[float, str]] = []
        for _, anim in self.panes: all_ts.extend(anim.char_timestamps())
        return all_ts
    def compute_state(self, t: float) -> Tuple:
        states = []
        for renderer, animator in self.panes:
            nv = animator.visible_at(t); cur_vis = True
            if nv > 0:
                idx = bisect.bisect_right(animator._timestamps, t)
                if idx > 0:
                    last_ts = animator.timeline[idx - 1][0]
                    if t - last_ts > 0.25: cur_vis = (int((t - last_ts) / renderer.CURSOR_BLINK) % 2) == 0
            active_char, key_flash = animator.active_key_at(t)
            if not renderer.keyboard_overlay: active_char = None; key_flash = 0.0
            vis_text = animator.text_snapshots[nv]; vis_err = animator.error_snapshots[nv]; states.append((vis_text, vis_err, cur_vis, active_char, round(key_flash, 2)))
        return tuple(states)
    def render_frame(self, t: float, target: Optional[QImage] = None, precomputed_state: Optional[Tuple] = None) -> QImage:
        img = target if target is not None else QImage(self.frame_w, self.frame_h, QImage.Format_RGB32)
        p = QPainter(img); p.setRenderHint(QPainter.SmoothPixmapTransform)
        v_grad = QRadialGradient(self.frame_w/2, self.frame_h/2, max(self.frame_w, self.frame_h)/1.5)
        v_grad.setColorAt(0, QColor(self.bg_color)); darker = QColor(self.bg_color).darker(150); v_grad.setColorAt(1, darker)
        p.fillRect(0, 0, self.frame_w, self.frame_h, QBrush(v_grad))
        if precomputed_state is None: precomputed_state = self.compute_state(t)
        sorted_indices = sorted(range(len(self.panes)), key=lambda i: self.pane_rects[i].width() * self.pane_rects[i].height(), reverse=True)
        for i in sorted_indices:
            if i >= len(precomputed_state): break
            vis_text, vis_err, cur_vis, active_char, key_flash = precomputed_state[i]; renderer, animator = self.panes[i]; rect = self.pane_rects[i]
            pane_img = renderer.render_frame(vis_text, vis_err, cur_vis, active_char=active_char, key_flash=key_flash); p.drawImage(rect.topLeft(), pane_img)
        p.end(); return img

class TextRenderer:
    TOKEN_COLOR_MAP = {"keyword":"keyword","builtin":"builtin","string":"string","number":"number","comment":"comment","decorator":"decorator","function":"function","class_name":"class_name","operator":"operator","bracket":"builtin"}
    CURSOR_BLINK = 0.53
    def __init__(self, width: int, height: int, theme_name: str = "Dracula", font_family: str = "Consolas", font_size: int = 22, show_line_numbers: bool = True, show_window_chrome: bool = True, padding: int = 24, tab_size: int = 4, title_text: str = "document.txt", language: str = "Text", keyboard_overlay: Optional[KeyboardOverlay] = None, bg_image_path: Optional[str] = None, total_lines: int = 0, cursor_glow: bool = True, show_watermark: bool = False):
        self.width = width; self.height = height; self.theme = THEMES.get(theme_name, THEMES["Dracula"]); self.font_family = font_family; self.font_size = font_size; self.show_line_numbers = show_line_numbers; self.show_window_chrome = show_window_chrome; self.padding = padding; self.tab_size = tab_size; self.title_text = title_text; self.language = language; self.keyboard_overlay = keyboard_overlay; self.total_lines = total_lines; self.cursor_glow = cursor_glow; self.show_watermark = show_watermark
        _families = [font_family, "JetBrains Mono", "DejaVu Sans Mono", "Liberation Mono", "Courier New", "monospace"]; _available = QFontDatabase.families(); chosen = "monospace"
        for f in _families:
            if f in _available: chosen = f; break
        self.font = QFont(chosen, font_size); self.font.setFamilies(_families + ["Noto Color Emoji", "Apple Color Emoji", "Segoe UI Emoji"]); self.font.setFixedPitch(True); self.fm = QFontMetrics(self.font); self.char_w = self.fm.horizontalAdvance("M"); self.line_h = self.fm.height()
        self._qcolors = {k: QColor(v) for k, v in vars(self.theme).items() if isinstance(v, str) and v.startswith("#")}; self._qc_fg = self._qcolors.get("foreground", QColor("#f8f8f2")); self._qc_ln = self._qcolors.get("line_number", QColor("#6272a4")); self._qc_cursor = self._qcolors.get("cursor", QColor("#f8f8f2")); self._qc_current_line = self._qcolors.get("current_line", QColor("#44475a"))
        self.bg_image = (QImage(bg_image_path) if bg_image_path and os.path.exists(bg_image_path) else None); self._build_bg_cache()
        self._layout_nv: Union[str, int] = -1; self._layout_lines: List[str] = []; self._layout_offsets: List[int] = []; self._layout_cursor_line: int = 0
        self._line_cache: "OrderedDict[str, List[int]]" = OrderedDict(); self._tab_advance = self.char_w * self.tab_size
    @staticmethod
    def auto_font_size(lines_count: int, width: int, height: int, padding: int = 24, show_window_chrome: bool = True, show_line_numbers: bool = True, tab_size: int = 4, text: Optional[str] = None, font_family: str = "Consolas", keyboard_h: int = 0) -> int:
        chrome_h = 42 if show_window_chrome else 0; kb_used = min(keyboard_h, (height - 2 * padding) // 3) if keyboard_h > 0 else 0; rect_h = height - 2 * padding - kb_used - chrome_h; rect_w = width - 2 * padding - 8
        if rect_h < 20 or rect_w < 40 or lines_count < 1: return 14
        max_chars = 80
        if text: max_chars = max(max(len(line.replace("\t", " " * tab_size)) for line in text.split("\n")), 1)
        def _ln_w(cw: int) -> int: return (len(str(lines_count)) * cw + 16) if show_line_numbers else 0
        max_font = max(14, min(48, int(width / 80))); target_vis = min(lines_count, 35); max_check = min(max_chars, 120); lo, hi, best = 8, max_font, 14
        while lo <= hi:
            mid = (lo + hi) // 2; fm = QFontMetrics(QFont(font_family, mid)); lh = fm.height()
            if target_vis * lh <= rect_h:
                cw = fm.horizontalAdvance("M")
                if max_check * cw + _ln_w(cw) <= rect_w: best = mid; lo = mid + 1
                else: hi = mid - 1
            else: hi = mid - 1
        return max(8, best)
    def _get_line_layout(self, line: str) -> List[int]:
        cached = self._line_cache.get(line)
        if cached is not None: return cached
        char_x: List[int] = []; x = 0; tab = self._tab_advance; ham = self.fm.horizontalAdvance
        for ch in line: char_x.append(x); x += tab if ch == "\t" else ham(ch)
        char_x.append(x)
        if len(self._line_cache) >= 512: self._line_cache.popitem(last=False)
        self._line_cache[line] = char_x; return char_x
    def _tokenize_to_colors(self, text: str) -> List[str]:
        tokens = Tokenizer.tokenize(text, self.language); colors: List[str] = ["foreground"] * len(text); pos = 0; get = self.TOKEN_COLOR_MAP.get
        for ttype, ttxt in tokens:
            ckey = get(ttype, "foreground"); end = min(pos + len(ttxt), len(colors)); colors[pos:end] = [ckey] * (end - pos); pos = end
        return colors
    def _build_bg_cache(self) -> None:
        self._bg = QImage(self.width, self.height, QImage.Format_RGB32); self._bg.fill(QColor(self.theme.background)); p = QPainter(self._bg); p.setRenderHint(QPainter.Antialiasing)
        if self.bg_image: scaled = self.bg_image.scaled(self.width, self.height, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation); p.drawImage((self.width - scaled.width()) // 2, (self.height - scaled.height()) // 2, scaled); p.fillRect(0, 0, self.width, self.height, QColor(0, 0, 0, 130))
        else: bg = self._qcolors.get("background", QColor("#282a36")); g = QLinearGradient(0, 0, 0, self.height); g.setColorAt(0, bg.lighter(105)); g.setColorAt(1, bg); p.fillRect(0, 0, self.width, self.height, g)
        w, h, pad = self.width, self.height, self.padding; chrome_h = 42 if self.show_window_chrome else 0; kb_reserve = (min(self.keyboard_overlay.height_needed(), (h - 2 * pad) // 3) if self.keyboard_overlay else 0); wx, wy, ww, wh = pad, pad, w - 2 * pad, h - 2 * pad - kb_reserve
        p.setPen(Qt.PenStyle.NoPen)
        for s in range(6, 0, -1): p.setBrush(QColor(0, 0, 0, int(40 - s * 5))); p.drawRoundedRect(wx - s, wy - s + (s // 2), ww + 2 * s, wh + 2 * s, 12 + s, 12 + s)
        p.setPen(QColor(self.theme.window_border)); p.setBrush(QColor(self.theme.background)); p.drawRoundedRect(wx, wy, ww, wh, 12, 12)
        if self.show_window_chrome:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(self.theme.title_bar)); p.drawRoundedRect(wx, wy, ww, chrome_h, 12, 12); p.drawRect(wx, wy + chrome_h - 12, ww, 12)
            for i, color in enumerate(["#ff5f56", "#ffbd2e", "#27c93f"]): p.setBrush(QColor(color)); p.setPen(Qt.PenStyle.NoPen); p.drawEllipse(QPoint(wx + 20 + i * 24, wy + 19), 7, 7)
            p.setPen(QColor(self.theme.title_text)); p.setFont(QFont(self.font_family, max(8, self.font_size // 3))); p.drawText(QRect(wx, wy, ww, chrome_h), Qt.AlignCenter, self.title_text)
            code_top = wy + chrome_h
        else: code_top = wy
        self._code_rect = QRect(wx + 4, code_top, ww - 8, wh - (code_top - wy))
        if self.keyboard_overlay: self.keyboard_overlay.reposition(wy + wh + max(8, h // 60))
        p.end()
    def render_frame(self, display_chars: List[str], num_visible: int, cursor_visible: bool = True, target: Optional[QImage] = None, active_char: Optional[str] = None, key_flash: float = 0.0) -> QImage:
        img = target if target is not None else QImage(self.width, self.height, QImage.Format_RGB32)
        if target is None: img.fill(QColor(self.theme.background))
        p = QPainter(img); p.setRenderHint(QPainter.TextAntialiasing); p.drawImage(0, 0, self._bg); cr = self._code_rect
        visible_text = "".join(display_chars[:num_visible])
        colors = self._tokenize_to_colors(visible_text)
        if visible_text != self._layout_nv:
            self._layout_lines = visible_text.split("\n"); offsets: List[int] = []; off = 0
            for ln in self._layout_lines: offsets.append(off); off += len(ln) + 1
            self._layout_offsets = offsets; self._layout_cursor_line = visible_text.count("\n"); self._layout_nv = visible_text
        lines = self._layout_lines; line_offsets = self._layout_offsets; cursor_line = self._layout_cursor_line; total_lines = len(lines)
        cr_h, cr_top = cr.height(), cr.top(); max_vis = max(1, -(-cr_h // self.line_h)); lh_base = self.line_h
        scroll = 0; margin_bottom = max(3, max_vis // 4); margin_top = 3
        if cursor_line >= scroll + max_vis - margin_bottom: scroll = max(0, cursor_line - max_vis + margin_bottom + 1)
        if cursor_line < scroll + margin_top: scroll = max(0, cursor_line - margin_top)
        if scroll > max(0, total_lines - max_vis): scroll = max(0, total_lines - max_vis)
        ln_width = (len(str(total_lines + scroll)) * self.char_w + 16) if self.show_line_numbers else 0
        current_scroll_line = cursor_line - scroll
        line_y_arr: List[int] = []; line_h_arr: List[int] = []; y_acc = cr_top
        for si in range(max_vis):
            li = scroll + si
            if li >= total_lines: break
            line_y_arr.append(y_acc); line_h_arr.append(lh_base); y_acc += lh_base
        n_drawn = len(line_y_arr)
        if 0 <= current_scroll_line < n_drawn:
            p.fillRect(cr.left(), line_y_arr[current_scroll_line], cr.width(), line_h_arr[current_scroll_line], self._qc_current_line)
        if self.show_line_numbers and ln_width > 0:
            sep_x = cr.left() + ln_width; sc = QColor(self._qc_ln); sc.setAlpha(60); p.setPen(QPen(sc, 1)); p.drawLine(sep_x, cr.top(), sep_x, cr.top() + max_vis * lh_base)
        p.setClipRect(cr); p.setFont(self.font); x0 = cr.left() + ln_width
        n_vis_chars = len(visible_text); fg = self._qc_fg; qc = self._qcolors
        for si in range(n_drawn):
            li = scroll + si; lh = line_h_arr[si]; y = line_y_arr[si]; global_off = line_offsets[li]
            if self.show_line_numbers:
                p.setPen(self._qc_ln)
                p.drawText(QRect(cr.left(), y, ln_width, lh), Qt.AlignRight | Qt.AlignVCenter, str(li + 1))
            line = lines[li]
            if not line:
                if cursor_visible and li == cursor_line: self._draw_caret(p, int(x0), int(y + lh * 0.18), max(4, lh - 10))
                continue
            char_x = self._get_line_layout(line)
            cur_key = colors[global_off] if global_off < n_vis_chars else "foreground"
            cur_qc = qc.get(cur_key, fg)
            run_start = 0
            for j in range(1, len(line) + 1):
                next_qc = fg
                if j < len(line):
                    gp = global_off + j
                    next_key = colors[gp] if gp < n_vis_chars else "foreground"
                    next_qc = qc.get(next_key, fg)
                if j == len(line) or next_qc is not cur_qc:
                    run_text = line[run_start:j].replace("\t", " " * self.tab_size)
                    p.setPen(cur_qc)
                    p.drawText(QPoint(int(x0 + char_x[run_start]), int(y + lh * 0.78)), run_text)
                    cur_qc = next_qc; run_start = j
            if cursor_visible and li == cursor_line:
                n_ch = len(line)
                if n_ch < len(char_x): cx = char_x[n_ch]
                else:
                    last_x = char_x[-1] if char_x else 0
                    cx = last_x + (self._tab_advance if line and line[-1] == "\t" else (self.fm.horizontalAdvance(line[-1]) if line else 0))
                self._draw_caret(p, int(x0 + cx), int(y + lh * 0.18), max(4, lh - 10))
        p.setClipping(False)
        if self.keyboard_overlay:
            ak = None; kf = 0.0
            if active_char is not None and key_flash > 0: ak = self.keyboard_overlay.resolve_key(active_char); kf = key_flash
            self.keyboard_overlay.draw(p, active_key=ak, flash=kf)
        p.end(); return img
    def _draw_caret(self, p: QPainter, x: int, y: int, h: Optional[int] = None):
        w = max(2, self.font_size // 10); caret_h = h if h is not None else self.line_h - 10
        if self.cursor_glow:
            gc = QColor(self._qc_cursor); gc.setAlpha(60); p.fillRect(x - w, y - 2, w * 3, caret_h + 4, gc)
            gc.setAlpha(100); p.fillRect(x - 1, y - 1, w * 2, caret_h + 2, gc)
        p.fillRect(x, y, w, caret_h, self._qc_cursor)
