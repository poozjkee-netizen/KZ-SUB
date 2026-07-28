"""Тесты параметров декодирования Whisper (без faster-whisper — только опции).

Модель импортируется лениво, поэтому набор опций проверяется dep-free.
Запуск: python tests/test_transcribe_options.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings  # noqa: E402
from app.transcribe import decode_options  # noqa: E402


def test_anti_hallucination_defaults():
    """Против «выдуманных слов»: опора на предыдущий текст выключена."""
    opts = decode_options()
    assert opts["condition_on_previous_text"] is False
    # Пороги отсечения надуманного текста присутствуют.
    assert "no_speech_threshold" in opts
    assert "log_prob_threshold" in opts
    assert "compression_ratio_threshold" in opts


def test_defaults_favour_completeness_over_filtering():
    """Пропуск реплики дороже лишнего слова — фильтры настроены на полноту.

    Замер 2026-07-28: с выключенными фильтрами пропавшие предложения вернулись,
    значит речь резали наши пороги, а не модель. Оставляем те средства против
    галлюцинаций, которые ничего не удаляют (condition_on_previous_text=false,
    сжимаемость), и отпускаем те, что выбрасывают куски аудио.
    """
    opts = decode_options()
    # Порог -1.0 подобран под английский: на казахском модель менее уверена.
    assert opts["log_prob_threshold"] <= -1.5
    # Самый агрессивный фильтр — перепрыгивает участок целиком.
    assert "hallucination_silence_threshold" not in opts
    # VAD мягче штатного, иначе тихие окончания фраз не считаются речью.
    assert opts["vad_parameters"]["threshold"] < 0.5


def test_word_timestamps_required_for_karaoke():
    # Пословные метки нужны нарезке по словам — без них караоке-режим деградирует.
    assert decode_options()["word_timestamps"] is True


def test_vad_padding_reduced_against_early_text():
    """Паддинг VAD меньше штатных 400 мс — это и есть опережение субтитра."""
    vad = decode_options()["vad_parameters"]
    assert vad["speech_pad_ms"] == settings.vad_speech_pad_ms
    assert vad["speech_pad_ms"] < 400
    assert vad["min_silence_duration_ms"] == settings.vad_min_silence_ms
    assert vad["threshold"] == settings.vad_threshold


def test_hallucination_threshold_toggles_by_zero():
    old = settings.hallucination_silence_threshold
    try:
        settings.hallucination_silence_threshold = 2.0
        assert decode_options()["hallucination_silence_threshold"] == 2.0
        settings.hallucination_silence_threshold = 0
        assert "hallucination_silence_threshold" not in decode_options()
    finally:
        settings.hallucination_silence_threshold = old


def test_initial_prompt_and_hotwords_optional():
    """Затравка и подсказки передаются только когда заданы.

    Пустая строка меняет поведение декодера, поэтому её не отправляем вовсе.
    """
    old = (settings.initial_prompt, settings.hotwords)
    try:
        settings.initial_prompt, settings.hotwords = "", ""
        opts = decode_options()
        assert "initial_prompt" not in opts and "hotwords" not in opts

        # Код-свитчинг: пример смешанной речи склоняет писать русские слова по-русски.
        settings.initial_prompt = "  Бүгін, кстати, вообще қызық болды.  "
        settings.hotwords = "Алматы, Астана"
        opts = decode_options()
        assert opts["initial_prompt"] == "Бүгін, кстати, вообще қызық болды."
        assert opts["hotwords"] == "Алматы, Астана"
    finally:
        settings.initial_prompt, settings.hotwords = old


def test_language_is_fixed_to_kazakh():
    # Авто-детект вредит: Whisper путает казахский с русским/татарским/киргизским.
    assert decode_options()["language"] == settings.language


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok: {name}")
    print("Все тесты опций декодирования пройдены.")
