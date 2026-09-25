"""Accident Detection API: accounts (JWT), images and videos in MongoDB GridFS, admin dashboard.

Run:  python -m uvicorn server.main:app --host 127.0.0.1 --port 8000
"""
import hashlib
import io
import json
import os
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from PIL import Image
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from server.auth import (check_password, create_token, current_user, hash_password, public_user,
                         require_admin)
from server.db import db, downloads, init_db, media, media_files, now, users
from server.notify import download_email, send_email

app = FastAPI(title="Accident Detection API")
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD = 6
KINDS = {"image", "video"}


@app.on_event("startup")
def startup():
    init_db(hash_password)


# ---------------------------------------------------------------- Download notifications (website)

EMAIL_EVERY_VISITOR_MINUTES = 10  # the same visitor clicking again within 10 min is counted, not emailed
MAX_EMAILS_PER_HOUR = 20          # protects the mailbox (and the Resend quota) against spam clicks


def describe_agent(ua):
    os_name = next((name for key, name in (("Windows NT 10", "Windows 10/11"), ("Windows NT 6.3", "Windows 8.1"),
                                          ("Windows", "Windows"), ("Mac OS X", "macOS"), ("Android", "Android"),
                                          ("iPhone", "iOS"), ("iPad", "iPadOS"), ("Linux", "Linux")) if key in ua), "?")
    browser = next((name for key, name in (("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"),
                                          ("Chrome/", "Chrome"), ("Safari/", "Safari")) if key in ua), "?")
    return f"{os_name} · {browser}"


def local_time():
    try:
        return datetime.now(ZoneInfo(os.environ.get("NOTIFY_TIMEZONE", "UTC"))).strftime("%d/%m/%Y %H:%M:%S %Z")
    except ZoneInfoNotFoundError:
        return now().strftime("%d/%m/%Y %H:%M:%S UTC")


@app.post("/track/download")
async def track_download(request: Request):
    """Called by the website (navigator.sendBeacon) when the download button is clicked.
    Counts every click and emails the owner, without storing the visitor's IP address."""
    try:
        data = json.loads((await request.body())[:2000] or b"{}")
        data = data if isinstance(data, dict) else {}
    except ValueError:
        data = {}
    ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "")).split(",")[0].strip()
    visitor = hashlib.sha256((os.environ.get("JWT_SECRET_KEY", "") + ip).encode()).hexdigest()[:16]  # anonymous id
    ua = request.headers.get("user-agent", "")[:300]
    since_visitor = now() - timedelta(minutes=EMAIL_EVERY_VISITOR_MINUTES)
    should_email = (downloads.count_documents({"visitor": visitor, "at": {"$gte": since_visitor}}) == 0
                    and downloads.count_documents({"emailed": True, "at": {"$gte": now() - timedelta(hours=1)}}) < MAX_EMAILS_PER_HOUR)
    doc = {"at": now(), "visitor": visitor, "user_agent": ua, "version": str(data.get("version", ""))[:40],
           "page_language": str(data.get("lang", ""))[:5], "referrer": request.headers.get("referer", "")[:200],
           "emailed": should_email}
    downloads.insert_one(doc)
    if should_email:
        total = downloads.count_documents({})
        info = {"Date": local_time(), "Version": doc["version"] or "—", "Système · navigateur": describe_agent(ua),
                "Langue du site": doc["page_language"].upper() or "—",
                "Langue du navigateur": request.headers.get("accept-language", "").split(",")[0]}
        sent = await run_in_threadpool(send_email, f"AccidentAI téléchargé ({total})", download_email(info, total))
        if not sent:  # keep "emailed" true only for emails that really left (it feeds the hourly cap)
            downloads.update_one({"_id": doc["_id"]}, {"$set": {"emailed": False}})
    return Response(status_code=204)


@app.get("/health")
def health():
    db.command("ping")
    return {"status": "ok"}


# ---------------------------------------------------------------- Auth

class Credentials(BaseModel):
    username: str
    password: str


