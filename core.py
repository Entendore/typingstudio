"""Core configuration, strict schemas, OS abstractions, and FileScanner."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Final, Dict
from abc import ABC, abstractmethod
import json, os, platform, subprocess, logging, threading
from collections import defaultdict
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal

CWD: Final[Path] = Path(__file__).resolve().parent.parent
INPUT_DIR: Final[Path] = CWD / "input"
OUTPUT_DIR: Final[Path] = CWD / "output"
SETTINGS_FILE: Final[Path] = CWD / "settings.json"

for d in (INPUT_DIR, OUTPUT_DIR): d.mkdir(parents=True, exist_ok=True)

log = logging.getLogger("TypingAnimStudio")
log.setLevel(logging.DEBUG)
log.addHandler(logging.StreamHandler())

def setup_project_logging(project_name: str) -> None:
    for h in log.handlers[:]:
        if isinstance(h, logging.FileHandler):
            log.removeHandler(h); h.close()
    fh = logging.FileHandler(str(CWD / f"{project_name}.log"), mode="w", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(threadName)-20s | %(message)s", datefmt="%H:%M:%S"))
    log.addHandler(fh)

@dataclass(frozen=True, slots=True)
class AppSettingsSchema:
    theme: str = "Dracula"
    fmt: str = "YouTube (16:9)"
    wpm: int = 100
    j_wpm: int = 90
    s_wpm: int = 130
    sound: str = "Mechanical"
    volume: int = 80
    resolution: str = "1080p"
    speed: float = 1.0
    loop: bool = False
    yt_title: str = "TypingAnimStudio Demo"
    yt_channel: str = "@code_typing"
    multi_stagger: float = 0.2
    text_font_size: int = 17
    ascii_font_size: int = 14
    ascii_color_mode: str = "Rainbow"

    def __post_init__(self):
        if not (10 <= self.wpm <= 500): object.__setattr__(self, 'wpm', max(10, min(500, self.wpm)))
        if not (10 <= self.j_wpm <= 500): object.__setattr__(self, 'j_wpm', max(10, min(500, self.j_wpm)))
        if not (10 <= self.s_wpm <= 500): object.__setattr__(self, 's_wpm', max(10, min(500, self.s_wpm)))
        if not (0 <= self.volume <= 100): object.__setattr__(self, 'volume', max(0, min(100, self.volume)))

class SettingsRepository:
    def __init__(self, file_path: Path): self._file_path = file_path; self._data = {}; self._load()
    def _load(self):
        if self._file_path.exists():
            try:
                with open(self._file_path, "r", encoding="utf-8") as f: self._data = json.load(f)
            except Exception: self._data = {}
    def get(self, key: str) -> AppSettingsSchema:
        raw = self._data.get(key, {})
        try: return AppSettingsSchema(**raw)
        except TypeError: return AppSettingsSchema()
    def save(self, key: str, schema: AppSettingsSchema):
        self._data[key] = asdict(schema)
        with open(self._file_path, "w", encoding="utf-8") as f: json.dump(self._data, f, indent=2)

class EventBus(QObject):
    file_scanned = Signal(list)
    def __init__(self, parent=None): super().__init__(parent); self._subs = defaultdict(list)
    def subscribe(self, event: str, handler: Callable): self._subs[event].append(handler)
    def publish(self, event: str, *args, **kwargs):
        for h in self._subs.get(event, []):
            try: h(*args, **kwargs)
            except Exception: log.exception("Event handler failed")

bus = EventBus()

class FileScanner(QObject):
    files_changed = Signal(list)
    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self.path = path
        self._files = set()
        self._timer = QTimer(self)
        self._timer.setInterval(1500)
        self._timer.timeout.connect(self._scan)
        self._timer.start()
        self._scan()

    def _scan(self):
        if not self.path.is_dir(): return
        current = set()
        for f in os.listdir(self.path):
            if (self.path / f).is_file(): current.add(f)
        if current != self._files:
            self._files = current
            self.files_changed.emit(sorted(list(current)))

class ProcessFactory(ABC):
    @abstractmethod
    def create_popen(self, cmd: list, **kwargs) -> subprocess.Popen: pass

class WindowsProcessFactory(ProcessFactory):
    def create_popen(self, cmd: list, **kwargs) -> subprocess.Popen:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        kwargs['startupinfo'] = si; kwargs['close_fds'] = True
        return subprocess.Popen(cmd, **kwargs)

class PosixProcessFactory(ProcessFactory):
    def create_popen(self, cmd: list, **kwargs) -> subprocess.Popen:
        kwargs['close_fds'] = True
        return subprocess.Popen(cmd, **kwargs)

def get_process_factory() -> ProcessFactory:
    return WindowsProcessFactory() if platform.system() == "Windows" else PosixProcessFactory()

@dataclass(frozen=True, slots=True)
class Theme:
    name: str; background: str; foreground: str; keyword: str; string: str; function: str

class ThemeRegistry:
    _themes = {
        "Dracula": Theme("Dracula", "#282a36", "#f8f8f2", "#ff79c6", "#f1fa8c", "#50fa7b"),
        "Tokyo Night": Theme("Tokyo Night", "#1a1b26", "#c0caf5", "#bb9af7", "#9ece6a", "#7aa2f7"),
        "Monokai": Theme("Monokai", "#272822", "#f8f8f2", "#f92672", "#e6db74", "#a6e22e"),
        "Nord": Theme("Nord", "#2e3440", "#d8dee9", "#81a1c1", "#ebcb8b", "#88c0d0"),
        "Solarized": Theme("Solarized", "#002b36", "#839496", "#859900", "#2aa198", "#268bd2"),
        "GitHub Dark": Theme("GitHub Dark", "#0d1117", "#c9d1d9", "#ff7b72", "#a5d6ff", "#d2a8ff"),
        "One Dark": Theme("One Dark", "#282c34", "#abb2bf", "#c678dd", "#98c379", "#61afef"),
    }
    @classmethod
    def get(cls, name: str) -> Theme: return cls._themes.get(name, cls._themes["Dracula"])
    @classmethod
    def names(cls) -> list: return list(cls._themes.keys())

THEMES = {n: ThemeRegistry.get(n) for n in ThemeRegistry.names()}
