import aiohttp
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from db import set_token, get_tokens
from requests import format_user

# --- MODIFIED PROFILE CARD FORMATTER ---
def format_user_with_nationality(user):
    def time_ago(dt_str):
        if not dt_str:
            return "N/A"
        try:
            from dateutil import parser
            from datetime import datetime, timezone
            dt = parser.isoparse(dt_str)
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
    return (
        f"<b>Name:</b> {user.get('name', 'N/A')}\n"
        f"<b>ID:</b> <code>{user.get('_id', 'N/A')}</code>\n"
        f"<b>Description:</b> {user.get('description', 'N/A')}\n"
        f"<b>Birth Year:</b> {user.get('birthYear', 'N/A')}\n"
        f"<b>Nationality Code:</b> {user.get('nationalityCode', 'N/A')}\n"
        f"<b>Platform:</b> {user.get('platform', 'N/A')}\n"
        f"<b>Profile Score:</b> {user.get('profileScore', 'N/A')}\n"
        f"<b>Distance:</b> {user.get('distance', 'N/A')} km\n"
        f"<b>Language Codes:</b> {', '.join(user.get('languageCodes', []))}\n"
        f"<b>Last Active:</b> {last_active}\n"
        "Photos: " + ' '.join([f"<a href='{url}'>Photo</a>" for url in user.get('photoUrls', [])])
    )

SIGNUP_MENU = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="Sign Up", callback_data="signup_go"),
        InlineKeyboardButton(text="Sign In", callback_data="signin_go")
    ]
])

VERIFY_BUTTON = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Verify Email", callback_data="signup_verify")]
])
BACK_TO_SIGNUP = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Back", callback_data="signup_menu")]
])

user_signup_states = {}

async def signup_command(message: Message):
    user_signup_states[message.chat.id] = {"stage": "menu"}
    await message.answer("Choose an option:", reply_markup=SIGNUP_MENU)

async def signup_callback_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    state = user_signup_states.get(user_id, {"stage": "menu"})
    if callback.data == "signup_go":
        state["stage"] = "ask_email"
        user_signup_states[user_id] = state
        await callback.message.edit_text("Enter your email for registration:", reply_markup=BACK_TO_SIGNUP)
        await callback.answer()
        return True
    if callback.data == "signup_menu":
        state["stage"] = "menu"
        await callback.message.edit_text("Choose an option:", reply_markup=SIGNUP_MENU)
        await callback.answer()
        return True
    if callback.data == "signin_go":
        state["stage"] = "signin_email"
        user_signup_states[user_id] = state
        await callback.message.edit_text("Enter your email to sign in:", reply_markup=BACK_TO_SIGNUP)
        await callback.answer()
        return True
    if callback.data == "signup_verify":
        creds = state.get("creds")
        if not creds:
            await callback.answer("No signup info. Please sign up again.", show_alert=True)
            state["stage"] = "menu"
            await callback.message.edit_text("Choose an option:", reply_markup=SIGNUP_MENU)
            return True
        await callback.message.edit_text("Checking verification and logging in...", reply_markup=None)
        login_result = await try_signin(creds['email'], creds['password'])
        if login_result.get("accessToken"):
            await store_token_and_show_card(callback.message, login_result, creds)
        elif login_result.get("errorCode") == "NotVerified":
            await callback.message.edit_text("Email not verified! Please check your inbox and click the link, then try Verify again.", reply_markup=VERIFY_BUTTON)
        else:
            await callback.message.edit_text(f"Login failed: {login_result.get('errorMessage', 'Unknown error')}", reply_markup=SIGNUP_MENU)
        return True
    return False

async def signup_message_handler(message: Message):
    user_id = message.from_user.id
    if user_id not in user_signup_states:
        return False
    state = user_signup_states[user_id]
    if message.text and message.text.startswith("/"):
        return False

    # SIGNUP FLOW
    if state.get("stage") == "ask_email":
        state["stage"] = "ask_password"
        state["email"] = message.text.strip()
        await message.answer("Enter a password for your account:", reply_markup=BACK_TO_SIGNUP)
        return True
    if state.get("stage") == "ask_password":
        state["stage"] = "ask_name"
        state["password"] = message.text.strip()
        await message.answer("Enter your display name:", reply_markup=BACK_TO_SIGNUP)
        return True
    if state.get("stage") == "ask_name":
        state["stage"] = "ask_gender"
        state["name"] = message.text.strip()
        await message.answer("Enter your gender (M/F):", reply_markup=BACK_TO_SIGNUP)
        return True
    if state.get("stage") == "ask_gender":
        gender = message.text.strip().upper()
        if gender not in ("M", "F"):
            await message.answer("Please enter M or F for gender:")
            return True
        state["stage"] = "ask_desc"
        state["gender"] = gender
        await message.answer("Enter your profile description:", reply_markup=BACK_TO_SIGNUP)
        return True
    if state.get("stage") == "ask_desc":
        state["stage"] = "signup_submit"
        state["desc"] = message.text.strip()
        processing_msg = await message.answer("Registering your account, please wait...", reply_markup=None)
        signup_result = await try_signup(state)
        if signup_result.get("user", {}).get("_id"):
            state["creds"] = {
                "email": state["email"],
                "password": state["password"],
                "name": state["name"],
            }
            state["stage"] = "await_verify"
            await processing_msg.edit_text("Account created! Please verify your email, then click the button below.", reply_markup=VERIFY_BUTTON)
        else:
            err = signup_result.get("errorMessage", "Registration failed.")
            state["stage"] = "menu"
            await processing_msg.edit_text(f"Signup failed: {err}", reply_markup=SIGNUP_MENU)
        return True

    # SIGNIN FLOW
    if state.get("stage") == "signin_email":
        state["stage"] = "signin_password"
        state["signin_email"] = message.text.strip()
        await message.answer("Enter your password:", reply_markup=BACK_TO_SIGNUP)
        return True
    if state.get("stage") == "signin_password":
        email = state["signin_email"]
        password = message.text.strip()
        processing_msg = await message.answer("Signing in, please wait...", reply_markup=None)
        login_result = await try_signin(email, password)
        if login_result.get("accessToken"):
            creds = {"email": email, "password": password}
            await store_token_and_show_card(processing_msg, login_result, creds)
            state["stage"] = "menu"
        else:
            err = login_result.get("errorMessage", "Sign in failed.")
            await processing_msg.edit_text(f"Sign in failed: {err}", reply_markup=SIGNUP_MENU)
            state["stage"] = "menu"
        return True

    return False

