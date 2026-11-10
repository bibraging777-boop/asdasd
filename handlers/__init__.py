"""Handler routers, in dispatch order."""
from __future__ import annotations

from aiogram import Router

from handlers import errors, interactions, registration, search, start, wallet

ROUTERS: tuple[Router, ...] = (
    errors.router,
    wallet.router,  # payment confirmations first, regardless of FSM state
    start.router,  # commands take priority over FSM text input
    registration.router,
    search.router,
    interactions.router,
    errors.fallback_router,
)
