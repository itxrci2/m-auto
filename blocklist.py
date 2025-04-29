from db import db
from aiogram import types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

BLOCKLIST_MARKUP = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="On", callback_data="blocklist_on"),
        InlineKeyboardButton(text="Off", callback_data="blocklist_off"),
        InlineKeyboardButton(text="Clear", callback_data="blocklist_clear"),
    ]
])

def get_blocklist_doc(user_id):
    return db.blocklists.find_one({"user_id": user_id})

def get_user_blocklist(user_id):
    doc = get_blocklist_doc(user_id)
    if doc and "ids" in doc:
        return set(doc["ids"])
    return set()

def set_user_blocklist(user_id, ids):
    db.blocklists.update_one(
        {"user_id": user_id},
        {"$set": {"ids": list(ids)}},
        upsert=True
    )

def add_to_blocklist(user_id, user_to_block):
    ids = get_user_blocklist(user_id)
    ids.add(user_to_block)
    set_user_blocklist(user_id, ids)

def clear_blocklist(user_id):
    db.blocklists.update_one({"user_id": user_id}, {"$set": {"ids": []}}, upsert=True)

def is_blocklist_active(user_id):
    doc = get_blocklist_doc(user_id)
    return bool(doc and doc.get("active", False))

def set_blocklist_active(user_id, active: bool):
    db.blocklists.update_one(
        {"user_id": user_id},
        {"$set": {"active": active}},
        upsert=True
    )

async def blocklist_command(message_or_callback, edit=True):
    # Always edit the message for settings, to avoid sending a new message
    if isinstance(message_or_callback, types.CallbackQuery):
        user_id = message_or_callback.from_user.id
    else:
        user_id = message_or_callback.chat.id
    status = "ON" if is_blocklist_active(user_id) else "OFF"
    count = len(get_user_blocklist(user_id))
    text = (
        f"Blocklist status: <b>{status}</b>\n"
        f"Blocked users: <b>{count}</b>\n\n"
        f"Use the buttons to turn blocklist ON/OFF or CLEAR the blocklist."
    )
    if isinstance(message_or_callback, types.CallbackQuery) or edit:
        # Edit message if from callback, or if explicitly requested via edit param
        if isinstance(message_or_callback, types.CallbackQuery):
            await message_or_callback.message.edit_text(text, reply_markup=BLOCKLIST_MARKUP, parse_mode="HTML")
            await message_or_callback.answer()
        else:
            await message_or_callback.edit_text(text, reply_markup=BLOCKLIST_MARKUP, parse_mode="HTML")
    else:
        await message_or_callback.answer(text, reply_markup=BLOCKLIST_MARKUP, parse_mode="HTML")

async def handle_blocklist_callback(callback_query):
    user_id = callback_query.from_user.id
    data = callback_query.data
    updated = False

    if data == "blocklist_on":
        set_blocklist_active(user_id, True)
        await callback_query.answer("Blocklist is now ON.")
        updated = True
    elif data == "blocklist_off":
        set_blocklist_active(user_id, False)
        await callback_query.answer("Blocklist is now OFF.")
        updated = True
    elif data == "blocklist_clear":
        clear_blocklist(user_id)
        await callback_query.answer("Blocklist cleared!")
        updated = True

    if updated:
        status = "ON" if is_blocklist_active(user_id) else "OFF"
        count = len(get_user_blocklist(user_id))
        text = (
            f"Blocklist status: <b>{status}</b>\n"
            f"Blocked users: <b>{count}</b>\n\n"
            f"Use the buttons to turn blocklist ON/OFF or CLEAR the blocklist."
        )
        await callback_query.message.edit_text(text, reply_markup=BLOCKLIST_MARKUP, parse_mode="HTML")
        return True

    return False
