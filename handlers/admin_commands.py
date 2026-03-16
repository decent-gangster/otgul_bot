import csv
import io
import logging
from datetime import date

from aiogram import Router, F
from aiogram.types import Message, BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command

from handlers.admin_request import IsAdmin
from database.engine import AsyncSessionFactory
from database.crud import get_approved_requests_for_month, get_pending_requests
from database.models import User
from keyboards.menus import admin_main_menu
from keyboards.request_kb import admin_request_keyboard
from sqlalchemy import select

logger = logging.getLogger(__name__)
router = Router()
router.message.filter(IsAdmin())


# ─── /report — CSV-отчёт за текущий месяц ────────────────────────────────────
@router.message(Command("report"))
async def cmd_report(message: Message):
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
        "Тип", "Дата начала", "Дата окончания", "Дней",
        "Причина", "Комментарий администратора",
    ])

    for idx, (req, user) in enumerate(rows, start=1):
        days = (req.end_date - req.start_date).days + 1
        writer.writerow([
            idx,
            user.full_name,
            user.tg_id,
            req.type.value,
            req.start_date.strftime("%d.%m.%Y"),
            req.end_date.strftime("%d.%m.%Y"),
            days,
            req.reason or "—",
            req.admin_comment or "—",
        ])

    # BOM для корректного открытия в Excel
    csv_bytes = ("\ufeff" + output.getvalue()).encode("utf-8")
    filename = f"report_{month_names_gen[today.month]}_{today.year}.csv"

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
    async with AsyncSessionFactory() as session:
        rows = await get_pending_requests(session)

    if not rows:
        await message.answer(
            "✅ Новых заявок нет — все обработаны.",
            reply_markup=admin_main_menu(),
        )
        return

    await message.answer(
        f"📬 <b>Новые заявки на рассмотрении: {len(rows)}</b>\n\nНажмите кнопки под каждой заявкой:",
        parse_mode="HTML",
    )

    for req, user in rows:
        start = req.start_date.strftime("%d.%m.%Y")
        end = req.end_date.strftime("%d.%m.%Y")
        days = (req.end_date - req.start_date).days + 1
        text = (
            f"📋 <b>Заявка #{req.id}</b>\n"
            f"👤 {user.full_name}\n"
            f"🗂 {req.type.value} | {start} — {end} ({days} д.)\n"
            f"💬 {req.reason or '—'}"
        )
        await message.answer(text, reply_markup=admin_request_keyboard(req.id), parse_mode="HTML")


# ─── Управление сотрудниками ──────────────────────────────────────────────────
@router.message(F.text == "👥 Управление сотрудниками")
async def cmd_manage_employees(message: Message):
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
        f"👥 <b>Сотрудники ({len(users)}):</b>\n\n" + "\n\n".join(lines),
        parse_mode="HTML",
        reply_markup=admin_main_menu(),
    )
