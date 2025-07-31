import asyncio
import logging
import html
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from lounge import fetch_lounge_users, open_chatroom, send_message

AUTOLOUNGE_TASKS = {}

def get_alounge_markup():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🛑 Stop", callback_data="alounge_stop")]
        ]
    )

async def send_lounge_once(token, messages, bot, chat_id, status_message):
    users = await fetch_lounge_users(token)
    sent_count = 0
    for user in users:
        user_id = user["user"]["_id"]
        chatroom_id = await open_chatroom(token, user_id)
        if chatroom_id:
            for message in messages:
                await send_message(token, chatroom_id, message.strip())
            sent_count += 1
    if bot and chat_id and status_message:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=status_message.message_id,
            text=f"[Auto] Messages sent to {sent_count} users in lounge.",
            reply_markup=get_alounge_markup()
        )
    return sent_count

async def alounge_command_handler(message, has_valid_access, get_current_account, user_states, bot):
    user_id = message.chat.id
    state = user_states[user_id]
    if not has_valid_access(user_id):
        await message.reply("You are not authorized to use this bot.")
        return
    token = get_current_account(user_id)
    if not token:
        await message.reply("No active account found. Please set an account before sending messages.")
        return
    command_text = message.text.strip()
    if len(command_text.split()) < 2:
        await message.reply("Please provide a message to send. Usage: /alounge <message>")
        return
    messages = [msg.strip() for msg in " ".join(command_text.split()[1:]).split(",") if msg.strip()]
    if user_id in AUTOLOUNGE_TASKS:
        await message.reply("Auto-lounge is already running. Use the Stop button on the pinned message to stop it.")
        return

    msg_lines = "\n".join(f"<b>Message:</b> {html.escape(m)}" for m in messages)
    status_msg = await message.reply(
        f"Auto-Lounge started!\n\n{msg_lines}\n\nMessages will be sent every 30 seconds.",
        reply_markup=get_alounge_markup(),
        parse_mode="HTML"
    )
    # Pin the message for easy access
    try:
        await bot.pin_chat_message(chat_id=user_id, message_id=status_msg.message_id, disable_notification=True)
        state["pinned_message_id"] = status_msg.message_id
    except Exception as e:
        logging.warning(f"Failed to pin message: {e}")

    # Start background task
    task = asyncio.create_task(
        alounge_loop(token, messages, bot, user_id, status_msg, state)
    )
    AUTOLOUNGE_TASKS[user_id] = (task, status_msg.message_id)
    state["alounge_running"] = True

async def alounge_loop(token, messages, bot, chat_id, status_message, state):
    try:
        while True:
            await send_lounge_once(token, messages, bot, chat_id, status_message)
            await asyncio.sleep(30)
    except asyncio.CancelledError:
        # Clean up and unpin message
        try:
            await bot.unpin_chat_message(chat_id=chat_id, message_id=status_message.message_id)
        except Exception:
            pass
        state["alounge_running"] = False
        return

async def handle_alounge_callback(callback_query, user_states, bot, get_current_account):
    user_id = callback_query.from_user.id
    state = user_states[user_id]
    if callback_query.data == "alounge_stop":
        # Cancel the task if running
        task_info = AUTOLOUNGE_TASKS.pop(user_id, None)
        if task_info:
            task, pinned_msg_id = task_info
            task.cancel()
            await callback_query.message.edit_text("Auto-Lounge stopped. ✅")
            try:
                await bot.unpin_chat_message(chat_id=user_id, message_id=pinned_msg_id)
            except Exception:
                pass
            state["alounge_running"] = False
            state["pinned_message_id"] = None
            await callback_query.answer("Stopped.")
            return True
        else:
            await callback_query.answer("No auto-lounge running.")
            return True
    return False
