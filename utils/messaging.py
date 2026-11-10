"""Small messaging helpers shared across handlers."""
from __future__ import annotations

import logging
from contextlib import suppress
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import CallbackQuery, Message

import texts
from keyboards.common import age_gate_kb, subscription_kb, top_up_kb
from services.billing import InsufficientFunds

logger = logging.getLogger(__name__)


async def safe_send(bot: Bot, chat_id: int, text: str, **kwargs: Any) -> bool:
    """Send to another user; False if undeliverable (e.g. they blocked the bot)."""
    try:
        await bot.send_message(chat_id, text, **kwargs)
    except TelegramAPIError as exc:
        logger.info("Could not deliver message to %s: %s", chat_id, exc)
        return False
    return True


async def strip_keyboard(callback: CallbackQuery) -> None:
    """Remove the inline keyboard of the pressed message to prevent re-use."""
    if isinstance(callback.message, Message):
        with suppress(TelegramBadRequest):
            await callback.message.edit_reply_markup(reply_markup=None)


async def send_age_gate(bot: Bot, chat_id: int) -> None:
    await bot.send_message(chat_id, texts.AGE_GATE, reply_markup=age_gate_kb())


async def send_subscription_prompt(bot: Bot, chat_id: int) -> None:
    await bot.send_message(
        chat_id,
        "📢 To use the bot, please subscribe to our channel, then press "
        "<b>Check subscription</b>.",
        reply_markup=subscription_kb(),
    )


async def send_top_up_prompt(bot: Bot, chat_id: int, error: InsufficientFunds) -> None:
    await bot.send_message(
        chat_id,
        "💸 <b>Not enough credits.</b>\n"
        f"This action costs {error.price}, your balance is {error.balance}.\n\n"
        "Top up to continue:",
        reply_markup=top_up_kb(),
    )
