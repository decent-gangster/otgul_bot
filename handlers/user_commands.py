from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from datetime import date

from keyboards.menus import user_main_menu, admin_main_menu
from database.engine import AsyncSessionFactory
from database.crud import get_or_create_user, get_user_month_days, get_requests_by_user
from database.models import UserRole, RequestStatus

router = Router()

STATUS_LABELS = {
    RequestStatus.pending:  "⏳ На рассмотрении",
    RequestStatus.approved: "✅ Одобрена",
    RequestStatus.rejected: "❌ Отклонена",
}


@router.message(Command("start"))
async def cmd_start(message: Message):
    async with AsyncSessionFactory() as session:
        user = await get_or_create_user(session, message.from_user.id, message.from_user.full_name)

    if user.role == UserRole.admin:
        role_label = "👑 Администратор"
        menu = admin_main_menu()
    else:
        role_label = "👤 Сотрудник"
        menu = user_main_menu()

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
    today = date.today()

    async with AsyncSessionFactory() as session:
        user = await get_or_create_user(session, message.from_user.id, message.from_user.full_name)
        days_this_month = await get_user_month_days(session, user.id, today.year, today.month)
        all_requests = await get_requests_by_user(session, user.id)

    approved = [r for r in all_requests if r.status == RequestStatus.approved]
    pending  = [r for r in all_requests if r.status == RequestStatus.pending]

    month_names = [
        "", "январе", "феврале", "марте", "апреле", "мае", "июне",
        "июле", "августе", "сентябре", "октябре", "ноябре", "декабре",
    ]

    await message.answer(
        f"💰 <b>Ваш баланс и статистика</b>\n\n"
        f"📅 Отгулов взято в {month_names[today.month]}: <b>{days_this_month} д.</b>\n"
        f"🏦 Остаток баланса: <b>{user.vacation_balance:.1f} д.</b>\n\n"
        f"📊 <b>Всего заявок:</b>\n"
        f"  ✅ Одобрено: {len(approved)}\n"
        f"  ⏳ На рассмотрении: {len(pending)}\n"
        f"  📝 Всего подано: {len(all_requests)}",
        parse_mode="HTML",
    )


@router.message(F.text == "📋 Мои заявки")
async def cmd_my_requests(message: Message):
    async with AsyncSessionFactory() as session:
        user = await get_or_create_user(session, message.from_user.id, message.from_user.full_name)
        requests = await get_requests_by_user(session, user.id)

    if not requests:
        await message.answer("У вас пока нет заявок. Нажмите «📝 Подать заявку».")
        return

    lines = []
    for req in requests[:10]:  # показываем последние 10
        start = req.start_date.strftime("%d.%m.%Y")
        end = req.end_date.strftime("%d.%m.%Y")
        status = STATUS_LABELS.get(req.status, req.status)
        lines.append(
            f"<b>#{req.id}</b> | {req.type.value} | {start} — {end}\n"
            f"   {status}"
        )

    total = len(requests)
    header = f"📋 <b>Ваши заявки</b> (последние {min(total, 10)} из {total}):\n\n"
    await message.answer(header + "\n\n".join(lines), parse_mode="HTML")


@router.message(F.text == "🔙 Назад")
async def cmd_back(message: Message):
    async with AsyncSessionFactory() as session:
        user = await get_or_create_user(session, message.from_user.id, message.from_user.full_name)

    menu = admin_main_menu() if user.role == UserRole.admin else user_main_menu()
    await message.answer("Главное меню:", reply_markup=menu)
