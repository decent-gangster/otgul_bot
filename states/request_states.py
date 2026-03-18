from aiogram.fsm.state import State, StatesGroup


class RequestForm(StatesGroup):
    """Состояния для подачи заявки на отгул/отпуск/больничный."""
    choosing_type = State()        # выбор типа заявки
    choosing_hours_or_days = State()  # только для отгула: полный день или по часам
    choosing_hours = State()       # ввод количества часов
    choosing_start_date = State()  # выбор даты начала
    choosing_end_date = State()    # выбор даты окончания
    entering_reason = State()      # ввод причины
    confirming = State()           # подтверждение перед отправкой


class AdminReviewForm(StatesGroup):
    """Состояния для обработки заявки администратором."""
    choosing_request = State()   # выбор заявки из списка
    entering_comment = State()   # ввод комментария при отказе
