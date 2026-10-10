import os
import secrets
import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from functools import wraps
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv
from flask import Flask, g, jsonify, render_template, request, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DATABASE = Path(os.environ.get("CAMPUSLOOP_DATABASE", BASE_DIR / "campusloop.db"))
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
MODEL_NAME = "gemma-4-26b-a4b-it"
COLLEGE_TIMEZONE = os.environ.get("COLLEGE_TIMEZONE", "Asia/Kolkata")
TOKEN_CONVERSION = 10
UPLOAD_LIMIT = 5 * 1024 * 1024
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32),
    MAX_CONTENT_LENGTH=UPLOAD_LIMIT,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
)


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def college_zone():
    try:
        return ZoneInfo(COLLEGE_TIMEZONE)
    except ZoneInfoNotFoundError as exc:
        raise RuntimeError(f"Unknown COLLEGE_TIMEZONE: {COLLEGE_TIMEZONE}") from exc


def attendance_reward_tier(percentage):
    if percentage < 70:
        return 0
    if percentage < 80:
        return 200
    if percentage < 90:
        return 300
    if percentage <= 100:
        return 500
    raise ValueError("Attendance percentage cannot exceed 100.")


def reward_value_paise(tokens):
    return tokens * TOKEN_CONVERSION


def token_conversion_json():
    return {"token_value_paise": TOKEN_CONVERSION, "conversion_tokens": 100, "conversion_rupees": 10}


def attendance_week(week_start):
    try:
        start_date = date.fromisoformat(week_start)
    except ValueError as exc:
        raise ValueError("Week start must be an ISO date (YYYY-MM-DD).") from exc
    if start_date.weekday() != 0:
        raise ValueError("Attendance reward weeks start on Monday.")
    zone = college_zone()
    local_start = datetime.combine(start_date, time.min, zone)
    local_end = datetime.combine(start_date + timedelta(days=7), time.min, zone)
    return (
        local_start.astimezone(timezone.utc).isoformat(),
        local_end.astimezone(timezone.utc).isoformat(),
        (start_date + timedelta(days=7)).isoformat(),
    )