async def try_signup(state):
    url = "https://api.meeff.com/user/register/email/v4"
    payload = {
      "providerId": state["email"],
      "providerToken": state["password"],
      "os": "Android v13",
      "platform": "android",
      "device": "BRAND: IPHONE, MODEL: 11, DEVICE: Infinix-X670, PRODUCT: X670-GL, DISPLAY: X670-H814DGHJKL-T-GL-240224V556",
      "pushToken": "cM_FLbrFTvSGxIbV6IBusT:APA91bFw8faC6nA_QUWskKsVhwnWz-ioHTdNpHC5Kk3eXonehp8VFVntWcz_2BiyF-fcYnP4DGOIu27gJPEff8p1uDk3e4DiYpFGInC08eFMH9MJjnuZ-Jc",
      "deviceUniqueId": "56cb9030870fa44a",
      "deviceLanguage": "en",
      "deviceRegion": "US",
      "simRegion": "PK",
      "deviceGmtOffset": "+0500",
      "deviceRooted": 0,
      "deviceEmulator": 0,
      "appVersion": "6.5.5",
      "name": state["name"],
      "gender": state["gender"],
      "color": "777777",
      "birthYear": 2004,
      "birthMonth": 3,
      "birthDay": 1,
      "nationalityCode": "US",
      "languages": "en,zh,ko,be,ru,uk",
      "levels": "5,1,1,1,1,1",
      "description": state["desc"],
      "photos": "https://meeffus.s3.amazonaws.com/profile/2025/06/16/20250616052423006_profile-1.0-bd262b27-1916-4bd3-9f1d-0e7fdba35268.jpg|https://meeffus.s3.amazonaws.com/profile/2025/06/16/20250616052438006_profile-1.0-349bf38c-4555-40cc-a322-e61afe15aa35.jpg",
      "purpose": "PB000000,PB000001",
      "purposeEtcDetail": "",
      "interest": "IS000001,IS000002,IS000003,IS000004,IS000005,IS000006,IS000007,IS000008",
      "locale": "en"
    }
    headers = {
      'User-Agent': "okhttp/5.0.0-alpha.14",
      'Accept-Encoding': "gzip",
      'Content-Type': "application/json",
      'content-type': "application/json; charset=utf-8"
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers) as resp:
            return await resp.json()

async def try_signin(email, password):
    url = "https://api.meeff.com/user/login/v4"
    payload = {
      "provider": "email",
      "providerId": email,
      "providerToken": password,
      "os": "Android v13",
      "platform": "android",
      "device": "BRAND: IPHONE, MODEL: 11, DEVICE: Infinix-X670, PRODUCT: X670-GL, DISPLAY: X670-H814DGHJKL-T-GL-240224V556",
      "pushToken": "cM_FLbrFTvSGxIbV6IBusT:APA91bFw8faC6nA_QUWskKsVhwnWz-ioHTdNpHC5Kk3eXonehp8VFVntWcz_2BiyF-fcYnP4DGOIu27gJPEff8p1uDk3e4DiYpFGInC08eFMH9MJjnuZ-Jc",
      "deviceUniqueId": "56cb9030870fa44a",
      "deviceLanguage": "en",
      "deviceRegion": "US",
      "simRegion": "PK",
      "deviceGmtOffset": "+0500",
      "deviceRooted": 0,
      "deviceEmulator": 0,
      "appVersion": "6.5.5",
      "locale": "en"
    }
    headers = {
      'User-Agent': "okhttp/5.0.0-alpha.14",
      'Accept-Encoding': "gzip",
      'Content-Type': "application/json",
      'content-type': "application/json; charset=utf-8"
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers) as resp:
            return await resp.json()

async def store_token_and_show_card(msg_obj, login_result, creds):
    access_token = login_result.get("accessToken")
    user_data = login_result.get("user")
    if access_token:
        user_id = msg_obj.chat.id
        tokens = get_tokens(user_id)
        account_name = user_data.get("name") if user_data else creds.get("email")
        set_token(user_id, access_token, account_name)
        if user_data:
            text = format_user_with_nationality(user_data)
            await msg_obj.edit_text("Account signed in and saved!\n" + text, parse_mode="HTML")
        else:
            await msg_obj.edit_text("Account signed in and saved! (Email not verified, info not available yet.)")
    else:
        await msg_obj.edit_text("Token not received, failed to save account.")
