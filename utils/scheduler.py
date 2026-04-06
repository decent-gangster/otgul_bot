import logging
from datetime import date, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from aiogram import Bot

from database.engine import AsyncSessionFactory
from database.crud import get_absent_today, get_requests_starting_on
from utils.formatters import format_request_period, format_request_duration

logger = logging.getLogger(__name__)


async def send_daily_digest(bot: Bot, group_id: int) -> None:
    """Отправляет в группу ежедневный дайджест об отсутствующих сотрудниках."""
    if date.today().weekday() >= 5:  # 5=суббота, 6=воскресенье
        return
    try:
        async with AsyncSessionFactory() as session:
            rows = await get_absent_today(session)

        if not rows:
            text = "☀️ <b>Доброе утро!</b>\n\nСегодня все в строю! 💪"
        else:
            lines = []
            for req, user in rows:
                period = format_request_period(req)
                duration = format_request_duration(req)
                lines.append(f"• <b>{user.full_name}</b> — {req.type.value} ({period}, {duration})")
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


async def send_reminders(bot: Bot) -> None:
    """Отправляет сотрудникам личное напоминание накануне отгула/отпуска."""
    if date.today().weekday() == 5:  # суббота — завтра воскресенье, напоминать не нужно
        return
    try:
        tomorrow = date.today() + timedelta(days=1)
        async with AsyncSessionFactory() as session:
            rows = await get_requests_starting_on(session, tomorrow)

        if not rows:
            return

        for req, user in rows:
            try:
                period = format_request_period(req)
                duration = format_request_duration(req)
                mention = f"@{user.username}" if user.username else user.full_name
                await bot.send_message(
                    user.tg_id,
                    f"🔔 <b>Напоминание</b>\n\n"
                    f"{mention}, завтра у вас: <b>{req.type.value}</b>\n"
                    f"📅 Период: <b>{period}</b>\n"
                    f"🔢 Длительность: <b>{duration}</b>",
                    parse_mode="HTML",
                )
                logger.info("Напоминание отправлено пользователю id=%d о заявке #%d", user.tg_id, req.id)
            except Exception as e:
                logger.warning("Не удалось отправить напоминание пользователю id=%d: %s", user.tg_id, e)
    except Exception as e:
        logger.error("Ошибка при отправке напоминаний: %s", e)


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
    scheduler.add_job(
        send_reminders,
        trigger=CronTrigger(hour=17, minute=0, timezone="Asia/Bishkek"),
        kwargs={"bot": bot},
        id="daily_reminders",
        replace_existing=True,
    )
    return scheduler
