import csv
import io
from datetime import date

from aiogram import Router, F
from aiogram.types import Message, BufferedInputFile
from aiogram.filters import Command

from handlers.admin_request import IsAdmin
from database.engine import AsyncSessionFactory
from database.crud import get_approved_requests_for_month
from keyboards.menus import admin_main_menu

router = Router()
router.message.filter(IsAdmin())


@router.message(Command("report"))
async def cmd_report(message: Message):
    today = date.today()

    async with AsyncSessionFactory() as session:
        rows = await get_approved_requests_for_month(session, today.year, today.month)

    if not rows:
        month_names = [
            "", "январе", "феврале", "марте", "апреле", "мае", "июне",
            "июле", "августе", "сентябре", "октябре", "ноябре", "декабре"
        ]
        await message.answer(
            f"📭 В {month_names[today.month]} нет одобренных заявок.",
            reply_markup=admin_main_menu()
        )
        return

    # ── Генерация CSV в памяти ────────────────────────────────────────────────
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_ALL)

    writer.writerow([
        "№", "Сотрудник", "Telegram ID",
        "Тип", "Дата начала", "Дата окончания", "Дней",
        "Причина", "Комментарий администратора"
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

    month_names_gen = [
        "", "январь", "февраль", "март", "апрель", "май", "июнь",
        "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"
    ]
    filename = f"report_{month_names_gen[today.month]}_{today.year}.csv"

    await message.answer_document(
        document=BufferedInputFile(csv_bytes, filename=filename),
        caption=(
            f"📊 <b>Отчёт за {month_names_gen[today.month]} {today.year}</b>\n"
            f"Одобренных заявок: <b>{len(rows)}</b>"
        ),
        parse_mode="HTML"
    )
