import os
import json
import hmac
import hashlib
import sqlite3
from datetime import datetime, timezone
from urllib.parse import parse_qsl

from flask import Flask, request, jsonify, send_file


app = Flask(__name__)

# ==============================
# CONFIG
# ==============================

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}

DATABASE = "poletgram.db"


# ==============================
# DATABASE
# ==============================

def db():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():

    connection = db()
    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT UNIQUE,
            name TEXT NOT NULL,
            bio TEXT DEFAULT '',
            avatar TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reserved_usernames (
            username TEXT PRIMARY KEY,
            admin_id INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS username_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            telegram_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL
        )
    """)

    connection.commit()
    connection.close()


init_db()


# ==============================
# HELPERS
# ==============================

def now():
    return datetime.now(timezone.utc).isoformat()


def error(message, status=400):
    return jsonify({
        "error": message
    }), status


def valid_username(username):

    if not username:
        return False

    if len(username) < 3 or len(username) > 32:
        return False

    allowed = "abcdefghijklmnopqrstuvwxyz0123456789_"

    return all(char in allowed for char in username)


# ==============================
# TELEGRAM WEB APP AUTH
# ==============================

def validate_telegram_init_data(init_data):

    if not BOT_TOKEN:
        return None

    try:

        data = dict(parse_qsl(
            init_data,
            keep_blank_values=True
        ))

        received_hash = data.pop("hash", None)

        if not received_hash:
            return None

        data_check_string = "\n".join(
            f"{key}={data[key]}"
            for key in sorted(data)
        )

        secret_key = hmac.new(
            b"WebAppData",
            BOT_TOKEN.encode(),
            hashlib.sha256
        ).digest()

        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(
            calculated_hash,
            received_hash
        ):
            return None

        if "user" not in data:
            return None

        user = json.loads(data["user"])

        return user

    except Exception:
        return None


def current_user():

    init_data = request.headers.get(
        "X-Telegram-Init-Data",
        ""
    )

    if not init_data:
        return None

    return validate_telegram_init_data(init_data)


def require_user():

    user = current_user()

    if not user:
        return None, error(
            "Telegram foydalanuvchisi tasdiqlanmadi.",
            401
        )

    return user, None


def require_admin():

    user, response = require_user()

    if response:
        return None, response

    telegram_id = int(user["id"])

    if telegram_id not in ADMIN_IDS:
        return None, error(
            "Siz admin emassiz.",
            403
        )

    return user, None


# ==============================
# HOME
# ==============================

@app.route("/")
def home():

    return send_file("index.html")


# ==============================
# CURRENT USER
# ==============================

@app.route("/api/me")
def me():

    user, response = require_user()

    if response:
        return response

    telegram_id = int(user["id"])

    connection = db()

    profile = connection.execute(
        """
        SELECT *
        FROM users
        WHERE telegram_id = ?
        """,
        (telegram_id,)
    ).fetchone()

    connection.close()

    return jsonify({
        "telegram_user": {
            "id": telegram_id,
            "first_name": user.get("first_name", ""),
            "last_name": user.get("last_name", ""),
            "username": user.get("username", ""),
            "photo_url": user.get("photo_url", "")
        },
        "profile": dict(profile) if profile else None,
        "is_admin": telegram_id in ADMIN_IDS
    })


# ==============================
# CREATE PROFILE
# ==============================

@app.route("/api/profile", methods=["POST"])
def create_profile():

    user, response = require_user()

    if response:
        return response

    data = request.get_json() or {}

    username = str(
        data.get("username", "")
    ).strip().lower().lstrip("@")

    name = str(
        data.get("name", "")
    ).strip()

    bio = str(
        data.get("bio", "")
    ).strip()

    avatar = str(
        data.get("avatar", "")
    )

    if not valid_username(username):
        return error(
            "Username 3-32 ta belgi bo‘lishi kerak. "
            "Faqat a-z, 0-9 va _ ishlating."
        )

    if not name:
        return error(
            "Ism kiritilishi kerak."
        )

    telegram_id = int(user["id"])

    connection = db()

    try:

        reserved = connection.execute(
            """
            SELECT username
            FROM reserved_usernames
            WHERE username = ?
            """,
            (username,)
        ).fetchone()

        if reserved:
            return error(
                "Bu username admin tomonidan rezerv qilingan.",
                409
            )

        existing_user = connection.execute(
            """
            SELECT username
            FROM users
            WHERE username = ?
            """,
            (username,)
        ).fetchone()

        if existing_user:
            return error(
                "Bu username allaqachon band.",
                409
            )

        already_profile = connection.execute(
            """
            SELECT telegram_id
            FROM users
            WHERE telegram_id = ?
            """,
            (telegram_id,)
        ).fetchone()

        if already_profile:
            return error(
                "Sizda allaqachon Poletgram profili mavjud.",
                409
            )

        connection.execute(
            """
            INSERT INTO users
            (
                telegram_id,
                username,
                name,
                bio,
                avatar,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                telegram_id,
                username,
                name,
                bio,
                avatar,
                now()
            )
        )

        connection.commit()

        profile = connection.execute(
            """
            SELECT *
            FROM users
            WHERE telegram_id = ?
            """,
            (telegram_id,)
        ).fetchone()

        return jsonify({
            "success": True,
            "profile": dict(profile)
        })

    except sqlite3.IntegrityError:

        return error(
            "Bu username allaqachon band.",
            409
        )

    finally:

        connection.close()


