# Anonymous 18+ dating bot

Telegram bot built with Python 3.11+, aiogram 3 and async SQLAlchemy 2.0
(SQLite via `aiosqlite` or PostgreSQL via `asyncpg`). Onboarding is free;
viewing profiles and contacting people costs internal credits, topped up with
Telegram Stars.

## Run

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set BOT_TOKEN, optionally SPONSOR_CHANNEL_ID
python main.py
```

Tables are created on start-up. For the subscription check the bot must be an
administrator of the sponsor channel. Tests: `pip install pytest && pytest`.

## Layout

| Path | Purpose |
| --- | --- |
| `config.py` | Settings and `PRICE_*` constants (environment / `.env`) |
| `database/models.py` | `User`, `Profile`, `Match`, `PMRequest`, `Transaction` (+ `Dislike`, `ProfileUnlock`) |
| `database/repo.py` | Queries: feed candidate selection, likes, unlocks, PM requests |
| `services/billing.py` | Atomic charge / credit with ledger entries, view pricing |
| `services/subscription.py` | Sponsor channel membership check |
| `middlewares/db.py` | Per-update session injection (commit / rollback) and user loading |
| `middlewares/gates.py` | 18+ gate and mandatory subscription gate |
| `handlers/start.py` | Age captcha, subscription check, menu, own profile |
| `handlers/registration.py` | Registration FSM |
| `handlers/search.py` | Feed, view modes, unlocks |
| `handlers/interactions.py` | Like / dislike, anonymous and named messages, PM requests |
| `handlers/wallet.py` | Balance, packages, Telegram Stars payments (`PAYMENTS_MOCK` for dev) |
| `keyboards/` | Inline keyboards and typed callback data |

## Behaviour notes

- The balance lives in `users.balance`; every change has a row in
  `transactions` (signed `amount`), so the ledger always sums to the balance.
- Credits are deducted before a paid action runs. If delivery to the other
  user fails, the charge is refunded.
- A viewer never pays twice for the same part of a profile: unlocks are stored
  in `profile_unlocks`, and "Unlock full profile" charges only the missing part.
- Interaction buttons only work for profiles the viewer has actually been
  shown, so forged callback data cannot reach arbitrary users.
- A user who declares an age under 18 (gate button or registration) is blocked.
- With several bot processes, use `REDIS_URL` for FSM storage and PostgreSQL.
