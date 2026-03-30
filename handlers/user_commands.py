import logging

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from datetime import date, timedelta
import calendar

from keyboards.menus import user_main_menu, admin_main_menu
from keyboards.request_kb import (cancel_own_request_keyboard, cancel_confirm_keyboard,
                                   RequestCancelCallback, RequestCancelConfirmCallback,
                                   RequestCancelBackCallback, MonthNavCallback, month_nav_keyboard)
from database.engine import AsyncSessionFactory
from database.crud import (get_or_create_user, get_user_month_days, get_requests_by_user,
                           get_awaiting_work_requests, get_balance_log, get_absences_for_period)
from database.models import UserRole, RequestStatus, RequestType, TimeOffRequest
from utils.formatters import format_request_period, format_request_duration
from sqlalchemy import select

logger = logging.getLogger(__name__)
router = Router()

STATUS_LABELS = {
    RequestStatus.pending:       "⏳ На рассмотрении",
    RequestStatus.approved:      "✅ Одобрена",
    RequestStatus.rejected:      "❌ Отклонена",
    RequestStatus.awaiting_work: "🔄 Ожидает отработки",
    RequestStatus.revoked:       "🔄 Отозвана",
    RequestStatus.cancelled:     "🚫 Отменена вами",
}


def _u(message: Message) -> str:
    """Короткая строка для идентификации пользователя в логах."""
    u = message.from_user
    return f"[id={u.id} name={u.full_name!r}]"


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext, admin_ids: list[int]):
    from states.request_states import OnboardingForm
    logger.info("▶ /start | пользователь %s", _u(message))
    async with AsyncSessionFactory() as session:
        user = await get_or_create_user(session, message.from_user.id, message.from_user.full_name, username=message.from_user.username)

    if not user.birth_date:
        await state.set_state(OnboardingForm.entering_name)
        await message.answer(
            "👋 <b>Добро пожаловать!</b>\n\n"
            "Для начала работы введите ваше <b>ФИО</b> полностью:\n"
            "<i>Например: Иванов Иван Иванович</i>",
            parse_mode="HTML",
        )
        return

    is_admin = message.from_user.id in admin_ids or user.role == UserRole.admin
    if is_admin:
        role_label = "👑 Администратор"
        menu = admin_main_menu()
        logger.info("   роль: ADMIN | показано меню администратора | %s", _u(message))
    else:
        role_label = "👤 Сотрудник"
        menu = user_main_menu()
        logger.info("   роль: USER  | показано меню сотрудника | %s", _u(message))

    await message.answer(
        f"Привет, <b>{message.from_user.first_name}</b>! 👋\n\n"
        f"Роль: {role_label}\n"
        f"Я помогу управлять заявками на отгулы, отпуска и больничные.",
        reply_markup=menu,
        parse_mode="HTML",
    )


