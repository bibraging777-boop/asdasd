"""Database session and user injection middlewares."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, Bot
from aiogram.types import TelegramObject, Update
from aiogram.types import User as TgUser
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import texts
from database import repo

Handler = Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]]


class DbSessionMiddleware(BaseMiddleware):
    """Opens one session per update and injects it as ``session``.

    Commits when the handler succeeds and rolls back when it raises, so a
    failed handler never leaves a half-applied change (or charge) behind.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def __call__(
        self, handler: Handler, event: TelegramObject, data: dict[str, Any]
    ) -> Any:
        async with self._session_factory() as session:
            data["session"] = session
            try:
                result = await handler(event, data)
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise


class UserMiddleware(BaseMiddleware):
    """Loads (or creates) the DB user as ``user`` and drops banned users."""

    async def __call__(
        self, handler: Handler, event: TelegramObject, data: dict[str, Any]
    ) -> Any:
        tg_user: TgUser | None = data.get("event_from_user")
        if tg_user is None or tg_user.is_bot:
            return await handler(event, data)

        user = await repo.get_or_create_user(
            data["session"], tg_user.id, tg_user.username, tg_user.first_name
        )
        data["user"] = user
        if user.is_banned:
            await self._notify_banned(event, data["bot"], tg_user.id)
            return None
        return await handler(event, data)

    @staticmethod
    async def _notify_banned(event: TelegramObject, bot: Bot, telegram_id: int) -> None:
        if not isinstance(event, Update):
            return
        if event.callback_query is not None:
            await event.callback_query.answer(texts.BANNED, show_alert=True)
        elif event.message is not None and event.message.chat.type == "private":
            await bot.send_message(telegram_id, texts.BANNED)
