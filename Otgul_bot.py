import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import load_config
from database.engine import init_db
from handlers import user_request, admin_request

logging.basicConfig(level=logging.INFO, format="%(asctime)s — %(levelname)s — %(message)s")
logger = logging.getLogger(__name__)


async def main():
    config = load_config()

    bot = Bot(token=config.bot_token)
    dp = Dispatcher(storage=MemoryStorage())

    # Передаём данные в хендлеры через workflow_data
    dp.workflow_data["admin_ids"] = config.admin_ids
    dp.workflow_data["group_id"] = config.group_id

    # Подключаем роутеры (порядок важен: admin раньше user)
    dp.include_router(admin_request.router)
    dp.include_router(user_request.router)

    # Создаём таблицы БД
    await init_db()
    logger.info("База данных инициализирована")

    # Запуск бота
    logger.info("Бот запущен")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
