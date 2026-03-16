from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters.callback_data import CallbackData
import calendar
from datetime import date


class CalendarCallback(CallbackData, prefix="cal"):
    action: str   # prev_month / next_month / day / ignore
    year: int
    month: int
    day: int


def build_calendar(year: int = None, month: int = None) -> InlineKeyboardMarkup:
    """Генерирует инлайн-клавиатуру с календарём на указанный месяц."""
    today = date.today()
    if year is None:
        year = today.year
    if month is None:
        month = today.month

    buttons = []

    # ── Заголовок: месяц и год ───────────────────────────────────────────────
    month_names = [
        "", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
        "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"
    ]
    header = InlineKeyboardButton(
        text=f"{month_names[month]} {year}",
        callback_data=CalendarCallback(action="ignore", year=year, month=month, day=0).pack()
    )
    buttons.append([header])

    # ── Дни недели ───────────────────────────────────────────────────────────
    week_days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    buttons.append([
        InlineKeyboardButton(
            text=d,
            callback_data=CalendarCallback(action="ignore", year=year, month=month, day=0).pack()
        )
        for d in week_days
    ])

    # ── Дни месяца ───────────────────────────────────────────────────────────
    cal = calendar.monthcalendar(year, month)
    for week in cal:
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(
                    text=" ",
                    callback_data=CalendarCallback(action="ignore", year=year, month=month, day=0).pack()
                ))
            else:
                current_date = date(year, month, day)
                text = f"·{day}·" if current_date == today else str(day)
                row.append(InlineKeyboardButton(
                    text=text,
                    callback_data=CalendarCallback(action="day", year=year, month=month, day=day).pack()
                ))
        buttons.append(row)

    # ── Навигация: пред/след месяц ───────────────────────────────────────────
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1

    buttons.append([
        InlineKeyboardButton(
            text="◀ Пред.",
            callback_data=CalendarCallback(action="prev_month", year=prev_year, month=prev_month, day=0).pack()
        ),
        InlineKeyboardButton(
            text="След. ▶",
            callback_data=CalendarCallback(action="next_month", year=next_year, month=next_month, day=0).pack()
        ),
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)
