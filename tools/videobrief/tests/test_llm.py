"""Тесты локальной модели: поиск файлов .gguf, выбор, поток ответа.

Сама llama-cpp-python тут не нужна: её место занимает подделка в sys.modules —
проверяем свою обвязку, а не чужую библиотеку.
Запуск: python tools/videobrief/tests/test_llm.py
"""
import os
import shutil
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

from videobrief import llm  # noqa: E402

ANSWER = ["## 1. О чём ролик\n", "Про одну ошибку."]


class FakeLlama:
    """Подделка llama_cpp.Llama: запоминает, с чем её позвали."""
    created = []
    calls = []

    def __init__(self, **kwargs):
        FakeLlama.created.append(kwargs)

    def create_chat_completion(self, **kwargs):
        FakeLlama.calls.append(kwargs)
        for piece in ANSWER:
            yield {"choices": [{"delta": {"content": piece}}]}
        yield {"choices": [{"delta": {}}]}


def _install_fake():
    module = types.ModuleType("llama_cpp")
    module.Llama = FakeLlama
    sys.modules["llama_cpp"] = module
    llm._loaded.clear()
    FakeLlama.created.clear()
    FakeLlama.calls.clear()


def _gguf(path, megabytes):
    with open(path, "wb") as fh:
        fh.write(b"\0" * (megabytes * 1024 * 1024))
    return path


def test_is_instruct():
    assert llm.is_instruct("gemma-3-12b-it-UD-Q4_K_XL.gguf")
    assert llm.is_instruct("Mistral-7B-Instruct.gguf")
    assert not llm.is_instruct("llama-3-8b-base.gguf")


def test_find_models_sorts_instruct_and_size():
    work = tempfile.mkdtemp(prefix="npbrief-gguf-")
    try:
        _gguf(os.path.join(work, "base-big.gguf"), 300)
        _gguf(os.path.join(work, "gemma-3-12b-it.gguf"), 200)
        _gguf(os.path.join(work, "gemma-4-E4B-it.gguf"), 150)
        # Словарь, а не модель: такие файлы брать нельзя.
        _gguf(os.path.join(work, "ggml-vocab-gemma.gguf"), 1)

        models = llm.find_models((work,))
        names = [os.path.basename(m) for m in models]
        assert names == ["gemma-3-12b-it.gguf", "gemma-4-E4B-it.gguf", "base-big.gguf"]
        assert not any("vocab" in n for n in names)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_find_models_skips_missing_dirs():
    assert llm.find_models(("/такой/папки/нет",)) == []


def test_pick():
    models = ["/m/gemma-3-12b-it.gguf", "/m/qwen-7b-it.gguf"]
    assert llm.pick(models) == "/m/gemma-3-12b-it.gguf"       # первая = лучшая
    assert llm.pick(models, "qwen") == "/m/qwen-7b-it.gguf"    # хватит куска имени
    assert llm.pick([], "gemma") == ""


def test_pick_accepts_existing_path():
    work = tempfile.mkdtemp(prefix="npbrief-gguf-")
    try:
        path = _gguf(os.path.join(work, "своя.gguf"), 1)
        assert llm.pick([], path) == path
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_generate_streams_and_caches_model():
    _install_fake()
    seen = []
    text = llm.generate("/m/gemma.gguf", "система", "задание", ctx=8192,
                        on_token=seen.append)
    assert text == "".join(ANSWER).strip()
    assert len(seen) == 2                      # ответ пришёл потоком
    assert FakeLlama.created[0]["n_ctx"] == 8192
    assert FakeLlama.created[0]["n_gpu_layers"] == -1   # считаем на видеокарте
    assert FakeLlama.calls[0]["messages"][0]["content"] == "система"

    # Вторая просьба не грузит модель заново — иначе каждый ролик ждал бы минуту.
    llm.generate("/m/gemma.gguf", "система", "ещё задание", ctx=8192)
    assert len(FakeLlama.created) == 1


def test_missing_library_says_what_to_install():
    llm._loaded.clear()
    saved = sys.modules.pop("llama_cpp", None)
    sys.modules["llama_cpp"] = None  # имитируем отсутствие пакета
    try:
        llm.generate("/m/gemma.gguf", "с", "з")
    except llm.LLMError as exc:
        assert "pip install llama-cpp-python" in str(exc)
    else:
        raise AssertionError("отсутствие библиотеки прошло незамеченным")
    finally:
        sys.modules.pop("llama_cpp", None)
        if saved is not None:
            sys.modules["llama_cpp"] = saved


def test_worker_threads_leaves_room_for_the_system():
    """Модель не должна занимать все ядра — иначе мак встаёт колом."""
    assert llm.worker_threads(16) == 14
    assert llm.worker_threads(4) == 2
    assert llm.worker_threads(2) == 2   # на слабой машине меньше двух не даём
    assert llm.worker_threads(1) == 2


def test_generate_limits_threads_and_batch():
    _install_fake()
    llm.generate("/m/gemma.gguf", "с", "з", ctx=4096)
    created = FakeLlama.created[0]
    assert created["n_threads"] == llm.worker_threads()
    assert created["n_batch"] == 256


def run():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"  ok {name}")
    print("test_llm: всё зелёное")


if __name__ == "__main__":
    run()
