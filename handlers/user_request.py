import logging

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from datetime import date, datetime
import pytz

from states.request_states import RequestForm, OvertimeForm
from keyboards.calendar import build_calendar, CalendarCallback
from keyboards.request_kb import (
    request_type_keyboard, otgul_type_keyboard, hours_or_days_keyboard, time_keyboard, fmt_time,
    confirm_keyboard, RequestTypeCallback, TimeCallback, admin_request_keyboard,
    TIME_SLOTS,
)
from keyboards.menus import user_main_menu
from database.engine import AsyncSessionFactory
from database.crud import get_or_create_user, create_request, has_overtime_on_date, has_birthday_request_this_year
from database.models import RequestType

logger = logging.getLogger(__name__)
router = Router()

BISHKEK_TZ = pytz.timezone("Asia/Bishkek")


def _now_raw() -> str:
    """Текущее время в Asia/Bishkek в формате 'HHMM'."""
    now = datetime.now(BISHKEK_TZ)
    return f"{now.hour:02d}{now.minute:02d}"

REQUEST_TYPE_LABELS = {
    "отгул": "🗓 Отгул (свой счёт)",
    "отгул (с содержанием)": "🗓 Отгул (с содержанием)",
    "отпуск": "🌴 Отпуск",
    "больничный": "🏥 Больничный",
    "день рождения": "🎂 День рождения",
}


def _u(event) -> str:
    u = event.from_user
    return f"[id={u.id} name={u.full_name!r}]"


def format_duration(req_data: dict) -> str:
    """Возвращает строку длительности: '2 д.' или '3.5 ч.'"""
    if req_data.get("hours"):
        h = req_data["hours"]
        return f"{h:.0f} ч." if h == int(h) else f"{h:.1f} ч."
    start = date.fromisoformat(req_data["start_date"])
    end = date.fromisoformat(req_data["end_date"])
    return f"{(end - start).days + 1} д."


# ─── Шаг 1: Подать заявку ────────────────────────────────────────────────────
@router.message(F.text == "📝 Подать заявку")
async def start_request(message: Message, state: FSMContext):
    logger.info("📝 Подать заявку | шаг 1: выбор типа | %s", _u(message))
    await state.clear()
    await state.set_state(RequestForm.choosing_type)
    await message.answer("📋 <b>Выберите тип заявки:</b>", reply_markup=request_type_keyboard(), parse_mode="HTML")


# ─── Шаг 2: Выбор типа ───────────────────────────────────────────────────────
@router.callback_query(RequestTypeCallback.filter(), RequestForm.choosing_type)
async def choose_type(call: CallbackQuery, callback_data: RequestTypeCallback, state: FSMContext):
    req_type = callback_data.type_value
    logger.info("📝 шаг 2: тип=%s | %s", req_type, _u(call))
    await state.update_data(request_type=req_type, hours=None)

    if req_type == "отгул":
        await state.set_state(RequestForm.choosing_otgul_type)
        await call.message.edit_text(
            "✅ Тип: <b>🗓 Отгул</b>\n\n"
            "📌 <b>Выберите вид отгула:</b>",
            reply_markup=otgul_type_keyboard(),
            parse_mode="HTML",
        )
    elif req_type == "день рождения":
        today = date.today()
        async with AsyncSessionFactory() as session:
            user = await get_or_create_user(session, call.from_user.id, call.from_user.full_name)
            already_used = await has_birthday_request_this_year(session, user.id, today.year)

        if not user.birth_date:
            await call.answer("⚠️ Дата рождения не указана. Пройдите регистрацию через /start.", show_alert=True)
            return

        birthday_this_year = date(today.year, user.birth_date.month, user.birth_date.day)

        if birthday_this_year < today:
            await call.answer("⚠️ Ваш день рождения в этом году уже прошёл.", show_alert=True)
            return
        if birthday_this_year.weekday() >= 5:
            day_names = ["понедельник", "вторник", "среду", "четверг", "пятницу", "субботу", "воскресенье"]
            await call.answer(
                f"⚠️ Ваш день рождения выпадает на {day_names[birthday_this_year.weekday()]}. Отгул недоступен.",
                show_alert=True,
            )
            return
        if already_used:
            await call.answer("⚠️ Вы уже использовали отгул на день рождения в этом году.", show_alert=True)
            return

        await state.update_data(
            request_type="день рождения",
            start_date=birthday_this_year.isoformat(),
            end_date=birthday_this_year.isoformat(),
            hours=None,
        )
        await state.set_state(RequestForm.entering_reason)
        await call.message.edit_text(
            f"🎂 <b>Отгул на день рождения</b>\n\n"
            f"📅 Дата: <b>{birthday_this_year.strftime('%d.%m.%Y')}</b>\n\n"
            f"✏️ <b>Укажите причину</b> (или напишите «—»):",
            parse_mode="HTML",
        )
    else:
        await state.set_state(RequestForm.choosing_start_date)
        await call.message.edit_text(
            f"✅ Тип: <b>{REQUEST_TYPE_LABELS[req_type]}</b>\n\n"
            f"📅 <b>Выберите дату начала</b>:",
            reply_markup=build_calendar(),
            parse_mode="HTML",
        )
    await call.answer()


