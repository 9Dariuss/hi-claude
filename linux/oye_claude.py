#!/usr/bin/env python3
"""Oye Claude: activa Claude Code en la terminal con la voz.

Escucha el micrófono de forma continua, detecta "Hey Claude" / "Oye Claude"
(y variantes), transcribe la orden con faster-whisper (100 % local) y la
escribe en una sesión de tmux donde corre `claude`.

Uso:
    python oye_claude.py              # daemon normal
    python oye_claude.py --test-mic   # muestra niveles del micrófono
    python oye_claude.py --list-devices
    python oye_claude.py --say "explica este repo"   # prueba el envío sin voz
"""

from __future__ import annotations

import argparse
import collections
import os
import queue
import re
import shlex
import shutil
import subprocess
import sys
import time
import tomllib
import unicodedata
from dataclasses import dataclass, field, fields
from pathlib import Path

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_LEN = SAMPLE_RATE * FRAME_MS // 1000

CONFIG_PATH = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "oye-claude" / "config.toml"

# "hey/oye/ey/okay ... claude" con las variantes que suele producir Whisper
# al oír "Claude" con acento español ("clod", "cloud", "claudio", ...).
WAKE_RE = re.compile(
    r"\b(?:hey|hei|hay|ei|ey|eh|oye|oie|olle|hoy|okay|ok|hola)\b[\s,.!¡¿?-]*"
    r"(?:claude|claud|claudio|clod|clode|cloud|clowd|clau|klaud|klod|cloth|close|clot)\b[\s,.!?:-]*",
    re.IGNORECASE,
)

CANCEL_RE = re.compile(r"^(?:cancela|cancelar|para|parar|detente|stop|escape|alto)\W*$", re.IGNORECASE)
CLEAR_RE = re.compile(r"^(?:nueva conversaci[oó]n|limpia(?:r)?(?: la)?(?: conversaci[oó]n)?|clear)\W*$", re.IGNORECASE)


@dataclass
class Config:
    # Micrófono: None = el predeterminado del sistema, o nombre/índice de --list-devices
    input_device: str | int | None = None
    # Modelo rápido para detectar la palabra de activación y modelo para la orden
    wake_model: str = "base"
    command_model: str = "small"
    language: str = "es"
    compute_type: str = "int8"
    # Segundos de audio que se usan para buscar la palabra de activación
    wake_window_s: float = 2.0
    # Silero VAD: mínimo de voz real (s) para molestarse en pasar la frase a Whisper
    min_speech_s: float = 0.3
    # Silencio que cierra una frase (ms)
    end_silence_ms: int = 700
    command_end_silence_ms: int = 1300
    # Tiempo máximo esperando la orden tras decir solo "Oye Claude" (s)
    command_timeout_s: float = 8.0
    max_utterance_s: float = 20.0
    # VAD por energía: dB por encima del ruido de fondo y mínimo absoluto (dBFS)
    vad_margin_db: float = 12.0
    vad_min_dbfs: float = -50.0
    # Sesión de tmux y cómo arrancar Claude
    tmux_session: str = "claude"
    claude_command: str = "claude"
    workdir: str = "~"
    terminal: str = "alacritty --title 'Claude (voz)' -e"
    claude_startup_s: float = 5.0
    # Abrir una ventana de terminal si nadie está mirando la sesión
    open_terminal_if_detached: bool = True
    beep: bool = True
    notify: bool = True

    @classmethod
    def load(cls, path: Path) -> "Config":
        cfg = cls()
        if path.exists():
            data = tomllib.loads(path.read_text())
            known = {f.name for f in fields(cls)}
            for key, value in data.items():
                if key in known:
                    setattr(cfg, key, value)
                else:
                    log(f"aviso: clave desconocida en {path}: {key}")
        return cfg


def log(msg: str) -> None:
    print(time.strftime("[%H:%M:%S]"), msg, flush=True)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text).strip()
    return re.sub(r"\s+", " ", text)


# --------------------------------------------------------------------------- audio

