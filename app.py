from __future__ import annotations

import os
from datetime import datetime
from typing import Dict, List, Tuple

import mysql.connector
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash

SECTORS: List[Tuple[str, str]] = [
    ("hotel", "Hotel"),
    ("event_management", "Event Management"),
    ("construction", "Construction"),
    ("hospital", "Hospital"),
    ("medical", "Medical"),
    ("electrical_shop", "Electrical Shop"),
    ("mechanical_workshop", "Mechanical Workshop"),
    ("car_bike_accessories", "Car & Bike Accessories"),
    ("beauty_parlor", "Beauty Parlor"),
    ("departmental_store", "Departmental Store"),
]

SECTOR_TABLES: Dict[str, str] = {key: f"sector_{key}" for key, _ in SECTORS}

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "dev-secret-change-me")
_db_ready = False


def get_db():
    return mysql.connector.connect(**get_db_config())


def get_db_config() -> Dict[str, str | int]:
    required = ["DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME"]
    missing = [key for key in required if not os.environ.get(key)]
    if missing:
        raise RuntimeError(f"Missing database env vars: {', '.join(missing)}")

    return {
        "host": os.environ["DB_HOST"],
        "user": os.environ["DB_USER"],
        "password": os.environ["DB_PASSWORD"],
        "database": os.environ["DB_NAME"],
        "port": int(os.environ.get("DB_PORT", "3306")),
    }


def init_db() -> None:
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            email VARCHAR(255) UNIQUE,
            mobile VARCHAR(32) UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            created_at DATETIME NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS admins (
            id INT AUTO_INCREMENT PRIMARY KEY,
            email VARCHAR(255) UNIQUE,
            mobile VARCHAR(32) UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            created_at DATETIME NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS bookings (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            mobile VARCHAR(32) NOT NULL,
            address TEXT NOT NULL,
            sector_key VARCHAR(64) NOT NULL,
            latitude DECIMAL(10,7),
            longitude DECIMAL(10,7),
            geo_address TEXT,
            created_at DATETIME NOT NULL
        )
        """
    )

    for table in SECTOR_TABLES.values():
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table} (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                rating DECIMAL(2,1) NOT NULL,
                contact VARCHAR(255),
                address TEXT
            )
            """
        )

    conn.commit()

    admin_email = os.environ.get("ADMIN_SEED_EMAIL")
    admin_password = os.environ.get("ADMIN_SEED_PASSWORD")
    if admin_email and admin_password:
        cur.execute("SELECT COUNT(*) FROM admins")
        count = cur.fetchone()[0]
        if count == 0:
            cur.execute(
                "INSERT INTO admins (email, mobile, password_hash, created_at) VALUES (%s, %s, %s, %s)",
                (
                    admin_email,
                    None,
                    generate_password_hash(admin_password),
                    datetime.utcnow(),
                ),
            )
            conn.commit()

    cur.close()
    conn.close()


@app.before_request
def ensure_db() -> None:
    global _db_ready
    if not _db_ready:
        init_db()
        _db_ready = True


def admin_required():
    if not session.get("admin_id"):
        return redirect(url_for("admin_login"))
    return None


@app.route("/")
def index():
    return render_template("index.html", sectors=SECTORS)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip()
        password = request.form.get("password", "").strip()

        if not identifier or not password:
            flash("Please enter email/mobile and password.", "error")
            return redirect(url_for("login"))

        conn = get_db()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT * FROM users WHERE email = %s OR mobile = %s",
            (identifier, identifier),
        )
        user = cur.fetchone()
        cur.close()
        conn.close()

        if not user or not check_password_hash(user["password_hash"], password):
            flash("Invalid credentials.", "error")
            return redirect(url_for("login"))

        session["user_id"] = user["id"]
        session["user_identifier"] = user["email"] or user["mobile"]
        flash("Logged in successfully.", "success")
        return redirect(url_for("index"))

    return render_template("login.html")


@app.route("/register", methods=["POST"])
def register():
    email = request.form.get("email", "").strip() or None
    mobile = request.form.get("mobile", "").strip() or None
    password = request.form.get("password", "").strip()

    if not (email or mobile) or not password:
        flash("Provide email or mobile and a password.", "error")
        return redirect(url_for("login"))

    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO users (email, mobile, password_hash, created_at) VALUES (%s, %s, %s, %s)",
            (email, mobile, generate_password_hash(password), datetime.utcnow()),
        )
        conn.commit()
        flash("Account created. Please log in.", "success")
    except mysql.connector.IntegrityError:
        flash("Email or mobile already registered.", "error")
    finally:
        cur.close()
        conn.close()

    return redirect(url_for("login"))


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "success")
    return redirect(url_for("index"))


