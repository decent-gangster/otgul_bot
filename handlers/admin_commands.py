import csv
import io
import logging
from datetime import date

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command

from handlers.admin_request import IsAdmin
from database.engine import AsyncSessionFactory
from database.crud import (get_approved_requests_for_month, get_pending_requests,
                           get_user_by_tg_id, get_all_approved_requests)
from database.models import User, UserRole, RequestStatus, RequestType
from keyboards.menus import admin_main_menu
from keyboards.request_kb import admin_request_keyboard, revoke_request_keyboard, RequestRevokeCallback
from sqlalchemy import select as sa_select
from utils.formatters import format_request_period, format_request_duration
from sqlalchemy import select
from database.crud import add_overtime_hours, deduct_overtime_hours, add_balance_log
from database.models import TimeOffRequest

logger = logging.getLogger(__name__)
router = Router()
router.message.filter(IsAdmin())


# ─── /report — CSV-отчёт за текущий месяц ────────────────────────────────────
def _a(message: Message) -> str:
    u = message.from_user
    return f"[admin id={u.id} name={u.full_name!r}]"


@router.message(Command("report"))
async def cmd_report(message: Message):
    logger.info("📊 /report | %s", _a(message))
    today = date.today()

    async with AsyncSessionFactory() as session:
        rows = await get_approved_requests_for_month(session, today.year, today.month)

    month_names_prep = [
        "", "январе", "феврале", "марте", "апреле", "мае", "июне",
        "июле", "августе", "сентябре", "октябре", "ноябре", "декабре",
    ]
    month_names_gen = [
        "", "январь", "февраль", "март", "апрель", "май", "июнь",
        "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
    ]

    if not rows:
        await message.answer(
            f"📭 В {month_names_prep[today.month]} нет одобренных заявок.",
            reply_markup=admin_main_menu(),
        )
        return

    # ── Генерация CSV в памяти ────────────────────────────────────────────────
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
            idx,
            user.full_name,
            user.tg_id,
            req.type.value,
            req.start_date.strftime("%d.%m.%Y"),
            req.end_date.strftime("%d.%m.%Y"),
            days,
            f"{req.hours:.1f}" if req.hours else "—",
            req.reason or "—",
            req.admin_comment or "—",
        ])

    # BOM для корректного открытия в Excel
    csv_bytes = ("\ufeff" + output.getvalue()).encode("utf-8")
    filename = f"report_{month_names_gen[today.month]}_{today.year}.csv"

    logger.info("   сгенерирован отчёт: %d заявок, файл=%s | %s", len(rows), filename, _a(message))
    await message.answer_document(
        document=BufferedInputFile(csv_bytes, filename=filename),
        caption=(
            f"📊 <b>Отчёт за {month_names_gen[today.month]} {today.year}</b>\n"
            f"Одобренных заявок: <b>{len(rows)}</b>"
        ),
        parse_mode="HTML",
    )


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

    admin_name = f"@{call.from_user.username}" if call.from_user.username else call.from_user.full_name
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
