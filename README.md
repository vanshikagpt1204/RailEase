# RailEase — Train Booking Demo

A Python Flask + SQLite train search and booking demo.

## Requirements
- Python 3.10+
- VS Code

## Run on Windows
1. Extract the ZIP and open the `railease` folder in VS Code.
2. Open Terminal → New Terminal.
3. Create a virtual environment:
   ```powershell
   py -m venv .venv
   .venv\Scripts\activate
   ```
4. Install dependencies:
   ```powershell
   python -m pip install -r requirements.txt
   ```
5. Start the website:
   ```powershell
   python app.py
   ```
6. Open `http://127.0.0.1:5000` in your browser.

The SQLite database `railease.db` is created automatically on first run.

## Included
- Home page with station/date search
- Train results and sample seat availability
- Sign up, login, logout
- Passenger booking flow and confirmation reference
- My Bookings and About Us
- Password hashing and per-user booking records

## Important
This is a functional demonstration using sample train inventory. It does NOT connect to IRCTC or any live railway reservation system, does not hold real seats, and does not issue valid railway tickets/PNRs or process payments. For real bookings, integrate an authorized railway API/provider after obtaining credentials and complying with its terms. Do not use demo PNRs as travel documents.