@router.message(Command("balance"))
@router.message(F.text == "💰 Мой баланс")
async def cmd_balance(message: Message):
    logger.info("💰 Баланс | %s", _u(message))
    today = date.today()

    async with AsyncSessionFactory() as session:
        user = await get_or_create_user(session, message.from_user.id, message.from_user.full_name, username=message.from_user.username)
        days_this_month = await get_user_month_days(session, user.id, today.year, today.month)
        all_requests = await get_requests_by_user(session, user.id)
        awaiting = await get_awaiting_work_requests(session, user.id)

    approved = [r for r in all_requests if r.status == RequestStatus.approved]
    pending  = [r for r in all_requests if r.status == RequestStatus.pending]

    logger.info(
        "   баланс=%.1f | отгулов в месяце=%d | одобрено=%d | pending=%d | %s",
        user.vacation_balance, days_this_month, len(approved), len(pending), _u(message)
    )

    month_names = [
        "", "январе", "феврале", "марте", "апреле", "мае", "июне",
        "июле", "августе", "сентябре", "октябре", "ноябре", "декабре",
    ]

    ot_hours = user.overtime_hours or 0
    ot_days = int(ot_hours // 9)
    ot_rem = ot_hours % 9
    if ot_rem == int(ot_rem):
        ot_rem_str = str(int(ot_rem))
    else:
        ot_rem_str = f"{ot_rem:.1f}"
    if ot_days > 0 and ot_rem > 0:
        overtime_str = f"{ot_days} д. {ot_rem_str} ч."
    elif ot_days > 0:
        overtime_str = f"{ot_days} д."
    else:
        overtime_str = f"{ot_rem_str} ч."

    # Блок долгов по отработке
    debt_block = ""
    if awaiting:
        total_debt = sum(r.debt_hours or 0 for r in awaiting)
        debt_lines = []
        for r in awaiting:
            from utils.formatters import format_request_period
            debt_lines.append(
                f"  • Заявка <b>#{r.id}</b> ({format_request_period(r)}): <b>{r.debt_hours:.1f} ч.</b>"
            )
        debt_block = (
            f"\n\n⚠️ <b>Долг по отработке: {total_debt:.1f} ч.</b>\n"
            + "\n".join(debt_lines)
        )

    await message.answer(
        f"💰 <b>Ваш баланс и статистика</b>\n\n"
        f"📅 Отгулов взято в {month_names[today.month]}: <b>{days_this_month} д.</b>\n"
        f"🏦 Остаток баланса: <b>{user.vacation_balance:.1f} д.</b>\n"
        f"🕐 Переработка: <b>{overtime_str}</b>"
        f"{debt_block}\n\n"
        f"📊 <b>Всего заявок:</b>\n"
        f"  ✅ Одобрено: {len(approved)}\n"
        f"  ⏳ На рассмотрении: {len(pending)}\n"
        f"  📝 Всего подано: {len(all_requests)}",
        parse_mode="HTML",
    )


@router.message(F.text == "📋 Мои заявки")
async def cmd_my_requests(message: Message):
    logger.info("📋 Мои заявки | %s", _u(message))
    async with AsyncSessionFactory() as session:
        user = await get_or_create_user(session, message.from_user.id, message.from_user.full_name, username=message.from_user.username)
        requests = await get_requests_by_user(session, user.id)

    logger.info("   найдено заявок: %d | %s", len(requests), _u(message))

    if not requests:
        await message.answer("У вас пока нет заявок. Нажмите «📝 Подать заявку».")
        return

    total = len(requests)
    await message.answer(
        f"📋 <b>Ваши заявки</b> (последние {min(total, 10)} из {total}):",
        parse_mode="HTML",
    )
    for req in requests[:10]:
        period = format_request_period(req)
        duration = format_request_duration(req)
        status = STATUS_LABELS.get(req.status, req.status)
        text = (
            f"<b>#{req.id}</b> | {req.type.value} | {period} ({duration})\n"
            f"   {status}"
        )
        kb = cancel_own_request_keyboard(req.id) if req.status == RequestStatus.pending else None
        await message.answer(text, reply_markup=kb, parse_mode="HTML")


# ─── Календарь отсутствий ────────────────────────────────────────────────────
_DAY_ABBR = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
_MONTHS_RU = [
    "", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]


def _fmt_absence_type(req) -> str:
    """Читаемое описание типа отсутствия с датами/временем."""
    s = req.start_date.strftime("%d.%m")
    e = req.end_date.strftime("%d.%m")
    date_range = s if s == e else f"{s}–{e}"

    if req.type == RequestType.vacation:
        return f"отпуск {date_range}"
    if req.type == RequestType.sick:
        return f"больничный {date_range}"
    suffix = "с сод." if req.type == RequestType.otgul_paid else "б/с"
    if req.time_from and req.time_to:
        return f"отгул {suffix} {s} {req.time_from}–{req.time_to}"
    return f"отгул {suffix} {date_range}"


async def _build_month_text(offset: int) -> str:
    today = date.today()
    # Вычисляем целевой месяц через смещение
    month = today.month + offset
    year = today.year + (month - 1) // 12
    month = ((month - 1) % 12) + 1

    first_day = date(year, month, 1)
    last_day = date(year, month, calendar.monthrange(year, month)[1])

    async with AsyncSessionFactory() as session:
        rows = await get_absences_for_period(session, first_day, last_day)

    header = f"📅 <b>{_MONTHS_RU[month]} {year}</b>\n"

    # Группируем по дням
    day_map: dict[date, list[str]] = {}
    for req, user in rows:
        cur = max(req.start_date, first_day)
        while cur <= min(req.end_date, last_day):
            label = f"{user.full_name} <i>({_fmt_absence_type(req)})</i>"
            day_map.setdefault(cur, []).append(label)
            cur += timedelta(days=1)

    if not day_map:
        return header + "\nВ этом месяце отсутствий нет."

    lines = [header]
    for d in sorted(day_map):
        dow = _DAY_ABBR[d.weekday()]
        lines.append(f"<b>{d.strftime('%d.%m')} ({dow}):</b> {', '.join(day_map[d])}")

    return "\n".join(lines)


@router.message(F.text == "📅 Календарь отсутствий")
async def cmd_absence_calendar(message: Message):
    logger.info("📅 Календарь отсутствий | %s", _u(message))
    text = await _build_month_text(offset=0)
    await message.answer(text, reply_markup=month_nav_keyboard(0), parse_mode="HTML")


@router.callback_query(MonthNavCallback.filter())
async def navigate_month(call: CallbackQuery, callback_data: MonthNavCallback):
    text = await _build_month_text(offset=callback_data.offset)
    await call.message.edit_text(text, reply_markup=month_nav_keyboard(callback_data.offset), parse_mode="HTML")
    await call.answer()


# ─── История баланса ─────────────────────────────────────────────────────────
@router.message(F.text == "📊 История баланса")
async def cmd_balance_log(message: Message):
    logger.info("📊 История баланса | %s", _u(message))
    async with AsyncSessionFactory() as session:
        user = await get_or_create_user(session, message.from_user.id, message.from_user.full_name, username=message.from_user.username)
        log = await get_balance_log(session, user.id)

    if not log:
        await message.answer(
            "📊 <b>История баланса</b>\n\nОпераций пока нет.",
            parse_mode="HTML",
        )
        return

    lines = []
    for entry in log:
        if entry.change > 0:
            icon, sign = "📈", "+"
        else:
            icon, sign = "📉", ""
        h = entry.change
        h_str = f"{h:.0f}" if h == int(h) else f"{h:.1f}"
        lines.append(
            f"{icon} <b>{sign}{h_str} ч.</b> — {entry.description}\n"
            f"   🕐 {entry.created_at}"
        )

    await message.answer(
        f"📊 <b>История баланса</b> (последние {len(log)} операций):\n\n" + "\n\n".join(lines),
        parse_mode="HTML",
    )


# ─── Отмена своей заявки (шаг 1: подтверждение) ──────────────────────────────
@router.callback_query(RequestCancelCallback.filter())
async def cancel_request_ask(call: CallbackQuery, callback_data: RequestCancelCallback):
    request_id = callback_data.request_id
    logger.info("❌ Запрос на отмену заявки #%d | %s", request_id, _u(call))
    await call.message.edit_reply_markup(
        reply_markup=cancel_confirm_keyboard(request_id)
    )
    await call.answer()


# ─── Отмена своей заявки (шаг 2: подтверждено) ───────────────────────────────
@router.callback_query(RequestCancelConfirmCallback.filter())
async def cancel_request_confirm(call: CallbackQuery, callback_data: RequestCancelConfirmCallback, bot: Bot, admin_ids: list[int]):
    request_id = callback_data.request_id
    logger.info("❌ Подтверждена отмена заявки #%d | %s", request_id, _u(call))

    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(TimeOffRequest).where(TimeOffRequest.id == request_id)
        )
        req = result.scalar_one_or_none()

        if not req:
            await call.answer("⚠️ Заявка не найдена!", show_alert=True)
            return
        if req.status != RequestStatus.pending:
            await call.answer("ℹ️ Заявку уже нельзя отменить — она обработана.", show_alert=True)
            return

        req.status = RequestStatus.cancelled
        await session.commit()

    await call.message.edit_text(
        call.message.text + "\n\n🚫 <b>Отменена вами</b>",
        parse_mode="HTML",
    )

    for admin_id in admin_ids:
        try:
            await bot.send_message(
                admin_id,
                f"🚫 <b>Заявка #{request_id} отменена сотрудником</b>\n\n"
                f"👤 {call.from_user.full_name}",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning("   не удалось уведомить админа id=%s: %s", admin_id, e)

    await call.answer("Заявка отменена")


# ─── Назад (вернуть кнопку «Отменить заявку») ────────────────────────────────
@router.callback_query(RequestCancelBackCallback.filter())
async def cancel_back(call: CallbackQuery, callback_data: RequestCancelBackCallback):
    await call.message.edit_reply_markup(
        reply_markup=cancel_own_request_keyboard(callback_data.request_id)
    )
    await call.answer()


@router.message(F.text == "🔙 Назад")
async def cmd_back(message: Message, admin_ids: list[int]):
    logger.info("🔙 Назад | %s", _u(message))
    async with AsyncSessionFactory() as session:
        user = await get_or_create_user(session, message.from_user.id, message.from_user.full_name, username=message.from_user.username)

    is_admin = message.from_user.id in admin_ids or user.role == UserRole.admin
    menu = admin_main_menu() if is_admin else user_main_menu()
    await message.answer("Главное меню:", reply_markup=menu)
