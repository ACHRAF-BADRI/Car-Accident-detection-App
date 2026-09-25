import os
from datetime import timedelta

import bcrypt
import jwt
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from server.db import now, users

SECRET = os.environ["JWT_SECRET_KEY"]
EXPIRE_HOURS = int(os.environ.get("JWT_EXPIRE_HOURS", "12"))
bearer = HTTPBearer(auto_error=False)


def hash_password(password):
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def check_password(password, password_hash):
    if len(password.encode()) > 72:  # bcrypt 5 raises on longer input; no stored password can be that long
        return False
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_token(user):
    payload = {"sub": str(user["_id"]), "role": user["role"], "exp": now() + timedelta(hours=EXPIRE_HOURS)}
    return jwt.encode(payload, SECRET, algorithm="HS256")


def public_user(user):
    return {"id": str(user["_id"]), "username": user["username"], "role": user["role"],
            "active": user.get("active", True),
            "full_name": user.get("full_name", ""), "email": user.get("email", ""),
            "created_at": user.get("created_at"), "last_login": user.get("last_login")}


def current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
    if credentials is None:
        raise HTTPException(401, "Not authenticated")
    try:
        payload = jwt.decode(credentials.credentials, SECRET, algorithms=["HS256"])
        user = users.find_one({"_id": ObjectId(payload["sub"])})
    except (jwt.PyJWTError, InvalidId, KeyError):
        raise HTTPException(401, "Invalid or expired token")
    if user is None:
        raise HTTPException(401, "User no longer exists")
    if not user.get("active", True):
        raise HTTPException(403, "account_suspended")  # also cuts sessions that were open before
    return user  # role is read from the database, so a demotion takes effect immediately


def require_admin(user=Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(403, "Admin only")
    return user