def new_user(username, password, role="user", logged_in=False):
    if not USERNAME_RE.match(username):
        raise HTTPException(400, "invalid_username")
    if len(password) < MIN_PASSWORD:
        raise HTTPException(400, "weak_password")
    if users.find_one({"username_lower": username.lower()}):
        raise HTTPException(409, "username_taken")
    user = {"username": username, "username_lower": username.lower(),
            "password_hash": hash_password(password), "role": role, "active": True,
            "created_at": now(), "last_login": now() if logged_in else None}
    user["_id"] = users.insert_one(user).inserted_id
    return user


@app.post("/auth/register")
def register(body: Credentials):
    user = new_user(body.username, body.password, logged_in=True)
    return {"token": create_token(user), "user": public_user(user)}


@app.post("/auth/login")
def login(body: Credentials):
    user = users.find_one({"username_lower": body.username.lower()})
    if user is None or not check_password(body.password, user["password_hash"]):
        raise HTTPException(401, "invalid_credentials")
    if not user.get("active", True):
        raise HTTPException(403, "account_suspended")
    users.update_one({"_id": user["_id"]}, {"$set": {"last_login": now()}})
    return {"token": create_token(user), "user": public_user(user)}


@app.get("/auth/me")
def me(user=Depends(current_user)):
    return public_user(user)


class ProfileUpdate(BaseModel):
    full_name: str | None = None
    email: str | None = None


def profile_changes(body):
    """Validated $set for the editable profile fields (the username is the login and folder name: fixed)."""
    changes = {}
    if body.full_name is not None:
        name = body.full_name.strip()
        if len(name) > 80:
            raise HTTPException(400, "invalid_full_name")
        changes["full_name"] = name
    if body.email is not None:
        email = body.email.strip().lower()
        if email and not EMAIL_RE.match(email):
            raise HTTPException(400, "invalid_email")
        changes["email"] = email
    return changes


@app.patch("/auth/me")
def update_me(body: ProfileUpdate, user=Depends(current_user)):
    changes = profile_changes(body)
    if changes:
        users.update_one({"_id": user["_id"]}, {"$set": changes})
    return public_user(users.find_one({"_id": user["_id"]}))


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


@app.post("/auth/me/password")
def change_password(body: PasswordChange, user=Depends(current_user)):
    if not check_password(body.current_password, user["password_hash"]):
        raise HTTPException(400, "wrong_current_password")
    if len(body.new_password) < MIN_PASSWORD:
        raise HTTPException(400, "weak_password")
    users.update_one({"_id": user["_id"]}, {"$set": {"password_hash": hash_password(body.new_password)}})
    return {"changed": True}


@app.post("/auth/refresh")
def refresh(user=Depends(current_user)):
    """A still-valid token gets a fresh one, so long webcam sessions are not logged out."""
    return {"token": create_token(user), "user": public_user(user)}


# ---------------------------------------------------------------- Media (GridFS)

def media_doc(f):
    meta = f.get("metadata", {})
    return {"id": str(f["_id"]), "filename": f["filename"], "kind": meta.get("kind"), "size": f["length"],
            "owner_id": meta.get("owner_id"), "owner": meta.get("owner"),
            "captured_at": meta.get("captured_at"), "uploaded_at": f["uploadDate"],
            "probability": meta.get("probability"), "duration": meta.get("duration")}


def get_media_for(media_id, user):
    try:
        f = media_files.find_one({"_id": ObjectId(media_id)})
    except InvalidId:
        f = None
    if f is None:
        raise HTTPException(404, "not_found")
    if user["role"] != "admin" and f["metadata"]["owner_id"] != str(user["_id"]):
        raise HTTPException(403, "forbidden")
    return f


@app.post("/media")
async def upload(request: Request, kind: str, filename: str, captured_at: datetime | None = None,
                 probability: float | None = None, duration: float | None = None, user=Depends(current_user)):
    """The body is the raw file, streamed straight into GridFS (videos can be hundreds of MB)."""
    if kind not in KINDS:
        raise HTTPException(400, "invalid_kind")
    metadata = {"kind": kind, "owner_id": str(user["_id"]), "owner": user["username"],
                "captured_at": captured_at or now(), "probability": probability, "duration": duration,
                "content_type": request.headers.get("content-type", "application/octet-stream")}
    stream = media.open_upload_stream(filename, metadata=metadata)
    try:
        async for chunk in request.stream():
            await run_in_threadpool(stream.write, chunk)
        await run_in_threadpool(stream.close)
    except Exception:
        await run_in_threadpool(stream.abort)
        raise
    return media_doc(media_files.find_one({"_id": stream._id}))


