from db import db
from aiogram import types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import asyncio

BLOCKLIST_MARKUP = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="On", callback_data="blocklist_on"),
        InlineKeyboardButton(text="Off", callback_data="blocklist_off"),
        InlineKeyboardButton(text="Clear", callback_data="blocklist_clear"),
    ]
])

blocklist_lock = asyncio.Lock()

def get_blocklist_doc(user_id):
    return db.blocklists.find_one({"user_id": user_id})

def get_user_blocklist(user_id):
    """Return union of permanent and temporary blocklists."""
    doc = get_blocklist_doc(user_id)
    permanent = set(doc.get("permanent", [])) if doc else set()
    temporary = set(doc.get("temporary", [])) if doc else set()
    return permanent | temporary

def get_permanent_blocklist(user_id):
    doc = get_blocklist_doc(user_id)
    return set(doc.get("permanent", [])) if doc else set()

def get_temporary_blocklist(user_id):
    doc = get_blocklist_doc(user_id)
    return set(doc.get("temporary", [])) if doc else set()

def set_user_blocklist(user_id, permanent, temporary):
    db.blocklists.update_one(
        {"user_id": user_id},
        {"$set": {
            "permanent": list(permanent),
            "temporary": list(temporary)
        }},
        upsert=True
    )

def add_to_permanent_blocklist(user_id, user_to_block):
    doc = get_blocklist_doc(user_id)
    permanent = set(doc.get("permanent", [])) if doc else set()
    if user_to_block not in permanent:
        permanent.add(user_to_block)
        db.blocklists.update_one(
            {"user_id": user_id},
            {"$set": {"permanent": list(permanent)}},
            upsert=True
        )

def add_to_temporary_blocklist(user_id, user_to_block):
    doc = get_blocklist_doc(user_id)
    temporary = set(doc.get("temporary", [])) if doc else set()
    permanent = set(doc.get("permanent", [])) if doc else set()
    if user_to_block not in permanent and user_to_block not in temporary:
        temporary.add(user_to_block)
        db.blocklists.update_one(
            {"user_id": user_id},
            {"$set": {"temporary": list(temporary)}},
            upsert=True
        )

async def atomic_check_and_add_blocklist(user_id, user_to_block):
    """Atomically check the blocklist and add if not already present (prevents race condition)."""
    async with blocklist_lock:
        blocklist = get_user_blocklist(user_id)
        if user_to_block in blocklist:
            return True
        add_to_temporary_blocklist(user_id, user_to_block)
        return False

def clear_temporary_blocklist(user_id):
    db.blocklists.update_one({"user_id": user_id}, {"$set": {"temporary": []}}, upsert=True)

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
    if isinstance(message_or_callback, types.CallbackQuery):
        user_id = message_or_callback.from_user.id
    else:
        user_id = message_or_callback.chat.id
    status = "ON" if is_blocklist_active(user_id) else "OFF"
    permanent = get_permanent_blocklist(user_id)
    temporary = get_temporary_blocklist(user_id)
    text = (
        f"Blocklist status: <b>{status}</b>\n"
        f"Permanent blocks: <b>{len(permanent)}</b>\n"
        f"Temporary blocks: <b>{len(temporary)}</b>\n\n"
        f"Use the buttons to turn blocklist ON/OFF or CLEAR the temporary blocklist."
    )
    if isinstance(message_or_callback, types.CallbackQuery) or edit:
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
        clear_temporary_blocklist(user_id)
        await callback_query.answer("Temporary blocklist cleared!")
        updated = True

    if updated:
        status = "ON" if is_blocklist_active(user_id) else "OFF"
        permanent = get_permanent_blocklist(user_id)
        temporary = get_temporary_blocklist(user_id)
        text = (
            f"Blocklist status: <b>{status}</b>\n"
            f"Permanent blocks: <b>{len(permanent)}</b>\n"
            f"Temporary blocks: <b>{len(temporary)}</b>\n\n"
            f"Use the buttons to turn blocklist ON/OFF or CLEAR the temporary blocklist."
        )
        await callback_query.message.edit_text(text, reply_markup=BLOCKLIST_MARKUP, parse_mode="HTML")
        return True

    return False
