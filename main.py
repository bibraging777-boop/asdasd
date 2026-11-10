"""Bot entry point: ``python main.py``."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage, SimpleEventIsolation
from aiogram.types import BotCommand
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import settings
from database.engine import create_engine_and_factory, init_models
from handlers import ROUTERS
from middlewares.db import DbSessionMiddleware, UserMiddleware
from middlewares.gates import AccessGateMiddleware
from services.subscription import SubscriptionChecker

logger = logging.getLogger(__name__)


def create_storage() -> BaseStorage:
    if settings.REDIS_URL:
        from aiogram.fsm.storage.redis import RedisStorage  # requires `redis`

        return RedisStorage.from_url(settings.REDIS_URL)
    return MemoryStorage()


def create_dispatcher(
    session_factory: async_sessionmaker[AsyncSession],
    storage: BaseStorage | None = None,
) -> Dispatcher:
    # Event isolation serialises updates per user, so double taps and photo
    # albums cannot race on FSM data or balances within this process.
    dp = Dispatcher(storage=storage or MemoryStorage(), events_isolation=SimpleEventIsolation())

    subscriptions = SubscriptionChecker(
        settings.sponsor_chat_id, cache_ttl=settings.SUBSCRIPTION_CACHE_TTL
    )
    dp["subscriptions"] = subscriptions

    dp.update.outer_middleware(DbSessionMiddleware(session_factory))
    dp.update.outer_middleware(UserMiddleware())
    gate = AccessGateMiddleware(subscriptions)
    dp.message.outer_middleware(gate)
    dp.callback_query.outer_middleware(gate)

    dp.include_routers(*ROUTERS)
    return dp


async def main() -> None:
    logging.basicConfig(
        level=settings.LOG_LEVEL,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    engine, session_factory = create_engine_and_factory(settings.DATABASE_URL)
    await init_models(engine)

    bot = Bot(
        token=settings.BOT_TOKEN.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = create_dispatcher(session_factory, create_storage())

    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Start / main menu"),
            BotCommand(command="search", description="Browse profiles"),
            BotCommand(command="profile", description="My profile"),
            BotCommand(command="balance", description="Wallet and top-up"),
            BotCommand(command="cancel", description="Cancel current action"),
            BotCommand(command="help", description="Help and prices"),
        ]
    )
    if settings.PAYMENTS_MOCK:
        logger.warning("PAYMENTS_MOCK is enabled: top-ups are credited without payment")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
