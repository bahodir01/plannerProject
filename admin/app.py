"""Админ-панель (FastAPI): динамические настройки бота, доступы, логи."""
import os
import sys
import json

from fastapi import FastAPI, Request, Form, UploadFile, File, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# запуск из корня проекта: добавляем его в путь
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import settings_store
import event_log
import sheets
import api_usage
from admin import auth

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = FastAPI(title="Planner Bot Admin")
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

COOKIE = "planner_admin_session"


@app.on_event("startup")
def _startup():
    auth.ensure_admin_bootstrap()
    _sync_sheets_to_departments()


# ---------- Аутентификация ----------
def current_user(request: Request) -> str:
    token = request.cookies.get(COOKIE, "")
    user = auth.read_session(token)
    if not user:
        raise HTTPException(status_code=307, detail="redirect",
                            headers={"Location": "/login"})
    return user


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str = ""):
    return templates.TemplateResponse("login.html",
                                      {"request": request, "error": error})


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if not auth.check_login(username, password):
        event_log.log_event("admin_login_failed", username, "Неверный логин/пароль")
        return RedirectResponse("/login?error=1", status_code=303)
    token = auth.create_session(username)
    event_log.log_event("admin_login", username, "Вход в админ-панель")
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(COOKIE, token, httponly=True, samesite="lax", max_age=86400)
    return resp


@app.get("/logout")
def logout(request: Request):
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(COOKIE)
    return resp


# ---------- Обработчик редиректа неавторизованных ----------
@app.exception_handler(HTTPException)
async def _auth_redirect(request: Request, exc: HTTPException):
    if exc.status_code == 307 and exc.headers and "Location" in exc.headers:
        return RedirectResponse(exc.headers["Location"], status_code=303)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


# ---------- Главная / дашборд ----------
@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, user: str = Depends(current_user)):
    s = settings_store.load()
    ok_token = bool(s["telegram"]["token"])
    ok_creds = os.path.exists(s["google"]["creds_path"])

    # AI провайдеры
    ai_cfg = s.get("ai_providers", {})
    assemblyai_key = bool(ai_cfg.get("assemblyai_key"))
    gemini_key = bool(ai_cfg.get("gemini_key"))
    openai_key = bool(ai_cfg.get("openai_key"))

    return templates.TemplateResponse("dashboard.html", {
        "request": request, "user": user, "s": s, "active": "dashboard",
        "ok_token": ok_token, "ok_creds": ok_creds,
        "dept_count": len(s.get("departments", [])),
        "allowed_count": len(s["telegram"].get("allowed_user_ids", [])),
        "ai_config": ai_cfg,
        "assemblyai_key": assemblyai_key,
        "gemini_key": gemini_key,
        "openai_key": openai_key,
    })


# ---------- Настройки: Telegram / доступы ----------
@app.get("/settings/telegram", response_class=HTMLResponse)
def telegram_page(request: Request, user: str = Depends(current_user), saved: str = ""):
    s = settings_store.load()
    ids = ", ".join(str(x) for x in s["telegram"].get("allowed_user_ids", []))
    return templates.TemplateResponse("telegram.html", {
        "request": request, "user": user, "s": s, "allowed_ids": ids, "saved": saved, "active": "telegram",
    })


@app.post("/settings/telegram")
def telegram_save(request: Request, user: str = Depends(current_user),
                  token: str = Form(""), allowed_user_ids: str = Form("")):
    ids = []
    for part in allowed_user_ids.replace("\n", ",").split(","):
        part = part.strip()
        if part.isdigit():
            ids.append(int(part))
    settings_store.update_section("telegram", {"token": token.strip(),
                                               "allowed_user_ids": ids})
    event_log.log_event("settings_changed", user, "Telegram / доступы обновлены")
    return RedirectResponse("/settings/telegram?saved=1", status_code=303)


