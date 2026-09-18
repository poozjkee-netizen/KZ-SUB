"""Тесты локального разбора: поиск сервера, поток ответа, выбор модели, нарезка.

Сеть не нужна: поднимаем поддельные Ollama и OpenAI-совместимый сервер на
127.0.0.1 и гоняем через них весь путь, вплоть до готового brief.md.
Запуск: python tools/videobrief/tests/test_local_llm.py
"""
import json
import os
import shutil
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

from videobrief import local_llm, pipeline  # noqa: E402
from videobrief.longtext import needs_condensing, split_lines  # noqa: E402

ANSWER = "## 1. О чём ролик\nПро одну ошибку.\n"


class FakeOllama(BaseHTTPRequestHandler):
    """Минимальный Ollama: список моделей и потоковый /api/chat."""
    prompts = []

    def log_message(self, *a):
        pass

    def _send(self, payload, ctype="application/json"):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/tags":
            self._send({"models": [{"name": "llama3:8b"}, {"name": "gemma3:12b"}]})
        else:
            self.send_error(404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length).decode())
        FakeOllama.prompts.append(body)
        lines = b"".join(
            json.dumps({"message": {"content": part}, "done": False}).encode() + b"\n"
            for part in [ANSWER[:10], ANSWER[10:]]
        ) + json.dumps({"message": {"content": ""}, "done": True}).encode() + b"\n"
        self._send(lines, "application/x-ndjson")


