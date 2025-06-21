from pymongo import MongoClient

# MongoDB connection
client = MongoClient("mongodb+srv://itxcriminal:qureshihashmI1@cluster0.jyqy9.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0")
db = client.meeff_tokens

def set_token(user_id, token, account_name, email=None, filters=None):
    """
    Add or update a token for a user.
    If email is provided, overwrite any existing token for that email (per user).
    """
    query = {"user_id": user_id}
    if email:
        # Remove any existing token for the same user/email (to ensure only the latest per email)
        db.tokens.delete_many({"user_id": user_id, "email": email})
        query["email"] = email
    query["token"] = token

    update_data = {
        "user_id": user_id,
        "token": token,
        "name": account_name,
        "active": True,
        "email": email
    }
    if filters:
        update_data["filters"] = filters

    db.tokens.update_one(
        {"user_id": user_id, "token": token},
        {"$set": update_data},
        upsert=True
    )

def set_account_active(user_id, token, active: bool):
    db.tokens.update_one(
        {"user_id": user_id, "token": token},
        {"$set": {"active": active}}
    )

def get_tokens(user_id):
    # Only return active tokens
    return list(db.tokens.find(
        {"user_id": user_id, "active": True},
        {"_id": 0, "token": 1, "name": 1, "filters": 1, "active": 1, "email": 1}
    ))

def get_all_tokens(user_id):
    # Return all tokens, active and inactive (for manage UI)
    return list(db.tokens.find(
        {"user_id": user_id},
        {"_id": 0, "token": 1, "name": 1, "filters": 1, "active": 1, "email": 1}
    ))

def list_tokens():
    return list(db.tokens.find({"active": True}, {"_id": 0}))

def set_current_account(user_id, token):
    db.current_account.update_one({"user_id": user_id}, {"$set": {"token": token}}, upsert=True)

def get_current_account(user_id):
    record = db.current_account.find_one({"user_id": user_id})
    if not record:
        return None
    token = record["token"]
    doc = db.tokens.find_one({"user_id": user_id, "token": token, "active": True})
    return token if doc else None

def delete_token(user_id, token):
    db.tokens.delete_one({"user_id": user_id, "token": token})
    db.info_cards.delete_one({"user_id": user_id, "token": token})

def set_user_filters(user_id, token, filters):
    db.tokens.update_one(
        {"user_id": user_id, "token": token},
        {"$set": {"filters": filters}},
        upsert=True
    )

def get_user_filters(user_id, token):
    record = db.tokens.find_one({"user_id": user_id, "token": token}, {"filters": 1})
    return record["filters"] if record and "filters" in record else None

def add_to_blocklist(user_id, block_id):
    db.blocklist.update_one(
        {"user_id": user_id},
        {"$addToSet": {"blocklist": block_id}},
        upsert=True
    )

def get_user_blocklist(user_id):
    record = db.blocklist.find_one({"user_id": user_id})
    return set(record.get("blocklist", [])) if record else set()

def is_blocklist_active(user_id):
    record = db.blocklist.find_one({"user_id": user_id})
    return bool(record and record.get("blocklist"))

def transfer_user_data(from_user_id, to_user_id):
    """
    Transfer all tokens, filters, current account, info cards, and blocklist from one Telegram user to another.
    """
    # Transfer tokens
    tokens = list(db.tokens.find({'user_id': from_user_id}))
    for token in tokens:
        token_copy = token.copy()
        token_copy['user_id'] = to_user_id
        token_copy.pop('_id', None)
        db.tokens.update_one(
            {'user_id': to_user_id, 'token': token_copy['token']},
            {'$set': token_copy},
            upsert=True
        )
    # Transfer info cards
    info_cards = list(db.info_cards.find({'user_id': from_user_id}))
    for card in info_cards:
        card_copy = card.copy()
        card_copy['user_id'] = to_user_id
        card_copy.pop('_id', None)
        db.info_cards.update_one(
            {'user_id': to_user_id, 'token': card_copy['token']},
            {'$set': card_copy},
            upsert=True
        )
    # Transfer current account
    ca = db.current_account.find_one({'user_id': from_user_id})
    if ca:
        db.current_account.update_one(
            {'user_id': to_user_id},
            {'$set': {'token': ca['token']}},
            upsert=True
        )
    # Transfer blocklist
    bl = db.blocklist.find_one({'user_id': from_user_id})
    if bl and bl.get("blocklist"):
        db.blocklist.update_one(
            {'user_id': to_user_id},
            {'$set': {'blocklist': bl['blocklist']}},
            upsert=True
        )

# --- ACCOUNT INFO CARD LOGIC ---

def set_info_card(user_id, token, info_card, email=None):
    """
    Store or update the info card for a token (and email, if provided).
    Overwrites info card if same user_id+email or user_id+token exists.
    """
    query = {"user_id": user_id, "token": token}
    update_data = {
        "user_id": user_id,
        "token": token,
        "info_card": info_card
    }
    if email:
        update_data["email"] = email
        # Optionally update all info_cards for this email (most uses only update for token)
        db.info_cards.update_many({"user_id": user_id, "email": email}, {"$set": update_data})
    db.info_cards.update_one(query, {"$set": update_data}, upsert=True)

def get_info_card(user_id, token):
    record = db.info_cards.find_one({"user_id": user_id, "token": token})
    return record["info_card"] if record and "info_card" in record else None
