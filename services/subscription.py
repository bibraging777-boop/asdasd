"""Sponsor channel membership check (OP-check)."""
from __future__ import annotations

import logging
import time

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ChatMemberRestricted

logger = logging.getLogger(__name__)

_MEMBER_STATUSES = {
    ChatMemberStatus.MEMBER,
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.CREATOR,
}


class SubscriptionChecker:
    def __init__(self, channel_id: int | str | None, cache_ttl: int = 300) -> None:
        self._channel_id = channel_id
        self._ttl = cache_ttl
        # Only positive results are cached, so joining takes effect immediately.
        self._confirmed_until: dict[int, float] = {}

    @property
    def enabled(self) -> bool:
        return self._channel_id is not None

    async def is_subscribed(self, bot: Bot, telegram_id: int) -> bool:
        if self._channel_id is None:
            return True
        now = time.monotonic()
        if self._confirmed_until.get(telegram_id, 0.0) > now:
            return True
        try:
            member = await bot.get_chat_member(self._channel_id, telegram_id)
        except TelegramAPIError:
            # Usually a misconfiguration (bot is not a channel admin). Fail
            # open so a broken channel setup does not lock every user out.
            logger.exception("Subscription check failed for channel %s", self._channel_id)
            return True
        subscribed = member.status in _MEMBER_STATUSES or (
            isinstance(member, ChatMemberRestricted) and member.is_member
        )
        if subscribed:
            self._confirmed_until[telegram_id] = now + self._ttl
        else:
            self._confirmed_until.pop(telegram_id, None)
        return subscribed
