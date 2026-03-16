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
from database.crud import update_request_status
from database.models import TimeOffRequest, User, RequestStatus

logger = logging.getLogger(__name__)
router = Router()


# ─── Фильтр: только для администраторов ──────────────────────────────────────
class IsAdmin(Filter):
    async def __call__(self, event: CallbackQuery | Message, admin_ids: list[int]) -> bool:
        return event.from_user.id in admin_ids


router.callback_query.filter(IsAdmin())
router.message.filter(IsAdmin())


# ─── Вспомогательная функция: загрузить заявку вместе с пользователем ────────
async def _get_request_with_user(session, request_id: int):
    result = await session.execute(
        select(TimeOffRequest, User)
        .join(User, TimeOffRequest.user_id == User.id)
        .where(TimeOffRequest.id == request_id)
    )
    return result.one_or_none()


# ─── Нажатие «Одобрить» ──────────────────────────────────────────────────────
@router.callback_query(RequestActionCallback.filter(F.action == "approve"))
async def approve_request(
    call: CallbackQuery,
    callback_data: RequestActionCallback,
    bot: Bot,
    group_id: int,
):
    request_id = callback_data.request_id

    async with AsyncSessionFactory() as session:
        row = await _get_request_with_user(session, request_id)
        if not row:
            await call.answer("⚠️ Заявка не найдена!", show_alert=True)
            return

        req, user = row

        if req.status != RequestStatus.pending:
            await call.answer("ℹ️ Заявка уже была обработана ранее.", show_alert=True)
            return

        await update_request_status(session, request_id, status=RequestStatus.approved)

    start_str = req.start_date.strftime("%d.%m.%Y")
    end_str = req.end_date.strftime("%d.%m.%Y")
    type_label = req.type.value
    admin_name = f"@{call.from_user.username}" if call.from_user.username else call.from_user.full_name

    # ── Обновляем сообщение у администратора ────────────────────────────────
    await call.message.edit_text(
        call.message.text + f"\n\n✅ <b>Одобрено</b> администратором {admin_name}",
        parse_mode="HTML",
    )

    # ── Уведомление пользователю ─────────────────────────────────────────────
    try:
        await bot.send_message(
            user.tg_id,
            f"🎉 <b>Ваша заявка #{req.id} одобрена!</b>\n\n"
            f"📋 Тип: <b>{type_label}</b>\n"
            f"📅 Период: <b>{start_str} — {end_str}</b>\n\n"
            f"Хорошего отдыха! 😊",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning("Не удалось уведомить пользователя %s: %s", user.tg_id, e)

    # ── Сообщение в общую группу команды ─────────────────────────────────────
    try:
        await bot.send_message(
            group_id,
            f"📢 <b>Информация об отсутствии</b>\n\n"
            f"Сотрудник <b>{user.full_name}</b> будет отсутствовать "
            f"с <b>{start_str}</b> по <b>{end_str}</b> ({type_label}).",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning("Не удалось отправить сообщение в группу %s: %s", group_id, e)

    await call.answer("✅ Заявка одобрена")


# ─── Нажатие «Отклонить» — запрос причины ────────────────────────────────────
@router.callback_query(RequestActionCallback.filter(F.action == "reject"))
async def reject_request_ask_reason(
    call: CallbackQuery,
    callback_data: RequestActionCallback,
    state: FSMContext,
):
    async with AsyncSessionFactory() as session:
        row = await _get_request_with_user(session, callback_data.request_id)
        if not row:
            await call.answer("⚠️ Заявка не найдена!", show_alert=True)
            return

        req, _ = row
        if req.status != RequestStatus.pending:
            await call.answer("ℹ️ Заявка уже была обработана ранее.", show_alert=True)
            return

    await state.update_data(
        request_id=callback_data.request_id,
        original_message_id=call.message.message_id,
        original_chat_id=call.message.chat.id,
    )
    await state.set_state(AdminReviewForm.entering_comment)

    await call.message.reply(
        f"✏️ Укажите причину отказа по заявке <b>#{callback_data.request_id}</b>:",
        parse_mode="HTML",
    )
    await call.answer()


# ─── Получение причины отказа от админа ──────────────────────────────────────
@router.message(AdminReviewForm.entering_comment)
async def reject_request_save(message: Message, state: FSMContext, bot: Bot):
    comment = message.text.strip()
    data = await state.get_data()
    request_id = data["request_id"]
    await state.clear()

    async with AsyncSessionFactory() as session:
        row = await _get_request_with_user(session, request_id)
        if not row:
            await message.answer("⚠️ Заявка не найдена!")
            return

        req, user = row
        await update_request_status(
            session, request_id, status=RequestStatus.rejected, admin_comment=comment
        )

    start_str = req.start_date.strftime("%d.%m.%Y")
    end_str = req.end_date.strftime("%d.%m.%Y")

    # ── Подтверждение администратору ─────────────────────────────────────────
    await message.answer(
        f"❌ Заявка <b>#{request_id}</b> отклонена.\n💬 Причина сохранена: <i>{comment}</i>",
        reply_markup=admin_main_menu(),
        parse_mode="HTML",
    )

    # ── Обновляем исходное сообщение с заявкой ───────────────────────────────
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
        logger.warning("Не удалось обновить сообщение с заявкой: %s", e)

    # ── Уведомление пользователю ─────────────────────────────────────────────
    try:
        await bot.send_message(
            user.tg_id,
            f"😔 <b>Ваша заявка #{req.id} отклонена.</b>\n\n"
            f"📋 Тип: <b>{req.type.value}</b>\n"
            f"📅 Период: <b>{start_str} — {end_str}</b>\n\n"
            f"💬 Комментарий администратора: <i>{comment}</i>",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning("Не удалось уведомить пользователя %s: %s", user.tg_id, e)
