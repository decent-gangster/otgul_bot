import logging

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.filters import Filter
from sqlalchemy import select

from states.request_states import AdminReviewForm
from keyboards.request_kb import RequestActionCallback
from keyboards.menus import admin_main_menu
from database.engine import AsyncSessionFactory
from database.crud import update_request_status, add_overtime_hours, deduct_overtime_hours, apply_overtime_to_debts, add_balance_log, add_admin_log
from database.models import TimeOffRequest, User, RequestStatus, RequestType
from utils.formatters import format_request_period, format_request_duration

logger = logging.getLogger(__name__)
router = Router()


def _a(event) -> str:
    u = event.from_user
    return f"[admin id={u.id} name={u.full_name!r}]"


class IsAdmin(Filter):
    async def __call__(self, event: CallbackQuery | Message, admin_ids: list[int]) -> bool:
        return event.from_user.id in admin_ids


router.callback_query.filter(IsAdmin())
router.message.filter(IsAdmin())


async def _get_request_with_user(session, request_id: int):
    result = await session.execute(
        select(TimeOffRequest, User)
        .join(User, TimeOffRequest.user_id == User.id)
        .where(TimeOffRequest.id == request_id)
    )
    return result.one_or_none()


# ─── Одобрить ────────────────────────────────────────────────────────────────
@router.callback_query(RequestActionCallback.filter(F.action == "approve"))
async def approve_request(
    call: CallbackQuery,
    callback_data: RequestActionCallback,
    bot: Bot,
    group_id: int,
):
    request_id = callback_data.request_id
    logger.info("✅ Одобрить заявку #%d | %s", request_id, _a(call))

    async with AsyncSessionFactory() as session:
        row = await _get_request_with_user(session, request_id)
        if not row:
            logger.warning("   заявка #%d не найдена | %s", request_id, _a(call))
            await call.answer("⚠️ Заявка не найдена!", show_alert=True)
            return

        req, user = row

        if req.status != RequestStatus.pending:
            logger.warning("   заявка #%d уже обработана (статус=%s) | %s", request_id, req.status, _a(call))
            await call.answer("ℹ️ Заявка уже была обработана ранее.", show_alert=True)
            return

        # ── Логика начисления/списания часов ─────────────────────────────────
        final_status = RequestStatus.approved
        debt_hours = None
        overtime_note = ""  # дополнительная строка в уведомление сотруднику

        if req.type == RequestType.overtime and req.hours:
            # Сначала гасим долги, остаток идёт в баланс
            leftover, closed_ids = await apply_overtime_to_debts(session, req.user_id, req.hours)
            if leftover > 0:
                await add_overtime_hours(session, req.user_id, leftover)
                await add_balance_log(session, req.user_id, +leftover,
                    f"Переработка одобрена (заявка #{req.id})", req.id)
            if closed_ids:
                ids_str = ", ".join(f"#{i}" for i in closed_ids)
                hours_for_debts = req.hours - leftover
                await add_balance_log(session, req.user_id, -hours_for_debts,
                    f"Зачтено в счёт долга (заявки {ids_str})", req.id)
                overtime_note = f"\n✅ Долг по отработке закрыт (заявки {ids_str})."
                logger.info("   закрыты долги %s у пользователя id=%d", ids_str, user.tg_id)
            logger.info("   начислено %.1f ч. переработки (в баланс %.1f ч.) пользователю id=%d",
                        req.hours, leftover, user.tg_id)

        elif req.type == RequestType.otgul_paid:
            total_needed = req.hours if req.hours else ((req.end_date - req.start_date).days + 1) * 9
            balance = user.overtime_hours or 0

            if balance >= total_needed:
                await deduct_overtime_hours(session, req.user_id, total_needed)
                await add_balance_log(session, req.user_id, -total_needed,
                    f"Отгул с отработкой одобрен (заявка #{req.id})", req.id)
                overtime_note = f"\n💳 Списано с баланса переработки: {total_needed:.1f} ч."
                logger.info("   списано %.1f ч. с баланса у пользователя id=%d", total_needed, user.tg_id)
            else:
                deducted = balance
                remaining = round(total_needed - deducted, 2)
                if deducted > 0:
                    await deduct_overtime_hours(session, req.user_id, deducted)
                    await add_balance_log(session, req.user_id, -deducted,
                        f"Отгул с отработкой, частично (заявка #{req.id})", req.id)
                final_status = RequestStatus.awaiting_work
                debt_hours = remaining
                if deducted > 0:
                    overtime_note = (
                        f"\n💳 Списано с баланса: {deducted:.1f} ч."
                        f"\n⏳ Осталось отработать: {remaining:.1f} ч."
                    )
                else:
                    overtime_note = f"\n⏳ Необходимо отработать: {remaining:.1f} ч."
                logger.info("   отгул с содержанием: списано %.1f ч., долг %.1f ч. у пользователя id=%d",
                            deducted, remaining, user.tg_id)

        await update_request_status(session, request_id, status=final_status, debt_hours=debt_hours)
        logger.info("   заявка #%d → %s | сотрудник id=%d %r | %s", request_id, final_status, user.tg_id, user.full_name, _a(call))
        admin_name = f"@{call.from_user.username}" if call.from_user.username else call.from_user.full_name
        action = "approved" if final_status == RequestStatus.approved else "approved_awaiting"
        await add_admin_log(session, call.from_user.id, admin_name, action,
                            user.full_name, request_id,
                            f"{req.type.value}" + (f", долг {debt_hours:.1f} ч." if debt_hours else ""))

    period = format_request_period(req)
    duration = format_request_duration(req)
    type_label = req.type.value
    admin_name = f"@{call.from_user.username}" if call.from_user.username else call.from_user.full_name

    await call.message.edit_text(
        call.message.text + f"\n\n✅ <b>Одобрено</b> администратором {admin_name}",
        parse_mode="HTML",
    )

    try:
        if final_status == RequestStatus.awaiting_work:
            header = f"🎉 <b>Ваша заявка #{req.id} одобрена!</b> (ожидает отработки)"
        else:
            header = f"🎉 <b>Ваша заявка #{req.id} одобрена!</b>"
        closing = "" if req.type == RequestType.overtime else "\n\nХорошего отдыха! 😊"
        await bot.send_message(
            user.tg_id,
            f"{header}\n\n"
            f"📋 Тип: <b>{type_label}</b>\n"
            f"📅 Период: <b>{period}</b>\n"
            f"🔢 Длительность: <b>{duration}</b>"
            f"{overtime_note}"
            f"{closing}",
            parse_mode="HTML",
        )
        logger.info("   уведомление отправлено пользователю id=%d", user.tg_id)
    except Exception as e:
        logger.warning("   не удалось уведомить пользователя id=%d: %s", user.tg_id, e)

    try:
        if req.type == RequestType.overtime:
            from datetime import date as date_
            verb = "работал" if req.start_date < date_.today() else "работает"
            group_text = (
                f"🕐 <b>Переработка</b>\n\n"
                f"Сотрудник <b>{user.full_name}</b> {verb} сверхурочно "
                f"<b>{period}</b> — {duration}."
            )
        else:
            group_text = (
                f"📢 <b>Информация об отсутствии</b>\n\n"
                f"Сотрудник <b>{user.full_name}</b> будет отсутствовать "
                f"<b>{period}</b> ({type_label}, {duration})."
            )
        await bot.send_message(group_id, group_text, parse_mode="HTML")
        logger.info("   анонс отправлен в группу id=%d", group_id)
    except Exception as e:
        logger.warning("   не удалось отправить анонс в группу id=%d: %s", group_id, e)

    await call.answer("✅ Заявка одобрена")