# ==============================
# EDIT PROFILE
# ==============================

@app.route("/api/profile", methods=["PUT"])
def edit_profile():

    user, response = require_user()

    if response:
        return response

    data = request.get_json() or {}

    username = str(
        data.get("username", "")
    ).strip().lower().lstrip("@")

    name = str(
        data.get("name", "")
    ).strip()

    bio = str(
        data.get("bio", "")
    ).strip()

    avatar = str(
        data.get("avatar", "")
    )

    if not valid_username(username):
        return error(
            "Username noto‘g‘ri."
        )

    if not name:
        return error(
            "Ism kiritilishi kerak."
        )

    telegram_id = int(user["id"])

    connection = db()

    try:

        reserved = connection.execute(
            """
            SELECT username
            FROM reserved_usernames
            WHERE username = ?
            """,
            (username,)
        ).fetchone()

        if reserved:

            return error(
                "Bu username admin tomonidan rezerv qilingan.",
                409
            )

        another_user = connection.execute(
            """
            SELECT telegram_id
            FROM users
            WHERE username = ?
            AND telegram_id != ?
            """,
            (
                username,
                telegram_id
            )
        ).fetchone()

        if another_user:

            return error(
                "Bu username allaqachon band.",
                409
            )

        connection.execute(
            """
            UPDATE users
            SET
                username = ?,
                name = ?,
                bio = ?,
                avatar = ?
            WHERE telegram_id = ?
            """,
            (
                username,
                name,
                bio,
                avatar,
                telegram_id
            )
        )

        connection.commit()

        profile = connection.execute(
            """
            SELECT *
            FROM users
            WHERE telegram_id = ?
            """,
            (telegram_id,)
        ).fetchone()

        if not profile:
            return error(
                "Profil topilmadi.",
                404
            )

        return jsonify({
            "success": True,
            "profile": dict(profile)
        })

    except sqlite3.IntegrityError:

        return error(
            "Bu username band.",
            409
        )

    finally:

        connection.close()


# ==============================
# CHECK USERNAME
# ==============================

@app.route("/api/username/check")
def check_username():

    user, response = require_user()

    if response:
        return response

    username = request.args.get(
        "username",
        ""
    ).strip().lower().lstrip("@")

    if not valid_username(username):

        return jsonify({
            "available": False,
            "taken": False,
            "reserved": False,
            "invalid": True
        })

    connection = db()

    reserved = connection.execute(
        """
        SELECT username
        FROM reserved_usernames
        WHERE username = ?
        """,
        (username,)
    ).fetchone()

    if reserved:

        connection.close()

        return jsonify({
            "available": False,
            "taken": False,
            "reserved": True
        })

    taken = connection.execute(
        """
        SELECT telegram_id
        FROM users
        WHERE username = ?
        """,
        (username,)
    ).fetchone()

    connection.close()

    current_id = int(user["id"])

    if taken and int(taken["telegram_id"]) != current_id:

        return jsonify({
            "available": False,
            "taken": True,
            "reserved": False
        })

    return jsonify({
        "available": True,
        "taken": False,
        "reserved": False
    })


# ==============================
# USER REQUEST
# ==============================

