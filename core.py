from __future__ import annotations
from collections import OrderedDict
from pathlib import Path
from typing import Dict, FrozenSet, Final, Optional, Tuple, List
from contextlib import contextmanager
from dataclasses import dataclass
import logging, os, platform, subprocess, tempfile, shutil, threading, json, math, unicodedata
import numpy as np

CWD: Final[Path] = Path.cwd()
INPUT_DIR: Final[Path] = CWD / "input"
OUTPUT_DIR: Final[Path] = CWD / "output"
TEMP_DIR: Final[Path] = CWD / "temp"
SETTINGS_FILE: Final[Path] = CWD / "settings.json"

for _d in (INPUT_DIR, OUTPUT_DIR, TEMP_DIR): _d.mkdir(parents=True, exist_ok=True)

SUPPORTED_EXTENSIONS: FrozenSet[str] = frozenset({".py",".js",".ts",".jsx",".tsx",".java",".c",".cpp",".h",".hpp",".cs",".go",".rs",".rb",".php",".swift",".kt",".sh",".bash",".zsh",".sql",".html",".htm",".css",".scss",".json",".yaml",".yml",".toml",".ini",".cfg",".txt",".md",".lua",".dart",".r",".m",".csv",".asc",".ascii",".art",".nfo",".diz",".emoji",".emo"})
SKIP_DIRS: FrozenSet[str] = frozenset({".git",".hg",".svn","__pycache__","node_modules",".venv","venv",".env",".idea",".vscode","dist","build",".tox",".mypy_cache",".pytest_cache",".next",".nuxt","target","vendor",".bundle"})
EXT_TO_LANGUAGE: Dict[str, str] = {".py":"Python",".js":"JavaScript",".jsx":"JavaScript",".ts":"TypeScript",".tsx":"TypeScript",".java":"Java",".c":"CFamily",".cpp":"CFamily",".h":"CFamily",".hpp":"CFamily",".cs":"CSharp",".go":"Go",".rs":"Rust",".rb":"Ruby",".php":"PHP",".swift":"CFamily",".kt":"Java",".sh":"Bash",".bash":"Bash",".zsh":"Bash",".sql":"SQL",".html":"HTML",".htm":"HTML",".css":"CSS",".scss":"SCSS",".json":"JSON",".yaml":"YAML",".yml":"YAML",".md":"Markdown",".txt":"Text",".lua":"Lua",".dart":"Dart",".r":"R",".m":"MATLAB",".csv":"Text",".asc":"ASCII Art",".ascii":"ASCII Art",".art":"ASCII Art",".nfo":"ASCII Art",".diz":"ASCII Art",".emoji":"Emoji Art",".emo":"Emoji Art"}
JR_VS_SR_EXTENSIONS = frozenset({".json"})
CODE_EXTENSIONS = SUPPORTED_EXTENSIONS - JR_VS_SR_EXTENSIONS
AUDIO_SAMPLE_RATE: int = 48000

EXPORT_FORMATS: Dict[str, dict] = {
    "YouTube (16:9)": {"resolutions": OrderedDict([("1920x1080",(1920,1080)),("1280x720",(1280,720)),("3840x2160",(3840,2160))]),"orientation":"landscape"},
    "YouTube Shorts (9:16)": {"resolutions": OrderedDict([("1080x1920",(1080,1920)),("720x1280",(720,1280))]),"orientation":"portrait"},
    "Both (YT + Shorts)": {"resolutions": OrderedDict([("1920x1080",(1920,1080)),("1080x1920",(1080,1920))]),"orientation":"both"}
}

