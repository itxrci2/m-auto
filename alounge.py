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

def get_alounge_choice_markup():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Current", callback_data="alounge_current"),
                InlineKeyboardButton(text="All", callback_data="alounge_all")
            ],
            [InlineKeyboardButton(text="Cancel", callback_data="alounge_cancel")]
        ]
    )

def get_alounge_confirm_markup():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Confirm", callback_data="alounge_confirm")],
            [InlineKeyboardButton(text="Cancel", callback_data="alounge_cancel")]
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
    return sent_count

async def alounge_command_handler(message, has_valid_access, get_current_account, user_states, bot, get_tokens=None):
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

    state['pending_alounge_message'] = messages
    msg_lines = "\n".join(f"<b>Message:</b> {html.escape(m)}" for m in messages)
    markup = get_alounge_choice_markup()
    await message.reply(
        f"How would you like to send your auto lounge message?\n\n{msg_lines}",
        reply_markup=markup,
        parse_mode="HTML"
    )

async def alounge_loop(token, messages, bot, chat_id, status_message, state):
    total_sent = 0
    try:
        while True:
            sent_this_round = await send_lounge_once(token, messages, bot, chat_id, status_message)
            total_sent += sent_this_round
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_message.message_id,
                text=f"[Auto] Messages sent to {sent_this_round} users in lounge (this round).\nTotal messages sent since started: {total_sent}",
                reply_markup=get_alounge_markup()
            )
            await asyncio.sleep(30)
    except asyncio.CancelledError:
        try:
            await bot.unpin_chat_message(chat_id=chat_id, message_id=status_message.message_id)
        except Exception:
            pass
        state["alounge_running"] = False
        return

async def alounge_all_loop(tokens, messages, bot, chat_id, status_message, state):
    account_totals = [0 for _ in tokens]
    try:
        while True:
            results = []
            for idx, token_info in enumerate(tokens):
                sent_count = await send_lounge_once(token_info["token"], messages, bot, chat_id, status_message)
                account_totals[idx] += sent_count
                results.append(sent_count)
            summary_text = (
                f"Total Accounts: {len(tokens)}\n"
                f"Auto-lounge sent messages this round: ({' | '.join(str(x) for x in results)})\n"
                f"Total messages sent since started: ({' | '.join(str(x) for x in account_totals)})"
            )
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_message.message_id,
                text=summary_text,
                parse_mode="HTML",
                reply_markup=get_alounge_markup()
            )
            await asyncio.sleep(30)
    except asyncio.CancelledError:
        try:
            await bot.unpin_chat_message(chat_id=chat_id, message_id=status_message.message_id)
        except Exception:
            pass
        state["alounge_running"] = False
        return

async def handle_alounge_callback(callback_query, user_states, bot, get_current_account, get_tokens=None):
    user_id = callback_query.from_user.id
    state = user_states[user_id]
    data = callback_query.data

    # --- Choice: Current
    if data == "alounge_current":
        token = get_current_account(user_id)
        if not token:
            await callback_query.answer("No current account found.")
            return True
        messages = state.get('pending_alounge_message', [])
        msg_lines = "\n".join(f"<b>Message:</b> {html.escape(m)}" for m in messages)
        status_msg = await callback_query.message.edit_text(
            f"Auto-lounge started for the current account!\n{msg_lines}\n\nMessages will be sent every 30 seconds.",
            reply_markup=get_alounge_markup(),
            parse_mode="HTML"
        )
        try:
            await bot.pin_chat_message(chat_id=user_id, message_id=status_msg.message_id, disable_notification=True)
            state["pinned_message_id"] = status_msg.message_id
        except Exception as e:
            logging.warning(f"Failed to pin message: {e}")
        task = asyncio.create_task(
            alounge_loop(token, messages, bot, user_id, status_msg, state)
        )
        AUTOLOUNGE_TASKS[user_id] = [task]
        state["alounge_running"] = True
        state.pop('pending_alounge_message', None)
        await callback_query.answer("Auto-lounge started.")
        return True

    # --- Choice: All accounts
    elif data == "alounge_all":
        if get_tokens is None:
            await callback_query.answer("Account selection not available.")
            return True
        tokens = get_tokens(user_id)
        if not tokens:
            await callback_query.message.edit_text("No accounts found.")
            return True
        acc_line = "<b>Accounts:</b> " + ", ".join(html.escape(t["name"]) for t in tokens)
        confirm_markup = get_alounge_confirm_markup()
        await callback_query.message.edit_text(
            f"You chose to send the auto lounge message to:\n{acc_line}\n\nPress Confirm to proceed.",
            reply_markup=confirm_markup,
            parse_mode="HTML"
        )
        state['alounge_send_type'] = "alounge_all"
        await callback_query.answer()
        return True

    # --- Confirm All
    elif data == "alounge_confirm":
        if get_tokens is None:
            await callback_query.answer("Account selection not available.")
            return True
        tokens = get_tokens(user_id)
        if not tokens:
            await callback_query.message.edit_text("No accounts found.")
            return True
        messages = state.get('pending_alounge_message', [])
        status_msg = await callback_query.message.edit_text(
            "Auto-lounge started for all accounts! Messages will be sent every 30 seconds.",
            reply_markup=get_alounge_markup()
        )
        try:
            await bot.pin_chat_message(chat_id=user_id, message_id=status_msg.message_id, disable_notification=True)
            state["pinned_message_id"] = status_msg.message_id
        except Exception as e:
            logging.warning(f"Failed to pin message: {e}")
        task = asyncio.create_task(
            alounge_all_loop(tokens, messages, bot, user_id, status_msg, state)
        )
        AUTOLOUNGE_TASKS[user_id] = [task]
        state["alounge_running"] = True
        state.pop('pending_alounge_message', None)
        state.pop('alounge_send_type', None)
        await callback_query.answer("Auto-lounge started for all accounts.")
        return True

    # --- Cancel
    elif data == "alounge_cancel":
        state.pop('alounge_send_type', None)
        state.pop('pending_alounge_message', None)
        await callback_query.message.edit_text("Auto-lounge sending cancelled.")
        await callback_query.answer("Cancelled.")
        return True

    # --- Stop
    elif data == "alounge_stop":
        # Cancel the task(s) if running
        task_list = AUTOLOUNGE_TASKS.pop(user_id, None)
        if task_list:
            for task in task_list:
                task.cancel()
            try:
                if state.get("pinned_message_id"):
                    await bot.unpin_chat_message(chat_id=user_id, message_id=state["pinned_message_id"])
            except Exception:
                pass
            state["alounge_running"] = False
            state["pinned_message_id"] = None
            await callback_query.message.edit_text("Auto-lounge stopped. ✅")
            await callback_query.answer("Stopped.")
            return True
        else:
            await callback_query.answer("No auto-lounge running.")
            return True

    return False