# ─── Шаг 2б: Вид отгула (за свой счёт / с содержанием) ──────────────────────
@router.callback_query(F.data == "otgul_own", RequestForm.choosing_otgul_type)
async def choose_otgul_own(call: CallbackQuery, state: FSMContext):
    logger.info("📝 шаг 2б: отгул за свой счёт | %s", _u(call))
    await state.update_data(request_type="отгул")
    await state.set_state(RequestForm.choosing_hours_or_days)
    await call.message.edit_text(
        "✅ Вид: <b>💸 За свой счёт</b>\n\n"
        "📌 <b>Как взять отгул?</b>",
        reply_markup=hours_or_days_keyboard(),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data == "otgul_paid", RequestForm.choosing_otgul_type)
async def choose_otgul_paid(call: CallbackQuery, state: FSMContext):
    logger.info("📝 шаг 2б: отгул с содержанием | %s", _u(call))
    await state.update_data(request_type="отгул (с содержанием)")
    await state.set_state(RequestForm.choosing_hours_or_days)
    await call.message.edit_text(
        "✅ Вид: <b>✅ С содержанием (отработка)</b>\n\n"
        "📌 <b>Как взять отгул?</b>",
        reply_markup=hours_or_days_keyboard(),
        parse_mode="HTML",
    )
    await call.answer()


# ─── Шаг 3а: Полный день или по часам (только для отгула) ────────────────────
@router.callback_query(F.data == "otgul_full_day", RequestForm.choosing_hours_or_days)
async def choose_full_day(call: CallbackQuery, state: FSMContext):
    logger.info("📝 шаг 3а: отгул полный день | %s", _u(call))
    await state.update_data(hours=None)
    await state.set_state(RequestForm.choosing_start_date)
    await call.message.edit_text(
        "✅ Тип: <b>🗓 Отгул — полный день</b>\n\n📅 <b>Выберите дату начала</b>:",
        reply_markup=build_calendar(),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data == "otgul_by_hours", RequestForm.choosing_hours_or_days)
async def choose_by_hours(call: CallbackQuery, state: FSMContext):
    logger.info("📝 шаг 3а: отгул по часам — выбор даты | %s", _u(call))
    await state.update_data(otgul_by_hours=True)
    await state.set_state(RequestForm.choosing_start_date)
    await call.message.edit_text(
        "✅ Тип: <b>⏱ Отгул по часам</b>\n\n"
        "📅 <b>Выберите дату отгула:</b>",
        reply_markup=build_calendar(),
        parse_mode="HTML",
    )
    await call.answer()


