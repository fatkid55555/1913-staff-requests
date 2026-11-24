"""
1913 Staff Requests — the website employees reach by scanning the QR code
next to the printed schedule.

What it does:
  - Staff pick their name from a list and type the 4-digit code a manager gave them.
  - They can ask for days off, or offer a shift to a coworker.
  - A shift trade goes to the coworker first. Only once they accept does it go to a manager.
  - The managers get an email for every request waiting on them, log in through the
    separate "Manager login" (real username + password), and approves or denies.

Safety:
  - Codes and passwords are stored scrambled; nobody can read them back.
  - 5 wrong tries on one name locks that name for 15 minutes, so nobody can
    sit there guessing codes.

Where the data lives:
  - On the live website: an online database (Neon), address in the DATABASE_URL secret.
  - Testing on the laptop with no DATABASE_URL: a throwaway file in the Windows
    temp folder. Never inside the project folder.

Secrets it reads (Streamlit's secrets box online, or environment variables locally):
  DATABASE_URL, MANAGER_USERNAME, MANAGER_PASSWORD,
  GMAIL_USER, GMAIL_APP_PASSWORD, ALERT_TO, APP_URL
"""

import base64
import calendar
import inspect
import os
import re
import secrets as pyrandom
import smtplib
import sqlite3
import ssl
import tempfile
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr
from html import escape

import bcrypt
import streamlit as st

st.set_page_config(page_title="1913 Staff Requests", page_icon="🗓️", layout="centered")

HERE = os.path.dirname(os.path.abspath(__file__))

# 1913 is open Tuesday through Saturday. Python counts Monday as 0, so Tue=1 ... Sat=5.
OPEN_DAYS = {1, 2, 3, 4, 5}

MAX_TRIES = 5          # wrong codes allowed before a name is locked
LOCK_MINUTES = 15      # how long the lock lasts

# Plain-English label and color for each status.
STATUS = {
    "waiting_coworker": ("Waiting on coworker", "#AE834A"),
    "coworker_declined": ("Coworker said no", "#8a8a8a"),
    "waiting_joe": ("Waiting on manager", "#AE834A"),
    "approved": ("Approved", "#2e7d32"),
    "denied": ("Denied", "#c62828"),
    "cancelled": ("Cancelled", "#8a8a8a"),
}


