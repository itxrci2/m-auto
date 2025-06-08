import asyncio
import aiohttp
import html
import logging
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

COUNTRIES = [
    "AF", "AX", "AL", "DZ", "AS", "AD", "AO", "AI", "AQ", "AG", "AR", "AM", "AW", "AU", "AT", "AZ",
    "BS", "BH", "BD", "BB", "BY", "BE", "BZ", "BJ", "BM", "BT", "BO", "BQ", "BA", "BW", "BV", "BR",
    "IO", "BN", "BG", "BF", "BI", "CV", "KH", "CM", "CA", "KY", "CF", "TD", "CL", "CN", "CX", "CC",
    "CO", "KM", "CG", "CD", "CK", "CR", "CI", "HR", "CU", "CW", "CY", "CZ", "DK", "DJ", "DM", "DO",
    "EC", "EG", "SV", "GQ", "ER", "EE", "SZ", "ET", "FK", "FO", "FJ", "FI", "FR", "GF", "PF", "TF",
    "GA", "GM", "GE", "DE", "GH", "GI", "GR", "GL", "GD", "GP", "GU", "GT", "GG", "GN", "GW", "GY",
    "HT", "HM", "VA", "HN", "HK", "HU", "IS", "IN", "ID", "IR", "IQ", "IE", "IM", "IL", "IT", "JM",
    "JP", "JE", "JO", "KZ", "KE", "KI", "KP", "KR", "KW", "KG", "LA", "LV", "LB", "LS", "LR", "LY",
    "LI", "LT", "LU", "MO", "MG", "MW", "MY", "MV", "ML", "MT", "MH", "MQ", "MR", "MU", "YT", "MX",
    "FM", "MD", "MC", "MN", "ME", "MS", "MA", "MZ", "MM", "NA", "NR", "NP", "NL", "NC", "NZ", "NI",
    "NE", "NG", "NU", "NF", "MK", "MP", "NO", "OM", "PK", "PW", "PS", "PA", "PG", "PY", "PE", "PH",
    "PN", "PL", "PT", "PR", "QA", "RE", "RO", "RU", "RW", "BL", "SH", "KN", "LC", "MF", "PM", "VC",
    "WS", "SM", "ST", "SA", "SN", "RS", "SC", "SL", "SG", "SX", "SK", "SI", "SB", "SO", "ZA", "GS",
    "SS", "ES", "LK", "SD", "SR", "SJ", "SE", "CH", "SY", "TW", "TJ", "TZ", "TH", "TL", "TG", "TK",
    "TO", "TT", "TN", "TR", "TM", "TC", "TV", "UG", "UA", "AE", "GB", "US", "UM", "UY", "UZ", "VU",
    "VE", "VN", "VG", "VI", "WF", "EH", "YE", "ZM", "ZW"
]
REQUESTS_PER_COUNTRY = 2
BASE_HEADERS = {
    "User-Agent": "okhttp/4.12.0",
    "Accept-Encoding": "gzip",
    "Content-Type": "application/json; charset=utf-8"
}

ALL_COUNTRIES_CHOICE_MARKUP = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="Current", callback_data="allcountries_current"),
        InlineKeyboardButton(text="All", callback_data="allcountries_all")
    ],
    [InlineKeyboardButton(text="Cancel", callback_data="allcountries_cancel")]
])
ALL_COUNTRIES_ALL_CONFIRM_MARKUP = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Confirm", callback_data="allcountries_confirm")],
    [InlineKeyboardButton(text="Cancel", callback_data="allcountries_cancel")]
])
ALL_COUNTRIES_STOP_MARKUP = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Stop", callback_data="stop")]
])

async def update_country_filter(session, headers, country_code):
    url = "https://api.meeff.com/user/updateFilter/v1"
    data = {
        "filterGenderType": 5, "filterBirthYearFrom": 1981, "filterBirthYearTo": 2007,
        "filterDistance": 510, "filterLanguageCodes": "", "filterNationalityBlock": 0,
        "filterNationalityCode": country_code, "locale": "en"
    }
    try:
        async with session.post(url, json=data, headers=headers) as resp:
            if resp.status != 200:
                logging.error(f"❌ Failed to update country: {country_code}, status: {resp.status}")
    except Exception as e:
        logging.error(f"❌ Exception updating country filter for {country_code}: {e}")

