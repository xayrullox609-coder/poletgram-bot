from flask import Flask, request, jsonify, send_from_directory
import sqlite3
import os

app = Flask(__name__, static_folder="static")

DB = "poletgram.db"

# Bu yerga o'zingning Telegram ID'ingni yozasan
ADMIN_IDS = {
    8377033647
}


def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT UNIQUE,
            name TEXT NOT NULL DEFAULT '',
            bio TEXT NOT NULL DEFAULT '',
            avatar TEXT NOT NULL DEFAULT ''
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS reserved_usernames (
            username TEXT PRIMARY KEY,
            admin_id INTEGER NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS username_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            telegram_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
        )
    """)

    conn.commit()
    conn.close()


init_db()


@app.route("/")
def home():
    return send_from_directory("static", "index.html")


@app.route("/api/profile", methods=["GET"])
def profile():
    telegram_id = request.args.get("telegram_id")

    if not telegram_id:
        return jsonify({"error": "telegram_id kerak"}), 400

    conn = db()

    user = conn.execute(
        "SELECT * FROM users WHERE telegram_id=?",
        (telegram_id,)
    ).fetchone()

    conn.close()

    if not user:
        return jsonify({
            "exists": False
        })

    return jsonify({
        "exists": True,
        "telegram_id": user["telegram_id"],
        "username": user["username"],
        "name": user["name"],
        "bio": user["bio"],
        "avatar": user["avatar"]
    })


@app.route("/api/profile", methods=["POST"])
def create_profile():
    data = request.json or {}

    telegram_id = data.get("telegram_id")
    username = (data.get("username") or "").lower().strip().lstrip("@")
    name = data.get("name", "").strip()
    bio = data.get("bio", "").strip()
    avatar = data.get("avatar", "")

    if not telegram_id or not username or not name:
        return jsonify({
            "error": "Username va ism majburiy"
        }), 400

    conn = db()

    # Admin rezerv qilgan username tekshiriladi
    reserved = conn.execute(
        "SELECT * FROM reserved_usernames WHERE username=?",
        (username,)
    ).fetchone()

    if reserved:
        conn.close()
        return jsonify({
            "error": "Bu username admin tomonidan egallangan"
        }), 409

    try:
        conn.execute("""
            INSERT INTO users
            (telegram_id, username, name, bio, avatar)
            VALUES (?, ?, ?, ?, ?)
        """, (
            telegram_id,
            username,
            name,
            bio,
            avatar
        ))

        conn.commit()

    except sqlite3.IntegrityError:
        conn.close()

        return jsonify({
            "error": "Bu username allaqachon ishlatilgan"
        }), 409

    conn.close()

    return jsonify({
        "success": True
    })


# Username mavjudligini tekshirish
@app.route("/api/username/check")
def check_username():
    username = (
        request.args.get("username", "")
        .lower()
        .strip()
        .lstrip("@")
    )

    conn = db()

    user = conn.execute(
        "SELECT telegram_id FROM users WHERE username=?",
        (username,)
    ).fetchone()

    reserved = conn.execute(
        "SELECT admin_id FROM reserved_usernames WHERE username=?",
        (username,)
    ).fetchone()

    conn.close()

    if reserved:
        return jsonify({
            "available": False,
            "reserved": True
        })

    if user:
        return jsonify({
            "available": False,
            "reserved": False
        })

    return jsonify({
        "available": True,
        "reserved": False
    })


# ADMIN: username egallash
@app.route("/api/admin/reserve", methods=["POST"])
def admin_reserve():
    data = request.json or {}

    admin_id = int(data.get("admin_id", 0))

    if admin_id not in ADMIN_IDS:
        return jsonify({"error": "Ruxsat yo'q"}), 403

    username = (
        data.get("username", "")
        .lower()
        .strip()
        .lstrip("@")
    )

    if not username:
        return jsonify({"error": "Username kiriting"}), 400

    conn = db()

    try:
        conn.execute("""
            INSERT INTO reserved_usernames
            (username, admin_id)
            VALUES (?, ?)
        """, (username, admin_id))

        conn.commit()

    except sqlite3.IntegrityError:
        conn.close()

        return jsonify({
            "error": "Bu username allaqachon rezervda"
        }), 409

    conn.close()

    return jsonify({
        "success": True,
        "message": f"@{username} egallandi"
    })


# USER: admin egallagan username uchun so'rov
@app.route("/api/username/request", methods=["POST"])
def username_request():
    data = request.json or {}

    telegram_id = int(data.get("telegram_id", 0))

    username = (
        data.get("username", "")
        .lower()
        .strip()
        .lstrip("@")
    )

    conn = db()

    reserved = conn.execute(
        "SELECT * FROM reserved_usernames WHERE username=?",
        (username,)
    ).fetchone()

    if not reserved:
        conn.close()

        return jsonify({
            "error": "Bu username admin rezervida emas"
        }), 404

    conn.execute("""
        INSERT INTO username_requests
        (username, telegram_id)
        VALUES (?, ?)
    """, (
        username,
        telegram_id
    ))

    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "message": "So'rov adminga yuborildi"
    })


# ADMIN: so'rovlarni ko'rish
@app.route("/api/admin/requests")
def admin_requests():
    admin_id = int(request.args.get("admin_id", 0))

    if admin_id not in ADMIN_IDS:
        return jsonify({"error": "Ruxsat yo'q"}), 403

    conn = db()

    rows = conn.execute("""
        SELECT *
        FROM username_requests
        WHERE status='pending'
        ORDER BY id DESC
    """).fetchall()

    conn.close()

    return jsonify([
        dict(row)
        for row in rows
    ])


# ADMIN: username'ni foydalanuvchiga berish
@app.route("/api/admin/give", methods=["POST"])
def admin_give():
    data = request.json or {}

    admin_id = int(data.get("admin_id", 0))

    if admin_id not in ADMIN_IDS:
        return jsonify({"error": "Ruxsat yo'q"}), 403

    request_id = int(data.get("request_id"))

    conn = db()

    req = conn.execute(
        "SELECT * FROM username_requests WHERE id=?",
        (request_id,)
    ).fetchone()

    if not req:
        conn.close()
        return jsonify({"error": "So'rov topilmadi"}), 404

    username = req["username"]
    user_id = req["telegram_id"]

    # Username rezervdan chiqariladi
    conn.execute(
        "DELETE FROM reserved_usernames WHERE username=?",
        (username,)
    )

    # Eski username bo'lsa almashtiriladi
    conn.execute("""
        UPDATE users
        SET username=?
        WHERE telegram_id=?
    """, (username, user_id))

    conn.execute("""
        UPDATE username_requests
        SET status='approved'
        WHERE id=?
    """, (request_id,))

    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "message": f"@{username} foydalanuvchiga berildi"
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)