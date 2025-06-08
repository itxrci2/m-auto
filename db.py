from pymongo import MongoClient

# MongoDB connection
client = MongoClient("mongodb+srv://itxcriminal:qureshihashmI1@cluster0.jyqy9.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0")
db = client.meeff_tokens

def set_token(user_id, token, meeff_user_id, filters=None):
    update_data = {
        "user_id": user_id,
        "token": token,
        "name": meeff_user_id,
        "active": True  # New field for toggle
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
        {"_id": 0, "token": 1, "name": 1, "filters": 1}
    ))

def get_all_tokens(user_id):
    # Return all tokens, active and inactive (for manage UI)
    return list(db.tokens.find(
        {"user_id": user_id},
        {"_id": 0, "token": 1, "name": 1, "filters": 1, "active": 1}
    ))

def list_tokens():
    return list(db.tokens.find({"active": True}, {"_id": 0}))

def set_current_account(user_id, token):
    db.current_account.update_one({"user_id": user_id}, {"$set": {"token": token}}, upsert=True)

def get_current_account(user_id):
    record = db.current_account.find_one({"user_id": user_id})
    if not record:
        return None
    # Only return if the token is active
    token = record["token"]
    doc = db.tokens.find_one({"user_id": user_id, "token": token, "active": True})
    return token if doc else None

def delete_token(user_id, token):
    db.tokens.delete_one({"user_id": user_id, "token": token})

def set_user_filters(user_id, token, filters):
    db.tokens.update_one(
        {"user_id": user_id, "token": token},
        {"$set": {"filters": filters}},
        upsert=True
    )

def get_user_filters(user_id, token):
    record = db.tokens.find_one({"user_id": user_id, "token": token}, {"filters": 1})
    return record["filters"] if record and "filters" in record else None
