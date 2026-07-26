"""Тесты постобработки текста: зацикливания, словарь, долгие реплики.

Запуск: python tests/test_postprocess.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings  # noqa: E402
from app.postprocess import (  # noqa: E402
    apply_lexicon, collapse_repeats, drop_long_cues, parse_lexicon, postprocess,
)
from app.srt import Segment  # noqa: E402


def _segs(texts, step=0.5):
    """Список реплик с последовательными тайм-кодами."""
    return [Segment(i * step, (i + 1) * step, t) for i, t in enumerate(texts)]


def test_collapse_repeats_trims_model_loop():
    # Зацикливание модели: одно слово 8 раз подряд.
    segs = _segs(["РАХМЕТ"] * 8)
    out = collapse_repeats(segs, max_repeats=3)
    assert len(out) == 3
    # Тайм-коды остаются от первых реплик серии.
    assert out[0].start == segs[0].start


def test_collapse_repeats_keeps_natural_repetition():
    # Нормальный повтор в речи не должен пострадать при пороге 3.
    segs = _segs(["ЖОҚ", "ЖОҚ", "ӘЛЕМ"])
    assert len(collapse_repeats(segs, max_repeats=3)) == 3


def test_collapse_repeats_resets_between_streaks():
    segs = _segs(["А", "А", "А", "А", "Б", "А", "А"])
    out = collapse_repeats(segs, max_repeats=2)
    assert [s.text for s in out] == ["А", "А", "Б", "А", "А"]


def test_collapse_repeats_disabled_by_zero():
    segs = _segs(["А"] * 5)
    assert len(collapse_repeats(segs, max_repeats=0)) == 5


def test_collapse_repeats_ignores_case_and_spaces():
    segs = _segs(["Сәлем", "сәлем ", "СӘЛЕМ"])
    assert len(collapse_repeats(segs, max_repeats=1)) == 1


def test_drop_long_cues():
    segs = [Segment(0.0, 0.4, "СӨЗ"), Segment(1.0, 9.0, "ГАЛЛЮЦИНАЦИЯ")]
    out = drop_long_cues(segs, max_seconds=5.0)
    assert [s.text for s in out] == ["СӨЗ"]
    # 0 = выключено
    assert len(drop_long_cues(segs, max_seconds=0)) == 2


def test_parse_lexicon_formats():
    rules = parse_lexicon("нурсултан=Нұрсұлтан\n# коммент\nмусор=,  а=б ")
    assert ("нурсултан", "Нұрсұлтан") in rules
    assert ("мусор", "") in rules          # пустая правая часть = удалить
    assert ("а", "б") in rules
    assert all(not w.startswith("#") for w, _ in rules)


def test_apply_lexicon_case_rules():
    rules = [("алматы", "Алматы")]
    out = apply_lexicon(_segs(["АЛМАТЫ", "алматы", "Алматы"]), rules)
    # Капс сохраняется (оформление применяется ДО постобработки), а для
    # строчного вхождения побеждает регистр самого правила — в этом его смысл.
    assert [s.text for s in out] == ["АЛМАТЫ", "Алматы", "Алматы"]


def test_apply_lexicon_uppercases_replacement_in_caps_text():
    # Правило написано строчными, текст — капсом: не вставляем строчные буквы.
    out = apply_lexicon(_segs(["КОК АСПАН"]), [("кок", "көк")])
    assert out[0].text == "КӨК АСПАН"


def test_apply_lexicon_fixes_word_and_respects_boundaries():
    rules = [("кок", "көк")]
    out = apply_lexicon(_segs(["кок аспан", "кокос"]), rules)
    assert out[0].text == "көк аспан"
    assert out[1].text == "кокос"          # часть другого слова не трогаем


def test_apply_lexicon_deletes_and_drops_empty_segments():
    rules = [("мусор", "")]
    out = apply_lexicon(_segs(["мусор", "сөз мусор"]), rules)
    assert [s.text for s in out] == ["сөз"]   # пустая реплика отброшена


def test_postprocess_reads_settings_and_lexicon_file():
    old = (settings.max_repeats, settings.max_cue_drop_seconds,
           settings.lexicon, settings.lexicon_path)
    path = os.path.join(tempfile.mkdtemp(), "lex.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("# правки терминов\nастана=Астана\n")
    try:
        settings.max_repeats = 2
        settings.max_cue_drop_seconds = 0
        settings.lexicon = "кок=көк"
        settings.lexicon_path = path
        out = postprocess(_segs(["астана", "кок", "А", "А", "А"]))
        texts = [s.text for s in out]
        assert texts[:2] == ["Астана", "көк"]   # словарь: и env, и файл
        assert texts.count("А") == 2            # порог повторов применён
    finally:
        (settings.max_repeats, settings.max_cue_drop_seconds,
         settings.lexicon, settings.lexicon_path) = old


def test_postprocess_noop_by_default_keeps_segments():
    old = (settings.lexicon, settings.lexicon_path, settings.max_cue_drop_seconds)
    try:
        settings.lexicon, settings.lexicon_path = "", ""
        settings.max_cue_drop_seconds = 0
        segs = _segs(["БІР", "ЕКІ", "ҮШ"])
        assert [s.text for s in postprocess(segs)] == ["БІР", "ЕКІ", "ҮШ"]
    finally:
        (settings.lexicon, settings.lexicon_path,
         settings.max_cue_drop_seconds) = old


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok: {name}")
    print("Все тесты постобработки пройдены.")