# ─── Шаг 3б: Выбор времени начала ────────────────────────────────────────────
@router.callback_query(TimeCallback.filter(), RequestForm.choosing_time_from)
async def choose_time_from(call: CallbackQuery, callback_data: TimeCallback, state: FSMContext):
    raw_from = callback_data.value          # "0800"
    time_from = fmt_time(raw_from)          # "08:00"
    logger.info("📝 шаг 3б: время начала=%s | %s", time_from, _u(call))
    data = await state.get_data()
    await state.update_data(time_from=time_from)

    # Для конечного времени: после начала И не в прошлом (если сегодня)
    start_date = date.fromisoformat(data["start_date"])
    min_raw = _now_raw() if start_date == date.today() else None
    after = max(raw_from, min_raw) if min_raw else raw_from

    await state.set_state(RequestForm.choosing_time_to)
    await call.message.edit_text(
        f"✅ Начало: <b>{time_from}</b>\n\n"
        f"🕕 <b>Выберите время окончания:</b>",
        reply_markup=time_keyboard(after=after),
        parse_mode="HTML",
    )
    await call.answer()


# ─── Шаг 3в: Выбор времени окончания ─────────────────────────────────────────
@router.callback_query(TimeCallback.filter(), RequestForm.choosing_time_to)
async def choose_time_to(call: CallbackQuery, callback_data: TimeCallback, state: FSMContext):
    raw_to = callback_data.value            # "1400"
    time_to = fmt_time(raw_to)              # "14:00"
    data = await state.get_data()
    time_from = data["time_from"]           # "08:00"

    from_h, from_m = map(int, time_from.split(":"))
    to_h, to_m = map(int, time_to.split(":"))
    hours = (to_h * 60 + to_m - from_h * 60 - from_m) / 60

    logger.info("📝 шаг 3в: время конца=%s, часов=%.1f | %s", time_to, hours, _u(call))
    await state.update_data(time_to=time_to, hours=hours)
    await state.set_state(RequestForm.entering_reason)
    await call.message.edit_text(
        f"✅ Время: <b>{time_from} — {time_to} ({hours:.1f} ч.)</b>\n\n"
        f"✏️ <b>Укажите причину</b> (или напишите «—»):",
        parse_mode="HTML",
    )
    await call.answer()


# ─── Шаг 4: Дата начала ──────────────────────────────────────────────────────
@router.callback_query(CalendarCallback.filter(F.action == "day"), RequestForm.choosing_start_date)
async def choose_start_date(call: CallbackQuery, callback_data: CalendarCallback, state: FSMContext):
    chosen = date(callback_data.year, callback_data.month, callback_data.day)
    if chosen < date.today():
        logger.warning("⚠ Попытка выбрать прошедшую дату %s | %s", chosen, _u(call))
        await call.answer("⚠️ Нельзя выбрать прошедшую дату!", show_alert=True)
        return
    if chosen.weekday() >= 5:
        await call.answer("⚠️ Нельзя брать отгул в выходной день!", show_alert=True)
        return

    data = await state.get_data()
    logger.info("📝 шаг 4: дата начала=%s | %s", chosen, _u(call))
    await state.update_data(start_date=chosen.isoformat(), end_date=chosen.isoformat())

    if data.get("otgul_by_hours"):
        # Для отгула по часам — показываем выбор времени (фильтруем если сегодня)
        min_raw = _now_raw() if chosen == date.today() else None
        available = [t for t in TIME_SLOTS if min_raw is None or t > min_raw]
        if not available:
            logger.warning("⚠ Сегодня рабочее время закончилось | %s", _u(call))
            await call.answer("⚠️ На сегодня рабочее время уже закончилось!", show_alert=True)
            return
        await state.set_state(RequestForm.choosing_time_from)
        await call.message.edit_text(
            f"✅ Дата: <b>{chosen.strftime('%d.%m.%Y')}</b>\n\n"
            f"🕐 <b>Выберите время начала:</b>",
            reply_markup=time_keyboard(after=min_raw, before="1730"),
            parse_mode="HTML",
        )
    else:
        await state.set_state(RequestForm.choosing_end_date)
        await call.message.edit_text(
            f"✅ Дата начала: <b>{chosen.strftime('%d.%m.%Y')}</b>\n\n"
            f"📅 <b>Выберите дату окончания</b>:",
            reply_markup=build_calendar(chosen.year, chosen.month),
            parse_mode="HTML",
        )
    await call.answer()


