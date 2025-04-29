from aiogram import types
from db import get_current_account, get_user_filters, set_user_filters
from common import get_filter_keyboard, get_gender_keyboard, get_age_keyboard, get_nationality_keyboard
import aiohttp
import json

async def filter_command(msg, edit=False):
    """Show the filter menu, edit message if edit=True, else send new message."""
    user_id = getattr(msg, 'chat', msg).id
    token = get_current_account(user_id)
    text = "Set your filter preferences:" if token else "No active account found. Please set an account before updating filters."
    markup = get_filter_keyboard()
    if edit and hasattr(msg, "edit_text"):
        await msg.edit_text(text, reply_markup=markup)
    else:
        await msg.answer(text, reply_markup=markup)

async def set_filter(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    token = get_current_account(user_id)
    if not token:
        await callback_query.message.edit_text("No active account found. Please set an account before updating filters.")
        return

    filters = get_user_filters(user_id, token) or {}
    filter_data = {
        "filterGenderType": filters.get("filterGenderType", 7),
        "filterBirthYearFrom": filters.get("filterBirthYearFrom", 1979),
        "filterBirthYearTo": 2006,
        "filterDistance": 510,
        "filterLanguageCodes": filters.get("filterLanguageCodes", ""),
        "filterNationalityBlock": filters.get("filterNationalityBlock", 0),
        "filterNationalityCode": filters.get("filterNationalityCode", ""),
        "locale": "en"
    }

    d = callback_query.data
    if d == "filter_gender":
        await callback_query.message.edit_text("Select Gender:", reply_markup=get_gender_keyboard())
        return
    if d.startswith("filter_gender_"):
        gender = d.split("_")[-1]
        filter_data["filterGenderType"] = {"male": 6, "female": 5, "all": 7}.get(gender, 7)
        msg = f"Filter updated: Gender set to {gender.capitalize()}"
    elif d == "filter_age":
        await callback_query.message.edit_text("Select Age:", reply_markup=get_age_keyboard())
        return
    elif d.startswith("filter_age_"):
        age = int(d.split("_")[-1])
        filter_data["filterBirthYearFrom"] = 2024 - age  # Adjust current year if needed
        filter_data["filterBirthYearTo"] = 2006
        msg = f"Filter updated: Age set to {age}"
    elif d == "filter_nationality":
        await callback_query.message.edit_text("Select Nationality:", reply_markup=get_nationality_keyboard())
        return
    elif d.startswith("filter_nationality_"):
        nationality = d.split("_")[-1]
        filter_data["filterNationalityCode"] = "" if nationality == "all" else nationality
        msg = f"Filter updated: Nationality set to {nationality}"
    else:
        return

    set_user_filters(user_id, token, filter_data)
    headers = {
        'User-Agent': "okhttp/4.12.0",
        'Accept-Encoding': "gzip",
        'meeff-access-token': token,
        'content-type': "application/json; charset=utf-8"
    }
    url = "https://api.meeff.com/user/updateFilter/v1"
    async with aiohttp.ClientSession() as session:
        async with session.post(url, data=json.dumps(filter_data), headers=headers) as response:
            if response.status == 200:
                await callback_query.message.edit_text(msg)
            else:
                resp_text = await response.text()
                await callback_query.message.edit_text(f"Failed to update filter. Response: {resp_text}")
