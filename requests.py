import asyncio
import aiohttp
import html
import logging
from dateutil import parser
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from blocklist import is_blocklist_active, add_to_blocklist, get_user_blocklist

# --- Inline Keyboards ---
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

def format_user_details(user):
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
        if response.status != 200:
            logging.error(f"Failed to fetch users: {response.status}")
            return []
        return (await response.json()).get("users", [])

async def update_status(user_id, bot, state, account_name, batch_no, total_added, skipped_count=0):
    msg = f"Account: {account_name}\nBatch: {batch_no} Requests sent: {total_added}"
    if skipped_count:
        msg += f"\nSkipped: {skipped_count}"
    try:
        await bot.edit_message_text(
            chat_id=user_id,
            message_id=state["status_message_id"],
            text=msg,
            reply_markup=STOP_MARKUP
        )
    except Exception as e:
        logging.error(f"Error updating status: {e}")

async def finish_requests(user_id, bot, state, account_name, text, skipped_count=0):
    msg = f"Account: {account_name}\n{text}"
    if skipped_count:
        msg += f"\nSkipped: {skipped_count}"
    try:
        await bot.edit_message_text(
            chat_id=user_id,
            message_id=state["status_message_id"],
            text=msg,
            reply_markup=None
        )
    except Exception as e:
        logging.error(f"Error editing message on finish: {e}")
    state["running"] = False
    state.pop("stopped_by_user", None)
    if state.get("pinned_message_id"):
        try:
            await bot.unpin_chat_message(chat_id=user_id, message_id=state["pinned_message_id"])
        except Exception as e:
            logging.warning(f"Error unpinning message on finish: {e}")
        state["pinned_message_id"] = None

async def process_users(session, users, token, user_id, state, bot, account_name):
    blocklist_active = is_blocklist_active(user_id)
    blocklist_ids = get_user_blocklist(user_id)
    skipped_count = state.get("skipped_count", 0)

    for user in users:
        if not state["running"]:
            break
        user_id_to_add = user['_id']
        if user_id_to_add in blocklist_ids:
            skipped_count += 1
            state["skipped_count"] = skipped_count
            await update_status(
                user_id, bot, state, account_name, state["batch_index"],
                state.get("total_added_friends", 0), skipped_count
            )
            continue
        url = f"https://api.meeff.com/user/undoableAnswer/v5/?userId={user_id_to_add}&isOkay=1"
        headers = {"meeff-access-token": token, "Connection": "keep-alive"}
        async with session.get(url, headers=headers) as response:
            data = await response.json()
            if data.get("errorCode") == "LikeExceeded":
                await finish_requests(user_id, bot, state, account_name, "Daily like limit reached.", skipped_count)
                return True
            await bot.send_message(chat_id=user_id, text=format_user_details(user), parse_mode="HTML")
            state["total_added_friends"] += 1
            if blocklist_active:
                add_to_blocklist(user_id, user_id_to_add)
            if state["running"]:
                await update_status(
                    user_id, bot, state, account_name, state["batch_index"],
                    state["total_added_friends"], skipped_count
                )
            await asyncio.sleep(1)
    state["skipped_count"] = skipped_count
    return skipped_count

async def run_requests(user_id, state, bot, get_current_account, account_name=None):
    state["total_added_friends"] = 0
    state["batch_index"] = 0
    state["skipped_count"] = 0
    async with aiohttp.ClientSession() as session:
        while state["running"]:
            try:
                token = get_current_account(user_id)
                if not token:
                    await finish_requests(
                        user_id, bot, state, account_name,
                        "No active account found. Please set an account before starting requests.",
                        state.get("skipped_count", 0)
                    )
                    return state.get("skipped_count", 0)
                users = await fetch_users(session, token)
                state["batch_index"] += 1
                if not users:
                    await update_status(
                        user_id, bot, state, account_name or 'Current',
                        state["batch_index"], state["total_added_friends"],
                        state.get("skipped_count", 0)
                    )
                else:
                    skipped_count = await process_users(
                        session, users, token, user_id, state, bot, account_name or "Current"
                    )
                    if skipped_count is True:
                        break
                await asyncio.sleep(1)
            except Exception as e:
                if state.get("stopped_by_user"):
                    return state.get("skipped_count", 0)
                await finish_requests(
                    user_id, bot, state, account_name,
                    f"An error occurred: {e}", state.get("skipped_count", 0)
                )
                break
    return state.get("skipped_count", 0)