# ─── Навигация по календарю ───────────────────────────────────────────────────
@router.callback_query(
    CalendarCallback.filter(F.action.in_({"prev_month", "next_month"})),
    RequestForm.choosing_start_date,
)
@router.callback_query(
    CalendarCallback.filter(F.action.in_({"prev_month", "next_month"})),
    RequestForm.choosing_end_date,
)
@router.callback_query(
    CalendarCallback.filter(F.action.in_({"prev_month", "next_month"})),
    OvertimeForm.choosing_date,
)
async def navigate_calendar(call: CallbackQuery, callback_data: CalendarCallback):
    await call.message.edit_reply_markup(
        reply_markup=build_calendar(callback_data.year, callback_data.month)
    )
    await call.answer()


@router.callback_query(CalendarCallback.filter(F.action == "ignore"))
async def ignore_calendar(call: CallbackQuery):
    await call.answer()


# ─── Шаг 5: Дата окончания ───────────────────────────────────────────────────
@router.callback_query(CalendarCallback.filter(F.action == "day"), RequestForm.choosing_end_date)
async def choose_end_date(call: CallbackQuery, callback_data: CalendarCallback, state: FSMContext):
    data = await state.get_data()
    start = date.fromisoformat(data["start_date"])
    end = date(callback_data.year, callback_data.month, callback_data.day)

    if end < start:
        logger.warning("⚠ Дата конца %s < начала %s | %s", end, start, _u(call))
        await call.answer("⚠️ Дата окончания не может быть раньше даты начала!", show_alert=True)
        return
    if end.weekday() >= 5:
        await call.answer("⚠️ Нельзя указывать выходной день как дату окончания!", show_alert=True)
        return

    days = (end - start).days + 1
    logger.info("📝 шаг 5: дата конца=%s (%d д.) | %s", end, days, _u(call))
    await state.update_data(end_date=end.isoformat())
    await state.set_state(RequestForm.entering_reason)
    await call.message.edit_text(
        f"✅ Дата начала: <b>{start.strftime('%d.%m.%Y')}</b>\n"
        f"✅ Дата окончания: <b>{end.strftime('%d.%m.%Y')}</b>\n\n"
        f"✏️ <b>Укажите причину</b> (или напишите «—»):",
        parse_mode="HTML",
    )
    await call.answer()


# ─── Шаг 6: Причина ──────────────────────────────────────────────────────────
@router.message(RequestForm.entering_reason)
async def enter_reason(message: Message, state: FSMContext):
    reason = message.text.strip()
    logger.info("📝 шаг 6: причина=%r | %s", reason[:50], _u(message))
    await state.update_data(reason=reason)
    data = await state.get_data()

    start = date.fromisoformat(data["start_date"])
    end = date.fromisoformat(data["end_date"])
    duration = format_duration(data)
    type_label = REQUEST_TYPE_LABELS[data["request_type"]]

    summary = (
        f"📄 <b>Итог вашей заявки:</b>\n\n"
        f"📋 Тип: <b>{type_label}</b>\n"
        f"📅 Начало: <b>{start.strftime('%d.%m.%Y')}</b>\n"
    )
    if not data.get("hours"):
        summary += f"📅 Конец: <b>{end.strftime('%d.%m.%Y')}</b>\n"
    if data.get("time_from") and data.get("time_to"):
        summary += f"⏰ Время: <b>{data['time_from']} — {data['time_to']}</b>\n"
    summary += (
        f"🔢 Длительность: <b>{duration}</b>\n"
        f"💬 Причина: <b>{reason}</b>\n\n"
        f"Всё верно?"
    )
    await state.set_state(RequestForm.confirming)
    await message.answer(summary, reply_markup=confirm_keyboard(), parse_mode="HTML")


