"""End-to-end flow through the real dispatcher with a fake Telegram API."""

from __future__ import annotations

import asyncio
import datetime as dt
import re
from collections.abc import AsyncGenerator
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.methods import GetChatMember, SendMediaGroup, SendMessage, SendPhoto, TelegramMethod
from aiogram.types import (
    CallbackQuery,
    Chat,
    ChatMemberLeft,
    ChatMemberMember,
    Message,
    PhotoSize,
    SuccessfulPayment,
    Update,
)
from aiogram.types import (
    User as TgUser,
)
from sqlalchemy import func, select

from database.engine import create_engine_and_factory, init_models
from database.models import Match, PMRequest, PMRequestStatus, Profile, Transaction, User
from keyboards.callbacks import SUBSCRIPTION_CHECK, AgeCb, CardCb, MenuCb, PMCb, RegCb, SearchCb
from main import create_dispatcher

ALICE, BOB = 1001, 1002


class FakeSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod[Any]] = []
        self.subscribed: set[int] = set()

    async def close(self) -> None:
        pass

    async def stream_content(self, *args: Any, **kwargs: Any) -> AsyncGenerator[bytes, None]:
        yield b""

    async def make_request(
        self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None
    ) -> Any:
        self.calls.append(method)
        if isinstance(method, GetChatMember):
            tg = TgUser(id=method.user_id, is_bot=False, first_name="x")
            cls = ChatMemberMember if method.user_id in self.subscribed else ChatMemberLeft
            return cls(user=tg)
        message = Message(
            message_id=len(self.calls),
            date=dt.datetime.now(dt.timezone.utc),
            chat=Chat(id=getattr(method, "chat_id", None) or 0, type="private"),
        )
        if isinstance(method, SendMediaGroup):
            return [message]
        if isinstance(method, (SendMessage, SendPhoto)):
            return message
        return True

    def texts_to(self, chat_id: int) -> list[str]:
        out = []
        for call in self.calls:
            if isinstance(call, (SendMessage, SendPhoto)) and call.chat_id == chat_id:
                out.append(getattr(call, "text", None) or getattr(call, "caption", None) or "")
        return out


class Driver:
    def __init__(self, dp: Dispatcher, bot: Bot) -> None:
        self.dp, self.bot, self._n = dp, bot, 0

    def _user(self, uid: int) -> TgUser:
        return TgUser(id=uid, is_bot=False, first_name=f"U{uid}", username=f"user{uid}")

    def _message(self, uid: int, **kwargs: Any) -> Message:
        self._n += 1
        return Message(
            message_id=self._n,
            date=dt.datetime.now(dt.timezone.utc),
            chat=Chat(id=uid, type="private"),
            from_user=self._user(uid),
            **kwargs,
        )

    async def send(self, uid: int, **kwargs: Any) -> None:
        message = self._message(uid, **kwargs)
        await self.dp.feed_update(self.bot, Update(update_id=self._n, message=message))

    async def click(self, uid: int, data: Any) -> None:
        packed = data if isinstance(data, str) else data.pack()
        query = CallbackQuery(
            id=str(self._n),
            from_user=self._user(uid),
            chat_instance="ci",
            data=packed,
            message=self._message(uid, text="card"),
        )
        await self.dp.feed_update(self.bot, Update(update_id=self._n, callback_query=query))


async def _register(d: Driver, api: FakeSession, uid: int, gender: str, target: str) -> None:
    await d.send(uid, text="/start")
    assert "Adults only" in api.texts_to(uid)[-1]
    # Everything is locked until the gate is passed.
    await d.send(uid, text="/search")
    assert "Adults only" in api.texts_to(uid)[-1]

    await d.click(uid, AgeCb(action="confirm"))
    a, b = map(int, re.search(r"(\d+) \+ (\d+)", api.calls[-1].text).groups())
    await d.click(uid, AgeCb(action="answer", value=a + b + 1))
    assert "Wrong answer" in api.calls[-1].text
    a, b = map(int, re.search(r"(\d+) \+ (\d+)", api.calls[-1].text).groups())
    await d.click(uid, AgeCb(action="answer", value=a + b))
    assert "subscribe" in api.texts_to(uid)[-1]

    await d.click(uid, SUBSCRIPTION_CHECK)
    assert "Step 1/5" not in api.texts_to(uid)[-1]
    api.subscribed.add(uid)
    await d.click(uid, SUBSCRIPTION_CHECK)
    assert "Step 1/5" in api.texts_to(uid)[-1]

    await d.click(uid, RegCb(field="category", value="intimate"))
    await d.click(uid, RegCb(field="gender", value=gender))
    await d.click(uid, RegCb(field="target", value=target))
    await d.send(uid, text="abc")
    await d.send(uid, text="27")
    await d.send(uid, text="Berlin")
    await d.send(uid, text="short")
    await d.send(uid, text=f"<b>bio</b> of user {uid}, long enough")
    await d.click(uid, RegCb(field="photos", value="done"))  # no photo yet
    for n in range(2):
        photo = PhotoSize(file_id=f"photo-{uid}-{n}", file_unique_id=f"u{n}", width=1, height=1)
        await d.send(uid, photo=[photo])
    await d.click(uid, RegCb(field="photos", value="done"))
    assert "Free onboarding is complete" in api.texts_to(uid)[-1]


