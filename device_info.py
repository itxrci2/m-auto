import random

OS_VERSIONS = ["iOS 17.5.1", "iOS 16.7.2", "iOS 15.4.1"]
PLATFORMS = ["ios", "android"]
DEVICE_MODELS = [
    "iPhone15,3", "iPhone14,2", "iPhone13,1", "SM-G998B", "Pixel 7 Pro"
]
DEVICE_NAMES = [
    "iPhone 15 Pro Max", "iPhone 14 Pro", "Galaxy S21 Ultra", "Pixel 7 Pro"
]
PRODUCTS = [
    "iPhone15ProMax", "iPhone14Pro", "SM-G998B", "Pixel7Pro"
]
DISPLAYS = [
    "Super Retina XDR OLED", "AMOLED", "OLED", "LTPO OLED"
]
BRANDS = ["Apple", "Samsung", "Google"]
REGIONS = ["US", "KR", "RU", "BR", "IN", "UK", "CN"]
GMT_OFFSETS = ["-0700", "+0900", "+0300", "+0530", "+0000", "+0800"]

def random_hex(length=16):
    return "".join(random.choices("0123456789abcdef", k=length))

def random_device_info():
    brand = random.choice(BRANDS)
    model = random.choice(DEVICE_MODELS)
    device_name = random.choice(DEVICE_NAMES)
    product = random.choice(PRODUCTS)
    display = random.choice(DISPLAYS)
    os = random.choice(OS_VERSIONS)
    platform = random.choice(PLATFORMS)
    region = random.choice(REGIONS)
    gmt_offset = random.choice(GMT_OFFSETS)
    device_unique_id = random_hex(16)
    push_token = f"APA91b{random_hex(38)}"
    return {
        "os": os,
        "platform": platform,
        "device": f"BRAND: {brand}, MODEL: {model}, DEVICE: {device_name}, PRODUCT: {product}, DISPLAY: {display}",
        "pushToken": push_token,
        "deviceUniqueId": device_unique_id,
        "deviceLanguage": "en",
        "deviceRegion": region,
        "simRegion": region,
        "deviceGmtOffset": gmt_offset,
        "deviceRooted": 0,
        "deviceEmulator": 0,
        "appVersion": "6.5.5",
    }
