"""Entrada de voz: micrófono → frase (VAD) → texto con faster-whisper (100 % local).

El micrófono solo se abre mientras escuchas (botón o atajo); no hay nada en segundo plano.
"""

from __future__ import annotations

import collections
import os
import queue
import re
import sys
import threading
import time
import unicodedata
from pathlib import Path
from typing import Callable

import numpy as np
import sounddevice as sd

from .config import Config

SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_LEN = SAMPLE_RATE * FRAME_MS // 1000

# Por costumbre se dirá «Oye Claude, …» aunque ya no haga falta: se quita del principio.
WAKE_PREFIX_RE = re.compile(
    r"^\W*(?:hey|hei|ei|ey|eh|oye|oie|ok|okay|hola)?[\s,.!¡]*"
    r"(?:claude|claud|claudio|clod|clode|cloud|clowd|clau|klaud|klod)\b[\s,.!?:-]*",
    re.IGNORECASE,
)


def log(msg: str) -> None:
    print(time.strftime("[%H:%M:%S]"), msg, file=sys.stderr, flush=True)


def clean_command(text: str) -> str:
    text = unicodedata.normalize("NFC", text).strip()
    text = re.sub(r"\s+", " ", text)
    return WAKE_PREFIX_RE.sub("", text, count=1).strip()


# --------------------------------------------------------------------------- GPU

def ensure_cuda_libs() -> None:
    """Las librerías CUDA instaladas con pip (nvidia-cublas, nvidia-cudnn) se cargan con
    dlopen, que solo mira LD_LIBRARY_PATH al arrancar: se añaden y el proceso se relanza."""
    try:
        import nvidia
    except ImportError:
        return
    libs = [str(d) for base in nvidia.__path__ for d in sorted(Path(base).glob("*/lib"))]
    current = os.environ.get("LD_LIBRARY_PATH", "")
    missing = [d for d in libs if d not in current.split(":")]
    if missing:
        os.environ["LD_LIBRARY_PATH"] = ":".join(missing + ([current] if current else []))
        os.execv(sys.executable, [sys.executable, *sys.argv])


def cuda_available() -> bool:
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


# --------------------------------------------------------------------------- audio