# ---------- Настройки: Google Sheets ----------
@app.get("/settings/google", response_class=HTMLResponse)
def google_page(request: Request, user: str = Depends(current_user),
                saved: str = "", test: str = ""):
    s = settings_store.load()
    creds_exists = os.path.exists(s["google"]["creds_path"])
    test_result = None
    if test == "1":
        test_result = sheets.test_connection()
    return templates.TemplateResponse("google.html", {
        "request": request, "user": user, "s": s, "active": "google",
        "creds_exists": creds_exists, "saved": saved, "test_result": test_result,
    })


@app.post("/settings/google")
async def google_save(request: Request, user: str = Depends(current_user),
                      sheet_name: str = Form(""), creds_path: str = Form(""),
                      creds_file: UploadFile = File(None)):
    creds_path = creds_path.strip() or "google-creds.json"
    # если загрузили файл — сохраняем его по указанному пути
    if creds_file is not None and creds_file.filename:
        content = await creds_file.read()
        try:
            json.loads(content)  # валидация, что это JSON
        except Exception:  # noqa: BLE001
            return RedirectResponse("/settings/google?saved=err", status_code=303)
        with open(creds_path, "wb") as f:
            f.write(content)
    settings_store.update_section("google", {"sheet_name": sheet_name.strip(),
                                             "creds_path": creds_path})
    event_log.log_event("settings_changed", user, "Google Sheets настройки обновлены")
    return RedirectResponse("/settings/google?saved=1", status_code=303)


@app.get("/settings/google/test")
def google_test(request: Request, user: str = Depends(current_user)):
    return RedirectResponse("/settings/google?test=1", status_code=303)


# ---------- Настройки: AI провайдеры ----------
@app.get("/settings/ai_providers", response_class=HTMLResponse)
def ai_providers_page(request: Request, user: str = Depends(current_user), saved: str = ""):
    s = settings_store.load()
    ai_config = s.get("ai_providers", {})
    return templates.TemplateResponse("ai_providers.html", {
        "request": request, "user": user, "config": ai_config, "saved": saved, "active": "ai_providers",
    })


@app.post("/settings/ai_providers")
def ai_providers_save(request: Request, user: str = Depends(current_user),
                      stt_primary: str = Form(""), stt_fallback: str = Form(""),
                      nlp_primary: str = Form(""), nlp_fallback: str = Form(""),
                      assemblyai_key: str = Form(""), gemini_key: str = Form(""),
                      openai_key: str = Form("")):
    settings_store.update_section("ai_providers", {
        "stt_primary": stt_primary.strip(),
        "stt_fallback": stt_fallback.strip(),
        "nlp_primary": nlp_primary.strip(),
        "nlp_fallback": nlp_fallback.strip(),
        "assemblyai_key": assemblyai_key.strip(),
        "gemini_key": gemini_key.strip(),
        "openai_key": openai_key.strip(),
    })
    event_log.log_event("settings_changed", user, "AI провайдеры обновлены")
    return RedirectResponse("/settings/ai_providers?saved=1", status_code=303)


# ---------- Настройки: поведение ----------
@app.post("/settings/behavior")
def behavior_save(request: Request, user: str = Depends(current_user),
                  require_confirmation: str = Form(""), timezone: str = Form(""),
                  default_status: str = Form("")):
    settings_store.update_section("behavior", {
        "require_confirmation": require_confirmation == "on",
        "timezone": timezone.strip() or "Asia/Tashkent",
        "default_status": default_status.strip() or "In Progress",
    })
    event_log.log_event("settings_changed", user, "Параметры поведения обновлены")
    return RedirectResponse("/settings/behavior?saved=1", status_code=303)


@app.get("/settings/behavior", response_class=HTMLResponse)
def behavior_page(request: Request, user: str = Depends(current_user), saved: str = ""):
    s = settings_store.load()
    return templates.TemplateResponse("behavior.html", {
        "request": request, "user": user, "s": s, "saved": saved, "active": "behavior",
    })


