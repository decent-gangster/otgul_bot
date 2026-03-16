from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from datetime import date

from keyboards.menus import user_main_menu
from database.engine import AsyncSessionFactory
from database.crud import get_or_create_user, get_user_month_days, get_requests_by_user

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message):
    async with AsyncSessionFactory() as session:
        user = await get_or_create_user(session, message.from_user.id, message.from_user.full_name)

    role_label = "👑 Администратор" if user.role == "admin" else "👤 Сотрудник"
    await message.answer(
        f"Привет, <b>{message.from_user.first_name}</b>! 👋\n\n"
        f"Роль: {role_label}\n"
        f"Я помогу управлять заявками на отгулы, отпуска и больничные.",
        reply_markup=user_main_menu(),
        parse_mode="HTML"
    )


@router.message(Command("balance"))
@router.message(F.text == "💰 Мой баланс")
async def cmd_balance(message: Message):
    today = date.today()

    async with AsyncSessionFactory() as session:
        user = await get_or_create_user(session, message.from_user.id, message.from_user.full_name)
        days_this_month = await get_user_month_days(session, user.id, today.year, today.month)
        all_requests = await get_requests_by_user(session, user.id)

    # Считаем статистику по всем заявкам
    approved = [r for r in all_requests if r.status == "approved"]
    pending  = [r for r in all_requests if r.status == "pending"]

    month_names = [
        "", "январе", "феврале", "марте", "апреле", "мае", "июне",
        "июле", "августе", "сентябре", "октябре", "ноябре", "декабре"
    ]

    await message.answer(
        f"💰 <b>Ваш баланс и статистика</b>\n\n"
        f"📅 Отгулов взято в {month_names[today.month]}: <b>{days_this_month} д.</b>\n"
        f"🏦 Остаток баланса: <b>{user.vacation_balance:.1f} д.</b>\n\n"
        f"📊 <b>Всего заявок:</b>\n"
        f"  ✅ Одобрено: {len(approved)}\n"
        f"  ⏳ На рассмотрении: {len(pending)}\n"
        f"  📝 Всего подано: {len(all_requests)}",
        parse_mode="HTML"
    )