class Listener:
    """Corta el audio del micrófono en una frase usando un VAD de energía adaptativo."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.q: queue.Queue[np.ndarray] = queue.Queue()
        # ruido de fondo = percentil bajo de los últimos ~5 s (sobrevive a voz continua)
        self.levels: collections.deque[float] = collections.deque(maxlen=5000 // FRAME_MS)
        self.level_db = -90.0
        self.stop_requested = threading.Event()
        self.mute_until = 0.0
        device = cfg.input_device
        if isinstance(device, str) and device.isdigit():
            device = int(device)
        self.stream = sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="float32",
            blocksize=FRAME_LEN, device=device, callback=self._callback,
        )

    def _callback(self, indata, frames, time_info, status):  # hilo de audio
        self.q.put(indata[:, 0].copy())

    def __enter__(self):
        self.stream.start()
        return self

    def __exit__(self, *exc):
        self.stream.stop()
        self.stream.close()

    def mute(self, seconds: float) -> None:
        self.mute_until = time.monotonic() + seconds

    @staticmethod
    def dbfs(frame: np.ndarray) -> float:
        rms = float(np.sqrt(np.mean(frame * frame)) + 1e-10)
        return 20 * np.log10(rms)

    @property
    def noise_db(self) -> float:
        return float(np.percentile(self.levels, 15)) if len(self.levels) > 10 else -60.0

    def _is_speech(self, db: float) -> bool:
        self.levels.append(db)
        return db > max(self.noise_db + self.cfg.vad_margin_db, self.cfg.vad_min_dbfs)

    def record_utterance(self) -> np.ndarray | None:
        """Graba hasta que dejas de hablar (o se pide parar). None si no dijiste nada."""
        preroll = collections.deque(maxlen=10)  # 300 ms antes del inicio
        voiced: list[np.ndarray] = []
        speech_run = silence_run = 0
        need_silence = self.cfg.end_silence_ms // FRAME_MS
        max_frames = int(self.cfg.max_utterance_s * 1000 / FRAME_MS)
        deadline = time.monotonic() + self.cfg.start_timeout_s

        while True:
            if self.stop_requested.is_set():
                return np.concatenate(voiced) if voiced else None
            if not voiced and time.monotonic() > deadline:
                return None
            try:
                frame = self.q.get(timeout=0.1)
            except queue.Empty:
                continue
            if time.monotonic() < self.mute_until:
                continue
            db = self.level_db = self.dbfs(frame)
            speech = self._is_speech(db)

            if not voiced:
                preroll.append(frame)
                speech_run = speech_run + 1 if speech else 0
                if speech_run >= 3:  # 90 ms seguidos de voz = empieza la frase
                    voiced = list(preroll)
                continue

            voiced.append(frame)
            silence_run = 0 if speech else silence_run + 1
            if silence_run >= need_silence or len(voiced) >= max_frames:
                return np.concatenate(voiced)


def beep(freq: float, ms: int = 120) -> None:
    t = np.linspace(0, ms / 1000, int(SAMPLE_RATE * ms / 1000), endpoint=False)
    tone = 0.25 * np.sin(2 * np.pi * freq * t) * np.hanning(len(t))
    try:
        sd.play(tone.astype(np.float32), SAMPLE_RATE)
    except Exception as exc:  # sin salida de audio no es grave
        log(f"no se pudo reproducir el pitido: {exc}")


# --------------------------------------------------------------------------- whisper

class Transcriber:
    def __init__(self, cfg: Config):
        from faster_whisper import WhisperModel

        self.cfg = cfg
        threads = max(1, (os.cpu_count() or 4) // 2)

        def load(device: str) -> None:
            ctype = cfg.compute_type
            if ctype == "auto":
                ctype = "int8_float16" if device == "cuda" else "int8"
            log(f"cargando whisper {cfg.model} en {device} ({ctype})")
            self.model = WhisperModel(cfg.model, device=device, compute_type=ctype, cpu_threads=threads)
            self.device = device

        if cfg.device in ("auto", "cuda") and cuda_available():
            try:
                load("cuda")
                return
            except Exception as exc:  # p. ej. driver actualizado sin reiniciar
                log(f"no se pudo usar la GPU, sigo en CPU: {exc}")
        load("cpu")

    def transcribe(self, audio: np.ndarray) -> str:
        # Sin initial_prompt: con ruido Whisper tiende a "repetir" el prompt.
        segments, _ = self.model.transcribe(
            audio, language=self.cfg.language, beam_size=5,
            condition_on_previous_text=False, vad_filter=True,
        )
        # descarta segmentos que Whisper considera ruido o se inventa
        texts = [s.text for s in segments if s.no_speech_prob < 0.6 and s.avg_logprob > -1.0]
        return clean_command(" ".join(texts))


# Un solo modelo en memoria aunque haya varias ventanas escuchando
_transcriber: Transcriber | None = None
_transcriber_lock = threading.Lock()


def get_transcriber(cfg: Config) -> Transcriber:
    global _transcriber
    with _transcriber_lock:
        if _transcriber is None:
            _transcriber = Transcriber(cfg)
        return _transcriber


# --------------------------------------------------------------------------- controlador

class VoiceInput:
    """Una toma de voz cada vez: abre el micro, graba una frase y la transcribe en un hilo.

    Los callbacks se llaman desde ese hilo; la interfaz debe pasarlos a su bucle principal.
    on_state recibe "listening", "transcribing" o "idle".
    """

    def __init__(self, cfg: Config, on_state: Callable[[str], None],
                 on_text: Callable[[str], None], on_error: Callable[[str], None]):
        self.cfg = cfg
        self.on_state, self.on_text, self.on_error = on_state, on_text, on_error
        self.beep = True
        self._listener: Listener | None = None
        self.active = False

    @property
    def level_db(self) -> float:
        return self._listener.level_db if self._listener else -90.0

    def preload(self) -> None:
        threading.Thread(target=get_transcriber, args=(self.cfg,), daemon=True).start()

    def start(self) -> None:
        if self.active:
            return
        self.active = True
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self) -> None:
        """Deja de escuchar y transcribe lo grabado hasta ahora."""
        if self._listener:
            self._listener.stop_requested.set()

    def _run(self) -> None:
        try:
            # El modelo carga en paralelo mientras ya se está grabando.
            self.preload()
            with Listener(self.cfg) as mic:
                self._listener = mic
                if self.beep:
                    beep(880)
                    mic.mute(0.15)
                self.on_state("listening")
                audio = mic.record_utterance()
            self._listener = None
            if audio is None or len(audio) < SAMPLE_RATE * 0.3:
                return
            self.on_state("transcribing")
            text = get_transcriber(self.cfg).transcribe(audio)
            if text:
                self.on_text(text)
            else:
                self.on_error("No he entendido nada")
        except Exception as exc:
            log(f"error de voz: {exc!r}")
            self.on_error(f"Error con el micrófono o Whisper: {exc}")
        finally:
            self._listener = None
            self.active = False
            self.on_state("idle")