# ---------- Синхронизация листов из Google Sheets ----------
def _sync_sheets_to_departments():
    """Автоматически создаёт новые направления из новых листов в таблице."""
    try:
        s = settings_store.load()
        existing_names = {d["name"].strip().lower() for d in s.get("departments", [])}
        worksheet_names = sheets.list_worksheets()

        new_depts = []
        for ws_name in worksheet_names:
            if ws_name.strip().lower() not in existing_names:
                new_depts.append({
                    "name": ws_name,
                    "staff_name": "",
                    "aliases": [ws_name.strip().lower()],
                })

        if new_depts:
            all_depts = s.get("departments", []) + new_depts
            settings_store.set_departments(all_depts)
            event_log.log_event("auto_sync", "system", f"Автоматически добавлено {len(new_depts)} новых направлений из листов")
    except Exception:
        pass  # тихо игнорируем ошибки при синхронизации


# ---------- Настройки: направления (листы) ----------
@app.get("/settings/departments", response_class=HTMLResponse)
def departments_page(request: Request, user: str = Depends(current_user), saved: str = ""):
    _sync_sheets_to_departments()
    s = settings_store.load()
    # Подтягивание исполнителей отключено
    # exclude_sheets = ["Roadmap", "Planner", "Department Ish reja"]
    # staff_names = sheets.get_staff_names(exclude_sheets=exclude_sheets)
    staff_names = []
    return templates.TemplateResponse("departments.html", {
        "request": request, "user": user, "departments": s.get("departments", []), "active": "departments",
        "saved": saved, "staff_names": staff_names,
    })


@app.post("/settings/departments")
async def departments_save(request: Request, user: str = Depends(current_user)):
    """Принимает список направлений из формы (name[], staff[], aliases[])."""
    form = await request.form()
    names = form.getlist("name")
    staff = form.getlist("staff")
    aliases = form.getlist("aliases")
    depts = []
    for i, name in enumerate(names):
        name = (name or "").strip()
        if not name:
            continue
        al = [a.strip().lower() for a in (aliases[i] if i < len(aliases) else "").split(",") if a.strip()]
        depts.append({
            "name": name,
            "staff_name": (staff[i] if i < len(staff) else "").strip(),
            "aliases": al,
        })
    settings_store.set_departments(depts)
    event_log.log_event("settings_changed", user, f"Направления обновлены ({len(depts)})")
    return RedirectResponse("/settings/departments?saved=1", status_code=303)


# ---------- Настройки: смена пароля админа ----------
@app.get("/settings/account", response_class=HTMLResponse)
def account_page(request: Request, user: str = Depends(current_user), saved: str = ""):
    s = settings_store.load()
    return templates.TemplateResponse("account.html", {
        "request": request, "user": user, "username": s["admin"]["username"], "active": "account",
        "saved": saved,
    })


@app.post("/settings/account")
def account_save(request: Request, user: str = Depends(current_user),
                 username: str = Form(...), password: str = Form("")):
    auth.set_credentials(username.strip(), password)
    event_log.log_event("settings_changed", user, "Учётные данные админа изменены")
    return RedirectResponse("/settings/account?saved=1", status_code=303)


# ---------- Мониторинг: Использование API ----------
@app.get("/api_usage", response_class=HTMLResponse)
def api_usage_page(request: Request, user: str = Depends(current_user)):
    stats = api_usage.get_usage_stats(days=30)
    free_tier = api_usage.get_free_tier_status()
    return templates.TemplateResponse("api_usage.html", {
        "request": request, "user": user, "stats": stats, "free_tier_status": free_tier,
        "active": "api_usage",
    })


# ---------- Логи ----------
@app.get("/logs", response_class=HTMLResponse)
def logs_page(request: Request, user: str = Depends(current_user), kind: str = ""):
    events = event_log.read_events(limit=300, kind=kind or None)
    bot_log = event_log.read_bot_log(lines=200)
    return templates.TemplateResponse("logs.html", {
        "request": request, "user": user, "events": events, "active": "logs",
        "bot_log": bot_log, "kind": kind,
    })


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("ADMIN_PORT", "8000"))
    uvicorn.run("admin.app:app", host="0.0.0.0", port=port, reload=False)