# ---------------------------------------------------------------------------
# The 1913 look: cream page, black header with the real logo, gold buttons.
# ---------------------------------------------------------------------------
def apply_style():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@600;700&family=Montserrat:wght@400;500;600&display=swap');

    /* Page background and fonts */
    .stApp { background: #FDFADA; }
    html, body, .stApp, p, label, input, button, textarea, li {
        font-family: 'Montserrat', sans-serif !important; color: #070909; }
    h1, h2, h3 { font-family: 'Cormorant Garamond', serif !important; color: #070909 !important; }

    /* Hide Streamlit's own menu bar and footer */
    header[data-testid="stHeader"], footer, [data-testid="stToolbar"] { display: none !important; }
    .block-container { padding-top: 0 !important; max-width: 520px; }

    /* Black band across the top with the logo */
    .brand { background: #070909; margin: 0 -1rem 1.2rem -1rem; padding: 26px 0 18px;
             text-align: center; border-bottom: 4px solid #AE834A; }
    .brand img { width: 150px; }
    .brand .sub { color: #AE834A; letter-spacing: .25em; font-size: .72rem;
                  margin-top: 10px; font-weight: 600; }

    /* Buttons: big, rounded, easy to hit with a thumb */
    .stButton button, .stFormSubmitButton button {
        border-radius: 12px !important; min-height: 3rem; font-weight: 600 !important;
        border: 1.5px solid #070909 !important; background: #fff !important; color: #070909 !important; }
    .stButton button[kind^="primary"], .stFormSubmitButton button[kind^="primary"] {
        background: #070909 !important; color: #FDFADA !important; border-color: #070909 !important; }
    .stButton button[kind^="primary"] p, .stFormSubmitButton button[kind^="primary"] p { color: #FDFADA !important; }
    .stButton button:hover, .stFormSubmitButton button:hover { border-color: #AE834A !important; }
    .stButton button:hover p, .stFormSubmitButton button:hover p { color: #AE834A !important; }
    /* Switched-off buttons look faded so it's clear they can't be pressed */
    .stButton button:disabled { opacity: .3; cursor: not-allowed; }

    /* Input boxes */
    .stTextInput input, .stDateInput input, .stTextArea textarea, [data-baseweb="select"] > div {
        background: #fff !important; border-radius: 10px !important; }

    /* White cards for forms and request lists */
    [data-testid="stForm"], [data-testid="stVerticalBlockBorderWrapper"] {
        background: #fff; border-radius: 16px !important; border: 1px solid #e7dfb8 !important; }

    /* Colored status tag */
    .chip { display: inline-block; padding: 3px 12px; border-radius: 999px; color: #fff;
            font-size: .75rem; font-weight: 600; letter-spacing: .03em; }
    .when { font-family: 'Cormorant Garamond', serif; font-size: 1.45rem; font-weight: 700;
            margin: 6px 0 0; }
    .muted { color: #6b6b6b; font-size: .85rem; }

    /* Tap calendar on the request-off page.
       Streamlit normally stacks side-by-side boxes on phones; these rules keep
       the calendar 7 days across on any screen. */
    [class*="offcal"] [data-testid="stHorizontalBlock"], [class*="offnav"] [data-testid="stHorizontalBlock"] {
        flex-wrap: nowrap !important; gap: 4px !important; }
    [class*="offcal"], [class*="offcal"] [data-testid="stVerticalBlock"] { gap: 4px !important; }
    [class*="offcal"] [data-testid="stMarkdownContainer"] { margin-bottom: 0 !important; }
    [class*="offcal"] .stMarkdown p { margin: 0 !important; }
    [class*="offnav"] [data-testid="stColumn"] { min-width: 0 !important; }
    [class*="offnav"] .stButton button { min-height: 2.4rem !important; font-size: 1.2rem; }
    [class*="offnav"] .stButton button:disabled { opacity: .25; }
    [class*="offcal"] [data-testid="stColumn"] {
        min-width: 0 !important; flex: 1 1 0 !important; width: auto !important; }
    [class*="offcal"] .stButton button {
        min-height: 2.6rem !important; padding: 0 !important; border-radius: 10px !important;
        border: 1px solid #e7dfb8 !important; width: 100%; }
    [class*="offcal"] .stButton button p { font-size: .9rem !important; font-weight: 600; }
    /* Picked days: gold */
    [class*="offcal"] .stButton button[kind="primary"] {
        background: #AE834A !important; border-color: #AE834A !important; }
    [class*="offcal"] .stButton button[kind="primary"] p { color: #fff !important; }
    /* Blackout days: black, crossed out, can't be tapped */
    [class*="offcal"] .stButton button[kind="tertiary"] {
        background: #070909 !important; border-color: #070909 !important; opacity: 1 !important; }
    [class*="offcal"] .stButton button[kind="tertiary"] p {
        color: #FDFADA !important; text-decoration: line-through; }
    /* Closed / past days: faded, can't be tapped */
    [class*="offcal"] .stButton button[kind="secondary"]:disabled {
        opacity: 1; background: transparent !important; border-color: transparent !important; }
    [class*="offcal"] .stButton button[kind="secondary"]:disabled p { color: #cfcfcf !important; }
    [class*="offcal"] .stButton button:not(:disabled):hover { border-color: #AE834A !important; }
    [class*="st-key-blkrow"] [data-testid="stHorizontalBlock"] { flex-wrap: nowrap !important; }
    [class*="st-key-blkrow"] [data-testid="stColumn"] { min-width: 0 !important; }
    [class*="st-key-blkrow"] .stButton button p { white-space: nowrap; }
    .cal-week { display: grid; grid-template-columns: repeat(7, 1fr); gap: 4px;
                text-align: center; font-size: .7rem; color: #6b6b6b; font-weight: 600;
                padding-bottom: 2px; line-height: 1.4; }
    .cal-month { font-family: 'Cormorant Garamond', serif; font-weight: 700; white-space: nowrap;
                 font-size: 1.3rem; text-align: center; padding-top: .3rem; }
    .cal-key { font-size: .75rem; color: #6b6b6b; margin: 2px 0 6px; }
    .cal-key span { display: inline-block; width: 12px; height: 12px; border-radius: 3px;
                    vertical-align: -1px; margin: 0 4px 0 10px; }

    /* Tabs (manager screen) in gold */
    .stTabs [aria-selected="true"] { color: #AE834A !important; }
    .stTabs [data-baseweb="tab-highlight"] { background: #AE834A !important; }
    </style>
    """, unsafe_allow_html=True)

    logo_path = os.path.join(HERE, "logo.png")
    logo = ""
    if os.path.exists(logo_path):
        with open(logo_path, "rb") as f:
            logo = f'<img src="data:image/png;base64,{base64.b64encode(f.read()).decode()}">'
    st.markdown(f'<div class="brand">{logo}<div class="sub">STAFF REQUESTS</div></div>',
                unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Reading secrets
# ---------------------------------------------------------------------------
def get_secret(name, default=""):
    """Look for a setting on the laptop first, then in Streamlit's secrets box."""
    if os.environ.get(name):
        return os.environ[name]
    try:
        return st.secrets.get(name, default)
    except Exception:  # no secrets box exists when testing on the laptop
        return default


# ---------------------------------------------------------------------------
# The database
# The same app works against the online database (live) or a local test file.
# The SQL is written once; for the test file the "%s" blanks become "?".
# ---------------------------------------------------------------------------
DATABASE_URL = get_secret("DATABASE_URL")
USING_ONLINE_DB = bool(DATABASE_URL)
TEST_DB_FILE = os.path.join(tempfile.gettempdir(), "1913_staff_requests_TEST.db")


@st.cache_resource
def online_connection():
    """Open ONE line to the online database and keep it open for everyone.
    (Before, every single lookup dialed a fresh connection — that was the slowness.)"""
    import psycopg  # only needed online; Windows on the laptop blocks it
    return psycopg.connect(DATABASE_URL, autocommit=True)


def _execute(conn, sql, params, fetch):
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = []
    if fetch:
        names = [c[0] for c in cur.description]
        rows = [dict(zip(names, r)) for r in cur.fetchall()]
    conn.commit()
    return rows


def run(sql, params=(), fetch=False):
    """Run one database command. Returns rows as a list of dicts when fetch=True."""
    if USING_ONLINE_DB:
        conn = online_connection()
        try:
            return _execute(conn, sql, params, fetch)
        except Exception:
            # The database naps after a few quiet minutes and drops the line.
            # If that's what happened, dial again once and retry. Otherwise it's a real error.
            if not (conn.closed or conn.broken):
                raise
            online_connection.clear()
            return _execute(online_connection(), sql, params, fetch)
    # Laptop test copy: a local file, fast enough to open each time.
    conn = sqlite3.connect(TEST_DB_FILE)
    try:
        return _execute(conn, sql.replace("%s", "?"), params, fetch)
    finally:
        conn.close()


def create_tables():
    """Make the two tables the first time the app starts. Does nothing after that."""
    id_col = "SERIAL PRIMARY KEY" if USING_ONLINE_DB else "INTEGER PRIMARY KEY AUTOINCREMENT"
    run(f"""
        CREATE TABLE IF NOT EXISTS employees (
            id {id_col},
            name TEXT NOT NULL,
            username TEXT NOT NULL UNIQUE,
            pw_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'employee',
            active INTEGER NOT NULL DEFAULT 1,
            must_change_pw INTEGER NOT NULL DEFAULT 0,
            failed_tries INTEGER NOT NULL DEFAULT 0,
            locked_until TEXT
        )""")
    run(f"""
        CREATE TABLE IF NOT EXISTS requests (
            id {id_col},
            kind TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            employee_id INTEGER NOT NULL,
            coworker_id INTEGER,
            reason TEXT,
            status TEXT NOT NULL,
            manager_note TEXT,
            created_at TEXT NOT NULL,
            decided_at TEXT
        )""")
    # Days (or stretches of days) nobody can request off. Trades are still allowed.
    run(f"""
        CREATE TABLE IF NOT EXISTS blackouts (
            id {id_col},
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            label TEXT
        )""")
    # Each person's email for request updates (optional). Older databases get it added here.
    if USING_ONLINE_DB:
        run("ALTER TABLE employees ADD COLUMN IF NOT EXISTS email TEXT")
    else:
        try:
            run("ALTER TABLE employees ADD COLUMN email TEXT")
        except sqlite3.OperationalError:
            pass  # already added


def upcoming_blackouts():
    """Blackouts that haven't ended yet, soonest first."""
    return run("SELECT * FROM blackouts WHERE end_date >= %s ORDER BY start_date",
               (date.today().isoformat(),), fetch=True)


def blackout_line(b):
    """'Thu, Dec 31 (NYE)' — one blackout in plain words."""
    text = nice_range(b)
    return f"{text} ({b['label']})" if b.get("label") else text


def blackout_days(blackouts):
    """Every single blacked-out date, e.g. {date(2026,12,31): 'NYE', ...}."""
    days = {}
    for b in blackouts:
        d, end = date.fromisoformat(b["start_date"]), date.fromisoformat(b["end_date"])
        while d <= end:
            days[d] = b.get("label") or "Blackout"
            d += timedelta(1)
    return days


def pick_day(d, who=""):
    """What happens when someone taps a day on the calendar.
    First tap = first day. Second tap = last day. A third tap starts over.
    'who' keeps the staff calendar and the manager blackout calendar separate."""
    start, end = st.session_state.get(who + "pick_start"), st.session_state.get(who + "pick_end")
    if start is None or end is not None or d < start:
        st.session_state[who + "pick_start"], st.session_state[who + "pick_end"] = d, None
    else:
        st.session_state[who + "pick_end"] = d


def picked_days(who=""):
    """(first, last) the person has tapped, or (None, None)."""
    first = st.session_state.get(who + "pick_start")
    return first, st.session_state.get(who + "pick_end") or first


def clear_picks(who=""):
    st.session_state[who + "pick_start"] = st.session_state[who + "pick_end"] = None


def shift_month(step, who=""):
    m = st.session_state[who + "cal_month"]
    m = (m + timedelta(32)).replace(day=1) if step > 0 else (m - timedelta(1)).replace(day=1)
    st.session_state[who + "cal_month"] = m


def tap_calendar(blacked, who="", picked_label="Your days off"):
    """One month of tappable days, with arrows to change months.
    Blackout days are black and can't be tapped; closed and past days are faded."""
    first_month = date.today().replace(day=1)
    month = st.session_state.setdefault(who + "cal_month", first_month)
    start, end = picked_days(who)
    # Month name with arrows to go back and forward
    with st.container(key=who + "offnav"):
        prev, title, nxt = st.columns([1, 4, 1], vertical_alignment="center")
        prev.button("‹", key=who + "cal_prev", on_click=shift_month, args=(-1, who),
                    disabled=month <= first_month, width="stretch")
        title.markdown(f'<div class="cal-month">{month:%B %Y}</div>', unsafe_allow_html=True)
        nxt.button("›", key=who + "cal_next", on_click=shift_month, args=(1, who), width="stretch")
    # The days, 7 across
    with st.container(key=who + "offcal"):
        st.markdown('<div class="cal-week"><div>S</div><div>M</div><div>T</div><div>W</div>'
                    '<div>T</div><div>F</div><div>S</div></div>', unsafe_allow_html=True)
        for week in calendar.Calendar(firstweekday=6).monthdatescalendar(month.year, month.month):
            cols = st.columns(7)
            for col, d in zip(cols, week):
                if d.month != month.month:
                    continue  # leave the box empty for days from other months
                key = f"{who}day{d:%Y%m%d}"
                if d in blacked:
                    col.button(str(d.day), key=key, type="tertiary", disabled=True,
                               help=blacked[d], width="stretch")
                elif d < date.today() or d.weekday() not in OPEN_DAYS:
                    col.button(str(d.day), key=key, disabled=True, width="stretch")
                else:
                    picked = start is not None and start <= d <= end
                    col.button(str(d.day), key=key, type="primary" if picked else "secondary",
                               on_click=pick_day, args=(d, who), width="stretch")
    st.markdown(f'<div class="cal-key"><span style="background:#AE834A"></span>{picked_label}'
                '<span style="background:#070909"></span>Blackout — no requests off</div>',
                unsafe_allow_html=True)


def make_first_manager():
    """If nobody is a manager yet, create the first manager login from the secrets."""
    if run("SELECT id FROM employees WHERE role = 'manager'", fetch=True):
        return
    username = get_secret("MANAGER_USERNAME").strip().lower()
    password = get_secret("MANAGER_PASSWORD")
    if username and password:
        run("INSERT INTO employees (name, username, pw_hash, role, must_change_pw) "
            "VALUES (%s, %s, %s, 'manager', 1)",
            ("Manager", username, scramble(password)))


# ---------------------------------------------------------------------------
# Codes and passwords — stored scrambled, so nobody (managers included) can read them.
# ---------------------------------------------------------------------------
def scramble(secret):
    return bcrypt.hashpw(secret.encode(), bcrypt.gensalt()).decode()


def matches(secret, scrambled):
    return bcrypt.checkpw(secret.encode(), scrambled.encode())


def random_code():
    return "".join(pyrandom.choice("0123456789") for _ in range(4))


def is_code(text):
    return len(text) == 4 and text.isdigit()


def try_login(person, secret):
    """Check a code/password, counting wrong tries. Returns (ok, message)."""
    if person["locked_until"] and person["locked_until"] > now_text():
        return False, "Too many wrong tries. Wait 15 minutes or ask a manager to reset your code."
    if matches(secret, person["pw_hash"]):
        run("UPDATE employees SET failed_tries = 0, locked_until = NULL WHERE id = %s",
            (person["id"],))
        return True, ""
    tries = person["failed_tries"] + 1
    if tries >= MAX_TRIES:
        until = (datetime.now() + timedelta(minutes=LOCK_MINUTES)).strftime("%Y-%m-%d %H:%M")
        run("UPDATE employees SET failed_tries = 0, locked_until = %s WHERE id = %s",
            (until, person["id"]))
        return False, "Too many wrong tries. Wait 15 minutes or ask a manager to reset your code."
    run("UPDATE employees SET failed_tries = %s WHERE id = %s", (tries, person["id"]))
    return False, f"That's not right. {MAX_TRIES - tries} tries left."


# ---------------------------------------------------------------------------
# Alert email to the managers
# ---------------------------------------------------------------------------
# Where staff replies go when they hit Reply on any email from the site.
REPLY_TO = "jpascolla@1913roselle.com"
SENDER_NAME = "1913 Staff Requests"


def send_email(to, subject, body, link_text="", reply_to=None):
    """Send one email through the site's Gmail. Returns None if it went out,
    otherwise a short note saying what went wrong."""
    user = get_secret("GMAIL_USER")
    app_pw = get_secret("GMAIL_APP_PASSWORD").replace(" ", "")
    if not (user and app_pw):
        return "NOT SET UP"
    link = get_secret("APP_URL")
    msg = EmailMessage()
    msg["From"] = formataddr((SENDER_NAME, user))  # shows as "1913 Staff Requests"
    msg["To"] = to
    if reply_to:
        msg["Reply-To"] = reply_to
    msg["Subject"] = subject
    msg.set_content(body + (f"\n\n{link_text}: {link}" if link and link_text else ""))
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx, timeout=30) as s:
            s.login(user, app_pw)
            s.send_message(msg)
        return None
    except Exception as e:
        return str(e)


def email_managers(subject, body):
    """Send the managers an alert. If email isn't set up, just say so on screen."""
    to = get_secret("ALERT_TO")
    problem = send_email(to, subject, body, link_text="Approve or deny") if to else "NOT SET UP"
    if problem == "NOT SET UP":
        notice("info", "(Email alerts are not set up on this copy, so no alert was sent.)")
    elif problem:
        # The request is already saved; managers will still see it when they log in.
        notice("warning", f"Your request was saved, but the alert email to the manager failed: {problem}")


def email_staff(emp_id, subject, body):
    """Email one staff member, if they've given us an email. Quietly skips if they haven't."""
    rows = run("SELECT name, email FROM employees WHERE id = %s", (emp_id,), fetch=True)
    if not rows or not rows[0].get("email"):
        return
    problem = send_email(rows[0]["email"], subject, body, link_text="Open 1913 Staff Requests",
                         reply_to=REPLY_TO)
    if problem == "NOT SET UP":
        notice("info", f"(Email to {rows[0]['name']} skipped — email isn't set up on this copy.)")
    elif problem:
        notice("warning", f"Saved, but the email to {rows[0]['name']} didn't go out: {problem}")


def looks_like_email(text):
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", text))


def save_email(emp_id, name, email):
    """Store someone's email and send them a 'you're set up' message to prove it works.
    Returns (ok, message) for the screen."""
    run("UPDATE employees SET email = %s WHERE id = %s", (email, emp_id))
    problem = send_email(
        email, "You're set up for 1913 request updates",
        f"Hi {name.split()[0]},\n\nYou'll now get an email from 1913 Staff Requests when:\n"
        "  - a manager approves or denies your request\n"
        "  - a coworker offers you a shift\n"
        "  - a coworker answers your shift offer\n\n"
        "If you didn't set this up, just reply to this email.",
        link_text="Open 1913 Staff Requests", reply_to=REPLY_TO)
    if problem == "NOT SET UP":
        return True, "Email saved. (Test email skipped — email isn't set up on this copy.)"
    if problem:
        return False, f"Email saved, but the test email didn't go out — check the spelling. ({problem})"
    return True, ("Email saved. We just sent a test email — if it isn't there in a few minutes, "
                  "check spam or the spelling.")


def notice(kind, text):
    """Save a message to show at the top of the next screen, so it survives a page refresh."""
    st.session_state.setdefault("notices", []).append((kind, text))


def show_notices():
    for kind, text in st.session_state.pop("notices", []):
        getattr(st, kind)(text)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def next_open_day():
    d = date.today()
    while d.weekday() not in OPEN_DAYS:
        d += timedelta(1)
    return d


def nice_date(text):
    """'2026-12-05' -> 'Sat, Dec 5'"""
    d = date.fromisoformat(text)
    return f"{d:%a, %b} {d.day}"


def nice_range(req):
    if req["start_date"] == req["end_date"]:
        return nice_date(req["start_date"])
    return f"{nice_date(req['start_date'])} – {nice_date(req['end_date'])}"


_NAMES = None  # everyone's name, looked up once per screen instead of once per row


def name_of(emp_id):
    global _NAMES
    if _NAMES is None:
        _NAMES = {r["id"]: r["name"] for r in run("SELECT id, name FROM employees", fetch=True)}
    return _NAMES.get(emp_id, "?")


def staff_list(exclude_id=None):
    rows = run("SELECT * FROM employees WHERE active = 1 AND role = 'employee' ORDER BY name",
               fetch=True)
    return [r for r in rows if r["id"] != exclude_id]


def describe(req):
    """One plain line describing a request, used in emails and the manager history."""
    who = name_of(req["employee_id"])
    if req["kind"] == "off":
        line = f"{who} wants OFF {nice_range(req)}"
    else:
        line = f"{who} wants {name_of(req['coworker_id'])} to take their shift {nice_range(req)}"
    if req.get("reason"):
        line += f' — "{req["reason"]}"'
    return line


def request_card(req, viewer_id=None, extra_note=""):
    """Draw one request as a white card with a colored status tag."""
    label, color = STATUS[req["status"]]
    if req["kind"] == "off":
        title = f"Off — {name_of(req['employee_id'])}" if viewer_id is None else "Day off"
    elif viewer_id == req["coworker_id"]:
        title = f"Taking {name_of(req['employee_id'])}'s shift"
    elif viewer_id == req["employee_id"]:
        title = f"Giving shift to {name_of(req['coworker_id'])}"
    else:
        title = f"Trade — {name_of(req['employee_id'])} → {name_of(req['coworker_id'])}"
    html = (f'<span class="chip" style="background:{color}">{label}</span>'
            f'<div class="when">{nice_range(req)}</div>'
            f'<div class="muted">{escape(title)}</div>')
    if req.get("reason"):
        html += f'<div class="muted">“{escape(req["reason"])}”</div>'
    if req.get("manager_note"):
        html += f'<div class="muted"><b>Manager:</b> {escape(req["manager_note"])}</div>'
    if extra_note:
        html += f'<div class="muted">{escape(extra_note)}</div>'
    st.markdown(html, unsafe_allow_html=True)


def go(page):
    st.session_state.page = page
    st.rerun()


def back_button():
    if st.button("← Back"):
        go("home")


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------
def login_screen():
    staff = staff_list()
    st.markdown("### Who are you?")
    with st.form("staff_login"):
        names = [s["name"] for s in staff]
        picked = st.selectbox("Your name", names, index=None, placeholder="Pick your name")
        code = st.text_input("Your 4-digit code", type="password", max_chars=4)
        if st.form_submit_button("Log in", type="primary", width="stretch"):
            if picked is None:
                st.error("Pick your name first.")
            else:
                person = next(s for s in staff if s["name"] == picked)
                ok, message = try_login(person, code)
                if ok:
                    st.session_state.user_id = person["id"]
                    go("home")
                st.error(message)

    with st.expander("Manager login"):
        # Managers pick their name from a list instead of typing a username.
        managers = run("SELECT * FROM employees WHERE role = 'manager' AND active = 1 "
                       "ORDER BY name", fetch=True)
        with st.form("manager_login"):
            picked_mgr = st.selectbox("Manager", [m["name"] for m in managers], index=None,
                                      placeholder="Pick your name")
            password = st.text_input("Password", type="password")
            if st.form_submit_button("Log in as manager", width="stretch"):
                if picked_mgr is None:
                    st.error("Pick your name first.")
                else:
                    person = next(m for m in managers if m["name"] == picked_mgr)
                    ok, message = try_login(person, password)
                    if ok:
                        st.session_state.user_id = person["id"]
                        go("home")
                    st.error(message)


def change_password_form(user, forced):
    """Manager-only: change your own password."""
    if forced:
        st.markdown(f"### Welcome, {user['name']}")
        st.write("Pick your own password before you go on.")
    with st.form("change_pw"):
        new1 = st.text_input("New password", type="password")
        new2 = st.text_input("Type it again", type="password")
        if st.form_submit_button("Save password", type="primary"):
            if len(new1) < 8:
                st.error("Use at least 8 characters.")
            elif new1 != new2:
                st.error("The two don't match.")
            else:
                run("UPDATE employees SET pw_hash = %s, must_change_pw = 0 WHERE id = %s",
                    (scramble(new1), user["id"]))
                st.success("Password saved.")
                st.rerun()


# ---------------------------------------------------------------------------
# Staff screens: a home menu with big buttons, one page per job.
# ---------------------------------------------------------------------------
def staff_home(user):
    offers = run("SELECT id FROM requests WHERE coworker_id = %s AND status = 'waiting_coworker'",
                 (user["id"],), fetch=True)
    first_name = user["name"].split()[0]
    st.markdown(f"## Hi, {escape(first_name)}")
    st.markdown('<p class="muted">What do you need?</p>', unsafe_allow_html=True)
    if st.button("🗓️  Request a day off", type="primary", width="stretch"):
        go("off")
    if st.button("🔁  Trade a shift", type="primary", width="stretch"):
        go("trade")
    offer_label = f"🙋  Shifts offered to me ({len(offers)})" if offers else "🙋  Shifts offered to me"
    if st.button(offer_label, width="stretch"):
        go("offers")
    if st.button("📋  My requests", width="stretch"):
        go("mine")
    email_label = "✉️  Email updates: on" if user.get("email") else "✉️  Get email updates"
    if st.button(email_label, width="stretch"):
        go("email")


def page_email(user):
    back_button()
    st.markdown("## Email updates")
    st.markdown('<p class="muted">Get an email when a manager approves or denies your request, '
                'when a coworker offers you a shift, and when someone answers your shift offer.</p>',
                unsafe_allow_html=True)
    current = user.get("email") or ""
    with st.form("email_form"):
        new = st.text_input("Your email", value=current, placeholder="you@example.com").strip()
        if st.form_submit_button("Save", type="primary", width="stretch"):
            if not looks_like_email(new):
                st.error("That doesn't look like an email address.")
            else:
                ok, message = save_email(user["id"], user["name"], new)
                notice("success" if ok else "warning", message)
                st.rerun()
    if current and st.button("Stop email updates", width="stretch"):
        run("UPDATE employees SET email = NULL WHERE id = %s", (user["id"],))
        notice("success", "Email updates turned off.")
        st.rerun()


def page_request_off(user):
    back_button()
    st.markdown("## Request a day off")
    blackouts = upcoming_blackouts()

    st.markdown('<p class="muted">Tap your first day off, then your last day off. '
                'One day? Just tap it once.</p>', unsafe_allow_html=True)
    tap_calendar(blackout_days(blackouts))
    if blackouts:
        st.markdown('<p class="muted"><b>Blackout days:</b> ' +
                    "; ".join(escape(blackout_line(b)) for b in blackouts) + "</p>",
                    unsafe_allow_html=True)

    first, last = picked_days()
    with st.container(border=True):
        if first is None:
            st.markdown('<p class="muted">No days picked yet.</p>', unsafe_allow_html=True)
            problem = "pick"
        else:
            picked = dict(start_date=first.isoformat(), end_date=last.isoformat())
            st.markdown(f'<div class="when">Off: {nice_range(picked)}</div>', unsafe_allow_html=True)
            problem = ""
            # A range can run across a blackout even though the blackout day itself can't be tapped.
            if hits := [b for b in blackouts if b["start_date"] <= last.isoformat()
                        and b["end_date"] >= first.isoformat()]:
                problem = ("Those days run into a blackout — no requests off: " +
                           "; ".join(blackout_line(b) for b in hits))
                st.error(problem)
            if st.button("Clear", key="pick_clear"):
                clear_picks()
                st.rerun()
        rnd = st.session_state.get("off_round", 0)
        reason = st.text_input("Reason (optional)", key=f"off_reason{rnd}")
        # Send stays switched off until good days are picked, so nothing bad gets saved.
        if st.button("Send to manager", type="primary", width="stretch",
                     disabled=bool(problem), key="off_send"):
            req = dict(kind="off", start_date=first.isoformat(), end_date=last.isoformat(),
                       employee_id=user["id"], coworker_id=None, reason=reason.strip())
            run("INSERT INTO requests (kind, start_date, end_date, employee_id, reason, "
                "status, created_at) VALUES ('off', %s, %s, %s, %s, 'waiting_joe', %s)",
                (req["start_date"], req["end_date"], user["id"], req["reason"], now_text()))
            email_managers(f"Request off: {user['name']} {nice_range(req)}", describe(req))
            notice("success", "Sent. A manager will approve or deny it — check My requests.")
            clear_picks()
            st.session_state.off_round = rnd + 1
            st.rerun()


def page_trade(user):
    back_button()
    st.markdown("## Trade a shift")
    coworkers = staff_list(exclude_id=user["id"])
    if not coworkers:
        st.write("No coworkers are set up yet.")
        return
    with st.container(border=True):
        shift = st.date_input("Your shift to give away", value=next_open_day(),
                              min_value=date.today(), format="MM/DD/YYYY", key="trade_date")
        closed = shift.weekday() not in OPEN_DAYS
        if closed:
            st.warning(f"We're closed {shift:%A}s — pick a Tuesday through Saturday.")
        names = {c["name"]: c["id"] for c in coworkers}
        who = st.selectbox("Who is taking it?", list(names), index=None,
                           placeholder="Pick a coworker")
        note = st.text_input("Note (optional)", key="trade_note")
        st.markdown('<p class="muted">They have to accept it before it goes to a manager. '
                    'Tell them to log in and check “Shifts offered to me.”</p>',
                    unsafe_allow_html=True)
        if st.button("Send offer", type="primary", width="stretch",
                     disabled=closed or who is None):
            run("INSERT INTO requests (kind, start_date, end_date, employee_id, coworker_id, "
                "reason, status, created_at) VALUES ('trade', %s, %s, %s, %s, %s, "
                "'waiting_coworker', %s)",
                (shift.isoformat(), shift.isoformat(), user["id"], names[who],
                 note.strip(), now_text()))
            when = nice_date(shift.isoformat())
            email_staff(names[who], f"{user['name']} offered you a shift: {when}",
                        f"{user['name']} wants you to take their shift on {when}."
                        + (f'\nTheir note: "{note.strip()}"' if note.strip() else "")
                        + "\n\nLog in and tap \"Shifts offered to me\" to accept or decline.")
            notice("success", f"Offer sent to {who}. They have to accept it before it goes to a manager.")
            st.rerun()


def page_offers(user):
    back_button()
    st.markdown("## Shifts offered to me")
    offers = run("SELECT * FROM requests WHERE coworker_id = %s AND status = 'waiting_coworker' "
                 "ORDER BY start_date", (user["id"],), fetch=True)
    if not offers:
        st.write("Nobody has offered you a shift.")
    for req in offers:
        with st.container(border=True):
            request_card(req, viewer_id=user["id"])
            col_yes, col_no = st.columns(2)
            if col_yes.button("Accept", key=f"acc{req['id']}", type="primary", width="stretch"):
                run("UPDATE requests SET status = 'waiting_joe' WHERE id = %s", (req["id"],))
                email_managers(f"Shift trade: {name_of(req['employee_id'])} → {user['name']} "
                          f"{nice_range(req)}", describe(req) + f"\n{user['name']} accepted.")
                email_staff(req["employee_id"], f"{user['name']} accepted your shift: {nice_range(req)}",
                            f"{user['name']} said yes to taking your shift on {nice_range(req)}.\n\n"
                            "It now goes to a manager to approve. You'll get another email when they decide.")
                st.rerun()
            if col_no.button("Decline", key=f"dec{req['id']}", width="stretch"):
                run("UPDATE requests SET status = 'coworker_declined', decided_at = %s "
                    "WHERE id = %s", (now_text(), req["id"]))
                email_staff(req["employee_id"], f"{user['name']} declined your shift: {nice_range(req)}",
                            f"{user['name']} said no to taking your shift on {nice_range(req)}.\n\n"
                            "The shift is still yours. You can offer it to someone else.")
                st.rerun()


def page_mine(user):
    back_button()
    st.markdown("## My requests")
    mine = run("SELECT * FROM requests WHERE employee_id = %s OR coworker_id = %s "
               "ORDER BY id DESC LIMIT 30", (user["id"], user["id"]), fetch=True)
    if not mine:
        st.write("No requests yet.")
    for req in mine:
        with st.container(border=True):
            request_card(req, viewer_id=user["id"])
            still_open = req["status"] in ("waiting_coworker", "waiting_joe")
            if still_open and req["employee_id"] == user["id"]:
                if st.button("Cancel this request", key=f"can{req['id']}"):
                    run("UPDATE requests SET status = 'cancelled', decided_at = %s WHERE id = %s",
                        (now_text(), req["id"]))
                    st.rerun()


# ---------------------------------------------------------------------------
# Manager screen
# ---------------------------------------------------------------------------
def tell_staff_decision(req, status, note):
    """Email the staff involved once a manager approves or denies."""
    word = "APPROVED" if status == "approved" else "DENIED"
    note_line = f'\n\nNote from the manager: "{note}"' if note else ""
    when = nice_range(req)
    if req["kind"] == "off":
        email_staff(req["employee_id"], f"Your request off {when}: {word.title()}",
                    f"Your request off for {when} was {word}.{note_line}")
    else:
        giver, taker = name_of(req["employee_id"]), name_of(req["coworker_id"])
        result = (f"{taker} is working it." if status == "approved"
                  else f"The shift stays with {giver}.")
        for emp_id in (req["employee_id"], req["coworker_id"]):
            email_staff(emp_id, f"Shift trade {when}: {word.title()}",
                        f"The shift trade on {when} — {taker} taking {giver}'s shift — "
                        f"was {word}. {result}{note_line}")


def manager_screen(user):
    pending = run("SELECT * FROM requests WHERE status = 'waiting_joe' ORDER BY start_date",
                  fetch=True)
    st.markdown("## Manager")
    tab_pending, tab_all, tab_blackout, tab_staff = st.tabs(
        [f"Waiting on you ({len(pending)})", "History", "Blackout days", "Staff"])

    # --- Blackout days: dates nobody can request off --------------------------
    with tab_blackout:
        st.markdown('<p class="muted">Staff can\'t request these days off. '
                    'Shift trades are still allowed.</p>', unsafe_allow_html=True)
        st.markdown('<p class="muted">Tap the first day, then the last day. '
                    'One day? Just tap it once.</p>', unsafe_allow_html=True)
        tap_calendar(blackout_days(upcoming_blackouts()), who="blk_", picked_label="New blackout")
        b_first, b_last = picked_days("blk_")
        with st.container(border=True):
            if b_first is None:
                st.markdown('<p class="muted">No days picked yet.</p>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div class="when">Black out: '
                            f'{nice_range(dict(start_date=b_first.isoformat(), end_date=b_last.isoformat()))}'
                            f'</div>', unsafe_allow_html=True)
                if st.button("Clear", key="blk_clear"):
                    clear_picks("blk_")
                    st.rerun()
            b_round = st.session_state.get("blk_round", 0)
            b_label = st.text_input("Label (optional) — e.g. NYE, Valentine's", key=f"blk_label{b_round}")
            if st.button("Add blackout", type="primary", disabled=b_first is None, key="blk_add"):
                run("INSERT INTO blackouts (start_date, end_date, label) VALUES (%s, %s, %s)",
                    (b_first.isoformat(), b_last.isoformat(), b_label.strip()))
                notice("success", "Blackout added.")
                clear_picks("blk_")
                st.session_state.blk_round = b_round + 1
                st.rerun()
        blackouts = upcoming_blackouts()
        if not blackouts:
            st.write("No blackout days coming up.")
        for b in blackouts:
            # Keep the date and its Remove button on one line, even on phones
            col_text, col_btn = st.container(key=f"blkrow{b['id']}").columns(
                [2, 1], vertical_alignment="center")
            col_text.markdown(f"**{escape(blackout_line(b))}**")
            if col_btn.button("Remove", key=f"unblack{b['id']}", width="stretch"):
                run("DELETE FROM blackouts WHERE id = %s", (b["id"],))
                st.rerun()

    # --- Requests waiting on a manager----------------------------------------
    with tab_pending:
        if not pending:
            st.write("Nothing waiting on you.")
        for req in pending:
            with st.container(border=True):
                request_card(req, extra_note=f"Sent {req['created_at']}")
                note = st.text_input("Note back to them (optional)", key=f"note{req['id']}")
                col_yes, col_no = st.columns(2)
                for col, label, status, style in ((col_yes, "Approve", "approved", "primary"),
                                                  (col_no, "Deny", "denied", "secondary")):
                    if col.button(label, key=f"{status}{req['id']}", type=style, width="stretch"):
                        run("UPDATE requests SET status = %s, manager_note = %s, decided_at = %s "
                            "WHERE id = %s", (status, note.strip(), now_text(), req["id"]))
                        tell_staff_decision(req, status, note.strip())
                        st.rerun()

    # --- History ------------------------------------------------------------
    with tab_all:
        rows = run("SELECT * FROM requests ORDER BY start_date DESC LIMIT 200", fetch=True)
        st.dataframe(
            [{"Date": nice_range(r), "Type": "Off" if r["kind"] == "off" else "Trade",
              "Who": name_of(r["employee_id"]),
              "Covering": name_of(r["coworker_id"]) if r["coworker_id"] else "",
              "Status": STATUS[r["status"]][0], "Reason": r["reason"] or "",
              "Your note": r["manager_note"] or ""} for r in rows],
            hide_index=True, width="stretch")

    # --- Add and manage staff -----------------------------------------------
    with tab_staff:
        st.markdown("#### Add staff")
        st.markdown('<p class="muted">One per line: name, then a comma and their 4-digit code. '
                    'Leave the code off and one is picked for you.<br>'
                    'Example: <code>Maria Lopez, 4821</code></p>', unsafe_allow_html=True)
        with st.form("add_staff", clear_on_submit=True):
            lines = st.text_area("Names and codes")
            if st.form_submit_button("Add", type="primary"):
                created, problems = [], []
                for line in [x.strip() for x in lines.splitlines() if x.strip()]:
                    name, _, code = (p.strip() for p in line.partition(","))
                    code = code or random_code()
                    if not is_code(code):
                        problems.append(f"{name}: code must be exactly 4 numbers")
                        continue
                    if run("SELECT id FROM employees WHERE lower(name) = lower(%s)", (name,), fetch=True):
                        problems.append(f"{name}: already on the list")
                        continue
                    # A hidden username keeps every row unique; staff never see or type it.
                    username = "staff-" + pyrandom.token_hex(4)
                    run("INSERT INTO employees (name, username, pw_hash) VALUES (%s, %s, %s)",
                        (name, username, scramble(code)))
                    created.append({"Name": name, "Code": code})
                st.session_state.just_created = created
                st.session_state.problems = problems
        for p in st.session_state.get("problems", []):
            st.error(p)
        if st.session_state.get("just_created"):
            st.success("Added. Write these codes down — they can't be looked up later:")
            st.dataframe(st.session_state.just_created, hide_index=True, width="stretch")

        st.markdown("#### Everyone")
        staff = run("SELECT * FROM employees WHERE role = 'employee' ORDER BY active DESC, name",
                    fetch=True)
        for emp in staff:
            locked = emp["locked_until"] and emp["locked_until"] > now_text()
            label = (emp["name"] + (" ✉️" if emp.get("email") else "")
                     + ("" if emp["active"] else " — turned off") + (" 🔒" if locked else ""))
            with st.expander(label):
                # Their email for request updates — managers can add or fix it for them.
                new_email = st.text_input("Email for updates (blank = none)", value=emp.get("email") or "",
                                          key=f"email{emp['id']}").strip()
                if st.button("Save email", key=f"saveemail{emp['id']}"):
                    if not new_email:
                        run("UPDATE employees SET email = NULL WHERE id = %s", (emp["id"],))
                        notice("success", f"Email removed for {emp['name']}.")
                        st.rerun()
                    elif not looks_like_email(new_email):
                        st.error("That doesn't look like an email address.")
                    else:
                        ok, message = save_email(emp["id"], emp["name"], new_email)
                        notice("success" if ok else "warning", f"{emp['name']}: {message}")
                        st.rerun()
                new_code = st.text_input("New 4-digit code", max_chars=4, key=f"code{emp['id']}")
                col_save, col_toggle = st.columns(2)
                if col_save.button("Save code", key=f"save{emp['id']}", width="stretch"):
                    if is_code(new_code):
                        run("UPDATE employees SET pw_hash = %s, failed_tries = 0, "
                            "locked_until = NULL WHERE id = %s", (scramble(new_code), emp["id"]))
                        st.success(f"New code saved for {emp['name']}.")
                    else:
                        st.error("Code must be exactly 4 numbers.")
                toggle = "Turn off" if emp["active"] else "Turn back on"
                if col_toggle.button(toggle, key=f"tog{emp['id']}", width="stretch"):
                    run("UPDATE employees SET active = %s WHERE id = %s",
                        (0 if emp["active"] else 1, emp["id"]))
                    st.rerun()

        # --- Managers: anyone here can approve/deny and manage staff ---------
        st.markdown("#### Managers")
        managers = run("SELECT name FROM employees WHERE role = 'manager' "
                       "AND active = 1 ORDER BY name", fetch=True)
        st.markdown('<p class="muted">' + ", ".join(escape(m["name"]) for m in managers)
                    + "</p>", unsafe_allow_html=True)
        with st.expander("Add a manager"):
            with st.form("add_manager", clear_on_submit=True):
                m_name = st.text_input("Their name (as it shows in the login list)").strip()
                m_pw = st.text_input("Temporary password (8+ characters)", type="password")
                st.markdown('<p class="muted">They pick their own password the first time '
                            'they log in.</p>', unsafe_allow_html=True)
                if st.form_submit_button("Add manager", type="primary"):
                    if not m_name:
                        st.error("Fill in their name.")
                    elif len(m_pw) < 8:
                        st.error("Temporary password needs at least 8 characters.")
                    elif run("SELECT id FROM employees WHERE role = 'manager' AND active = 1 "
                             "AND lower(name) = lower(%s)", (m_name,), fetch=True):
                        st.error("There's already a manager with that name. Use a different one.")
                    else:
                        # A hidden username keeps every row unique; nobody types it.
                        m_user = "mgr-" + pyrandom.token_hex(4)
                        run("INSERT INTO employees (name, username, pw_hash, role, must_change_pw) "
                            "VALUES (%s, %s, %s, 'manager', 1)", (m_name, m_user, scramble(m_pw)))
                        st.success(f"{m_name} can now pick their name under Manager login.")

        with st.expander("Change my manager password"):
            change_password_form(user, forced=False)


# ---------------------------------------------------------------------------
# Start here
# ---------------------------------------------------------------------------
@st.cache_resource
def setup_once(setup_code):
    """Check the tables and first manager once, not on every tap.
    It's handed the text of create_tables(), so whenever an update changes
    the tables (like adding blackouts), setup runs again on its own —
    no reboot needed."""
    create_tables()
    make_first_manager()
    return True


apply_style()
setup_once(inspect.getsource(create_tables))

if not USING_ONLINE_DB:
    st.warning("TEST COPY — using a throwaway file on this computer, not the real database.")

user = None
if "user_id" in st.session_state:
    rows = run("SELECT * FROM employees WHERE id = %s", (st.session_state.user_id,), fetch=True)
    user = rows[0] if rows and rows[0]["active"] else None

show_notices()
if user is None:
    login_screen()
else:
    if user["must_change_pw"]:
        change_password_form(user, forced=True)
    elif user["role"] == "manager":
        manager_screen(user)
    else:
        page = st.session_state.get("page", "home")
        {"home": staff_home, "off": page_request_off, "trade": page_trade,
         "offers": page_offers, "mine": page_mine, "email": page_email}.get(page, staff_home)(user)

    # Log out sits at the bottom of every screen.
    st.divider()
    if st.button("Log out", width="stretch"):
        st.session_state.clear()
        st.rerun()
