"""Telegram-бот: приём задач (текст/голос) -> запись в журнал Planner
(Google Sheets) в лист по направлению. Все настройки динамические (админка)."""
import os
import time
import hashlib
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters,
)

import config
import nlp
import sheets
import event_log

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.FileHandler("logs/bot.log"), logging.StreamHandler()],
)
log = logging.getLogger("bot")

_seen: dict[str, float] = {}
_pending: dict[str, dict] = {}


def t(lang: str, ru: str, alt: str) -> str:
    return ru if lang == "ru" else alt


def _dedupe(key: str, ttl: int = 60) -> bool:
    now = time.time()
    for k, ts in list(_seen.items()):
        if now - ts > ttl:
            del _seen[k]
    if key in _seen:
        return True
    _seen[key] = now
    return False


def _actor(tg_user) -> str:
    return f"@{tg_user.username}" if tg_user.username else str(tg_user.id)


def _preview(draft: dict, lang: str) -> str:
    task = draft["task"]
    dept = config.get_department(draft["department"])
    staff = dept.get("staff_name") if dept else ""
    return (
        t(lang, "📋 Проверьте задачу:", "📋 Vazifani tekshiring:") + "\n\n"
        f"📁 {t(lang, 'Лист', 'List')}: {draft['department']}\n"
        + (f"👤 {staff}\n" if staff else "")
        + f"📝 {task['task']}\n"
        f"📅 {task.get('deadline') or 'Regular'}\n"
        f"🗒 {task.get('comment') or '—'}"
    )


async def _write_and_report(draft: dict, lang: str, reply_fn, actor: str) -> None:
    task = draft["task"]
    dept = config.get_department(draft["department"])
    staff = dept.get("staff_name", "") if dept else ""
    try:
        result = sheets.append_task(
            department=draft["department"],
            staff_name=staff,
            task=task["task"],
            deadline=task.get("deadline", ""),
            status=config.default_status(),
            comment=task.get("comment", ""),
        )
        event_log.log_event(
            "task_created", actor,
            f"{draft['department']}: {task['task']}",
            deadline=task.get("deadline"), worksheet=result["worksheet"],
        )
        await reply_fn(
            t(lang, "✅ Задача записана в журнал", "✅ Vazifa jurnalga yozildi") + "\n\n"
            f"📁 {result['worksheet']}\n"
            + (f"👤 {staff}\n" if staff else "")
            + f"📝 {task['task']}\n"
            f"📅 {task.get('deadline') or 'Regular'}"
        )
    except Exception as e:  # noqa: BLE001
        log.exception("Sheet write failed")
        event_log.log_event("error", actor, f"Ошибка записи: {e}",
                            department=draft.get("department"))
        await reply_fn(t(lang, f"⚠️ Не удалось записать: {e}",
                         f"⚠️ Yozib bo'lmadi: {e}"))


def _ask_department_kb(token: str):
    kb, row = [], []
    for i, name in enumerate(config.department_names()):
        row.append(InlineKeyboardButton(name, callback_data=f"dep:{token}:{i}"))
        if len(row) == 2:
            kb.append(row); row = []
    if row:
        kb.append(row)
    return InlineKeyboardMarkup(kb)


def _confirm_kb(lang: str, token: str):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(t(lang, "✅ Записать", "✅ Yozish"),
                             callback_data=f"ok:{token}"),
        InlineKeyboardButton(t(lang, "❌ Отмена", "❌ Bekor"),
                             callback_data=f"no:{token}"),
    ]])


async def _proceed(draft: dict, lang: str, token: str, reply_fn, actor: str,
                   edit_fn=None):
    if config.require_confirmation():
        _pending[token] = {**draft, "actor": actor}
        send = edit_fn or reply_fn
        await send(_preview(draft, lang), reply_markup=_confirm_kb(lang, token))
    else:
        await _write_and_report(draft, lang, reply_fn, actor)


async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    tg_user = update.effective_user
    actor = _actor(tg_user)

    # 1) Whitelist (динамический)
    allowed = config.allowed_user_ids()
    if allowed and tg_user.id not in allowed:
        await msg.reply_text("⛔ У вас нет доступа к этому боту.")
        event_log.log_event("access_denied", actor,
                            f"Отказано в доступе (id={tg_user.id})")
        log.warning("Blocked user %s", tg_user.id)
        return

    # 2) Текст или голос
    if msg.voice:
        f = await ctx.bot.get_file(msg.voice.file_id)
        path = f"/tmp/{msg.voice.file_id}.ogg"
        await f.download_to_drive(path)
        try:
            text = nlp.transcribe(path)
        finally:
            if os.path.exists(path):
                os.remove(path)
        if not text:
            await msg.reply_text("🔇 Не удалось распознать речь. Пришлите текстом.")
            return
    else:
        text = (msg.text or "").strip()
    if not text:
        return

    lang = nlp.detect_lang(text)

    # 3) Дубли
    key = hashlib.sha256(f"{tg_user.id}:{text}".encode()).hexdigest()
    if _dedupe(key):
        return
    token = key[:16]

    # 4) Парсинг
    try:
        task = nlp.parse_task(text)
    except Exception:  # noqa: BLE001
        log.exception("Parse failed")
        event_log.log_event("error", actor, "Не удалось разобрать задачу")
        await msg.reply_text(t(lang, "❌ Не смог разобрать задачу.",
                               "❌ Vazifani tushunolmadim."))
        return

    # 5) Направление
    department = task.get("department")
    if not department or department not in config.department_names():
        department = config.resolve_department(text)

    draft = {"task": task, "department": department, "lang": lang}
    if not department:
        _pending[token] = {**draft, "actor": actor}
        await msg.reply_text(
            t(lang, "📁 В какой лист записать?", "📁 Qaysi listga yozay?"),
            reply_markup=_ask_department_kb(token),
        )
        return

    await _proceed(draft, lang, token, msg.reply_text, actor)


async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    actor = _actor(update.effective_user)

    if data.startswith("no:"):
        p = _pending.pop(data.split(":", 1)[1], None)
        if p:
            event_log.log_event("task_cancelled", actor,
                                p["task"].get("task", ""))
        await q.edit_message_text("❌ Отменено.")
        return

    if data.startswith("ok:"):
        token = data.split(":", 1)[1]
        draft = _pending.pop(token, None)
        if not draft:
            await q.edit_message_text("⌛ Черновик устарел, отправьте заново.")
            return
        lang = draft["lang"]
        await q.edit_message_text(t(lang, "⏳ Записываю...", "⏳ Yozilmoqda..."))
        await _write_and_report(draft, lang, q.message.reply_text,
                                draft.get("actor", actor))
        return

    if data.startswith("dep:"):
        _, token, idx = data.split(":")
        draft = _pending.get(token)
        if not draft:
            await q.edit_message_text("⌛ Черновик устарел, отправьте заново.")
            return
        draft["department"] = config.department_names()[int(idx)]
        lang = draft["lang"]
        await _proceed(draft, lang, token, q.message.reply_text,
                       draft.get("actor", actor), q.edit_message_text)
        return


def main():
    token = config.telegram_token()
    if not token:
        raise SystemExit("Не задан токен Telegram. Укажите его в админ-панели.")
    app = Application.builder().token(token).build()
    app.add_handler(MessageHandler(filters.TEXT | filters.VOICE, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))
    event_log.log_event("bot_started", "system", "Бот запущен")
    log.info("Bot started. Confirmation=%s Sheets=%s",
             config.require_confirmation(), config.sheet_name())
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