async def handle_requests_callback(
    callback_query,
    state,
    bot,
    user_id,
    get_current_account,
    get_tokens,
    set_current_account,
    start_markup
):
    data = callback_query.data

    async def edit(text, markup=None):
        await callback_query.message.edit_text(text, reply_markup=markup)
        await callback_query.answer()

    if data == "start":
        await edit("How would you like to send requests?", REQUESTS_CHOICE_MARKUP)
        return True

    if data == "requests_all":
        await edit("You chose to run requests for ALL accounts.\nPress Confirm to proceed.", REQUESTS_ALL_CONFIRM_MARKUP)
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
        per_account_added = []
        per_account_skipped = []
        for idx, token_info in enumerate(tokens):
            account_name = token_info.get('name', f"Account {idx+1}")
            set_current_account(user_id, token_info["token"])
            state["running"] = True
            state["skipped_count"] = 0
            status_message = await callback_query.message.edit_text(
                f"Account: {account_name}\nBatch: 1 Requests sent: 0",
                reply_markup=STOP_MARKUP,
                parse_mode="HTML"
            )
            state["status_message_id"] = status_message.message_id
            state["pinned_message_id"] = status_message.message_id
            await bot.pin_chat_message(chat_id=user_id, message_id=state["status_message_id"])
            try:
                skipped_count = await run_requests(user_id, state, bot, get_current_account, account_name=account_name)
            except Exception:
                skipped_count = state.get("skipped_count", 0)
            per_account_added.append(state.get("total_added_friends", 0))
            per_account_skipped.append(skipped_count or 0)
            pin_id = state.get("pinned_message_id")
            if pin_id:
                try:
                    await bot.unpin_chat_message(chat_id=user_id, message_id=pin_id)
                except Exception:
                    pass
                state["pinned_message_id"] = None
            if not state.get("running"):
                break

        summary_text = (
            f"Total Account: {len(tokens)}\n"
            f"Requests sent successfully\n"
            f"({' | '.join(str(x) for x in per_account_added)})"
        )
        if any(per_account_skipped):
            summary_text += "\nSkipped: " + " | ".join(str(x) for x in per_account_skipped)
        await edit(summary_text, start_markup)
        state.pop("pending_requests_all", None)
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
        account_name = next((t.get("name", "Current") for t in tokens if t["token"] == current_token), "Current")
        state["running"] = True
        state["skipped_count"] = 0
        try:
            status_message = await callback_query.message.edit_text(
                f"Account: {account_name}\nBatch: 1 Requests sent: 0",
                reply_markup=STOP_MARKUP
            )
            state["status_message_id"] = status_message.message_id
            state["pinned_message_id"] = status_message.message_id
            await bot.pin_chat_message(chat_id=user_id, message_id=state["status_message_id"])
            skipped_count = await run_requests(user_id, state, bot, get_current_account, account_name=account_name)
            final_msg = (
                f"Account: {account_name}\nRequests sent successfully ({state.get('total_added_friends', 0)})"
            )
            if skipped_count:
                final_msg += f"\nSkipped: {skipped_count}"
            await bot.edit_message_text(
                chat_id=user_id,
                message_id=state["status_message_id"],
                text=final_msg,
                reply_markup=start_markup
            )
            await callback_query.answer("Requests finished!")
            pin_id = state.get("pinned_message_id")
            if pin_id:
                try:
                    await bot.unpin_chat_message(chat_id=user_id, message_id=pin_id)
                except Exception:
                    pass
                state["pinned_message_id"] = None
        except Exception as e:
            logging.error(f"Error while starting requests: {e}")
            if not state.get("stopped_by_user"):
                await edit("Failed to start requests. Please try again later.", start_markup)
            state["running"] = False
            state.pop("stopped_by_user", None)
        return True

    if data == "stop":
        if not state["running"]:
            await callback_query.answer("Requests are not running!")
            return True
        state["running"] = False
        state["stopped_by_user"] = True
        tokens = get_tokens(user_id)
        current_token = get_current_account(user_id)
        account_name = next((t.get("name", "Current") for t in tokens if t["token"] == current_token), "Current")
        try:
            skipped_count = state.get("skipped_count", 0)
            msg = f"Account: {account_name}\nRequests sent successfully ({state.get('total_added_friends', 0)})"
            if skipped_count:
                msg += f"\nSkipped: {skipped_count}"
            await callback_query.message.edit_text(
                msg,
                reply_markup=start_markup
            )
        except Exception as e:
            logging.error(f"Error editing message on stop: {e}")
        await callback_query.answer("Stopped.")
        pin_id = state.get("pinned_message_id")
        if pin_id:
            try:
                await bot.unpin_chat_message(chat_id=user_id, message_id=pin_id)
            except Exception as e:
                logging.warning(f"Error unpinning message on stop: {e}")
            state["pinned_message_id"] = None
        state.pop("stopped_by_user", None)
        return True

    return False
