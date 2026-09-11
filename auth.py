import hashlib
import os
import secrets
import datetime
from fastapi import Header, HTTPException, Depends, status
from app.database import get_db
from app.config import SESSION_EXPIRE_SECONDS, DEFAULT_ADMIN_WHATSAPP, DEFAULT_ADMIN_PIN, DEFAULT_ADMIN_NAME

def hash_pin(pin: str, salt: str = None) -> tuple[str, str]:
    if not salt:
        salt = secrets.token_hex(16)
    pin_bytes = pin.encode('utf-8')
    salt_bytes = salt.encode('utf-8')
    derived = hashlib.pbkdf2_hmac('sha256', pin_bytes, salt_bytes, 100000)
    return derived.hex(), salt

def verify_pin(pin: str, pin_hash: str, salt: str) -> bool:
    new_hash, _ = hash_pin(pin, salt)
    return secrets.compare_digest(new_hash, pin_hash)

def ensure_default_admin():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE role = 'ADMIN' OR whatsapp_number = ?;", (DEFAULT_ADMIN_WHATSAPP,))
    admin = cursor.fetchone()
    if not admin:
        pin_hash, salt = hash_pin(DEFAULT_ADMIN_PIN)
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
        cursor.execute("""
            INSERT INTO users (full_name, whatsapp_number, pin_hash, salt, role, applied_role, role_status, school_organization, photo_url, created_at)
            VALUES (?, ?, ?, ?, 'ADMIN', 'ADMIN', 'APPROVED', 'Tab Directorate', '', ?)
        """, (DEFAULT_ADMIN_NAME, DEFAULT_ADMIN_WHATSAPP, pin_hash, salt, now_str))
        conn.commit()
    conn.close()

def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.datetime.now(datetime.timezone.utc)
    expires = now + datetime.timedelta(seconds=SESSION_EXPIRE_SECONDS)
    conn = get_db()
    conn.execute(
        "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (token, user_id, now.isoformat(), expires.isoformat())
    )
    conn.commit()
    conn.close()
    return token

def get_current_user_optional(authorization: str = Header(None)) -> dict | None:
    if not authorization:
        return None
    token = authorization.replace("Bearer ", "").strip()
    if not token:
        return None
    conn = get_db()
    cursor = conn.cursor()
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    cursor.execute("""
        SELECT u.id, u.full_name, u.whatsapp_number, u.role, u.applied_role, u.role_status, u.school_organization, u.photo_url, s.expires_at
        FROM sessions s
        JOIN users u ON s.user_id = u.id
        WHERE s.token = ? AND s.expires_at > ?
    """, (token, now_str))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    return dict(row)

def get_current_user(authorization: str = Header(None)) -> dict:
    user = get_current_user_optional(authorization)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required or session expired."
        )
    return user

def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required."
        )
    return user

def require_judge_or_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") not in ("JUDGE", "ADMIN"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Judge or Administrator access required."
        )
    return user

def require_leader_or_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") not in ("LEADER", "ADMIN"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Approved Team Leader or Administrator access required."
        )
    return user
