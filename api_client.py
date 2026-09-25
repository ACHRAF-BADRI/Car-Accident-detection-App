"""Talks to the Accident Detection API (server/main.py)."""
import os
import threading
import time
from datetime import datetime

import requests

DEFAULT_API_URL = "http://127.0.0.1:8000"
REFRESH_AFTER = 3600  # renew the token every hour so multi-day webcam sessions stay signed in


def api_url_from_env():
    """API_URL from the environment or the project's .env file (without the server's secrets)."""
    if os.environ.get("API_URL"):
        return os.environ["API_URL"]
    try:
        with open(os.path.join(os.path.dirname(__file__), ".env"), encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("API_URL="):
                    return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return DEFAULT_API_URL


class ApiError(Exception):
    """`code` is the server's error key (e.g. "invalid_credentials") or "unreachable"."""

    def __init__(self, code, status=None):
        super().__init__(code)
        self.code = code
        self.status = status


def parse_time(value):
    """API timestamps -> local aware datetime (None stays None)."""
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()


class ApiClient:
    def __init__(self, base_url=None):
        self.base_url = (base_url or api_url_from_env()).rstrip("/")
        self.session = requests.Session()
        self.token = None
        self.token_time = 0.0
        self.user = None
        self.lock = threading.Lock()

    # -- plumbing
    def request(self, method, path, auth=True, timeout=30, **kwargs):
        if auth:
            self.refresh_if_needed()
            kwargs.setdefault("headers", {})["Authorization"] = f"Bearer {self.token}"
        try:
            response = self.session.request(method, self.base_url + path, timeout=timeout, **kwargs)
        except requests.RequestException:
            raise ApiError("unreachable")
        if response.status_code >= 400:
            try:
                code = response.json().get("detail", "error")
            except ValueError:
                code = "error"
            raise ApiError(code if isinstance(code, str) else "error", response.status_code)
        return response

    def refresh_if_needed(self):
        with self.lock:
            if self.token and time.time() - self.token_time > REFRESH_AFTER:
                response = self.session.post(self.base_url + "/auth/refresh", timeout=15,
                                             headers={"Authorization": f"Bearer {self.token}"})
                if response.ok:
                    self._set_session(response.json())

    def _set_session(self, data):
        self.token = data["token"]
        self.token_time = time.time()
        self.user = data["user"]
        return self.user

    # -- auth
    def is_up(self):
        try:
            return self.session.get(self.base_url + "/health", timeout=3).ok
        except requests.RequestException:
            return False

    def login(self, username, password):
        return self._set_session(self.request("POST", "/auth/login", auth=False,
                                              json={"username": username, "password": password}).json())

    def register(self, username, password):
        return self._set_session(self.request("POST", "/auth/register", auth=False,
                                              json={"username": username, "password": password}).json())

    def logout(self):
        self.token = self.user = None

    def update_profile(self, full_name, email):
        self.user = self.request("PATCH", "/auth/me", json={"full_name": full_name, "email": email}).json()
        return self.user

    def change_password(self, current_password, new_password):
        return self.request("POST", "/auth/me/password",
                            json={"current_password": current_password, "new_password": new_password}).json()

    # -- media
    def upload(self, path, kind, captured_at=None, probability=None, duration=None):
        params = {"kind": kind, "filename": os.path.basename(path)}
        if captured_at:
            params["captured_at"] = captured_at.isoformat()
        if probability is not None:
            params["probability"] = probability
        if duration is not None:
            params["duration"] = duration
        content_type = "video/mp4" if kind == "video" else "image/png"
        with open(path, "rb") as f:  # a file object is streamed, never loaded in memory
            return self.request("POST", "/media", params=params, data=f, timeout=600,
                                headers={"Content-Type": content_type}).json()

    def list_media(self, kind=None, owner_id=None):
        params = {k: v for k, v in (("kind", kind), ("owner_id", owner_id)) if v}
        return self.request("GET", "/media", params=params).json()

    def thumbnail(self, media_id):
        return self.request("GET", f"/media/{media_id}/thumb").content

    def download(self, media_id, dest, progress=None):
        """Download to `dest` (via a .part file); progress(fraction) is called from this thread."""
        response = self.request("GET", f"/media/{media_id}/file", stream=True, timeout=600)
        total = int(response.headers.get("Content-Length", 0)) or None
        done = 0
        tmp = dest + ".part"
        with open(tmp, "wb") as f:
            for chunk in response.iter_content(256 * 1024):
                f.write(chunk)
                done += len(chunk)
                if progress and total:
                    progress(done / total)
        os.replace(tmp, dest)
        return dest

    def delete_media(self, media_id):
        return self.request("DELETE", f"/media/{media_id}").json()

    def delete_many(self, kind=None, owner_id=None, filenames=None):
        """All files of a kind (owner_id: admin only), or just the given file names. Returns how many were deleted."""
        params = {k: v for k, v in (("kind", kind), ("owner_id", owner_id)) if v}
        if filenames is not None:
            params["filenames"] = ",".join(filenames)
        return self.request("DELETE", "/media", params=params).json()["deleted"]

    # -- admin
    def admin_users(self):
        return self.request("GET", "/admin/users").json()

    def set_role(self, user_id, role):
        return self.request("PATCH", f"/admin/users/{user_id}", json={"role": role}).json()

    def create_user(self, username, password, role="user"):
        return self.request("POST", "/admin/users", json={"username": username, "password": password, "role": role}).json()

    def set_active(self, user_id, active):
        return self.request("PATCH", f"/admin/users/{user_id}/status", json={"active": active}).json()

    def admin_update_profile(self, user_id, full_name, email, password=None):
        body = {"full_name": full_name, "email": email}
        if password:
            body["password"] = password
        return self.request("PATCH", f"/admin/users/{user_id}/profile", json=body).json()

    def delete_user(self, user_id):
        return self.request("DELETE", f"/admin/users/{user_id}").json()

    def admin_stats(self, days=14):
        return self.request("GET", "/admin/stats", params={"days": days}).json()
