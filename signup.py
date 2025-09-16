import aiohttp
import json
import itertools
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from db import set_token, get_tokens, set_info_card, get_info_card, set_user_filters, get_user_filters
from requests import format_user
from device_info import random_device_info

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

    card = (
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
    if "email" in user:
        card += f"\n<b>Email:</b> <code>{user['email']}</code>"
    if "password" in user:
        card += f"\n<b>Password:</b> <code>{user['password']}</code>"
    if "token" in user:
        card += f"\n<b>Token:</b> <code>{user['token']}</code>"
    return card

SIGNUP_MENU = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="Sign Up", callback_data="signup_go"),
        InlineKeyboardButton(text="Sign In", callback_data="signin_go"),
        InlineKeyboardButton(text="Mass Signup", callback_data="mass_signup_go"),
    ]
])
VERIFY_BUTTON = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Verify Email", callback_data="signup_verify")]
])
BACK_TO_SIGNUP = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Back", callback_data="signup_menu")]
])
DONE_PHOTOS = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Done", callback_data="signup_photos_done")],
    [InlineKeyboardButton(text="Back", callback_data="signup_menu")]
])
RESEND_EMAIL_BUTTON = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Resend Verification Email", callback_data="resend_email_verification")],
    [InlineKeyboardButton(text="Back", callback_data="signup_menu")]
])

user_signup_states = {}

DEFAULT_PHOTOS = (
    "https://meeffus.s3.amazonaws.com/profile/2025/06/16/20250616052423006_profile-1.0-bd262b27-1916-4bd3-9f1d-0e7fdba35268.jpg|"
    "https://meeffus.s3.amazonaws.com/profile/2025/06/16/20250616052438006_profile-1.0-349bf38c-4555-40cc-a322-e61afe15aa35.jpg"
)

DEFAULT_FILTER = {
    "filterGenderType": 5,
    "filterBirthYearFrom": 1995,
    "filterBirthYearTo": 2007,
    "filterDistance": 510,
    "filterLanguageCodes": "",
    "filterNationalityBlock": 0,
    "filterNationalityCode": "",
    "locale": "en"
}

def generate_gmail_dot_variants(email):
    # johnsmith@gmail.com -> all possible dot variants (Gmail ignores dots)
    # returns a set of variants
    if '@' not in email:
        return []
    local, domain = email.lower().split('@', 1)
    if domain != "gmail.com":
        return [email]
    positions = list(range(1, len(local)))
    combos = []
    for i in range(0, len(positions)+1):
        for dots in itertools.combinations(positions, i):
            s = list(local)
            for offset, pos in enumerate(dots):
                s.insert(pos + offset, '.')
            combos.append("".join(s) + '@gmail.com')
    return list(set(combos))

