"""Declarative SQLAlchemy 2.0 models."""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(AsyncAttrs, DeclarativeBase):
    pass


class Category(str, enum.Enum):
    FRIENDSHIP = "friendship"
    CHATTING = "chatting"
    INTIMATE = "intimate"


class Gender(str, enum.Enum):
    MALE = "male"
    FEMALE = "female"


class TargetGender(str, enum.Enum):
    MEN = "men"
    WOMEN = "women"
    ALL = "all"


class PMRequestStatus(str, enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ActionType(str, enum.Enum):
    SIGNUP_BONUS = "signup_bonus"
    TOP_UP = "top_up"
    VIEW_PHOTOS = "view_photos"
    VIEW_BIO = "view_bio"
    VIEW_FULL = "view_full"
    ANON_MSG = "anon_msg"
    NAMED_MSG = "named_msg"
    PM_REQUEST = "pm_request"
    REFUND = "refund"


GENDER_TO_TARGET: dict[Gender, TargetGender] = {
    Gender.MALE: TargetGender.MEN,
    Gender.FEMALE: TargetGender.WOMEN,
}
TARGET_TO_GENDER: dict[TargetGender, Gender] = {
    target: gender for gender, target in GENDER_TO_TARGET.items()
}


def _enum(cls: type[enum.Enum]) -> SAEnum:
    # Stored as plain strings (enum values) so both SQLite and Postgres
    # behave the same and adding members needs no ALTER TYPE.
    return SAEnum(
        cls,
        native_enum=False,
        length=16,
        values_callable=lambda members: [m.value for m in members],
    )


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("balance >= 0", name="ck_users_balance_non_negative"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(128))
    balance: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_verified_18: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Profile(Base):
    __tablename__ = "profiles"
    __table_args__ = (
        CheckConstraint("age >= 18", name="ck_profiles_adult"),
        Index("ix_profiles_feed", "category", "gender", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    category: Mapped[Category] = mapped_column(_enum(Category))
    gender: Mapped[Gender] = mapped_column(_enum(Gender))
    target_gender: Mapped[TargetGender] = mapped_column(_enum(TargetGender))
    age: Mapped[int] = mapped_column(Integer)
    city: Mapped[str] = mapped_column(String(64))
    bio: Mapped[str] = mapped_column(Text)
    photos: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")


class Match(Base):
    """A like. ``is_mutual`` is set on both rows once the like is returned."""

    __tablename__ = "matches"
    __table_args__ = (UniqueConstraint("liker_id", "liked_id", name="uq_matches_pair"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    liker_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    liked_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    is_mutual: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Dislike(Base):
    """A skipped profile; kept so it is never shown to the same viewer again."""

    __tablename__ = "dislikes"
    __table_args__ = (UniqueConstraint("user_id", "target_id", name="uq_dislikes_pair"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    target_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))


class ProfileUnlock(Base):
    """What a viewer has already paid to see, so nothing is charged twice."""

    __tablename__ = "profile_unlocks"
    __table_args__ = (UniqueConstraint("viewer_id", "target_id", name="uq_unlocks_pair"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    viewer_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    target_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    has_photos: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    has_bio: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")


class PMRequest(Base):
    __tablename__ = "pm_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    receiver_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[PMRequestStatus] = mapped_column(
        _enum(PMRequestStatus), default=PMRequestStatus.PENDING
    )
    # Amount actually charged, so a refund never depends on current prices.
    price_paid: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Transaction(Base):
    """Ledger entry. ``amount`` is signed: negative for spends, positive for credits."""

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    amount: Mapped[int] = mapped_column(Integer)
    action_type: Mapped[str] = mapped_column(String(32))
    # Payment provider charge id; unique so a payment is credited only once.
    external_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