@app.get("/media")
def list_media(kind: str | None = None, owner_id: str | None = None, user=Depends(current_user)):
    query = {}
    if user["role"] == "admin":
        if owner_id:
            query["metadata.owner_id"] = owner_id
    else:
        query["metadata.owner_id"] = str(user["_id"])  # a user only ever sees their own files
    if kind:
        query["metadata.kind"] = kind
    return [media_doc(f) for f in media_files.find(query).sort("metadata.captured_at", -1)]


@app.get("/media/{media_id}/file")
def download(media_id: str, user=Depends(current_user)):
    f = get_media_for(media_id, user)
    grid_out = media.open_download_stream(f["_id"])

    def chunks():
        while chunk := grid_out.readchunk():
            yield chunk

    return StreamingResponse(chunks(), media_type=f["metadata"].get("content_type", "application/octet-stream"),
                             headers={"Content-Length": str(f["length"]),
                                      "Content-Disposition": f'attachment; filename="{f["filename"]}"'})


@app.get("/media/{media_id}/thumb")
def thumbnail(media_id: str, user=Depends(current_user)):
    f = get_media_for(media_id, user)
    if f["metadata"]["kind"] != "image":
        raise HTTPException(400, "not_an_image")
    img = Image.open(io.BytesIO(media.open_download_stream(f["_id"]).read())).convert("RGB")
    img.thumbnail((320, 200))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=80)
    return Response(out.getvalue(), media_type="image/jpeg")


@app.delete("/media")
def delete_many(kind: str | None = None, owner_id: str | None = None, filenames: str | None = None,
                user=Depends(current_user)):
    """Delete several files at once: all of a kind, or only the given comma-separated file names.
    A user can only target their own files; an admin can target anyone's with owner_id."""
    query = {"metadata.owner_id": owner_id if user["role"] == "admin" and owner_id else str(user["_id"])}
    if kind:
        query["metadata.kind"] = kind
    if filenames is not None:
        query["filename"] = {"$in": [name for name in filenames.split(",") if name]}
    files = list(media_files.find(query, {"_id": 1}))
    for f in files:
        media.delete(f["_id"])
    return {"deleted": len(files)}


@app.delete("/media/{media_id}")
def delete_media(media_id: str, user=Depends(current_user)):
    f = get_media_for(media_id, user)
    media.delete(f["_id"])
    return {"deleted": media_id}


# ---------------------------------------------------------------- Admin

def usage_by_owner():
    rows = media_files.aggregate([{"$group": {
        "_id": "$metadata.owner_id",
        "images": {"$sum": {"$cond": [{"$eq": ["$metadata.kind", "image"]}, 1, 0]}},
        "videos": {"$sum": {"$cond": [{"$eq": ["$metadata.kind", "video"]}, 1, 0]}},
        "bytes": {"$sum": "$length"},
        "last_upload": {"$max": "$uploadDate"},
    }}])
    return {row["_id"]: row for row in rows}


@app.get("/admin/users")
def admin_users(_=Depends(require_admin)):
    usage = usage_by_owner()
    result = []
    for user in users.find().sort("created_at", 1):
        u = usage.get(str(user["_id"]), {})
        result.append({**public_user(user), "images": u.get("images", 0), "videos": u.get("videos", 0),
                       "bytes": u.get("bytes", 0), "last_upload": u.get("last_upload")})
    return result


class NewUser(BaseModel):
    username: str
    password: str
    role: str = "user"


@app.post("/admin/users")
def create_user(body: NewUser, _=Depends(require_admin)):
    if body.role not in ("admin", "user"):
        raise HTTPException(400, "invalid_role")
    return public_user(new_user(body.username, body.password, body.role))


def find_user(user_id):
    try:
        target = users.find_one({"_id": ObjectId(user_id)})
    except InvalidId:
        target = None
    if target is None:
        raise HTTPException(404, "not_found")
    return target


def is_last_active_admin(target):
    return (target["role"] == "admin" and target.get("active", True)
            and users.count_documents({"role": "admin", "active": {"$ne": False}}) == 1)


