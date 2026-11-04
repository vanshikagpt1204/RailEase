import os, sqlite3, secrets
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session, g
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key")
DB = os.path.join(os.path.dirname(__file__), "railease.db")

STATIONS = {
    "LKO": "Lucknow NR", "NDLS": "New Delhi", "BSB": "Varanasi",
    "CNB": "Kanpur Central", "PRYJ": "Prayagraj", "BPL": "Bhopal",
    "AGC": "Agra Cantt", "JP": "Jaipur", "MUM": "Mumbai Central",
    "HWH": "Howrah", "PNBE": "Patna", "GKP": "Gorakhpur"
}
TRAINS = [
    {"no":"12004","name":"Shatabdi Express","from":"LKO","to":"NDLS","depart":"06:10","arrive":"12:30","duration":"6h 20m","days":"Daily","fare":1250,"seats":18,"classes":["CC","EC"]},
    {"no":"125 ಕ1","name":"Gomti Express","from":"LKO","to":"NDLS","depart":"05:45","arrive":"14:10","duration":"8h 25m","days":"Daily","fare":620,"seats":32,"classes":["2S","SL","3A"]},
    {"no":"14204","name":"Babu Dham Express","from":"LKO","to":"BSB","depart":"07:20","arrive":"13:05","duration":"5h 45m","days":"Daily","fare":410,"seats":24,"classes":["2S","SL","3A"]},
    {"no":"22425","name":"Vande Bharat Express","from":"LKO","to":"BSB","depart":"15:20","arrive":"19:00","duration":"3h 40m","days":"Except Sun","fare":980,"seats":12,"classes":["CC","EC"]},
    {"no":"12230","name":"Lucknow Mail","from":"LKO","to":"MUM","depart":"22:00","arrive":"05:30","duration":"31h 30m","days":"Daily","fare":890,"seats":9,"classes":["SL","3A","2A"]},
    {"no":"12556","name":"Gorakhdham Express","from":"GKP","to":"NDLS","depart":"18:00","arrive":"07:10","duration":"13h 10m","days":"Daily","fare":740,"seats":21,"classes":["SL","3A","2A"]}
]
# Correct a sample train number typo while keeping data readable.
TRAINS[1]["no"] = "14216"

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(_):
    conn = g.pop("db", None)
    if conn: conn.close()

def init_db():
    conn = sqlite3.connect(DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL, password TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS bookings(
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
        pnr TEXT UNIQUE NOT NULL, train_no TEXT NOT NULL, train_name TEXT NOT NULL,
        origin TEXT NOT NULL, destination TEXT NOT NULL, journey_date TEXT NOT NULL,
        travel_class TEXT NOT NULL, passenger TEXT NOT NULL, age INTEGER NOT NULL,
        fare INTEGER NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL)""")
    conn.commit(); conn.close()

@app.before_request
def load_user():
    g.user = None
    if session.get("user_id"):
        g.user = db().execute("SELECT id,name,email FROM users WHERE id=?", (session["user_id"],)).fetchone()

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
    return {"stations": STATIONS, "now": datetime.today().strftime("%Y-%m-%d")}

@app.route("/")
def index():
    return render_template("index.html", trains=TRAINS[:3])

@app.route("/search")
def search():
    origin, destination = request.args.get("from","LKO"), request.args.get("to","NDLS")
    date = request.args.get("date", datetime.today().strftime("%Y-%m-%d"))
    results = [t for t in TRAINS if t["from"] == origin and t["to"] == destination]
    return render_template("results.html", trains=results, origin=origin, destination=destination, date=date)

@app.route("/signup", methods=["GET","POST"])
def signup():
    if request.method == "POST":
        name, email, password = (request.form.get(x,"").strip() for x in ("name","email","password"))
        if not name or not email or len(password) < 8:
            flash("Enter all details. Password must be at least 8 characters.", "danger")
        else:
            try:
                cur = db().execute("INSERT INTO users(name,email,password) VALUES(?,?,?)",
                                   (name,email,generate_password_hash(password)))
                db().commit(); session["user_id"] = cur.lastrowid
                flash("Account created. Welcome aboard!", "success")
                return redirect(url_for("index"))
            except sqlite3.IntegrityError:
                flash("An account with this email already exists.", "danger")
    return render_template("auth.html", mode="signup")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        user = db().execute("SELECT * FROM users WHERE email=?", (request.form.get("email","").strip(),)).fetchone()
        if user and check_password_hash(user["password"], request.form.get("password","")):
            session["user_id"] = user["id"]
            flash("You are now logged in.", "success")
            return redirect(url_for("index"))
        flash("Incorrect email or password.", "danger")
    return render_template("auth.html", mode="login")

@app.route("/logout")
def logout():
    session.clear(); flash("You have been logged out.", "info")
    return redirect(url_for("index"))

@app.route("/book", methods=["GET","POST"])
@login_required
def book():
    train_no = request.args.get("train") or request.form.get("train_no")
    train = next((t for t in TRAINS if t["no"] == train_no), None)
    if not train: return redirect(url_for("index"))
    date = request.args.get("date") or request.form.get("journey_date") or datetime.today().strftime("%Y-%m-%d")
    if request.method == "POST":
        passenger = request.form.get("passenger","").strip()
        try: age = int(request.form.get("age","0"))
        except ValueError: age = 0
        travel_class = request.form.get("travel_class","")
        if not passenger or not (1 <= age <= 120) or travel_class not in train["classes"]:
            flash("Please enter valid passenger details.", "danger")
        else:
            pnr = str(secrets.randbelow(9000000000) + 1000000000)
            fare = train["fare"] + (250 if travel_class in ("3A","CC") else 650 if travel_class in ("2A","EC") else 0)
            db().execute("""INSERT INTO bookings(user_id,pnr,train_no,train_name,origin,destination,
                journey_date,travel_class,passenger,age,fare,status,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (g.user["id"],pnr,train["no"],train["name"],train["from"],train["to"],
                 date,travel_class,passenger,age,fare,"CONFIRMED",datetime.now().isoformat(timespec="minutes")))
            db().commit()
            return redirect(url_for("confirmation", pnr=pnr))
    return render_template("book.html", train=train, date=date)

@app.route("/confirmation/<pnr>")
@login_required
def confirmation(pnr):
    booking = db().execute("SELECT * FROM bookings WHERE pnr=? AND user_id=?", (pnr,g.user["id"])).fetchone()
    if not booking: return redirect(url_for("my_bookings"))
    return render_template("confirmation.html", booking=booking)

@app.route("/my-bookings")
@login_required
def my_bookings():
    bookings = db().execute("SELECT * FROM bookings WHERE user_id=? ORDER BY id DESC", (g.user["id"],)).fetchall()
    return render_template("my_bookings.html", bookings=bookings)

@app.route("/about")
def about():
    return render_template("about.html")

if __name__ == "__main__":
    init_db()
    app.run(debug=True)
