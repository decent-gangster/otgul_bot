from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters.callback_data import CallbackData


class RequestTypeCallback(CallbackData, prefix="req_type"):
    type_value: str  # otgul / vacation / sick


class RequestActionCallback(CallbackData, prefix="req_action"):
    action: str      # approve / reject
    request_id: int


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
