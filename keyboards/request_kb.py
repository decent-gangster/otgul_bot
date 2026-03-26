from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters.callback_data import CallbackData


class RequestTypeCallback(CallbackData, prefix="req_type"):
    type_value: str  # otgul / vacation / sick


class RequestActionCallback(CallbackData, prefix="req_action"):
    action: str      # approve / reject
    request_id: int


class RequestRevokeCallback(CallbackData, prefix="req_revoke"):
    request_id: int


class RequestCancelCallback(CallbackData, prefix="req_cancel"):
    request_id: int


class RequestCancelConfirmCallback(CallbackData, prefix="req_cancel_ok"):
    request_id: int


class RequestCancelBackCallback(CallbackData, prefix="req_cancel_back"):
    request_id: int


class ReportPeriodCallback(CallbackData, prefix="report"):
    period: str  # "current", "previous", "custom"


class TimeCallback(CallbackData, prefix="time_pick"):
    value: str  # "0800" — без двоеточия, оно запрещено в CallbackData


# Рабочий день 08:00–17:30, шаг 30 мин. Формат "HHMM" (без двоеточия)
TIME_SLOTS = [
    "0830", "0900", "0930",
    "1000", "1030", "1100", "1130",
    "1200", "1230", "1300", "1330",
    "1400", "1430", "1500", "1530",
    "1600", "1630", "1700", "1730",
]


def fmt_time(raw: str) -> str:
    """'0800' → '08:00'"""
    return f"{raw[:2]}:{raw[2:]}"


def time_keyboard(after: str = None, before: str = None) -> InlineKeyboardMarkup:
    """Клавиатура выбора времени. after — 'HHMM', показываем только слоты позже него. before — строго меньше."""
    slots = [t for t in TIME_SLOTS if (after is None or t > after) and (before is None or t < before)]
    buttons = [
        InlineKeyboardButton(text=fmt_time(t), callback_data=TimeCallback(value=t).pack())
        for t in slots
    ]
    rows = [buttons[i:i + 4] for i in range(0, len(buttons), 4)]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def request_type_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора типа заявки."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🗓 Отгул",
            callback_data=RequestTypeCallback(type_value="отгул").pack()
        )],
        [InlineKeyboardButton(
            text="🌴 Отпуск",
            callback_data=RequestTypeCallback(type_value="отпуск").pack()
        )],
        [InlineKeyboardButton(
            text="🏥 Больничный",
            callback_data=RequestTypeCallback(type_value="больничный").pack()
        )],
        [InlineKeyboardButton(
            text="🎂 День рождения",
            callback_data=RequestTypeCallback(type_value="день рождения").pack()
        )],
    ])


def otgul_type_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора вида отгула: за свой счёт или с содержанием."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💸 За свой счёт", callback_data="otgul_own")],
        [InlineKeyboardButton(text="✅ С содержанием (отработка)", callback_data="otgul_paid")],
    ])


def hours_or_days_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора: полный день или отгул по часам."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Полный день", callback_data="otgul_full_day")],
        [InlineKeyboardButton(text="⏱ По часам", callback_data="otgul_by_hours")],
    ])


def confirm_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура подтверждения заявки."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_request"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_request"),
        ]
    ])


def report_period_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора периода для отчёта."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Текущий месяц", callback_data=ReportPeriodCallback(period="current").pack())],
        [InlineKeyboardButton(text="📅 Прошлый месяц", callback_data=ReportPeriodCallback(period="previous").pack())],
        [InlineKeyboardButton(text="✏️ Указать период", callback_data=ReportPeriodCallback(period="custom").pack())],
    ])


def cancel_own_request_keyboard(request_id: int) -> InlineKeyboardMarkup:
    """Кнопка отмены заявки самим сотрудником (pending)."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="❌ Отменить заявку",
            callback_data=RequestCancelCallback(request_id=request_id).pack()
        )
    ]])


def cancel_confirm_keyboard(request_id: int) -> InlineKeyboardMarkup:
    """Подтверждение отмены заявки."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="✅ Да, отменить",
            callback_data=RequestCancelConfirmCallback(request_id=request_id).pack()
        ),
        InlineKeyboardButton(text="◀️ Назад", callback_data=RequestCancelBackCallback(request_id=request_id).pack()),
    ]])


def revoke_request_keyboard(request_id: int) -> InlineKeyboardMarkup:
    """Кнопка отзыва одобренной заявки."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="🔄 Отозвать",
            callback_data=RequestRevokeCallback(request_id=request_id).pack()
        )
    ]])


def admin_request_keyboard(request_id: int) -> InlineKeyboardMarkup:
    """Клавиатура для одобрения/отклонения заявки администратором."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Одобрить",
                callback_data=RequestActionCallback(action="approve", request_id=request_id).pack()
            ),
            InlineKeyboardButton(
                text="❌ Отклонить",
                callback_data=RequestActionCallback(action="reject", request_id=request_id).pack()
            ),
        ]
    ])
