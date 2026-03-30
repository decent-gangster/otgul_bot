from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


def user_main_menu() -> ReplyKeyboardMarkup:
    """Главное меню для обычного пользователя."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📝 Подать заявку")],
            [KeyboardButton(text="🕐 Подать переработку")],
            [KeyboardButton(text="📋 Мои заявки")],
            [KeyboardButton(text="💰 Мой баланс")],
            [KeyboardButton(text="📊 История баланса")],
            [KeyboardButton(text="📅 Календарь отсутствий")],
            [KeyboardButton(text="📄 Шаблоны заявлений")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие..."
    )


def admin_main_menu() -> ReplyKeyboardMarkup:
    """Главное меню для администратора."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📬 Список новых заявок")],
            [KeyboardButton(text="✅ Одобренные заявки")],
            [KeyboardButton(text="📊 Отчёт")],
            [KeyboardButton(text="📈 Статистика")],
            [KeyboardButton(text="👥 Управление сотрудниками")],
            [KeyboardButton(text="💼 Балансы сотрудников")],
            [KeyboardButton(text="📝 Подать заявку")],
            [KeyboardButton(text="🕐 Подать переработку")],
            [KeyboardButton(text="💰 Мой баланс")],
            [KeyboardButton(text="📊 История баланса")],
            [KeyboardButton(text="📅 Календарь отсутствий")],
            [KeyboardButton(text="📄 Шаблоны заявлений")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие..."
    )


def back_keyboard() -> ReplyKeyboardMarkup:
    """Кнопка возврата в меню."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🔙 Назад")]],
        resize_keyboard=True
    )
