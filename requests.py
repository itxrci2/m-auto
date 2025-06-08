import asyncio
import aiohttp
import html
import random
import logging
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest
from blocklist import is_blocklist_active, add_to_blocklist, get_user_blocklist
from dateutil import parser

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

def format_user(user):
    def time_ago(dt_str):
        if not dt_str:
            return "N/A"
        try:
            dt = parser.isoparse(dt_str)
            now = parser.parse("now")
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
    return (
        f"<b>Name:</b> {html.escape(user.get('name', 'N/A'))}\n"
        f"<b>ID:</b> <code>{html.escape(user.get('_id', 'N/A'))}</code>\n"
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

def format_progress(accounts, names):
    lines = ["Accounts Progress:"]
    for i, acc in enumerate(accounts):
        s = f"{names[i]}: {acc['added']} sent, {acc['skipped']} skipped"
        if acc.get("exceeded"): s += " (Exceeded)"
        lines.append(s)
    return "\n".join(lines)

async def safe_edit(bot, chat_id, msg_id, text, markup=None):
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=text, reply_markup=markup)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e): pass
        else: logging.warning(f"edit_message_text error: {e}")
    except Exception as e:
        logging.warning(f"edit_message_text unknown error: {e}")

async def run_requests_parallel(user_id, bot, tokens, status_message_id, state):
    accounts = [{"added":0, "skipped":0, "exceeded":False, "running":True} for _ in tokens]
    names = [tok.get("name", f"Account {i+1}") for i, tok in enumerate(tokens)]
    state["per_account"] = accounts
    state["account_names"] = names
    lock = asyncio.Lock()
    last_text = None

    async def update():
        nonlocal last_text
        text = format_progress(accounts, names)
        if text != last_text and not state.get("finalized"):
            last_text = text
            await safe_edit(bot, user_id, status_message_id, text, STOP_MARKUP)

    async def worker(i, token):
        acc = accounts[i]
        async with aiohttp.ClientSession() as session:
            while acc["running"] and state.get("running", True):
                users = await fetch_users(session, token["token"])
                if not users:
                    await update()
                    break
                blocklist = get_user_blocklist(user_id) if is_blocklist_active(user_id) else set()
                for user in users:
                    if not acc["running"] or not state.get("running", True): break
                    if user['_id'] in blocklist:
                        acc["skipped"] += 1; await update(); continue
                    url = f"https://api.meeff.com/user/undoableAnswer/v5/?userId={user['_id']}&isOkay=1"
                    headers = {"meeff-access-token": token["token"], "Connection": "keep-alive"}
                    async with session.get(url, headers=headers) as resp:
                        data = await resp.json()
                        if data.get("errorCode") == "LikeExceeded":
                            acc["exceeded"] = True; acc["running"] = False; await update(); return
                        acc["added"] += 1
                        if is_blocklist_active(user_id): add_to_blocklist(user_id, user['_id'])
                        try: await bot.send_message(user_id, format_user(user), parse_mode="HTML")
                        except: pass
                        await update(); await asyncio.sleep(1)
                await asyncio.sleep(1)
            await update()

    # Set finalized to False at the start
    state["finalized"] = False
    await safe_edit(bot, user_id, status_message_id, format_progress(accounts, names), STOP_MARKUP)
    await asyncio.gather(*(worker(idx, tok) for idx, tok in enumerate(tokens)))
    if state.get("finalized"):
        return
    state["finalized"] = True
    await safe_edit(bot, user_id, status_message_id, format_progress(accounts, names))

async def run_requests_single(user_id, state, bot, token, account_name):
    state["total_added_friends"] = 0
    state["skipped_count"] = 0
    last_text = None

    async def update():
        nonlocal last_text
        text = f"Account: {account_name}\nRequests sent: {state['total_added_friends']}\nSkipped: {state['skipped_count']}"
        if text != last_text and not state.get("finalized"):
            last_text = text
            await safe_edit(bot, user_id, state["status_message_id"], text, STOP_MARKUP)

    async with aiohttp.ClientSession() as session:
        while state["running"]:
            users = await fetch_users(session, token)
            if not users: await update(); break
            blocklist = get_user_blocklist(user_id) if is_blocklist_active(user_id) else set()
            for user in users:
                if not state["running"]: break
                if user['_id'] in blocklist:
                    state["skipped_count"] += 1; await update(); continue
                url = f"https://api.meeff.com/user/undoableAnswer/v5/?userId={user['_id']}&isOkay=1"
                headers = {"meeff-access-token": token, "Connection": "keep-alive"}
                async with session.get(url, headers=headers) as resp:
                    data = await resp.json()
                    if data.get("errorCode") == "LikeExceeded":
                        state["running"] = False
                        if state.get("finalized"):
                            return
                        state["finalized"] = True
                        await safe_edit(bot, user_id, state["status_message_id"],
                            f"Account: {account_name}\nLike limit exceeded!\nRequests sent: {state['total_added_friends']}")
                        return
                    state["total_added_friends"] += 1
                    if is_blocklist_active(user_id): add_to_blocklist(user_id, user['_id'])
                    try: await bot.send_message(user_id, format_user(user), parse_mode="HTML")
                    except: pass
                    await update(); await asyncio.sleep(1)
            await asyncio.sleep(1)
    if state.get("finalized"):
        return
    state["finalized"] = True
    await safe_edit(bot, user_id, state["status_message_id"],
        f"Account: {account_name}\nRequests sent: {state['total_added_friends']}\nSkipped: {state['skipped_count']}")