def connect_db():
    connection = sqlite3.connect(DATABASE, timeout=10, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def db():
    if "db" not in g:
        g.db = connect_db()
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def initialize_database():
    connection = connect_db()
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('student', 'admin')),
            balance INTEGER NOT NULL DEFAULT 0 CHECK(balance >= 0),
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ledger (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            entry_type TEXT NOT NULL CHECK(entry_type IN ('credit', 'debit')),
            amount INTEGER NOT NULL CHECK(amount > 0),
            reason TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_id TEXT NOT NULL,
            idempotency_key TEXT,
            created_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS ledger_idempotency
            ON ledger(user_id, idempotency_key) WHERE idempotency_key IS NOT NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS ledger_refund_once
            ON ledger(source_type, source_id) WHERE source_type = 'order_refund';
        CREATE UNIQUE INDEX IF NOT EXISTS ledger_approval_once
            ON ledger(source_type, source_id)
            WHERE source_type IN ('submission_approval','activity_participation');
        CREATE UNIQUE INDEX IF NOT EXISTS ledger_unique_reference
            ON ledger(source_type, source_id);
        CREATE TABLE IF NOT EXISTS rewards (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            token_price INTEGER NOT NULL CHECK(token_price > 0),
            active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS menu_items (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            token_price INTEGER NOT NULL CHECK(token_price > 0),
            active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS orders (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            token_cost INTEGER NOT NULL CHECK(token_cost > 0),
            status TEXT NOT NULL CHECK(status IN ('Pending','Preparing','Ready','Completed','Cancelled')),
            idempotency_key TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(user_id, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY,
            order_id TEXT NOT NULL REFERENCES orders(id),
            menu_item_id INTEGER REFERENCES menu_items(id),
            item_name TEXT NOT NULL,
            quantity INTEGER NOT NULL CHECK(quantity > 0),
            unit_token_price INTEGER NOT NULL CHECK(unit_token_price > 0)
        );
        CREATE TABLE IF NOT EXISTS activities (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            category TEXT NOT NULL,
            start_at TEXT NOT NULL,
            end_at TEXT NOT NULL,
            venue TEXT NOT NULL,
            organizer TEXT NOT NULL,
            instructions TEXT NOT NULL,
            reward_tokens INTEGER NOT NULL DEFAULT 0 CHECK(reward_tokens >= 0),
            is_sample INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS activity_participations (
            id INTEGER PRIMARY KEY,
            activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id),
            status TEXT NOT NULL CHECK(status IN ('Pending Review','Approved','Rejected')),
            reward_tokens INTEGER NOT NULL DEFAULT 0 CHECK(reward_tokens >= 0),
            created_at TEXT NOT NULL,
            reviewed_at TEXT,
            UNIQUE(activity_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS submissions (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            category TEXT NOT NULL,
            image_filename TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('Pending Review','Approved','Rejected')),
            reward_tokens INTEGER NOT NULL DEFAULT 0 CHECK(reward_tokens >= 0),
            created_at TEXT NOT NULL,
            reviewed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE
        );
        CREATE TABLE IF NOT EXISTS course_sections (
            id INTEGER PRIMARY KEY,
            course_id INTEGER NOT NULL REFERENCES courses(id),
            name TEXT NOT NULL,
            UNIQUE(course_id, name)
        );
        CREATE TABLE IF NOT EXISTS subjects (
            id INTEGER PRIMARY KEY,
            section_id INTEGER NOT NULL REFERENCES course_sections(id),
            name TEXT NOT NULL,
            UNIQUE(section_id, name)
        );
        CREATE TABLE IF NOT EXISTS scheduled_classes (
            id INTEGER PRIMARY KEY,
            section_id INTEGER NOT NULL REFERENCES course_sections(id),
            subject_id INTEGER NOT NULL REFERENCES subjects(id),
            name TEXT NOT NULL,
            UNIQUE(section_id, subject_id)
        );
        CREATE TABLE IF NOT EXISTS student_enrollments (
            section_id INTEGER NOT NULL REFERENCES course_sections(id),
            student_id INTEGER NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL,
            PRIMARY KEY(section_id, student_id)
        );
        CREATE TABLE IF NOT EXISTS teacher_assignments (
            class_id INTEGER NOT NULL REFERENCES scheduled_classes(id),
            teacher_id INTEGER NOT NULL REFERENCES users(id),
            assigned_at TEXT NOT NULL,
            PRIMARY KEY(class_id, teacher_id)
        );
        CREATE TABLE IF NOT EXISTS class_sessions (
            id INTEGER PRIMARY KEY,
            class_id INTEGER NOT NULL REFERENCES scheduled_classes(id),
            starts_at TEXT NOT NULL,
            ends_at TEXT NOT NULL,
            finalized INTEGER NOT NULL DEFAULT 0 CHECK(finalized IN (0,1)),
            created_by INTEGER NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL,
            UNIQUE(class_id, starts_at)
        );
        CREATE TABLE IF NOT EXISTS attendance_records (
            id INTEGER PRIMARY KEY,
            session_id INTEGER NOT NULL REFERENCES class_sessions(id),
            student_id INTEGER NOT NULL REFERENCES users(id),
            status TEXT NOT NULL CHECK(status IN ('Present','Absent')),
            recorded_by INTEGER NOT NULL REFERENCES users(id),
            recorded_at TEXT NOT NULL,
            UNIQUE(session_id, student_id)
        );
        CREATE TABLE IF NOT EXISTS attendance_corrections (
            id INTEGER PRIMARY KEY,
            attendance_id INTEGER NOT NULL REFERENCES attendance_records(id),
            previous_status TEXT NOT NULL CHECK(previous_status IN ('Present','Absent')),
            corrected_status TEXT NOT NULL CHECK(corrected_status IN ('Present','Absent')),
            reason TEXT NOT NULL,
            corrected_by INTEGER NOT NULL REFERENCES users(id),
            corrected_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS weekly_attendance_rewards (
            id INTEGER PRIMARY KEY,
            student_id INTEGER NOT NULL REFERENCES users(id),
            week_start TEXT NOT NULL,
            week_end TEXT NOT NULL,
            attendance_percentage REAL NOT NULL CHECK(attendance_percentage BETWEEN 0 AND 100),
            sessions_attended INTEGER NOT NULL CHECK(sessions_attended >= 0),
            sessions_held INTEGER NOT NULL CHECK(sessions_held > 0),
            reward_tokens INTEGER NOT NULL CHECK(reward_tokens >= 0),
            status TEXT NOT NULL CHECK(status IN ('Issued','Not eligible')),
            issued_by INTEGER NOT NULL REFERENCES users(id),
            issued_at TEXT NOT NULL,
            UNIQUE(student_id, week_start)
        );
        CREATE TABLE IF NOT EXISTS attendance_reward_adjustments (
            id INTEGER PRIMARY KEY,
            reference TEXT NOT NULL UNIQUE,
            student_id INTEGER NOT NULL REFERENCES users(id),
            week_start TEXT NOT NULL,
            previous_percentage REAL NOT NULL,
            corrected_percentage REAL NOT NULL,
            previous_reward INTEGER NOT NULL,
            corrected_reward INTEGER NOT NULL,
            delta_tokens INTEGER NOT NULL,
            reason TEXT NOT NULL,
            request_key TEXT NOT NULL,
            adjusted_by INTEGER NOT NULL REFERENCES users(id),
            ledger_id INTEGER REFERENCES ledger(id),
            created_at TEXT NOT NULL,
            UNIQUE(student_id, week_start, request_key)
        );
        """
    )
    connection.execute("INSERT OR IGNORE INTO settings(key,value) VALUES ('contribution_reward','50')")
    connection.execute("INSERT OR IGNORE INTO settings(key,value) VALUES ('college_timezone',?)", (COLLEGE_TIMEZONE,))
    connection.execute("DELETE FROM settings WHERE key IN ('conversion_tokens','conversion_rupees')")
    weekly_columns = {row["name"] for row in connection.execute("PRAGMA table_info(weekly_attendance_rewards)")}
    if "status" not in weekly_columns:
        connection.execute(
            "ALTER TABLE weekly_attendance_rewards ADD COLUMN status TEXT NOT NULL DEFAULT 'Issued'"
        )
    reward_columns = {row["name"] for row in connection.execute("PRAGMA table_info(rewards)")}
    if "rupee_value" in reward_columns:
        connection.execute("ALTER TABLE rewards DROP COLUMN rupee_value")
    reconcile_legacy_balances(connection)
    if connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        if os.environ.get("CAMPUSLOOP_DEMO_MODE") == "1":
            connection.execute(
                "INSERT INTO users(name,email,password_hash,role,balance,created_at) VALUES(?,?,?,?,?,?)",
                ("CampusLoop Admin", "admin@campusloop.demo", generate_password_hash("CampusLoop123!"), "admin", 0, utc_now()),
            )
            student = connection.execute(
                "INSERT INTO users(name,email,password_hash,role,balance,created_at) VALUES(?,?,?,?,?,?)",
                ("Aarav Student", "student@campusloop.demo", generate_password_hash("CampusLoop123!"), "student", 350, utc_now()),
            ).lastrowid
            connection.execute(
                "INSERT INTO ledger(user_id,entry_type,amount,reason,source_type,source_id,created_at) VALUES(?,?,?,?,?,?,?)",
                (student, "credit", 350, "Welcome demo balance", "demo_seed", "welcome", utc_now()),
            )
        else:
            admin_email = os.environ.get("CAMPUSLOOP_ADMIN_EMAIL", "").strip().lower()
            admin_password = os.environ.get("CAMPUSLOOP_ADMIN_PASSWORD", "")
            if bool(admin_email) != bool(admin_password):
                connection.close()
                raise RuntimeError("Set both CAMPUSLOOP_ADMIN_EMAIL and CAMPUSLOOP_ADMIN_PASSWORD to bootstrap an admin.")
            if admin_email:
                if "@" not in admin_email or len(admin_password) < 12:
                    connection.close()
                    raise RuntimeError("Bootstrap admin requires a valid email and password of at least 12 characters.")
                connection.execute(
                    "INSERT INTO users(name,email,password_hash,role,balance,created_at) VALUES(?,?,?,?,0,?)",
                    ("CampusLoop Admin", admin_email, generate_password_hash(admin_password), "admin", utc_now()),
                )
    if connection.execute("SELECT COUNT(*) FROM rewards").fetchone()[0] == 0:
        connection.executemany(
            "INSERT INTO rewards(name,description,token_price) VALUES(?,?,?)",
            [
                ("Demo smoothie", "A refreshing fruit smoothie.", 100),
                ("Masala chai", "Freshly brewed canteen chai.", 45),
                ("Veg sandwich", "Toasted seasonal vegetable sandwich.", 80),
                ("Fresh lime soda", "Chilled lime soda, sweet or salted.", 65),
            ],
        )
    if connection.execute("SELECT COUNT(*) FROM menu_items").fetchone()[0] == 0:
        connection.executemany(
            "INSERT INTO menu_items(name,description,token_price) VALUES(?,?,?)",
            [
                ("Veg sandwich", "Toasted seasonal vegetable sandwich.", 80),
                ("Masala chai", "Freshly brewed canteen chai.", 45),
                ("Fresh lime soda", "Chilled lime soda, sweet or salted.", 65),
                ("Demo smoothie", "A refreshing fruit smoothie.", 100),
                ("Poha bowl", "Warm poha with peanuts and lemon.", 55),
            ],
        )
    if connection.execute("SELECT COUNT(*) FROM activities").fetchone()[0] == 0:
        now = datetime.now(timezone.utc)
        seed = [
            ("Sustainable Campus Workshop", "Learn practical ways to reduce waste and energy use on campus.", "Workshop", now + timedelta(days=3), now + timedelta(days=3, hours=2), "Innovation Lab", "Student Green Council", "Register at the student desk; bring your campus ID.", 30),
            ("Inter-Department Design Sprint", "Teams prototype a solution to a student-life challenge.", "Competition", now + timedelta(days=7), now + timedelta(days=7, hours=5), "Design Studio", "CampusLoop Demo Team", "Form a team of 2-4 and sign up at the venue.", 75),
            ("Campus Fest Poster Jam", "Create bold artwork for the upcoming student festival.", "College Fest", now + timedelta(days=12), now + timedelta(days=12, hours=4), "Arts Quad", "Cultural Committee", "Bring a laptop or sketchbook; all skill levels welcome.", 50),
        ]
        connection.executemany(
            "INSERT INTO activities(title,description,category,start_at,end_at,venue,organizer,instructions,reward_tokens,is_sample) VALUES(?,?,?,?,?,?,?,?,?,1)",
            [(t, d, c, s.isoformat(), e.isoformat(), v, o, i, r) for t, d, c, s, e, v, o, i, r in seed],
        )
    connection.close()


def balance_from_ledger(connection, user_id):
    row = connection.execute(
        "SELECT COALESCE(SUM(CASE WHEN entry_type='credit' THEN amount ELSE -amount END),0) AS balance "
        "FROM ledger WHERE user_id=?",
        (user_id,),
    ).fetchone()
    return row["balance"]


def reconcile_legacy_balances(connection):
    connection.execute("BEGIN IMMEDIATE")
    try:
        for user in connection.execute("SELECT id,balance FROM users").fetchall():
            ledger_balance = balance_from_ledger(connection, user["id"])
            if ledger_balance != user["balance"]:
                difference = user["balance"] - ledger_balance
                direction = "credit" if difference > 0 else "debit"
                amount = abs(difference)
                reference = f"legacy-balance-user-{user['id']}"
                if not connection.execute(
                    "SELECT 1 FROM ledger WHERE source_type='legacy_balance_reconciliation' AND source_id=?",
                    (reference,),
                ).fetchone():
                    connection.execute(
                        "INSERT INTO ledger(user_id,entry_type,amount,reason,source_type,source_id,idempotency_key,created_at) "
                        "VALUES(?,?,?,?,?,?,?,?)",
                        (
                            user["id"], direction, amount,
                            "One-time migration reconciliation of the legacy token balance",
                            "legacy_balance_reconciliation", reference, reference, utc_now(),
                        ),
                    )
            connection.execute(
                "UPDATE users SET balance=? WHERE id=?",
                (balance_from_ledger(connection, user["id"]), user["id"]),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def error(message, status=400):
    return jsonify({"error": message}), status


def login_required(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return error("Please log in to continue.", 401)
        return function(*args, **kwargs)
    return wrapped


def admin_required(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return error("Please log in to continue.", 401)
        user = db().execute("SELECT role FROM users WHERE id=?", (session["user_id"],)).fetchone()
        if not user or user["role"] != "admin":
            return error("Admin access required.", 403)
        return function(*args, **kwargs)
    return wrapped


def current_user():
    return db().execute(
        "SELECT u.id,u.name,u.email,u.role,"
        "COALESCE(SUM(CASE WHEN l.entry_type='credit' THEN l.amount ELSE -l.amount END),0) AS balance "
        "FROM users u LEFT JOIN ledger l ON l.user_id=u.id WHERE u.id=? GROUP BY u.id",
        (session["user_id"],),
    ).fetchone()


def user_session_payload(user):
    payload = to_dict(user)
    payload["is_teacher"] = bool(db().execute(
        "SELECT 1 FROM teacher_assignments WHERE teacher_id=? LIMIT 1", (user["id"],)
    ).fetchone())
    return payload


def to_dict(row):
    return dict(row)


def ledger_change(connection, user_id, amount, direction, reason, source_type, source_id, idempotency_key=None):
    if direction not in {"credit", "debit"} or amount <= 0:
        raise ValueError("Invalid token transaction.")
    if not reason or not source_type or source_id is None:
        raise ValueError("Token transactions require a reason and unique reference.")
    if idempotency_key:
        prior = connection.execute(
            "SELECT id FROM ledger WHERE user_id=? AND idempotency_key=?", (user_id, idempotency_key)
        ).fetchone()
        if prior:
            return False
    user = connection.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        raise ValueError("Student account not found.")
    current_balance = balance_from_ledger(connection, user_id)
    new_balance = current_balance + amount if direction == "credit" else current_balance - amount
    if new_balance < 0:
        raise ValueError("Insufficient token balance.")
    cursor = connection.execute(
        "INSERT INTO ledger(user_id,entry_type,amount,reason,source_type,source_id,idempotency_key,created_at) VALUES(?,?,?,?,?,?,?,?)",
        (user_id, direction, amount, reason, source_type, str(source_id), idempotency_key, utc_now()),
    )
    connection.execute("UPDATE users SET balance=? WHERE id=?", (new_balance, user_id))
    return cursor.lastrowid


@app.errorhandler(413)
def upload_too_large(_error):
    return error("Artwork must be 5 MB or smaller.", 413)


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/session")
def session_info():
    user = current_user() if session.get("user_id") else None
    if not user:
        return jsonify({
            "user": None, "csrf_token": session.setdefault("csrf_token", secrets.token_urlsafe(24)),
            **token_conversion_json(),
        })
    return jsonify({
        "user": user_session_payload(user),
        "csrf_token": session.setdefault("csrf_token", secrets.token_urlsafe(24)),
        **token_conversion_json(),
    })


@app.before_request
def protect_mutations():
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.path.startswith("/api/"):
        token = request.headers.get("X-CSRF-Token")
        if not token or not secrets.compare_digest(token, session.get("csrf_token", "")):
            return error("Your session expired. Refresh the page and try again.", 400)


@app.post("/api/register")
def register():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    if not name or len(name) > 80 or "@" not in email or len(email) > 254 or len(password) < 8:
        return error("Enter a name, valid email, and password of at least 8 characters.")
    try:
        cursor = db().execute(
            "INSERT INTO users(name,email,password_hash,role,balance,created_at) VALUES(?,?,?,?,0,?)",
            (name, email, generate_password_hash(password), "student", utc_now()),
        )
    except sqlite3.IntegrityError:
        return error("An account with that email already exists.", 409)
    session.clear()
    session["user_id"] = cursor.lastrowid
    session["csrf_token"] = secrets.token_urlsafe(24)
    return jsonify({"user": user_session_payload(current_user()), "csrf_token": session["csrf_token"], **token_conversion_json()}), 201


@app.post("/api/login")
def login():
    data = request.get_json(silent=True) or {}
    user = db().execute("SELECT * FROM users WHERE email=?", (str(data.get("email", "")).strip().lower(),)).fetchone()
    if not user or not check_password_hash(user["password_hash"], str(data.get("password", ""))):
        return error("Email or password is incorrect.", 401)
    session.clear()
    session["user_id"] = user["id"]
    session["csrf_token"] = secrets.token_urlsafe(24)
    return jsonify({"user": user_session_payload(current_user()), "csrf_token": session["csrf_token"], **token_conversion_json()})


@app.post("/api/logout")
@login_required
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.get("/api/dashboard")
@login_required
def dashboard():
    user = current_user()
    transactions = db().execute(
        "SELECT entry_type,amount,reason,created_at FROM ledger WHERE user_id=? ORDER BY id DESC LIMIT 8",
        (user["id"],),
    ).fetchall()
    now_local = datetime.now(college_zone())
    week_start = (now_local.date() - timedelta(days=now_local.weekday())).isoformat()
    attendance_summary = attendance_stats_for_student(db(), user["id"], week_start)
    return jsonify({
        "user": to_dict(user),
        "recent_activity": [to_dict(x) for x in transactions],
        "balance_value_paise": reward_value_paise(user["balance"]),
        "conversion_tokens": 100,
        "conversion_rupees": 10,
        "attendance": attendance_summary,
    })


@app.get("/api/ledger")
@login_required
def ledger_history():
    rows = db().execute(
        "SELECT entry_type,amount,reason,created_at FROM ledger WHERE user_id=? ORDER BY id DESC LIMIT 100",
        (session["user_id"],),
    ).fetchall()
    return jsonify([{**to_dict(row), "amount_value_paise": reward_value_paise(row["amount"])} for row in rows])


def attendance_stats_for_student(connection, student_id, week_start):
    start_utc, end_utc, week_end = attendance_week(week_start)
    local_now = datetime.now(college_zone())
    week_complete = local_now >= datetime.fromisoformat(end_utc).astimezone(college_zone())
    rows = connection.execute(
        "SELECT s.id AS session_id,s.starts_at,s.ends_at,s.finalized,sc.name AS class_name,"
        "su.name AS subject_name,cs.name AS section_name,c.name AS course_name,ar.id AS attendance_id,ar.status "
        "FROM student_enrollments e JOIN course_sections cs ON cs.id=e.section_id "
        "JOIN courses c ON c.id=cs.course_id JOIN scheduled_classes sc ON sc.section_id=cs.id "
        "JOIN subjects su ON su.id=sc.subject_id JOIN class_sessions s ON s.class_id=sc.id "
        "LEFT JOIN attendance_records ar ON ar.session_id=s.id AND ar.student_id=e.student_id "
        "WHERE e.student_id=? AND s.starts_at>=? AND s.starts_at<? ORDER BY s.starts_at,sc.name",
        (student_id, start_utc, end_utc),
    ).fetchall()
    held = len(rows)
    attended = sum(1 for row in rows if row["status"] == "Present")
    percentage = round((attended * 100.0 / held), 2) if held else 0.0
    finalized = bool(held) and all(row["finalized"] and row["attendance_id"] is not None for row in rows)
    eligible = week_complete and finalized
    try:
        tier = attendance_reward_tier(percentage) if held else 0
    except ValueError:
        tier = 0
    next_threshold = next((threshold for threshold in (70, 80, 90, 101) if percentage < threshold), None)
    return {
        "week_start": week_start,
        "week_end": week_end,
        "timezone": COLLEGE_TIMEZONE,
        "percentage": percentage,
        "sessions_attended": attended,
        "sessions_held": held,
        "tier_preview_tokens": tier,
        "eligible_reward_tokens": tier if eligible else 0,
        "next_threshold": next_threshold if next_threshold != 101 else None,
        "week_complete": week_complete,
        "all_sessions_finalized": finalized,
        "eligible_for_processing": eligible,
        "records": [to_dict(row) for row in rows],
    }


def assigned_teacher(connection, teacher_id, class_id):
    return connection.execute(
        "SELECT 1 FROM teacher_assignments WHERE teacher_id=? AND class_id=?",
        (teacher_id, class_id),
    ).fetchone() is not None


def can_manage_class(connection, user_id, class_id):
    role = connection.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
    return bool(role and (role["role"] == "admin" or assigned_teacher(connection, user_id, class_id)))


def attendance_admin_report(connection, week_start):
    start_utc, end_utc, _week_end = attendance_week(week_start)
    local_now = datetime.now(college_zone())
    complete = local_now >= datetime.fromisoformat(end_utc).astimezone(college_zone())
    enrollments = connection.execute(
        "SELECT DISTINCT u.id AS student_id,u.name,u.email FROM users u "
        "JOIN student_enrollments e ON e.student_id=u.id ORDER BY u.name"
    ).fetchall()
    results = []
    for student in enrollments:
        stats = attendance_stats_for_student(connection, student["student_id"], week_start)
        issued = connection.execute(
            "SELECT * FROM weekly_attendance_rewards WHERE student_id=? AND week_start=?",
            (student["student_id"], week_start),
        ).fetchone()
        adjustments = connection.execute(
            "SELECT COALESCE(SUM(delta_tokens),0) AS delta FROM attendance_reward_adjustments "
            "WHERE student_id=? AND week_start=?",
            (student["student_id"], week_start),
        ).fetchone()["delta"]
        results.append({
            "student_id": student["student_id"],
            "student_name": student["name"],
            "student_email": student["email"],
            "percentage": stats["percentage"],
            "sessions_attended": stats["sessions_attended"],
            "sessions_held": stats["sessions_held"],
            "tier_preview_tokens": stats["tier_preview_tokens"],
            "eligible_reward_tokens": stats["eligible_reward_tokens"],
            "eligible_for_processing": stats["eligible_for_processing"],
            "status": (
                ("Already issued" if issued["reward_tokens"] else "Not eligible (processed)") if issued else
                "Incomplete" if not stats["eligible_for_processing"] else
                "Eligible" if stats["eligible_reward_tokens"] else
                "Not eligible"
            ),
            "issued_reward_tokens": issued["reward_tokens"] if issued else None,
            "current_reward_tokens": issued["reward_tokens"] + adjustments if issued else None,
            "week_start": week_start,
        })
    return {
        "week_start": week_start,
        "timezone": COLLEGE_TIMEZONE,
        "week_complete": complete,
        "week_end_local": (date.fromisoformat(week_start) + timedelta(days=7)).isoformat(),
        "students": results,
    }


@app.get("/api/attendance/me")
@login_required
def my_attendance():
    local_today = datetime.now(college_zone()).date()
    current_week = (local_today - timedelta(days=local_today.weekday())).isoformat()
    selected_week = request.args.get("week_start", current_week)
    stats = attendance_stats_for_student(db(), session["user_id"], selected_week)
    current_records = [
        {**to_dict(row), "status": row["status"] or "Not recorded"}
        for row in stats.pop("records")
    ]
    history = db().execute(
        "SELECT w.*,COALESCE(SUM(a.delta_tokens),0) AS adjustment_delta "
        "FROM weekly_attendance_rewards w LEFT JOIN attendance_reward_adjustments a "
        "ON a.student_id=w.student_id AND a.week_start=w.week_start "
        "WHERE w.student_id=? GROUP BY w.id ORDER BY w.week_start DESC",
        (session["user_id"],),
    ).fetchall()
    records = db().execute(
        "SELECT ar.id AS attendance_id,ar.status,ar.recorded_at,s.starts_at,s.finalized,"
        "sc.name AS class_name,su.name AS subject_name,cs.name AS section_name,c.name AS course_name "
        "FROM attendance_records ar JOIN class_sessions s ON s.id=ar.session_id "
        "JOIN scheduled_classes sc ON sc.id=s.class_id JOIN course_sections cs ON cs.id=sc.section_id "
        "JOIN courses c ON c.id=cs.course_id JOIN subjects su ON su.id=sc.subject_id "
        "WHERE ar.student_id=? ORDER BY s.starts_at DESC",
        (session["user_id"],),
    ).fetchall()
    weekly_history = []
    for row in history:
        item = to_dict(row)
        item["current_reward_tokens"] = item["reward_tokens"] + item.pop("adjustment_delta")
        weekly_history.append(item)
    return jsonify({
        "current_week": stats,
        "current_week_records": current_records,
        "history": weekly_history,
        "class_records": [to_dict(row) for row in records],
        "timezone": COLLEGE_TIMEZONE,
        "conversion_tokens": 100,
        "conversion_rupees": 10,
    })


@app.post("/api/admin/classes")
@admin_required
def admin_create_class():
    data = request.get_json(silent=True) or {}
    fields = [str(data.get(key, "")).strip() for key in ("course", "section", "subject", "class_name")]
    if any(not value or len(value) > 100 for value in fields):
        return error("Enter a course, section, subject, and class name.")
    connection = db()
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("INSERT INTO courses(name) VALUES(?) ON CONFLICT(name) DO NOTHING", (fields[0],))
        course_id = connection.execute("SELECT id FROM courses WHERE name=?", (fields[0],)).fetchone()["id"]
        connection.execute(
            "INSERT INTO course_sections(course_id,name) VALUES(?,?) ON CONFLICT(course_id,name) DO NOTHING",
            (course_id, fields[1]),
        )
        section_id = connection.execute(
            "SELECT id FROM course_sections WHERE course_id=? AND name=?", (course_id, fields[1])
        ).fetchone()["id"]
        connection.execute(
            "INSERT INTO subjects(section_id,name) VALUES(?,?) ON CONFLICT(section_id,name) DO NOTHING",
            (section_id, fields[2]),
        )
        subject_id = connection.execute(
            "SELECT id FROM subjects WHERE section_id=? AND name=?", (section_id, fields[2])
        ).fetchone()["id"]
        connection.execute(
            "INSERT INTO scheduled_classes(section_id,subject_id,name) VALUES(?,?,?) "
            "ON CONFLICT(section_id,subject_id) DO UPDATE SET name=excluded.name",
            (section_id, subject_id, fields[3]),
        )
        class_id = connection.execute(
            "SELECT id FROM scheduled_classes WHERE section_id=? AND subject_id=?", (section_id, subject_id)
        ).fetchone()["id"]
        connection.commit()
    except sqlite3.IntegrityError as exc:
        connection.rollback()
        return error(str(exc), 409)
    return jsonify({"id": class_id}), 201


@app.post("/api/admin/enrollments")
@admin_required
def admin_enroll_student():
    data = request.get_json(silent=True) or {}
    section_id, student_id = data.get("section_id"), data.get("student_id")
    if not isinstance(section_id, int) or not isinstance(student_id, int):
        return error("Choose a course section and student.")
    connection = db()
    student = connection.execute("SELECT id FROM users WHERE id=? AND role='student'", (student_id,)).fetchone()
    section = connection.execute("SELECT id FROM course_sections WHERE id=?", (section_id,)).fetchone()
    if not student or not section:
        return error("The selected student or section does not exist.", 404)
    try:
        connection.execute(
            "INSERT INTO student_enrollments(section_id,student_id,created_at) VALUES(?,?,?)",
            (section_id, student_id, utc_now()),
        )
    except sqlite3.IntegrityError:
        return error("This student is already enrolled in that section.", 409)
    return jsonify({"ok": True}), 201


@app.post("/api/admin/teacher-assignments")
@admin_required
def admin_assign_teacher():
    data = request.get_json(silent=True) or {}
    class_id, teacher_id = data.get("class_id"), data.get("teacher_id")
    if not isinstance(class_id, int) or not isinstance(teacher_id, int):
        return error("Choose a class and teacher account.")
    connection = db()
    if not connection.execute("SELECT 1 FROM scheduled_classes WHERE id=?", (class_id,)).fetchone():
        return error("Class not found.", 404)
    if not connection.execute("SELECT 1 FROM users WHERE id=? AND role='student'", (teacher_id,)).fetchone():
        return error("Teacher must be an existing student account.", 404)
    try:
        connection.execute(
            "INSERT INTO teacher_assignments(class_id,teacher_id,assigned_at) VALUES(?,?,?)",
            (class_id, teacher_id, utc_now()),
        )
    except sqlite3.IntegrityError:
        return error("This teacher is already assigned to that class.", 409)
    return jsonify({"ok": True}), 201


@app.post("/api/admin/sessions")
@admin_required
def admin_schedule_class_session():
    data = request.get_json(silent=True) or {}
    class_id = data.get("class_id")
    if not isinstance(class_id, int):
        return error("Choose a class.")
    try:
        start = datetime.fromisoformat(str(data.get("starts_at", "")).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(data.get("ends_at", "")).replace("Z", "+00:00"))
        if start.utcoffset() is None:
            start = start.replace(tzinfo=college_zone())
        if end.utcoffset() is None:
            end = end.replace(tzinfo=college_zone())
        if start >= end:
            return error("Class session end must be after its start.")
        starts_at = start.astimezone(timezone.utc).replace(microsecond=0).isoformat()
        ends_at = end.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    except ValueError:
        return error("Enter valid class start and end timestamps.")
    if not db().execute("SELECT 1 FROM scheduled_classes WHERE id=?", (class_id,)).fetchone():
        return error("Class not found.", 404)
    try:
        cursor = db().execute(
            "INSERT INTO class_sessions(class_id,starts_at,ends_at,created_by,created_at) VALUES(?,?,?,?,?)",
            (class_id, starts_at, ends_at, session["user_id"], utc_now()),
        )
    except sqlite3.IntegrityError:
        return error("A session already exists for this class at that start time.", 409)
    return jsonify({"id": cursor.lastrowid}), 201


@app.get("/api/admin/attendance")
@admin_required
def admin_attendance_report():
    local_today = datetime.now(college_zone()).date()
    current_monday = local_today - timedelta(days=local_today.weekday())
    default_week = (current_monday - timedelta(days=7)).isoformat()
    week_start = request.args.get("week_start", default_week)
    try:
        return jsonify(attendance_admin_report(db(), week_start))
    except ValueError as exc:
        return error(str(exc))


@app.get("/api/teacher/sessions")
@login_required
def teacher_sessions():
    connection = db()
    user = connection.execute("SELECT role FROM users WHERE id=?", (session["user_id"],)).fetchone()
    if not user or (
        user["role"] != "admin"
        and not connection.execute(
            "SELECT 1 FROM teacher_assignments WHERE teacher_id=? LIMIT 1", (session["user_id"],)
        ).fetchone()
    ):
        return error("Teacher access required.", 403)
    rows = connection.execute(
        "SELECT s.id AS session_id,s.starts_at,s.ends_at,s.finalized,sc.id AS class_id,sc.name AS class_name,"
        "cs.name AS section_name,c.name AS course_name,su.name AS subject_name "
        "FROM class_sessions s JOIN scheduled_classes sc ON sc.id=s.class_id "
        "JOIN course_sections cs ON cs.id=sc.section_id JOIN courses c ON c.id=cs.course_id "
        "JOIN subjects su ON su.id=sc.subject_id "
        "WHERE ?='admin' OR EXISTS(SELECT 1 FROM teacher_assignments ta WHERE ta.class_id=sc.id AND ta.teacher_id=?) "
        "ORDER BY s.starts_at DESC",
        (user["role"], session["user_id"]),
    ).fetchall()
    result = []
    for row in rows:
        item = to_dict(row)
        item["students"] = [
            to_dict(student) for student in connection.execute(
                "SELECT u.id AS student_id,u.name,ar.id AS attendance_id,ar.status "
                "FROM student_enrollments e JOIN users u ON u.id=e.student_id "
                "LEFT JOIN attendance_records ar ON ar.student_id=u.id AND ar.session_id=? "
                "JOIN scheduled_classes sc ON sc.id=? "
                "WHERE e.section_id=sc.section_id ORDER BY u.name",
                (row["session_id"], row["class_id"]),
            ).fetchall()
        ]
        result.append(item)
    return jsonify(result)


@app.post("/api/teacher/sessions/<int:session_id>/attendance")
@login_required
def teacher_record_attendance(session_id):
    data = request.get_json(silent=True) or {}
    records = data.get("records")
    if not isinstance(records, list) or not records:
        return error("Submit at least one attendance record.")
    connection = db()
    try:
        connection.execute("BEGIN IMMEDIATE")
        class_session = connection.execute(
            "SELECT * FROM class_sessions WHERE id=?", (session_id,)
        ).fetchone()
        if not class_session:
            connection.rollback()
            return error("Class session not found.", 404)
        if not can_manage_class(connection, session["user_id"], class_session["class_id"]):
            connection.rollback()
            return error("You are not assigned to this class.", 403)
        if class_session["finalized"]:
            connection.rollback()
            return error("This attendance session is finalized. Use an audited correction.", 409)
        enrolled_ids = {
            row["student_id"] for row in connection.execute(
                "SELECT e.student_id FROM student_enrollments e JOIN scheduled_classes sc "
                "ON sc.section_id=e.section_id WHERE sc.id=?",
                (class_session["class_id"],),
            ).fetchall()
        }
        seen = set()
        for record in records:
            if not isinstance(record, dict) or not isinstance(record.get("student_id"), int):
                connection.rollback()
                return error("Each record must identify an enrolled student.")
            student_id, status = record["student_id"], record.get("status")
            if student_id not in enrolled_ids or student_id in seen or status not in {"Present", "Absent"}:
                connection.rollback()
                return error("Attendance includes a duplicate, non-enrolled student, or invalid status.")
            seen.add(student_id)
            connection.execute(
                "INSERT INTO attendance_records(session_id,student_id,status,recorded_by,recorded_at) VALUES(?,?,?,?,?)",
                (session_id, student_id, status, session["user_id"], utc_now()),
            )
        connection.commit()
    except sqlite3.IntegrityError:
        connection.rollback()
        return error("Attendance already exists for a student in this session.", 409)
    return jsonify({"ok": True, "records_saved": len(records)})


@app.post("/api/teacher/sessions/<int:session_id>/finalize")
@login_required
def teacher_finalize_attendance(session_id):
    connection = db()
    try:
        connection.execute("BEGIN IMMEDIATE")
        class_session = connection.execute(
            "SELECT * FROM class_sessions WHERE id=?", (session_id,)
        ).fetchone()
        if not class_session:
            connection.rollback()
            return error("Class session not found.", 404)
        if not can_manage_class(connection, session["user_id"], class_session["class_id"]):
            connection.rollback()
            return error("You are not assigned to this class.", 403)
        if class_session["finalized"]:
            connection.rollback()
            return error("This session is already finalized.", 409)
        enrolled_count = connection.execute(
            "SELECT COUNT(*) AS count FROM student_enrollments e JOIN scheduled_classes sc "
            "ON sc.section_id=e.section_id WHERE sc.id=?",
            (class_session["class_id"],),
        ).fetchone()["count"]
        attendance_count = connection.execute(
            "SELECT COUNT(*) AS count FROM attendance_records WHERE session_id=?", (session_id,)
        ).fetchone()["count"]
        if not enrolled_count or attendance_count != enrolled_count:
            connection.rollback()
            return error("Record Present or Absent for every enrolled student before finalizing.")
        connection.execute("UPDATE class_sessions SET finalized=1 WHERE id=?", (session_id,))
        connection.commit()
    except sqlite3.Error as exc:
        connection.rollback()
        return error(f"Could not finalize attendance: {exc}", 409)
    return jsonify({"ok": True, "finalized": True})


@app.patch("/api/teacher/attendance/<int:attendance_id>")
@login_required
def correct_attendance(attendance_id):
    data = request.get_json(silent=True) or {}
    new_status = data.get("status")
    reason = str(data.get("reason", "")).strip()
    if new_status not in {"Present", "Absent"} or not reason or len(reason) > 500:
        return error("Choose Present or Absent and provide a correction reason (max 500 characters).")
    connection = db()
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT ar.*,s.class_id FROM attendance_records ar JOIN class_sessions s ON s.id=ar.session_id "
            "WHERE ar.id=?",
            (attendance_id,),
        ).fetchone()
        if not row:
            connection.rollback()
            return error("Attendance record not found.", 404)
        if not can_manage_class(connection, session["user_id"], row["class_id"]):
            connection.rollback()
            return error("You are not assigned to this class.", 403)
        if row["status"] == new_status:
            connection.rollback()
            return error("The record already has that attendance status.", 409)
        connection.execute(
            "INSERT INTO attendance_corrections(attendance_id,previous_status,corrected_status,reason,corrected_by,corrected_at) "
            "VALUES(?,?,?,?,?,?)",
            (attendance_id, row["status"], new_status, reason, session["user_id"], utc_now()),
        )
        connection.execute(
            "UPDATE attendance_records SET status=?,recorded_by=?,recorded_at=? WHERE id=?",
            (new_status, session["user_id"], utc_now(), attendance_id),
        )
        connection.commit()
    except sqlite3.Error as exc:
        connection.rollback()
        return error(f"Could not correct attendance: {exc}", 409)
    return jsonify({"ok": True, "status": new_status, "audit_logged": True})


@app.post("/api/admin/attendance/process-week")
@admin_required
def admin_process_attendance_week():
    data = request.get_json(silent=True) or {}
    week_start = str(data.get("week_start", ""))
    try:
        report = attendance_admin_report(db(), week_start)
    except ValueError as exc:
        return error(str(exc))
    if not report["week_complete"]:
        return error("Attendance rewards can only be processed after the college-local week is complete.", 409)
    connection = db()
    issued, skipped = [], []
    try:
        connection.execute("BEGIN IMMEDIATE")
        for student in report["students"]:
            student_id = student["student_id"]
            if connection.execute(
                "SELECT 1 FROM weekly_attendance_rewards WHERE student_id=? AND week_start=?",
                (student_id, week_start),
            ).fetchone():
                skipped.append(student_id)
                continue
            stats = attendance_stats_for_student(connection, student_id, week_start)
            if not stats["eligible_for_processing"]:
                skipped.append(student_id)
                continue
            reward = attendance_reward_tier(stats["percentage"])
            status = "Issued" if reward else "Not eligible"
            cursor = connection.execute(
                "INSERT INTO weekly_attendance_rewards(student_id,week_start,week_end,attendance_percentage,"
                "sessions_attended,sessions_held,reward_tokens,status,issued_by,issued_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    student_id, week_start, stats["week_end"], stats["percentage"],
                    stats["sessions_attended"], stats["sessions_held"], reward, status,
                    session["user_id"], utc_now(),
                ),
            )
            if reward:
                reason = f"Weekly Attendance Bonus — {stats['percentage']:g}% — +{reward} tokens"
                ledger_change(
                    connection, student_id, reward, "credit", reason,
                    "weekly_attendance_bonus", f"{student_id}:{week_start}",
                    f"weekly-attendance:{student_id}:{week_start}",
                )
            issued.append({"student_id": student_id, "percentage": stats["percentage"], "reward_tokens": reward})
        connection.commit()
    except (ValueError, sqlite3.IntegrityError, sqlite3.Error) as exc:
        connection.rollback()
        return error(f"Weekly attendance processing rolled back: {exc}", 409)
    return jsonify({"ok": True, "week_start": week_start, "issued": issued, "skipped_student_ids": skipped})


@app.post("/api/admin/attendance/rewards/<int:student_id>/<week_start>/adjust")
@admin_required
def admin_adjust_attendance_reward(student_id, week_start):
    data = request.get_json(silent=True) or {}
    reason = str(data.get("reason", "")).strip()
    request_key = str(data.get("idempotency_key", "")).strip()
    if not reason or len(reason) > 500 or not request_key or len(request_key) > 100:
        return error("Provide an adjustment reason and a valid idempotency key.")
    connection = db()
    try:
        connection.execute("BEGIN IMMEDIATE")
        prior = connection.execute(
            "SELECT * FROM attendance_reward_adjustments WHERE student_id=? AND week_start=? AND request_key=?",
            (student_id, week_start, request_key),
        ).fetchone()
        if prior:
            connection.commit()
            return jsonify({"ok": True, "duplicate": True, **to_dict(prior)})
        issued = connection.execute(
            "SELECT * FROM weekly_attendance_rewards WHERE student_id=? AND week_start=?",
            (student_id, week_start),
        ).fetchone()
        if not issued:
            connection.rollback()
            return error("This student's completed week has no processed reward to adjust.", 404)
        stats = attendance_stats_for_student(connection, student_id, week_start)
        if not stats["eligible_for_processing"]:
            connection.rollback()
            return error("The corrected attendance week is incomplete or not fully finalized.", 409)
        corrected_reward = attendance_reward_tier(stats["percentage"])
        adjustments = connection.execute(
            "SELECT COALESCE(SUM(delta_tokens),0) AS delta FROM attendance_reward_adjustments "
            "WHERE student_id=? AND week_start=?",
            (student_id, week_start),
        ).fetchone()["delta"]
        previous_reward = issued["reward_tokens"] + adjustments
        delta = corrected_reward - previous_reward
        reference = str(uuid4())
        ledger_id = None
        if delta:
            ledger_id = ledger_change(
                connection, student_id, abs(delta), "credit" if delta > 0 else "debit",
                f"Attendance correction adjustment — week {week_start} — {reason}",
                "attendance_reward_adjustment", reference, f"attendance-adjustment:{reference}",
            )
        cursor = connection.execute(
            "INSERT INTO attendance_reward_adjustments(reference,student_id,week_start,previous_percentage,"
            "corrected_percentage,previous_reward,corrected_reward,delta_tokens,reason,request_key,adjusted_by,ledger_id,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                reference, student_id, week_start, issued["attendance_percentage"],
                stats["percentage"], previous_reward, corrected_reward, delta, reason,
                request_key, session["user_id"], ledger_id, utc_now(),
            ),
        )
        adjustment = connection.execute(
            "SELECT * FROM attendance_reward_adjustments WHERE id=?", (cursor.lastrowid,)
        ).fetchone()
        connection.commit()
    except (ValueError, sqlite3.IntegrityError, sqlite3.Error) as exc:
        connection.rollback()
        return error(f"Attendance reward adjustment rolled back: {exc}", 409)
    return jsonify({"ok": True, **to_dict(adjustment)})


@app.get("/api/rewards")
@login_required
def rewards():
    rows = db().execute("SELECT * FROM rewards WHERE active=1 ORDER BY token_price").fetchall()
    return jsonify([{**to_dict(row), "reward_value_paise": reward_value_paise(row["token_price"])} for row in rows])


@app.post("/api/rewards/<int:reward_id>/redeem")
@login_required
def redeem_reward(reward_id):
    data = request.get_json(silent=True) or {}
    key = str(data.get("idempotency_key", "")).strip()
    if not key or len(key) > 100:
        return error("A valid redemption request key is required.")
    connection = db()
    try:
        connection.execute("BEGIN IMMEDIATE")
        reward = connection.execute("SELECT * FROM rewards WHERE id=? AND active=1", (reward_id,)).fetchone()
        if not reward:
            connection.rollback()
            return error("That reward is no longer available.", 404)
        changed = ledger_change(
            connection, session["user_id"], reward["token_price"], "debit",
            f"Redeemed: {reward['name']}", "reward_redemption", key, key,
        )
        if not changed:
            connection.rollback()
            return error("This redemption request was already processed.", 409)
        connection.commit()
    except (ValueError, sqlite3.IntegrityError) as exc:
        connection.rollback()
        return error(str(exc) or "This redemption request was already processed.", 409)
    return jsonify({"ok": True, "balance": current_user()["balance"]})


@app.get("/api/menu")
@login_required
def menu():
    rows = db().execute("SELECT * FROM menu_items WHERE active=1 ORDER BY name").fetchall()
    return jsonify([{**to_dict(row), "token_value_paise": reward_value_paise(row["token_price"])} for row in rows])


@app.post("/api/orders")
@login_required
def place_order():
    data = request.get_json(silent=True) or {}
    key = str(data.get("idempotency_key", "")).strip()
    lines = data.get("items")
    if not key or len(key) > 100 or not isinstance(lines, list) or not lines or len(lines) > 20:
        return error("Add menu items and submit a valid order.")
    normalized = {}
    for line in lines:
        if not isinstance(line, dict) or not str(line.get("quantity", "")).isdigit():
            return error("Order quantities must be whole numbers.")
        item_id = line.get("item_id")
        quantity = int(line["quantity"])
        if not isinstance(item_id, int) or quantity < 1 or quantity > 20:
            return error("Order quantities must be between 1 and 20.")
        normalized[item_id] = normalized.get(item_id, 0) + quantity
    connection = db()
    try:
        connection.execute("BEGIN IMMEDIATE")
        if connection.execute("SELECT 1 FROM orders WHERE user_id=? AND idempotency_key=?", (session["user_id"], key)).fetchone():
            connection.rollback()
            return error("This order request was already processed.", 409)
        items = []
        for item_id, quantity in normalized.items():
            item = connection.execute("SELECT * FROM menu_items WHERE id=? AND active=1", (item_id,)).fetchone()
            if not item:
                connection.rollback()
                return error("A selected menu item is unavailable.", 404)
            items.append((item, quantity))
        total = sum(item["token_price"] * quantity for item, quantity in items)
        order_id = str(uuid4())
        connection.execute(
            "INSERT INTO orders(id,user_id,token_cost,status,idempotency_key,created_at) VALUES(?,?,?,'Pending',?,?)",
            (order_id, session["user_id"], total, key, utc_now()),
        )
        for item, quantity in items:
            connection.execute(
                "INSERT INTO order_items(order_id,menu_item_id,item_name,quantity,unit_token_price) VALUES(?,?,?,?,?)",
                (order_id, item["id"], item["name"], quantity, item["token_price"]),
            )
        ledger_change(
            connection, session["user_id"], total, "debit", f"Canteen order {order_id[:8]}",
            "canteen_order", order_id, f"order:{key}",
        )
        connection.commit()
    except (ValueError, sqlite3.IntegrityError) as exc:
        connection.rollback()
        return error(str(exc) or "This order request was already processed.", 409)
    return jsonify({
        "id": order_id, "status": "Pending", "token_cost": total,
        "token_cost_value_paise": reward_value_paise(total),
        "balance": current_user()["balance"],
    }), 201


def order_json(row):
    order = to_dict(row)
    order["token_cost_value_paise"] = reward_value_paise(order["token_cost"])
    order["items"] = [
        {**to_dict(item), "unit_value_paise": reward_value_paise(item["unit_token_price"])}
        for item in db().execute(
            "SELECT item_name,quantity,unit_token_price FROM order_items WHERE order_id=? ORDER BY id", (order["id"],)
        ).fetchall()
    ]
    return order


@app.get("/api/orders")
@login_required
def my_orders():
    rows = db().execute("SELECT * FROM orders WHERE user_id=? ORDER BY created_at DESC", (session["user_id"],)).fetchall()
    return jsonify([order_json(row) for row in rows])


@app.post("/api/orders/<order_id>/cancel")
@login_required
def cancel_order(order_id):
    connection = db()
    try:
        connection.execute("BEGIN IMMEDIATE")
        order = connection.execute(
            "SELECT * FROM orders WHERE id=? AND user_id=?", (order_id, session["user_id"])
        ).fetchone()
        if not order:
            connection.rollback()
            return error("Order not found.", 404)
        if order["status"] != "Pending":
            connection.rollback()
            return error("Only pending orders can be cancelled and refunded.", 409)
        changed = connection.execute(
            "UPDATE orders SET status='Cancelled' WHERE id=? AND status='Pending'", (order_id,)
        ).rowcount
        if changed != 1:
            connection.rollback()
            return error("This order can no longer be cancelled.", 409)
        ledger_change(
            connection, session["user_id"], order["token_cost"], "credit",
            f"Refund: cancelled order {order_id[:8]}", "order_refund", order_id,
        )
        connection.commit()
    except (ValueError, sqlite3.IntegrityError) as exc:
        connection.rollback()
        return error(str(exc), 409)
    return jsonify({"ok": True, "balance": current_user()["balance"]})


def activity_state(start_at, end_at):
    now = datetime.now(timezone.utc)
    start = datetime.fromisoformat(start_at.replace("Z", "+00:00"))
    end = datetime.fromisoformat(end_at.replace("Z", "+00:00"))
    if now < start:
        return "Upcoming"
    if now <= end:
        return "Ongoing"
    return "Completed"


@app.get("/api/activities")
@login_required
def activities():
    query = str(request.args.get("q", "")).strip()[:100]
    category = str(request.args.get("category", "")).strip()[:40]
    rows = db().execute(
        "SELECT a.*, p.status AS participation_status FROM activities a "
        "LEFT JOIN activity_participations p ON p.activity_id=a.id AND p.user_id=? ORDER BY a.start_at",
        (session["user_id"],),
    ).fetchall()
    result = []
    for row in rows:
        item = to_dict(row)
        item["state"] = activity_state(item["start_at"], item["end_at"])
        if item["state"] in {"Upcoming", "Ongoing"} and (
            (not query or query.casefold() in " ".join(str(item[k]) for k in ("title", "description", "venue", "organizer")).casefold())
            and (not category or item["category"] == category)
        ):
            result.append(item)
    return jsonify(result)


@app.post("/api/activities/<int:activity_id>/participate")
@login_required
def participate(activity_id):
    connection = db()
    activity = connection.execute("SELECT * FROM activities WHERE id=?", (activity_id,)).fetchone()
    if not activity:
        return error("Activity not found.", 404)
    if activity_state(activity["start_at"], activity["end_at"]) == "Completed":
        return error("This activity has already ended.", 409)
    try:
        connection.execute(
            "INSERT INTO activity_participations(activity_id,user_id,status,created_at) VALUES(?,?,'Pending Review',?)",
            (activity_id, session["user_id"], utc_now()),
        )
    except sqlite3.IntegrityError:
        return error("You have already submitted participation for this activity.", 409)
    return jsonify({"status": "Pending Review"}), 201


@app.post("/api/submissions")
@login_required
def submit_artwork():
    file = request.files.get("image")
    title = str(request.form.get("title", "")).strip()
    description = str(request.form.get("description", "")).strip()
    category = str(request.form.get("category", "")).strip()
    if not title or len(title) > 100 or not description or len(description) > 1000 or category not in {"Event Poster", "Canteen Promotion", "Banner"}:
        return error("Enter a title, description, and valid artwork category.")
    if not file or not file.filename or "." not in file.filename:
        return error("Choose a PNG, JPG, or WebP image.")
    extension = file.filename.rsplit(".", 1)[1].lower()
    if extension not in ALLOWED_EXTENSIONS:
        return error("Only PNG, JPG, and WebP images are allowed.")
    header = file.stream.read(12)
    file.stream.seek(0)
    valid_image = (
        (extension == "png" and header.startswith(b"\x89PNG\r\n\x1a\n"))
        or (extension in {"jpg", "jpeg"} and header.startswith(b"\xff\xd8\xff"))
        or (extension == "webp" and header[:4] == b"RIFF" and header[8:12] == b"WEBP")
    )
    if not valid_image:
        return error("The selected file contents do not match a supported image type.")
    filename = f"{uuid4().hex}.{extension}"
    file.save(UPLOAD_DIR / filename)
    submission_id = str(uuid4())
    db().execute(
        "INSERT INTO submissions(id,user_id,title,description,category,image_filename,status,reward_tokens,created_at) VALUES(?,?,?,?,?,?,'Pending Review',0,?)",
        (submission_id, session["user_id"], title, description, category, filename, utc_now()),
    )
    return jsonify({"id": submission_id, "status": "Pending Review"}), 201


@app.get("/api/submissions")
@login_required
def my_submissions():
    rows = db().execute(
        "SELECT id,title,description,category,image_filename,status,reward_tokens,created_at,reviewed_at FROM submissions WHERE user_id=? ORDER BY created_at DESC",
        (session["user_id"],),
    ).fetchall()
    return jsonify([{**to_dict(row), "image_url": f"/uploads/{row['image_filename']}"} for row in rows])


@app.get("/uploads/<path:filename>")
@login_required
def uploaded_artwork(filename):
    user = current_user()
    if user["role"] != "admin" and not db().execute(
        "SELECT 1 FROM submissions WHERE user_id=? AND image_filename=?", (user["id"], filename)
    ).fetchone():
        return error("Artwork not found.", 404)
    if user["role"] == "admin" and not db().execute(
        "SELECT 1 FROM submissions WHERE image_filename=?", (filename,)
    ).fetchone():
        return error("Artwork not found.", 404)
    return send_from_directory(UPLOAD_DIR, filename)


@app.get("/api/admin/overview")
@admin_required
def admin_overview():
    return jsonify({
        "orders": [order_json(row) for row in db().execute("SELECT * FROM orders ORDER BY created_at DESC LIMIT 100").fetchall()],
        "submissions": [
            {**to_dict(row), "student_name": row["student_name"], "image_url": f"/uploads/{row['image_filename']}"}
            for row in db().execute(
                "SELECT s.*,u.name AS student_name FROM submissions s JOIN users u ON u.id=s.user_id ORDER BY s.created_at DESC"
            ).fetchall()
        ],
        "activities": [to_dict(row) for row in db().execute("SELECT * FROM activities ORDER BY start_at DESC").fetchall()],
        "participations": [
            to_dict(row) for row in db().execute(
                "SELECT p.*,a.title AS activity_title,a.reward_tokens AS configured_reward,u.name AS student_name FROM activity_participations p "
                "JOIN activities a ON a.id=p.activity_id JOIN users u ON u.id=p.user_id ORDER BY p.created_at DESC"
            ).fetchall()
        ],
        "rewards": [
            {**to_dict(row), "reward_value_paise": reward_value_paise(row["token_price"])}
            for row in db().execute("SELECT * FROM rewards ORDER BY token_price").fetchall()
        ],
        "menu": [to_dict(row) for row in db().execute("SELECT * FROM menu_items ORDER BY name").fetchall()],
        "contribution_reward": int(db().execute("SELECT value FROM settings WHERE key='contribution_reward'").fetchone()[0]),
        "attendance_classes": [to_dict(row) for row in db().execute(
            "SELECT sc.id,sc.section_id,sc.name AS class_name,cs.name AS section_name,c.name AS course_name,su.name AS subject_name "
            "FROM scheduled_classes sc JOIN course_sections cs ON cs.id=sc.section_id "
            "JOIN courses c ON c.id=cs.course_id JOIN subjects su ON su.id=sc.subject_id ORDER BY c.name,cs.name,su.name"
        ).fetchall()],
        "attendance_students": [to_dict(row) for row in db().execute(
            "SELECT id,name,email FROM users WHERE role='student' ORDER BY name"
        ).fetchall()],
        "attendance_teachers": [to_dict(row) for row in db().execute(
            "SELECT DISTINCT u.id,u.name,u.email FROM users u WHERE u.role='student' ORDER BY u.name"
        ).fetchall()],
        "attendance_corrections": [to_dict(row) for row in db().execute(
            "SELECT ac.*,u.name AS student_name,sc.name AS class_name "
            "FROM attendance_corrections ac JOIN attendance_records ar ON ar.id=ac.attendance_id "
            "JOIN users u ON u.id=ar.student_id JOIN class_sessions s ON s.id=ar.session_id "
            "JOIN scheduled_classes sc ON sc.id=s.class_id ORDER BY ac.corrected_at DESC LIMIT 100"
        ).fetchall()],
        "attendance_adjustments": [to_dict(row) for row in db().execute(
            "SELECT a.*,u.name AS student_name FROM attendance_reward_adjustments a "
            "JOIN users u ON u.id=a.student_id ORDER BY a.created_at DESC LIMIT 100"
        ).fetchall()],
    })


@app.post("/api/admin/rewards")
@admin_required
def admin_add_reward():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    description = str(data.get("description", "")).strip()
    price = data.get("token_price")
    if not name or len(name) > 80 or not isinstance(price, int) or price < 1:
        return error("Enter a reward name and a valid whole-number token price.")
    cursor = db().execute("INSERT INTO rewards(name,description,token_price) VALUES(?,?,?)", (name, description, price))
    return jsonify({"id": cursor.lastrowid, "reward_value_paise": reward_value_paise(price)}), 201


@app.patch("/api/admin/rewards/<int:reward_id>")
@admin_required
def admin_update_reward(reward_id):
    data = request.get_json(silent=True) or {}
    price = data.get("token_price")
    if not isinstance(price, int) or price < 1:
        return error("Enter a valid whole-number token price.")
    changed = db().execute("UPDATE rewards SET token_price=? WHERE id=?", (price, reward_id)).rowcount
    return jsonify({"ok": True, "reward_value_paise": reward_value_paise(price)}) if changed else error("Reward not found.", 404)


@app.post("/api/admin/menu")
@admin_required
def admin_add_menu_item():
    data = request.get_json(silent=True) or {}
    name, price = str(data.get("name", "")).strip(), data.get("token_price")
    if not name or len(name) > 80 or not isinstance(price, int) or price < 1:
        return error("Enter a menu item name and valid token price.")
    cursor = db().execute(
        "INSERT INTO menu_items(name,description,token_price) VALUES(?,?,?)",
        (name, str(data.get("description", "")).strip()[:300], price),
    )
    return jsonify({"id": cursor.lastrowid}), 201


@app.patch("/api/admin/menu/<int:item_id>")
@admin_required
def admin_update_menu(item_id):
    data = request.get_json(silent=True) or {}
    price = data.get("token_price")
    if not isinstance(price, int) or price < 1:
        return error("Enter a valid whole-number token price.")
    changed = db().execute("UPDATE menu_items SET token_price=? WHERE id=?", (price, item_id)).rowcount
    return (jsonify({"ok": True}) if changed else error("Menu item not found.", 404))


@app.route("/api/admin/activities", methods=["POST"])
@app.route("/api/admin/activities/<int:activity_id>", methods=["PUT", "DELETE"])
@admin_required
def admin_activities(activity_id=None):
    connection = db()
    if request.method == "DELETE":
        changed = connection.execute("DELETE FROM activities WHERE id=?", (activity_id,)).rowcount
        return jsonify({"ok": True}) if changed else error("Activity not found.", 404)
    data = request.get_json(silent=True) or {}
    required = ("title", "description", "category", "start_at", "end_at", "venue", "organizer", "instructions")
    values = [str(data.get(key, "")).strip() for key in required]
    reward = data.get("reward_tokens", 0)
    if any(not value for value in values) or not isinstance(reward, int) or reward < 0:
        return error("Complete all activity fields and enter a valid reward.")
    try:
        start = datetime.fromisoformat(values[3].replace("Z", "+00:00"))
        end = datetime.fromisoformat(values[4].replace("Z", "+00:00"))
        if start.utcoffset() is None or end.utcoffset() is None:
            return error("Activity timestamps must include a timezone.")
        if start >= end:
            return error("Activity end must be after its start.")
    except ValueError:
        return error("Enter valid activity start and end dates.")
    values[3] = start.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    values[4] = end.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    if activity_id is None:
        cursor = connection.execute(
            "INSERT INTO activities(title,description,category,start_at,end_at,venue,organizer,instructions,reward_tokens,is_sample) VALUES(?,?,?,?,?,?,?,?,?,0)",
            (*values, reward),
        )
        return jsonify({"id": cursor.lastrowid}), 201
    changed = connection.execute(
        "UPDATE activities SET title=?,description=?,category=?,start_at=?,end_at=?,venue=?,organizer=?,instructions=?,reward_tokens=? WHERE id=?",
        (*values, reward, activity_id),
    ).rowcount
    return jsonify({"ok": True}) if changed else error("Activity not found.", 404)


@app.patch("/api/admin/orders/<order_id>")
@admin_required
def admin_update_order(order_id):
    data = request.get_json(silent=True) or {}
    status = data.get("status")
    allowed = {"Pending": {"Preparing", "Cancelled"}, "Preparing": {"Ready"}, "Ready": {"Completed"}}
    connection = db()
    try:
        connection.execute("BEGIN IMMEDIATE")
        order = connection.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if not order:
            connection.rollback()
            return error("Order not found.", 404)
        if status not in allowed.get(order["status"], set()):
            connection.rollback()
            return error("That order status transition is not allowed.", 409)
        if status == "Cancelled":
            connection.execute("UPDATE orders SET status='Cancelled' WHERE id=?", (order_id,))
            ledger_change(
                connection, order["user_id"], order["token_cost"], "credit",
                f"Refund: cancelled order {order_id[:8]}", "order_refund", order_id,
            )
        else:
            connection.execute("UPDATE orders SET status=? WHERE id=?", (status, order_id))
        connection.commit()
    except (ValueError, sqlite3.IntegrityError) as exc:
        connection.rollback()
        return error(str(exc), 409)
    return jsonify({"ok": True})


@app.patch("/api/admin/participations/<int:participation_id>")
@admin_required
def admin_review_participation(participation_id):
    data = request.get_json(silent=True) or {}
    status = data.get("status")
    if status not in {"Approved", "Rejected"}:
        return error("Choose Approved or Rejected.")
    connection = db()
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT p.*,a.title AS activity_title,a.reward_tokens AS configured_reward "
            "FROM activity_participations p JOIN activities a ON a.id=p.activity_id WHERE p.id=?",
            (participation_id,),
        ).fetchone()
        if not row:
            connection.rollback()
            return error("Participation request not found.", 404)
        if row["status"] != "Pending Review":
            connection.rollback()
            return error("This participation request has already been reviewed.", 409)
        reward = row["configured_reward"] if status == "Approved" else 0
        connection.execute(
            "UPDATE activity_participations SET status=?,reward_tokens=?,reviewed_at=? WHERE id=? AND status='Pending Review'",
            (status, reward, utc_now(), participation_id),
        )
        if reward:
            ledger_change(
                connection, row["user_id"], reward, "credit",
                f"Approved activity participation: {row['activity_title']}",
                "activity_participation", participation_id,
            )
        connection.commit()
    except (ValueError, sqlite3.IntegrityError) as exc:
        connection.rollback()
        return error(str(exc), 409)
    return jsonify({"ok": True, "reward_tokens": reward})


@app.patch("/api/admin/submissions/<submission_id>")
@admin_required
def admin_review_submission(submission_id):
    data = request.get_json(silent=True) or {}
    status = data.get("status")
    if status not in {"Approved", "Rejected"}:
        return error("Choose Approved or Rejected.")
    connection = db()
    try:
        connection.execute("BEGIN IMMEDIATE")
        submission = connection.execute("SELECT * FROM submissions WHERE id=?", (submission_id,)).fetchone()
        if not submission:
            connection.rollback()
            return error("Submission not found.", 404)
        if submission["status"] != "Pending Review":
            connection.rollback()
            return error("This submission has already been reviewed.", 409)
        reward = int(connection.execute("SELECT value FROM settings WHERE key='contribution_reward'").fetchone()[0]) if status == "Approved" else 0
        connection.execute(
            "UPDATE submissions SET status=?,reward_tokens=?,reviewed_at=? WHERE id=? AND status='Pending Review'",
            (status, reward, utc_now(), submission_id),
        )
        if status == "Approved" and reward:
            ledger_change(
                connection, submission["user_id"], reward, "credit", f"Approved contribution: {submission['title']}",
                "submission_approval", submission_id,
            )
        connection.commit()
    except (ValueError, sqlite3.IntegrityError) as exc:
        connection.rollback()
        return error(str(exc), 409)
    return jsonify({"ok": True, "reward_tokens": reward})


@app.patch("/api/admin/settings/contribution-reward")
@admin_required
def admin_contribution_reward():
    data = request.get_json(silent=True) or {}
    amount = data.get("reward_tokens")
    if not isinstance(amount, int) or amount < 0 or amount > 10000:
        return error("Contribution reward must be between 0 and 10,000 tokens.")
    db().execute("UPDATE settings SET value=? WHERE key='contribution_reward'", (str(amount),))
    return jsonify({"ok": True, "reward_tokens": amount})


@app.post("/api/assistant")
@login_required
def assistant():
    data = request.get_json(silent=True) or {}
    question = str(data.get("message", "")).strip()
    if not question or len(question) > 1000:
        return error("Ask a question up to 1,000 characters.")
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return error("Gemma 4 is unavailable: configure GOOGLE_API_KEY in your .env file.", 503)

    user = current_user()
    terms = question.casefold()
    relevant = {}
    if any(word in terms for word in ("balance", "token", "earn", "reward", "redeem", "afford", "cheap", "price")):
        relevant["wallet"] = {"verified_balance": user["balance"], "conversion": "100 tokens = ₹10 reward value"}
        relevant["rewards"] = [
            {**to_dict(row), "reward_value_paise": reward_value_paise(row["token_price"])}
            for row in db().execute("SELECT name,description,token_price FROM rewards WHERE active=1 ORDER BY token_price")
        ]
        relevant["earning_rules"] = {
            "participation": "Students request participation review. Admin approval awards the activity's configured reward once.",
            "creative_contributions": "Poster, banner, or canteen promotion submissions earn the configured contribution reward only after admin approval.",
            "configured_contribution_reward": int(db().execute("SELECT value FROM settings WHERE key='contribution_reward'").fetchone()[0]),
        }
        relevant["recent_transactions"] = [
            to_dict(row) for row in db().execute(
                "SELECT entry_type,amount,reason,created_at FROM ledger WHERE user_id=? ORDER BY id DESC LIMIT 10",
                (user["id"],),
            )
        ] if any(word in terms for word in ("transaction", "ledger", "history", "earned", "spent")) else []
    if any(word in terms for word in ("activity", "event", "workshop", "competition", "fest", "volunteer", "poster", "banner")):
        relevant["activities"] = [
            {**to_dict(row), "state": activity_state(row["start_at"], row["end_at"])}
            for row in db().execute("SELECT title,description,category,start_at,end_at,venue,organizer,instructions,reward_tokens,is_sample FROM activities ORDER BY start_at")
            if activity_state(row["start_at"], row["end_at"]) in {"Upcoming", "Ongoing"}
        ]
        relevant["poster_submission_opportunity"] = "Students may submit event posters, banners, or canteen promotions. Pending Review submissions earn the admin-configured reward only after approval."
    if any(word in terms for word in ("order", "canteen", "preparing", "ready", "bought", "purchase")):
        relevant["my_orders"] = [
            order_json(row) for row in db().execute(
                "SELECT * FROM orders WHERE user_id=? ORDER BY created_at DESC LIMIT 20", (user["id"],)
            )
        ]
    if any(word in terms for word in ("attendance", "attended", "absent", "present", "weekly bonus")):
        local_date = datetime.now(college_zone()).date()
        current_week = (local_date - timedelta(days=local_date.weekday())).isoformat()
        relevant["attendance"] = {
            "verified_current_week": attendance_stats_for_student(db(), user["id"], current_week),
            "weekly_reward_history": [
                to_dict(row) for row in db().execute(
                    "SELECT week_start,week_end,attendance_percentage,sessions_attended,sessions_held,reward_tokens,status "
                    "FROM weekly_attendance_rewards WHERE student_id=? ORDER BY week_start DESC LIMIT 12",
                    (user["id"],),
                )
            ],
            "tiers": [
                {"minimum_percentage": 70, "tokens": 200},
                {"minimum_percentage": 80, "tokens": 300},
                {"minimum_percentage": 90, "tokens": 500},
            ],
            "rules": "The backend computes attendance from recorded, finalized class sessions. Only a completed college-local week with all sessions finalized can be issued; the assistant cannot determine or grant rewards.",
        }
    context_json = jsonify(relevant).get_data(as_text=True)
    prompt = (
        "You are CampusLoop's helpful campus rewards assistant. You must use only the verified application data "
        "in the JSON context below. If requested information is absent, say it is not available in the app data. "
        "Never infer or invent balance, prices, activities, rewards, transactions, or orders. Never claim to change "
        "tokens, submissions, or orders. Explain rules clearly and keep private order data limited to this signed-in "
        "student. Sample activities are demo examples, not verified college events.\n"
        f"VERIFIED CONTEXT JSON:\n{context_json}\nSTUDENT QUESTION:\n{question}"
    )
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
        answer = getattr(response, "text", None)
        if not answer:
            return error("Gemma 4 returned an empty response. Please try again.", 502)
        return jsonify({"answer": answer, "model": MODEL_NAME})
    except Exception:
        app.logger.exception("Gemma 4 assistant request failed")
        return error("Gemma 4 is temporarily unavailable. No alternate model was used; please try again shortly.", 503)


with app.app_context():
    initialize_database()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=os.environ.get("FLASK_DEBUG") == "1")
