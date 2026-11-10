"""Access gate: 18+ verification, then sponsor channel subscription."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, Bot
from aiogram.enums import ChatType
from aiogram.types import CallbackQuery, Message, TelegramObject

from database.models import User
from keyboards.callbacks import AGE_PREFIX, SUBSCRIPTION_CHECK
from services.subscription import SubscriptionChecker
from utils.messaging import send_age_gate, send_subscription_prompt

Handler = Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]]


class AccessGateMiddleware(BaseMiddleware):
    """Register as an outer middleware on ``message`` and ``callback_query``.

    Nothing but the gate's own callbacks reaches a handler until the user is
    age-verified and subscribed. Payment confirmations always pass so a paid
    top-up is never lost.
    """

    def __init__(self, subscriptions: SubscriptionChecker) -> None:
        self._subscriptions = subscriptions

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        user: User | None = data.get("user")
        if user is None:
            return None
        bot: Bot = data["bot"]
        callback = event if isinstance(event, CallbackQuery) else None
        message = event if isinstance(event, Message) else None

        chat = (
            message.chat
            if message
            else (callback.message.chat if callback and callback.message else None)
        )
        if chat is None or chat.type != ChatType.PRIVATE:
            return None  # the bot only works in private chats
        if message is not None and message.successful_payment is not None:
            return await handler(event, data)

        callback_data = (callback.data or "") if callback else ""

        if not user.is_verified_18:
            if callback_data.startswith(f"{AGE_PREFIX}:"):
                return await handler(event, data)
            if callback is not None:
                await callback.answer()
            await send_age_gate(bot, user.telegram_id)
            return None

        if not await self._subscriptions.is_subscribed(bot, user.telegram_id):
            if callback is not None:
                if callback_data == SUBSCRIPTION_CHECK:
                    await callback.answer("You are not subscribed yet.", show_alert=True)
                    return None
                await callback.answer()
            await send_subscription_prompt(bot, user.telegram_id)
            return None

        return await handler(event, data)
