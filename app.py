
import os
import re
import sqlite3
import secrets
from datetime import datetime
from functools import wraps
from pathlib import Path

import requests
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash, session, g
from werkzeug.security import generate_password_hash, check_password_hash


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

RAILRADAR_API_KEY = os.getenv("RAILRADAR_API_KEY")
RAILRADAR_BASE_URL = "https://api.railradar.in/v1"

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-this-secret-key")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

DB = str(BASE_DIR / "railease.db")


# ---------------------------------------------------------
# Station data and homepage preview data
# ---------------------------------------------------------

STATIONS = {
    "LKO": "Lucknow NR",
    "NDLS": "New Delhi",
    "BSB": "Varanasi",
    "CNB": "Kanpur Central",
    "PRYJ": "Prayagraj",
    "BPL": "Bhopal",
    "AGC": "Agra Cantt",
    "JP": "Jaipur",
    "MUM": "Mumbai Central",
    "HWH": "Howrah",
    "PNBE": "Patna",
    "GKP": "Gorakhpur",
}

# Homepage preview only. Actual search results are requested from RailRadar.
TRAINS = [
    {
        "no": "12004", "name": "Shatabdi Express",
        "from": "LKO", "to": "NDLS", "depart": "06:10",
        "arrive": "12:30", "duration": "6h 20m",
        "days": "Daily", "fare": 1250, "seats": 18,
        "classes": ["CC", "EC"],
    },
    {
        "no": "14216", "name": "Gomti Express",
        "from": "LKO", "to": "NDLS", "depart": "05:45",
        "arrive": "14:10", "duration": "8h 25m",
        "days": "Daily", "fare": 620, "seats": 32,
        "classes": ["2S", "SL", "3A"],
    },
    {
        "no": "14204", "name": "Babu Dham Express",
        "from": "LKO", "to": "BSB", "depart": "07:20",
        "arrive": "13:05", "duration": "5h 45m",
        "days": "Daily", "fare": 410, "seats": 24,
        "classes": ["2S", "SL", "3A"],
    },
]


