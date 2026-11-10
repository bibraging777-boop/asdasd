"""Gate, menu and wallet keyboards."""
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import settings
from keyboards.callbacks import SUBSCRIPTION_CHECK, AgeCb, BuyCb, MenuCb


def age_gate_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ I am 18 or older", callback_data=AgeCb(action="confirm"))
    kb.button(text="🚫 I am under 18", callback_data=AgeCb(action="minor"))
    return kb.adjust(1).as_markup()


def captcha_kb(options: list[int]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for option in options:
        kb.button(text=str(option), callback_data=AgeCb(action="answer", value=option))
    return kb.adjust(len(options)).as_markup()


def subscription_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if settings.sponsor_url:
        kb.button(text="📢 Join the channel", url=settings.sponsor_url)
    kb.button(text="🔄 Check subscription", callback_data=SUBSCRIPTION_CHECK)
    return kb.adjust(1).as_markup()


def main_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔍 Search", callback_data=MenuCb(action="search"))
    kb.button(text="👤 My profile", callback_data=MenuCb(action="profile"))
    kb.button(text="💰 Wallet", callback_data=MenuCb(action="wallet"))
    return kb.adjust(1, 2).as_markup()


def profile_kb(is_active: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✏️ Fill in again", callback_data=MenuCb(action="edit"))
    kb.button(
        text="⏸ Hide from search" if is_active else "▶️ Show in search",
        callback_data=MenuCb(action="toggle"),
    )
    kb.button(text="⬅️ Menu", callback_data=MenuCb(action="home"))
    return kb.adjust(1).as_markup()


def top_up_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for index, (coins, stars) in enumerate(settings.COIN_PACKAGES):
        kb.button(text=f"💎 {coins} credits — {stars} ⭐", callback_data=BuyCb(package=index))
    kb.button(text="⬅️ Menu", callback_data=MenuCb(action="home"))
    return kb.adjust(1).as_markup()
