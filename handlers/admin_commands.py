import csv
import io
import logging
from datetime import date

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from handlers.admin_request import IsAdmin
from database.engine import AsyncSessionFactory
from database.crud import (get_approved_requests_for_month, get_approved_requests_for_period,
                           get_pending_requests, get_user_by_tg_id, get_all_approved_requests,
                           add_overtime_hours, deduct_overtime_hours, add_balance_log,
                           get_all_users_balance_stats, get_monthly_type_stats, get_otgul_top,
                           add_admin_log, get_admin_log)
from database.models import User, UserRole, RequestStatus, RequestType, TimeOffRequest
from keyboards.menus import admin_main_menu
from keyboards.request_kb import (admin_request_keyboard, revoke_request_keyboard,
                                  RequestRevokeCallback, ReportPeriodCallback, report_period_keyboard,
                                  StatsNavCallback, stats_nav_keyboard)
from sqlalchemy import select as sa_select
from sqlalchemy import select
import calendar as cal
from utils.formatters import format_request_period, format_request_duration
from states.request_states import ReportForm

logger = logging.getLogger(__name__)
router = Router()
router.message.filter(IsAdmin())


def _a(message: Message) -> str:
    u = message.from_user
    return f"[admin id={u.id} name={u.full_name!r}]"


async def _send_report(target: Message, rows: list, start: date, end: date) -> None:
    """Генерирует и отправляет CSV-отчёт за указанный период."""
    period_str = f"{start.strftime('%d.%m.%Y')}–{end.strftime('%d.%m.%Y')}"

    if not rows:
        await target.answer(f"📭 За период {period_str} нет одобренных заявок.")
        return

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_ALL)
    writer.writerow([
        "№", "Сотрудник", "Telegram ID",
        "Тип", "Дата начала", "Дата окончания", "Дней", "Часов",
        "Причина", "Комментарий администратора",
    ])
    for idx, (req, user) in enumerate(rows, start=1):
        days = (req.end_date - req.start_date).days + 1 if not req.hours else "—"
        writer.writerow([
            idx, user.full_name, user.tg_id, req.type.value,
            req.start_date.strftime("%d.%m.%Y"), req.end_date.strftime("%d.%m.%Y"),
            days, f"{req.hours:.1f}" if req.hours else "—",
            req.reason or "—", req.admin_comment or "—",
        ])

    csv_bytes = ("\ufeff" + output.getvalue()).encode("utf-8")
    filename = f"report_{start.strftime('%d.%m.%Y')}-{end.strftime('%d.%m.%Y')}.csv"

    await target.answer_document(
        document=BufferedInputFile(csv_bytes, filename=filename),
        caption=(
            f"📊 <b>Отчёт за {period_str}</b>\n"
            f"Одобренных заявок: <b>{len(rows)}</b>"
        ),
        parse_mode="HTML",
    )


