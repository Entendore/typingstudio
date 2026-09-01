from __future__ import annotations
from typing import Dict, List, Tuple, Callable, Optional
from dataclasses import dataclass, field
import io, math, random, wave
import numpy as np

try:
    from scipy.signal import lfilter as _scipy_lfilter, fftconvolve as _scipy_fftconvolve
    _HAS_SCIPY = True
except ImportError: _HAS_SCIPY = False

try:
    import numba
    from numba import njit
    _HAS_NUMBA = True
except ImportError: _HAS_NUMBA = False

if _HAS_NUMBA:
    @njit(cache=True)
    def _nb_k_weight(x, sr):
        n = len(x); y = np.empty(n, dtype=np.float64)
        if sr == 48000: s1_b0, s1_b1, s1_b2, s1_a1, s1_a2 = 1.53512485958624, -2.61187896900947, 1.23925952524423, -1.69019851598276, 0.732626261909496; s2_b0, s2_b1, s2_b2, s2_a1, s2_a2 = 1.0, -2.0, 1.0, -1.99004745481143, 0.990072500365666
        elif sr == 44100: s1_b0, s1_b1, s1_b2, s1_a1, s1_a2 = 1.53058976, -2.60968407, 1.24087861, -1.68589681, 0.73233165; s2_b0, s2_b1, s2_b2, s2_a1, s2_a2 = 1.0, -2.0, 1.0, -1.98993544, 0.98996959
        else:
            for i in range(n): y[i] = x[i]
            return y
        z1 = z2 = 0.0
        for i in range(n): xn=x[i]; yn=s1_b0*xn+z1; z1=s1_b1*xn-s1_a1*yn+z2; z2=s1_b2*xn-s1_a2*yn; y[i]=yn
        z1 = z2 = 0.0
        for i in range(n): xn=y[i]; yn=s2_b0*xn+z1; z1=s2_b1*xn-s2_a1*yn+z2; z2=s2_b2*xn-s2_a2*yn; y[i]=yn
        return y

    @njit(cache=True)
    def _nb_apply_gain(x, gain):
        n = len(x); out = np.empty(n, dtype=np.float64)
        for i in range(n): out[i] = x[i] * gain
        return out

    @njit(cache=True)
    def _nb_master_limiter(x, threshold):
        n = len(x); out = np.empty(n, dtype=np.float64); gain = 1.0; rs = 1.0 / 2400.0
        for i in range(n):
            xn = x[i]; ax = xn
            if ax < 0.0: ax = -ax
            if ax * gain > threshold: tg = threshold / max(ax, 1e-10); gain = gain * 0.9 + tg * 0.1
            else: gain = min(1.0, gain + rs)
            out[i] = xn * gain
        return out

    @njit(cache=True)
    def _nb_mix(mix, flat, offsets, lengths, starts):
        n_mix, n_flat = mix.shape[0], flat.shape[0]
        for i in range(len(starts)):
            s, ln, o = starts[i], lengths[i], offsets[i]
            for j in range(ln):
                if s + j < n_mix and o + j < n_flat: mix[s + j] += flat[o + j]

def _k_weight_pure(x, sr):
    if sr == 48000: s1b=[1.53512485958624,-2.61187896900947,1.23925952524423]; s1a=[1.0,-1.69019851598276,0.732626261909496]; s2b=[1.0,-2.0,1.0]; s2a=[1.0,-1.99004745481143,0.990072500365666]
    elif sr == 44100: s1b=[1.53058976,-2.60968407,1.24087861]; s1a=[1.0,-1.68589681,0.73233165]; s2b=[1.0,-2.0,1.0]; s2a=[1.0,-1.98993544,0.98996959]
    else: return x.copy()
    if _HAS_SCIPY:
        from scipy.signal import lfilter
        y = lfilter(s1b, s1a, x); y = lfilter(s2b, s2a, y); return y
    y = np.zeros_like(x); z1 = z2 = 0.0; b0, b1, b2 = s1b; a1, a2 = s1a[1], s1a[2]
    for i in range(len(x)): xn=x[i]; yn=b0*xn+z1; z1=b1*xn-a1*yn+z2; z2=b2*xn-a2*yn; y[i]=yn
    z1 = z2 = 0.0; b0, b1, b2 = s2b; a1, a2 = s2a[1], s2a[2]
    for i in range(len(y)): xn=y[i]; yn=b0*xn+z1; z1=b1*xn-a1*yn+z2; z2=b2*xn-a2*yn; y[i]=yn
    return y

