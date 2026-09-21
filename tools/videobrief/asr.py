"""Распознавание речи, когда у ролика нет готовых субтитров.

Язык не задаём: прилетает виральный контент на любом языке, и авто-детект
Whisper тут единственно верный. Считает на процессоре — ctranslate2 (движок
faster-whisper) видеокарту мака не использует, поэтому вариантов «cpu/gpu» в
настройках нет: они были бы обманом.
"""
from __future__ import annotations

from .transcript import Segment

_model = None
_model_name: str | None = None


def _get_model(name: str):
    global _model, _model_name
    if _model is None or _model_name != name:
        # Импорт внутри функции: без faster-whisper программа обязана работать
        # на готовых субтитрах и на своей расшифровке.
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:  # pragma: no cover — зависит от окружения
            raise RuntimeError(
                "Не установлен faster-whisper — это он распознаёт речь.\n"
                "Поставь его: pip install faster-whisper"
            ) from exc
        _model = WhisperModel(name, device="cpu", compute_type="int8")
        _model_name = name
    return _model


def transcribe(path: str, model_name: str = "large-v3",
               language: str | None = None) -> tuple[list[Segment], str]:
    """Аудиофайл -> (сегменты, определённый язык).

    VAD включён: он отсекает музыкальные проигрыши, на которых Whisper любит
    выдумывать реплики.
    """
    model = _get_model(model_name)
    segments_iter, info = model.transcribe(
        path,
        language=language or None,
        task="transcribe",
        beam_size=5,
        vad_filter=True,
        condition_on_previous_text=False,
    )
    segments = [
        Segment(start=float(s.start), end=float(s.end), text=(s.text or "").strip())
        for s in segments_iter
        if (s.text or "").strip()
    ]
    return segments, (getattr(info, "language", "") or "")
