"""
Authentication module — MySQL-backed user management with JWT sessions.
"""
import os
import re
import hmac
import hashlib
import base64
import secrets
import time
from datetime import datetime, timedelta
from typing import Optional

import mysql.connector
from mysql.connector import pooling
import bcrypt

# ── DB connection pool ────────────────────────────────────────────────────────

_pool: Optional[pooling.MySQLConnectionPool] = None


def get_pool() -> pooling.MySQLConnectionPool:
    global _pool
    if _pool is None:
        _pool = pooling.MySQLConnectionPool(
            pool_name="marketai",
            pool_size=5,
            host=os.environ.get("MYSQL_HOST", "127.0.0.1"),
            port=int(os.environ.get("MYSQL_PORT", 3306)),
            user=os.environ.get("MYSQL_USER", "root"),
            password=os.environ.get("MYSQL_PASSWORD", ""),
            database=os.environ.get("MYSQL_DATABASE", "marketai"),
            autocommit=True,
        )
    return _pool


def get_conn():
    return get_pool().get_connection()


def init_db():
    """Create tables and seed admin if they don't exist."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            email       VARCHAR(255) NOT NULL UNIQUE,
            password    VARCHAR(255) NOT NULL,
            role        ENUM('admin','user') NOT NULL DEFAULT 'user',
            must_change  TINYINT(1) NOT NULL DEFAULT 1,
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS campaign_logs (
            id           INT AUTO_INCREMENT PRIMARY KEY,
            user_id      INT NOT NULL,
            email        VARCHAR(255) NOT NULL,
            role         VARCHAR(20) NOT NULL,
            input_type   ENUM('prompt','image+prompt') NOT NULL DEFAULT 'prompt',
            prompt       TEXT,
            image_count  INT NOT NULL DEFAULT 0,
            started_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    # Seed admin (password: Admin@MarketAI1)
    admin_hash = bcrypt.hashpw(b"Admin@MarketAI1", bcrypt.gensalt(12)).decode()
    cur.execute("""
        INSERT IGNORE INTO users (email, password, role, must_change)
        VALUES (%s, %s, 'admin', 0)
    """, ("admin@marketai.com", admin_hash))
    cur.close()
    conn.close()


# ── Password helpers ──────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(12)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


def password_strong(plain: str) -> bool:
    """Min 8 chars, at least one upper, one lower, one digit, one special."""
    return bool(re.match(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^a-zA-Z\d]).{8,}$', plain))


# ── Simple JWT (HS256, no external lib) ──────────────────────────────────────

_SECRET = os.environ.get("JWT_SECRET", secrets.token_hex(32))
_TTL = 60 * 60 * 8  # 8 hours


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _sign(msg: str) -> str:
    return _b64url(hmac.new(_SECRET.encode(), msg.encode(), hashlib.sha256).digest())


def create_token(user_id: int, email: str, role: str) -> str:
    import json
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64url(json.dumps({
        "sub": user_id, "email": email, "role": role,
        "exp": int(time.time()) + _TTL
    }).encode())
    sig = _sign(f"{header}.{payload}")
    return f"{header}.{payload}.{sig}"


def decode_token(token: str) -> Optional[dict]:
    import json
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header, payload, sig = parts
        if _sign(f"{header}.{payload}") != sig:
            return None
        data = json.loads(base64.urlsafe_b64decode(payload + "=="))
        if data.get("exp", 0) < time.time():
            return None
        return data
    except Exception:
        return None


# ── User CRUD ─────────────────────────────────────────────────────────────────

def get_user_by_email(email: str) -> Optional[dict]:
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM users WHERE email=%s", (email,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def get_user_by_id(user_id: int) -> Optional[dict]:
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM users WHERE id=%s", (user_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def create_user(email: str, temp_password: str) -> dict:
    hashed = hash_password(temp_password)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (email, password, role, must_change) VALUES (%s, %s, 'user', 1)",
        (email, hashed)
    )
    user_id = cur.lastrowid
    cur.close()
    conn.close()
    return {"id": user_id, "email": email, "role": "user", "must_change": True}


def update_password(user_id: int, new_password: str):
    hashed = hash_password(new_password)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET password=%s, must_change=0 WHERE id=%s",
        (hashed, user_id)
    )
    cur.close()
    conn.close()


def delete_user(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM users WHERE id=%s AND role!='admin'", (user_id,))
    cur.close()
    conn.close()


def log_campaign(user_id: int, email: str, role: str, prompt: str, image_count: int):
    input_type = "image+prompt" if image_count > 0 else "prompt"
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO campaign_logs (user_id, email, role, input_type, prompt, image_count) VALUES (%s,%s,%s,%s,%s,%s)",
        (user_id, email, role, input_type, prompt or "", image_count)
    )
    cur.close()
    conn.close()


def list_campaign_logs() -> list:
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, user_id, email, role, input_type, prompt, image_count, started_at FROM campaign_logs ORDER BY started_at DESC LIMIT 200")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    for r in rows:
        if isinstance(r.get("started_at"), datetime):
            r["started_at"] = r["started_at"].isoformat()
    return rows


def list_users() -> list:
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, email, role, must_change, created_at FROM users ORDER BY id")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    # make created_at JSON-serialisable
    for r in rows:
        if isinstance(r.get("created_at"), datetime):
            r["created_at"] = r["created_at"].isoformat()
    return rows