ENCODERS: Dict[str, dict] = {
    "YouTube Pro (H.264/AAC)": {"base": ["-c:v","libx264","-preset","slow","-crf","17","-profile:v","high","-pix_fmt","yuv420p"],"use_dynamic_vbv":True,"use_dynamic_gop":True,"color_tags":True},
    "x264 (CPU, Fast)": {"base": ["-c:v","libx264","-preset","medium","-crf","20","-pix_fmt","yuv420p"],"use_dynamic_gop":True,"color_tags":True},
    "NVENC (NVIDIA)": {"base": ["-c:v","h264_nvenc","-preset","p5","-rc","vbr","-cq","19","-b:v","0","-pix_fmt","yuv420p"],"use_dynamic_gop":True,"color_tags":True},
    "QSV (Intel)": {"base": ["-c:v","h264_qsv","-preset","medium","-global_quality","19","-pix_fmt","yuv420p"],"use_dynamic_gop":True,"color_tags":True},
    "AMF (AMD)": {"base": ["-c:v","h264_amf","-preset","speed","-rc","cqp","-qp_i","19","-qp_p","19","-pix_fmt","yuv420p"],"use_dynamic_gop":True,"color_tags":True}
}

class StudioError(Exception): pass
class RenderingError(StudioError): pass
class AudioGenerationError(StudioError): pass
class ExportError(StudioError): pass
class FFmpegError(ExportError): pass

log = logging.getLogger("TypingStudio"); log.setLevel(logging.DEBUG)
_sh = logging.StreamHandler(); _sh.setLevel(logging.WARNING); log.addHandler(_sh)

