import asyncio
import aiohttp
import html
import logging
import json
import time
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest
from blocklist import is_blocklist_active, add_to_blocklist, get_user_blocklist
from dateutil import parser
from datetime import datetime
from db import get_user_filters

# --- UI MARKUPS ---

REQUESTS_CHOICE_MARKUP = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="Current", callback_data="requests_current"),
        InlineKeyboardButton(text="All", callback_data="requests_all")
    ],
    [InlineKeyboardButton(text="Cancel", callback_data="requests_cancel")]
])
REQUESTS_ALL_CONFIRM_MARKUP = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Confirm", callback_data="requests_confirm")],
    [InlineKeyboardButton(text="Cancel", callback_data="requests_cancel")]
])
STOP_MARKUP = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Stop Requests", callback_data="stop")]
])

SPEED_LEVELS = {
    "default": ("Default", 3.0),
    "turbo": ("Turbo", 0.02)
}

def get_speed_markup(current_speed=None):
    buttons = []
    for key, (title, _) in SPEED_LEVELS.items():
        text = f"{title} {'(Current)' if key == current_speed else ''}"
        buttons.append(InlineKeyboardButton(text=text, callback_data=f"speed_{key}"))
    buttons.append(InlineKeyboardButton(text="Custom", callback_data="speed_custom"))
    return InlineKeyboardMarkup(inline_keyboard=[buttons])

