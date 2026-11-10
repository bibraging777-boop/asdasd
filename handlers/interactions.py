"""Likes, paid messages and private-chat (PM) requests."""
from __future__ import annotations

from html import escape

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

import texts
from config import settings
from database import repo
from database.models import ActionType, PMRequest, PMRequestStatus, User
from handlers.search import show_next
from keyboards.callbacks import CardCb, PMCb
from keyboards.search import contact_kb, pm_request_kb
from services import billing
from services.billing import InsufficientFunds
from states import Interaction
from utils.messaging import safe_send, send_top_up_prompt, strip_keyboard

router = Router(name="interactions")

UNAVAILABLE = "This profile is no longer available."
MSG_TARGET_KEY = "msg_target"
MSG_KIND_KEY = "msg_kind"

_MESSAGE_PRICING: dict[str, tuple[str, ActionType]] = {
    "anon": ("PRICE_SEND_ANON_MSG", ActionType.ANON_MSG),
    "named": ("PRICE_SEND_NAMED_MSG", ActionType.NAMED_MSG),
}


def _message_price(kind: str) -> tuple[int, ActionType]:
    setting_name, action = _MESSAGE_PRICING[kind]
    return getattr(settings, setting_name), action


# --- Like / dislike ---------------------------------------------------------


@router.callback_query(CardCb.filter(F.action == "like"))
async def like(
    callback: CallbackQuery,
    callback_data: CardCb,
    state: FSMContext,
    session: AsyncSession,
    user: User,
    bot: Bot,
) -> None:
    reachable = await repo.get_reachable_target(session, user.id, callback_data.target)
    if reachable is None:
        await callback.answer(UNAVAILABLE, show_alert=True)
        await strip_keyboard(callback)
        return
    target, _ = reachable
    mutual = await repo.add_like(session, user.id, target.id)
    await session.commit()
    await callback.answer("❤️ Liked")
    await strip_keyboard(callback)

    if mutual:
        notice = (
            "💞 <b>It's a mutual like!</b>\n"
            "Someone you liked has liked you back. Send a message or request "
            "a private chat to exchange Telegram handles:"
        )
        await safe_send(bot, user.telegram_id, notice, reply_markup=contact_kb(target.id))
        await safe_send(bot, target.telegram_id, notice, reply_markup=contact_kb(user.id))
    await show_next(bot, session, state, user)


@router.callback_query(CardCb.filter(F.action == "dislike"))
async def dislike(
    callback: CallbackQuery,
    callback_data: CardCb,
    state: FSMContext,
    session: AsyncSession,
    user: User,
    bot: Bot,
) -> None:
    unlock = await repo.get_unlock(session, user.id, callback_data.target)
    if unlock is not None:
        await repo.add_dislike(session, user.id, callback_data.target)
        await session.commit()
    await callback.answer("👎 Skipped")
    await strip_keyboard(callback)
    await show_next(bot, session, state, user)


# --- Anonymous / named messages ---------------------------------------------


@router.callback_query(CardCb.filter(F.action.in_({"anon", "named"})))
async def start_message(
    callback: CallbackQuery,
    callback_data: CardCb,
    state: FSMContext,
    session: AsyncSession,
    user: User,
    bot: Bot,
) -> None:
    reachable = await repo.get_reachable_target(session, user.id, callback_data.target)
    if reachable is None:
        await callback.answer(UNAVAILABLE, show_alert=True)
        return
    await callback.answer()
    price, _ = _message_price(callback_data.action)
    if user.balance < price:
        await send_top_up_prompt(bot, user.telegram_id, InsufficientFunds(price, user.balance))
        return

    await state.set_state(Interaction.writing_message)
    await state.update_data({MSG_TARGET_KEY: reachable[0].id, MSG_KIND_KEY: callback_data.action})
    disclosure = (
        "The recipient will <b>not</b> see who you are."
        if callback_data.action == "anon"
        else "Your name and profile summary <b>will be shown</b> to the recipient."
    )
    await bot.send_message(
        user.telegram_id,
        f"✏️ Write your message (text, up to {settings.MESSAGE_MAX_LENGTH} characters).\n"
        f"{disclosure}\nCost: {price} credits, charged when sent. /cancel to abort.",
    )


