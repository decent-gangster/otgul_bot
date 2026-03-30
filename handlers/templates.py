import logging
from datetime import datetime, date

import pymorphy3
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from states.request_states import TemplateForm
from database.engine import AsyncSessionFactory
from database.crud import get_or_create_user

_morph = pymorphy3.MorphAnalyzer()
_MIN_NOMN_SCORE = 0.05  # порог для фильтрации ложных именительных разборов

def _inflect_word(word: str) -> str:
    """Склоняет слово в творительный падеж.
    Ищет именительный разбор с вероятностью выше порога (чтобы не склонять
    слова, которые явно стоят в другом падеже, типа «ребенка», «здоровья»).
    """
    parsed = _morph.parse(word)
    if not parsed:
        return word
    nomn = next(
        (p for p in parsed
         if p.tag.POS in ("NOUN", "ADJF", "ADJS", "PRTF", "PRTS")
         and p.tag.case == "nomn"
         and p.score >= _MIN_NOMN_SCORE),
        None,
    )
    if nomn is None:
        return word
    grammemes = {"ablt"}
    if nomn.tag.number == "plur":
        grammemes.add("plur")
    inflected = nomn.inflect(grammemes)
    if inflected:
        result = inflected.word
        return result.capitalize() if word[0].isupper() else result
    return word


def to_instrumental(text: str) -> str:
    """Переводит причину в творительный падеж. Если уже начинается с «с/со» — оставляет как есть."""
    text = text.strip()
    if text.lower().startswith(("с ", "со ")):
        return text
    converted = " ".join(_inflect_word(w) for w in text.split())
    return "с " + converted

logger = logging.getLogger(__name__)
router = Router()

GENITIVE_NAMES = {
    "Эгембердиев Элтуран Алмазович":    "Эгембердиева Элтурана Алмазовича",
    "Бурхан кызы Айкокул":              "Бурхан кызы Айкокул",
    "Коледин Руслан Константинович":     "Коледина Руслана Константиновича",
    "Сатимов Абдулла Дильшотжонович":   "Сатимова Абдуллы Дильшотжоновича",
    "Мирланова Саадат Мирлановна":       "Мирлановой Саадат Мирлановны",
    "Джапарова Айым Канатбековна":       "Джапаровой Айым Канатбековны",
}


def _genitive(full_name: str) -> str:
    return GENITIVE_NAMES.get(full_name, full_name)


MONTHS_RU = [
    "", "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


def _date_ru(d: date) -> str:
    return f"{d.day:02d} {MONTHS_RU[d.month]} {d.year} года"


def _parse_date(text: str) -> date | None:
    try:
        return datetime.strptime(text.strip(), "%d.%m.%Y").date()
    except ValueError:
        return None


def templates_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌴 Трудовой отпуск", callback_data="tmpl_vacation")],
        [InlineKeyboardButton(text="📄 Отгул без содержания", callback_data="tmpl_dayoff")],
    ])


def _vacation_text(full_name: str, start: date) -> str:
    today_str = _date_ru(date.today())
    return (
        f"Председателю Правления\n"
        f"ОАО «Мбанк»\n"
        f"господину Ишенбаеву М.Б.\n"
        f"от __________________________________\n"
        f"отдела автоматизации процессов обслуживания\n"
        f"Управления проектами клиентского опыта\n"
        f"и автоматизации обслуживания ДКОиОК\n"
        f"{_genitive(full_name)}\n"
        f"\n\n"
        f"                  Заявление\n"
        f"\n\n"
        f"Прошу Вас предоставить мне трудовой отпуск\n"
        f"с {_date_ru(start)} на 14 календарных дней.\n"
        f"\n\n"
        f"{today_str}\n"
        f"Подпись: ___________"
    )


def _dayoff_text(full_name: str, start: date, end: date, reason: str) -> str:
    today_str = _date_ru(date.today())
    return (
        f"Председателю Правления\n"
        f"ОАО «Мбанк»\n"
        f"господину Ишенбаеву М.Б.\n"
        f"от __________________________________\n"
        f"отдела автоматизации процессов обслуживания\n"
        f"Управления проектами клиентского опыта\n"
        f"и автоматизации обслуживания ДКОиОК\n"
        f"{_genitive(full_name)}\n"
        f"\n\n"
        f"                  Заявление\n"
        f"\n\n"
        f"Прошу Вас предоставить мне отпуск без сохранения\n"
        f"заработной платы с {_date_ru(start)}\n"
        f"по {_date_ru(end)}, в связи {to_instrumental(reason)}.\n"
        f"\n\n"
        f"{today_str}\n"
        f"Подпись: ___________"
    )