async def check_email_exists(email):
    url = "https://api.meeff.com/user/checkEmail/v1"
    payload = {
        "email": email,
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
            status = resp.status
            try:
                resp_json = await resp.json()
            except Exception:
                resp_json = {}
            if status == 406 or resp_json.get("errorCode") == "AlreadyInUse":
                return False, resp_json.get("errorMessage", "This email address is already in use.")
            return True, ""

async def signup_command(message: Message):
    user_signup_states[message.chat.id] = {"stage": "menu"}
    await message.answer("Choose an option:", reply_markup=SIGNUP_MENU)

async def signup_callback_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    state = user_signup_states.get(user_id, {"stage": "menu"})
    if callback.data == "signup_go":
        state["stage"] = "ask_email"
        state["mass_signup"] = False
        user_signup_states[user_id] = state
        await callback.message.edit_text("Enter your email for registration:", reply_markup=BACK_TO_SIGNUP)
        await callback.answer()
        return True
    if callback.data == "signup_menu":
        state["stage"] = "menu"
        state.pop("mass_signup", None)
        await callback.message.edit_text("Choose an option:", reply_markup=SIGNUP_MENU)
        await callback.answer()
        return True
    if callback.data == "signin_go":
        state["stage"] = "signin_email"
        state["mass_signup"] = False
        user_signup_states[user_id] = state
        await callback.message.edit_text("Enter your email to sign in:", reply_markup=BACK_TO_SIGNUP)
        await callback.answer()
        return True
    if callback.data == "mass_signup_go":
        state["stage"] = "ask_mass_count"
        state["mass_signup"] = True
        user_signup_states[user_id] = state
        await callback.message.edit_text("How many accounts do you want to create? (e.g., 10)", reply_markup=BACK_TO_SIGNUP)
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
        elif login_result.get("errorCode") in ("NotVerified", "EmailVerificationRequired"):
            await callback.message.edit_text(
                "Email not verified! Please check your inbox and click the link, then try Verify again.\n"
                "Or click the button below to resend the verification email.",
                reply_markup=RESEND_EMAIL_BUTTON
            )
        else:
            await callback.message.edit_text(f"Login failed: {login_result.get('errorMessage', 'Unknown error')}", reply_markup=SIGNUP_MENU)
        return True
    if callback.data == "resend_email_verification":
        creds = state.get("creds")
        if not creds or not creds.get("email") or not creds.get("password"):
            await callback.answer("No signup info. Please sign up again.", show_alert=True)
            return True
        login_result = await try_signin(creds['email'], creds['password'])
        access_token = login_result.get("accessToken")
        if not access_token:
            await callback.answer("Token not available. Try signing up again.", show_alert=True)
            return True
        resend_result = await resend_verification_email(access_token)
        if (resend_result.get("errorCode") == "" or resend_result.get("errorCode") is None):
            await callback.message.edit_text(
                "Verification email resent! Please check your inbox and verify your email.",
                reply_markup=VERIFY_BUTTON
            )
        else:
            await callback.message.edit_text(
                f"Failed to resend verification email: {resend_result.get('errorMessage', 'Unknown error')}",
                reply_markup=RESEND_EMAIL_BUTTON
            )
        await callback.answer()
        return True
    if callback.data == "signup_photos_done":
        if state.get("mass_signup"):
            state["stage"] = "mass_ask_filters"
            await callback.message.edit_text("Now configure filters for these accounts.\nSend filters as JSON, or type 'default' to use the default filter:", reply_markup=BACK_TO_SIGNUP)
        else:
            state["stage"] = "signup_submit"
            processing_msg = await callback.message.edit_text("Registering your account, please wait...", reply_markup=None)
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
    return False

async def signup_message_handler(message: Message):
    user_id = message.from_user.id
    if user_id not in user_signup_states:
        return False
    state = user_signup_states[user_id]
    if message.text and message.text.startswith("/"):
        return False

    # --- MASS SIGNUP FLOW ---
    if state.get("mass_signup"):
        # Step 1: How many accounts
        if state.get("stage") == "ask_mass_count":
            try:
                count = int(message.text.strip())
                if not (2 <= count <= 50):
                    await message.answer("Please enter a number between 2 and 50.")
                    return True
                state["mass_count"] = count
                state["stage"] = "ask_mass_email"
                await message.answer("Enter your base Gmail address (e.g. john.doe@gmail.com). Only Gmail is supported.", reply_markup=BACK_TO_SIGNUP)
            except Exception:
                await message.answer("Invalid number. Please try again.")
            return True
        # Step 2: Base Email
        if state.get("stage") == "ask_mass_email":
            email = message.text.strip().lower()
            if not (email.endswith('@gmail.com') and '@' in email):
                await message.answer("Only Gmail addresses are supported. Try again.")
                return True
            state["mass_email"] = email
            state["stage"] = "finding_mass_emails"
            await message.answer("Checking available emails, please wait...", reply_markup=None)

            emails = generate_gmail_dot_variants(email)
            available_emails = []
            for eml in emails:
                ok, _ = await check_email_exists(eml)
                if ok:
                    available_emails.append(eml)
                    if len(available_emails) >= state["mass_count"]:
                        break
            if len(available_emails) < state["mass_count"]:
                await message.answer(
                    f"Only found {len(available_emails)} available emails. Please try a different base address or lower the count."
                )
                state["stage"] = "ask_mass_email"
                return True
            state["mass_emails"] = available_emails
            state["mass_current"] = 0
            await message.answer(
                f"Found {len(available_emails)} available emails!\nNow enter a password for all accounts:",
                reply_markup=BACK_TO_SIGNUP
            )
            state["stage"] = "mass_ask_password"
            return True
        if state.get("stage") == "mass_ask_password":
            state["password"] = message.text.strip()
            state["stage"] = "mass_ask_name"
            await message.answer("Enter a display name for all accounts:", reply_markup=BACK_TO_SIGNUP)
            return True
        if state.get("stage") == "mass_ask_name":
            state["name"] = message.text.strip()
            state["stage"] = "mass_ask_gender"
            await message.answer("Enter gender for all accounts (M/F):", reply_markup=BACK_TO_SIGNUP)
            return True
        if state.get("stage") == "mass_ask_gender":
            gender = message.text.strip().upper()
            if gender not in ("M", "F"):
                await message.answer("Please enter M or F for gender:")
                return True
            state["gender"] = gender
            state["stage"] = "mass_ask_desc"
            await message.answer("Enter a profile description for all accounts:", reply_markup=BACK_TO_SIGNUP)
            return True
        if state.get("stage") == "mass_ask_desc":
            state["desc"] = message.text.strip()
            state["photos"] = []
            state["stage"] = "mass_ask_photos"
            await message.answer(
                "Now send up to 6 profile pictures (shared by all accounts). Send each as a photo. When done, click 'Done' or send /done.",
                reply_markup=DONE_PHOTOS
            )
            return True
        if state.get("stage") == "mass_ask_photos":
            if message.content_type == "photo":
                if len(state["photos"]) >= 6:
                    await message.answer("Already got 6 photos. Click Done or /done.")
                    return True
                photo = message.photo[-1]
                file = await message.bot.get_file(photo.file_id)
                file_url = f"https://api.telegram.org/file/bot{message.bot.token}/{file.file_path}"
                async with aiohttp.ClientSession() as session:
                    async with session.get(file_url) as resp:
                        img_bytes = await resp.read()
                img_url = await meeff_upload_image(img_bytes)
                if img_url:
                    state["photos"].append(img_url)
                    await message.answer(f"Photo uploaded ({len(state['photos'])}/6).")
                else:
                    await message.answer("Failed to upload photo. Try again.")
                if len(state["photos"]) == 6:
                    await message.answer("You've uploaded 6 photos. Click Done or /done.", reply_markup=DONE_PHOTOS)
                return True
            elif message.text and message.text.strip().lower() == "/done":
                state["stage"] = "mass_ask_filters"
                await message.answer(
                    "Now configure filters for these accounts.\nSend filters as JSON, or type 'default' to use the default filter:",
                    reply_markup=BACK_TO_SIGNUP
                )
                return True
            else:
                await message.answer("Please send a photo or click Done.")
                return True
        if state.get("stage") == "mass_ask_filters":
            if message.text.strip().lower() == "default":
                state["filters"] = DEFAULT_FILTER
            else:
                try:
                    state["filters"] = json.loads(message.text)
                except Exception:
                    await message.answer("Invalid JSON. Try again or send 'default'.")
                    return True
            state["stage"] = "mass_signup_submit"
            await message.answer("Starting mass signup. Please wait, accounts are being created...")
            results = []
            for idx, eml in enumerate(state["mass_emails"]):
                user_state = {
                    "email": eml,
                    "password": state["password"],
                    "name": state["name"],
                    "gender": state["gender"],
                    "desc": state["desc"],
                    "photos": state["photos"],
                }
                signup_result = await try_signup(user_state)
                if signup_result.get("user", {}).get("_id"):
                    access_token = None
                    login_result = await try_signin(user_state["email"], user_state["password"])
                    if login_result.get("accessToken"):
                        access_token = login_result["accessToken"]
                        set_token(user_id, access_token, user_state["name"], user_state["email"])
                        set_user_filters(user_id, access_token, state["filters"])
                        results.append((user_state["email"], "OK"))
                    else:
                        results.append((user_state["email"], "Signup OK, but signin failed"))
                else:
                    err = signup_result.get("errorMessage", "Registration failed.")
                    results.append((user_state["email"], f"Signup failed: {err}"))
            report = "\n".join([f"{eml}: {res}" for eml, res in results])
            await message.answer(
                f"Mass signup finished for {len(state['mass_emails'])} accounts!\n\n{report}",
                reply_markup=SIGNUP_MENU
            )
            state.clear()
            return True

    # --- SINGLE SIGNUP FLOW ---
    if state.get("stage") == "ask_email":
        email = message.text.strip()
        ok, msg = await check_email_exists(email)
        if not ok:
            await message.answer(f"{msg}", reply_markup=BACK_TO_SIGNUP)
            return True
        state["stage"] = "ask_password"
        state["email"] = email
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
        state["stage"] = "ask_photos"
        state["desc"] = message.text.strip()
        state["photos"] = []
        await message.answer(
            "Now send up to 6 profile pictures one by one. Send each as a photo (not file). "
            "When done, click 'Done' or send /done.", reply_markup=DONE_PHOTOS)
        return True
    if state.get("stage") == "ask_photos":
        if message.content_type == "photo":
            if len(state["photos"]) >= 6:
                await message.answer("You have already sent 6 photos. Click Done to finish or /done.")
                return True
            photo = message.photo[-1]
            file = await message.bot.get_file(photo.file_id)
            file_url = f"https://api.telegram.org/file/bot{message.bot.token}/{file.file_path}"
            async with aiohttp.ClientSession() as session:
                async with session.get(file_url) as resp:
                    img_bytes = await resp.read()
            img_url = await meeff_upload_image(img_bytes)
            if img_url:
                state["photos"].append(img_url)
                await message.answer(f"Photo uploaded ({len(state['photos'])}/6).")
            else:
                await message.answer("Failed to upload photo. Try again.")
            if len(state["photos"]) == 6:
                await message.answer("You've uploaded 6 photos. Click Done to finish or /done.", reply_markup=DONE_PHOTOS)
            return True
        elif message.text and message.text.strip().lower() == "/done":
            state["stage"] = "signup_submit"
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
        else:
            await message.answer("Please send a photo or click Done to finish.")
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
            # Always save creds in state, even if not verified!
            state["creds"] = {"email": email, "password": password}
            creds = state["creds"]
            await store_token_and_show_card(processing_msg, login_result, creds)
            state["stage"] = "menu"
        else:
            err = login_result.get("errorMessage", "Sign in failed.")
            await processing_msg.edit_text(f"Sign in failed: {err}", reply_markup=SIGNUP_MENU)
            state["stage"] = "menu"
        return True

    return False

async def meeff_upload_image(img_bytes):
    url = "https://api.meeff.com/api/upload/v1"
    payload = {
        "category": "profile",
        "count": 1,
        "locale": "en"
    }
    headers = {
        'User-Agent': "okhttp/5.0.0-alpha.14",
        'Accept-Encoding': "gzip",
        'Content-Type': "application/json; charset=utf-8"
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=json.dumps(payload), headers=headers) as resp:
                resp_json = await resp.json()
                upload_info = resp_json.get("data", {}).get("uploadImageInfoList", [{}])[0]
                data = resp_json.get("data", {})
                if not upload_info or not data:
                    print("Meeff upload: missing upload_info or data.")
                    return None
                upload_url = data.get("Host")
                fields = {
                    "key": upload_info.get("key"),
                    "acl": data.get("acl"),
                    "Content-Type": data.get("Content-Type"),
                    "x-amz-meta-uuid": data.get("x-amz-meta-uuid"),
                    "X-Amz-Algorithm": upload_info.get("X-Amz-Algorithm") or data.get("X-Amz-Algorithm"),
                    "X-Amz-Credential": upload_info.get("X-Amz-Credential") or data.get("X-Amz-Credential"),
                    "X-Amz-Date": upload_info.get("X-Amz-Date") or data.get("X-Amz-Date"),
                    "Policy": upload_info.get("Policy") or data.get("Policy"),
                    "X-Amz-Signature": upload_info.get("X-Amz-Signature") or data.get("X-Amz-Signature"),
                }
                for k, v in fields.items():
                    if v is None:
                        print(f"Meeff S3 upload missing field: {k}")
                        return None
                form = aiohttp.FormData()
                for k, v in fields.items():
                    form.add_field(k, v)
                form.add_field('file', img_bytes, filename='photo.jpg', content_type='image/jpeg')
                async with session.post(upload_url, data=form) as s3resp:
                    if s3resp.status in (200, 204):
                        return upload_info.get("uploadImagePath")
                    else:
                        print(f"S3 upload failed: {s3resp.status} {await s3resp.text()}")
        return None
    except Exception as ex:
        print(f"Photo upload failed: {ex}")
        return None

async def try_signup(state):
    device_info = random_device_info()
    if state.get("photos"):
        photos_str = "|".join(state["photos"])
    else:
        photos_str = DEFAULT_PHOTOS
    url = "https://api.meeff.com/user/register/email/v4"
    payload = {
        "providerId": state["email"],
        "providerToken": state["password"],
        **device_info,
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
        "photos": photos_str,
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
    device_info = random_device_info()
    url = "https://api.meeff.com/user/login/v4"
    payload = {
        "provider": "email",
        "providerId": email,
        "providerToken": password,
        **device_info,
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

async def resend_verification_email(access_token):
    url = "https://api.meeff.com/user/resendEmailVerification/v1"
    payload = {"locale": "en"}
    headers = {
        'User-Agent': "okhttp/5.1.0",
        'Accept-Encoding': "gzip",
        'Content-Type': "application/json",
        'meeff-access-token': access_token,
        'content-type': "application/json; charset=utf-8"
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers) as resp:
            try:
                return await resp.json()
            except Exception:
                return {"errorCode": "unknown", "errorMessage": "No response."}

async def store_token_and_show_card(msg_obj, login_result, creds):
    access_token = login_result.get("accessToken")
    user_data = login_result.get("user")
    email = creds.get("email")
    if access_token:
        user_id = msg_obj.chat.id
        tokens = get_tokens(user_id)
        account_name = user_data.get("name") if user_data else creds.get("email")
        set_token(user_id, access_token, account_name, email)
        # --- Set default filter for new accounts ---
        if not get_user_filters(user_id, access_token):
            set_user_filters(user_id, access_token, DEFAULT_FILTER)
        if user_data:
            user_data["email"] = creds.get("email")
            user_data["password"] = creds.get("password")
            user_data["token"] = access_token
            text = format_user_with_nationality(user_data)
            set_info_card(user_id, access_token, text, email)
            await msg_obj.edit_text("Account signed in and saved!\n" + text, parse_mode="HTML")
        else:
            # Show resend button if not verified (no user info)
            await msg_obj.edit_text(
                "Account signed in and saved! (Email not verified, info not available yet.)\n"
                "Please verify your email, or click below to resend the verification email.",
                reply_markup=RESEND_EMAIL_BUTTON
            )
    else:
        await msg_obj.edit_text("Token not received, failed to save account.")
