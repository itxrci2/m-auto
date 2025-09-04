from aiogram import types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_filter_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Gender", callback_data="filter_gender")],
        [InlineKeyboardButton(text="Age", callback_data="filter_age")],
        [InlineKeyboardButton(text="Nationality", callback_data="filter_nationality")],
        [InlineKeyboardButton(text="Back", callback_data="back_to_menu")]
    ])
    return keyboard

def get_gender_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="All Gender", callback_data="filter_gender_all")],
        [InlineKeyboardButton(text="Male", callback_data="filter_gender_male")],
        [InlineKeyboardButton(text="Female", callback_data="filter_gender_female")],
        [InlineKeyboardButton(text="Back", callback_data="filter_back")]
    ])
    return keyboard

def get_age_keyboard():
    # Ages 18–49 inclusive, split into rows of 8
    ages = list(range(18, 50))  # 18 to 49 inclusive
    max_per_row = 8
    rows = []
    for i in range(0, len(ages), max_per_row):
        row = [InlineKeyboardButton(text=str(age), callback_data=f"filter_age_{age}") for age in ages[i:i+max_per_row]]
        rows.append(row)
    rows.append([InlineKeyboardButton(text="Back", callback_data="filter_back")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=rows)
    return keyboard

def get_nationality_keyboard():
    countries = [
        ("RU", "🇷🇺"), ("UA", "🇺🇦"), ("BY", "🇧🇾"), ("IR", "🇮🇷"), ("PH", "🇵🇭"),
        ("PK", "🇵🇰"), ("US", "🇺🇸"), ("IN", "🇮🇳"), ("DE", "🇩🇪"), ("FR", "🇫🇷"),
        ("BR", "🇧🇷"), ("CN", "🇨🇳"), ("JP", "🇯🇵"), ("KR", "🇰🇷"), ("CA", "🇨🇦"),
        ("AU", "🇦🇺"), ("IT", "🇮🇹"), ("ES", "🇪🇸"), ("ZA", "🇿🇦"), ("TR", "🇹🇷")
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="All Countries", callback_data="filter_nationality_all")],
        *[[InlineKeyboardButton(text=f"{flag} {country}", callback_data=f"filter_nationality_{country}")] for country, flag in countries],
        [InlineKeyboardButton(text="Back", callback_data="filter_back")]
    ])
    return keyboard
