"""Замер качества распознавания: WER / CER (только stdlib).

Зачем: любая правка «для качества» без замера — гадание. Этот модуль даёт
воспроизводимую метрику до/после, чтобы улучшения были доказуемы, а регресс
ловился (см. docs/tasks/04-asr-quality.md).

WER (Word Error Rate) = (замены + вставки + удаления) / число слов эталона.
CER — то же по символам: для казахского полезен, потому что часть ошибок
модели — это одна буква (і/и, ұ/у, һ/х), и WER штрафует их как целое слово.

Использование:
    python -m app.wer эталон.txt распознанное.srt
    python -m app.wer эталон.txt распознанное.srt --keep-punct
Принимает .srt и .txt в любом сочетании.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Пунктуацию по умолчанию игнорируем: продукт печатает субтитры в караоке-стиле
# без знаков (KZSUB_STRIP_PUNCTUATION), и штрафовать за них нечестно.
_PUNCT_RE = re.compile(r"[^\w\s-]", re.UNICODE)
_SRT_TIME_RE = re.compile(r"^\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}\s*-->")


@dataclass
class ErrorRate:
    """Результат сравнения: метрика и разбор ошибок по типам."""
    errors: int
    total: int
    substitutions: int
    insertions: int
    deletions: int

    @property
    def rate(self) -> float:
        return (self.errors / self.total) if self.total else 0.0

    def __str__(self) -> str:
        return (f"{self.rate * 100:.2f}%  "
                f"(замен {self.substitutions}, вставок {self.insertions}, "
                f"удалений {self.deletions}, всего {self.total})")


def normalize(text: str, keep_punct: bool = False) -> str:
    """Приводит текст к сравнимому виду: регистр, пунктуация, пробелы.

    NFC-нормализация нужна для «й» и «ё»: только они из используемых букв имеют
    каноническое разложение (и + U+0306, е + U+0308), поэтому один и тот же на
    вид текст из разных источников иначе давал бы ложные ошибки. Остальные
    казахские буквы (ә, ғ, қ, ң, ө, ұ, ү, һ, і) — одиночные кодовые точки.
    """
    text = unicodedata.normalize("NFC", text).casefold()
    if not keep_punct:
        text = _PUNCT_RE.sub(" ", text)
    return " ".join(text.split())


def parse_srt(content: str) -> str:
    """Достаёт из .srt только текст реплик (без номеров и тайм-кодов)."""
    lines: list[str] = []
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.isdigit() or _SRT_TIME_RE.match(line):
            continue
        lines.append(line)
    return " ".join(lines)


def load_text(path: str) -> str:
    """Читает .srt или .txt и возвращает плоский текст."""
    with open(path, encoding="utf-8-sig") as f:
        content = f.read()
    return parse_srt(content) if path.lower().endswith(".srt") else content


def _distance(ref: list, hyp: list) -> ErrorRate:
    """Расстояние Левенштейна с разбором по типам ошибок.

    Храним две строки матрицы вместо всей: на транскриптах в тысячи слов полная
    матрица не нужна, а память растёт как O(n*m).
    """
    n, m = len(ref), len(hyp)
    # В каждой ячейке: (стоимость, замены, вставки, удаления).
    prev: list[tuple[int, int, int, int]] = [(j, 0, j, 0) for j in range(m + 1)]
    for i in range(1, n + 1):
        cur = [(i, 0, 0, i)]
        for j in range(1, m + 1):
            if ref[i - 1] == hyp[j - 1]:
                cur.append(prev[j - 1])
                continue
            sub = prev[j - 1]
            ins = cur[j - 1]
            dele = prev[j]
            best = min(sub[0], ins[0], dele[0])
            if best == sub[0]:
                cur.append((sub[0] + 1, sub[1] + 1, sub[2], sub[3]))
            elif best == ins[0]:
                cur.append((ins[0] + 1, ins[1], ins[2] + 1, ins[3]))
            else:
                cur.append((dele[0] + 1, dele[1], dele[2], dele[3] + 1))
        prev = cur
    cost, subs, ins_, dels = prev[m]
    return ErrorRate(errors=cost, total=n, substitutions=subs,
                     insertions=ins_, deletions=dels)


def wer(reference: str, hypothesis: str, keep_punct: bool = False) -> ErrorRate:
    """Word Error Rate между эталоном и распознанным текстом."""
    ref = normalize(reference, keep_punct).split()
    hyp = normalize(hypothesis, keep_punct).split()
    return _distance(ref, hyp)


def cer(reference: str, hypothesis: str, keep_punct: bool = False) -> ErrorRate:
    """Character Error Rate (пробелы не считаем — важны сами буквы)."""
    ref = list(normalize(reference, keep_punct).replace(" ", ""))
    hyp = list(normalize(hypothesis, keep_punct).replace(" ", ""))
    return _distance(ref, hyp)


def _main() -> None:
    import argparse

    p = argparse.ArgumentParser(description="WER/CER распознавания (NP SUB)")
    p.add_argument("reference", help="эталонный текст (.txt или .srt)")
    p.add_argument("hypothesis", help="распознанный текст (.srt или .txt)")
    p.add_argument("--keep-punct", action="store_true",
                   help="учитывать пунктуацию (по умолчанию игнорируется)")
    args = p.parse_args()

    ref = load_text(args.reference)
    hyp = load_text(args.hypothesis)
    print("WER:", wer(ref, hyp, args.keep_punct))
    print("CER:", cer(ref, hyp, args.keep_punct))


if __name__ == "__main__":
    _main()