def run_requests(user_id, state, bot, get_current_account, account_name=None):
    token = get_current_account(user_id)
    return run_requests_single(user_id, state, bot, token, account_name or "Current")

async def handle_requests_callback(
    callback_query, state, bot, user_id, get_current_account, get_tokens, set_current_account, start_markup
):
    data = callback_query.data

    async def edit(text, markup=None):
        await callback_query.message.edit_text(text, reply_markup=markup)
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
        tokens = get_tokens(user_id)
        if not tokens:
            await edit("No accounts found.", start_markup)
            state.pop("pending_requests_all", None)
            return True
        state.update({"running": True, "finalized": False, "mode": "all"})
        status_msg = await callback_query.message.edit_text(
            "Accounts Progress:\n" + "\n".join(f"{tok.get('name', f'Account {i+1}')}: 0 sent, 0 skipped"
                for i, tok in enumerate(tokens)), reply_markup=STOP_MARKUP
        )
        state["pinned_message_id"] = status_msg.message_id
        await bot.pin_chat_message(chat_id=user_id, message_id=status_msg.message_id)
        await run_requests_parallel(user_id, bot, tokens, status_msg.message_id, state)
        try: await bot.unpin_chat_message(chat_id=user_id, message_id=status_msg.message_id)
        except: pass
        state.pop("pending_requests_all", None)
        state["running"] = False
        return True

    if data == "requests_cancel":
        state.pop("pending_requests_all", None)
        await edit("Requests operation cancelled.", start_markup)
        await callback_query.answer("Cancelled.")
        return True

    if data == "requests_current":
        if state.get("running"):
            await callback_query.answer("Requests are already running!")
            return True
        tokens = get_tokens(user_id)
        current_token = get_current_account(user_id)
        account_name = next((tok.get("name", "Current") for tok in tokens if tok["token"] == current_token), "Current")
        state.update({"running": True, "finalized": False, "mode": "current", "skipped_count": 0})
        status_message = await callback_query.message.edit_text(
            f"Account: {account_name}\nRequests sent: 0\nSkipped: 0", reply_markup=STOP_MARKUP
        )
        state["status_message_id"] = status_message.message_id
        state["pinned_message_id"] = status_message.message_id
        await bot.pin_chat_message(chat_id=user_id, message_id=state["status_message_id"])
        await run_requests_single(user_id, state, bot, current_token, account_name)
        pin_id = state.get("pinned_message_id")
        if pin_id:
            try: await bot.unpin_chat_message(chat_id=user_id, message_id=pin_id)
            except: pass
            state["pinned_message_id"] = None
        state["running"] = False
        state.pop("mode", None)
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
        if state.get("mode") == "all" and "per_account" in state and "account_names" in state:
            await callback_query.message.edit_text(
                format_progress(state["per_account"], state["account_names"]), reply_markup=start_markup
            )
            state.pop("per_account", None)
            state.pop("account_names", None)
            state.pop("mode", None)
            if pin_id:
                try: await bot.unpin_chat_message(chat_id=user_id, message_id=pin_id)
                except: pass
                state["pinned_message_id"] = None
            state["running"] = False
            state.pop("stopped_by_user", None)
            return True
        tokens = get_tokens(user_id)
        current_token = get_current_account(user_id)
        account_name = next((tok.get("name", "Current") for tok in tokens if tok["token"] == current_token), "Current")
        msg = f"Account: {account_name}\nRequests sent: {state.get('total_added_friends',0)}\nSkipped: {state.get('skipped_count',0)}"
        await callback_query.message.edit_text(msg, reply_markup=start_markup)
        if pin_id:
            try: await bot.unpin_chat_message(chat_id=user_id, message_id=pin_id)
            except: pass
            state["pinned_message_id"] = None
        state["running"] = False
        state.pop("stopped_by_user", None)
        state.pop("mode", None)
        state.pop("per_account", None)
        state.pop("account_names", None)
        return True

    return False
