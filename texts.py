"""User-facing labels and text rendering (all user input is HTML-escaped here)."""
from __future__ import annotations

from html import escape

from config import settings
from database.models import Category, Gender, Profile, TargetGender, User
from services.billing import ViewMode

CATEGORY_LABELS: dict[Category, str] = {
    Category.FRIENDSHIP: "🤝 Friendship / Дружба",
    Category.CHATTING: "💬 Chatting / Общение",
    Category.INTIMATE: "🔥 Intimate / Интим",
}
GENDER_LABELS: dict[Gender, str] = {Gender.MALE: "👨 Man", Gender.FEMALE: "👩 Woman"}
TARGET_LABELS: dict[TargetGender, str] = {
    TargetGender.MEN: "👨 Men",
    TargetGender.WOMEN: "👩 Women",
    TargetGender.ALL: "👥 All",
}
MODE_LABELS: dict[ViewMode, str] = {
    ViewMode.PHOTOS: "📸 Photos only",
    ViewMode.BIO: "📝 Bio only",
    ViewMode.FULL: "⭐ Full profile",
}

AGE_GATE = (
    "🔞 <b>Adults only</b>\n\n"
    "This bot is an anonymous dating service intended strictly for people "
    "aged 18 or older. By continuing you confirm that you are an adult and "
    "that viewing such content is legal where you live."
)
MINOR_BLOCKED = (
    "🚫 This service is strictly 18+. Access has been blocked for this account."
)
BANNED = "🚫 Your access to this bot is restricted."


def price_list() -> str:
    s = settings
    return (
        "<b>Prices (credits)</b>\n"
        f"📸 View photos only — {s.PRICE_VIEW_PHOTOS_ONLY}\n"
        f"📝 View bio only — {s.PRICE_VIEW_BIO_ONLY}\n"
        f"⭐ View full profile — {s.PRICE_VIEW_FULL_PROFILE}\n"
        f"🕶 Anonymous message — {s.PRICE_SEND_ANON_MSG}\n"
        f"✍️ Named message — {s.PRICE_SEND_NAMED_MSG}\n"
        f"📩 Request private chat — {s.PRICE_REQUEST_PM}"
    )


def card_text(profile: Profile, *, show_photos: bool, show_bio: bool, footer: str = "") -> str:
    lines = [f"<b>{CATEGORY_LABELS[profile.category]}</b>"]
    if show_bio:
        lines.append(f"{GENDER_LABELS[profile.gender]}, {profile.age}")
        if show_photos:
            lines.append(f"📍 {escape(profile.city)} · 🖼 {len(profile.photos)} photo(s)")
        lines += ["", escape(profile.bio)]
    else:
        lines.append(f"🔒 Bio locked. Unlock for {settings.PRICE_VIEW_BIO_ONLY} credits.")
    if not show_photos:
        lines += [
            "",
            f"🔒 Photos locked. Unlock for {settings.PRICE_VIEW_PHOTOS_ONLY} credits.",
        ]
    if footer:
        lines += ["", footer]
    return "\n".join(lines)


def own_profile_text(profile: Profile) -> str:
    status = "🟢 visible in search" if profile.is_active else "⏸ hidden from search"
    return (
        "<b>Your profile</b>\n"
        f"{CATEGORY_LABELS[profile.category]}\n"
        f"{GENDER_LABELS[profile.gender]}, {profile.age} · "
        f"looking for: {TARGET_LABELS[profile.target_gender]}\n"
        f"📍 {escape(profile.city)}\n\n"
        f"{escape(profile.bio)}\n\n"
        f"Status: {status}"
    )


def display_name(user: User) -> str:
    return escape(user.first_name or "User")


def handle_of(user: User) -> str:
    """Public @handle, or a tg:// mention link when the user has no username."""
    if user.username:
        return f"@{escape(user.username)}"
    return f'<a href="tg://user?id={user.telegram_id}">{display_name(user)}</a>'
