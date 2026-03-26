import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import load_config
from database.engine import init_db
from utils.scheduler import setup_scheduler
from utils.logger import setup_logging

from handlers import (
    onboarding,
    user_commands,
    user_request,
    admin_commands,
    admin_request,
)

setup_logging()
logger = logging.getLogger(__name__)


async def main() -> None:
    config = load_config()

    # ── Бот и диспетчер ──────────────────────────────────────────────────────
    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # ── Глобальные данные для хендлеров ──────────────────────────────────────
    dp.workflow_data["admin_ids"] = config.admin_ids
    dp.workflow_data["group_id"]  = config.group_id

    # ── Роутеры (порядок важен: admin-фильтры регистрируются раньше user) ────
    dp.include_router(onboarding.router)       # онбординг (ФИО + дата рождения)
    dp.include_router(admin_commands.router)   # /report и прочие команды админа
    dp.include_router(admin_request.router)    # одобрить / отклонить заявку
    dp.include_router(user_commands.router)    # /start, /balance, «Мой баланс»
    dp.include_router(user_request.router)     # FSM подачи заявки

    # ── База данных ───────────────────────────────────────────────────────────
    await init_db()
    logger.info("База данных инициализирована")

    # ── Планировщик ──────────────────────────────────────────────────────────
    scheduler = setup_scheduler(bot, config.group_id)
    scheduler.start()
    logger.info("Планировщик запущен — дайджест в 09:00 МСК")

    # ── Polling ───────────────────────────────────────────────────────────────
    logger.info("Бот запущен и ожидает сообщений...")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown()
        await bot.session.close()
        logger.info("Бот остановлен")


if __name__ == "__main__":
    asyncio.run(main())