@app.route("/book", methods=["GET", "POST"])
def book():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        mobile = request.form.get("mobile", "").strip()
        address = request.form.get("address", "").strip()
        sector_key = request.form.get("sector", "").strip()
        latitude = request.form.get("latitude")
        longitude = request.form.get("longitude")
        geo_address = request.form.get("geo_address", "").strip() or None

        if not name or not mobile or not address or sector_key not in SECTOR_TABLES:
            flash("Please fill all fields.", "error")
            return redirect(url_for("book"))

        if not latitude or not longitude:
            flash("Live location is required. Please allow location access.", "error")
            return redirect(url_for("book"))

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO bookings
            (name, mobile, address, sector_key, latitude, longitude, geo_address, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                name,
                mobile,
                address,
                sector_key,
                latitude,
                longitude,
                geo_address,
                datetime.utcnow(),
            ),
        )
        conn.commit()
        cur.close()
        conn.close()

        sheet_ok = write_to_google_sheet(name, mobile, address, sector_key, latitude, longitude, geo_address)
        notify_ok = send_notifications(name, mobile, address, sector_key, latitude, longitude, geo_address)

        if sheet_ok:
            flash("Booking saved to Google Sheet.", "success")
        else:
            flash("Booking saved locally (Google Sheet not configured).", "warning")

        if notify_ok:
            flash("Notification sent.", "success")
        else:
            flash("Notification not sent (email/SMS not configured).", "warning")

        return redirect(url_for("book"))

    return render_template("book.html", sectors=SECTORS)


@app.route("/sector/<sector_key>")
def sector(sector_key: str):
    if sector_key not in SECTOR_TABLES:
        flash("Unknown sector.", "error")
        return redirect(url_for("index"))

    table = SECTOR_TABLES[sector_key]
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute(f"SELECT * FROM {table} ORDER BY rating DESC, name ASC")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    sector_name = dict(SECTORS)[sector_key]
    return render_template("sector.html", sector_name=sector_name, rows=rows)


@app.route("/health")
def health():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        cur.close()
        conn.close()
        return {"status": "ok"}, 200
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}, 500


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip()
        password = request.form.get("password", "").strip()

        conn = get_db()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT * FROM admins WHERE email = %s OR mobile = %s",
            (identifier, identifier),
        )
        admin = cur.fetchone()
        cur.close()
        conn.close()

        if not admin or not check_password_hash(admin["password_hash"], password):
            flash("Invalid admin credentials.", "error")
            return redirect(url_for("admin_login"))

        session["admin_id"] = admin["id"]
        session["admin_identifier"] = admin["email"] or admin["mobile"]
        flash("Admin logged in.", "success")
        return redirect(url_for("admin_dashboard"))

    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_id", None)
    session.pop("admin_identifier", None)
    flash("Admin logged out.", "success")
    return redirect(url_for("index"))


@app.route("/admin")
def admin_dashboard():
    guard = admin_required()
    if guard:
        return guard

    sector_key = request.args.get("sector", SECTORS[0][0])
    if sector_key not in SECTOR_TABLES:
        sector_key = SECTORS[0][0]

    table = SECTOR_TABLES[sector_key]
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute(f"SELECT * FROM {table} ORDER BY rating DESC, name ASC")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    return render_template(
        "admin_dashboard.html",
        sectors=SECTORS,
        active_sector=sector_key,
        rows=rows,
    )


@app.route("/admin/sector/<sector_key>/add", methods=["POST"])
def admin_add_listing(sector_key: str):
    guard = admin_required()
    if guard:
        return guard

    if sector_key not in SECTOR_TABLES:
        flash("Unknown sector.", "error")
        return redirect(url_for("admin_dashboard"))

    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip() or None
    rating = request.form.get("rating", "").strip()
    contact = request.form.get("contact", "").strip() or None
    address = request.form.get("address", "").strip() or None

    if not name or not rating:
        flash("Name and rating are required.", "error")
        return redirect(url_for("admin_dashboard", sector=sector_key))

    table = SECTOR_TABLES[sector_key]
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        f"INSERT INTO {table} (name, description, rating, contact, address) VALUES (%s, %s, %s, %s, %s)",
        (name, description, rating, contact, address),
    )
    conn.commit()
    cur.close()
    conn.close()

    flash("Listing added.", "success")
    return redirect(url_for("admin_dashboard", sector=sector_key))