class Listener:
    """Corta el audio del micrófono en frases usando un VAD de energía adaptativo."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.q: queue.Queue[np.ndarray] = queue.Queue()
        # ruido de fondo = percentil bajo de los últimos ~5 s (sobrevive a voz continua)
        self.levels: collections.deque[float] = collections.deque(maxlen=5000 // FRAME_MS)
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

    def flush(self) -> None:
        while not self.q.empty():
            self.q.get_nowait()

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

    def next_utterance(self, end_silence_ms: int, timeout_s: float | None = None) -> np.ndarray | None:
        """Bloquea hasta capturar una frase completa. None si vence timeout_s sin voz."""
        preroll = collections.deque(maxlen=10)  # 300 ms antes del inicio
        voiced: list[np.ndarray] = []
        speech_run = silence_run = 0
        need_silence = end_silence_ms // FRAME_MS
        max_frames = int(self.cfg.max_utterance_s * 1000 / FRAME_MS)
        deadline = time.monotonic() + timeout_s if timeout_s else None

        while True:
            if deadline and not voiced and time.monotonic() > deadline:
                return None
            try:
                frame = self.q.get(timeout=0.5)
            except queue.Empty:
                continue
            if time.monotonic() < self.mute_until:
                continue
            db = self.dbfs(frame)
            speech = self._is_speech(db)

            if not voiced:
                preroll.append(frame)
                if speech:
                    speech_run += 1
                    if speech_run >= 3:  # 90 ms seguidos de voz = empieza la frase
                        voiced = list(preroll)
                        silence_run = 0
                else:
                    speech_run = 0
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
        from faster_whisper.vad import VadOptions, get_speech_timestamps

        self._vad = get_speech_timestamps
        self._vad_options = VadOptions(threshold=0.5, min_speech_duration_ms=250)

        self.cfg = cfg
        threads = max(1, (os.cpu_count() or 4) // 2)
        log(f"cargando modelos whisper: wake={cfg.wake_model} orden={cfg.command_model} ...")
        # La detección corre con cada frase que se oye: pocos hilos gastan menos CPU en total.
        self.wake = WhisperModel(cfg.wake_model, device="cpu", compute_type=cfg.compute_type, cpu_threads=2)
        self.command = WhisperModel(cfg.command_model, device="cpu", compute_type=cfg.compute_type, cpu_threads=threads)
        log("modelos listos")

    def _run(self, model, audio: np.ndarray) -> str:
        # Sin initial_prompt: con ruido Whisper tiende a "repetir" el prompt,
        # y si contuviera "Oye Claude" se activaría solo.
        segments, _ = model.transcribe(
            audio, language=self.cfg.language, beam_size=1 if model is self.wake else 5,
            condition_on_previous_text=False, vad_filter=False,
        )
        # descarta segmentos que Whisper considera ruido o se inventa
        texts = [s.text for s in segments if s.no_speech_prob < 0.6 and s.avg_logprob > -1.0]
        return normalize(" ".join(texts))

    def speech_seconds(self, audio: np.ndarray) -> float:
        """Voz humana real según Silero VAD (~10 ms); filtra teclado, golpes, ventiladores..."""
        stamps = self._vad(audio, self._vad_options)
        return sum(t["end"] - t["start"] for t in stamps) / SAMPLE_RATE

    def wake_text(self, audio: np.ndarray) -> str:
        return self._run(self.wake, audio[: int(self.cfg.wake_window_s * SAMPLE_RATE)])

    def command_text(self, audio: np.ndarray) -> str:
        return self._run(self.command, audio)


# --------------------------------------------------------------------------- tmux / claude

class ClaudeSession:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        if not shutil.which("tmux"):
            sys.exit("Falta tmux. Instálalo con: sudo pacman -S tmux")

    def _tmux(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(["tmux", *args], capture_output=True, text=True, check=check)

    def exists(self) -> bool:
        return self._tmux("has-session", "-t", self.cfg.tmux_session, check=False).returncode == 0

    def attached(self) -> bool:
        out = self._tmux("list-clients", "-t", self.cfg.tmux_session, check=False).stdout
        return bool(out.strip())

    def ensure(self) -> None:
        name = self.cfg.tmux_session
        created = False
        if not self.exists():
            workdir = os.path.expanduser(self.cfg.workdir)
            log(f"creando sesión tmux '{name}' en {workdir}")
            self._tmux("new-session", "-d", "-s", name, "-c", workdir, self.cfg.claude_command)
            created = True
        if self.cfg.open_terminal_if_detached and not self.attached():
            cmd = shlex.split(self.cfg.terminal) + ["tmux", "attach-session", "-t", name]
            log(f"abriendo terminal: {' '.join(cmd)}")
            subprocess.Popen(cmd, start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if created:
            time.sleep(self.cfg.claude_startup_s)

    def send_text(self, text: str) -> None:
        self.ensure()
        target = self.cfg.tmux_session
        self._tmux("send-keys", "-t", target, "-l", "--", text)
        time.sleep(0.2)  # deja que Claude Code procese el texto antes del Enter
        self._tmux("send-keys", "-t", target, "Enter")

    def send_key(self, key: str) -> None:
        if self.exists():
            self._tmux("send-keys", "-t", self.cfg.tmux_session, key)


def notify(cfg: Config, title: str, body: str = "") -> None:
    if cfg.notify and shutil.which("notify-send"):
        subprocess.run(["notify-send", "-a", "Oye Claude", "-i", "audio-input-microphone",
                        "-t", "4000", title, body], check=False)


# --------------------------------------------------------------------------- main

def dispatch(cfg: Config, session: ClaudeSession, command: str) -> None:
    command = command.strip(" ,.;:")
    if not command:
        log("orden vacía, no envío nada")
        return
    if CANCEL_RE.match(command):
        log("→ Escape (cancelar)")
        session.send_key("Escape")
        notify(cfg, "Claude: cancelado")
        return
    if CLEAR_RE.match(command):
        log("→ /clear")
        session.send_text("/clear")
        notify(cfg, "Claude: nueva conversación")
        return
    log(f"→ Claude: {command}")
    notify(cfg, "Claude", command)
    session.send_text(command)


def run(cfg: Config) -> None:
    transcriber = Transcriber(cfg)
    session = ClaudeSession(cfg)

    with Listener(cfg) as mic:
        log("escuchando… di «Oye Claude» o «Hey Claude»")
        while True:
            audio = mic.next_utterance(cfg.end_silence_ms)
            dur = len(audio) / SAMPLE_RATE
            if dur < 0.4 or transcriber.speech_seconds(audio) < cfg.min_speech_s:
                continue
            heard = transcriber.wake_text(audio)
            if not heard:
                continue
            match = WAKE_RE.search(heard)
            if not match:
                log(f"(ignorado) {heard}")
                continue

            log(f"¡activado! «{heard}» ({dur:.1f}s)")
            # Si la frase sigue tras la palabra de activación, la orden ya está ahí.
            has_more = len(heard) > match.end() + 2 or dur > cfg.wake_window_s
            full = transcriber.command_text(audio) if has_more else heard
            m2 = WAKE_RE.search(full)
            command = full[m2.end():] if m2 else ""

            if len(command.strip(" ,.;:!?")) < 2:
                # Solo dijo "Oye Claude": pitido y espera la orden.
                if cfg.beep:
                    beep(880)
                    mic.mute(0.2)
                notify(cfg, "Te escucho…")
                mic.flush()
                audio = mic.next_utterance(cfg.command_end_silence_ms, timeout_s=cfg.command_timeout_s)
                if audio is None:
                    log("sin orden, vuelvo a esperar")
                    if cfg.beep:
                        beep(440)
                    continue
                command = transcriber.command_text(audio)
                m3 = WAKE_RE.match(command)  # por si repite "Oye Claude"
                if m3:
                    command = command[m3.end():]

            if cfg.beep:
                beep(1320, 80)
            try:
                dispatch(cfg, session, command)
            except subprocess.CalledProcessError as exc:
                log(f"error con tmux: {exc.stderr.strip()}")
                notify(cfg, "Oye Claude: error", exc.stderr.strip())
            mic.flush()


def test_mic(cfg: Config) -> None:
    with Listener(cfg) as mic:
        print("Habla y observa los niveles (Ctrl+C para salir)")
        while True:
            frame = mic.q.get()
            db = mic.dbfs(frame)
            speech = mic._is_speech(db)
            bar = "█" * max(0, int((db + 70) / 2))
            print(f"\r{db:6.1f} dBFS ruido {mic.noise_db:6.1f} {'VOZ ' if speech else '    '}{bar:<35}", end="", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, default=CONFIG_PATH)
    ap.add_argument("--list-devices", action="store_true")
    ap.add_argument("--test-mic", action="store_true")
    ap.add_argument("--say", metavar="TEXTO", help="envía TEXTO a Claude sin usar la voz")
    args = ap.parse_args()
    cfg = Config.load(args.config)

    try:
        if args.list_devices:
            print(sd.query_devices())
        elif args.test_mic:
            test_mic(cfg)
        elif args.say:
            dispatch(cfg, ClaudeSession(cfg), args.say)
        else:
            run(cfg)
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