async def fetch_users(session, headers):
    url = "https://api.meeff.com/user/explore/v2/?lat=-3.7895238&lng=-38.5327365"
    try:
        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                return (await resp.json()).get("users", [])
    except Exception as e:
        logging.error(f"❌ Exception fetching users: {e}")
    return []

async def like_user(session, headers, user_id):
    url = f"https://api.meeff.com/user/undoableAnswer/v5/?userId={user_id}&isOkay=1"
    try:
        async with session.get(url, headers=headers) as resp:
            if resp.status == 429:
                return False
    except Exception as e:
        logging.error(f"❌ Exception liking user {user_id}: {e}")
    return True

async def run_all_countries_token(user_id, state, bot, token, account_name, show_progress=True):
    if not token:
        await bot.edit_message_text(
            chat_id=user_id, message_id=state["status_message_id"],
            text="No active account found. Please set an account before starting All Countries feature."
        )
        return 0, 0, False

    headers = dict(BASE_HEADERS)
    headers["meeff-access-token"] = token
    requests_sent = countries_processed = 0
    like_limit_exceeded = False

    async with aiohttp.ClientSession() as session:
        for country_code in COUNTRIES:
            if not state["running"]:
                break
            await update_country_filter(session, headers, country_code)
            users = await fetch_users(session, headers)
            country_requests = 0
            countries_processed += 1
            state["countries_processed"] = countries_processed
            state["total_added_friends"] = requests_sent
            for user in users:
                if country_requests >= REQUESTS_PER_COUNTRY or not state["running"]:
                    break
                if not await like_user(session, headers, user["_id"]):
                    like_limit_exceeded = True
                    break  # break only the inner (user) loop, not the countries or accounts
                requests_sent += 1
                country_requests += 1
                state["total_added_friends"] = requests_sent
                if show_progress:
                    await bot.edit_message_text(
                        chat_id=user_id, message_id=state["status_message_id"],
                        text=f"Account: {account_name}\nCountry: {country_code} Requests sent: {requests_sent}",
                        reply_markup=state.get("stop_markup")
                    )
                await asyncio.sleep(4)
            if like_limit_exceeded:  # if like limit, do NOT continue to next country, exit for this account
                break
            await asyncio.sleep(1)
        state["countries_processed"] = countries_processed
        state["total_added_friends"] = requests_sent
    return requests_sent, countries_processed, like_limit_exceeded

def run_all_countries(user_id, state, bot, get_current_account, account_name, show_progress=True):
    token = get_current_account(user_id)
    return run_all_countries_token(user_id, state, bot, token, account_name, show_progress)

