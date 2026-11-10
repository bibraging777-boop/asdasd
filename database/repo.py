"""Query helpers shared by handlers and middlewares."""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.models import (
    GENDER_TO_TARGET,
    TARGET_TO_GENDER,
    ActionType,
    Category,
    Dislike,
    Match,
    PMRequest,
    PMRequestStatus,
    Profile,
    ProfileUnlock,
    TargetGender,
    Transaction,
    User,
)


async def get_or_create_user(
    session: AsyncSession, telegram_id: int, username: str | None, first_name: str | None
) -> User:
    stmt = select(User).where(User.telegram_id == telegram_id)
    user = await session.scalar(stmt)
    if user is None:
        try:
            async with session.begin_nested():
                user = User(
                    telegram_id=telegram_id,
                    username=username,
                    first_name=first_name,
                    balance=settings.STARTING_BALANCE,
                )
                session.add(user)
                await session.flush()
                if settings.STARTING_BALANCE:
                    session.add(
                        Transaction(
                            user_id=user.id,
                            amount=settings.STARTING_BALANCE,
                            action_type=ActionType.SIGNUP_BONUS.value,
                        )
                    )
        except IntegrityError:
            # Lost a race with a concurrent first update from the same user.
            user = (await session.execute(stmt)).scalar_one()
    elif user.username != username or user.first_name != first_name:
        user.username = username
        user.first_name = first_name
    return user


async def get_profile(session: AsyncSession, user_id: int) -> Profile | None:
    return await session.scalar(select(Profile).where(Profile.user_id == user_id))


async def upsert_profile(session: AsyncSession, user_id: int, **fields: Any) -> Profile:
    profile = await get_profile(session, user_id)
    if profile is None:
        profile = Profile(user_id=user_id, **fields)
        session.add(profile)
    else:
        for key, value in fields.items():
            setattr(profile, key, value)
    profile.is_active = True
    await session.flush()
    return profile


async def next_candidate(
    session: AsyncSession, viewer: Profile, category: Category
) -> Profile | None:
    """Random active profile matching the filters that the viewer has not rated."""
    liked = select(Match.id).where(
        Match.liker_id == viewer.user_id, Match.liked_id == Profile.user_id
    )
    disliked = select(Dislike.id).where(
        Dislike.user_id == viewer.user_id, Dislike.target_id == Profile.user_id
    )
    stmt = (
        select(Profile)
        .join(User, User.id == Profile.user_id)
        .where(
            Profile.is_active.is_(True),
            User.is_banned.is_(False),
            User.is_verified_18.is_(True),
            Profile.user_id != viewer.user_id,
            Profile.category == category,
            # The candidate must also be looking for the viewer's gender.
            Profile.target_gender.in_([TargetGender.ALL, GENDER_TO_TARGET[viewer.gender]]),
            ~liked.exists(),
            ~disliked.exists(),
        )
    )
    if viewer.target_gender is not TargetGender.ALL:
        stmt = stmt.where(Profile.gender == TARGET_TO_GENDER[viewer.target_gender])
    return await session.scalar(stmt.order_by(func.random()).limit(1))


async def get_unlock(
    session: AsyncSession, viewer_id: int, target_id: int
) -> ProfileUnlock | None:
    return await session.scalar(
        select(ProfileUnlock).where(
            ProfileUnlock.viewer_id == viewer_id, ProfileUnlock.target_id == target_id
        )
    )


async def grant_unlock(
    session: AsyncSession, viewer_id: int, target_id: int, *, photos: bool, bio: bool
) -> ProfileUnlock:
    unlock = await get_unlock(session, viewer_id, target_id)
    if unlock is None:
        unlock = ProfileUnlock(
            viewer_id=viewer_id, target_id=target_id, has_photos=False, has_bio=False
        )
        session.add(unlock)
    unlock.has_photos = unlock.has_photos or photos
    unlock.has_bio = unlock.has_bio or bio
    await session.flush()
    return unlock


async def get_reachable_target(
    session: AsyncSession, viewer_id: int, target_id: int
) -> tuple[User, Profile] | None:
    """Target user + profile, only if the viewer was actually shown that profile.

    Callback data is client-controlled, so interactions are limited to
    profiles the viewer has paid to see.
    """
    if viewer_id == target_id:
        return None
    unlock = await get_unlock(session, viewer_id, target_id)
    if unlock is None or not (unlock.has_photos or unlock.has_bio):
        return None
    target = await session.get(User, target_id)
    profile = await get_profile(session, target_id)
    if target is None or profile is None or target.is_banned or not profile.is_active:
        return None
    return target, profile


async def add_like(session: AsyncSession, liker_id: int, liked_id: int) -> bool:
    """Record a like. Returns True when it completes a mutual match."""
    existing = await session.scalar(
        select(Match).where(Match.liker_id == liker_id, Match.liked_id == liked_id)
    )
    if existing is not None:
        return False
    reverse = await session.scalar(
        select(Match).where(Match.liker_id == liked_id, Match.liked_id == liker_id)
    )
    if reverse is not None:
        reverse.is_mutual = True
    session.add(Match(liker_id=liker_id, liked_id=liked_id, is_mutual=reverse is not None))
    await session.flush()
    return reverse is not None


async def add_dislike(session: AsyncSession, user_id: int, target_id: int) -> None:
    existing = await session.scalar(
        select(Dislike.id).where(Dislike.user_id == user_id, Dislike.target_id == target_id)
    )
    if existing is None:
        session.add(Dislike(user_id=user_id, target_id=target_id))
        await session.flush()


async def has_pending_pm_request(
    session: AsyncSession, sender_id: int, receiver_id: int
) -> bool:
    found = await session.scalar(
        select(PMRequest.id).where(
            PMRequest.sender_id == sender_id,
            PMRequest.receiver_id == receiver_id,
            PMRequest.status == PMRequestStatus.PENDING,
        )
    )
    return found is not None


async def resolve_pm_request(
    session: AsyncSession, request_id: int, receiver_id: int, status: PMRequestStatus
) -> PMRequest | None:
    """Atomically move a pending request to ``status``; None if not pending/owned."""
    result = await session.execute(
        update(PMRequest)
        .where(
            PMRequest.id == request_id,
            PMRequest.receiver_id == receiver_id,
            PMRequest.status == PMRequestStatus.PENDING,
        )
        .values(status=status)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:  # type: ignore[attr-defined]
        return None
    request = await session.get(PMRequest, request_id)
    if request is not None:
        await session.refresh(request)
    return request