def setup_project_logging(project_name: str) -> None:
    for h in log.handlers[:]:
        if isinstance(h, logging.FileHandler): log.removeHandler(h); h.close()
    fh = logging.FileHandler(f"{project_name}.log", mode="w", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(threadName)-20s | %(message)s", datefmt="%H:%M:%S"))
    log.addHandler(fh)

def _subprocess_startup_info() -> Optional[subprocess.STARTUPINFO]:
    if platform.system() == "Windows":
        si = subprocess.STARTUPINFO(); si.dwFlags |= subprocess.STARTF_USESHOWWINDOW; si.wShowWindow = subprocess.SW_HIDE; return si
    return None

@contextmanager
def temp_directory(prefix: str = "export_"):
    tmp = tempfile.mkdtemp(dir=str(TEMP_DIR), prefix=prefix)
    try: yield tmp
    finally: shutil.rmtree(tmp, ignore_errors=True)

@dataclass(frozen=True, slots=True)
class Theme:
    name: str; background: str; foreground: str; comment: str; keyword: str; string: str; number: str; function: str; builtin: str; decorator: str; operator: str; class_name: str; line_number: str; current_line: str; cursor: str; title_bar: str; title_text: str; window_border: str; junior_accent: str = "#7aa2f7"; senior_accent: str = "#9ece6a"

class ThemeRegistry:
    _instance = None; _lock = threading.Lock()
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls); cls._instance._themes: Dict[str, Theme] = {}; cls._instance._load_defaults()
        return cls._instance
    def _load_defaults(self) -> None:
        raw = {
            "Dracula": {"background":"#282a36","foreground":"#f8f8f2","comment":"#6272a4","keyword":"#ff79c6","string":"#f1fa8c","number":"#bd93f9","function":"#50fa7b","builtin":"#8be9fd","decorator":"#50fa7b","operator":"#ff79c6","class_name":"#8be9fd","line_number":"#6272a4","current_line":"#44475a","cursor":"#f8f8f2","title_bar":"#21222c","title_text":"#8be9fd","window_border":"#191a21","junior_accent":"#8be9fd","senior_accent":"#50fa7b"},
            "Tokyo Night": {"background":"#16171e","foreground":"#c0caf5","comment":"#565f89","keyword":"#bb9af7","string":"#9ece6a","number":"#ff9e64","function":"#7aa2f7","builtin":"#7aa2f7","decorator":"#e0af68","operator":"#89ddff","class_name":"#7dcfff","line_number":"#3b4261","current_line":"#1a1b26","cursor":"#c0caf5","title_bar":"#1a1b26","title_text":"#7aa2f7","window_border":"#16171e","junior_accent":"#7aa2f7","senior_accent":"#9ece6a"},
            "One Dark": {"background":"#282c34","foreground":"#abb2bf","comment":"#5c6370","keyword":"#c678dd","string":"#98c379","number":"#d19a66","function":"#61afef","builtin":"#e5c07b","decorator":"#56b6c2","operator":"#c678dd","class_name":"#e5c07b","line_number":"#4b5263","current_line":"#2c313c","cursor":"#528bff","title_bar":"#21252b","title_text":"#61afef","window_border":"#181a1f","junior_accent":"#61afef","senior_accent":"#98c379"},
            "GitHub Dark": {"background":"#0d1117","foreground":"#c9d1d9","comment":"#8b949e","keyword":"#ff7b72","string":"#a5d6ff","number":"#79c0ff","function":"#d2a8ff","builtin":"#ffa657","decorator":"#ffa657","operator":"#ff7b72","class_name":"#ffa657","line_number":"#484f58","current_line":"#161b22","cursor":"#58a6ff","title_bar":"#010409","title_text":"#58a6ff","window_border":"#010409","junior_accent":"#58a6ff","senior_accent":"#7ee787"},
            "Monokai": {"background":"#272822","foreground":"#f8f8f2","comment":"#75715e","keyword":"#f92672","string":"#e6db74","number":"#ae81ff","function":"#a6e22e","builtin":"#66d9ef","decorator":"#a6e22e","operator":"#f92672","class_name":"#66d9ef","line_number":"#75715e","current_line":"#3e3d32","cursor":"#f8f8f2","title_bar":"#1e1f1c","title_text":"#a6e22e","window_border":"#1e1f1c","junior_accent":"#66d9ef","senior_accent":"#a6e22e"},
            "Solarized Dark": {"background":"#002b36","foreground":"#839496","comment":"#586e75","keyword":"#859900","string":"#2aa198","number":"#d33682","function":"#268bd2","builtin":"#b58900","decorator":"#cb4b16","operator":"#859900","class_name":"#b58900","line_number":"#073642","current_line":"#073642","cursor":"#839496","title_bar":"#073642","title_text":"#268bd2","window_border":"#002b36","junior_accent":"#268bd2","senior_accent":"#859900"},
            "VS Code Dark+": {"background":"#1e1e1e","foreground":"#d4d4d4","comment":"#6a9955","keyword":"#569cd6","string":"#ce9178","number":"#b5cea8","function":"#dcdcaa","builtin":"#4ec9b0","decorator":"#4ec9b0","operator":"#d4d4d4","class_name":"#4ec9b0","line_number":"#858585","current_line":"#2a2d2e","cursor":"#aeafad","title_bar":"#323233","title_text":"#007acc","window_border":"#323233","junior_accent":"#569cd6","senior_accent":"#dcdcaa"},
            "Light (Paper)": {"background":"#fafafa","foreground":"#383a42","comment":"#a0a1a7","keyword":"#a626a4","string":"#50a14f","number":"#986801","function":"#4078f2","builtin":"#c18401","decorator":"#4078f2","operator":"#a626a4","class_name":"#c18401","line_number":"#d0d0d0","current_line":"#f0f0f0","cursor":"#383a42","title_bar":"#e8e8e8","title_text":"#4078f2","window_border":"#d0d0d0","junior_accent":"#4078f2","senior_accent":"#50a14f"}
        }
        for name, d in raw.items(): self._themes[name] = Theme(name=name, **d)
    def get(self, name: str) -> Theme: return self._themes.get(name, self._themes["Dracula"])
    def names(self) -> list: return list(self._themes.keys())

THEMES: Dict[str, Theme] = {name: ThemeRegistry().get(name) for name in ThemeRegistry().names()}

ZWJ = '\u200d'; VS16 = '\ufe0f'
def _split_graphemes(text: str) -> List[str]:
    graphemes = []; i = 0; n = len(text)
    while i < n:
        c = text[i]; i += 1
        while i < n:
            nxt = text[i]
            if nxt == ZWJ or nxt == VS16 or unicodedata.combining(nxt) != 0:
                c += nxt; i += 1
                if c[-1] == ZWJ and i < n: c += text[i]; i += 1
            else: break
        graphemes.append(c)
    return graphemes

