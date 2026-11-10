"""Registration flow keyboards."""
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.models import Category, Gender, TargetGender
from keyboards.callbacks import RegCb
from texts import CATEGORY_LABELS, GENDER_LABELS, TARGET_LABELS


def category_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for category in Category:
        kb.button(
            text=CATEGORY_LABELS[category],
            callback_data=RegCb(field="category", value=category.value),
        )
    return kb.adjust(1).as_markup()


def gender_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for gender in Gender:
        kb.button(
            text=GENDER_LABELS[gender], callback_data=RegCb(field="gender", value=gender.value)
        )
    return kb.adjust(2).as_markup()


def target_gender_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for target in TargetGender:
        kb.button(
            text=TARGET_LABELS[target], callback_data=RegCb(field="target", value=target.value)
        )
    return kb.adjust(3).as_markup()


def photos_done_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Done", callback_data=RegCb(field="photos", value="done"))
    return kb.as_markup()
