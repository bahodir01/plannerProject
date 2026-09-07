"""Запись задач в журнал Planner (Google Sheets), в лист по направлению.
Клиент и таблица кешируются по (creds_path, sheet_name); при смене настроек
в админке пересоздаются автоматически."""
import logging

import gspread

import config

log = logging.getLogger(__name__)

_gc = None
_spreadsheet = None
_signature: tuple | None = None

# A Staff Name | B Task/Activity | C Period | D Deadline | E Status | F Comment
_COLUMN_ORDER = ["staff", "task", "period", "deadline", "status", "comment"]


def _get_spreadsheet():
    """Возвращает открытую таблицу, пересоздавая при смене кредов/имени."""
    global _gc, _spreadsheet, _signature
    creds = config.google_creds_path()
    name = config.sheet_name()
    sig = (creds, name)
    if _spreadsheet is None or sig != _signature:
        _gc = gspread.service_account(filename=creds)
        _spreadsheet = _gc.open(name)
        _signature = sig
        log.info("Spreadsheet opened: %s", name)
    return _spreadsheet


def list_worksheets() -> list[str]:
    return [ws.title for ws in _get_spreadsheet().worksheets()]


def _find_worksheet(department: str):
    target = department.strip().lower()
    for ws in _get_spreadsheet().worksheets():
        if ws.title.strip().lower() == target:
            return ws
    raise ValueError(f"Лист «{department}» не найден в таблице")


def append_task(department: str, staff_name: str, task: str,
                deadline: str, status: str, comment: str = "") -> dict:
    """Дописывает строку задачи в лист направления. Period (C) оставляется пустым."""
    ws = _find_worksheet(department)
    row = {
        "staff": staff_name,
        "task": task,
        "period": "",
        "deadline": deadline or "",
        "status": status,
        "comment": comment or "",
    }
    ordered = [row[c] for c in _COLUMN_ORDER]
    ws.append_row(ordered, value_input_option="USER_ENTERED")
    log.info("Appended to '%s': %s", department, ordered)
    return {"worksheet": ws.title, "row": ordered}


def get_staff_names(exclude_sheets=None) -> list[str]:
    """Извлекает все уникальные имена исполнителей из листов (колонка B).
    exclude_sheets: список названий листов для исключения (например: ['Roadmap Planner'])."""
    if exclude_sheets is None:
        exclude_sheets = []
    exclude_lower = {name.strip().lower() for name in exclude_sheets}

    staff_set = set()
    try:
        for ws in _get_spreadsheet().worksheets():
            # Пропускаем листы в списке исключений
            if ws.title.strip().lower() in exclude_lower:
                continue
            # Получаем все значения из колонки B (staff_name)
            col_b = ws.col_values(2)
            # Пропускаем заголовок (обычно первая строка)
            for name in col_b[1:]:  # начинаем со второй строки
                name = name.strip()
                if name:  # исключаем пустые ячейки
                    staff_set.add(name)
    except Exception as e:  # noqa: BLE001
        log.error("Error getting staff names: %s", e)
    return sorted(list(staff_set))


def test_connection() -> dict:
    """Проверка связи с таблицей (для кнопки в админке)."""
    try:
        titles = list_worksheets()
        return {"ok": True, "worksheets": titles}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