def _compute_lufs(x, sr):
    if len(x) < sr//2: return -70.0
    xf = x.astype(np.float64)
    if _HAS_NUMBA: xk=_nb_k_weight(xf,sr)
    else: xk = _k_weight_pure(xf, sr)
    ms = np.mean(xk**2)
    if ms < 1e-20: return -70.0
    return -0.691 + 10.0 * np.log10(ms)

def _normalize_to_lufs(x, sr, target_lufs=-14.0, tp_db=-1.0):
    if len(x) < sr//2: return x
    xf = x.astype(np.float64)
    cl = _compute_lufs(xf, sr)
    if not np.isfinite(cl) or cl <= -70.0: return x
    gdb = target_lufs - cl; gl = 10.0 ** (gdb / 20.0)
    if _HAS_NUMBA: xn = _nb_apply_gain(xf, gl)
    else: xn = xf * gl
    tp = 10.0 ** (tp_db / 20.0)
    if _HAS_NUMBA: xn = _nb_master_limiter(xn, tp)
    else:
        p = np.max(np.abs(xn))
        if p > tp: xn = xn * (tp / p)
    return xn

class DSP:
    @staticmethod
    def env_exp(n: int, sr: int, attack: float = 0.001, decay_rate: float = 30.0, attack_curve: float = 2.0) -> np.ndarray:
        t = np.arange(n, dtype=np.float64) / sr; env = np.exp(-t * decay_rate); a_samp = max(1, int(attack * sr))
        if a_samp < n:
            a_env = np.linspace(0, 1, a_samp, dtype=np.float64) ** attack_curve
            env[:a_samp] = a_env * np.exp(-np.arange(a_samp, dtype=np.float64) / sr * decay_rate)
        return env

    @staticmethod
    def fir_lowpass(cutoff: float, sr: int = 44100, n_taps: int = 127, window: str = "blackman") -> np.ndarray:
        if n_taps % 2 == 0: n_taps += 1
        cutoff = min(max(1.0, cutoff), sr / 2.0 - 1.0)
        if cutoff <= 0: return np.zeros(n_taps)
        fc = cutoff / sr; n = np.arange(n_taps, dtype=np.float64); center = (n_taps - 1) / 2.0; h = np.sinc(2 * fc * (n - center))
        match window:
            case "blackman": w = 0.42 - 0.5*np.cos(2*np.pi*n/(n_taps-1)) + 0.08*np.cos(4*np.pi*n/(n_taps-1))
            case "hamming": w = 0.54 - 0.46*np.cos(2*np.pi*n/(n_taps-1))
            case "hann": w = 0.5 - 0.5*np.cos(2*np.pi*n/(n_taps-1))
            case _: w = np.ones(n_taps)
        h *= w; s = np.sum(h)
        if s > 0: h /= s
        return h

    @staticmethod
    def fir_highpass(cutoff: float, sr: int = 44100, n_taps: int = 127, window: str = "blackman") -> np.ndarray:
        hlp = DSP.fir_lowpass(cutoff, sr, n_taps, window); h = -hlp; h[len(h)//2] += 1.0; return h

    @staticmethod
    def fir_bandpass(low: float, high: float, sr: int = 44100, n_taps: int = 255, window: str = "blackman") -> np.ndarray:
        return DSP.fir_lowpass(high, sr, n_taps, window) - DSP.fir_lowpass(low, sr, n_taps, window)

    @staticmethod
    def convolve(x: np.ndarray, h: np.ndarray) -> np.ndarray:
        n, nh = len(x), len(h)
        if nh <= 1: return x * h[0] if nh == 1 else x
        if _HAS_SCIPY and nh > 64: return _scipy_fftconvolve(x, h, mode='full')[:n].astype(np.float32)
        if nh < 64 and n < 2048: return np.convolve(x, h, mode='full')[:n].astype(np.float32)
        MAX_FFT_BITS = 20; total = n + nh - 1
        if total.bit_length() <= MAX_FFT_BITS:
            n_fft = 1 << total.bit_length()
            return np.fft.irfft(np.fft.rfft(x, n_fft) * np.fft.rfft(h, n_fft), n_fft)[:n].astype(np.float32)
        n_fft = 1 << MAX_FFT_BITS; block = n_fft - nh + 1; H = np.fft.rfft(h, n_fft); out = np.zeros(total, dtype=np.float32)
        for i in range(0, n, block):
            end = min(i + block, n); yb = np.fft.irfft(np.fft.rfft(x[i:end], n_fft) * H, n_fft)
            out[i:i + min(len(yb), total - i)] += yb[:min(len(yb), total - i)]
        return out[:n].astype(np.float32)

    @staticmethod
    def filt_lp(x, c, sr=44100, n_taps=127): return DSP.convolve(x, DSP.fir_lowpass(c, sr, n_taps))
    @staticmethod
    def filt_hp(x, c, sr=44100, n_taps=127): return DSP.convolve(x, DSP.fir_highpass(c, sr, n_taps))
    @staticmethod
    def filt_bp(x, l, h, sr=44100, n_taps=255): return DSP.convolve(x, DSP.fir_bandpass(l, h, sr, n_taps))

    @staticmethod
    def dc_block(x, sr=44100): return DSP.filt_hp(x, 20.0, sr, n_taps=63)

    @staticmethod
    def osc_sine(f, n, sr, phase=0.0): return np.sin(2 * np.pi * f * (np.arange(n, dtype=np.float64) / sr) + phase).astype(np.float32)

    @staticmethod
    def osc_sweep(f1, f2, n, sr):
        if n <= 0: return np.zeros(0, dtype=np.float32)
        if f1 <= 0 or f2 <= 0: return np.zeros(n, dtype=np.float32)
        t = np.arange(n, dtype=np.float64) / sr; freq = f1 * (f2 / f1) ** (t / (n / sr)); return np.sin(2 * np.pi * np.cumsum(freq) / sr).astype(np.float32)

    @staticmethod
    def osc_808(f, n, sr, pitch_drop=0.5):
        t = np.arange(n, dtype=np.float64) / sr
        freq = np.zeros(n, dtype=np.float64)
        drop_len = int(sr * 0.05)
        if drop_len > 0:
            freq[:drop_len] = np.linspace(f, f * (1.0 - pitch_drop), drop_len)
            freq[drop_len:] = f * (1.0 - pitch_drop)
        else: freq[:] = f
        phase = 2 * np.pi * np.cumsum(freq) / sr
        return np.sin(phase).astype(np.float32)

    @staticmethod
    def osc_fm(c, mr, mi, n, sr, phase=0.0):
        t = np.arange(n, dtype=np.float64) / sr; return np.sin(2 * np.pi * c * t + mi * np.sin(2 * np.pi * c * mr * t) + phase).astype(np.float32)

    @staticmethod
    def osc_fm_multi(c, mrs, mis, n, sr):
        t = np.arange(n, dtype=np.float64) / sr; ph = 2 * np.pi * c * t
        for mr, mi in zip(mrs, mis): ph += mi * np.sin(2 * np.pi * c * mr * t)
        return np.sin(ph).astype(np.float32)

    @staticmethod
    def osc_saw(f, n, sr):
        t = np.arange(n, dtype=np.float64) / sr; sig = np.zeros(n, dtype=np.float64)
        for h in range(1, 17):
            fh = f * h
            if fh >= sr * 0.45: break
            sig += np.sin(2 * np.pi * fh * t) / h
        return (sig * 0.5).astype(np.float32)

    @staticmethod
    def noise_white(n, rng): return rng.randn(n).astype(np.float32)
    @staticmethod
    def noise_pink(n, rng, sr=44100):
        bs = min(n, sr * 5); white = rng.randn(bs).astype(np.float32); fft = np.fft.rfft(white); freqs = np.fft.rfftfreq(bs, 1.0 / sr)
        if len(freqs) > 1: freqs[0] = max(freqs[1], 1.0); fft[1:] /= np.sqrt(np.abs(freqs[1:])); fft[0] = 0
        pink = np.fft.irfft(fft, n=bs).astype(np.float32); p = np.max(np.abs(pink))
        if p > 1e-6: pink /= p
        reps, rem = n // bs, n % bs; out = np.tile(pink, reps) if reps > 0 else np.array([], dtype=np.float32)
        if rem > 0: out = np.concatenate([out, pink[:rem]])
        return out

    @staticmethod
    def normalize(x, target_db=-1.0):
        p = np.max(np.abs(x)) if len(x) > 0 else 0.0
        if p < 1e-10: return x
        return x * (10 ** (target_db / 20) / p)

    @staticmethod
    def to_int16(x, target_db=-1.0):
        x = DSP.normalize(x, target_db); x = np.clip(x, -1.0, 1.0); np.nan_to_num(x, copy=False, nan=0.0, posinf=1.0, neginf=-1.0); return (x * 32767).astype(np.int16)

    @staticmethod
    def lookahead_limiter(x, sr=44100, threshold_db=-1.0, release_ms=50):
        target_lin = 10 ** (threshold_db / 20); peak = np.max(np.abs(x))
        if peak <= target_lin: return x.astype(np.float32)
        env = np.abs(x).astype(np.float32); gain = np.ones_like(x, dtype=np.float32); mask = env > target_lin; gain[mask] = target_lin / env[mask]
        lookahead = int(sr * 0.002)
        if lookahead > 0 and len(gain) > lookahead: gain = np.roll(gain, -lookahead); gain[-lookahead:] = gain[-lookahead - 1]
        return (x * gain).astype(np.float32)

    @staticmethod
    def compressor_rms(x, sr, threshold_db=-12.0, ratio=3.0, attack_ms=10, release_ms=100):
        if threshold_db >= 0 or ratio <= 1: return x.astype(np.float32)
        target_lin = 10 ** (threshold_db / 20); env = np.abs(x).astype(np.float32); ac = np.exp(-1.0 / (sr * (attack_ms / 1000.0))); rc = np.exp(-1.0 / (sr * (release_ms / 1000.0)))
        if _HAS_SCIPY:
            env_a = _scipy_lfilter([1 - ac], [1, -ac], env); env_r = _scipy_lfilter([1 - rc], [1, -rc], env); smooth_env = np.maximum(env_a, env_r).astype(np.float32)
        else: smooth_env = env
        gain = np.ones_like(x, dtype=np.float32); mask = smooth_env > target_lin
        gain[mask] = 1.0 - (1.0 - 1.0 / ratio) * (1.0 - target_lin / smooth_env[mask])
        return (x * gain).astype(np.float32)

    @staticmethod
    def sat_tube(x, drive=1.0):
        if drive <= 0: return x
        return (np.tanh(x * drive) / max(0.001, np.tanh(drive))).astype(np.float32)

    @staticmethod
    def master_mono(x, sr=44100, target_db=-0.1):
        if len(x) == 0: return x
        x = DSP.dc_block(x, sr); x = DSP.filt_hp(x, 25.0, sr, n_taps=127)
        x = DSP.compressor_rms(x, sr, threshold_db=-22.0, ratio=1.8, attack_ms=30, release_ms=220)
        x = DSP.compressor_rms(x, sr, threshold_db=-12.0, ratio=2.5, attack_ms=8, release_ms=100)
        return np.clip(DSP.lookahead_limiter(x, sr, threshold_db=target_db), -1.0, 1.0).astype(np.float32)

@dataclass(slots=True)
class Voice:
    osc: str = "sine"; freq: float = 440.0; freq_end: float = 0.0; fm_ratio: float = 1.0; fm_index: float = 0.0; fm_ratios: Optional[List[float]] = None; fm_indices: Optional[List[float]] = None
    attack: float = 0.001; decay_rate: float = 30.0; attack_curve: float = 2.0; filt: str = "none"; f_cutoff: float = 8000.0; f_high: float = 12000.0; f_q: float = 1.0; drive: float = 0.0; gain: float = 0.5; delay: float = 0.0
    pitch_drop: float = 0.5  # Bugfix: Added missing field

class SoundRenderer:
    __slots__ = ("sr",)
    def __init__(self, sr: int = 44100): self.sr = sr
    def render(self, voices: List[Voice], duration: float, rng: np.random.RandomState) -> np.ndarray:
        n = int(self.sr * duration)
        if n <= 0: return np.zeros(0, dtype=np.float32)
        mix = np.zeros(n, dtype=np.float32)
        for v in voices:
            sig = self._render_voice(v, n, rng); d_samp = int(v.delay * self.sr)
            if d_samp > 0:
                if d_samp >= n: continue
                sig = np.concatenate([np.zeros(d_samp, dtype=np.float32), sig[:n - d_samp]])
            if len(sig) < n: sig = np.concatenate([sig, np.zeros(n - len(sig), dtype=np.float32)])
            else: sig = sig[:n]
            mix += sig
        return DSP.dc_block(mix, self.sr)

    def _render_voice(self, v: Voice, n: int, rng: np.random.RandomState) -> np.ndarray:
        match v.osc:
            case "sine": sig = DSP.osc_sine(v.freq, n, self.sr)
            case "sweep": sig = DSP.osc_sweep(v.freq, v.freq_end, n, self.sr)
            case "808": sig = DSP.osc_808(v.freq, n, self.sr, pitch_drop=v.pitch_drop) # Bugfix: use v.pitch_drop
            case "fm": sig = DSP.osc_fm_multi(v.freq, v.fm_ratios, v.fm_indices, n, self.sr) if v.fm_ratios else DSP.osc_fm(v.freq, v.fm_ratio, v.fm_index, n, self.sr)
            case "noise_white": sig = DSP.noise_white(n, rng)
            case "noise_pink": sig = DSP.noise_pink(n, rng, self.sr)
            case "saw": sig = DSP.osc_saw(v.freq, n, self.sr)
            case _: sig = np.zeros(n, dtype=np.float32)
        sig *= DSP.env_exp(n, self.sr, attack=v.attack, decay_rate=v.decay_rate, attack_curve=v.attack_curve)
        match v.filt:
            case "lp": sig = DSP.filt_lp(sig, v.f_cutoff, self.sr)
            case "hp": sig = DSP.filt_hp(sig, v.f_cutoff, self.sr)
            case "bp": sig = DSP.filt_bp(sig, v.f_cutoff, v.f_high, self.sr)
        if v.drive > 0: sig = DSP.sat_tube(sig, v.drive)
        return sig * v.gain

class VoiceFactory:
    @staticmethod
    def transient_tick(freq, gain=0.5, delay=0.0, rng=None):
        if rng: freq = freq * (2 ** rng.uniform(-0.05, 0.05))
        return Voice(osc="noise_white", attack=0.00001, decay_rate=1000.0, attack_curve=3.0, filt="hp", f_cutoff=4000, drive=1.5, gain=gain, delay=delay)
    @staticmethod
    def click_noise(freq, gain=0.5, delay=0.0, rng=None):
        if rng: freq = freq * (2 ** rng.uniform(-0.05, 0.05))
        return Voice(osc="noise_white", attack=0.0001, decay_rate=300.0, attack_curve=3.0, filt="bp", f_cutoff=freq*0.7, f_high=freq*1.8, drive=1.8, gain=gain*0.8, delay=delay)
    @staticmethod
    def thock(freq, gain=0.45, delay=0.002, rng=None):
        if rng: freq = freq * (2 ** rng.uniform(-0.01, 0.01))
        return Voice(osc="sweep", freq=freq*1.1, freq_end=freq*0.9, attack=0.001, decay_rate=50.0, attack_curve=2.5, filt="lp", f_cutoff=max(400.0, freq * 3.5), gain=gain, delay=delay)
    @staticmethod
    def sub(freq, gain=0.30, delay=0.003, rng=None):
        if rng: freq = freq * (2 ** rng.uniform(-0.005, 0.005))
        return Voice(osc="sine", freq=freq, attack=0.002, decay_rate=30.0, attack_curve=2.0, filt="lp", f_cutoff=250, gain=gain, delay=delay)
    @staticmethod
    def sub_808(freq, gain=0.60, delay=0.0, pitch_drop=0.5, rng=None):
        if rng: freq = freq * (2 ** rng.uniform(-0.005, 0.005))
        return Voice(osc="808", freq=freq, attack=0.005, decay_rate=20.0, attack_curve=0.5, filt="lp", f_cutoff=200, gain=gain, delay=delay, pitch_drop=pitch_drop)
    @staticmethod
    def fm(freq, fm_idx=0.4, gain=0.35, cutoff=3500, delay=0.0, rng=None):
        if rng: freq = freq * (2 ** rng.uniform(-0.02, 0.02))
        return Voice(osc="fm", freq=freq, fm_ratio=2.0, fm_index=fm_idx, attack=0.0003, decay_rate=80.0, attack_curve=2.0, filt="lp", f_cutoff=cutoff, drive=1.2, gain=gain, delay=delay)
    @staticmethod
    def housing(freq, gain=0.30, delay=0.0, rng=None):
        if rng: freq = freq * (2 ** rng.uniform(-0.01, 0.01))
        return Voice(osc="sine", freq=freq, attack=0.001, decay_rate=60.0, attack_curve=2.0, filt="lp", f_cutoff=3000, gain=gain, delay=delay)
_VF = VoiceFactory

SOUND_PRESETS: Dict[str, Dict[str, str]] = {
    "Mechanical": {"desc": "Cherry MX Blue: sharp click jacket, tactile bump, deep housing resonance."},
    "Cherry MX Red": {"desc": "Linear thock: deep sub-bass, keycap housing resonance, minimal high-frequency transient."},
    "Cherry Brown": {"desc": "Tactile bump: dual-filtered mid-range FM with smooth exponential decay envelope."},
    "IBM Model M": {"desc": "Buckling spring: metallic FM ping with long decay, membrane snap, and housing resonance."},
    "ASMR Deep Thock": {"desc": "Ultra-deep sub-bass thock with soft pink noise, optimized for brain tingles."},
    "Heavenly ASMR": {"desc": "Angellic, wide-stereo glass chimes paired with soft sub-bass. Processed with tape saturation."},
    "Lo-Fi Chill": {"desc": "Warm, heavily tape-saturated, bitcrushed, and wow/flutter keys for relaxing coding."},
    "Neuro Bass": {"desc": "Aggressive Reese bass and dense sub-harmonic impacts for dark, intense coding."},
    "Retro 80s E.Piano": {"desc": "True DX7 6-operator FM synthesis matrix for a classic 1980s electric piano."},
    "Water Drop ASMR": {"desc": "Additive synthesis of a water droplet with pitch drop and lush spring reverb tail."},
    "Cyberpunk UI": {"desc": "Analog foldback distortion and metallic ring modulation for harsh digital sci-fi transients."},
    "Vocal Whisper": {"desc": "Formant-filtered pink noise sounding like a soft human whisper. Highly ASMR-inducing."},
    "Goblin Cave": {"desc": "Dripping wet cave ambience with VOSIM alien chatter and Karplus-Strong drops."}
}
CLICK_DURATIONS: Dict[str, float] = {k: 0.12 for k in SOUND_PRESETS.keys()}
CLICK_DURATIONS["ASMR Deep Thock"] = 0.18; CLICK_DURATIONS["Heavenly ASMR"] = 0.22; CLICK_DURATIONS["Neuro Bass"] = 0.22
CLICK_DURATIONS["Vocal Whisper"] = 0.15; CLICK_DURATIONS["Water Drop ASMR"] = 0.30; CLICK_DURATIONS["Retro 80s E.Piano"] = 0.35; CLICK_DURATIONS["Goblin Cave"] = 0.25

def _mk_click(sr, dur, seed, voices):
    rng = np.random.RandomState(seed); R = SoundRenderer(sr)
    return DSP.to_int16(R.render(voices, dur, rng))

_PRESET_FACTORIES: Dict[str, Dict[str, Callable]] = {
    "Mechanical": {"click": lambda sr,d,s: _mk_click(sr,d,s,[_VF.transient_tick(4000, 0.45, rng=np.random.RandomState(s)), _VF.click_noise(4000, 0.45, rng=np.random.RandomState(s)), _VF.thock(180, 0.55, 0.002, rng=np.random.RandomState(s)), _VF.sub(80, 0.35, 0.003, rng=np.random.RandomState(s))])},
    "Cherry MX Red": {"click": lambda sr,d,s: _mk_click(sr,d,s,[_VF.thock(150, 0.55, 0.001, rng=np.random.RandomState(s)), _VF.sub(70, 0.45, 0.002, rng=np.random.RandomState(s))])},
    "Cherry Brown": {"click": lambda sr,d,s: _mk_click(sr,d,s,[_VF.fm(200, 0.3, 0.3, 3000, 0.0, rng=np.random.RandomState(s)), _VF.thock(120, 0.45, 0.002, rng=np.random.RandomState(s))])},
    "IBM Model M": {"click": lambda sr,d,s: _mk_click(sr,d,s,[_VF.fm(800, 1.2, 0.5, 8000, 0.0, rng=np.random.RandomState(s)), _VF.housing(300, 0.4, 0.001, rng=np.random.RandomState(s))])},
    "ASMR Deep Thock": {"click": lambda sr,d,s: _mk_click(sr,d,s,[_VF.thock(120, 0.75, 0.001, rng=np.random.RandomState(s)), _VF.sub(55, 0.55, 0.002, rng=np.random.RandomState(s))])},
    "Heavenly ASMR": {"click": lambda sr,d,s: _mk_click(sr,d,s,[_VF.fm(800, 2.0, 0.5, 3500, 0.002, rng=np.random.RandomState(s)), _VF.sub(100, 0.45, 0.001, rng=np.random.RandomState(s))])},
    "Lo-Fi Chill": {"click": lambda sr,d,s: _mk_click(sr,d,s,[_VF.thock(150, 0.55, 0.004, rng=np.random.RandomState(s))])},
    "Neuro Bass": {"click": lambda sr,d,s: _mk_click(sr,d,s,[_VF.sub_808(80, 0.60, 0.0, 0.8, rng=np.random.RandomState(s))])},
    "Retro 80s E.Piano": {"click": lambda sr,d,s: _mk_click(sr,d,s,[_VF.fm(220, 1.5, 0.5, 6000, 0.001, rng=np.random.RandomState(s))])},
    "Water Drop ASMR": {"click": lambda sr,d,s: _mk_click(sr,d,s,[_VF.fm(800, 0.5, 0.5, 5000, 0.0, rng=np.random.RandomState(s))])},
    "Cyberpunk UI": {"click": lambda sr,d,s: _mk_click(sr,d,s,[_VF.transient_tick(3000, 0.30, rng=np.random.RandomState(s)), _VF.sub(80, 0.40, 0.003, rng=np.random.RandomState(s))])},
    "Vocal Whisper": {"click": lambda sr,d,s: _mk_click(sr,d,s,[_VF.fm(200, 0.2, 0.4, 2000, 0.0, rng=np.random.RandomState(s))])},
    "Goblin Cave": {"click": lambda sr,d,s: _mk_click(sr,d,s,[_VF.fm(80, 2.0, 0.4, 3000, 0.0, rng=np.random.RandomState(s))])}
}

class SimpleSoundGen:
    _SHIFT_MAP = {'~': '`', '!': '1', '@': '2', '#': '3', '$': '4', '%': '5', '^': '6', '&': '7', '*': '8', '(': '9', ')': '0', '_': '-', '+': '=', '{': '[', '}': ']', '|': '\\', ':': ';', '"': "'", '<': ',', '>': '.', '?': '/'}
    def __init__(self, sr: int = 44100, preset: str = "Mechanical", stereo: bool = False, reverb_amt: float = 0.1, target_lufs: float = -14.0):
        self.sr, self.preset, self.stereo, self.reverb_amt, self.target_lufs = sr, preset, stereo, reverb_amt, target_lufs
        factories = _PRESET_FACTORIES.get(preset, _PRESET_FACTORIES["Mechanical"]); click_dur = CLICK_DURATIONS.get(preset, 0.06)
        self.key_sounds = {}; seed_base = 0
        for ch in "`1234567890-=[]\\": snd = factories["click"](sr, click_dur, seed_base); self.key_sounds[ch.lower()] = snd; seed_base += 1
        for ch in "qwertyuiop": snd = factories["click"](sr, click_dur, seed_base); self.key_sounds[ch.lower()] = snd; seed_base += 1
        for ch in "asdfghjkl;'": snd = factories["click"](sr, click_dur, seed_base); self.key_sounds[ch.lower()] = snd; seed_base += 1
        for ch in "zxcvbnm,./": snd = factories["click"](sr, click_dur, seed_base); self.key_sounds[ch.lower()] = snd; seed_base += 1
        self.mod_sounds = {}; mod_seed = 500
        for mod_name in ["tab", "caps", "shift", "ctrl", "alt", "win", "fn", "menu", "esc"]: snd = factories["click"](sr, 0.1, mod_seed); self.mod_sounds[mod_name] = snd; mod_seed += 1
        self.fallback_clicks = [factories["click"](sr, click_dur, 900 + i) for i in range(8)]
        self.spaces = [factories["click"](sr, 0.1, 600 + i) for i in range(3)]
        self.enters = [factories["click"](sr, 0.1, 700 + i) for i in range(2)]
        self.releases = [factories["click"](sr, 0.06, 400 + i) for i in range(8)]

    def _pick(self, char: str, rng: random.Random) -> Tuple[np.ndarray, float]:
        if char == "__release__": return rng.choice(self.releases), rng.uniform(0.3, 0.5)
        if char == "\n": return rng.choice(self.enters), rng.uniform(1.10, 1.25)
        if char == " ": return self.spaces[rng.randint(0, 2)], rng.uniform(1.05, 1.15)
        if char == "\t": return self.mod_sounds["tab"], rng.uniform(0.95, 1.05)
        cl = char.lower()
        if cl in self._SHIFT_MAP: cl = self._SHIFT_MAP[cl]
        if cl in self.key_sounds: return self.key_sounds[cl], rng.uniform(0.92, 1.08)
        return rng.choice(self.fallback_clicks), rng.uniform(0.92, 1.08)

    def generate_pcm(self, timestamps: List[Tuple[float, str]], volume: float = 0.5) -> np.ndarray:
        if not timestamps: return np.zeros(0, dtype=np.int16)
        sr = self.sr; rng = random.Random(98765); all_ts: List[Tuple[float, str]] = []
        for ts, ch in timestamps:
            all_ts.append((ts, ch))
            if ch.isalnum() or ch in ".,;[]'": all_ts.append((ts + 0.045 + rng.uniform(0, 0.015), "__release__"))
        n = int(sr * (max(ts for ts, _ in all_ts) + 0.3)); raw_sounds: List[Tuple[np.ndarray, float, int]] = []
        for ts, ch in all_ts:
            snd, vm = self._pick(ch, rng); s = int(ts * sr)
            if s >= n: continue
            snd_float = snd.astype(np.float32) / 32767.0
            if len(snd_float) == 0: continue
            snd_mono = snd_float * ((rng.gauss(1.0, 0.05) * vm) ** 0.8) * volume; pan = 0.0
            raw_sounds.append((snd_mono, pan, s))
        if not raw_sounds: return np.zeros(n, dtype=np.int16)
        mono_sounds = [s[0] for s in raw_sounds]; starts = np.array([s[2] for s in raw_sounds], dtype=np.int64); lengths = np.array([len(s) for s in mono_sounds], dtype=np.int64); flat = np.concatenate(mono_sounds) if mono_sounds else np.array([], dtype=np.float32); offsets = np.zeros(len(mono_sounds), dtype=np.int64)
        for i in range(1, len(mono_sounds)): offsets[i] = offsets[i - 1] + lengths[i - 1]
        mix = np.zeros(n, dtype=np.float32)
        if len(flat) > 0:
            if _HAS_NUMBA: _nb_mix(mix, flat, offsets, lengths, starts)
            else:
                for i in range(len(starts)): s_idx, ln, o = int(starts[i]), int(lengths[i]), int(offsets[i]); mix[s_idx:s_idx + ln] += flat[o:o + ln]
        mix = DSP.master_mono(mix, sr)
        mix = _normalize_to_lufs(mix, sr, self.target_lufs)
        return np.clip(mix * 32767.0, -32768, 32767).astype(np.int16)

    def generate_track(self, timestamps: List[Tuple[float, str]], filepath: str, volume: float = 0.5) -> None:
        if not timestamps: return
        pcm = self.generate_pcm(timestamps, volume)
        if len(pcm) == 0: return
        with wave.open(filepath, "w") as wf: wf.setnchannels(2 if self.stereo else 1); wf.setsampwidth(2); wf.setframerate(self.sr); wf.writeframes(pcm.astype('<i2').tobytes())

def _pcm_to_wav_bytes(pcm: np.ndarray, sr: int = 44100, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "w") as wf: wf.setnchannels(channels); wf.setsampwidth(2); wf.setframerate(sr); wf.writeframes(pcm.tobytes())
    return buf.getvalue()
