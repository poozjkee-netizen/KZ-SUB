"""Тесты замера качества распознавания (WER/CER). Только stdlib.

Запуск: python tests/test_wer.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.wer import cer, normalize, parse_srt, wer  # noqa: E402


def test_identical_text_is_zero():
    assert wer("сәлем әлем", "сәлем әлем").rate == 0.0
    assert cer("сәлем", "сәлем").rate == 0.0


def test_substitution_insertion_deletion_counted():
    r = wer("бір екі үш", "бір төрт үш")          # одна замена
    assert (r.substitutions, r.insertions, r.deletions) == (1, 0, 0)
    assert abs(r.rate - 1 / 3) < 1e-9

    r = wer("бір екі", "бір екі үш")               # одна вставка
    assert (r.substitutions, r.insertions, r.deletions) == (0, 1, 0)

    r = wer("бір екі үш", "бір үш")                # одно удаление
    assert (r.substitutions, r.insertions, r.deletions) == (0, 0, 1)


def test_punctuation_and_case_ignored_by_default():
    # Продукт печатает субтитры БЕЗ пунктуации и капсом — штрафовать за это нельзя.
    assert wer("Сәлем, әлем!", "СӘЛЕМ ӘЛЕМ").rate == 0.0
    # С --keep-punct пунктуация уже учитывается.
    assert wer("сәлем, әлем", "сәлем әлем", keep_punct=True).rate > 0.0


def test_nfc_normalization_of_kazakh_letters():
    """«й» как готовый символ и как «и» + краткая — один и тот же текст.

    Из используемых букв каноническое разложение есть только у «й» и «ё»;
    именно на них NFC-нормализация и спасает от ложных ошибок.
    """
    precomposed = "\u049b\u0430\u0439\u0434\u0430"          # қайда, й = U+0439
    decomposed = "\u049b\u0430\u0438\u0306\u0434\u0430"    # и + U+0306 (краткая)
    assert precomposed != decomposed        # байт-в-байт это разные строки
    assert normalize(precomposed) == normalize(decomposed)
    assert wer(precomposed, decomposed).rate == 0.0


def test_cer_is_gentler_than_wer_on_one_letter_error():
    """Ошибка в одну букву: WER штрафует словом, CER — символом."""
    ref, hyp = "қазақша", "казақша"    # қ → к
    assert wer(ref, hyp).rate == 1.0
    assert cer(ref, hyp).rate < 0.2


def test_parse_srt_extracts_only_text():
    srt = (
        "1\n00:00:00,000 --> 00:00:01,000\nСӘЛЕМ\n\n"
        "2\n00:00:01,000 --> 00:00:02,000\nӘЛЕМ\n"
    )
    assert parse_srt(srt) == "СӘЛЕМ ӘЛЕМ"


def test_empty_reference_does_not_crash():
    assert wer("", "что-то").total == 0
    assert wer("", "что-то").rate == 0.0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok: {name}")
    print("Все тесты WER/CER пройдены.")
