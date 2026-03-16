import logging

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from datetime import date

logger = logging.getLogger(__name__)

from states.request_states import RequestForm
from keyboards.calendar import build_calendar, CalendarCallback
from keyboards.request_kb import request_type_keyboard, confirm_keyboard, RequestTypeCallback, admin_request_keyboard
from keyboards.menus import user_main_menu, back_keyboard
from database.engine import AsyncSessionFactory
from database.crud import get_or_create_user, create_request
from database.models import RequestType

router = Router()

# ─── Типы заявок — человекочитаемые названия ─────────────────────────────────
REQUEST_TYPE_LABELS = {
    "отгул": "🗓 Отгул (свой счёт)",
    "отпуск": "🌴 Отпуск",
    "больничный": "🏥 Больничный",
}


# ─── Шаг 1: Пользователь нажимает «Подать заявку» ────────────────────────────
@router.message(F.text == "📝 Подать заявку")
async def start_request(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(RequestForm.choosing_start_date)
    await message.answer(
        "📅 <b>Выберите дату начала</b>:",
        reply_markup=build_calendar(),
        parse_mode="HTML"
    )


# ─── Шаг 2: Выбор даты начала через инлайн-календарь ─────────────────────────
@router.callback_query(CalendarCallback.filter(F.action == "day"), RequestForm.choosing_start_date)
async def choose_start_date(call: CallbackQuery, callback_data: CalendarCallback, state: FSMContext):
    chosen = date(callback_data.year, callback_data.month, callback_data.day)
    if chosen < date.today():
        await call.answer("⚠️ Нельзя выбрать прошедшую дату!", show_alert=True)
        return

    await state.update_data(start_date=chosen.isoformat())
    await state.set_state(RequestForm.choosing_end_date)
    await call.message.edit_text(
        f"✅ Дата начала: <b>{chosen.strftime('%d.%m.%Y')}</b>\n\n"
        f"📅 <b>Выберите дату окончания</b>:",
        reply_markup=build_calendar(chosen.year, chosen.month),
        parse_mode="HTML"
    )
    await call.answer()


# ─── Навигация по календарю (общая — работает в обоих состояниях) ─────────────
@router.callback_query(
    CalendarCallback.filter(F.action.in_({"prev_month", "next_month"})),
    RequestForm.choosing_start_date
)
@router.callback_query(
    CalendarCallback.filter(F.action.in_({"prev_month", "next_month"})),
    RequestForm.choosing_end_date
)
async def navigate_calendar(call: CallbackQuery, callback_data: CalendarCallback):
    await call.message.edit_reply_markup(
        reply_markup=build_calendar(callback_data.year, callback_data.month)
    )
    await call.answer()


@router.callback_query(CalendarCallback.filter(F.action == "ignore"))
async def ignore_calendar(call: CallbackQuery):
    await call.answer()


# ─── Шаг 3: Выбор даты окончания ─────────────────────────────────────────────
@router.callback_query(CalendarCallback.filter(F.action == "day"), RequestForm.choosing_end_date)
async def choose_end_date(call: CallbackQuery, callback_data: CalendarCallback, state: FSMContext):
    data = await state.get_data()
    start = date.fromisoformat(data["start_date"])
    end = date(callback_data.year, callback_data.month, callback_data.day)

    if end < start:
        await call.answer("⚠️ Дата окончания не может быть раньше даты начала!", show_alert=True)
        return

    await state.update_data(end_date=end.isoformat())
    await state.set_state(RequestForm.choosing_type)
    await call.message.edit_text(
        f"✅ Дата начала: <b>{start.strftime('%d.%m.%Y')}</b>\n"
        f"✅ Дата окончания: <b>{end.strftime('%d.%m.%Y')}</b>\n\n"
        f"📋 <b>Выберите тип заявки:</b>",
        reply_markup=request_type_keyboard(),
        parse_mode="HTML"
    )
    await call.answer()


# ─── Шаг 4: Выбор типа заявки ────────────────────────────────────────────────
@router.callback_query(RequestTypeCallback.filter(), RequestForm.choosing_type)
async def choose_type(call: CallbackQuery, callback_data: RequestTypeCallback, state: FSMContext):
    await state.update_data(request_type=callback_data.type_value)
    await state.set_state(RequestForm.entering_reason)
    await call.message.edit_text(
        f"✅ Тип: <b>{REQUEST_TYPE_LABELS[callback_data.type_value]}</b>\n\n"
        f"✏️ <b>Укажите причину</b> (или напишите «—» если не хотите):",
        parse_mode="HTML"
    )
    await call.answer()


# ─── Шаг 5: Ввод причины ─────────────────────────────────────────────────────
@router.message(RequestForm.entering_reason)
async def enter_reason(message: Message, state: FSMContext):
    reason = message.text.strip()
    await state.update_data(reason=reason)
    data = await state.get_data()

    start = date.fromisoformat(data["start_date"])
    end = date.fromisoformat(data["end_date"])
    days = (end - start).days + 1

    summary = (
        f"📄 <b>Итог вашей заявки:</b>\n\n"
        f"📋 Тип: <b>{REQUEST_TYPE_LABELS[data['request_type']]}</b>\n"
        f"📅 Начало: <b>{start.strftime('%d.%m.%Y')}</b>\n"
        f"📅 Конец: <b>{end.strftime('%d.%m.%Y')}</b>\n"
        f"🔢 Дней: <b>{days}</b>\n"
        f"💬 Причина: <b>{reason}</b>\n\n"
        f"Всё верно?"
    )
    await state.set_state(RequestForm.confirming)
    await message.answer(summary, reply_markup=confirm_keyboard(), parse_mode="HTML")


# ─── Шаг 6: Подтверждение — сохранение в БД и уведомление админу ─────────────
@router.callback_query(F.data == "confirm_request", RequestForm.confirming)
async def confirm_request(call: CallbackQuery, state: FSMContext, bot: Bot, admin_ids: list[int]):
    data = await state.get_data()
    await state.clear()

    async with AsyncSessionFactory() as session:
        user = await get_or_create_user(session, call.from_user.id, call.from_user.full_name)
        req = await create_request(
            session,
            user_id=user.id,
            start_date=date.fromisoformat(data["start_date"]),
            end_date=date.fromisoformat(data["end_date"]),
            type=RequestType(data["request_type"]),
            reason=data["reason"],
        )

    start = date.fromisoformat(data["start_date"])
    end = date.fromisoformat(data["end_date"])
    days = (end - start).days + 1

    # ── Ответ пользователю ──────────────────────────────────────────────────
    await call.message.edit_text(
        f"✅ <b>Заявка #{req.id} отправлена на рассмотрение!</b>\n\n"
        f"Вы получите уведомление, когда администратор примет решение.",
        parse_mode="HTML"
    )
    await call.message.answer("Главное меню:", reply_markup=user_main_menu())

    # ── Уведомление администраторам ─────────────────────────────────────────
    admin_text = (
        f"📬 <b>Новая заявка #{req.id}</b>\n\n"
        f"👤 Сотрудник: <b>{call.from_user.full_name}</b> (ID: {call.from_user.id})\n"
        f"📋 Тип: <b>{REQUEST_TYPE_LABELS[data['request_type']]}</b>\n"
        f"📅 Период: <b>{start.strftime('%d.%m.%Y')} — {end.strftime('%d.%m.%Y')}</b>\n"
        f"🔢 Дней: <b>{days}</b>\n"
        f"💬 Причина: <b>{data['reason']}</b>"
    )
    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, admin_text, reply_markup=admin_request_keyboard(req.id), parse_mode="HTML")
        except Exception as e:
            logger.warning("Не удалось уведомить администратора %s: %s", admin_id, e)

    await call.answer()


# ─── Отмена на шаге подтверждения ────────────────────────────────────────────
@router.callback_query(F.data == "cancel_request", RequestForm.confirming)
async def cancel_request(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("❌ Заявка отменена.")
    await call.message.answer("Главное меню:", reply_markup=user_main_menu())
    await call.answer()