@router.message(Interaction.writing_message, F.text, ~F.text.startswith("/"))
async def deliver_message(
    message: Message, state: FSMContext, session: AsyncSession, user: User, bot: Bot
) -> None:
    text = (message.text or "").strip()
    if not text or len(text) > settings.MESSAGE_MAX_LENGTH:
        await message.answer(
            f"The message must be 1–{settings.MESSAGE_MAX_LENGTH} characters. Try again."
        )
        return

    data = await state.get_data()
    kind = data.get(MSG_KIND_KEY)
    target_id = data.get(MSG_TARGET_KEY)
    await state.set_state(None)
    reachable = (
        await repo.get_reachable_target(session, user.id, target_id)
        if isinstance(target_id, int) and kind in _MESSAGE_PRICING
        else None
    )
    if reachable is None:
        await message.answer(f"{UNAVAILABLE} You were not charged.")
        return
    target, _ = reachable

    if kind == "anon":
        body = f"🕶 <b>Anonymous message</b>\n\n{escape(text)}"
    else:
        own = await repo.get_profile(session, user.id)
        if own is None:
            await message.answer("Create your profile first: /start")
            return
        body = (
            f"✍️ <b>Message from {texts.display_name(user)}</b>, {own.age}, "
            f"{escape(own.city)} · {texts.CATEGORY_LABELS[own.category]}\n\n{escape(text)}"
        )

    price, action = _message_price(kind)
    try:
        await billing.charge(session, user, price, action)
    except InsufficientFunds as error:
        await send_top_up_prompt(bot, user.telegram_id, error)
        return
    await session.commit()

    if await safe_send(bot, target.telegram_id, body):
        await message.answer(f"✅ Message sent. Balance: {user.balance} credits.")
    else:
        await billing.credit(session, user, price, ActionType.REFUND)
        await session.commit()
        await message.answer(
            "⚠️ The message could not be delivered. Your credits were refunded."
        )


@router.message(Interaction.writing_message)
async def message_wrong_content(message: Message) -> None:
    await message.answer("Only text messages can be sent. Write your text or /cancel.")


# --- Private chat (PM) requests ---------------------------------------------


@router.callback_query(CardCb.filter(F.action == "pm"))
async def request_pm(
    callback: CallbackQuery,
    callback_data: CardCb,
    session: AsyncSession,
    user: User,
    bot: Bot,
) -> None:
    reachable = await repo.get_reachable_target(session, user.id, callback_data.target)
    own = await repo.get_profile(session, user.id)
    if reachable is None or own is None:
        await callback.answer(UNAVAILABLE, show_alert=True)
        return
    target, _ = reachable
    if await repo.has_pending_pm_request(session, user.id, target.id):
        await callback.answer("Your previous request is still pending.", show_alert=True)
        return
    await callback.answer()

    price = settings.PRICE_REQUEST_PM
    try:
        await billing.charge(session, user, price, ActionType.PM_REQUEST)
    except InsufficientFunds as error:
        await send_top_up_prompt(bot, user.telegram_id, error)
        return
    request = PMRequest(
        sender_id=user.id,
        receiver_id=target.id,
        status=PMRequestStatus.PENDING,
        price_paid=price,
    )
    session.add(request)
    await session.commit()

    delivered = await safe_send(
        bot,
        target.telegram_id,
        f"📩 User from <b>{texts.CATEGORY_LABELS[own.category]}</b> wants to exchange "
        "direct Telegram handles. Accept / Reject?",
        reply_markup=pm_request_kb(request.id),
    )
    if delivered:
        await bot.send_message(
            user.telegram_id,
            f"📩 Request sent. You will be notified about the answer.\n"
            f"Balance: {user.balance} credits.",
        )
        return
    request.status = PMRequestStatus.REJECTED
    await billing.credit(session, user, price, ActionType.REFUND)
    await session.commit()
    await bot.send_message(
        user.telegram_id,
        "⚠️ The request could not be delivered. Your credits were refunded.",
    )


@router.callback_query(PMCb.filter(F.action.in_({"accept", "reject"})))
async def decide_pm_request(
    callback: CallbackQuery,
    callback_data: PMCb,
    session: AsyncSession,
    user: User,
    bot: Bot,
) -> None:
    accepted = callback_data.action == "accept"
    request = await repo.resolve_pm_request(
        session,
        callback_data.request_id,
        user.id,
        PMRequestStatus.ACCEPTED if accepted else PMRequestStatus.REJECTED,
    )
    sender = await session.get(User, request.sender_id) if request else None
    if request is None or sender is None:
        await callback.answer("This request has already been processed.", show_alert=True)
        await strip_keyboard(callback)
        return

    refunded = False
    if not accepted and settings.REFUND_ON_PM_REJECT:
        refunded = await billing.credit(session, sender, request.price_paid, ActionType.REFUND)
    await session.commit()
    await callback.answer()
    await strip_keyboard(callback)

    if accepted:
        await bot.send_message(
            user.telegram_id,
            f"✅ Accepted. Here is their contact: {texts.handle_of(sender)}",
        )
        await safe_send(
            bot,
            sender.telegram_id,
            f"✅ Your private chat request was accepted! Contact: {texts.handle_of(user)}",
        )
    else:
        await bot.send_message(user.telegram_id, "❌ Request rejected.")
        refund_note = (
            f" {request.price_paid} credits were refunded to your balance." if refunded else ""
        )
        await safe_send(
            bot,
            sender.telegram_id,
            f"❌ Your private chat request was declined.{refund_note}",
        )