EXAMPLES_JR_VS_SR: Dict[str, dict] = {
    "fibonacci_jr_vs_sr.json": {"name": "Fibonacci","language": "Python","junior_code": "def fib(n):\n    if n <= 1:\n        return n\n    else:\n        return fib(n - 1) + fib(n - 2)\n\nfor i in range(10):\n    print(fib(i))\n","senior_code": "from functools import lru_cache\n\n@lru_cache(maxsize=None)\ndef fib(n: int) -> int:\n    \"\"\"Return the n-th Fibonacci number (memoised).\"\"\"\n    if n < 2:\n        return n\n    return fib(n - 1) + fib(n - 2)\n\nprint([fib(i) for i in range(100)])\n"},
}
EXAMPLES_MULTI_WINDOW: Dict[str, str] = {"bubble_sort.py": "def bubble_sort(arr):\n    n = len(arr)\n    for i in range(n):\n        for j in range(0, n - i - 1):\n            if arr[j] > arr[j + 1]:\n                arr[j], arr[j + 1] = arr[j + 1], arr[j]\n    return arr\n\nprint(bubble_sort([64, 34, 25, 12, 22, 11, 90]))\n"}
EXAMPLES_YOUTUBE: Dict[str, str] = {"tcp_echo_server.py": "import socket\nimport threading\n\ndef handle_client(conn, addr):\n    print(f'Connected by {addr}')\n    while True:\n        data = conn.recv(1024)\n        if not data: break\n        conn.sendall(data)\n    conn.close()\n"}
EXAMPLES_TEXT: Dict[str, str] = {"sample.txt": "The Art of Writing\n\nWriting is a medium of human communication that represents language.\n\n1. Clarity\n2. Conciseness\n3. Coherence\n4. Correctness\n5. Engagement\n\n\"Good writing is clear thinking made visible.\""}
EXAMPLES_EMOJI_ASCII: Dict[str, str] = "hello.emoji": "👋🌍✨\n\nFamily: 👨‍👩‍👧‍👦\nCouple: 👩‍❤️‍👨\n\n🎉🎊🎈🥳", "logo.asc": "  _____  _____  _____ _____   ____   ___  \n |  __ ||  __ ||  __ |  ___| |  _ | / _ | \n | |_/ || |_/ || |_/ | |___  | |_| || | | |\n |    / |    / |    /|  ___| |  _  || | | |\n | |\ \ | |\ \ | |\ \| |___  | | | || |_| |\n \_| |_|\_| |_|\_| \_\_____| \_| |_|\___/ \n"}

def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as f: json.dump(data, f, indent=2, ensure_ascii=False)
def _write_text(path, content):
    with open(path, "w", encoding="utf-8") as f: f.write(content)

def ensure_examples_for_project(project: str) -> int:
    input_dir = str(INPUT_DIR)
    if not os.path.isdir(input_dir): return 0
    written = 0; examples = {}
    if project == "jr_vs_sr": examples = EXAMPLES_JR_VS_SR
    elif project == "multi_window": examples = EXAMPLES_MULTI_WINDOW
    elif project == "youtube": examples = EXAMPLES_YOUTUBE
    elif project == "text": examples = EXAMPLES_TEXT
    elif project == "emoji_ascii": examples = EXAMPLES_EMOJI_ASCII
    
    if project == "jr_vs_sr":
        existing = [f for f in os.listdir(input_dir) if f.lower().endswith(".json")]
    else:
        existing = [f for f in os.listdir(input_dir) if os.path.splitext(f)[1].lower() in CODE_EXTENSIONS]
        
    if not existing and examples:
        for fname, content in examples.items():
            if isinstance(content, dict): _write_json(os.path.join(input_dir, fname), content)
            else: _write_text(os.path.join(input_dir, fname), content)
            written += 1
    return written

def load_jr_vs_sr_json(path: str) -> Tuple[str, str, str, str]:
    with open(path, "r", encoding="utf-8") as f: data = json.load(f)
    name = data.get("name") or os.path.splitext(os.path.basename(path))[0]
    language = data.get("language", "Python")
    junior = data.get("junior_code") or data.get("code", "")
    senior = data.get("senior_code") or data.get("code", "")
    return name, language, junior, senior

def format_duration(seconds: float) -> str:
    if seconds is None or math.isnan(seconds) or seconds < 0: return "--:--"
    total = int(round(seconds)); h, rem = divmod(total, 3600); m, s = divmod(rem, 60)
    if h > 0: return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"
