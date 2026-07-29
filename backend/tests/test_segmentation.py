"""Тесты нарезки субтитров (чистая логика, без Whisper)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.asr_types import RawSegment, Word  # noqa: E402
from app.segmentation import (  # noqa: E402
    _wrap, build_captions, resegment, resegment_words, strip_punctuation_for,
)


def _words(pairs, step=0.4, start=0.0):
    """Список (текст) -> Word'ы с последовательными тайм-кодами без пауз."""
    out = []
    t = start
    for text in pairs:
        out.append(Word(t, t + step, text))
        t += step
    return out


def test_wrap_two_lines():
    # Текст в пределах ёмкости реплики (max_line_chars * max_lines).
    text = "бір екі үш төрт"
    wrapped = _wrap(text, max_line_chars=10, max_lines=2)
    lines = wrapped.split("\n")
    assert len(lines) == 2
    assert len(lines[0]) <= 10                       # первая строка в лимите
    assert " ".join(lines).split() == text.split()   # ни одно слово не потеряно


def test_wrap_single_long_word_kept():
    wrapped = _wrap("супердлинноеслово", max_line_chars=5, max_lines=2)
    assert wrapped == "супердлинноеслово"  # не режем внутри слова


def test_split_by_char_limit():
    # Много коротких слов подряд без пауз -> должно разбиться на несколько реплик.
    words = _words(["аа", "бб", "вв", "гг", "дд", "ее", "жж", "зз"])
    raw = [RawSegment(words[0].start, words[-1].end, "x", words)]
    cues = resegment(raw, max_line_chars=6, max_lines=1, max_cue_seconds=99, max_gap_seconds=99)
    assert len(cues) > 1
    for c in cues:
        assert len(c.text) <= 6


def test_split_by_gap():
    a = _words(["сәлем", "әлем"], start=0.0)          # 0.0..0.8
    b = _words(["қалай", "жағдай"], start=5.0)          # большой разрыв
    raw = [RawSegment(0.0, 8.0, "x", a + b)]
    cues = resegment(raw, max_line_chars=99, max_lines=2, max_cue_seconds=99, max_gap_seconds=0.8)
    assert len(cues) == 2
    assert cues[0].text == "сәлем әлем"
    assert cues[1].text == "қалай жағдай"


def test_split_by_duration():
    words = _words(["бір", "екі", "үш", "төрт"], step=3.0)  # каждая пара уже >5с
    raw = [RawSegment(words[0].start, words[-1].end, "x", words)]
    cues = resegment(raw, max_line_chars=99, max_lines=2, max_cue_seconds=5.0, max_gap_seconds=99)
    assert len(cues) > 1


def test_fallback_without_words():
    raw = [RawSegment(0.0, 2.0, "мәтін сөзсіз тайм-кодтар", words=[])]
    cues = resegment(raw, max_line_chars=99, max_lines=2, max_cue_seconds=99, max_gap_seconds=99)
    assert len(cues) == 1
    assert cues[0].start == 0.0 and cues[0].end == 2.0
    assert "мәтін" in cues[0].text


def test_words_one_per_cue():
    words = _words(["алма", "жеді", "бала"])
    raw = [RawSegment(words[0].start, words[-1].end, "x", words)]
    cues = resegment_words(raw, glue_max_chars=2)
    assert [c.text for c in cues] == ["алма", "жеді", "бала"]


def test_words_preposition_glues_to_next():
    words = _words(["ол", "в", "доме", "жатыр"])
    raw = [RawSegment(words[0].start, words[-1].end, "x", words)]
    cues = resegment_words(raw, glue_max_chars=2)
    # "в" — предлог, прилипает к "доме"; "ол"(2 симв.) тоже служебное -> к "в доме"
    assert [c.text for c in cues] == ["ол в доме", "жатыр"]


def test_words_short_by_length_glues():
    words = _words(["де", "келді"])  # "де" — 2 символа, служебное
    raw = [RawSegment(words[0].start, words[-1].end, "x", words)]
    cues = resegment_words(raw, glue_max_chars=2)
    assert [c.text for c in cues] == ["де келді"]


def test_words_trailing_short_attaches_to_prev():
    words = _words(["үйде", "жоқ", "ма"])  # "ма" в конце -> к предыдущей реплике
    raw = [RawSegment(words[0].start, words[-1].end, "x", words)]
    cues = resegment_words(raw, glue_max_chars=2)
    assert [c.text for c in cues] == ["үйде", "жоқ ма"]


def test_words_timestamps_span_group():
    words = _words(["на", "столе"], step=0.5, start=1.0)  # 1.0-1.5, 1.5-2.0
    raw = [RawSegment(1.0, 2.0, "x", words)]
    cues = resegment_words(raw, glue_max_chars=2)
    assert len(cues) == 1
    assert cues[0].start == 1.0 and cues[0].end == 2.0


def test_build_captions_picks_mode_and_falls_back_to_phrases():
    """Режим приходит из запроса, поэтому выбор должен быть в одном месте.

    Неизвестное значение не должно ронять прогон: лучше отдать читаемые
    фразы, чем ошибку из-за опечатки в параметре.
    """
    words = _words(["бүгін", "кеше", "ертең", "таңертең", "кешке"])
    raw = [RawSegment(words[0].start, words[-1].end, "x", words)]
    common = dict(glue_max_chars=2, max_line_chars=42, max_lines=2,
                  max_cue_seconds=7.0, max_gap_seconds=0.8)

    word = build_captions(raw, "word", **common)
    phrase = build_captions(raw, "phrase", **common)
    assert [s.text for s in word] == [s.text for s in resegment_words(raw, glue_max_chars=2)]
    assert [s.text for s in phrase] == [
        s.text for s in resegment(raw, max_line_chars=42, max_lines=2,
                                  max_cue_seconds=7.0, max_gap_seconds=0.8)
    ]
    assert len(word) > len(phrase)          # караоке дробит сильнее фраз
    assert [s.text for s in build_captions(raw, "чепуха", **common)] == \
           [s.text for s in phrase]


def test_punctuation_kept_in_phrases_and_stripped_in_karaoke():
    """Во фразах пунктуация — это читаемость, в караоке — мусор.

    Одно слово с запятой на экране выглядит ошибкой, а фраза без запятых
    заставляет перечитывать. Whisper расставляет знаки сам, поэтому во
    фразовом режиме их достаточно просто не трогать.
    """
    assert strip_punctuation_for("word", True, True) is True
    assert strip_punctuation_for("phrase", True, True) is False

    # Настройку можно выключить — тогда фразы чистятся как раньше.
    assert strip_punctuation_for("phrase", True, False) is True
    # А если пунктуацию вообще не снимают, режим ничего не меняет.
    assert strip_punctuation_for("word", False, True) is False


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok: {name}")
    print("Все тесты нарезки пройдены.")