class FakeOpenAI(FakeOllama):
    """Тот же сервер, но в OpenAI-совместимом виде (LM Studio, llama.cpp)."""

    def do_GET(self):
        if self.path == "/v1/models":
            self._send({"data": [{"id": "gemma-3-12b-it"}]})
        else:
            self.send_error(404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        json.loads(self.rfile.read(length).decode())
        chunks = [ANSWER[:5], ANSWER[5:]]
        sse = b"".join(
            b"data: " + json.dumps({"choices": [{"delta": {"content": c}}]}).encode() + b"\n\n"
            for c in chunks
        ) + b"data: [DONE]\n\n"
        self._send(sse, "text/event-stream")


def _serve(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def test_pick_model():
    models = ["llama3:8b", "gemma3:12b", "qwen2.5:7b"]
    assert local_llm.pick_model(models) == "gemma3:12b"          # Gemma в приоритете
    assert local_llm.pick_model(models, "gemma") == "gemma3:12b"  # хватит куска имени
    assert local_llm.pick_model(models, "qwen2.5:7b") == "qwen2.5:7b"
    assert local_llm.pick_model(["mistral:7b"]) == "mistral:7b"   # нет Gemma — первая
    assert local_llm.pick_model([]) == ""


def test_parse_chunk():
    assert local_llm._parse_chunk('{"message":{"content":"привет"}}', "ollama") == "привет"
    assert local_llm._parse_chunk('data: {"choices":[{"delta":{"content":"a"}}]}',
                                  "openai") == "a"
    assert local_llm._parse_chunk("data: [DONE]", "openai") == ""
    assert local_llm._parse_chunk("мусор", "ollama") == ""
    assert local_llm._parse_chunk("", "openai") == ""


def test_detect_and_chat_ollama():
    srv, base = _serve(FakeOllama)
    try:
        server = local_llm.detect(base)
        assert server.kind == "ollama"
        assert "gemma3:12b" in server.models
        seen = []
        text = local_llm.chat(server, "gemma3:12b", "система", "задание",
                              on_token=seen.append)
        assert text == ANSWER.strip()
        assert len(seen) >= 2  # ответ пришёл потоком, а не одним куском
        sent = FakeOllama.prompts[-1]
        assert sent["model"] == "gemma3:12b"
        assert sent["messages"][0]["content"] == "система"
        # Окно контекста задаётся явно, иначе Ollama молча обрежет расшифровку.
        assert sent["options"]["num_ctx"] >= 8192
    finally:
        srv.shutdown()


def test_detect_and_chat_openai():
    srv, base = _serve(FakeOpenAI)
    try:
        server = local_llm.detect(base)
        assert server.kind == "openai"
        assert local_llm.chat(server, "gemma-3-12b-it", "с", "з") == ANSWER.strip()
    finally:
        srv.shutdown()


def test_detect_reports_missing_server():
    try:
        local_llm.detect("http://127.0.0.1:9")
    except local_llm.LocalLLMError as exc:
        assert "Ollama" in str(exc)
    else:
        raise AssertionError("молчащий адрес принят за рабочий сервер")


def test_split_lines_keeps_lines_whole():
    text = "\n".join(f"[00:{i:02d}] реплика номер {i}" for i in range(20))
    parts = split_lines(text, 120)
    assert len(parts) > 1
    assert all(len(p) <= 130 for p in parts)
    # Ни одна реплика не разорвана: склейка обязана дать исходный текст.
    assert "\n".join(parts) == text
    assert needs_condensing(text, 120) and not needs_condensing(text, 100000)


def test_full_run_on_local_model():
    """Весь конвейер с локальной моделью: расшифровка с диска -> brief.md."""
    srv, base = _serve(FakeOllama)
    work = tempfile.mkdtemp(prefix="npbrief-local-")
    try:
        srt = os.path.join(work, "sub.srt")
        with open(srt, "w", encoding="utf-8") as fh:
            fh.write("1\n00:00:00,000 --> 00:00:03,000\nOne mistake everyone makes.\n")
        video = os.path.join(work, "clip.mp4")
        open(video, "wb").close()

        opts = pipeline.Options(source=video, transcript=srt, out_root=work,
                                engine="local", local_url=base, local_model="gemma")
        result = pipeline.run(opts)

        assert result.brief_path and os.path.exists(result.brief_path)
        assert "gemma3:12b (локально, ollama)" == result.engine_note
        with open(result.brief_path, encoding="utf-8") as fh:
            brief = fh.read()
        assert "О чём ролик" in brief
        assert "gemma3:12b" in brief  # в шапке видно, чем разобрано
        assert result.analysis_error is None
    finally:
        srv.shutdown()
        shutil.rmtree(work, ignore_errors=True)


def test_long_transcript_is_condensed_in_parts():
    """Длинный ролик не влезает в окно локальной модели — он сжимается по частям."""
    srv, base = _serve(FakeOllama)
    work = tempfile.mkdtemp(prefix="npbrief-long-")
    FakeOllama.prompts.clear()
    try:
        timed = os.path.join(work, "timed.txt")
        with open(timed, "w", encoding="utf-8") as fh:
            for i in range(200):
                fh.write(f"[{i // 60:02d}:{i % 60:02d}] реплика номер {i} про монтаж\n")
        video = os.path.join(work, "clip.mp4")
        open(video, "wb").close()

        opts = pipeline.Options(source=video, transcript=timed, out_root=work,
                                engine="local", local_url=base, local_model="gemma",
                                local_max_chars=900)
        result = pipeline.run(opts)

        # Несколько сжатий + один финальный разбор.
        assert len(FakeOllama.prompts) >= 3
        assert result.brief_path and os.path.exists(result.brief_path)
        # В расшифровке на диске — полный текст, сжатие только для модели.
        with open(result.timed_path, encoding="utf-8") as fh:
            assert "реплика номер 199" in fh.read()
    finally:
        srv.shutdown()
        shutil.rmtree(work, ignore_errors=True)


def test_engine_local_without_server_is_explicit():
    work = tempfile.mkdtemp(prefix="npbrief-local-")
    try:
        srt = os.path.join(work, "sub.srt")
        with open(srt, "w", encoding="utf-8") as fh:
            fh.write("1\n00:00:00,000 --> 00:00:02,000\nтекст\n")
        video = os.path.join(work, "clip.mp4")
        open(video, "wb").close()
        opts = pipeline.Options(source=video, transcript=srt, out_root=work,
                                engine="local", local_url="http://127.0.0.1:9")
        result = pipeline.run(opts)
        # Расшифровка сохранена, а причина отказа — человеческая.
        assert os.path.exists(result.transcript_path)
        assert result.brief_path is None
        assert "Ollama" in result.analysis_error
    finally:
        shutil.rmtree(work, ignore_errors=True)


def run():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"  ok {name}")
    print("test_local_llm: всё зелёное")


if __name__ == "__main__":
    run()