# ─── Кнопка «📊 Отчёт» ────────────────────────────────────────────────────────
@router.message(F.text == "📊 Отчёт")
async def cmd_report_menu(message: Message, state: FSMContext):
    logger.info("📊 Отчёт | %s", _a(message))
    await state.clear()
    await message.answer(
        "📊 <b>Отчёт по заявкам</b>\n\nВыберите период:",
        reply_markup=report_period_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(ReportPeriodCallback.filter(F.period == "current"))
async def report_current_month(call: CallbackQuery):
    today = date.today()
    start = date(today.year, today.month, 1)
    import calendar as cal
    end = date(today.year, today.month, cal.monthrange(today.year, today.month)[1])
    logger.info("📊 Отчёт: текущий месяц %s–%s | admin id=%d", start, end, call.from_user.id)
    async with AsyncSessionFactory() as session:
        rows = await get_approved_requests_for_period(session, start, end)
    await call.message.delete()
    await _send_report(call.message, rows, start, end)
    await call.answer()


@router.callback_query(ReportPeriodCallback.filter(F.period == "previous"))
async def report_previous_month(call: CallbackQuery):
    today = date.today()
    import calendar as cal
    prev_month = today.month - 1 or 12
    prev_year = today.year if today.month > 1 else today.year - 1
    start = date(prev_year, prev_month, 1)
    end = date(prev_year, prev_month, cal.monthrange(prev_year, prev_month)[1])
    logger.info("📊 Отчёт: прошлый месяц %s–%s | admin id=%d", start, end, call.from_user.id)
    async with AsyncSessionFactory() as session:
        rows = await get_approved_requests_for_period(session, start, end)
    await call.message.delete()
    await _send_report(call.message, rows, start, end)
    await call.answer()


@router.callback_query(ReportPeriodCallback.filter(F.period == "custom"))
async def report_custom_ask(call: CallbackQuery, state: FSMContext):
    logger.info("📊 Отчёт: произвольный период | admin id=%d", call.from_user.id)
    await state.set_state(ReportForm.entering_period)
    await call.message.edit_text(
        "✏️ Введите период в формате:\n"
        "<code>ДД.ММ.ГГГГ-ДД.ММ.ГГГГ</code>\n\n"
        "<i>Например: 01.03.2026-31.03.2026</i>",
        parse_mode="HTML",
    )
    await call.answer()


@router.message(ReportForm.entering_period)
async def report_custom_generate(message: Message, state: FSMContext):
    text = message.text.strip().replace(" ", "")
    try:
        parts = text.split("-")
        # формат ДД.ММ.ГГГГ содержит точки, поэтому split по "-" даст 2 части
        # но ДД.ММ.ГГГГ-ДД.ММ.ГГГГ → split("-") даст ["ДД.ММ.ГГГГ", "ДД.ММ.ГГГГ"]
        if len(parts) != 2:
            raise ValueError
        start = date(int(parts[0][6:10]), int(parts[0][3:5]), int(parts[0][0:2]))
        end   = date(int(parts[1][6:10]), int(parts[1][3:5]), int(parts[1][0:2]))
        if end < start:
            raise ValueError
    except (ValueError, IndexError):
        await message.answer(
            "⚠️ Неверный формат. Введите период как:\n"
            "<code>01.03.2026-31.03.2026</code>",
            parse_mode="HTML",
        )
        return

    await state.clear()
    logger.info("📊 Отчёт: период %s–%s | admin id=%d", start, end, message.from_user.id)
    async with AsyncSessionFactory() as session:
        rows = await get_approved_requests_for_period(session, start, end)
    await _send_report(message, rows, start, end)


# ─── Статистика ──────────────────────────────────────────────────────────────
_MONTHS_RU = [
    "", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]
_TYPE_LABELS = {
    RequestType.otgul:       "🗓 Отгул (б/с)",
    RequestType.otgul_paid:  "🗓 Отгул (с сод.)",
    RequestType.vacation:    "🏖 Отпуск",
    RequestType.sick:        "🏥 Больничный",
    RequestType.overtime:    "⏱ Переработка",
}


async def _build_stats_text(offset: int) -> str:
    today = date.today()
    month = ((today.month - 1 + offset) % 12) + 1
    year = today.year + (today.month - 1 + offset) // 12

    async with AsyncSessionFactory() as session:
        type_counts = await get_monthly_type_stats(session, year, month)
        top_month = await get_otgul_top(session, year, month=month)
        top_year = await get_otgul_top(session, year)

    total = sum(type_counts.values())
    header = f"📈 <b>Статистика — {_MONTHS_RU[month]} {year}</b>\n"

    # Разбивка по типам
    if total == 0:
        type_block = "\nЗаявок в этом месяце нет."
    else:
        lines = []
        for req_type, label in _TYPE_LABELS.items():
            cnt = type_counts.get(req_type, 0)
            if cnt:
                pct = cnt / total * 100
                lines.append(f"  {label}: <b>{cnt}</b> ({pct:.0f}%)")
        lines.append(f"\n  Итого: <b>{total}</b> заявок")
        type_block = "\n" + "\n".join(lines)

    # Топ за месяц
    if top_month:
        month_top_lines = [f"  {i+1}. {name} — <b>{cnt}</b>" for i, (name, cnt) in enumerate(top_month)]
        month_top_block = "\n\n🏆 <b>Топ по отгулам за месяц:</b>\n" + "\n".join(month_top_lines)
    else:
        month_top_block = "\n\n🏆 <b>Топ по отгулам за месяц:</b>\n  Нет данных"

    # Топ за год
    if top_year:
        year_top_lines = [f"  {i+1}. {name} — <b>{cnt}</b>" for i, (name, cnt) in enumerate(top_year)]
        year_top_block = f"\n\n🥇 <b>Топ по отгулам за {year} год:</b>\n" + "\n".join(year_top_lines)
    else:
        year_top_block = f"\n\n🥇 <b>Топ по отгулам за {year} год:</b>\n  Нет данных"

    return header + type_block + month_top_block + year_top_block


@router.message(F.text == "📈 Статистика")
async def cmd_stats(message: Message):
    logger.info("📈 Статистика | %s", _a(message))
    text = await _build_stats_text(offset=0)
    await message.answer(text, reply_markup=stats_nav_keyboard(0), parse_mode="HTML")


@router.callback_query(StatsNavCallback.filter())
async def navigate_stats(call: CallbackQuery, callback_data: StatsNavCallback):
    text = await _build_stats_text(offset=callback_data.offset)
    await call.message.edit_text(text, reply_markup=stats_nav_keyboard(callback_data.offset), parse_mode="HTML")
    await call.answer()


# ─── Список новых заявок ─────────────────────────────────────────────────────
@router.message(F.text == "📬 Список новых заявок")
async def cmd_pending_requests(message: Message):
    logger.info("📬 Список новых заявок | %s", _a(message))
    async with AsyncSessionFactory() as session:
        rows = await get_pending_requests(session)

    if not rows:
        logger.info("   нет pending-заявок | %s", _a(message))
        await message.answer(
            "✅ Новых заявок нет — все обработаны.",
            reply_markup=admin_main_menu(),
        )
        return

    logger.info("   найдено pending-заявок: %d | %s", len(rows), _a(message))
    await message.answer(
        f"📬 <b>Новые заявки на рассмотрении: {len(rows)}</b>\n\nНажмите кнопки под каждой заявкой:",
        parse_mode="HTML",
    )

    for req, user in rows:
        period = format_request_period(req)
        duration = format_request_duration(req)
        text = (
            f"📋 <b>Заявка #{req.id}</b>\n"
            f"👤 {user.full_name}\n"
            f"🗂 {req.type.value} | {period} ({duration})\n"
            f"💬 {req.reason or '—'}"
        )
        await message.answer(text, reply_markup=admin_request_keyboard(req.id), parse_mode="HTML")


# ─── /adminlog — лог действий администратора ─────────────────────────────────
_ACTION_LABELS = {
    "approved":          "✅ Одобрил",
    "approved_awaiting": "✅ Одобрил (ожид. отработки)",
    "rejected":          "❌ Отклонил",
    "revoked":           "🔄 Отозвал",
}


@router.message(Command("adminlog"))
async def cmd_adminlog(message: Message):
    logger.info("/adminlog | %s", _a(message))
    async with AsyncSessionFactory() as session:
        entries = await get_admin_log(session, limit=30)

    if not entries:
        await message.answer("📋 Лог действий пуст.")
        return

    lines = []
    for e in entries:
        action_label = _ACTION_LABELS.get(e.action, e.action)
        req_ref = f" заявка #{e.request_id}" if e.request_id else ""
        detail = f"\n   💬 {e.details}" if e.details else ""
        lines.append(
            f"<b>{e.created_at}</b> {e.admin_name}\n"
            f"   {action_label}{req_ref} — {e.employee_name}{detail}"
        )

    await message.answer(
        f"📋 <b>Лог действий (последние {len(entries)}):</b>\n\n" + "\n\n".join(lines),
        parse_mode="HTML",
    )


# ─── Балансы сотрудников ──────────────────────────────────────────────────────
@router.message(F.text == "💼 Балансы сотрудников")
async def cmd_employees_balances(message: Message):
    logger.info("💼 Балансы сотрудников | %s", _a(message))
    async with AsyncSessionFactory() as session:
        stats = await get_all_users_balance_stats(session)

    if not stats:
        await message.answer("В базе данных ещё нет сотрудников.")
        return

    lines = []
    for user, otgul_days, vacation_days, debt_hours in stats:
        role_icon = "👑" if user.role == "admin" else "👤"
        otgul_str = f"{otgul_days:.1f}".rstrip("0").rstrip(".")
        parts = [
            f"⏱ Переработка: <b>{user.overtime_hours:.1f} ч.</b>",
            f"🗓 Отгулов взято: <b>{otgul_str} д.</b>",
            f"📅 Отпусков взято: <b>{vacation_days} д.</b>",
        ]
        if debt_hours > 0:
            parts.append(f"⚠️ Долг к отработке: <b>{debt_hours:.1f} ч.</b>")
        lines.append(f"{role_icon} <b>{user.full_name}</b>\n" + "\n".join(f"   {p}" for p in parts))

    await message.answer(
        f"💼 <b>Балансы сотрудников ({len(stats)}):</b>\n\n" + "\n\n".join(lines),
        parse_mode="HTML",
    )


# ─── Управление сотрудниками ──────────────────────────────────────────────────
@router.message(F.text == "👥 Управление сотрудниками")
async def cmd_manage_employees(message: Message):
    logger.info("👥 Управление сотрудниками | %s", _a(message))
    async with AsyncSessionFactory() as session:
        result = await session.execute(select(User).order_by(User.full_name))
        users = result.scalars().all()

    if not users:
        await message.answer("В базе данных ещё нет сотрудников.")
        return

    lines = []
    for user in users:
        role_icon = "👑" if user.role == "admin" else "👤"
        lines.append(
            f"{role_icon} <b>{user.full_name}</b>\n"
            f"   ID: <code>{user.tg_id}</code> | Баланс: {user.vacation_balance:.1f} д."
        )

    await message.answer(
        f"👥 <b>Сотрудники ({len(users)}):</b>\n\n" + "\n\n".join(lines) +
        "\n\n💡 Чтобы назначить администратора:\n<code>/make_admin &lt;tg_id&gt;</code>\n"
        "Чтобы снять права:\n<code>/remove_admin &lt;tg_id&gt;</code>",
        parse_mode="HTML",
        reply_markup=admin_main_menu(),
    )


# ─── /make_admin — назначить администратора ───────────────────────────────────
@router.message(Command("make_admin"))
async def cmd_make_admin(message: Message):
    args = message.text.split()
    if len(args) != 2 or not args[1].isdigit():
        await message.answer("Использование: <code>/make_admin &lt;tg_id&gt;</code>", parse_mode="HTML")
        return

    tg_id = int(args[1])
    async with AsyncSessionFactory() as session:
        user = await get_user_by_tg_id(session, tg_id)
        if not user:
            await message.answer(f"❌ Пользователь с ID <code>{tg_id}</code> не найден.\nОн должен сначала написать боту /start.", parse_mode="HTML")
            return
        if user.role == UserRole.admin:
            await message.answer(f"ℹ️ <b>{user.full_name}</b> уже является администратором.", parse_mode="HTML")
            return
        user.role = UserRole.admin
        await session.commit()
        logger.info("👑 /make_admin: пользователь id=%d %r назначен администратором | %s", tg_id, user.full_name, _a(message))

    await message.answer(
        f"✅ <b>{user.full_name}</b> назначен администратором.",
        parse_mode="HTML",
    )


# ─── /remove_admin — снять права администратора ───────────────────────────────
@router.message(Command("remove_admin"))
async def cmd_remove_admin(message: Message):
    args = message.text.split()
    if len(args) != 2 or not args[1].isdigit():
        await message.answer("Использование: <code>/remove_admin &lt;tg_id&gt;</code>", parse_mode="HTML")
        return

    tg_id = int(args[1])
    if tg_id == message.from_user.id:
        await message.answer("❌ Нельзя снять права у самого себя.", parse_mode="HTML")
        return

    async with AsyncSessionFactory() as session:
        user = await get_user_by_tg_id(session, tg_id)
        if not user:
            await message.answer(f"❌ Пользователь с ID <code>{tg_id}</code> не найден.", parse_mode="HTML")
            return
        if user.role != UserRole.admin:
            await message.answer(f"ℹ️ <b>{user.full_name}</b> не является администратором.", parse_mode="HTML")
            return
        user.role = UserRole.user
        await session.commit()
        logger.info("🔻 /remove_admin: права сняты у id=%d %r | %s", tg_id, user.full_name, _a(message))

    await message.answer(
        f"✅ Права администратора у <b>{user.full_name}</b> сняты.",
        parse_mode="HTML",
    )


# ─── Одобренные заявки ────────────────────────────────────────────────────────
@router.message(F.text == "✅ Одобренные заявки")
async def cmd_approved_requests(message: Message):
    logger.info("✅ Одобренные заявки | %s", _a(message))
    async with AsyncSessionFactory() as session:
        rows = await get_all_approved_requests(session)

    if not rows:
        await message.answer("📭 Одобренных заявок нет.", reply_markup=admin_main_menu())
        return

    await message.answer(f"✅ <b>Одобренные заявки ({len(rows)}):</b>\n\nНажмите «Отозвать» для отмены:", parse_mode="HTML")
    for req, user in rows:
        period = format_request_period(req)
        duration = format_request_duration(req)
        status_label = "🔄 Ожидает отработки" if req.status.value == "awaiting_work" else "✅ Одобрена"
        text = (
            f"📋 <b>Заявка #{req.id}</b>\n"
            f"👤 {user.full_name}\n"
            f"🗂 {req.type.value} | {period} ({duration})\n"
            f"💬 {req.reason or '—'}\n"
            f"Статус: {status_label}"
        )
        await message.answer(text, reply_markup=revoke_request_keyboard(req.id), parse_mode="HTML")


# ─── Отозвать заявку ──────────────────────────────────────────────────────────
@router.callback_query(RequestRevokeCallback.filter())
async def revoke_request(call: CallbackQuery, callback_data: RequestRevokeCallback, bot: Bot):
    request_id = callback_data.request_id
    logger.info("🔄 Отозвать заявку #%d | admin id=%d", request_id, call.from_user.id)

    async with AsyncSessionFactory() as session:
        result = await session.execute(
            sa_select(TimeOffRequest, User)
            .join(User, TimeOffRequest.user_id == User.id)
            .where(TimeOffRequest.id == request_id)
        )
        row = result.one_or_none()
        if not row:
            await call.answer("⚠️ Заявка не найдена!", show_alert=True)
            return

        req, user = row

        if req.status not in (RequestStatus.approved, RequestStatus.awaiting_work):
            await call.answer("ℹ️ Заявка уже не активна.", show_alert=True)
            return

        # Обратное начисление/списание баланса
        if req.type == RequestType.overtime and req.hours:
            await deduct_overtime_hours(session, req.user_id, req.hours)
            await add_balance_log(session, req.user_id, -req.hours,
                f"Переработка отозвана (заявка #{req.id})", req.id)
            logger.info("   отнято %.1f ч. переработки у пользователя id=%d", req.hours, user.tg_id)
        elif req.type == RequestType.otgul_paid and req.status == RequestStatus.approved:
            hours_paid = req.hours if req.hours else ((req.end_date - req.start_date).days + 1) * 9
            debt = req.debt_hours or 0
            actually_deducted = hours_paid - debt
            if actually_deducted > 0:
                await add_overtime_hours(session, req.user_id, actually_deducted)
                await add_balance_log(session, req.user_id, +actually_deducted,
                    f"Отгул с отработкой отозван (заявка #{req.id})", req.id)
                logger.info("   возвращено %.1f ч. переработки пользователю id=%d", actually_deducted, user.tg_id)

        req.status = RequestStatus.revoked
        await session.commit()
        admin_name_log = f"@{call.from_user.username}" if call.from_user.username else call.from_user.full_name
        logger.info("🔄 Заявка #%d отозвана | сотрудник %r | admin %s", req.id, user.full_name, admin_name_log)
        await add_admin_log(session, call.from_user.id, admin_name_log, "revoked",
                            user.full_name, req.id, req.type.value)

    admin_name = admin_name_log
    await call.message.edit_text(
        call.message.text + f"\n\n🔄 <b>Отозвано</b> администратором {admin_name}",
        parse_mode="HTML",
    )

    try:
        await bot.send_message(
            user.tg_id,
            f"🔄 <b>Ваша заявка #{req.id} была отозвана администратором.</b>\n\n"
            f"📋 Тип: <b>{req.type.value}</b>\n"
            f"📅 Период: <b>{format_request_period(req)}</b>",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning("   не удалось уведомить пользователя id=%d: %s", user.tg_id, e)

    await call.answer("✅ Заявка отозвана")