# ─── Точка входа ─────────────────────────────────────────────────────────────
@router.message(F.text == "📄 Шаблоны заявлений")
async def cmd_templates(message: Message, state: FSMContext):
    logger.info("📄 Шаблоны заявлений | id=%d", message.from_user.id)
    await state.clear()
    await message.answer(
        "📄 <b>Шаблоны заявлений</b>\n\nВыберите тип:",
        reply_markup=templates_keyboard(),
        parse_mode="HTML",
    )


# ─── Трудовой отпуск ─────────────────────────────────────────────────────────
@router.callback_query(F.data == "tmpl_vacation")
async def tmpl_vacation_ask_date(call: CallbackQuery, state: FSMContext):
    await state.update_data(tmpl_type="vacation")
    await state.set_state(TemplateForm.entering_start_date)
    await call.message.edit_text(
        "🌴 <b>Трудовой отпуск</b>\n\n"
        "Введите дату начала отпуска:\n"
        "<i>Например: 05.04.2026</i>",
        parse_mode="HTML",
    )
    await call.answer()


# ─── Отгул без содержания ─────────────────────────────────────────────────────
@router.callback_query(F.data == "tmpl_dayoff")
async def tmpl_dayoff_ask_date(call: CallbackQuery, state: FSMContext):
    await state.update_data(tmpl_type="dayoff")
    await state.set_state(TemplateForm.entering_start_date)
    await call.message.edit_text(
        "📄 <b>Отгул без содержания</b>\n\n"
        "Введите дату начала:\n"
        "<i>Например: 05.04.2026</i>",
        parse_mode="HTML",
    )
    await call.answer()


# ─── Дата начала (общий для обоих) ───────────────────────────────────────────
@router.message(TemplateForm.entering_start_date)
async def tmpl_enter_start(message: Message, state: FSMContext):
    start = _parse_date(message.text)
    if not start:
        await message.answer(
            "⚠️ Неверный формат. Введите дату как: <code>05.04.2026</code>",
            parse_mode="HTML",
        )
        return

    data = await state.get_data()
    await state.update_data(start_date=start.isoformat())

    if data["tmpl_type"] == "vacation":
        async with AsyncSessionFactory() as session:
            user = await get_or_create_user(session, message.from_user.id, message.from_user.full_name)
        text = _vacation_text(user.full_name, start)
        await state.clear()
        await message.answer(
            "📋 Скопируйте текст заявления:\n\n"
            f"<pre>{text}</pre>",
            parse_mode="HTML",
        )
    else:
        await state.set_state(TemplateForm.entering_end_date)
        await message.answer(
            "Введите дату окончания:\n<i>Например: 07.04.2026</i>",
            parse_mode="HTML",
        )


# ─── Дата окончания (только для отгула) ──────────────────────────────────────
@router.message(TemplateForm.entering_end_date)
async def tmpl_enter_end(message: Message, state: FSMContext):
    end = _parse_date(message.text)
    if not end:
        await message.answer(
            "⚠️ Неверный формат. Введите дату как: <code>07.04.2026</code>",
            parse_mode="HTML",
        )
        return

    data = await state.get_data()
    start = date.fromisoformat(data["start_date"])
    if end < start:
        await message.answer("⚠️ Дата окончания не может быть раньше даты начала.")
        return

    await state.update_data(end_date=end.isoformat())
    await state.set_state(TemplateForm.entering_reason)
    await message.answer("Укажите причину (<i>например: с семейными обстоятельствами</i>):", parse_mode="HTML")


# ─── Причина (только для отгула) ─────────────────────────────────────────────
@router.message(TemplateForm.entering_reason)
async def tmpl_enter_reason(message: Message, state: FSMContext):
    reason = message.text.strip()
    data = await state.get_data()
    start = date.fromisoformat(data["start_date"])
    end = date.fromisoformat(data["end_date"])

    async with AsyncSessionFactory() as session:
        user = await get_or_create_user(session, message.from_user.id, message.from_user.full_name)

    text = _dayoff_text(user.full_name, start, end, reason)
    await state.clear()
    await message.answer(
        "📋 Скопируйте текст заявления:\n\n"
        f"<pre>{text}</pre>",
        parse_mode="HTML",
    )
