"""Typed callback data factories."""
from __future__ import annotations

from aiogram.filters.callback_data import CallbackData

# Prefixes the access gate lets through before verification / subscription.
AGE_PREFIX = "age"
SUBSCRIPTION_CHECK = "sub:check"


class AgeCb(CallbackData, prefix=AGE_PREFIX):
    action: str  # confirm | minor | answer
    value: int = 0


class RegCb(CallbackData, prefix="reg"):
    field: str  # category | gender | target | photos
    value: str


class MenuCb(CallbackData, prefix="menu"):
    action: str  # home | search | profile | edit | toggle | wallet


class SearchCb(CallbackData, prefix="srch"):
    action: str  # category | mode
    value: str


class CardCb(CallbackData, prefix="card"):
    # like | dislike | anon | named | pm | unlock
    action: str
    target: int  # internal users.id, never a Telegram id


class PMCb(CallbackData, prefix="pm"):
    action: str  # accept | reject
    request_id: int


class BuyCb(CallbackData, prefix="buy"):
    package: int
