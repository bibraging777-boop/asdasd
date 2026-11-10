"""Search feed: category / view-mode selection and paid profile cards."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InputMediaPhoto, Message
from sqlalchemy.ext.asyncio import AsyncSession

import texts
from database import repo
from database.models import Category, Profile, User
from keyboards.callbacks import CardCb, MenuCb, SearchCb
from keyboards.common import main_menu_kb
from keyboards.search import card_kb, search_category_kb, search_mode_kb
from services import billing
from services.billing import InsufficientFunds, ViewMode
from utils.messaging import send_top_up_prompt, strip_keyboard

router = Router(name="search")

CATEGORY_KEY = "search_category"
MODE_KEY = "search_mode"


async def _ask_category(bot: Bot, chat_id: int) -> None:
    await bot.send_message(
        chat_id, "🔍 <b>Search</b>\nWho are you looking for?", reply_markup=search_category_kb()
    )


async def _start_search(bot: Bot, session: AsyncSession, user: User) -> None:
    if await repo.get_profile(session, user.id) is None:
        await bot.send_message(user.telegram_id, "Create your profile first: /start")
        return
    await _ask_category(bot, user.telegram_id)


@router.message(Command("search"))
async def cmd_search(message: Message, session: AsyncSession, user: User, bot: Bot) -> None:
    await _start_search(bot, session, user)


@router.callback_query(MenuCb.filter(F.action == "search"))
async def menu_search(
    callback: CallbackQuery, session: AsyncSession, user: User, bot: Bot
) -> None:
    await callback.answer()
    await _start_search(bot, session, user)


@router.callback_query(SearchCb.filter(F.action == "category"))
async def choose_category(
    callback: CallbackQuery, callback_data: SearchCb, state: FSMContext
) -> None:
    try:
        category = Category(callback_data.value)
    except ValueError:
        await callback.answer("Unknown option.", show_alert=True)
        return
    await state.update_data({CATEGORY_KEY: category.value})
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            f"Category: {texts.CATEGORY_LABELS[category]}\n\n"
            "Choose how to browse. You are charged per profile shown; anything "
            "you already unlocked is never charged twice.",
            reply_markup=search_mode_kb(),
        )


@router.callback_query(SearchCb.filter(F.action == "mode"))
async def choose_mode(
    callback: CallbackQuery,
    callback_data: SearchCb,
    state: FSMContext,
    session: AsyncSession,
    user: User,
    bot: Bot,
) -> None:
    try:
        mode = ViewMode(callback_data.value)
    except ValueError:
        await callback.answer("Unknown option.", show_alert=True)
        return
    await state.update_data({MODE_KEY: mode.value})
    await callback.answer()
    await strip_keyboard(callback)
    await show_next(bot, session, state, user)


async def send_card(
    bot: Bot,
    chat_id: int,
    profile: Profile,
    *,
    show_photos: bool,
    show_bio: bool,
    reply_markup: InlineKeyboardMarkup,
    footer: str = "",
) -> None:
    text = texts.card_text(profile, show_photos=show_photos, show_bio=show_bio, footer=footer)
    photos = profile.photos if show_photos else []
    if not photos:
        await bot.send_message(chat_id, text, reply_markup=reply_markup)
    elif len(photos) == 1:
        await bot.send_photo(chat_id, photos[0], caption=text, reply_markup=reply_markup)
    else:
        # Albums cannot carry an inline keyboard, so the card text follows them.
        await bot.send_media_group(chat_id, [InputMediaPhoto(media=p) for p in photos])
        await bot.send_message(chat_id, text, reply_markup=reply_markup)


def _footer(price: int, balance: int) -> str:
    spent = f"−{price} credits · " if price else "already unlocked · "
    return f"<i>{spent}balance {balance}</i>"


async def _charge_and_show(
    bot: Bot, session: AsyncSession, user: User, candidate: Profile, mode: ViewMode
) -> bool:
    """Charge for what ``mode`` newly reveals, then send the card."""
    unlock = await repo.get_unlock(session, user.id, candidate.user_id)
    has_photos = bool(unlock and unlock.has_photos)
    has_bio = bool(unlock and unlock.has_bio)
    price, action = billing.view_cost(mode, has_photos=has_photos, has_bio=has_bio)
    try:
        await billing.charge(session, user, price, action)
    except InsufficientFunds as error:
        await send_top_up_prompt(bot, user.telegram_id, error)
        return False

    unlock = await repo.grant_unlock(
        session,
        user.id,
        candidate.user_id,
        photos=mode in (ViewMode.PHOTOS, ViewMode.FULL),
        bio=mode in (ViewMode.BIO, ViewMode.FULL),
    )
    # Persist charge + unlock before sending: if delivery fails the user can
    # simply re-open the profile for free.
    await session.commit()

    remaining, _ = billing.view_cost(
        ViewMode.FULL, has_photos=unlock.has_photos, has_bio=unlock.has_bio
    )
    await send_card(
        bot,
        user.telegram_id,
        candidate,
        show_photos=unlock.has_photos,
        show_bio=unlock.has_bio,
        reply_markup=card_kb(candidate.user_id, unlock_price=remaining),
        footer=_footer(price, user.balance),
    )
    return True


async def show_next(bot: Bot, session: AsyncSession, state: FSMContext, user: User) -> None:
    """Show the next candidate for the user's saved search filters."""
    profile = await repo.get_profile(session, user.id)
    if profile is None:
        await bot.send_message(user.telegram_id, "Create your profile first: /start")
        return
    data = await state.get_data()
    try:
        category = Category(data[CATEGORY_KEY])
        mode = ViewMode(data[MODE_KEY])
    except (KeyError, ValueError):
        await _ask_category(bot, user.telegram_id)
        return

    candidate = await repo.next_candidate(session, profile, category)
    if candidate is None:
        await bot.send_message(
            user.telegram_id,
            "😔 No more profiles for these filters right now. Try another "
            "category or come back later.",
            reply_markup=main_menu_kb(),
        )
        return
    await _charge_and_show(bot, session, user, candidate, mode)


@router.callback_query(CardCb.filter(F.action == "unlock"))
async def unlock_rest(
    callback: CallbackQuery,
    callback_data: CardCb,
    session: AsyncSession,
    user: User,
    bot: Bot,
) -> None:
    reachable = await repo.get_reachable_target(session, user.id, callback_data.target)
    if reachable is None:
        await callback.answer("This profile is no longer available.", show_alert=True)
        return
    await callback.answer()
    _, candidate = reachable
    if await _charge_and_show(bot, session, user, candidate, ViewMode.FULL):
        await strip_keyboard(callback)
