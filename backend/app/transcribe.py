"""Обёртка над faster-whisper для распознавания казахской речи.

Модель загружается лениво (при первом запросе) и кэшируется в процессе.
На проде процесс должен жить на GPU-инстансе, иначе транскрибация медленная.
"""
from __future__ import annotations

import logging

from .asr_types import RawSegment, Word
from .config import settings

logger = logging.getLogger("kzsub.transcribe")

_model = None  # кэш загруженной модели на процесс


def _get_model():
    global _model
    if _model is None:
        # Импорт внутри функции — чтобы приложение поднималось даже без
        # установленной тяжёлой зависимости (например, в тестах логики).
        from faster_whisper import WhisperModel

        logger.info(
            "Загрузка Whisper: model=%s device=%s compute=%s",
            settings.whisper_model, settings.device, settings.compute_type,
        )
        _model = WhisperModel(
            settings.whisper_model,
            device=settings.device,
            compute_type=settings.compute_type,
        )
    return _model


def decode_options() -> dict:
    """Параметры вызова model.transcribe — отдельно, чтобы их можно было проверить.

    Собраны против двух реальных жалоб (см. docs/tasks/04-asr-quality.md):
      • «выдуманные слова» — condition_on_previous_text выключен (модель иначе
        продолжает свою же галлюцинацию как контекст), плюс пороги отсечения
        no_speech / log_prob / compression_ratio и пропуск длинной тишины;
      • «текст раньше речи» — уменьшенный VAD-паддинг (штатные 400 мс сдвигали
        начало реплики вперёд самой речи).

    Все значения — через config.py, чтобы подбирать их без правки кода. Но учти:
    модуль работает в ВОРКЕРЕ, поэтому в проде изменения требуют пересборки
    GPU-образа, а не только fly deploy.
    """
    opts = {
        "language": settings.language,
        "task": "transcribe",
        "beam_size": 5,
        "word_timestamps": True,          # нужны для нарезки по словам
        "vad_filter": True,               # отсекаем тишину -> точнее тайм-коды
        "vad_parameters": {
            "min_silence_duration_ms": settings.vad_min_silence_ms,
            "speech_pad_ms": settings.vad_speech_pad_ms,
            "threshold": settings.vad_threshold,
        },
        "condition_on_previous_text": settings.condition_on_previous_text,
        "no_speech_threshold": settings.no_speech_threshold,
        "log_prob_threshold": settings.log_prob_threshold,
        "compression_ratio_threshold": settings.compression_ratio_threshold,
    }
    # 0 = не использовать: параметр появился в faster-whisper 1.x и работает
    # только вместе с word_timestamps.
    if settings.hallucination_silence_threshold > 0:
        opts["hallucination_silence_threshold"] = settings.hallucination_silence_threshold

    # Затравка и подсказки передаются только если заданы: пустая строка меняет
    # поведение декодера, поэтому не отправляем её вовсе.
    if settings.initial_prompt.strip():
        opts["initial_prompt"] = settings.initial_prompt.strip()
    if settings.hotwords.strip():
        opts["hotwords"] = settings.hotwords.strip()
    return opts


def transcribe_file(path: str) -> tuple[list[RawSegment], float]:
    """Транскрибирует аудиофайл на казахском.

    Возвращает (список RawSegment с пословными тайм-кодами, длительность аудио).
    Язык жёстко зафиксирован (settings.language = 'kk'): продукт про казахский,
    авто-детект языка тут только вредит (Whisper часто путает kk с ru/tt/ky).

    word_timestamps=True нужен, чтобы аккуратно резать длинные реплики по
    границам слов (см. segmentation.py).
    """
    model = _get_model()

    segments_iter, info = model.transcribe(path, **decode_options())

    raw: list[RawSegment] = []
    for s in segments_iter:
        words: list[Word] = []
        for w in (getattr(s, "words", None) or []):
            # У faster-whisper слово лежит в .word (с ведущим пробелом).
            wt = (getattr(w, "word", "") or "").strip()
            if wt:
                words.append(Word(start=w.start, end=w.end, text=wt))
        raw.append(RawSegment(start=s.start, end=s.end, text=s.text, words=words))

    duration = float(getattr(info, "duration", 0.0) or 0.0)
    logger.info("Готово: %d сегментов, %.1f сек аудио", len(raw), duration)
    return raw, duration