@app.route("/admin/sector/<sector_key>/edit/<int:listing_id>", methods=["GET", "POST"])
def admin_edit_listing(sector_key: str, listing_id: int):
    guard = admin_required()
    if guard:
        return guard

    if sector_key not in SECTOR_TABLES:
        flash("Unknown sector.", "error")
        return redirect(url_for("admin_dashboard"))

    table = SECTOR_TABLES[sector_key]
    conn = get_db()
    cur = conn.cursor(dictionary=True)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip() or None
        rating = request.form.get("rating", "").strip()
        contact = request.form.get("contact", "").strip() or None
        address = request.form.get("address", "").strip() or None

        cur.execute(
            f"""
            UPDATE {table}
            SET name = %s, description = %s, rating = %s, contact = %s, address = %s
            WHERE id = %s
            """,
            (name, description, rating, contact, address, listing_id),
        )
        conn.commit()
        cur.close()
        conn.close()
        flash("Listing updated.", "success")
        return redirect(url_for("admin_dashboard", sector=sector_key))

    cur.execute(f"SELECT * FROM {table} WHERE id = %s", (listing_id,))
    listing = cur.fetchone()
    cur.close()
    conn.close()

    if not listing:
        flash("Listing not found.", "error")
        return redirect(url_for("admin_dashboard", sector=sector_key))

    return render_template(
        "admin_edit.html",
        sector_key=sector_key,
        sector_name=dict(SECTORS)[sector_key],
        listing=listing,
    )


@app.route("/admin/sector/<sector_key>/delete/<int:listing_id>", methods=["POST"])
def admin_delete_listing(sector_key: str, listing_id: int):
    guard = admin_required()
    if guard:
        return guard

    if sector_key not in SECTOR_TABLES:
        flash("Unknown sector.", "error")
        return redirect(url_for("admin_dashboard"))

    table = SECTOR_TABLES[sector_key]
    conn = get_db()
    cur = conn.cursor()
    cur.execute(f"DELETE FROM {table} WHERE id = %s", (listing_id,))
    conn.commit()
    cur.close()
    conn.close()

    flash("Listing deleted.", "success")
    return redirect(url_for("admin_dashboard", sector=sector_key))


def write_to_google_sheet(
    name: str,
    mobile: str,
    address: str,
    sector_key: str,
    latitude: str,
    longitude: str,
    geo_address: str | None,
) -> bool:
    creds_path = os.environ.get("GOOGLE_SHEETS_CREDENTIALS")
    sheet_id = os.environ.get("GOOGLE_SHEET_ID")
    if not creds_path or not sheet_id:
        return False

    try:
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(sheet_id).sheet1
        sheet.append_row(
            [
                name,
                mobile,
                address,
                sector_key,
                latitude,
                longitude,
                geo_address or "",
                datetime.utcnow().isoformat(),
            ]
        )
        return True
    except Exception:
        return False


def send_notifications(
    name: str,
    mobile: str,
    address: str,
    sector_key: str,
    latitude: str,
    longitude: str,
    geo_address: str | None,
) -> bool:
    email_sent = send_email_notification(name, mobile, address, sector_key, latitude, longitude, geo_address)
    sms_sent = send_sms_notification(name, mobile, address, sector_key, latitude, longitude, geo_address)
    return email_sent or sms_sent


def send_email_notification(
    name: str,
    mobile: str,
    address: str,
    sector_key: str,
    latitude: str,
    longitude: str,
    geo_address: str | None,
) -> bool:
    smtp_host = os.environ.get("SMTP_HOST")
    smtp_port = os.environ.get("SMTP_PORT")
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASS")
    smtp_from = os.environ.get("SMTP_FROM")
    notify_email = os.environ.get("NOTIFY_EMAIL")

    if not all([smtp_host, smtp_port, smtp_user, smtp_pass, smtp_from, notify_email]):
        return False

    try:
        import smtplib
        from email.message import EmailMessage

        msg = EmailMessage()
        msg["Subject"] = "New Booking Request"
        msg["From"] = smtp_from
        msg["To"] = notify_email
        msg.set_content(
            "\n".join(
                [
                    f"Name: {name}",
                    f"Mobile: {mobile}",
                    f"Address: {address}",
                    f"Sector: {sector_key}",
                    f"Latitude: {latitude}",
                    f"Longitude: {longitude}",
                    f"Geo Address: {geo_address or ''}",
                ]
            )
        )

        with smtplib.SMTP(smtp_host, int(smtp_port)) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        return True
    except Exception:
        return False


def send_sms_notification(
    name: str,
    mobile: str,
    address: str,
    sector_key: str,
    latitude: str,
    longitude: str,
    geo_address: str | None,
) -> bool:
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
    from_number = os.environ.get("TWILIO_FROM")
    notify_mobile = os.environ.get("NOTIFY_MOBILE")

    if not all([account_sid, auth_token, from_number, notify_mobile]):
        return False

    try:
        from twilio.rest import Client

        client = Client(account_sid, auth_token)
        body = (
            f"New booking: {name}, {mobile}, {address}, sector: {sector_key}, "
            f"lat: {latitude}, lng: {longitude}"
        )
        client.messages.create(from_=from_number, to=notify_mobile, body=body)
        return True
    except Exception:
        return False


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
