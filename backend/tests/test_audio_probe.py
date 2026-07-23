"""Тесты точной оценки длительности WAV (без тяжёлых зависимостей).

Запуск: python tests/test_audio_probe.py
"""
import os
import struct
import sys
import tempfile
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.audio_probe import probe_duration_seconds  # noqa: E402

_tmpdir = tempfile.mkdtemp()


def _make_wav(seconds: float, rate: int = 16000, channels: int = 1) -> str:
    """Пишет тишину (16-bit PCM) заданной длительности — как экспортирует панель."""
    path = os.path.join(_tmpdir, f"test_{seconds}_{rate}_{channels}.wav")
    n_frames = int(seconds * rate)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(rate)
        wf.writeframes(b"\x00\x00" * n_frames * channels)
    return path


def test_exact_duration_16khz_mono():
    path = _make_wav(150.0, rate=16000, channels=1)  # 2 мин 30 сек, как у панели
    dur = probe_duration_seconds(path, fallback_size_bytes=os.path.getsize(path))
    assert abs(dur - 150.0) < 0.01


def test_exact_duration_differs_from_old_size_heuristic():
    # Реальный битрейт 16kHz mono (~32 КБ/с) намного выше, чем предполагала
    # старая эвристика "1 МБ ≈ 60 сек" (~17.5 КБ/с) — она завышала длительность.
    path = _make_wav(150.0, rate=16000, channels=1)
    size = os.path.getsize(path)
    old_heuristic_estimate = max(1.0, size / (1 << 20) * 60)
    dur = probe_duration_seconds(path, fallback_size_bytes=size)
    assert dur < old_heuristic_estimate  # новая оценка точнее и меньше


def test_short_clip_stays_within_demo_quota():
    # Ровно тот сценарий, который сломался: 2:30 не должны выглядеть длиннее 3 мин.
    path = _make_wav(150.0)
    dur_minutes = probe_duration_seconds(path, fallback_size_bytes=os.path.getsize(path)) / 60.0
    assert dur_minutes < 3.0


def test_fallback_to_size_heuristic_for_non_wav():
    path = os.path.join(_tmpdir, "not_a_wav.bin")
    with open(path, "wb") as f:
        f.write(b"\x00" * (2 * 1024 * 1024))  # 2 МБ мусора, не WAV
    dur = probe_duration_seconds(path, fallback_size_bytes=os.path.getsize(path))
    assert abs(dur - 120.0) < 0.01  # 2 МБ * 60 сек/МБ = 120 сек (старая эвристика)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok: {name}")
    print("Все тесты оценки длительности аудио пройдены.")
