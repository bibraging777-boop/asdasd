"""FSM state groups."""
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class Registration(StatesGroup):
    category = State()
    gender = State()
    target_gender = State()
    age = State()
    city = State()
    bio = State()
    photos = State()


class Interaction(StatesGroup):
    writing_message = State()
