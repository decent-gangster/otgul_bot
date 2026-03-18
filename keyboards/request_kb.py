from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters.callback_data import CallbackData


class RequestTypeCallback(CallbackData, prefix="req_type"):
    type_value: str  # otgul / vacation / sick


class RequestActionCallback(CallbackData, prefix="req_action"):
    action: str      # approve / reject
    request_id: int


class TimeCallback(CallbackData, prefix="time_pick"):
    value: str  # "10:00"


TIME_SLOTS = [
    "08:00", "08:30", "09:00", "09:30",
    "10:00", "10:30", "11:00", "11:30",
    "12:00", "12:30", "13:00", "13:30",
    "14:00", "14:30", "15:00", "15:30",
    "16:00", "16:30", "17:00", "17:30",
    "18:00",
]


def time_keyboard(after: str = None) -> InlineKeyboardMarkup:
    """Клавиатура выбора времени. after — минимальное время (не включительно)."""
    slots = [t for t in TIME_SLOTS if after is None or t > after]
    buttons = [
        InlineKeyboardButton(text=t, callback_data=TimeCallback(value=t).pack())
        for t in slots
    ]
    rows = [buttons[i:i + 4] for i in range(0, len(buttons), 4)]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def request_type_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора типа заявки."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🗓 Отгул (свой счёт)",
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
