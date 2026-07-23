"""Telegram-бот выдачи ключей NP SUB.

Поток:
    /demo         — TRIAL-ключ (3 мин) выдаётся сразу, один раз на Telegram-аккаунт.
    /buy          — тариф Standard (60 мин/30 дней): бот показывает реквизиты
                    Kaspi, клиент жмёт «Я оплатил» → заявка уходит продавцу
                    (KZSUB_TELEGRAM_ADMIN_IDS) с кнопками Подтвердить/Отклонить.
                    Оплату по Kaspi нельзя проверить автоматически (нет
                    публичного API) — решение остаётся за человеком.

Вызывается вебхуком `POST /telegram/webhook` в main.py (handle_update на один
Update). Только stdlib (urllib) — не тянем python-telegram-bot/aiogram ради
пары HTTP-вызовов; логика лицензий не дублируется, бот напрямую работает с
app.licenses/app.plans (тот же процесс, тот же том БД).
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from . import licenses
from .config import settings
from .licenses import LicenseType

logger = logging.getLogger("kzsub.telegram")

_API_BASE = "https://api.telegram.org/bot{token}/{method}"

DEMO_PLAN = "demo"
STANDARD_PLAN = "standard"
STANDARD_PRICE_KZT = 1490

WELCOME = (
    "<b>NP SUB</b> — субтитры на казахском для Premiere Pro.\n\n"
    "/demo — бесплатный ключ на 3 минуты\n"
    "/buy — тариф Standard (60 мин или 30 дней) — {price} ₸\n"
    "/whoami — узнать свой Telegram ID"
).format(price=STANDARD_PRICE_KZT)


# --- Тонкий HTTP-клиент Telegram Bot API (stdlib urllib, как в runpod_client) -
def _call(method: str, payload: dict) -> dict:
    token = settings.telegram_bot_token
    if not token:
        logger.error("KZSUB_TELEGRAM_BOT_TOKEN не задан — вызов %s пропущен", method)
        return {"ok": False, "error": "no_token"}
    url = _API_BASE.format(token=token, method=method)
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        logger.error("Telegram API %s: HTTP %s %s", method, e.code, body)
        return {"ok": False, "error": body}
    except urllib.error.URLError as e:
        logger.error("Telegram API %s: %s", method, e)
        return {"ok": False, "error": str(e)}


def send_message(chat_id, text: str, reply_markup: dict | None = None) -> dict:
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return _call("sendMessage", payload)


def edit_message_text(chat_id, message_id, text: str, reply_markup: dict | None = None) -> dict:
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    return _call("editMessageText", payload)


def answer_callback_query(callback_query_id: str, text: str | None = None,
                           show_alert: bool = False) -> dict:
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
        payload["show_alert"] = show_alert
    return _call("answerCallbackQuery", payload)


def _kb(buttons: list[tuple[str, str]]) -> dict:
    """Инлайн-клавиатура в одну строку из пар (текст, callback_data)."""
    return {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in buttons]]}


def _admin_ids() -> set[str]:
    return {x.strip() for x in settings.telegram_admin_ids.split(",") if x.strip()}


def _is_admin(user_id) -> bool:
    return str(user_id) in _admin_ids()


# --- Команды -----------------------------------------------------------------
def _handle_demo(chat_id, user_id) -> None:
    email_key = f"tg:{user_id}"
    existing = licenses.find_by_email(email_key, type_=LicenseType.TRIAL)
    if existing is not None:
        send_message(
            chat_id,
            "Демо-ключ уже был выдан этому аккаунту:\n"
            f"<code>{existing.api_key}</code>\n\n"
            "Для продолжения — команда /buy (тариф Standard)."
        )
        return
    lic = licenses.create_from_plan(email_key, DEMO_PLAN)
    send_message(
        chat_id,
        "Ваш демо-ключ (3 минуты):\n"
        f"<code>{lic.api_key}</code>\n\n"
        "Вставьте его при активации плагина NP SUB в Premiere Pro."
    )


def _handle_buy(chat_id, user_id) -> None:
    kaspi = settings.kaspi_phone or "(номер Kaspi не настроен — обратитесь к продавцу)"
    text = (
        f"Тариф <b>Standard</b>: 60 минут или 30 дней (что раньше) — "
        f"{STANDARD_PRICE_KZT} ₸.\n\n"
        f"Оплатите переводом на Kaspi: <b>{kaspi}</b>\n"
        "После оплаты нажмите кнопку ниже — заявка уйдёт на подтверждение."
    )
    kb = _kb([("Я оплатил", f"pay:{chat_id}:{user_id}")])
    send_message(chat_id, text, reply_markup=kb)


def _handle_whoami(chat_id, user_id) -> None:
    send_message(chat_id, f"Ваш Telegram ID: <code>{user_id}</code>")


# --- Кнопки (callback_query) --------------------------------------------------
def _handle_pay_click(cq: dict) -> None:
    cq_id = cq["id"]
    _, chat_id, user_id = cq["data"].split(":")
    from_user = cq.get("from", {})
    username = from_user.get("username") or from_user.get("first_name") or str(user_id)
    message = cq["message"]

    answer_callback_query(cq_id, "Заявка отправлена, ждите подтверждения.")
    edit_message_text(
        message["chat"]["id"], message["message_id"],
        "Заявка отправлена продавцу. Ожидайте подтверждения оплаты.",
    )

    admins = _admin_ids()
    if not admins:
        send_message(chat_id, "Приём заявок пока не настроен — напишите продавцу напрямую.")
        return

    admin_text = (
        f"Заявка на Standard от @{username} (id {user_id}).\n"
        f"Проверьте оплату {STANDARD_PRICE_KZT} ₸ на Kaspi и подтвердите."
    )
    kb = _kb([
        ("✅ Подтвердить", f"confirm:{chat_id}:{user_id}"),
        ("❌ Отклонить", f"reject:{chat_id}:{user_id}"),
    ])
    for admin_id in admins:
        send_message(admin_id, admin_text, reply_markup=kb)


def _handle_admin_decision(cq: dict, approve: bool) -> None:
    cq_id = cq["id"]
    from_user = cq.get("from", {})
    if not _is_admin(from_user.get("id")):
        answer_callback_query(cq_id, "Только для продавца.", show_alert=True)
        return

    _, client_chat_id, client_user_id = cq["data"].split(":")
    message = cq["message"]

    if approve:
        email_key = f"tg:{client_user_id}"
        # Переиспользуем уже выданный ключ, если заявку подтвердили повторно
        # (двойной клик/гонка) — не плодим лицензии на один и тот же аккаунт.
        existing = licenses.find_by_email(email_key, type_=LicenseType.SUBSCRIPTION)
        lic = existing or licenses.create_from_plan(email_key, STANDARD_PLAN)
        send_message(
            client_chat_id,
            "Оплата подтверждена! Ваш ключ Standard:\n"
            f"<code>{lic.api_key}</code>\n\n"
            "Вставьте его при активации плагина NP SUB."
        )
        edit_message_text(message["chat"]["id"], message["message_id"],
                           "✅ Подтверждено, ключ выдан")
        answer_callback_query(cq_id, "Ключ выдан.")
    else:
        send_message(client_chat_id, "Оплата не найдена. Если вы оплатили — напишите продавцу.")
        edit_message_text(message["chat"]["id"], message["message_id"], "❌ Отклонено")
        answer_callback_query(cq_id, "Отклонено.")


# --- Точка входа ---------------------------------------------------------------
def handle_update(update: dict) -> None:
    """Разбирает один Update от Telegram (вызывается вебхуком в main.py)."""
    try:
        if "message" in update:
            msg = update["message"]
            chat_id = msg["chat"]["id"]
            user_id = msg["from"]["id"]
            text = (msg.get("text") or "").strip().lower()
            if text.startswith("/demo"):
                _handle_demo(chat_id, user_id)
            elif text.startswith("/buy"):
                _handle_buy(chat_id, user_id)
            elif text.startswith("/whoami"):
                _handle_whoami(chat_id, user_id)
            else:
                send_message(chat_id, WELCOME)
        elif "callback_query" in update:
            cq = update["callback_query"]
            data = cq.get("data", "")
            if data.startswith("pay:"):
                _handle_pay_click(cq)
            elif data.startswith("confirm:"):
                _handle_admin_decision(cq, approve=True)
            elif data.startswith("reject:"):
                _handle_admin_decision(cq, approve=False)
            else:
                answer_callback_query(cq["id"])
    except Exception:
        logger.exception("Ошибка обработки Telegram update")


# --- CLI: регистрация вебхука (ops, аналогично licenses.py) -------------------
def _main() -> None:
    import argparse

    p = argparse.ArgumentParser(description="Управление Telegram-ботом NP SUB")
    sub = p.add_subparsers(dest="cmd", required=True)

    sw = sub.add_parser("set-webhook", help="зарегистрировать вебхук в Telegram")
    sw.add_argument("url", help="https://<шлюз>/telegram/webhook")

    sub.add_parser("delete-webhook", help="снять вебхук")
    sub.add_parser("webhook-info", help="показать текущую настройку вебхука")

    args = p.parse_args()
    if args.cmd == "set-webhook":
        payload = {"url": args.url}
        if settings.telegram_webhook_secret:
            payload["secret_token"] = settings.telegram_webhook_secret
        else:
            print("ВНИМАНИЕ: KZSUB_TELEGRAM_WEBHOOK_SECRET не задан — "
                  "вебхук будет без проверки подлинности запросов.")
        print(_call("setWebhook", payload))
    elif args.cmd == "delete-webhook":
        print(_call("deleteWebhook", {}))
    elif args.cmd == "webhook-info":
        print(_call("getWebhookInfo", {}))


if __name__ == "__main__":
    _main()