async def _scenario(tmp_path: Any) -> None:
    engine, factory = create_engine_and_factory(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    await init_models(engine)
    api = FakeSession()
    bot = Bot("42:TEST", session=api, default=DefaultBotProperties(parse_mode="HTML"))
    d = Driver(create_dispatcher(factory), bot)

    async def user(uid: int) -> User:
        async with factory() as s:
            return (await s.execute(select(User).where(User.telegram_id == uid))).scalar_one()

    await _register(d, api, ALICE, "male", "women")
    await _register(d, api, BOB, "female", "men")
    alice, bob = await user(ALICE), await user(BOB)
    assert alice.balance == bob.balance == 30 and alice.is_verified_18

    # Photos-only view: 2 credits, album sent, bio locked and escaped nowhere.
    await d.click(ALICE, MenuCb(action="search"))
    await d.click(ALICE, SearchCb(action="category", value="intimate"))
    await d.click(ALICE, SearchCb(action="mode", value="photos"))
    assert isinstance(api.calls[-2], SendMediaGroup)
    card = api.texts_to(ALICE)[-1]
    assert "Bio locked" in card and "bio of user" not in card
    assert (await user(ALICE)).balance == 28

    # Unlocking the rest costs only the bio price and escapes user HTML.
    await d.click(ALICE, CardCb(action="unlock", target=bob.id))
    assert "&lt;b&gt;bio&lt;/b&gt; of user 1002" in api.texts_to(ALICE)[-1]
    assert (await user(ALICE)).balance == 27

    # Forged target ids (never shown to this viewer) are rejected.
    await d.click(BOB, CardCb(action="pm", target=alice.id))
    assert (await user(BOB)).balance == 30

    # Anonymous message: charged on send, sender identity not leaked.
    await d.click(ALICE, CardCb(action="anon", target=bob.id))
    await d.send(ALICE, text="hello <i>there</i>")
    received = api.texts_to(BOB)[-1]
    assert "hello &lt;i&gt;there&lt;/i&gt;" in received
    assert "U1001" not in received and "user1001" not in received
    assert (await user(ALICE)).balance == 22

    # Named message discloses the name.
    await d.click(ALICE, CardCb(action="named", target=bob.id))
    await d.send(ALICE, text="hi again")
    assert "U1001" in api.texts_to(BOB)[-1]
    assert (await user(ALICE)).balance == 19

    # PM request → reject → refund.
    await d.click(ALICE, CardCb(action="pm", target=bob.id))
    assert "wants to exchange direct Telegram handles" in api.texts_to(BOB)[-1]
    assert (await user(ALICE)).balance == 4
    await d.click(ALICE, CardCb(action="pm", target=bob.id))  # duplicate while pending
    assert (await user(ALICE)).balance == 4
    await d.click(BOB, PMCb(action="reject", request_id=1))
    assert "declined" in api.texts_to(ALICE)[-1]
    assert (await user(ALICE)).balance == 19

    # PM request → accept → both receive handles; second click is a no-op.
    await d.click(ALICE, CardCb(action="pm", target=bob.id))
    await d.click(BOB, PMCb(action="accept", request_id=2))
    assert "@user1001" in api.texts_to(BOB)[-1]
    assert "@user1002" in api.texts_to(ALICE)[-1]
    await d.click(BOB, PMCb(action="reject", request_id=2))
    assert (await user(ALICE)).balance == 4

    # Insufficient funds intercepts with a top-up prompt and no request.
    await d.click(ALICE, CardCb(action="pm", target=bob.id))
    assert "Not enough credits" in api.texts_to(ALICE)[-1]

    # Like, then feed is exhausted (liked profile excluded).
    await d.click(ALICE, CardCb(action="like", target=bob.id))
    assert "No more profiles" in api.texts_to(ALICE)[-1]

    # Bob browses bio-only, likes back → mutual on both rows.
    await d.send(BOB, text="/search")
    await d.click(BOB, SearchCb(action="category", value="intimate"))
    await d.click(BOB, SearchCb(action="mode", value="bio"))
    assert isinstance(api.calls[-1], SendMessage) and "Photos locked" in api.calls[-1].text
    assert (await user(BOB)).balance == 29
    await d.click(BOB, CardCb(action="like", target=alice.id))
    assert any("mutual like" in t for t in api.texts_to(ALICE))

    # Stars payment is credited exactly once.
    pay = SuccessfulPayment(
        currency="XTR",
        total_amount=25,
        invoice_payload="topup:50:25",
        telegram_payment_charge_id="ch1",
        provider_payment_charge_id="p1",
    )
    await d.send(ALICE, successful_payment=pay)
    await d.send(ALICE, successful_payment=pay)
    assert (await user(ALICE)).balance == 54

    async with factory() as s:
        assert (await s.scalar(select(func.count()).select_from(Profile))) == 2
        matches = (await s.scalars(select(Match))).all()
        assert len(matches) == 2 and all(m.is_mutual for m in matches)
        statuses = [
            r.status for r in (await s.scalars(select(PMRequest).order_by(PMRequest.id))).all()
        ]
        assert statuses == [PMRequestStatus.REJECTED, PMRequestStatus.ACCEPTED]
        # The ledger always reconciles with balances.
        for u in (await s.scalars(select(User))).all():
            total = await s.scalar(
                select(func.sum(Transaction.amount)).where(Transaction.user_id == u.id)
            )
            assert total == u.balance

    # A self-declared minor is blocked.
    await d.send(555, text="/start")
    await d.click(555, AgeCb(action="minor"))
    assert (await user(555)).is_banned
    before = len(api.texts_to(555))
    await d.send(555, text="/start")
    assert "restricted" in api.texts_to(555)[-1] and len(api.texts_to(555)) == before + 1

    await engine.dispose()


def test_full_flow(tmp_path: Any) -> None:
    asyncio.run(_scenario(tmp_path))
