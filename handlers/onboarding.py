import logging
from datetime import datetime, date

from aiogram import Router
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from states.request_states import OnboardingForm
from keyboards.menus import user_main_menu, admin_main_menu
from database.engine import AsyncSessionFactory
from database.crud import get_or_create_user
from database.models import UserRole

logger = logging.getLogger(__name__)
router = Router()


@router.message(OnboardingForm.entering_name)
async def onboarding_enter_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name.split()) < 2:
        await message.answer("⚠️ Введите полное ФИО (минимум два слова), например:\n<code>Иванов Иван Иванович</code>", parse_mode="HTML")
        return
    await state.update_data(full_name=name)
    await state.set_state(OnboardingForm.entering_birth_date)
    await message.answer(
        f"✅ ФИО: <b>{name}</b>\n\n"
        f"📅 Введите вашу <b>дату рождения</b> в формате <code>ДД.ММ.ГГГГ</code>:",
        parse_mode="HTML",
    )


@router.message(OnboardingForm.entering_birth_date)
async def onboarding_enter_birth_date(message: Message, state: FSMContext, admin_ids: list[int]):
    text = message.text.strip()
    try:
        birth_date = datetime.strptime(text, "%d.%m.%Y").date()
        today = date.today()
        if birth_date >= today or (today.year - birth_date.year) > 100:
            raise ValueError
    except ValueError:
        await message.answer(
            "⚠️ Неверный формат или дата.\n"
            "Введите дату в формате <code>ДД.ММ.ГГГГ</code>, например: <code>15.03.1995</code>",
            parse_mode="HTML",
        )
        return

    data = await state.get_data()
    full_name = data["full_name"]
    await state.clear()

    async with AsyncSessionFactory() as session:
        user = await get_or_create_user(session, message.from_user.id, message.from_user.full_name)
        user.full_name = full_name
        user.birth_date = birth_date
        await session.commit()

    logger.info("✅ Онбординг завершён | %s | дата рождения=%s", full_name, birth_date)

    is_admin = message.from_user.id in admin_ids or user.role == UserRole.admin
    menu = admin_main_menu() if is_admin else user_main_menu()

    await message.answer(
        f"✅ <b>Добро пожаловать, {full_name}!</b>\n\n"
        f"🎂 Дата рождения: <b>{birth_date.strftime('%d.%m.%Y')}</b>\n\n"
        f"Вы успешно зарегистрированы. Можете подавать заявки.",
        reply_markup=menu,
        parse_mode="HTML",
    )
