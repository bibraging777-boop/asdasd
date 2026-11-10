"""Profile registration FSM: category → gender → preference → age → city → bio → photos."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

import texts
from config import settings
from database import repo
from database.models import Category, Gender, TargetGender, User
from keyboards.callbacks import RegCb
from keyboards.common import top_up_kb
from keyboards.registration import category_kb, gender_kb, photos_done_kb, target_gender_kb
from states import Registration
from utils.messaging import strip_keyboard

router = Router(name="registration")

# Plain text that is not a bot command.
TEXT_INPUT = F.text & ~F.text.startswith("/")


async def begin_registration(bot: Bot, chat_id: int, state: FSMContext) -> None:
    await state.set_state(Registration.category)
    await state.update_data(reg={})
    await bot.send_message(
        chat_id,
        "📝 <b>Let's create your profile</b> (free).\n\n"
        "<b>Step 1/5.</b> What are you looking for?",
        reply_markup=category_kb(),
    )


async def _save(state: FSMContext, **fields: object) -> dict[str, object]:
    reg = dict((await state.get_data()).get("reg") or {})
    reg.update(fields)
    await state.update_data(reg=reg)
    return reg


@router.callback_query(Registration.category, RegCb.filter(F.field == "category"))
async def set_category(callback: CallbackQuery, callback_data: RegCb, state: FSMContext) -> None:
    try:
        category = Category(callback_data.value)
    except ValueError:
        await callback.answer("Unknown option.", show_alert=True)
        return
    await _save(state, category=category.value)
    await state.set_state(Registration.gender)
    await callback.answer()
    await strip_keyboard(callback)
    if callback.message:
        await callback.message.answer(
            f"Goal: {texts.CATEGORY_LABELS[category]}\n\n<b>Step 2/5.</b> Who are you?",
            reply_markup=gender_kb(),
        )


@router.callback_query(Registration.gender, RegCb.filter(F.field == "gender"))
async def set_gender(callback: CallbackQuery, callback_data: RegCb, state: FSMContext) -> None:
    try:
        gender = Gender(callback_data.value)
    except ValueError:
        await callback.answer("Unknown option.", show_alert=True)
        return
    await _save(state, gender=gender.value)
    await state.set_state(Registration.target_gender)
    await callback.answer()
    await strip_keyboard(callback)
    if callback.message:
        await callback.message.answer(
            "Who would you like to meet?", reply_markup=target_gender_kb()
        )


@router.callback_query(Registration.target_gender, RegCb.filter(F.field == "target"))
async def set_target_gender(
    callback: CallbackQuery, callback_data: RegCb, state: FSMContext
) -> None:
    try:
        target = TargetGender(callback_data.value)
    except ValueError:
        await callback.answer("Unknown option.", show_alert=True)
        return
    await _save(state, target_gender=target.value)
    await state.set_state(Registration.age)
    await callback.answer()
    await strip_keyboard(callback)
    if callback.message:
        await callback.message.answer(
            f"<b>Step 3/5.</b> How old are you? Send a number "
            f"({settings.MIN_AGE}–{settings.MAX_AGE})."
        )


@router.message(Registration.age, TEXT_INPUT)
async def set_age(message: Message, state: FSMContext, user: User) -> None:
    raw = (message.text or "").strip()
    if not raw.isdecimal() or len(raw) > 3:
        await message.answer("Please send your age as a number, e.g. 25.")
        return
    age = int(raw)
    if age < settings.MIN_AGE:
        # A self-declared minor is blocked outright; committed by the session middleware.
        user.is_banned = True
        await state.clear()
        await message.answer(texts.MINOR_BLOCKED)
        return
    if age > settings.MAX_AGE:
        await message.answer(f"Please enter an age up to {settings.MAX_AGE}.")
        return
    await _save(state, age=age)
    await state.set_state(Registration.city)
    await message.answer("Which city are you in?")


@router.message(Registration.city, TEXT_INPUT)
async def set_city(message: Message, state: FSMContext) -> None:
    city = " ".join((message.text or "").split())
    if not 2 <= len(city) <= settings.CITY_MAX_LENGTH:
        await message.answer(
            f"City name must be 2–{settings.CITY_MAX_LENGTH} characters. Try again."
        )
        return
    await _save(state, city=city)
    await state.set_state(Registration.bio)
    await message.answer(
        "<b>Step 4/5.</b> Tell about yourself: lifestyle, preferences, what you "
        f"are looking for ({settings.BIO_MIN_LENGTH}–{settings.BIO_MAX_LENGTH} characters)."
    )


@router.message(Registration.bio, TEXT_INPUT)
async def set_bio(message: Message, state: FSMContext) -> None:
    bio = (message.text or "").strip()
    if not settings.BIO_MIN_LENGTH <= len(bio) <= settings.BIO_MAX_LENGTH:
        await message.answer(
            f"The description must be {settings.BIO_MIN_LENGTH}–{settings.BIO_MAX_LENGTH} "
            f"characters (yours is {len(bio)}). Try again."
        )
        return
    await _save(state, bio=bio, photos=[])
    await state.set_state(Registration.photos)
    await message.answer(
        f"<b>Step 5/5.</b> Send 1–{settings.MAX_PHOTOS} photos (as photos, not files)."
    )


@router.message(Registration.photos, F.photo)
async def add_photo(
    message: Message, state: FSMContext, session: AsyncSession, user: User, bot: Bot
) -> None:
    assert message.photo  # guaranteed by the F.photo filter
    reg = dict((await state.get_data()).get("reg") or {})
    photos = list(reg.get("photos") or [])
    if len(photos) >= settings.MAX_PHOTOS:
        return
    photos.append(message.photo[-1].file_id)  # largest size
    await _save(state, photos=photos)
    if len(photos) >= settings.MAX_PHOTOS:
        await _finish(bot, session, state, user)
        return
    await message.answer(
        f"Photo {len(photos)}/{settings.MAX_PHOTOS} saved. Send more or press Done.",
        reply_markup=photos_done_kb(),
    )


@router.callback_query(Registration.photos, RegCb.filter(F.field == "photos"))
async def photos_done(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, user: User, bot: Bot
) -> None:
    reg = (await state.get_data()).get("reg") or {}
    if not reg.get("photos"):
        await callback.answer("Send at least one photo first.", show_alert=True)
        return
    await callback.answer()
    await strip_keyboard(callback)
    await _finish(bot, session, state, user)


async def _finish(bot: Bot, session: AsyncSession, state: FSMContext, user: User) -> None:
    reg = (await state.get_data()).get("reg") or {}
    try:
        fields = {
            "category": Category(reg["category"]),
            "gender": Gender(reg["gender"]),
            "target_gender": TargetGender(reg["target_gender"]),
            "age": int(reg["age"]),
            "city": str(reg["city"]),
            "bio": str(reg["bio"]),
            "photos": list(reg["photos"]),
        }
    except (KeyError, ValueError, TypeError):
        # FSM data was lost (e.g. storage restart): start over cleanly.
        await bot.send_message(user.telegram_id, "Something went wrong, let's start again.")
        await begin_registration(bot, user.telegram_id, state)
        return

    profile = await repo.upsert_profile(session, user.id, **fields)
    await session.commit()
    await state.clear()

    await bot.send_message(
        user.telegram_id, "✅ Profile saved!\n\n" + texts.own_profile_text(profile)
    )
    await bot.send_message(
        user.telegram_id,
        "🎉 <b>Free onboarding is complete.</b>\n\n"
        "From now on, viewing profiles and contacting people costs credits.\n\n"
        f"💰 Your balance: <b>{user.balance} credits</b>\n\n"
        f"{texts.price_list()}\n\n"
        "Top up below or open the menu to start searching.",
        reply_markup=top_up_kb(),
    )


@router.message(StateFilter(Registration))
async def unexpected_input(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    if current == Registration.photos.state:
        hint = "Please send a photo (as a photo, not a file)."
    elif current in {
        Registration.category.state,
        Registration.gender.state,
        Registration.target_gender.state,
    }:
        hint = "Please use the buttons above."
    else:
        hint = "Please send a text message."
    await message.answer(f"{hint}\nSend /cancel to stop registration.")