@app.route("/api/username/request", methods=["POST"])
def username_request():

    user, response = require_user()

    if response:
        return response

    data = request.get_json() or {}

    username = str(
        data.get("username", "")
    ).strip().lower().lstrip("@")

    if not valid_username(username):

        return error(
            "Username noto‘g‘ri."
        )

    telegram_id = int(user["id"])

    connection = db()

    reserved = connection.execute(
        """
        SELECT username
        FROM reserved_usernames
        WHERE username = ?
        """,
        (username,)
    ).fetchone()

    if not reserved:

        connection.close()

        return error(
            "Bu username admin tomonidan rezerv qilinmagan."
        )

    existing_request = connection.execute(
        """
        SELECT id
        FROM username_requests
        WHERE username = ?
        AND telegram_id = ?
        AND status = 'pending'
        """,
        (
            username,
            telegram_id
        )
    ).fetchone()

    if existing_request:

        connection.close()

        return error(
            "Siz bu username uchun allaqachon so‘rov yuborgansiz."
        )

    connection.execute(
        """
        INSERT INTO username_requests
        (
            username,
            telegram_id,
            status,
            created_at
        )
        VALUES (?, ?, 'pending', ?)
        """,
        (
            username,
            telegram_id,
            now()
        )
    )

    connection.commit()
    connection.close()

    return jsonify({
        "success": True
    })


# ==============================
# ADMIN RESERVE
# ==============================

@app.route("/api/admin/reserve", methods=["POST"])
def admin_reserve():

    admin, response = require_admin()

    if response:
        return response

    data = request.get_json() or {}

    username = str(
        data.get("username", "")
    ).strip().lower().lstrip("@")

    if not valid_username(username):

        return error(
            "Username noto‘g‘ri."
        )

    admin_id = int(admin["id"])

    connection = db()

    try:

        already_reserved = connection.execute(
            """
            SELECT username
            FROM reserved_usernames
            WHERE username = ?
            """,
            (username,)
        ).fetchone()

        if already_reserved:

            return error(
                "Bu username allaqachon rezerv qilingan.",
                409
            )

        # Agar username boshqa foydalanuvchida bo‘lsa,
        # undan username olib tashlanadi.
        owner = connection.execute(
            """
            SELECT telegram_id
            FROM users
            WHERE username = ?
            """,
            (username,)
        ).fetchone()

        if owner:

            connection.execute(
                """
                UPDATE users
                SET username = NULL
                WHERE telegram_id = ?
                """,
                (owner["telegram_id"],)
            )

        connection.execute(
            """
            INSERT INTO reserved_usernames
            (
                username,
                admin_id,
                created_at
            )
            VALUES (?, ?, ?)
            """,
            (
                username,
                admin_id,
                now()
            )
        )

        connection.commit()

        return jsonify({
            "success": True,
            "username": username
        })

    except sqlite3.IntegrityError:

        return error(
            "Username rezerv qilinmadi.",
            409
        )

    finally:

        connection.close()


# ==============================
# ADMIN REQUESTS
# ==============================

@app.route("/api/admin/requests")
def admin_requests():

    admin, response = require_admin()

    if response:
        return response

    connection = db()

    rows = connection.execute(
        """
        SELECT
            r.id,
            r.username,
            r.telegram_id,
            r.status,
            r.created_at,
            u.name,
            u.avatar
        FROM username_requests r
        LEFT JOIN users u
            ON u.telegram_id = r.telegram_id
        WHERE r.status = 'pending'
        ORDER BY r.id DESC
        """
    ).fetchall()

    connection.close()

    return jsonify({
        "requests": [
            dict(row)
            for row in rows
        ]
    })


# ==============================
# ADMIN GIVE USERNAME
# ==============================