class AdminProfileUpdate(ProfileUpdate):
    password: str | None = None  # set a new password without knowing the old one (reset)


@app.patch("/admin/users/{user_id}/profile")
def admin_update_profile(user_id: str, body: AdminProfileUpdate, _=Depends(require_admin)):
    target = find_user(user_id)
    changes = profile_changes(body)
    if body.password:
        if len(body.password) < MIN_PASSWORD:
            raise HTTPException(400, "weak_password")
        changes["password_hash"] = hash_password(body.password)
    if changes:
        users.update_one({"_id": target["_id"]}, {"$set": changes})
    return public_user(users.find_one({"_id": target["_id"]}))


class StatusChange(BaseModel):
    active: bool


@app.patch("/admin/users/{user_id}/status")
def change_status(user_id: str, body: StatusChange, admin=Depends(require_admin)):
    target = find_user(user_id)
    if not body.active:
        if target["_id"] == admin["_id"]:
            raise HTTPException(400, "cannot_suspend_self")
        if is_last_active_admin(target):
            raise HTTPException(400, "last_admin")
    users.update_one({"_id": target["_id"]}, {"$set": {"active": body.active}})
    return public_user(users.find_one({"_id": target["_id"]}))


@app.delete("/admin/users/{user_id}")
def delete_user(user_id: str, admin=Depends(require_admin)):
    """Removes the account and every image / video it uploaded."""
    target = find_user(user_id)
    if target["_id"] == admin["_id"]:
        raise HTTPException(400, "cannot_delete_self")
    if is_last_active_admin(target):
        raise HTTPException(400, "last_admin")
    files = list(media_files.find({"metadata.owner_id": str(target["_id"])}, {"_id": 1}))
    for f in files:
        media.delete(f["_id"])
    users.delete_one({"_id": target["_id"]})
    return {"deleted": user_id, "media_deleted": len(files)}


class RoleChange(BaseModel):
    role: str


@app.patch("/admin/users/{user_id}")
def change_role(user_id: str, body: RoleChange, admin=Depends(require_admin)):
    if body.role not in ("admin", "user"):
        raise HTTPException(400, "invalid_role")
    try:
        target = users.find_one({"_id": ObjectId(user_id)})
    except InvalidId:
        target = None
    if target is None:
        raise HTTPException(404, "not_found")
    if body.role == "user" and is_last_active_admin(target):
        raise HTTPException(400, "last_admin")
    users.update_one({"_id": target["_id"]}, {"$set": {"role": body.role}})
    return public_user(users.find_one({"_id": target["_id"]}))


@app.get("/admin/stats")
def admin_stats(days: int = 14, _=Depends(require_admin)):
    since = (now() - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    per_day = {row["_id"]: row for row in media_files.aggregate([
        {"$match": {"metadata.captured_at": {"$gte": since}}},
        {"$group": {"_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$metadata.captured_at"}},
                    "images": {"$sum": {"$cond": [{"$eq": ["$metadata.kind", "image"]}, 1, 0]}},
                    "videos": {"$sum": {"$cond": [{"$eq": ["$metadata.kind", "video"]}, 1, 0]}}}},
    ])}
    timeline = []
    for i in range(days):
        day = (since + timedelta(days=i)).strftime("%Y-%m-%d")
        row = per_day.get(day, {})
        timeline.append({"day": day, "images": row.get("images", 0), "videos": row.get("videos", 0)})

    usage = usage_by_owner()
    names = {str(u["_id"]): u["username"] for u in users.find({}, {"username": 1})}
    top = sorted(usage.values(), key=lambda r: r["images"], reverse=True)[:5]
    db_stats = db.command("dbStats")
    return {
        "users": users.count_documents({}),
        "admins": users.count_documents({"role": "admin"}),
        "images": sum(r["images"] for r in usage.values()),
        "videos": sum(r["videos"] for r in usage.values()),
        "media_bytes": sum(r["bytes"] for r in usage.values()),
        "db_storage_bytes": db_stats.get("storageSize", 0) + db_stats.get("indexSize", 0),
        "timeline": timeline,
        "top_users": [{"username": names.get(r["_id"], "?"), "images": r["images"], "videos": r["videos"]} for r in top],
    }
