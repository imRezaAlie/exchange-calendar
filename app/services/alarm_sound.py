"""Play a local bell. Failure to reach the audio device is silent."""

from __future__ import annotations

import io
import os
import math
import shutil
import struct
import subprocess
import threading
import wave
from pathlib import Path

SOUNDS = ("classic", "soft", "digital", "alert")


def render_wav(kind: str) -> bytes:
    recipe = {
        "classic": ([880.0, 1320.0], 0.75, 3.2),
        "soft": ([523.25, 659.25], 0.95, 2.0),
        "digital": ([988.0, 1318.0], 0.32, 9.0),
        "alert": ([740.0, 988.0], 0.28, 1.2),
    }.get(kind, ([880.0, 1320.0], 0.75, 3.2))
    frequencies, duration, decay = recipe
    rate = 22050
    count = int(rate * duration)
    frames = bytearray()
    for index in range(count):
        second = index / rate
        envelope = math.exp(-decay * second)
        if kind == "alert" and int(second * 8) % 2 == 0:
            envelope *= 0.35
        sample = sum(math.sin(2 * math.pi * frequency * second) for frequency in frequencies) / len(frequencies)
        value = int(max(-1.0, min(1.0, sample * envelope)) * 32000)
        frames += struct.pack("<h", value)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(frames)
    return buffer.getvalue()


def sound_path(directory: Path, kind: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    name = kind if kind in SOUNDS else "classic"
    path = directory / f"{name}.wav"
    if not path.exists() or path.stat().st_size < 44:
        path.write_bytes(render_wav(name))
    return path


def find_player() -> str | None:
    return shutil.which("paplay") or shutil.which("pw-play") or shutil.which("aplay")


def play_alarm(
    directory: Path,
    kind: str = "classic",
    volume: int = 70,
    repeats: int = 1,
    *,
    player: str | None = None,
) -> bool:
    """Play the bell off the UI thread. Returns False when audio cannot start."""
    if volume <= 0 or repeats <= 0 or os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        return False
    chosen = find_player() if player is None else player
    if not chosen:
        return False
    try:
        path = sound_path(directory, kind)
    except OSError:
        return False
    level = int(max(0, min(100, volume)) / 100 * 65536)
    command = _command(chosen, path, level)
    threading.Thread(target=_run, args=(command, max(1, min(repeats, 4))), daemon=True).start()
    return True


def _command(player: str, path: Path, level: int) -> list[str]:
    name = Path(player).name
    if name == "paplay":
        return [player, "--volume", str(max(1, level)), str(path)]
    return [player, str(path)]


def _run(command: list[str], repeats: int) -> None:
    for _ in range(repeats):
        try:
            subprocess.run(
                command,
                check=False,
                timeout=4,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.TimeoutExpired):
            return
