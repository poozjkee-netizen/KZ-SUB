"""Тесты окна приложения: токен, настройки, прогон через HTTP.

Сеть не нужна: сервер поднимается на 127.0.0.1 в этом же процессе.
Запуск: python tools/videobrief/tests/test_webapp.py
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

STATE = tempfile.mkdtemp(prefix="npbrief-test-")
os.environ["VIDEOBRIEF_STATE_DIR"] = STATE

from videobrief import settings as cfg, webapp  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402

_server = ThreadingHTTPServer(("127.0.0.1", 0), webapp.Handler)
PORT = _server.server_address[1]
threading.Thread(target=_server.serve_forever, daemon=True).start()


def _url(path, token=webapp.TOKEN):
    join = "&" if "?" in path else "?"
    return f"http://127.0.0.1:{PORT}{path}{join}t={token}"


def _get(path, token=webapp.TOKEN):
    with urllib.request.urlopen(_url(path, token)) as resp:
        return resp.status, resp.read().decode("utf-8")


def _post(path, payload):
    req = urllib.request.Request(_url(path), method="POST",
                                 data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # отказ тоже приходит как JSON
        return json.loads(exc.read().decode("utf-8"))


def test_page_requires_token():
    try:
        _get("/", token="wrong-token")
    except urllib.error.HTTPError as exc:
        assert exc.code == 403
    else:
        raise AssertionError("страница отдалась без токена")


def test_page_served_with_token():
    status, body = _get("/")
    assert status == 200
    assert "NP Brief" in body
    # Токен подставляется в страницу, плейсхолдер не должен остаться.
    assert "__TOKEN__" not in body
    assert webapp.TOKEN in body


def test_settings_roundtrip():
    out = _post("/api/settings", {"audience": "стоматологи",
                                  "model_path": "/m/gemma.gguf", "ctx": "8192"})
    assert out["settings"]["audience"] == "стоматологи"
    assert out["settings"]["model_path"] == "/m/gemma.gguf"
    # Числа из окна приходят строками — на диск должны лечь числами.
    assert out["settings"]["ctx"] == 8192
    assert cfg.load()["audience"] == "стоматологи"
    # Незнакомые ключи молча отбрасываются, а не засоряют файл настроек.
    assert "мусор" not in _post("/api/settings", {"мусор": 1})["settings"]


def test_models_listing():
    out = json.loads(_get("/api/models")[1])
    assert isinstance(out["models"], list)
    assert out["dirs"]  # где искали — показываем человеку


def test_run_requires_url():
    out = _post("/api/run", {"url": "   "})
    assert "Вставь ссылку" in out["error"]


def test_run_reports_failure_as_job_error():
    # Несуществующий файл и не-ссылка: прогон обязан завершиться понятной
    # ошибкой в статусе задания, а не уронить сервер.
    out = _post("/api/run", {"url": "не-ссылка-и-не-файл"})
    job = out["job"]
    for _ in range(100):
        state = json.loads(_get(f"/api/state?job={job}")[1])
        if state["job"]["status"] != "running":
            break
        time.sleep(0.1)
    assert state["job"]["status"] == "error"
    assert state["job"]["error"]
    # Слот освободился — иначе следующий ролик не запустится никогда.
    assert webapp._current is None


def run():
    try:
        for name, fn in sorted(globals().items()):
            if name.startswith("test_"):
                fn()
                print(f"  ok {name}")
        print("test_webapp: всё зелёное")
    finally:
        _server.shutdown()
        shutil.rmtree(STATE, ignore_errors=True)


if __name__ == "__main__":
    run()
