import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from aiogram import Bot

from database.engine import AsyncSessionFactory
from database.crud import get_absent_today

logger = logging.getLogger(__name__)


async def send_daily_digest(bot: Bot, group_id: int) -> None:
    """Отправляет в группу ежедневный дайджест об отсутствующих сотрудниках."""
    try:
        async with AsyncSessionFactory() as session:
            rows = await get_absent_today(session)

        if not rows:
            text = "☀️ <b>Доброе утро!</b>\n\nСегодня все в строю! 💪"
        else:
            lines = []
            for req, user in rows:
                end_str = req.end_date.strftime("%d.%m")
                lines.append(f"• <b>{user.full_name}</b> — {req.type.value} (до {end_str})")
            absent_list = "\n".join(lines)
            text = (
                f"☀️ <b>Доброе утро!</b>\n\n"
                f"📋 <b>Сегодня отсутствуют ({len(rows)}):</b>\n"
                f"{absent_list}"
            )

        await bot.send_message(group_id, text, parse_mode="HTML")
        logger.info("Ежедневный дайджест отправлен в группу %s", group_id)
    except Exception as e:
        logger.error("Ошибка при отправке дайджеста: %s", e)


def setup_scheduler(bot: Bot, group_id: int) -> AsyncIOScheduler:
    """Создаёт и настраивает планировщик задач."""
    scheduler = AsyncIOScheduler(timezone="Asia/Bishkek")
    scheduler.add_job(
        send_daily_digest,
        trigger=CronTrigger(hour=9, minute=0, timezone="Asia/Bishkek"),
        kwargs={"bot": bot, "group_id": group_id},
        id="daily_digest",
        replace_existing=True,
    )
    return scheduler
