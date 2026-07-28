#!/usr/bin/env python3
"""Слить LoRA-адаптер с базовой моделью Whisper в обычную модель.

Зачем: дообученные модели на HuggingFace часто выкладывают не целиком, а как
LoRA-адаптер (`adapter_config.json` + `adapter_model.safetensors`, без
`config.json`). Конвертер CTranslate2 такое не понимает — сначала адаптер надо
приклеить к базовой модели. База берётся из самого адаптера и может сама
оказаться чужим дообучением, а не оригинальным Whisper.

Запуск (из корня репозитория, в venv с transformers/peft):
    python scripts/merge-lora.py abilmansplus/whisper-turbo-kaz-rus-v1 --out ~/kazrus-merged

Дальше — конвертация и прогон:
    ct2-transformers-converter --model ~/kazrus-merged --output_dir ~/kaz-rus-ct2 \
        --quantization float16 --copy_files tokenizer.json preprocessor_config.json
    python scripts/transcribe-local.py запись.wav --out kazrus.srt --model ~/kaz-rus-ct2
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

# Файлы токенизатора: берём из репозитория адаптера, если он их несёт —
# там они соответствуют дообучению.
TOKENIZER_FILES = [
    "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json",
    "vocab.json", "merges.txt", "added_tokens.json", "normalizer.json",
]


def main() -> None:
    p = argparse.ArgumentParser(description="Слияние LoRA-адаптера с базовой моделью")
    p.add_argument("adapter", help="репозиторий или папка адаптера")
    p.add_argument("--out", required=True, help="куда сохранить слитую модель")
    p.add_argument("--base", default=None,
                   help="базовая модель (по умолчанию — из adapter_config.json)")
    p.add_argument("--processor", default="openai/whisper-large-v3-turbo",
                   help="откуда взять preprocessor_config.json, если его нет у базы")
    args = p.parse_args()

    try:
        from huggingface_hub import hf_hub_download
        from transformers import WhisperForConditionalGeneration, WhisperProcessor
        from peft import PeftModel
    except ImportError as e:
        sys.exit(f"Не хватает пакета: {e}\n"
                 'Поставь: pip install "transformers<5" peft')

    out = os.path.expanduser(args.out)

    base = args.base
    if not base:
        cfg_path = (os.path.join(args.adapter, "adapter_config.json")
                    if os.path.isdir(args.adapter)
                    else hf_hub_download(args.adapter, "adapter_config.json"))
        with open(cfg_path, encoding="utf-8") as f:
            base = json.load(f).get("base_model_name_or_path")
        if not base:
            sys.exit("В adapter_config.json нет base_model_name_or_path — "
                     "укажи базовую модель через --base")
    print(f"Базовая модель: {base}")

    print("Гружу базовую модель…")
    model = WhisperForConditionalGeneration.from_pretrained(base)
    print("Применяю адаптер…")
    model = PeftModel.from_pretrained(model, args.adapter).merge_and_unload()
    model.save_pretrained(out)

    # Процессор: preprocessor_config.json критичен — без него faster-whisper
    # возьмёт 80 мел-каналов вместо 128 и упадёт на несовпадении формы входа.
    try:
        WhisperProcessor.from_pretrained(base).save_pretrained(out)
    except Exception:
        print(f"У базы нет процессора — беру из {args.processor}")
        WhisperProcessor.from_pretrained(args.processor).save_pretrained(out)

    # Токенизатор адаптера берём только целиком: смесь файлов от адаптера и от
    # процессора рассыпается на несовпадении словарей. Признак полного набора —
    # наличие `tokenizer.json`.
    def fetch(name: str) -> str | None:
        try:
            return (os.path.join(args.adapter, name) if os.path.isdir(args.adapter)
                    else hf_hub_download(args.adapter, name))
        except Exception:
            return None  # необязательный файл: у адаптера его может не быть

    if fetch("tokenizer.json"):
        for name in TOKENIZER_FILES:
            src = fetch(name)
            if src:
                shutil.copy(src, os.path.join(out, name))

    print(f"Готово: {out}")


if __name__ == "__main__":
    main()
