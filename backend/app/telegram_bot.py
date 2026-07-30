"""Telegram-бот выдачи ключей NP SUB.

Поток:
    (любое первое сообщение) — выбор языка (казахский/русский), прежде чем
                    бот скажет что-либо ещё. Дальше все ответы этому
                    пользователю идут на выбранном языке; сменить — /lang.
    /demo         — TRIAL-ключ (3 мин) выдаётся сразу, один раз на Telegram-аккаунт.
                    К сообщению приложена кнопка перехода к покупке Standard —
                    демо должно вести к следующему шагу, а не заканчиваться тупиком.
    /buy          — тариф Standard (60 мин/30 дней): бот показывает реквизиты
                    Kaspi, клиент жмёт «Я оплатил» → заявка уходит продавцу
                    (KZSUB_TELEGRAM_ADMIN_IDS) с кнопками Подтвердить/Отклонить.
                    Оплату по Kaspi нельзя проверить автоматически (нет
                    публичного API) — решение остаётся за человеком.

Вызывается вебхуком `POST /telegram/webhook` в main.py (handle_update на один
Update). Только stdlib (urllib) — не тянем python-telegram-bot/aiogram ради
пары HTTP-вызовов; логика лицензий не дублируется, бот напрямую работает с
app.licenses/app.plans (тот же процесс, тот же том БД).

Сообщения продавцу (заявки на подтверждение оплаты) всегда на русском — это
интерфейс владельца бизнеса, а не клиента, локализовать его незачем.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from . import bot_users, licenses
from .config import settings
from .licenses import LicenseType

logger = logging.getLogger("kzsub.telegram")

_API_BASE = "https://api.telegram.org/bot{token}/{method}"

DEMO_PLAN = "demo"
STANDARD_PLAN = "standard"
STANDARD_PRICE_KZT = 1490
# Цена за минуту — дешёвый способ показать, что тариф стоит меньше, чем кажется
# одной суммой в 1490 ₸. round(1490 / 60) = 25.
STANDARD_PRICE_PER_MINUTE = round(STANDARD_PRICE_KZT / 60)

LANG_RU = "ru"
LANG_KK = "kk"

LANG_PROMPT_TEXT = "🇰🇿 Тілді таңдаңыз / 🇷🇺 Выберите язык"
LANG_KB = {
    "inline_keyboard": [[
        {"text": "🇰🇿 Қазақша", "callback_data": "lang:kk"},
        {"text": "🇷🇺 Русский", "callback_data": "lang:ru"},
    ]]
}


def _t(lang: str, ru: str, kk: str) -> str:
    """Строка на выбранном языке. Неизвестный/пустой lang — русский по умолчанию."""
    return kk if lang == LANG_KK else ru


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


def _buy_kb(chat_id, user_id, lang: str) -> dict:
    """Кнопка «к покупке» — приклеивается к /demo, чтобы демо вело к следующему
    шагу, а не заканчивалось тупиком после того, как минуты кончатся."""
    label = _t(lang, f"Standard — {STANDARD_PRICE_KZT} ₸ →", f"Standard — {STANDARD_PRICE_KZT} ₸ →")
    return _kb([(label, f"buy:{chat_id}:{user_id}")])


def _welcome_text(lang: str) -> str:
    return _t(
        lang,
        ru=(
            "<b>NP SUB</b> — субтитры на казахском для Premiere Pro.\n\n"
            "/demo — бесплатный ключ на 3 минуты\n"
            f"/buy — тариф Standard (60 мин или 30 дней) — {STANDARD_PRICE_KZT} ₸\n"
            "/whoami — узнать свой Telegram ID\n"
            "/lang — сменить язык\n\n"
            f"Демонстрация и подробности: {settings.landing_url}"
        ),
        kk=(
            "<b>NP SUB</b> — Premiere Pro-ға арналған қазақша субтитрлер.\n\n"
            "/demo — тегін кілт, 3 минут\n"
            f"/buy — Standard тарифі (60 минут немесе 30 күн) — {STANDARD_PRICE_KZT} ₸\n"
            "/whoami — Telegram ID-ыңызды білу\n"
            "/lang — тілді ауыстыру\n\n"
            f"Толығырақ және демо: {settings.landing_url}"
        ),
    )


# --- Команды -----------------------------------------------------------------
def _handle_demo(chat_id, user_id, lang: str) -> None:
    email_key = f"tg:{user_id}"
    existing = licenses.find_by_email(email_key, type_=LicenseType.TRIAL)
    kb = _buy_kb(chat_id, user_id, lang)
    if existing is not None:
        send_message(
            chat_id,
            _t(
                lang,
                ru=("Демо-ключ уже был выдан этому аккаунту:\n"
                    f"<code>{existing.api_key}</code>\n\n"
                    "Для продолжения — команда /buy (тариф Standard)."),
                kk=("Бұл аккаунтқа демо-кілт бұрын берілген:\n"
                    f"<code>{existing.api_key}</code>\n\n"
                    "Жалғастыру үшін — /buy командасы (Standard тарифі)."),
            ),
            reply_markup=kb,
        )
        return
    lic = licenses.create_from_plan(email_key, DEMO_PLAN)
    send_message(
        chat_id,
        _t(
            lang,
            ru=("Ваш демо-ключ (3 минуты):\n"
                f"<code>{lic.api_key}</code>\n\n"
                "Вставьте его при активации плагина NP SUB в Premiere Pro.\n\n"
                f"Когда минуты закончатся — Standard даёт 60 минут за "
                f"{STANDARD_PRICE_KZT} ₸ (≈{STANDARD_PRICE_PER_MINUTE} ₸/мин) "
                "и держится 30 дней."),
            kk=("Сіздің демо-кілтіңіз (3 минут):\n"
                f"<code>{lic.api_key}</code>\n\n"
                "Оны Premiere Pro-да NP SUB плагинін іске қосу кезінде енгізіңіз.\n\n"
                f"Минут таусылғанда — Standard 60 минут береді, бағасы "
                f"{STANDARD_PRICE_KZT} ₸ (≈{STANDARD_PRICE_PER_MINUTE} ₸/мин), "
                "30 күнге жарамды."),
        ),
        reply_markup=kb,
    )


def _handle_buy(chat_id, user_id, lang: str) -> None:
    kaspi = settings.kaspi_phone or _t(
        lang,
        "(номер Kaspi не настроен — обратитесь к продавцу)",
        "(Kaspi нөмірі көрсетілмеген — сатушыға хабарласыңыз)",
    )
    text = _t(
        lang,
        ru=(
            f"Тариф <b>Standard</b>: 60 минут или 30 дней (что раньше) — "
            f"{STANDARD_PRICE_KZT} ₸ (≈{STANDARD_PRICE_PER_MINUTE} ₸/мин).\n\n"
            f"Оплатите переводом на Kaspi: <b>{kaspi}</b>\n"
            "После оплаты нажмите кнопку ниже — заявка уйдёт на подтверждение.\n\n"
            "Минуты будут заканчиваться — бот сам напомнит заранее."
        ),
        kk=(
            f"<b>Standard</b> тарифі: 60 минут немесе 30 күн (қайсысы бұрын бітсе) — "
            f"{STANDARD_PRICE_KZT} ₸ (≈{STANDARD_PRICE_PER_MINUTE} ₸/мин).\n\n"
            f"Kaspi арқылы аударыңыз: <b>{kaspi}</b>\n"
            "Төлегеннен кейін төмендегі батырманы басыңыз — өтінім растауға кетеді.\n\n"
            "Минут таусыла бастаса — бот алдын ала өзі ескертеді."
        ),
    )
    kb = _kb([(_t(lang, "Я оплатил", "Төледім"), f"pay:{chat_id}:{user_id}")])
    send_message(chat_id, text, reply_markup=kb)


def _handle_whoami(chat_id, user_id, lang: str) -> None:
    send_message(chat_id, _t(
        lang,
        f"Ваш Telegram ID: <code>{user_id}</code>",
        f"Telegram ID-ыңыз: <code>{user_id}</code>",
    ))


def _handle_lang_prompt(chat_id) -> None:
    send_message(chat_id, LANG_PROMPT_TEXT, reply_markup=LANG_KB)


# --- Кнопки (callback_query) --------------------------------------------------
def _handle_lang_pick(cq: dict) -> None:
    """Выбор языка: сохраняем и сразу заменяем сообщение-выбор приветствием."""
    cq_id = cq["id"]
    lang = cq["data"].split(":", 1)[1]
    if lang not in (LANG_RU, LANG_KK):
        lang = LANG_RU
    user_id = cq["from"]["id"]
    message = cq["message"]

    bot_users.set_lang(user_id, lang)
    answer_callback_query(cq_id)
    edit_message_text(
        message["chat"]["id"], message["message_id"],
        _welcome_text(lang), reply_markup={"inline_keyboard": []},
    )


def _handle_buy_click(cq: dict) -> None:
    """Кнопка «к покупке», приклеенная к сообщению с демо-ключом."""
    cq_id = cq["id"]
    _, chat_id, user_id = cq["data"].split(":")
    lang = bot_users.get_lang(user_id)
    answer_callback_query(cq_id)
    _handle_buy(chat_id, user_id, lang)


def _handle_pay_click(cq: dict) -> None:
    cq_id = cq["id"]
    _, chat_id, user_id = cq["data"].split(":")
    lang = bot_users.get_lang(user_id)
    from_user = cq.get("from", {})
    username = from_user.get("username") or from_user.get("first_name") or str(user_id)
    message = cq["message"]

    answer_callback_query(cq_id, _t(
        lang, "Заявка отправлена, ждите подтверждения.",
        "Өтінім жіберілді, растауды күтіңіз.",
    ))
    edit_message_text(
        message["chat"]["id"], message["message_id"],
        _t(lang, "Заявка отправлена продавцу. Ожидайте подтверждения оплаты.",
                 "Өтінім сатушыға жіберілді. Төлемнің расталуын күтіңіз."),
    )

    admins = _admin_ids()
    if not admins:
        send_message(chat_id, _t(
            lang, "Приём заявок пока не настроен — напишите продавцу напрямую.",
            "Өтінімдерді қабылдау әлі теңшелмеген — сатушыға тікелей жазыңыз.",
        ))
        return

    # Продавцу — всегда по-русски: это его рабочий интерфейс, не клиентский.
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
    lang = bot_users.get_lang(client_user_id)
    message = cq["message"]

    if approve:
        email_key = f"tg:{client_user_id}"
        # Переиспользуем уже выданный ключ, если заявку подтвердили повторно
        # (двойной клик/гонка) — не плодим лицензии на один и тот же аккаунт.
        existing = licenses.find_by_email(email_key, type_=LicenseType.SUBSCRIPTION)
        lic = existing or licenses.create_from_plan(email_key, STANDARD_PLAN)
        send_message(
            client_chat_id,
            _t(
                lang,
                ru=("Оплата подтверждена! Ваш ключ Standard:\n"
                    f"<code>{lic.api_key}</code>\n\n"
                    "Вставьте его при активации плагина NP SUB."),
                kk=("Төлем расталды! Standard кілтіңіз:\n"
                    f"<code>{lic.api_key}</code>\n\n"
                    "Оны NP SUB плагинін іске қосу кезінде енгізіңіз."),
            ),
        )
        edit_message_text(message["chat"]["id"], message["message_id"],
                           "✅ Подтверждено, ключ выдан")
        answer_callback_query(cq_id, "Ключ выдан.")
    else:
        send_message(client_chat_id, _t(
            lang, "Оплата не найдена. Если вы оплатили — напишите продавцу.",
            "Төлем табылмады. Егер төлеген болсаңыз — сатушыға жазыңыз.",
        ))
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

            if text.startswith("/lang"):
                _handle_lang_prompt(chat_id)
                return

            lang = bot_users.get_lang(user_id)
            if not lang:
                # Первое сообщение от нового пользователя — только выбор языка,
                # ни один другой ответ ему до этого не показываем.
                _handle_lang_prompt(chat_id)
                return

            if text.startswith("/demo"):
                _handle_demo(chat_id, user_id, lang)
            elif text.startswith("/buy"):
                _handle_buy(chat_id, user_id, lang)
            elif text.startswith("/whoami"):
                _handle_whoami(chat_id, user_id, lang)
            else:
                send_message(chat_id, _welcome_text(lang))
        elif "callback_query" in update:
            cq = update["callback_query"]
            data = cq.get("data", "")
            if data.startswith("lang:"):
                _handle_lang_pick(cq)
            elif data.startswith("buy:"):
                _handle_buy_click(cq)
            elif data.startswith("pay:"):
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
