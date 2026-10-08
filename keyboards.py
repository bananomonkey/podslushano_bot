from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.filters.callback_data import CallbackData


class ModerationCB(CallbackData, prefix="mod"):
    action: str  # "approve" | "reject"
    post_id: int


class AdminPanelCB(CallbackData, prefix="adm"):
    action: str  # "add" | "remove" | "list" | "close"


class AdminRemoveCB(CallbackData, prefix="admdel"):
    user_id: int


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


def admin_panel_kb(is_super: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if is_super:
        builder.button(text="➕ Добавить админа", callback_data=AdminPanelCB(action="add"))
        builder.button(text="➖ Удалить админа", callback_data=AdminPanelCB(action="remove"))
    builder.button(text="📋 Список админов", callback_data=AdminPanelCB(action="list"))
    builder.button(text="✖️ Закрыть", callback_data=AdminPanelCB(action="close"))
    builder.adjust(1)
    return builder.as_markup()


def admin_remove_kb(admin_ids: list[int]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for user_id in admin_ids:
        builder.button(text=f"❌ {user_id}", callback_data=AdminRemoveCB(user_id=user_id))
    builder.button(text="⬅️ Назад", callback_data=AdminPanelCB(action="back"))
    builder.adjust(1)
    return builder.as_markup()


def moderation_kb(post_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Опубликовать", callback_data=ModerationCB(action="approve", post_id=post_id))
    builder.button(text="❌ Отклонить", callback_data=ModerationCB(action="reject", post_id=post_id))
    builder.adjust(2)
    return builder.as_markup()
