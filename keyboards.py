from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.filters.callback_data import CallbackData


class ModerationCB(CallbackData, prefix="mod"):
    action: str  # "approve" | "reject"
    post_id: int


def main_menu_kb() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text="📝 Предложить пост")
    builder.button(text="💬 Связь с админом")
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True)


def cancel_kb() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text="❌ Отмена")
    return builder.as_markup(resize_keyboard=True)


def moderation_kb(post_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Опубликовать", callback_data=ModerationCB(action="approve", post_id=post_id))
    builder.button(text="❌ Отклонить", callback_data=ModerationCB(action="reject", post_id=post_id))
    builder.adjust(2)
    return builder.as_markup()
