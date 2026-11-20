import os
import io
import importlib
import uuid
import hmac
import hashlib
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import cv2
import numpy as np
import pandas as pd
import qrcode
import streamlit as st
import plotly.express as px
from PIL import Image, ImageDraw, ImageFont

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
PHOTO_DIR = os.path.join(APP_DIR, "student_photos")
QR_DIR = os.path.join(APP_DIR, "qr_codes")
DB_PATH = os.path.join(DATA_DIR, "attendance.db")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(PHOTO_DIR, exist_ok=True)
os.makedirs(QR_DIR, exist_ok=True)

SCHOOL_NAME = os.getenv("SCHOOL_NAME", "AG High School")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")

st.set_page_config(
    page_title="Smart QR Attendance",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
.stApp { background: #f4f7fc; }
.block-container { padding-top: 1.5rem; }
.hero {
  background: linear-gradient(120deg,#102e59,#2367ae);
  color: white; padding: 25px 28px; border-radius: 18px;
  margin-bottom: 18px;
}
.hero h1 { margin: 0; font-size: 30px; }
.hero p { margin: 8px 0 0; opacity: .9; }
.metric {
  background: white; border: 1px solid #e4eaf3;
  border-radius: 15px; padding: 17px 19px;
  box-shadow: 0 4px 14px rgba(25,55,95,.05);
}
.metric-label { color:#65758b; font-size:13px; }
.metric-value { color:#173d70; font-size:27px; font-weight:750; margin-top:5px; }
.panel {
  background:white; border:1px solid #e4eaf3; border-radius:15px;
  padding:18px; margin-bottom:12px;
}
div[data-testid="stSidebar"] { background:#102e59; }
div[data-testid="stSidebar"] * { color:white; }
</style>
""", unsafe_allow_html=True)


def db():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_db():
    with db() as con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS students (
            student_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            class_name TEXT NOT NULL,
            roll_number TEXT NOT NULL,
            dob TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            address TEXT DEFAULT '',
            leaving_place TEXT DEFAULT '',
            district TEXT DEFAULT '',
            state TEXT DEFAULT '',
            photo_file TEXT DEFAULT '',
            qr_token_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(class_name, roll_number)
        )
        """)
        con.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            attendance_id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            attendance_date TEXT NOT NULL,
            attendance_time TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Present',
            FOREIGN KEY(student_id) REFERENCES students(student_id),
            UNIQUE(student_id, attendance_date)
        )
        """)
        con.commit()


def local_now():
    return datetime.now(ZoneInfo("Asia/Kolkata"))


def hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def get_students():
    with db() as con:
        return pd.read_sql_query("""
        SELECT student_id, name, class_name, roll_number, dob, phone,
               address, leaving_place, district, state, photo_file, created_at
        FROM students ORDER BY class_name, roll_number
        """, con)


def get_student(student_id):
    with db() as con:
        cur = con.execute("""
        SELECT student_id, name, class_name, roll_number, dob, phone,
               address, leaving_place, district, state, photo_file, qr_token_hash
        FROM students WHERE student_id=?
        """, (student_id,))
        return cur.fetchone()


def create_qr(student_id, token):
    payload = f"SCHOOLATTENDANCE|{student_id}|{token}"
    image = qrcode.make(payload)
    path = os.path.join(QR_DIR, f"{student_id}.png")
    image.save(path)
    return path


def make_id_card(student):
    # student tuple: id,name,class,roll,dob,phone,address,place,district,state,photo,hash
    sid, name, cls, roll, dob, phone, address, place, district, state, photo, _ = student
    w, h = 1200, 720
    canvas = Image.new("RGB", (w, h), "#f2f6fc")
    draw = ImageDraw.Draw(canvas)
    try:
        f_title = ImageFont.truetype("DejaVuSans-Bold.ttf", 42)
        f_name = ImageFont.truetype("DejaVuSans-Bold.ttf", 32)
        f_body = ImageFont.truetype("DejaVuSans.ttf", 23)
        f_small = ImageFont.truetype("DejaVuSans.ttf", 18)
    except Exception:
        f_title = f_name = f_body = f_small = ImageFont.load_default()

    draw.rounded_rectangle((15, 15, w-15, h-15), radius=28,
                           fill="white", outline="#1e4f91", width=6)
    draw.rounded_rectangle((28, 28, w-28, 135), radius=20, fill="#123b70")
    draw.text((w//2, 80), SCHOOL_NAME, font=f_title, fill="white", anchor="mm")
    draw.text((55, 165), "STUDENT IDENTITY CARD", font=f_body, fill="#174477")

    if photo and os.path.exists(photo):
        try:
            im = Image.open(photo).convert("RGB")
            im.thumbnail((235, 285))
            canvas.paste(im, (55, 220))
        except Exception:
            pass
    else:
        draw.rounded_rectangle((55, 220, 290, 505), radius=14,
                               fill="#e8eef7", outline="#a9bbd2", width=3)
        draw.text((172, 360), "PHOTO", font=f_body, fill="#52677e", anchor="mm")

    draw.text((335, 215), name, font=f_name, fill="#123b70")
    lines = [
        f"Student ID: {sid}",
        f"Class / Division: {cls}",
        f"Roll Number: {roll}",
        f"Date of Birth: {dob or '-'}",
        f"Phone: {phone or '-'}",
        f"Address: {address or '-'}",
        f"Leaving Place: {place or '-'}",
        f"District: {district or '-'}",
        f"State: {state or '-'}",
    ]
    y = 270
    for line in lines:
        draw.text((335, y), line[:65], font=f_body, fill="#243b56")
        y += 42

    qr_path = os.path.join(QR_DIR, f"{sid}.png")
    if os.path.exists(qr_path):
        qr = Image.open(qr_path).convert("RGB").resize((205, 205))
        canvas.paste(qr, (w-245, h-245))
        draw.text((w-142, h-28), "PRIVATE QR", font=f_small,
                  fill="#123b70", anchor="mm")
    return canvas


def decode_qr_image(uploaded):
    try:
        cv2 = importlib.import_module("cv2")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "QR scanning requires OpenCV. Install it with: pip install opencv-python-headless"
        ) from exc
    raw = uploaded.getvalue()
    arr = np.frombuffer(raw, np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image is None:
        return None
    detector = cv2.QRCodeDetector()
    value, points, _ = detector.detectAndDecode(image)
    return value or None


def record_attendance(payload):
    parts = payload.split("|")
    if len(parts) != 3 or parts[0] != "SCHOOLATTENDANCE":
        return False, "Invalid school QR code.", None

    _, student_id, token = parts
    student = get_student(student_id)
    if not student:
        return False, "Student record not found.", None

    if not hmac.compare_digest(student[11], hash_token(token)):
        return False, "QR verification failed.", None

    now = local_now()
    day = now.strftime("%Y-%m-%d")
    clock = now.strftime("%H:%M:%S")
    try:
        with db() as con:
            con.execute("""
            INSERT INTO attendance
            (student_id, attendance_date, attendance_time, status)
            VALUES (?, ?, ?, 'Present')
            """, (student_id, day, clock))
            con.commit()
        return True, f"Attendance marked at {clock}.", student
    except sqlite3.IntegrityError:
        return True, "Attendance was already marked today. Opening profile.", student


def attendance_frame(class_name=None, selected_date=None):
    query = """
    SELECT s.student_id, s.name, s.class_name, s.roll_number,
           a.attendance_date, a.attendance_time, a.status
    FROM attendance a JOIN students s ON s.student_id=a.student_id
    WHERE 1=1
    """
    params = []
    if class_name and class_name != "All classes":
        query += " AND s.class_name=?"
        params.append(class_name)
    if selected_date:
        query += " AND a.attendance_date=?"
        params.append(selected_date)
    query += " ORDER BY a.attendance_date DESC, a.attendance_time DESC"
    with db() as con:
        return pd.read_sql_query(query, con, params=params)


def admin_login():
    if not ADMIN_PASSWORD:
        st.error("Admin password is not set. Configure ADMIN_PASSWORD before using this app.")
        st.code('ADMIN_PASSWORD="choose-a-strong-password"')
        return False
    if st.session_state.get("admin_logged_in"):
        return True
    st.title("🔐 Administrator Login")
    password = st.text_input("Admin password", type="password")
    if st.button("Log in", type="primary"):
        if hmac.compare_digest(password, ADMIN_PASSWORD):
            st.session_state.admin_logged_in = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    return False


init_db()

st.sidebar.title("🎓 Smart Attendance")
st.sidebar.caption(SCHOOL_NAME)
page = st.sidebar.radio("Navigation", [
    "Dashboard", "Register Student", "Student Directory",
    "QR Scanner", "Attendance Records", "Reports", "Student Portal"
])
st.sidebar.markdown("---")
st.sidebar.caption("Private student information is visible only to authorized staff.")

st.markdown(f"""
<div class="hero">
  <h1>🏫 {SCHOOL_NAME}</h1>
  <p>Private QR Login • Automatic Attendance • Student Profiles</p>
</div>
""", unsafe_allow_html=True)

if page in ["Register Student", "Student Directory", "QR Scanner",
            "Attendance Records", "Reports"]:
    if not admin_login():
        st.stop()

if page == "Dashboard":
    students = get_students()
    today = local_now().strftime("%Y-%m-%d")
    todays = attendance_frame(selected_date=today)
    total = len(students)
    present = len(todays)
    pending = max(total - present, 0)
    percent = round(present / total * 100, 1) if total else 0

    st.subheader("📊 School Overview")
    cols = st.columns(4)
    metrics = [
        ("Total Students", total),
        ("Present Today", present),
        ("Not Marked Yet", pending),
        ("Attendance Rate", f"{percent}%")
    ]
    for col, (label, value) in zip(cols, metrics):
        col.markdown(
            f'<div class="metric"><div class="metric-label">{label}</div>'
            f'<div class="metric-value">{value}</div></div>',
            unsafe_allow_html=True
        )

    left, right = st.columns([1.1, 1])
    with left:
        st.subheader("Today's Attendance")
        if total:
            chart = pd.DataFrame({
                "Status": ["Present", "Not marked"],
                "Students": [present, pending]
            })
            st.plotly_chart(px.pie(chart, names="Status", values="Students",
                                   hole=.58, color_discrete_sequence=["#2376c8", "#dce5f1"]),
                            use_container_width=True)
        else:
            st.info("Register students to see dashboard analytics.")
    with right:
        st.subheader("Recent Attendance")
        recent = attendance_frame().head(8)
        st.dataframe(recent, use_container_width=True, hide_index=True)
    st.caption("“Not marked yet” does not mean confirmed absent. Finalize attendance before recording absences.")

elif page == "Register Student":
    st.subheader("➕ Register a Student")
    st.write("Enter student information. A unique private QR code will be generated.")
    with st.form("register_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            name = st.text_input("Student full name *")
            class_name = st.text_input("Class / Division *", placeholder="6th A")
            roll = st.text_input("Roll number *")
            dob = st.text_input("Date of birth", placeholder="DD/MM/YYYY")
            phone = st.text_input("Phone number")
        with c2:
            leaving_place = st.text_input("Leaving place / Village")
            district = st.text_input("District")
            state = st.text_input("State", value="Maharashtra")
            address = st.text_area("Full address")
            photo_upload = st.file_uploader("Student photo (optional)", type=["png", "jpg", "jpeg"])
        submitted = st.form_submit_button("Register & Generate Private QR", type="primary")
    if submitted:
        if not name.strip() or not class_name.strip() or not roll.strip():
            st.error("Name, class and roll number are required.")
        else:
            sid = str(uuid.uuid4())
            token = secrets_token = uuid.uuid4().hex + uuid.uuid4().hex
            photo_path = ""
            if photo_upload:
                ext = os.path.splitext(photo_upload.name)[1].lower()
                photo_path = os.path.join(PHOTO_DIR, sid + ext)
                with open(photo_path, "wb") as f:
                    f.write(photo_upload.getbuffer())
            try:
                with db() as con:
                    con.execute("""
                    INSERT INTO students
                    (student_id,name,class_name,roll_number,dob,phone,address,
                     leaving_place,district,state,photo_file,qr_token_hash,created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """, (sid, name.strip(), class_name.strip(), roll.strip(),
                          dob.strip(), phone.strip(), address.strip(),
                          leaving_place.strip(), district.strip(), state.strip(),
                          photo_path, hash_token(token),
                          local_now().isoformat()))
                    con.commit()
                qr_path = create_qr(sid, token)
                st.success("Student registered and private QR generated.")
                student = get_student(sid)
                card = make_id_card(student)
                buf = io.BytesIO()
                card.save(buf, format="PNG")
                st.image(card, caption="Student ID card preview", use_container_width=True)
                st.download_button("⬇️ Download Student ID Card (PNG)",
                                   data=buf.getvalue(),
                                   file_name=f"Student_ID_{roll}.png",
                                   mime="image/png")
                with open(qr_path, "rb") as f:
                    st.download_button("⬇️ Download Private QR Code",
                                       data=f.read(), file_name=f"QR_{roll}.png",
                                       mime="image/png")
                st.warning("Keep the QR image private. If it is copied, someone else may be able to present it. Use teacher verification at the school gate.")
            except sqlite3.IntegrityError:
                st.error("That roll number is already registered in this class.")

elif page == "Student Directory":
    st.subheader("👨‍🎓 Student Directory")
    df = get_students()
    if not df.empty:
        search = st.text_input("Search by name, ID, class or roll number")
        if search:
            mask = df.astype(str).apply(
                lambda col: col.str.contains(search, case=False, na=False)
            ).any(axis=1)
            df = df[mask]
        st.dataframe(df.drop(columns=["photo_file"], errors="ignore"),
                     use_container_width=True, hide_index=True)
        ids = df["student_id"].tolist()
        if ids:
            chosen = st.selectbox("Choose student for ID card", ids,
                                  format_func=lambda x: f"{df.loc[df.student_id==x, 'name'].iloc[0]} — {x[:8]}")
            if st.button("Create / View ID Card"):
                student = get_student(chosen)
                card = make_id_card(student)
                st.image(card, use_container_width=True)
                buf = io.BytesIO()
                card.save(buf, format="PNG")
                st.download_button("Download ID Card PNG", buf.getvalue(),
                                   file_name=f"ID_{chosen[:8]}.png", mime="image/png")
    else:
        st.info("No students registered yet.")

elif page == "QR Scanner":
    st.subheader("📷 Scan Student QR")
    st.write("Upload a clear photo or screenshot of the student's private QR code.")
    uploaded = st.file_uploader("Upload QR image", type=["png", "jpg", "jpeg"])
    if uploaded and st.button("Verify QR & Mark Attendance", type="primary"):
        try:
            payload = decode_qr_image(uploaded)
        except RuntimeError as exc:
            st.error(str(exc))
        else:
            if not payload:
                st.error("Could not read a QR code. Try a sharper, well-lit image.")
            else:
                ok, message, student = record_attendance(payload)
                if not ok:
                    st.error(message)
                else:
                    st.success(message)
                    st.markdown("### Student Dashboard")
                    st.markdown(f"## {student[1]}")
                    a, b, c = st.columns(3)
                    a.metric("Class", student[2])
                    b.metric("Roll Number", student[3])
                    b2 = student[0]
                    with db() as con:
                        hist = pd.read_sql_query("""
                        SELECT attendance_date, attendance_time, status
                        FROM attendance WHERE student_id=?
                        ORDER BY attendance_date DESC
                        """, con, params=(b2,))
                    c.metric("Present days", int((hist.status == "Present").sum()))
                    st.write("**Student ID:**", student[0])
                    st.write("**Phone:**", student[5] or "Not provided")
                    st.write("**Leaving place:**", student[8] or "Not provided")
                    st.write("**District / State:**", f"{student[9] or '-'} / {student[10] or '-'}")
                    st.dataframe(hist, use_container_width=True, hide_index=True)

elif page == "Attendance Records":
    st.subheader("🗓️ Attendance Records")
    students = get_students()
    classes = ["All classes"] + sorted(students.class_name.dropna().unique().tolist()) if not students.empty else ["All classes"]
    f1, f2 = st.columns(2)
    class_choice = f1.selectbox("Filter class", classes)
    date_choice = f2.date_input("Filter date", value=local_now().date())
    records = attendance_frame(class_choice, date_choice.strftime("%Y-%m-%d"))
    st.dataframe(records, use_container_width=True, hide_index=True)
    st.caption("Only recorded attendance entries appear here. Students not listed are not automatically classified as absent.")

elif page == "Reports":
    st.subheader("📈 Reports & Excel Export")
    students = get_students()
    records = attendance_frame()
    if not records.empty:
        st.plotly_chart(px.histogram(records, x="attendance_date",
                                     color="class_name", barmode="group",
                                     title="Attendance by date and class"),
                        use_container_width=True)
    else:
        st.info("No attendance records available yet.")
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        students.drop(columns=["photo_file"], errors="ignore").to_excel(
            writer, index=False, sheet_name="Students")
        records.to_excel(writer, index=False, sheet_name="Attendance")
    st.download_button("⬇️ Download Excel Report",
                       output.getvalue(),
                       file_name="School_Attendance_Report.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

elif page == "Student Portal":
    st.subheader("🔎 Student Portal")
    st.info("Student profile access requires a separate private portal credential. This demo uses student ID lookup only for testing; do not publish it as an unrestricted public portal.")
    student_id = st.text_input("Enter Student ID")
    if st.button("Find My Dashboard"):
        student = get_student(student_id.strip())
        if not student:
            st.error("Student not found.")
        else:
            st.warning("Demo lookup only. Before public deployment, add a student-specific password or one-time login verification.")
            st.markdown(f"## {student[1]}")
            st.write(f"Class: {student[2]} · Roll: {student[3]}")
            with db() as con:
                hist = pd.read_sql_query("""
                SELECT attendance_date, attendance_time, status
                FROM attendance WHERE student_id=?
                ORDER BY attendance_date DESC
                """, con, params=(student_id.strip(),))
            count = len(hist)
            present = int((hist.status == "Present").sum()) if count else 0
            st.metric("Present entries", present)
            st.metric("Recorded attendance percentage",
                      f"{present/count*100:.1f}%" if count else "0%")
            st.dataframe(hist, use_container_width=True, hide_index=True)

st.sidebar.markdown("---")
if st.session_state.get("admin_logged_in"):
    if st.sidebar.button("Log out"):
        st.session_state.admin_logged_in = False
        st.rerun()
st.sidebar.caption("Prototype • Verify identity before relying on QR-only attendance.")
