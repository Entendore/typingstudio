"""Comprehensive DSP Pipeline, Realistic Audio Synthesis, and Presets."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Dict
import numpy as np
import io, wave, random, math

class AudioProcessor(ABC):
    @abstractmethod
    def process(self, x: np.ndarray, sr: int) -> np.ndarray: pass

class DCEqualizer(AudioProcessor):
    def process(self, x: np.ndarray, sr: int) -> np.ndarray:
        if x.size == 0: return x
        return x - np.mean(x)

class HighPassFilter(AudioProcessor):
    def __init__(self, cutoff=80.0): self.cutoff = cutoff
    def process(self, x: np.ndarray, sr: int) -> np.ndarray:
        alpha = 1.0 - np.exp(-2.0 * np.pi * self.cutoff / sr)
        y = np.zeros_like(x)
        y[0] = x[0]
        for i in range(1, len(x)): y[i] = alpha * (y[i-1] + x[i] - x[i-1])
        return y

class RMSCompressor(AudioProcessor):
    def __init__(self, threshold_db: float = -12.0, ratio: float = 4.0, window_ms: int = 20):
        self.threshold = 10 ** (threshold_db / 20.0)
        self.ratio = ratio
        self.window_ms = window_ms
    def process(self, x: np.ndarray, sr: int) -> np.ndarray:
        if x.size == 0: return x
        window = max(1, int(sr * self.window_ms / 1000.0))
        x_sq = x ** 2
        cumsum = np.cumsum(np.insert(x_sq, 0, 0))
        sum_arr = (cumsum[window:] - cumsum[:-window]) / window
        rms_env = np.zeros_like(x)
        rms_env[:len(sum_arr)] = np.sqrt(sum_arr)
        if len(sum_arr) > 0: rms_env[len(sum_arr):] = sum_arr[-1]**0.5
        over = rms_env > self.threshold
        gain = np.ones_like(x)
        valid = over & (rms_env > 1e-6)
        gain[valid] = 1.0 - (1.0 / self.ratio) * (1.0 - self.threshold / rms_env[valid])
        return x * gain

class LookaheadLimiter(AudioProcessor):
    def process(self, x: np.ndarray, sr: int) -> np.ndarray:
        peak = float(np.max(np.abs(x))) if x.size > 0 else 0.0
        if peak > 0.99: return x * (0.99 / peak)
        return x

class AudioPipeline:
    def __init__(self, processors: List[AudioProcessor]): self._processors = processors
    def run(self, x: np.ndarray, sr: int) -> np.ndarray:
        for proc in self._processors: x = proc.process(x, sr)
        return x

master_pipeline = AudioPipeline([DCEqualizer(), HighPassFilter(80), RMSCompressor(), LookaheadLimiter()])

def one_pole_lp(x: np.ndarray, sr: int, cutoff: float) -> np.ndarray:
    if cutoff >= sr / 2.0: return x
    alpha = 1.0 - np.exp(-2.0 * np.pi * cutoff / sr)
    y = np.zeros_like(x)
    y[0] = x[0] * alpha
    for i in range(1, len(x)): y[i] = y[i-1] + alpha * (x[i] - y[i-1])
    return y

def comb_filter(x: np.ndarray, sr: int, freq: float, feedback: float = 0.85) -> np.ndarray:
    delay = max(1, int(sr / freq))
    y = np.zeros_like(x)
    for i in range(len(x)):
        y[i] = x[i] + (y[i-delay] if i >= delay else 0.0) * feedback
    return y

@dataclass(slots=True, frozen=True)
class SynthVoice:
    freq: float = 440.0; gain: float = 0.5; dur: float = 0.1; osc: str = "sine"
    attack: float = 0.001; decay: float = 0.5; noise: float = 0.0
    noise_cutoff: float = 1000.0; pitch_drop: float = 0.0; feedback: float = 0.0

class SoundRenderer:
    def render(self, voices: List[SynthVoice], duration: float, sr: int) -> np.ndarray:
        n = int(sr * duration)
        mix = np.zeros(n, dtype=np.float32)
        for v in voices:
            start = 0; end = min(n, start + int(v.dur * sr))
            if start >= end: continue
            seg_t = np.arange(end - start, dtype=np.float32) / sr
            freq_t = np.maximum(v.freq - seg_t * v.pitch_drop, 20.0)
            phase = 2 * np.pi * np.cumsum(freq_t) / sr
            
            if v.osc == "sine": tone = np.sin(phase)
            elif v.osc == "saw": tone = 2.0 * (phase / (2*np.pi) - np.floor(0.5 + phase / (2*np.pi)))
            elif v.osc == "square": tone = np.sign(np.sin(phase))
            elif v.osc == "triangle": tone = 2.0 * np.abs(2.0 * (phase / (2*np.pi) - np.floor(0.5 + phase / (2*np.pi)))) - 1.0
            elif v.osc == "comb":
                impulse = np.zeros_like(seg_t); impulse[0] = 1.0
                tone = comb_filter(impulse, sr, v.freq, v.feedback)
            else: tone = np.zeros_like(seg_t)
                
            noise_sig = np.zeros_like(seg_t)
            if v.noise > 0:
                raw_noise = np.random.uniform(-1, 1, len(seg_t)).astype(np.float32)
                noise_sig = one_pole_lp(raw_noise, sr, v.noise_cutoff)
                
            wave = (tone * (1.0 - v.noise) + noise_sig * v.noise)
            env = np.exp(-seg_t * v.decay)
            attack_samples = max(1, int(v.attack * sr))
            if attack_samples > 0: env[:attack_samples] *= np.linspace(0, 1, attack_samples)
            mix[start:end] += wave * env * v.gain
        return master_pipeline.run(mix, sr)

class VoiceFactory:
    @staticmethod
    def mechanical() -> List[SynthVoice]:
        return [SynthVoice(freq=120, gain=0.8, dur=0.12, osc="sine", decay=35.0, noise=0.4, noise_cutoff=800),
                SynthVoice(freq=2500, gain=0.3, dur=0.03, osc="square", decay=80.0, noise=0.2, noise_cutoff=5000)]
    @staticmethod
    def vintage_typewriter() -> List[SynthVoice]:
        return [SynthVoice(freq=1800, gain=0.6, dur=0.4, osc="comb", decay=4.0, feedback=0.88),
                SynthVoice(freq=80, gain=0.8, dur=0.08, osc="sine", decay=30.0, noise=0.6, noise_cutoff=400)]
    @staticmethod
    def bubble_pop() -> List[SynthVoice]:
        return [SynthVoice(freq=600, gain=0.7, dur=0.15, osc="sine", decay=15.0, pitch_drop=4000)]
    @staticmethod
    def cyberpunk() -> List[SynthVoice]:
        return [SynthVoice(freq=400, gain=0.6, dur=0.15, osc="saw", decay=20.0, pitch_drop=100),
                SynthVoice(freq=5000, gain=0.3, dur=0.04, osc="square", decay=60.0, noise=0.8, noise_cutoff=6000)]
    @staticmethod
    def asmr_desk() -> List[SynthVoice]:
        return [SynthVoice(freq=80, gain=0.9, dur=0.15, osc="sine", decay=12.0, noise=0.5, noise_cutoff=300)]
    @staticmethod
    def buckling_spring() -> List[SynthVoice]:
        return [SynthVoice(freq=3500, gain=0.5, dur=0.1, osc="comb", decay=10.0, feedback=0.75),
                SynthVoice(freq=120, gain=0.7, dur=0.06, osc="sine", decay=40.0, noise=0.5, noise_cutoff=800)]
    @staticmethod
    def swoosh() -> SynthVoice:
        return SynthVoice(freq=100, gain=0.4, dur=0.08, osc="noise", noise=1.0, noise_cutoff=1200, decay=15.0)

class SimpleSoundGen:
    def __init__(self, sr: int = 44100, preset: str = "Mechanical"):
        self.sr = sr; self.preset = preset
        self.renderer = SoundRenderer()
        self.rng = random.Random()
        self._setup_preset()
        
    def _setup_preset(self):
        if self.preset == "Mechanical":       self.voices = VoiceFactory.mechanical()
        elif self.preset == "Vintage":         self.voices = VoiceFactory.vintage_typewriter()
        elif self.preset == "Bubble":          self.voices = VoiceFactory.bubble_pop()
        elif self.preset == "Cyberpunk":       self.voices = VoiceFactory.cyberpunk()
        elif self.preset == "ASMR Desk":       self.voices = VoiceFactory.asmr_desk()
        elif self.preset == "Buckling Spring": self.voices = VoiceFactory.buckling_spring()
        elif self.preset == "None":           self.voices = []
        else:                                  self.voices = VoiceFactory.mechanical()
            
    def set_preset(self, preset: str):
        self.preset = preset
        self._setup_preset()
        
    def _render_keystroke_float(self, char: str = '') -> np.ndarray:
        if not self.voices: return np.zeros(0, dtype=np.float32)
        if char == ' ':
            voices = [SynthVoice(freq=80, gain=1.0, dur=0.15, osc="sine", decay=25.0, noise=0.4, noise_cutoff=600)]
        elif char == '\n':
            voices = [SynthVoice(freq=400, gain=0.8, dur=0.06, osc="square", decay=60.0, noise=0.6, noise_cutoff=2500), VoiceFactory.swoosh()]
        elif char == '\b':
            voices = [SynthVoice(freq=120, gain=0.8, dur=0.12, osc="sine", decay=35.0, noise=0.4, noise_cutoff=800)]
        else:
            voices = self.voices
            
        dur = max(v.dur for v in voices) + 0.05
        varied_voices = []
        for v in voices:
            v2 = SynthVoice(
                freq=v.freq * (1.0 + self.rng.uniform(-0.03, 0.03)),
                gain=v.gain * (1.0 + self.rng.uniform(-0.15, 0.15)),
                dur=v.dur, osc=v.osc, attack=v.attack, decay=v.decay,
                noise=v.noise, noise_cutoff=v.noise_cutoff,
                pitch_drop=v.pitch_drop, feedback=v.feedback
            )
            varied_voices.append(v2)
            
        raw = self.renderer.render(varied_voices, dur, self.sr)
        if char == '\b': raw = raw[::-1]
        return raw
        
    def generate_keystroke(self, char: str = '') -> np.ndarray:
        raw = self._render_keystroke_float(char)
        if raw.size == 0: return np.zeros(0, dtype=np.int16)
        return (np.clip(raw, -1.0, 1.0) * 32767.0).astype(np.int16)

    def _generate_room_tone(self, duration: float, sr: int) -> np.ndarray:
        n = int(duration * sr)
        white = np.random.uniform(-1, 1, n).astype(np.float32)
        brown = np.zeros(n, dtype=np.float32)
        beta = 0.02
        for i in range(1, n):
            brown[i] = (brown[i-1] + beta * white[i]) / (1.0 + beta)
        max_amp = np.max(np.abs(brown))
        if max_amp > 0: brown = brown / max_amp * 0.03
        return brown

    def generate_full_track(self, panels_data: List[Dict], duration: float, sr: int) -> np.ndarray:
        total_samples = int(duration * sr)
        track = np.zeros(total_samples, dtype=np.float32)
        
        if self.preset != "None":
            track += self._generate_room_tone(duration, sr)
            for p in panels_data:
                text = p.get('text', '')
                sf = p.get('speed_factor', 1.0)
                delay = p.get('delay', 0.0)
                if not text: continue
                for i, char in enumerate(text):
                    t = (i / max(1, len(text))) * ((duration - delay) / sf) + delay
                    if t >= duration: continue
                    start_sample = int(t * sr)
                    pcm_f = self._render_keystroke_float(char)
                    end_sample = min(total_samples, start_sample + len(pcm_f))
                    if start_sample < end_sample:
                        track[start_sample:end_sample] += pcm_f[:end_sample - start_sample]
                        
        track = HighPassFilter(80).process(track, sr)
        peak = np.max(np.abs(track))
        if peak > 0.99: track = track * (0.99 / peak)
        return (track * 32767.0).astype(np.int16)

def pcm_to_wav_bytes(pcm: np.ndarray, sr: int = 44100) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "w") as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(sr); wf.writeframes(pcm.tobytes())
    return buf.getvalue()
