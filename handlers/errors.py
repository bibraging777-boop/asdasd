"""Global error handler and catch-all fallbacks."""
from __future__ import annotations

import logging
from contextlib import suppress

from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, ErrorEvent, Message

from keyboards.common import main_menu_kb

router = Router(name="errors")
fallback_router = Router(name="fallback")
logger = logging.getLogger(__name__)


@router.errors()
async def on_error(event: ErrorEvent, bot: Bot) -> bool:
    logger.exception(
        "Unhandled error while processing update %s", event.update.update_id,
        exc_info=event.exception,
    )
    update = event.update
    with suppress(TelegramAPIError):
        if update.callback_query is not None:
            await update.callback_query.answer(
                "Something went wrong. Please try again.", show_alert=True
            )
        elif update.message is not None and update.message.chat.type == "private":
            await bot.send_message(
                update.message.chat.id, "⚠️ Something went wrong. Please try again later."
            )
    return True


@fallback_router.callback_query()
async def stale_callback(callback: CallbackQuery) -> None:
    await callback.answer("This button is no longer active.")


@fallback_router.message()
async def unknown_message(message: Message) -> None:
    await message.answer("I didn't get that. Use the menu:", reply_markup=main_menu_kb())
