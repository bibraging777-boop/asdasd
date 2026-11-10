"""Entry point handlers: age gate, subscription check, menu, own profile."""
from __future__ import annotations

import random
from contextlib import suppress

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

import texts
from database import repo
from database.models import User
from handlers.registration import begin_registration
from keyboards.callbacks import SUBSCRIPTION_CHECK, AgeCb, MenuCb
from keyboards.common import captcha_kb, main_menu_kb, profile_kb
from services.subscription import SubscriptionChecker
from utils.messaging import send_subscription_prompt, strip_keyboard

router = Router(name="start")

CAPTCHA_KEY = "captcha_answer"


def _new_captcha() -> tuple[str, int, list[int]]:
    a, b = random.randint(2, 9), random.randint(2, 9)
    answer = a + b
    options = {answer}
    while len(options) < 4:
        options.add(max(1, answer + random.choice((-3, -2, -1, 1, 2, 3))))
    shuffled = list(options)
    random.shuffle(shuffled)
    return f"{a} + {b}", answer, shuffled


async def _edit(callback: CallbackQuery, text: str, **kwargs: object) -> None:
    if isinstance(callback.message, Message):
        with suppress(TelegramBadRequest):
            await callback.message.edit_text(text, **kwargs)  # type: ignore[arg-type]


async def send_main_menu(bot: Bot, user: User) -> None:
    await bot.send_message(
        user.telegram_id,
        f"🏠 <b>Main menu</b>\n💰 Balance: {user.balance} credits",
        reply_markup=main_menu_kb(),
    )


async def enter(bot: Bot, session: AsyncSession, state: FSMContext, user: User) -> None:
    """Route a verified, subscribed user to registration or the main menu."""
    if await repo.get_profile(session, user.id) is None:
        await begin_registration(bot, user.telegram_id, state)
    else:
        await state.set_state(None)
        await send_main_menu(bot, user)


# --- 18+ gate ---------------------------------------------------------------


@router.callback_query(AgeCb.filter(F.action == "minor"))
async def age_minor(callback: CallbackQuery, user: User) -> None:
    if not user.is_verified_18:
        user.is_banned = True
        await _edit(callback, texts.MINOR_BLOCKED)
    await callback.answer()


@router.callback_query(AgeCb.filter(F.action == "confirm"))
async def age_confirm(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await callback.answer()
    if user.is_verified_18:
        return
    question, answer, options = _new_captcha()
    await state.update_data({CAPTCHA_KEY: answer})
    await _edit(
        callback,
        f"🤖 One more step — prove you are human.\n\n<b>{question} = ?</b>",
        reply_markup=captcha_kb(options),
    )


@router.callback_query(AgeCb.filter(F.action == "answer"))
async def age_captcha_answer(
    callback: CallbackQuery,
    callback_data: AgeCb,
    state: FSMContext,
    session: AsyncSession,
    user: User,
    bot: Bot,
    subscriptions: SubscriptionChecker,
) -> None:
    if user.is_verified_18:
        await callback.answer()
        return
    expected = (await state.get_data()).get(CAPTCHA_KEY)
    if expected is None or callback_data.value != expected:
        question, answer, options = _new_captcha()
        await state.update_data({CAPTCHA_KEY: answer})
        await callback.answer("Wrong answer, try again.")
        await _edit(
            callback,
            f"❌ Wrong answer. Try again.\n\n<b>{question} = ?</b>",
            reply_markup=captcha_kb(options),
        )
        return

    user.is_verified_18 = True
    await session.commit()
    await state.update_data({CAPTCHA_KEY: None})
    await callback.answer("Verified")
    await _edit(callback, "✅ Age confirmed. Welcome!")

    if await subscriptions.is_subscribed(bot, user.telegram_id):
        await enter(bot, session, state, user)
    else:
        await send_subscription_prompt(bot, user.telegram_id)


# --- Subscription gate ------------------------------------------------------


@router.callback_query(F.data == SUBSCRIPTION_CHECK)
async def subscription_confirmed(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, user: User, bot: Bot
) -> None:
    # Only reached when the gate middleware has confirmed the subscription.
    await callback.answer("Subscription confirmed ✅")
    await strip_keyboard(callback)
    await enter(bot, session, state, user)


# --- Commands & menu --------------------------------------------------------


@router.message(CommandStart())
async def cmd_start(
    message: Message, state: FSMContext, session: AsyncSession, user: User, bot: Bot
) -> None:
    await enter(bot, session, state, user)


@router.message(Command("menu"))
async def cmd_menu(
    message: Message, state: FSMContext, session: AsyncSession, user: User, bot: Bot
) -> None:
    await enter(bot, session, state, user)


@router.message(Command("cancel"))
async def cmd_cancel(
    message: Message, state: FSMContext, session: AsyncSession, user: User, bot: Bot
) -> None:
    if await state.get_state() is None:
        await message.answer("Nothing to cancel.")
    else:
        await state.set_state(None)
        await message.answer("Cancelled.")
    if await repo.get_profile(session, user.id) is None:
        await message.answer("Send /start whenever you want to create your profile.")
    else:
        await send_main_menu(bot, user)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "/menu — main menu\n/search — browse profiles\n/profile — your profile\n"
        "/balance — wallet and top-up\n/cancel — cancel the current action\n\n"
        + texts.price_list()
    )


@router.callback_query(MenuCb.filter(F.action == "home"))
async def menu_home(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, user: User, bot: Bot
) -> None:
    await callback.answer()
    await enter(bot, session, state, user)


async def _show_own_profile(bot: Bot, session: AsyncSession, state: FSMContext, user: User) -> None:
    profile = await repo.get_profile(session, user.id)
    if profile is None:
        await begin_registration(bot, user.telegram_id, state)
        return
    text = texts.own_profile_text(profile)
    markup = profile_kb(profile.is_active)
    if profile.photos:
        await bot.send_photo(
            user.telegram_id, profile.photos[0], caption=text, reply_markup=markup
        )
    else:
        await bot.send_message(user.telegram_id, text, reply_markup=markup)


@router.message(Command("profile"))
async def cmd_profile(
    message: Message, state: FSMContext, session: AsyncSession, user: User, bot: Bot
) -> None:
    await _show_own_profile(bot, session, state, user)


@router.callback_query(MenuCb.filter(F.action == "profile"))
async def menu_profile(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, user: User, bot: Bot
) -> None:
    await callback.answer()
    await _show_own_profile(bot, session, state, user)


@router.callback_query(MenuCb.filter(F.action == "edit"))
async def menu_edit_profile(
    callback: CallbackQuery, state: FSMContext, user: User, bot: Bot
) -> None:
    await callback.answer()
    await strip_keyboard(callback)
    await begin_registration(bot, user.telegram_id, state)


@router.callback_query(MenuCb.filter(F.action == "toggle"))
async def menu_toggle_profile(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    profile = await repo.get_profile(session, user.id)
    if profile is None:
        await callback.answer("Create a profile first: /start", show_alert=True)
        return
    profile.is_active = not profile.is_active
    await session.commit()
    await callback.answer(
        "Profile is visible in search." if profile.is_active else "Profile is hidden."
    )
    if isinstance(callback.message, Message):
        with suppress(TelegramBadRequest):
            await callback.message.edit_reply_markup(reply_markup=profile_kb(profile.is_active))