# ─── Шаг 7: Подтверждение ────────────────────────────────────────────────────
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
            hours=data.get("hours"),
            time_from=data.get("time_from"),
            time_to=data.get("time_to"),
            reason=data["reason"],
        )

    start = date.fromisoformat(data["start_date"])
    end = date.fromisoformat(data["end_date"])
    duration = format_duration(data)
    type_label = REQUEST_TYPE_LABELS[data["request_type"]]

    logger.info(
        "✅ Заявка #%d создана | тип=%s | %s — %s | %s | %s",
        req.id, data["request_type"], start, end, duration, _u(call)
    )

    await call.message.edit_text(
        f"✅ <b>Заявка #{req.id} отправлена на рассмотрение!</b>\n\n"
        f"Вы получите уведомление, когда администратор примет решение.",
        parse_mode="HTML",
    )
    await call.message.answer("Главное меню:", reply_markup=user_main_menu())

    # ── Уведомление администраторам ──────────────────────────────────────────
    admin_text = (
        f"📬 <b>Новая заявка #{req.id}</b>\n\n"
        f"👤 Сотрудник: <b>{user.full_name}</b> (ID: {call.from_user.id})\n"
        f"📋 Тип: <b>{type_label}</b>\n"
        f"📅 Дата: <b>{start.strftime('%d.%m.%Y')}"
    )
    if not data.get("hours"):
        admin_text += f" — {end.strftime('%d.%m.%Y')}"
    admin_text += f"</b>\n"
    if data.get("time_from") and data.get("time_to"):
        admin_text += f"⏰ Время: <b>{data['time_from']} — {data['time_to']}</b>\n"
    admin_text += (
        f"🔢 Длительность: <b>{duration}</b>\n"
        f"💬 Причина: <b>{data['reason']}</b>"
    )
    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, admin_text, reply_markup=admin_request_keyboard(req.id), parse_mode="HTML")
            logger.info("   уведомлен администратор id=%s о заявке #%d", admin_id, req.id)
        except Exception as e:
            logger.warning("   не удалось уведомить администратора id=%s: %s", admin_id, e)

    await call.answer()


# ─── Отмена ──────────────────────────────────────────────────────────────────
@router.callback_query(F.data == "cancel_request", RequestForm.confirming)
async def cancel_request(call: CallbackQuery, state: FSMContext):
    logger.info("❌ Заявка отменена | %s", _u(call))
    await state.clear()
    await call.message.edit_text("❌ Заявка отменена.")
    await call.message.answer("Главное меню:", reply_markup=user_main_menu())
    await call.answer()


# ══════════════════════════════════════════════════════════════════════════════
# ─── ПЕРЕРАБОТКА ─────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

@router.message(F.text == "🕐 Подать переработку")
async def start_overtime(message: Message, state: FSMContext):
    logger.info("🕐 Подать переработку | шаг 1: выбор даты | %s", _u(message))
    await state.clear()
    await state.set_state(OvertimeForm.choosing_date)
    await message.answer(
        "🕐 <b>Заявка на переработку</b>\n\n"
        "📅 <b>Выберите дату переработки:</b>",
        reply_markup=build_calendar(),
        parse_mode="HTML",
    )


@router.callback_query(CalendarCallback.filter(F.action == "day"), OvertimeForm.choosing_date)
async def overtime_choose_date(call: CallbackQuery, callback_data: CalendarCallback, state: FSMContext):
    chosen = date(callback_data.year, callback_data.month, callback_data.day)
    if chosen > date.today():
        await call.answer("⚠️ Нельзя подать переработку на будущую дату!", show_alert=True)
        return

    async with AsyncSessionFactory() as session:
        user = await get_or_create_user(session, call.from_user.id, call.from_user.full_name)
        duplicate = await has_overtime_on_date(session, user.id, chosen)
    if duplicate:
        logger.warning("⚠ Дубль переработки на дату %s | %s", chosen, _u(call))
        await call.answer("⚠️ У вас уже есть заявка на переработку за эту дату!", show_alert=True)
        return

    logger.info("🕐 шаг 2: дата переработки=%s | %s", chosen, _u(call))
    await state.update_data(overtime_date=chosen.isoformat())
    await state.set_state(OvertimeForm.entering_hours)
    await call.message.edit_text(
        f"✅ Дата: <b>{chosen.strftime('%d.%m.%Y')}</b>\n\n"
        f"⏱ <b>Сколько часов переработали?</b>\n"
        f"Введите число от 0.5 до 9 (например: 1, 1.5, 2):",
        parse_mode="HTML",
    )
    await call.answer()