def format_user(user):
    def time_ago(dt_str):
        if not dt_str:
            return "N/A"
        try:
            dt = parser.isoparse(dt_str)
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            diff = now - dt
            minutes = int(diff.total_seconds() // 60)
            if minutes < 1:
                return "just now"
            elif minutes < 60:
                return f"{minutes} min ago"
            hours = minutes // 60
            if hours < 24:
                return f"{hours} hr ago"
            days = hours // 24
            return f"{days} day(s) ago"
        except Exception:
            return "unknown"
    last_active = time_ago(user.get("recentAt"))
    nationality = html.escape(user.get('nationalityCode', 'N/A'))
    height = html.escape(str(user.get('height', 'N/A')))
    if "|" in height:
        height_val, height_unit = height.split("|", 1)
        height = f"{height_val.strip()} {height_unit.strip()}"
    return (
        f"<b>Name:</b> {html.escape(user.get('name', 'N/A'))}\n"
        f"<b>ID:</b> <code>{html.escape(user.get('_id', 'N/A'))}</code>\n"
        f"<b>Nationality:</b> {nationality}\n"
        f"<b>Height:</b> {height}\n"
        f"<b>Description:</b> {html.escape(user.get('description', 'N/A'))}\n"
        f"<b>Birth Year:</b> {html.escape(str(user.get('birthYear', 'N/A')))}\n"
        f"<b>Platform:</b> {html.escape(user.get('platform', 'N/A'))}\n"
        f"<b>Profile Score:</b> {html.escape(str(user.get('profileScore', 'N/A')))}\n"
        f"<b>Distance:</b> {html.escape(str(user.get('distance', 'N/A')))} km\n"
        f"<b>Language Codes:</b> {html.escape(', '.join(user.get('languageCodes', [])))}\n"
        f"<b>Last Active:</b> {last_active}\n"
        "Photos: " + ' '.join([f"<a href='{html.escape(url)}'>Photo</a>" for url in user.get('photoUrls', [])])
    )

async def fetch_users(session, token):
    url = "https://api.meeff.com/user/explore/v2/?lat=33.589510&lng=-117.860909"
    headers = {"meeff-access-token": token, "Connection": "keep-alive"}
    async with session.get(url, headers=headers) as response:
        return (await response.json()).get("users", [])

def format_time_used(start_time, end_time):
    delta = end_time - start_time
    total_seconds = int(delta.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}h {minutes}m {seconds}s"
    elif minutes > 0:
        return f"{minutes}m {seconds}s"
    else:
        return f"{seconds}s"

def format_progress(accounts, names):
    lines = ["🟢 <b>All Accounts Progress</b>"]
    for i, acc in enumerate(accounts):
        s = f"{i+1}. {names[i]}: {acc['added']} sent, {acc['skipped']} skipped"
        if acc.get("exceeded"): s += " <b>(Exceeded)</b>"
        lines.append(s)
    lines.append("\n⏳ Processing... (Press Stop to interrupt)")
    return "\n".join(lines)

def format_result(accounts, names, start_time, end_time, finished_by_user=False):
    lines = ["✅ <b>All Requests Completed</b>" if not finished_by_user else "⛔️ <b>Requests Stopped by User</b>"]
    for i, acc in enumerate(accounts):
        s = f"{i+1}. {names[i]}: {acc['added']} sent, {acc['skipped']} skipped"
        if acc.get("exceeded"): s += " <b>(Exceeded)</b>"
        lines.append(s)
    lines.append(f"⏱️ Time used: {format_time_used(start_time, end_time)}")
    return "\n".join(lines)

def format_progress_single(account_name, added, skipped):
    return (
        f"🟢 <b>Current Progress</b>\n"
        f"Account: {account_name}\n"
        f"├ Sent: {added}\n"
        f"└ Skipped: {skipped}\n"
        "\n⏳ Processing... (Press Stop to interrupt)"
    )

def format_result_single(account_name, added, skipped, start_time, end_time, like_exceeded=False, finished_by_user=False):
    status = "✅ <b>Requests Completed</b>" if not finished_by_user else "⛔️ <b>Requests Stopped by User</b>"
    extra = "\n<b>Like limit exceeded!</b>" if like_exceeded else ""
    return (
        f"{status}\n"
        f"Account: {account_name}{extra}\n"
        f"\n• Total Sent: {added}"
        f"\n• Skipped: {skipped}"
        f"\n⏱️ Time used: {format_time_used(start_time, end_time)}"
    )

async def safe_edit(bot, chat_id, msg_id, text, markup=None):
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=text, reply_markup=markup, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" in str(e): pass
        else: logging.warning(f"edit_message_text error: {e}")
    except Exception as e:
        logging.warning(f"edit_message_text unknown error: {e}")

async def update_current_filter(user_id, token):
    filters = get_user_filters(user_id, token)
    if not filters:
        return  # nothing to update
    headers = {
        'User-Agent': "okhttp/4.12.0",
        'Accept-Encoding': "gzip",
        'meeff-access-token': token,
        'content-type': "application/json; charset=utf-8"
    }
    url = "https://api.meeff.com/user/updateFilter/v1"
    async with aiohttp.ClientSession() as session:
        async with session.post(url, data=json.dumps(filters), headers=headers) as response:
            if response.status != 200:
                resp_text = await response.text()
                logging.warning(f"Failed to update filter for auto-refresh. Response: {resp_text}")

async def run_requests_parallel(user_id, bot, tokens, status_message_id, state, speed):
    start_time = datetime.now()
    accounts = [{"added":0, "skipped":0, "exceeded":False, "running":True} for _ in tokens]
    names = [tok.get("name", f"Account {i+1}") for i, tok in enumerate(tokens)]
    state["per_account"] = accounts
    state["account_names"] = names
    last_text = None
    last_update_time = 0
    UPDATE_INTERVAL = 2  # seconds

    async def update(force=False):
        nonlocal last_text, last_update_time
        now = time.time()
        if state.get("finalized"):
            return
        text = format_progress(accounts, names)
        if force or (text != last_text and (now - last_update_time) > UPDATE_INTERVAL):
            last_text = text
            last_update_time = now
            await safe_edit(bot, user_id, status_message_id, text, STOP_MARKUP)

    async def worker(i, token):
        acc = accounts[i]
        sent_since_last_filter_update = 0
        async with aiohttp.ClientSession() as session:
            while acc["running"] and state.get("running", True):
                users = await fetch_users(session, token["token"])
                if not users:
                    await update(force=True)
                    break
                blocklist = get_user_blocklist(user_id)
                for user in users:
                    if not acc["running"] or not state.get("running", True): break
                    if user['_id'] in blocklist:
                        acc["skipped"] += 1
                        await update()
                        continue
                    url = f"https://api.meeff.com/user/undoableAnswer/v5/?userId={user['_id']}&isOkay=1"
                    headers = {"meeff-access-token": token["token"], "Connection": "keep-alive"}
                    async with session.get(url, headers=headers) as resp:
                        data = await resp.json()
                        if data.get("errorCode") == "LikeExceeded":
                            acc["exceeded"] = True
                            acc["running"] = False
                            await update(force=True)
                            return
                        acc["added"] += 1
                        sent_since_last_filter_update += 1
                        if sent_since_last_filter_update >= 7:
                            sent_since_last_filter_update = 0
                            try:
                                await update_current_filter(user_id, token["token"])
                            except Exception as e:
                                logging.warning(f"Auto filter update failed: {e}")
                        if is_blocklist_active(user_id):  # only add if blocklist is ON
                            add_to_blocklist(user_id, user['_id'])
                        try:
                            await bot.send_message(user_id, format_user(user), parse_mode="HTML")
                        except: pass
                        await update()
                        await asyncio.sleep(speed)
                await asyncio.sleep(speed)
            await update(force=True)

    state["finalized"] = False
    await safe_edit(bot, user_id, status_message_id, format_progress(accounts, names), STOP_MARKUP)
    await asyncio.gather(*(worker(idx, tok) for idx, tok in enumerate(tokens)))
    end_time = datetime.now()
    state["finalized"] = True
    await safe_edit(
        bot,
        user_id,
        status_message_id,
        format_result(accounts, names, start_time, end_time, finished_by_user=state.get("stopped_by_user", False)),
    )

async def run_requests_single(user_id, state, bot, token, account_name, speed):
    start_time = datetime.now()
    state["total_added_friends"] = 0
    state["skipped_count"] = 0
    last_text = None
    last_update_time = 0
    UPDATE_INTERVAL = 2  # seconds
    like_exceeded = False
    sent_since_last_filter_update = 0

    async def update(force=False):
        nonlocal last_text, last_update_time
        now = time.time()
        if state.get("finalized"):
            return
        text = format_progress_single(account_name, state["total_added_friends"], state["skipped_count"])
        if force or (text != last_text and (now - last_update_time) > UPDATE_INTERVAL):
            last_text = text
            last_update_time = now
            await safe_edit(bot, user_id, state["status_message_id"], text, STOP_MARKUP)

    async with aiohttp.ClientSession() as session:
        while state.get("running", True):
            users = await fetch_users(session, token)
            if not users:
                await update(force=True)
                break
            blocklist = get_user_blocklist(user_id)
            for user in users:
                if not state.get("running", True): break
                if user['_id'] in blocklist:
                    state["skipped_count"] += 1
                    await update()
                    continue
                url = f"https://api.meeff.com/user/undoableAnswer/v5/?userId={user['_id']}&isOkay=1"
                headers = {"meeff-access-token": token, "Connection": "keep-alive"}
                async with session.get(url, headers=headers) as resp:
                    data = await resp.json()
                    if data.get("errorCode") == "LikeExceeded":
                        like_exceeded = True
                        state["running"] = False
                        break
                    state["total_added_friends"] += 1
                    sent_since_last_filter_update += 1
                    if sent_since_last_filter_update >= 7:
                        sent_since_last_filter_update = 0
                        try:
                            await update_current_filter(user_id, token)
                        except Exception as e:
                            logging.warning(f"Auto filter update failed: {e}")
                    if is_blocklist_active(user_id):
                        add_to_blocklist(user_id, user['_id'])
                    try:
                        await bot.send_message(user_id, format_user(user), parse_mode="HTML")
                    except: pass
                    await update()
                    await asyncio.sleep(speed)
            await asyncio.sleep(speed)
    end_time = datetime.now()
    state["finalized"] = True
    await safe_edit(
        bot, user_id, state["status_message_id"],
        format_result_single(
            account_name,
            state['total_added_friends'],
            state['skipped_count'],
            start_time, end_time,
            like_exceeded=like_exceeded,
            finished_by_user=state.get("stopped_by_user", False)
        )
    )

def run_requests(user_id, state, bot, get_current_account, account_name=None, speed=1.0):
    token = get_current_account(user_id)
    return run_requests_single(user_id, state, bot, token, account_name or "Current", speed)

async def handle_custom_speed_message(message, state, bot, get_tokens, get_current_account):
    user_id = message.from_user.id
    try:
        speed = float(message.text.strip())
        if not (0.01 <= speed <= 30):
            await message.reply("Please enter a value between 0.01 and 30 seconds. Send /cancel to abort.")
            return  # Stay in awaiting mode
        # Clear custom speed state after valid input
        state.pop("awaiting_custom_speed", None)
        mode = state.pop("pending_speed_mode", None)
        if mode == "current":
            tokens = get_tokens(user_id)
            current_token = get_current_account(user_id)
            account_name = state.pop("pending_account_name", "Current")
            state.update({"running": True, "finalized": False, "mode": "current", "skipped_count": 0})
            status_message = await message.answer(
                format_progress_single(account_name, 0, 0),
                reply_markup=STOP_MARKUP,
                parse_mode="HTML"
            )
            state["status_message_id"] = status_message.message_id
            state["pinned_message_id"] = status_message.message_id
            await bot.pin_chat_message(chat_id=user_id, message_id=state["status_message_id"])
            await run_requests_single(user_id, state, bot, current_token, account_name, speed)
            pin_id = state.get("pinned_message_id")
            if pin_id:
                try: await bot.unpin_chat_message(chat_id=user_id, message_id=pin_id)
                except: pass
                state["pinned_message_id"] = None
            state["running"] = False
            state.pop("mode", None)
            state.pop("stopped_by_user", None)
            state.pop("per_account", None)
            state.pop("account_names", None)
        elif mode == "all":
            tokens = get_tokens(user_id)
            if not tokens:
                await message.reply("No accounts found.")
                return
            state.update({"running": True, "finalized": False, "mode": "all"})
            status_msg = await message.answer(
                format_progress(
                    [{"added":0, "skipped":0, "exceeded":False} for _ in tokens],
                    [tok.get('name', f'Account {i+1}') for i, tok in enumerate(tokens)]
                ),
                reply_markup=STOP_MARKUP,
                parse_mode="HTML"
            )
            state["pinned_message_id"] = status_msg.message_id
            await bot.pin_chat_message(chat_id=user_id, message_id=status_msg.message_id)
            await run_requests_parallel(user_id, bot, tokens, status_msg.message_id, state, speed)
            try: await bot.unpin_chat_message(chat_id=user_id, message_id=status_msg.message_id)
            except: pass
            state["running"] = False
            state.pop("mode", None)
            state.pop("stopped_by_user", None)
            state.pop("per_account", None)
            state.pop("account_names", None)
        else:
            await message.reply("Speed selection not allowed here.")
        return
    except Exception:
        await message.reply("Invalid speed value. Please send a number like 1.5 for 1.5 seconds. Send /cancel to abort.")
        return  # Stay in awaiting mode

async def handle_requests_callback(
    callback_query, state, bot, user_id, get_current_account, get_tokens, set_current_account, start_markup
):
    data = callback_query.data

    async def edit(text, markup=None):
        await callback_query.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
        await callback_query.answer()

    if data == "start":
        await edit("How would you like to send requests?", REQUESTS_CHOICE_MARKUP)
        return True

    if data == "requests_all":
        tokens = get_tokens(user_id)
        if not tokens:
            await edit("No accounts found.", start_markup)
            return True
        text = "You chose to run requests for ALL accounts. Press Confirm to proceed.\n\nAccounts to process:\n"
        text += "\n".join(f"{i+1}. {tok.get('name', f'Account {i+1}')}" for i, tok in enumerate(tokens))
        await edit(text, REQUESTS_ALL_CONFIRM_MARKUP)
        state["pending_requests_all"] = True
        return True

    if data == "requests_confirm":
        if not state.get("pending_requests_all"):
            await callback_query.answer("Nothing to confirm.")
            return True
        state["pending_speed_mode"] = "all"
        await edit("Select speed for requests:", get_speed_markup())
        return True

    if data == "requests_current":
        if state.get("running"):
            await callback_query.answer("Requests are already running!")
            return True
        tokens = get_tokens(user_id)
        current_token = get_current_account(user_id)
        account_name = next((tok.get("name", "Current") for tok in tokens if tok["token"] == current_token), "Current")
        state["pending_speed_mode"] = "current"
        state["pending_account_name"] = account_name
        await edit("Select speed for requests:", get_speed_markup())
        return True

    if data == "speed_custom":
        state["awaiting_custom_speed"] = True
        await edit("Please send your custom speed in seconds (e.g., 2.0 for 2 seconds between requests):\nYou can /cancel to abort.", None)
        return True

    if data == "requests_cancel":
        state.pop("pending_requests_all", None)
        state.pop("pending_speed_mode", None)
        state.pop("pending_account_name", None)
        state.pop("awaiting_custom_speed", None)
        await edit("Requests operation cancelled.", start_markup)
        await callback_query.answer("Cancelled.")
        return True

    if data == "stop":
        if not state.get("running"):
            await callback_query.answer("Requests are not running!")
            return True
        if state.get("finalized"):
            await callback_query.answer("Stopped.")
            return True
        state["finalized"] = True
        state["running"] = False
        state["stopped_by_user"] = True
        pin_id = state.get("pinned_message_id")
        if pin_id:
            try: await bot.unpin_chat_message(chat_id=user_id, message_id=pin_id)
            except: pass
            state["pinned_message_id"] = None
        await callback_query.answer("Stopped.")
        return True

    if data.startswith("speed_"):
        selected = data.split("_", 1)[1]
        if selected not in SPEED_LEVELS:
            await edit("Unknown speed selected.")
            return True
        speed_value = SPEED_LEVELS[selected][1]
        mode = state.pop("pending_speed_mode", None)
        if mode == "current":
            tokens = get_tokens(user_id)
            current_token = get_current_account(user_id)
            account_name = state.pop("pending_account_name", "Current")
            state.update({"running": True, "finalized": False, "mode": "current", "skipped_count": 0})
            status_message = await callback_query.message.edit_text(
                format_progress_single(account_name, 0, 0),
                reply_markup=STOP_MARKUP,
                parse_mode="HTML"
            )
            state["status_message_id"] = status_message.message_id
            state["pinned_message_id"] = status_message.message_id
            await bot.pin_chat_message(chat_id=user_id, message_id=state["status_message_id"])
            await run_requests_single(user_id, state, bot, current_token, account_name, speed_value)
            pin_id = state.get("pinned_message_id")
            if pin_id:
                try: await bot.unpin_chat_message(chat_id=user_id, message_id=pin_id)
                except: pass
                state["pinned_message_id"] = None
            state["running"] = False
            state.pop("mode", None)
            state.pop("stopped_by_user", None)
            state.pop("per_account", None)
            state.pop("account_names", None)
            return True
        elif mode == "all":
            tokens = get_tokens(user_id)
            if not tokens:
                await edit("No accounts found.")
                return True
            state.update({"running": True, "finalized": False, "mode": "all"})
            status_msg = await callback_query.message.edit_text(
                format_progress(
                    [{"added":0, "skipped":0, "exceeded":False} for _ in tokens],
                    [tok.get('name', f'Account {i+1}') for i, tok in enumerate(tokens)]
                ),
                reply_markup=STOP_MARKUP,
                parse_mode="HTML"
            )
            state["pinned_message_id"] = status_msg.message_id
            await bot.pin_chat_message(chat_id=user_id, message_id=status_msg.message_id)
            await run_requests_parallel(user_id, bot, tokens, status_msg.message_id, state, speed_value)
            try: await bot.unpin_chat_message(chat_id=user_id, message_id=status_msg.message_id)
            except: pass
            state["running"] = False
            state.pop("mode", None)
            state.pop("stopped_by_user", None)
            state.pop("per_account", None)
            state.pop("account_names", None)
            return True
        else:
            await edit("Speed selection not allowed here.")
            return True

    return False