@app.route("/api/admin/give", methods=["POST"])
def admin_give():

    admin, response = require_admin()

    if response:
        return response

    data = request.get_json() or {}

    username = str(
        data.get("username", "")
    ).strip().lower().lstrip("@")

    telegram_id = data.get("telegram_id")
    request_id = data.get("request_id")

    if not valid_username(username):
        return error(
            "Username noto‘g‘ri."
        )

    if not telegram_id:
        return error(
            "Foydalanuvchi topilmadi."
        )

    try:
        telegram_id = int(telegram_id)
    except:
        return error(
            "Telegram ID noto‘g‘ri."
        )

    connection = db()

    try:

        reserved = connection.execute(
            """
            SELECT username
            FROM reserved_usernames
            WHERE username = ?
            """,
            (username,)
        ).fetchone()

        if not reserved:

            return error(
                "Bu username rezerv qilinmagan."
            )

        recipient = connection.execute(
            """
            SELECT telegram_id
            FROM users
            WHERE telegram_id = ?
            """,
            (telegram_id,)
        ).fetchone()

        if not recipient:

            return error(
                "Bu foydalanuvchining Poletgram profili yo‘q."
            )

        # Qabul qiluvchining eski username'i bo‘shatiladi.
        connection.execute(
            """
            UPDATE users
            SET username = NULL
            WHERE telegram_id = ?
            """,
            (telegram_id,)
        )

        # Username beriladi.
        connection.execute(
            """
            UPDATE users
            SET username = ?
            WHERE telegram_id = ?
            """,
            (
                username,
                telegram_id
            )
        )

        # Rezerv o‘chiriladi.
        connection.execute(
            """
            DELETE FROM reserved_usernames
            WHERE username = ?
            """,
            (username,)
        )

        # Tanlangan so‘rov tasdiqlanadi.
        if request_id:

            connection.execute(
                """
                UPDATE username_requests
                SET status = 'approved'
                WHERE id = ?
                """,
                (int(request_id),)
            )

        # Shu username uchun qolgan so‘rovlar rad qilinadi.
        connection.execute(
            """
            UPDATE username_requests
            SET status = 'rejected'
            WHERE username = ?
            AND status = 'pending'
            AND telegram_id != ?
            """,
            (
                username,
                telegram_id
            )
        )

        connection.commit()

        return jsonify({
            "success": True,
            "username": username
        })

    except sqlite3.IntegrityError:

        connection.rollback()

        return error(
            "Username berishda xatolik.",
            409
        )

    finally:

        connection.close()


# ==============================
# ADMIN REJECT REQUEST
# ==============================

@app.route("/api/admin/reject", methods=["POST"])
def admin_reject():

    admin, response = require_admin()

    if response:
        return response

    data = request.get_json() or {}

    request_id = data.get("request_id")

    if not request_id:
        return error(
            "So‘rov ID topilmadi."
        )

    try:
        request_id = int(request_id)
    except:
        return error(
            "So‘rov ID noto‘g‘ri."
        )

    connection = db()

    try:
        row = connection.execute(
            """
            SELECT username, telegram_id
            FROM username_requests
            WHERE id = ?
            AND status = 'pending'
            """,
            (request_id,)
        ).fetchone()

        if not row:
            return error(
                "So‘rov topilmadi yoki allaqachon ko‘rib chiqilgan.",
                404
            )

        connection.execute(
            """
            UPDATE username_requests
            SET status = 'rejected'
            WHERE id = ?
            """,
            (request_id,)
        )

        connection.commit()

        return jsonify({
            "success": True
        })

    finally:
        connection.close()


# ==============================
# ADMIN RESERVED USERNAMES
# ==============================

@app.route("/api/admin/reserved")
def admin_reserved():

    admin, response = require_admin()

    if response:
        return response

    connection = db()

    rows = connection.execute(
        """
        SELECT username, admin_id, created_at
        FROM reserved_usernames
        ORDER BY created_at DESC
        """
    ).fetchall()

    connection.close()

    return jsonify({
        "reserved": [
            dict(row)
            for row in rows
        ]
    })


# ==============================
# ADMIN RELEASE USERNAME
# ==============================

@app.route("/api/admin/release", methods=["POST"])
def admin_release():

    admin, response = require_admin()

    if response:
        return response

    data = request.get_json() or {}

    username = str(
        data.get("username", "")
    ).strip().lower().lstrip("@")

    if not valid_username(username):
        return error(
            "Username noto‘g‘ri."
        )

    connection = db()

    row = connection.execute(
        """
        SELECT username
        FROM reserved_usernames
        WHERE username = ?
        """,
        (username,)
    ).fetchone()

    if not row:
        connection.close()

        return error(
            "Bu username rezerv qilinmagan.",
            404
        )

    connection.execute(
        """
        DELETE FROM reserved_usernames
        WHERE username = ?
        """,
        (username,)
    )

    connection.commit()
    connection.close()

    return jsonify({
        "success": True,
        "username": username
    })


# ==============================
# ADMIN STATS
# ==============================

@app.route("/api/admin/stats")
def admin_stats():

    admin, response = require_admin()

    if response:
        return response

    connection = db()

    users = connection.execute(
        "SELECT COUNT(*) AS count FROM users"
    ).fetchone()["count"]

    reserved = connection.execute(
        "SELECT COUNT(*) AS count FROM reserved_usernames"
    ).fetchone()["count"]

    requests = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM username_requests
        WHERE status = 'pending'
        """
    ).fetchone()["count"]

    connection.close()

    return jsonify({
        "users": users,
        "reserved_usernames": reserved,
        "pending_requests": requests
    })


# ==============================
# START
# ==============================

if __name__ == "__main__":

    port = int(
        os.getenv("PORT", 10000)
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
