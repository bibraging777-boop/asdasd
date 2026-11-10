"""Search, profile card and PM request keyboards."""
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import settings
from database.models import Category
from keyboards.callbacks import CardCb, MenuCb, PMCb, SearchCb
from services.billing import ViewMode
from texts import CATEGORY_LABELS, MODE_LABELS


def search_category_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for category in Category:
        kb.button(
            text=CATEGORY_LABELS[category],
            callback_data=SearchCb(action="category", value=category.value),
        )
    kb.button(text="⬅️ Menu", callback_data=MenuCb(action="home"))
    return kb.adjust(1).as_markup()


def search_mode_kb() -> InlineKeyboardMarkup:
    prices = {
        ViewMode.PHOTOS: settings.PRICE_VIEW_PHOTOS_ONLY,
        ViewMode.BIO: settings.PRICE_VIEW_BIO_ONLY,
        ViewMode.FULL: settings.PRICE_VIEW_FULL_PROFILE,
    }
    kb = InlineKeyboardBuilder()
    for mode in ViewMode:
        kb.button(
            text=f"{MODE_LABELS[mode]} — {prices[mode]} cr. / profile",
            callback_data=SearchCb(action="mode", value=mode.value),
        )
    kb.button(text="⬅️ Menu", callback_data=MenuCb(action="home"))
    return kb.adjust(1).as_markup()


def contact_buttons(kb: InlineKeyboardBuilder, target_id: int) -> None:
    kb.button(
        text=f"🕶 Anonymous msg · {settings.PRICE_SEND_ANON_MSG}",
        callback_data=CardCb(action="anon", target=target_id),
    )
    kb.button(
        text=f"✍️ Named msg · {settings.PRICE_SEND_NAMED_MSG}",
        callback_data=CardCb(action="named", target=target_id),
    )
    kb.button(
        text=f"📩 Request PM / ЛС · {settings.PRICE_REQUEST_PM}",
        callback_data=CardCb(action="pm", target=target_id),
    )


def card_kb(target_id: int, *, unlock_price: int = 0) -> InlineKeyboardMarkup:
    """Interaction buttons; ``unlock_price`` > 0 adds an unlock-the-rest button."""
    kb = InlineKeyboardBuilder()
    kb.button(text="❤️", callback_data=CardCb(action="like", target=target_id))
    kb.button(text="👎", callback_data=CardCb(action="dislike", target=target_id))
    contact_buttons(kb, target_id)
    sizes = [2, 2, 1]
    if unlock_price > 0:
        kb.button(
            text=f"🔓 Unlock full profile · {unlock_price}",
            callback_data=CardCb(action="unlock", target=target_id),
        )
        sizes.append(1)
    return kb.adjust(*sizes).as_markup()


def contact_kb(target_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    contact_buttons(kb, target_id)
    return kb.adjust(2, 1).as_markup()


def pm_request_kb(request_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Accept", callback_data=PMCb(action="accept", request_id=request_id))
    kb.button(text="❌ Reject", callback_data=PMCb(action="reject", request_id=request_id))
    return kb.adjust(2).as_markup()
