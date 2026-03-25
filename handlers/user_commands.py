import logging

from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from datetime import date

from keyboards.menus import user_main_menu, admin_main_menu
from database.engine import AsyncSessionFactory
from database.crud import get_or_create_user, get_user_month_days, get_requests_by_user, get_awaiting_work_requests
from database.models import UserRole, RequestStatus, RequestType
from utils.formatters import format_request_period, format_request_duration

logger = logging.getLogger(__name__)
router = Router()

STATUS_LABELS = {
    RequestStatus.pending:       "⏳ На рассмотрении",
    RequestStatus.approved:      "✅ Одобрена",
    RequestStatus.rejected:      "❌ Отклонена",
    RequestStatus.awaiting_work: "🔄 Ожидает отработки",
}


def _u(message: Message) -> str:
    """Короткая строка для идентификации пользователя в логах."""
    u = message.from_user
    return f"[id={u.id} name={u.full_name!r}]"


@router.message(Command("start"))
async def cmd_start(message: Message):
    logger.info("▶ /start | пользователь %s", _u(message))
    async with AsyncSessionFactory() as session:
        user = await get_or_create_user(session, message.from_user.id, message.from_user.full_name)

    if user.role == UserRole.admin:
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
        user = await get_or_create_user(session, message.from_user.id, message.from_user.full_name)
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
        user = await get_or_create_user(session, message.from_user.id, message.from_user.full_name)
        requests = await get_requests_by_user(session, user.id)

    logger.info("   найдено заявок: %d | %s", len(requests), _u(message))

    if not requests:
        await message.answer("У вас пока нет заявок. Нажмите «📝 Подать заявку».")
        return

    lines = []
    for req in requests[:10]:
        period = format_request_period(req)
        duration = format_request_duration(req)
        status = STATUS_LABELS.get(req.status, req.status)
        lines.append(
            f"<b>#{req.id}</b> | {req.type.value} | {period} ({duration})\n"
            f"   {status}"
        )

    total = len(requests)
    header = f"📋 <b>Ваши заявки</b> (последние {min(total, 10)} из {total}):\n\n"
    await message.answer(header + "\n\n".join(lines), parse_mode="HTML")


@router.message(F.text == "🔙 Назад")
async def cmd_back(message: Message):
    logger.info("🔙 Назад | %s", _u(message))
    async with AsyncSessionFactory() as session:
        user = await get_or_create_user(session, message.from_user.id, message.from_user.full_name)

    menu = admin_main_menu() if user.role == UserRole.admin else user_main_menu()
    await message.answer("Главное меню:", reply_markup=menu)