# ─── Отклонить — запрос причины ──────────────────────────────────────────────
@router.callback_query(RequestActionCallback.filter(F.action == "reject"))
async def reject_request_ask_reason(
    call: CallbackQuery,
    callback_data: RequestActionCallback,
    state: FSMContext,
):
    request_id = callback_data.request_id
    logger.info("❌ Отклонить заявку #%d — запрос причины | %s", request_id, _a(call))

    async with AsyncSessionFactory() as session:
        row = await _get_request_with_user(session, request_id)
        if not row:
            logger.warning("   заявка #%d не найдена | %s", request_id, _a(call))
            await call.answer("⚠️ Заявка не найдена!", show_alert=True)
            return

        req, _ = row
        if req.status != RequestStatus.pending:
            logger.warning("   заявка #%d уже обработана (статус=%s) | %s", request_id, req.status, _a(call))
            await call.answer("ℹ️ Заявка уже была обработана ранее.", show_alert=True)
            return

    await state.update_data(
        request_id=request_id,
        original_message_id=call.message.message_id,
        original_chat_id=call.message.chat.id,
    )
    await state.set_state(AdminReviewForm.entering_comment)
    await call.message.reply(
        f"✏️ Укажите причину отказа по заявке <b>#{request_id}</b>:",
        parse_mode="HTML",
    )
    await call.answer()


# ─── Сохранение причины отказа ───────────────────────────────────────────────
@router.message(AdminReviewForm.entering_comment)
async def reject_request_save(message: Message, state: FSMContext, bot: Bot):
    comment = message.text.strip()
    data = await state.get_data()
    request_id = data["request_id"]
    await state.clear()

    logger.info("❌ Причина отказа по заявке #%d: %r | %s", request_id, comment[:80], _a(message))

    async with AsyncSessionFactory() as session:
        row = await _get_request_with_user(session, request_id)
        if not row:
            logger.warning("   заявка #%d не найдена при сохранении отказа | %s", request_id, _a(message))
            await message.answer("⚠️ Заявка не найдена!")
            return

        req, user = row
        await update_request_status(
            session, request_id, status=RequestStatus.rejected, admin_comment=comment
        )
        logger.info("   заявка #%d → rejected | сотрудник id=%d %r | %s", request_id, user.tg_id, user.full_name, _a(message))
        admin_name = f"@{message.from_user.username}" if message.from_user.username else message.from_user.full_name
        await add_admin_log(session, message.from_user.id, admin_name, "rejected",
                            user.full_name, request_id, comment)

    period = format_request_period(req)
    duration = format_request_duration(req)

    await message.answer(
        f"❌ Заявка <b>#{request_id}</b> отклонена.\n💬 Причина сохранена: <i>{comment}</i>",
        reply_markup=admin_main_menu(),
        parse_mode="HTML",
    )

    try:
        await bot.edit_message_text(
            chat_id=data["original_chat_id"],
            message_id=data["original_message_id"],
            text=(
                f"❌ <b>Заявка #{request_id} отклонена</b>\n"
                f"💬 Причина: <i>{comment}</i>"
            ),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning("   не удалось обновить сообщение с заявкой #%d: %s", request_id, e)

    try:
        await bot.send_message(
            user.tg_id,
            f"😔 <b>Ваша заявка #{req.id} отклонена.</b>\n\n"
            f"📋 Тип: <b>{req.type.value}</b>\n"
            f"📅 Период: <b>{period}</b>\n"
            f"🔢 Длительность: <b>{duration}</b>\n\n"
            f"💬 Комментарий администратора: <i>{comment}</i>",
            parse_mode="HTML",
        )
        logger.info("   уведомление об отказе отправлено пользователю id=%d", user.tg_id)
    except Exception as e:
        logger.warning("   не удалось уведомить пользователя id=%d: %s", user.tg_id, e)
