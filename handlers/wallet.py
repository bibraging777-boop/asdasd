"""Wallet: balance, top-up packages, Telegram Stars payments (or a mock)."""
from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery
from sqlalchemy.ext.asyncio import AsyncSession

import texts
from config import settings
from database.models import ActionType, User
from keyboards.callbacks import BuyCb, MenuCb
from keyboards.common import main_menu_kb, top_up_kb
from services import billing

router = Router(name="wallet")
logger = logging.getLogger(__name__)

STARS_CURRENCY = "XTR"
PAYLOAD_PREFIX = "topup"


def _parse_payload(payload: str) -> tuple[int, int] | None:
    """``topup:<coins>:<stars>`` → (coins, stars)."""
    parts = payload.split(":")
    if len(parts) != 3 or parts[0] != PAYLOAD_PREFIX:
        return None
    try:
        coins, stars = int(parts[1]), int(parts[2])
    except ValueError:
        return None
    return (coins, stars) if coins > 0 and stars > 0 else None


async def _show_wallet(bot: Bot, user: User) -> None:
    await bot.send_message(
        user.telegram_id,
        f"💰 <b>Wallet</b>\nBalance: <b>{user.balance} credits</b>\n\n"
        f"{texts.price_list()}\n\nChoose a package to top up:",
        reply_markup=top_up_kb(),
    )


@router.message(Command("balance"))
async def cmd_balance(message: Message, user: User, bot: Bot) -> None:
    await _show_wallet(bot, user)


@router.callback_query(MenuCb.filter(F.action == "wallet"))
async def menu_wallet(callback: CallbackQuery, user: User, bot: Bot) -> None:
    await callback.answer()
    await _show_wallet(bot, user)


@router.callback_query(BuyCb.filter())
async def buy_package(
    callback: CallbackQuery,
    callback_data: BuyCb,
    session: AsyncSession,
    user: User,
    bot: Bot,
) -> None:
    if not 0 <= callback_data.package < len(settings.COIN_PACKAGES):
        await callback.answer("This package is no longer available.", show_alert=True)
        return
    coins, stars = settings.COIN_PACKAGES[callback_data.package]
    await callback.answer()

    if settings.PAYMENTS_MOCK:
        await billing.credit(session, user, coins, ActionType.TOP_UP)
        await session.commit()
        await bot.send_message(
            user.telegram_id,
            f"🧪 Test payment: +{coins} credits. Balance: {user.balance}.",
            reply_markup=main_menu_kb(),
        )
        return

    await bot.send_invoice(
        chat_id=user.telegram_id,
        title=f"{coins} credits",
        description=f"Top up your balance with {coins} credits.",
        payload=f"{PAYLOAD_PREFIX}:{coins}:{stars}",
        currency=STARS_CURRENCY,
        prices=[LabeledPrice(label=f"{coins} credits", amount=stars)],
    )


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery) -> None:
    parsed = _parse_payload(query.invoice_payload)
    valid = (
        parsed is not None
        and query.currency == STARS_CURRENCY
        and query.total_amount == parsed[1]
    )
    await query.answer(ok=valid, error_message=None if valid else "Invalid invoice.")


@router.message(F.successful_payment)
async def successful_payment(
    message: Message, session: AsyncSession, user: User, bot: Bot
) -> None:
    payment = message.successful_payment
    assert payment is not None  # guaranteed by the filter
    parsed = _parse_payload(payment.invoice_payload)
    if parsed is None or payment.currency != STARS_CURRENCY or payment.total_amount != parsed[1]:
        logger.error(
            "Unexpected payment from %s: payload=%r amount=%s %s",
            user.telegram_id, payment.invoice_payload, payment.total_amount, payment.currency,
        )
        await message.answer("⚠️ Payment received but could not be matched. Contact support.")
        return

    coins = parsed[0]
    # The charge id makes crediting idempotent if Telegram redelivers the update.
    credited = await billing.credit(
        session, user, coins, ActionType.TOP_UP, external_id=payment.telegram_payment_charge_id
    )
    await session.commit()
    if credited:
        await message.answer(
            f"✅ Payment received: +{coins} credits. Balance: {user.balance}.",
            reply_markup=main_menu_kb(),
        )