async def handle_all_countries_callback(
    callback_query, state, bot, user_id,
    get_current_account, get_tokens, set_current_account,
    run_all_countries, start_markup
):
    data = callback_query.data

    if data == "all_countries":
        await callback_query.message.edit_text(
            "How would you like to run All Countries feature?",
            reply_markup=ALL_COUNTRIES_CHOICE_MARKUP
        )
        await callback_query.answer()
        return True

    if data == "allcountries_all":
        tokens = get_tokens(user_id)
        if not tokens:
            await callback_query.message.edit_text("No accounts found.", reply_markup=start_markup)
            await callback_query.answer()
            return True
        account_lines = "\n".join(f"{idx+1}. {t.get('name', f'Account {idx+1}')}" for idx, t in enumerate(tokens))
        await callback_query.message.edit_text(
            f"You chose to run All Countries for ALL accounts. Press Confirm to proceed.\n\nAccounts to process:\n{account_lines}",
            reply_markup=ALL_COUNTRIES_ALL_CONFIRM_MARKUP
        )
        state["pending_allcountries_all"] = True
        await callback_query.answer()
        return True

    if data == "allcountries_confirm":
        if not state.get("pending_allcountries_all"):
            await callback_query.answer("Nothing to confirm.")
            return True
        tokens = get_tokens(user_id)
        if not tokens:
            await callback_query.message.edit_text("No accounts found.", reply_markup=start_markup)
            await callback_query.answer()
            state.pop("pending_allcountries_all", None)
            return True
        per_account_requests_sent = []
        total_countries = total_requests = 0
        like_limit_exceeded = False
        for idx, token_info in enumerate(tokens):
            account_name = token_info.get('name', f"Account {idx+1}")
            token = token_info["token"]
            state["running"] = True
            await callback_query.message.edit_text(
                f"Account {idx+1}: {html.escape(account_name)}\nStarting All Countries feature...",
                reply_markup=ALL_COUNTRIES_STOP_MARKUP, parse_mode="HTML"
            )
            state["status_message_id"] = callback_query.message.message_id
            state["pinned_message_id"] = callback_query.message.message_id
            state["stop_markup"] = ALL_COUNTRIES_STOP_MARKUP
            await bot.pin_chat_message(chat_id=user_id, message_id=state["pinned_message_id"])
            requests_sent, countries_processed, like_limit = await run_all_countries_token(
                user_id, state, bot, token, account_name
            )
            per_account_requests_sent.append(requests_sent)
            total_countries = max(total_countries, countries_processed)
            total_requests += requests_sent
            if like_limit: like_limit_exceeded = True
            try:
                await bot.unpin_chat_message(chat_id=user_id, message_id=state["pinned_message_id"])
            except Exception:
                pass
            state["pinned_message_id"] = None
            # DO NOT break here on like_limit, only break if state["running"] is False (user stopped)
            if not state.get("running"):
                break
        summary_text = (
            f"Total Account: {len(per_account_requests_sent)}\n"
            f"Countries: {total_countries}\n"
            f"Requests sent successfully ({total_requests})\n"
            f"({' | '.join(str(x) for x in per_account_requests_sent)})"
        )
        if like_limit_exceeded: summary_text += "\nLike limit exceeded."
        await callback_query.message.edit_text(summary_text, reply_markup=start_markup)
        await callback_query.answer()
        state.pop("pending_allcountries_all", None)
        return True

    if data == "allcountries_cancel":
        state.pop("pending_allcountries_all", None)
        await callback_query.message.edit_text("All Countries operation cancelled.", reply_markup=start_markup)
        await callback_query.answer("Cancelled.")
        return True

    if data == "allcountries_current":
        if state.get("running"):
            await callback_query.answer("Another process is already running!")
            return True
        tokens = get_tokens(user_id)
        current_token = get_current_account(user_id)
        account_name = next((t.get("name", "Current") for t in tokens if t["token"] == current_token), "Current")
        state["running"] = True
        try:
            await callback_query.message.edit_text(
                f"Account: {html.escape(account_name)}\nStarting All Countries feature...",
                reply_markup=ALL_COUNTRIES_STOP_MARKUP, parse_mode="HTML"
            )
            state["status_message_id"] = callback_query.message.message_id
            state["pinned_message_id"] = callback_query.message.message_id
            state["stop_markup"] = ALL_COUNTRIES_STOP_MARKUP
            await bot.pin_chat_message(chat_id=user_id, message_id=state["pinned_message_id"])
            async def run_and_report():
                requests_sent, countries_processed, like_limit = await run_all_countries_token(
                    user_id, state, bot, current_token, account_name
                )
                summary_text = (
                    f"Account: {account_name}\n"
                    f"Countries: {countries_processed}\n"
                    f"Requests sent successfully ({requests_sent})"
                )
                if like_limit: summary_text += "\nLike limit exceeded."
                await bot.edit_message_text(
                    chat_id=user_id, message_id=state["status_message_id"],
                    text=summary_text, reply_markup=start_markup
                )
                try:
                    await bot.unpin_chat_message(chat_id=user_id, message_id=state["pinned_message_id"])
                except Exception:
                    pass
                state["pinned_message_id"] = None
            asyncio.create_task(run_and_report())
            await callback_query.answer("All Countries feature started!")
        except Exception as e:
            logging.error(f"Error while starting All Countries feature: {e}")
            await callback_query.message.edit_text("Failed to start All Countries feature.", reply_markup=start_markup)
            state["running"] = False
        return True

    if data == "stop":
        if not state["running"]:
            await callback_query.answer("All Countries are not running!")
        else:
            state["running"] = False
            tokens = get_tokens(user_id)
            current_token = get_current_account(user_id)
            account_name = next((t.get("name", "Current") for t in tokens if t["token"] == current_token), "Current")
            countries_processed = state.get("countries_processed", 0)
            requests_sent = state.get("total_added_friends", 0)
            message_text = (
                f"Account: {account_name}\n"
                f"Countries: {countries_processed}\n"
                f"Requests sent successfully ({requests_sent})"
            )
            await callback_query.message.edit_text(message_text, reply_markup=start_markup)
            await callback_query.answer("Stopped.")
            if state.get("pinned_message_id"):
                await bot.unpin_chat_message(chat_id=user_id, message_id=state["pinned_message_id"])
                state["pinned_message_id"] = None
        return True

    return False