# ---------------------------------------------------------
# Database
# ---------------------------------------------------------

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_error):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db():
    """Create the existing RailEase tables if they do not exist."""
    conn = sqlite3.connect(DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            pnr TEXT UNIQUE NOT NULL,
            train_no TEXT NOT NULL,
            train_name TEXT NOT NULL,
            origin TEXT NOT NULL,
            destination TEXT NOT NULL,
            journey_date TEXT NOT NULL,
            travel_class TEXT NOT NULL,
            passenger TEXT NOT NULL,
            age INTEGER NOT NULL,
            fare INTEGER NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


# Initialize during import as well, so Gunicorn has the tables.
init_db()


# ---------------------------------------------------------
# Authentication helpers
# ---------------------------------------------------------

@app.before_request
def load_user():
    g.user = None
    user_id = session.get("user_id")
    if user_id:
        g.user = db().execute(
            "SELECT id, name, email FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not g.user:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


@app.context_processor
def common():
    return {
        "stations": STATIONS,
        "now": datetime.today().strftime("%Y-%m-%d"),
    }


# ---------------------------------------------------------
# RailRadar API integration
# ---------------------------------------------------------

def get_trains_from_api(origin, destination, journey_date):
    """
    Fetch train information from RailRadar.

    Fare and seats below are illustrative demo values, not live railway data.
    """
    if not RAILRADAR_API_KEY:
        raise RuntimeError("RailRadar API key is missing.")

    endpoint = (
        f"{RAILRADAR_BASE_URL}/trains/between/"
        f"{origin}/{destination}"
    )
    headers = {
        "Authorization": f"Bearer {RAILRADAR_API_KEY}",
        "Accept": "application/json",
    }

    response = requests.get(
        endpoint,
        headers=headers,
        params={"date": journey_date, "lang": "en"},
        timeout=20,
    )
    response.raise_for_status()
    result = response.json()

    if not isinstance(result, dict) or not result.get("success"):
        raise RuntimeError("Unable to fetch train information.")

    api_trains = result.get("data", {}).get("trains", [])
    formatted_trains = []

    for item in api_trains:
        train = item.get("train") or {}
        source = item.get("from") or {}
        destination_data = item.get("to") or {}

        duration = item.get("duration")
        duration_text = "Not available"
        if isinstance(duration, (int, float)):
            hours = int(duration // 60)
            minutes = int(duration % 60)
            duration_text = f"{hours}h {minutes}m"

        run_days = train.get("runDays") or []
        if isinstance(run_days, list):
            days_text = ", ".join(str(day) for day in run_days)
        else:
            days_text = str(run_days) if run_days else "Not available"

        train_number = str(train.get("number") or "").strip()
        if not train_number:
            continue

        formatted_trains.append({
            "no": train_number,
            "name": train.get("name") or "Unknown Train",
            "from": source.get("code") or origin,
            "to": destination_data.get("code") or destination,
            "depart": source.get("departure") or "—",
            "arrive": destination_data.get("arrival") or "—",
            "duration": duration_text,
            "days": days_text,

            # Demo-only values. These are not live fares or seat availability.
            "fare": 500,
            "seats": 24,
            "classes": ["SL", "3A", "2A", "CC"],
            "is_demo": True,
        })

    return formatted_trains


# ---------------------------------------------------------
# Homepage and train search
# ---------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html", trains=TRAINS[:3])


@app.route("/search")
def search():
    origin = request.args.get("from", "LKO").strip().upper()
    destination = request.args.get("to", "NDLS").strip().upper()
    journey_date = request.args.get(
        "date", datetime.today().strftime("%Y-%m-%d")
    ).strip()

    results = []
    error = None

    if origin == destination:
        error = "Departure and destination stations cannot be the same."
    elif origin not in STATIONS or destination not in STATIONS:
        error = "Please select valid stations."
    elif not re.fullmatch(r"\d{4}-\d{2}-\d{2}", journey_date):
        error = "Please select a valid journey date."
    else:
        try:
            datetime.strptime(journey_date, "%Y-%m-%d")
            results = get_trains_from_api(origin, destination, journey_date)
        except requests.exceptions.Timeout:
            error = "Train search timed out. Please try again."
        except requests.exceptions.HTTPError as exc:
            status_code = (
                exc.response.status_code if exc.response is not None else "unknown"
            )
            error = f"Railway API returned an error: HTTP {status_code}."
        except requests.exceptions.RequestException:
            error = "Unable to connect to the railway API."
        except (RuntimeError, ValueError, TypeError):
            error = "Unable to retrieve train information."

    # Search results are kept for the next booking step.
    session["search_results"] = results

    return render_template(
        "results.html",
        trains=results,
        origin=origin,
        destination=destination,
        date=journey_date,
        error=error,
        data_source="RailRadar API",
    )


# ---------------------------------------------------------
# Signup, login and logout
# ---------------------------------------------------------

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not name or not email or len(password) < 8:
            flash(
                "Enter all details. Password must be at least 8 characters.",
                "danger",
            )
        else:
            try:
                cursor = db().execute(
                    "INSERT INTO users (name, email, password) VALUES (?, ?, ?)",
                    (name, email, generate_password_hash(password)),
                )
                db().commit()
                session.clear()
                session["user_id"] = cursor.lastrowid
                flash("Account created. Welcome aboard!", "success")
                return redirect(url_for("index"))
            except sqlite3.IntegrityError:
                flash("An account with this email already exists.", "danger")

    return render_template("auth.html", mode="signup")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = db().execute(
            "SELECT * FROM users WHERE email = ?",
            (email,),
        ).fetchone()

        if user and check_password_hash(user["password"], password):
            session.clear()
            session["user_id"] = user["id"]
            flash("You are now logged in.", "success")
            return redirect(url_for("index"))

        flash("Incorrect email or password.", "danger")

    return render_template("auth.html", mode="login")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))


# ---------------------------------------------------------
# Passenger details and booking review
# ---------------------------------------------------------

@app.route("/book", methods=["GET", "POST"])
@login_required
def book():
    train_no = (
        request.args.get("train") or request.form.get("train_no", "")
    ).strip()

    train = next(
        (
            item for item in session.get("search_results", [])
            if str(item.get("no")) == train_no
        ),
        None,
    )

    if not train:
        flash("Please search and select a train first.", "warning")
        return redirect(url_for("index"))

    journey_date = (
        request.args.get("date")
        or request.form.get("journey_date")
        or datetime.today().strftime("%Y-%m-%d")
    ).strip()

    if request.method == "POST":
        passenger = request.form.get("passenger", "").strip()

        try:
            age = int(request.form.get("age", "0"))
        except (TypeError, ValueError):
            age = 0

        travel_class = request.form.get("travel_class", "").strip()

        if not passenger or len(passenger) > 100 or not (1 <= age <= 120):
            flash("Please enter valid passenger details.", "danger")
        elif travel_class not in train.get("classes", []):
            flash("Please select a valid travel class.", "danger")
        else:
            base_fare = int(train.get("fare") or 500)
            class_extra = {
                "SL": 0,
                "3A": 250,
                "2A": 500,
                "CC": 200,
                "2S": 0,
                "EC": 500,
            }.get(travel_class, 0)

            session["pending_booking"] = {
                "train": train,
                "date": journey_date,
                "passenger": passenger,
                "age": age,
                "travel_class": travel_class,
                "fare": base_fare + class_extra,
            }
            return redirect(url_for("review_booking"))

    return render_template("book.html", train=train, date=journey_date)


@app.route("/review")
@login_required
def review_booking():
    booking = session.get("pending_booking")
    if not booking:
        flash("Please enter passenger details first.", "warning")
        return redirect(url_for("index"))

    return render_template(
        "review.html",
        train=booking["train"],
        date=booking["date"],
        passenger=booking["passenger"],
        age=booking["age"],
        travel_class=booking["travel_class"],
        fare=booking["fare"],
    )


# ---------------------------------------------------------
# Simulated payment
# ---------------------------------------------------------

@app.route("/demo-payment", methods=["GET", "POST"])
@login_required
def demo_payment():
    booking = session.get("pending_booking")
    if not booking:
        flash("Please complete your booking details first.", "warning")
        return redirect(url_for("index"))

    if request.method == "POST":
        # No payment gateway is contacted and no money is collected.
        session["demo_payment_status"] = "SUCCESS"
        return redirect(url_for("confirmation_page"))

    return render_template("payment.html", booking=booking)


# ---------------------------------------------------------
# Save demo booking and show confirmation
# ---------------------------------------------------------

@app.route("/confirmation")
@login_required
def confirmation_page():
    booking = session.get("pending_booking")
    payment_status = session.get("demo_payment_status")

    if not booking or payment_status != "SUCCESS":
        flash("Please complete the demo payment first.", "warning")
        return redirect(url_for("index"))

    demo_reference = "RE" + secrets.token_hex(4).upper()
    train = booking["train"]

    try:
        db().execute(
            """
            INSERT INTO bookings (
                user_id, pnr, train_no, train_name, origin, destination,
                journey_date, travel_class, passenger, age, fare,
                status, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                g.user["id"],
                demo_reference,
                str(train.get("no", "")),
                str(train.get("name", "Unknown Train")),
                str(train.get("from", "")),
                str(train.get("to", "")),
                booking["date"],
                booking["travel_class"],
                booking["passenger"],
                booking["age"],
                booking["fare"],
                "DEMO_CONFIRMED",
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        db().commit()
    except sqlite3.IntegrityError:
        db().rollback()
        flash("Unable to save this demo booking. Please try again.", "danger")
        return redirect(url_for("review_booking"))

    session.pop("pending_booking", None)
    session.pop("demo_payment_status", None)

    return redirect(url_for("confirmation", pnr=demo_reference))


@app.route("/confirmation/<pnr>")
@login_required
def confirmation(pnr):
    booking = db().execute(
        "SELECT * FROM bookings WHERE pnr = ? AND user_id = ?",
        (pnr, g.user["id"]),
    ).fetchone()

    if not booking:
        flash("Booking record not found.", "warning")
        return redirect(url_for("my_bookings"))

    return render_template("confirmation.html", booking=booking)


# ---------------------------------------------------------
# My bookings
# ---------------------------------------------------------

@app.route("/my-bookings")
@login_required
def my_bookings():
    bookings = db().execute(
        """
        SELECT * FROM bookings
        WHERE user_id = ?
        ORDER BY id DESC
        """,
        (g.user["id"],),
    ).fetchall()

    return render_template("my_bookings.html", bookings=bookings)


# ---------------------------------------------------------
# About page
# ---------------------------------------------------------

@app.route("/about")
def about():
    return render_template("about.html")


# ---------------------------------------------------------
# Local development
# ---------------------------------------------------------

if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "0") == "1",
    )
