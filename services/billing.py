"""Coin balance operations. Every change is mirrored in ``transactions``."""
from __future__ import annotations

import enum

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.models import ActionType, Transaction, User


class InsufficientFunds(Exception):
    def __init__(self, price: int, balance: int) -> None:
        super().__init__(f"need {price}, have {balance}")
        self.price = price
        self.balance = balance


class ViewMode(str, enum.Enum):
    PHOTOS = "photos"
    BIO = "bio"
    FULL = "full"


def view_cost(mode: ViewMode, *, has_photos: bool, has_bio: bool) -> tuple[int, ActionType]:
    """Price of showing a profile in ``mode`` given what is already unlocked."""
    need_photos = mode in (ViewMode.PHOTOS, ViewMode.FULL) and not has_photos
    need_bio = mode in (ViewMode.BIO, ViewMode.FULL) and not has_bio
    if need_photos and need_bio:
        return settings.PRICE_VIEW_FULL_PROFILE, ActionType.VIEW_FULL
    if need_photos:
        return settings.PRICE_VIEW_PHOTOS_ONLY, ActionType.VIEW_PHOTOS
    if need_bio:
        return settings.PRICE_VIEW_BIO_ONLY, ActionType.VIEW_BIO
    return 0, ActionType.VIEW_FULL


async def charge(session: AsyncSession, user: User, price: int, action: ActionType) -> None:
    """Deduct ``price`` coins or raise :class:`InsufficientFunds`.

    The guarded UPDATE makes the check-and-deduct atomic, so concurrent
    actions can never overdraw the balance. The caller commits.
    """
    if price <= 0:
        return
    result = await session.execute(
        update(User)
        .where(User.id == user.id, User.balance >= price)
        .values(balance=User.balance - price)
        .execution_options(synchronize_session=False)
    )
    await session.refresh(user, attribute_names=["balance"])
    if result.rowcount != 1:  # type: ignore[attr-defined]
        raise InsufficientFunds(price, user.balance)
    session.add(Transaction(user_id=user.id, amount=-price, action_type=action.value))
    await session.flush()


async def credit(
    session: AsyncSession,
    user: User,
    amount: int,
    action: ActionType,
    external_id: str | None = None,
) -> bool:
    """Add coins. Returns False if ``external_id`` was already credited."""
    if amount <= 0:
        return False
    if external_id is not None:
        seen = await session.scalar(
            select(Transaction.id).where(Transaction.external_id == external_id)
        )
        if seen is not None:
            return False
    await session.execute(
        update(User)
        .where(User.id == user.id)
        .values(balance=User.balance + amount)
        .execution_options(synchronize_session=False)
    )
    session.add(
        Transaction(
            user_id=user.id, amount=amount, action_type=action.value, external_id=external_id
        )
    )
    await session.flush()
    await session.refresh(user, attribute_names=["balance"])
    return True