@router.message(OvertimeForm.entering_hours)
async def overtime_enter_hours(message: Message, state: FSMContext):
    text = message.text.strip().replace(",", ".")
    try:
        hours = float(text)
        if not (0.5 <= hours <= 9):
            raise ValueError
    except ValueError:
        await message.answer("⚠️ Введите число от 0.5 до 9 (например: 1, 1.5, 2)")
        return
    logger.info("🕐 шаг 3: часов переработки=%.1f | %s", hours, _u(message))
    await state.update_data(overtime_hours=hours)
    await state.set_state(OvertimeForm.entering_reason)
    await message.answer(
        f"✅ Часов: <b>{hours:.1f} ч.</b>\n\n"
        f"✏️ <b>Укажите причину переработки</b> (или напишите «—»):",
        parse_mode="HTML",
    )


@router.message(OvertimeForm.entering_reason)
async def overtime_enter_reason(message: Message, state: FSMContext):
    reason = message.text.strip()
    logger.info("🕐 шаг 4: причина=%r | %s", reason[:50], _u(message))
    await state.update_data(overtime_reason=reason)
    data = await state.get_data()

    chosen = date.fromisoformat(data["overtime_date"])
    hours = data["overtime_hours"]
    h_str = f"{hours:.0f}" if hours == int(hours) else f"{hours:.1f}"

    summary = (
        f"📄 <b>Итог заявки на переработку:</b>\n\n"
        f"📅 Дата: <b>{chosen.strftime('%d.%m.%Y')}</b>\n"
        f"⏱ Длительность: <b>{h_str} ч.</b>\n"
        f"💬 Причина: <b>{reason}</b>\n\n"
        f"Всё верно?"
    )
    await state.set_state(OvertimeForm.confirming)
    await message.answer(summary, reply_markup=confirm_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "confirm_request", OvertimeForm.confirming)
async def overtime_confirm(call: CallbackQuery, state: FSMContext, bot: Bot, admin_ids: list[int]):
    data = await state.get_data()
    await state.clear()

    chosen = date.fromisoformat(data["overtime_date"])
    hours = data["overtime_hours"]
    h_str = f"{hours:.0f}" if hours == int(hours) else f"{hours:.1f}"

    async with AsyncSessionFactory() as session:
        user = await get_or_create_user(session, call.from_user.id, call.from_user.full_name)
        req = await create_request(
            session,
            user_id=user.id,
            start_date=chosen,
            end_date=chosen,
            type=RequestType.overtime,
            hours=hours,
            reason=data["overtime_reason"],
        )

    logger.info("✅ Переработка #%d создана | %.1f ч. | %s", req.id, hours, _u(call))

    await call.message.edit_text(
        f"✅ <b>Заявка на переработку #{req.id} отправлена!</b>\n\n"
        f"Вы получите уведомление, когда администратор примет решение.",
        parse_mode="HTML",
    )
    await call.message.answer("Главное меню:", reply_markup=user_main_menu())

    admin_text = (
        f"🕐 <b>Переработка #{req.id}</b>\n\n"
        f"👤 Сотрудник: <b>{user.full_name}</b> (ID: {call.from_user.id})\n"
        f"📅 Дата: <b>{chosen.strftime('%d.%m.%Y')}</b>\n"
        f"⏱ Длительность: <b>{h_str} ч.</b>\n"
        f"💬 Причина: <b>{data['overtime_reason']}</b>"
    )
    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, admin_text, reply_markup=admin_request_keyboard(req.id), parse_mode="HTML")
            logger.info("   уведомлен администратор id=%s о переработке #%d", admin_id, req.id)
        except Exception as e:
            logger.warning("   не удалось уведомить администратора id=%s: %s", admin_id, e)

    await call.answer()


@router.callback_query(F.data == "cancel_request", OvertimeForm.confirming)
async def overtime_cancel(call: CallbackQuery, state: FSMContext):
    logger.info("❌ Переработка отменена | %s", _u(call))
    await state.clear()
    await call.message.edit_text("❌ Заявка отменена.")
    await call.message.answer("Главное меню:", reply_markup=user_main_menu())
    await call.answer()
