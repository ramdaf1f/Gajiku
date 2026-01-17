import json, math, re, calendar, sqlite3, time, os
from datetime import datetime, date, timedelta
from flask import Blueprint, current_app, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import csv, io

from app.db import get_db
from app.repositories.user_repo import get_user_by_id, get_user_by_email
from app.utils.cache import get_cache, set_cache
from app.tasks.queue import get_stats as get_queue_stats
from app.services.email_service import enqueue_email

bp = Blueprint("web", __name__)

# ===== Health =====
@bp.route("/health")
def health():
    ret = require_admin()
    if ret:
        return ret
    return {
        "version": current_app.config["APP_VERSION"],
        "admin_fee_reg": current_app.config["ADMIN_FEE"],
        "admin_fee_urg_per_day": current_app.config["ADMIN_FEE_PER_DAY"],
        "db_path": current_app.config["DB_PATH"],
        "session_user": session.get("user_id"),
        "session_name": session.get("user_name"),
        "admin_id": session.get("admin_id"),
    }

@bp.get("/metrics")
def metrics():
    ret = require_admin()
    if ret:
        return ret
    return {
        "timestamp": int(time.time()),
        "queue": get_queue_stats(),
    }

# ===== Sanitize angka =====
def parse_int(raw, default=0):
    if raw is None:
        return default
    s = re.sub(r"[^\d\-]", "", str(raw))
    if s in ("", "-"):
        return default
    try:
        return int(s)
    except Exception:
        return default

# ===== Filter Rupiah =====
@bp.app_template_filter("rupiah")
def rupiah_format(value, with_decimal=False):
    try:
        if isinstance(value, str):
            value = re.sub(r"[^\d\-\.]", "", value)
        val = float(value)
        s = f"{val:,.2f}" if with_decimal else f"{int(round(val)):,}"
        s = s.replace(",", "_").replace(".", ",").replace("_", ".")
        return f"Rp. {s}"
    except Exception:
        return "Rp. 0"

# ===== Format Tanggal indonesia =====
@bp.app_template_filter("indo_date")
def indo_date(value):
    """Format tanggal Indonesia: dd-mm-YYYY (menerima date/datetime/string ISO)."""
    try:
        if hasattr(value, "strftime"):
            return value.strftime("%d-%m-%Y")
        return datetime.fromisoformat(str(value)).strftime("%d-%m-%Y")
    except Exception:
        return str(value)

@bp.app_template_filter("format_period_label")
def format_period_label_filter(value):
    return format_period_label(str(value))

# ===== Helpers =====
def month_key(d: date) -> str: return d.strftime("%Y-%m")
def ymd(d: date) -> str: return d.strftime("%Y-%m-%d")

def compute_limits(gaji: int, at_date: date, user_id: int):
    """
    Hitung batas talangan untuk user di tanggal tertentu.
    - Siklus A : 1–akhir bulan
    - Siklus B : 16–15
    - REG: sisa harian = (limit_harian * hari_ke) - total_sukses_per_periode_sampai_hari_ini
    """
    db = get_db()

    # Ambil email user + siklus dari master pegawai (join lewat email)
    row = db.execute("""
        SELECT u.email, p.siklus_gaji
        FROM users u
        LEFT JOIN pegawai p ON LOWER(p.email) = LOWER(u.email)
        WHERE u.id = ?
    """, (user_id,)).fetchone()
    user_email = (row["email"] if row and row["email"] else "").strip()
    siklus = (row["siklus_gaji"] if row and row["siklus_gaji"] else "A")

    # Plafon & limit harian
    plafon = math.floor(0.5 * (gaji or 0))
    limit_harian = math.floor(plafon / 30) if gaji else 0

    # Hari ke (menggunakan helper kamu) & kunci periode aktif
    hari_ke = day_in_cycle(at_date, siklus)
    mk = period_key_by_cycle(at_date, siklus)

    # Total nominal di periode aktif s.d. hari ini (by email agar duplikat user_id tidak lolos)
    if user_email:
        total_sukses = int(db.execute("""
            SELECT COALESCE(SUM(t.nominal), 0)
            FROM transactions t
            JOIN users u ON u.id = t.user_id
            WHERE LOWER(u.email) = LOWER(?)
              AND t.periode = ?
              AND t.status IN ('sukses','on-proses')
              AND t.tanggal <= ?
        """, (user_email, mk, ymd(at_date))).fetchone()[0] or 0)
    else:
        total_sukses = int(db.execute("""
            SELECT COALESCE(SUM(nominal), 0)
            FROM transactions
            WHERE user_id = ?
              AND periode = ?
              AND status IN ('sukses','on-proses')
              AND tanggal <= ?
        """, (user_id, mk, ymd(at_date))).fetchone()[0] or 0)

    # Sisa saldo REG (akumulatif harian)
    saldo = max((limit_harian * hari_ke) - total_sukses, 0)
    sisa_plafon = max(plafon - total_sukses, 0)

    return {
        "plafon": plafon,
        "limit_harian": limit_harian,
        "hari_ke": hari_ke,
        "total_sukses": total_sukses,
        "saldo": saldo,
        "periode_key": mk,
        "siklus": siklus,
        "sisa_plafon": sisa_plafon,
    }

def day_in_cycle(d: date, siklus: str) -> int:
    """Hitung hari ke- dalam periode berjalan sesuai siklus gaji."""
    if (siklus or 'A') == 'A':
        return d.day
    # Siklus B: periode 16..15
    if d.day >= 16:
        return d.day - 15  # 16->1, 17->2, ..., 31->16
    return d.day + 16     # 1->17, 2->18, ..., 15->31

def period_key_by_cycle(d: date, siklus: str) -> str:
    """Kunci periode (YYYY-MM) mengikuti bulan 'awal' periode."""
    if (siklus or 'A') == 'A':
        return d.strftime("%Y-%m")
    # Siklus B: periode mulai tanggal 16.
    # Jika tgl < 16, maka periode dianggap mulai 16 bulan sebelumnya.
    if d.day >= 16:
        return d.strftime("%Y-%m")
    # mundur 1 bulan:
    y = d.year; m = d.month - 1
    if m == 0: m = 12; y -= 1
    return f"{y:04d}-{m:02d}"

def add_months(d: date, delta: int) -> date:
    y = d.year + (d.month - 1 + delta) // 12
    m = (d.month - 1 + delta) % 12 + 1
    return date(y, m, 1)

def format_short_date(d: date) -> str:
    months = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
    return f"{d.day} {months[d.month - 1]} {d.year}"

def format_period_label(periode: str) -> str:
    """Format label periode 'YYYY-MM' menjadi 'Mon YYYY' (Indonesia)."""
    try:
        y, m = [int(x) for x in periode.split("-", 1)]
        months = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
        return f"{months[m - 1]} {y}"
    except Exception:
        return periode

def require_login():
    if "user_id" not in session:
        return redirect(url_for("web.login"))

def require_admin():
    if not session.get("is_admin"):
        flash("Anda harus login sebagai admin.", "error")
        return redirect(url_for("web.login"))

def current_sim_date():
    try:
        t = request.args.get("tanggal") or session.get("sim_date") or date.today().isoformat()
        return datetime.strptime(t, "%Y-%m-%d").date()
    except Exception:
        return date.today()

def get_formal_status():
    """
    Baca status aktif akun formal dari DB berdasar email formal di sesi.
    Return 1 jika aktif, 0 jika non-aktif, None kalau tidak ketemu.
    """
    email = session.get("formal_email")
    if not email:
        return None
    db = get_db()
    row = db.execute("""
        SELECT COALESCE(ua.status_aktif, p.status_aktif, 0) AS aktif
        FROM user_accounts ua
        JOIN pegawai p ON p.id = ua.pegawai_id
        WHERE ua.email = ?
        LIMIT 1
    """, (email,)).fetchone()
    return int(row["aktif"]) if row else None

def password_ok(pw: str) -> bool:
    return isinstance(pw, str) and len(pw) >= 6

def format_rupiah(n):
    try:
        return f"{int(n):,}".replace(",", ".")
    except:
        return str(n)

def apply_ppn(amount: int) -> int:
    """Tambahkan PPN 11% ke admin fee (dibulatkan ke atas)."""
    try:
        if not get_ppn_enabled():
            return int(amount or 0)
        return int(math.ceil((amount or 0) * 1.11))
    except Exception:
        return int(amount or 0)

def get_enabled_products():
    db = get_db()
    row = db.execute(
        "SELECT value FROM app_settings WHERE key='enabled_products' LIMIT 1"
    ).fetchone()
    if not row:
        return ["reg", "urg"]
    parts = [p.strip().lower() for p in (row["value"] or "").split(",") if p.strip()]
    enabled = []
    for p in parts:
        if p in ("reg", "urg") and p not in enabled:
            enabled.append(p)
    return enabled if enabled else ["reg", "urg"]

def set_enabled_products(products):
    value = ",".join(products)
    db = get_db()
    cur = db.execute(
        "UPDATE app_settings SET value=? WHERE key='enabled_products'",
        (value,),
    )
    if cur.rowcount == 0:
        db.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?)",
            ("enabled_products", value),
        )
    db.commit()

def get_ppn_enabled() -> bool:
    db = get_db()
    row = db.execute(
        "SELECT value FROM app_settings WHERE key='ppn_enabled' LIMIT 1"
    ).fetchone()
    if not row:
        return True
    val = str(row["value"] or "").strip().lower()
    return val not in ("0", "false", "no", "off")

def set_ppn_enabled(enabled: bool) -> None:
    value = "1" if enabled else "0"
    db = get_db()
    cur = db.execute(
        "UPDATE app_settings SET value=? WHERE key='ppn_enabled'",
        (value,),
    )
    if cur.rowcount == 0:
        db.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?)",
            ("ppn_enabled", value),
        )
    db.commit()

def allowed_avatar(filename: str) -> bool:
    ext = os.path.splitext(filename or "")[1].lower()
    return ext in {".png", ".jpg", ".jpeg", ".gif", ".webp"}

# app.py — TARUH DI BAWAH def protect_admin_routes() atau di bagian helpers

# ===== Routes umum =====
@bp.route("/")
def index():
    return redirect(url_for("web.dashboard") if "user_id" in session else url_for("web.login"))

# === LOGIN FORMAL (EMAIL + PASSWORD) + SIMULASI TANGGAL ===
@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        db = get_db()

        # --- Admin login (prioritas) ---
        adm = db.execute(
            "SELECT id, name, email, password_hash FROM admins WHERE LOWER(email)=? OR LOWER(name)=?",
            (email, email),
        ).fetchone()
        if adm and check_password_hash(adm["password_hash"], password):
            session.clear()
            session["is_admin"] = True
            session["admin_id"] = adm["id"]
            session["admin_name"] = adm["name"]
            session["admin_email"] = adm["email"]
            flash("Login admin berhasil.", "success")
            return redirect(url_for("web.admin_dashboard"))

        valid_ids = {
            str(current_app.config["ADMIN_USERNAME"]).strip().lower(),
            str(current_app.config["ADMIN_EMAIL"]).strip().lower(),
        }
        if email in valid_ids and password == current_app.config["ADMIN_PASSWORD"]:
            session.clear()
            session["is_admin"] = True
            session["admin_id"] = None
            session["admin_name"] = current_app.config["ADMIN_USERNAME"]
            session["admin_email"] = current_app.config["ADMIN_EMAIL"]
            flash("Login admin berhasil (ENV).", "success")
            return redirect(url_for("web.admin_dashboard"))

        today = date.today()
        try:
            day = int(request.form.get("tanggal") or today.day)
        except ValueError:
            day = today.day
        last_day = calendar.monthrange(today.year, today.month)[1]
        if day < 1 or day > last_day:
            flash(f"Tanggal tidak valid untuk bulan ini (1–{last_day}).", "error")
            return render_template("login.html", today=today)

        sim_date = date(today.year, today.month, day).isoformat()

        acc = db.execute("SELECT * FROM user_accounts WHERE email=?", (email,)).fetchone()
        if not acc or not check_password_hash(acc["password_hash"], password):
            flash("Email atau password salah.", "error")
            return render_template("login.html", today=today)

        p = db.execute("SELECT * FROM pegawai WHERE id=?", (acc["pegawai_id"],)).fetchone()
        if not p:
            flash("Akun tidak terhubung dengan master pegawai. Hubungi admin.", "error")
            return render_template("login.html", today=today)

        formal_active = int(p["status_aktif"] or 0)
        if formal_active != int(acc["status_aktif"] or 0):
            db.execute("UPDATE user_accounts SET status_aktif=? WHERE id=?", (formal_active, acc["id"]))
            db.commit()

        name_for_users = p["nama"] or acc["name"]
        db.execute("""
            INSERT INTO users(name, email, gaji, created_at)
            VALUES (?,?,?,?)
            ON CONFLICT(email) DO UPDATE SET
                name=excluded.name,
                gaji=excluded.gaji
        """, (name_for_users, p["email"], int(p["gaji"] or 0), datetime.now().isoformat(timespec="seconds")))
        db.commit()

        u = get_user_by_email(p["email"])

        session.clear()
        session["user_id"] = u["id"]
        session["user_name"] = u["name"]
        session["sim_date"] = sim_date
        session["formal_active"] = formal_active
        session["formal_email"] = p["email"]
        session["formal_email"] = p["email"]      # penting untuk re-check server-side
        session["formal_active"] = formal_active  # 1 aktif, 0 non-aktif

        flash("Login berhasil.", "success")
        return redirect(url_for("web.dashboard", tanggal=sim_date))

    return render_template("login.html", today=date.today())

@bp.route("/forgot", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        if not email:
            flash("Masukkan alamat email Anda.", "warning")
            return redirect(url_for("web.forgot_password"))

        db = get_db()
        acc = db.execute("SELECT * FROM user_accounts WHERE email=?", (email,)).fetchone()
        if not acc:
            flash("Email tidak terdaftar.", "danger")
            return redirect(url_for("web.forgot_password"))

        # generate password baru
        import secrets
        new_pass = secrets.token_hex(4)  # 8 karakter
        hash_new = generate_password_hash(new_pass)

        db.execute("UPDATE user_accounts SET password_hash=? WHERE id=?", (hash_new, acc["id"]))
        db.commit()

        subj = "[Dana Talangan] Reset Password Akun"
        body = f"Halo {acc['name']},\n\nPassword akun Anda telah direset.\nPassword baru: {new_pass}\n\nSegera login dan ubah password melalui menu Pengaturan."
        enqueue_email(subj, body, to_list=[email])

        flash("Password baru telah dikirim ke email Anda.", "info")
        return redirect(url_for("web.login"))

    return render_template("forgot.html")

@bp.post("/logout")
def logout():
    session.clear()
    flash("Anda telah logout.", "info")
    return redirect(url_for("web.login"))

@bp.post("/avatar/upload")
def avatar_upload():
    if not session.get("user_id") and not session.get("is_admin"):
        flash("Silakan login terlebih dahulu.", "error")
        return redirect(url_for("web.login"))

    file = request.files.get("avatar")
    if not file or not file.filename:
        flash("Pilih file gambar terlebih dahulu.", "error")
        return redirect(request.referrer or url_for("web.dashboard"))

    filename = secure_filename(file.filename)
    if not filename or not allowed_avatar(filename):
        flash("Format gambar tidak didukung.", "error")
        return redirect(request.referrer or url_for("web.dashboard"))

    ext = os.path.splitext(filename)[1].lower()
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    owner_id = session.get("admin_id") if session.get("is_admin") else session.get("user_id")
    owner_prefix = "admin" if session.get("is_admin") else "user"
    safe_name = f"{owner_prefix}_{owner_id or 'env'}_{stamp}{ext}"

    upload_dir = os.path.join(current_app.static_folder, "uploads", "avatars")
    os.makedirs(upload_dir, exist_ok=True)
    file.save(os.path.join(upload_dir, safe_name))
    rel_path = f"uploads/avatars/{safe_name}"

    db = get_db()
    if session.get("is_admin"):
        if session.get("admin_id"):
            db.execute("UPDATE admins SET avatar_path=? WHERE id=?", (rel_path, session["admin_id"]))
        elif session.get("admin_email"):
            db.execute("UPDATE admins SET avatar_path=? WHERE LOWER(email)=?", (rel_path, session["admin_email"].lower()))
        db.commit()
        flash("Avatar admin diperbarui.", "success")
        return redirect(url_for("web.admin_dashboard"))

    email = (session.get("formal_email") or "").strip().lower()
    if not email:
        u = db.execute("SELECT email FROM users WHERE id=?", (session["user_id"],)).fetchone()
        email = (u["email"] or "").strip().lower() if u else ""
    if email:
        db.execute("UPDATE user_accounts SET avatar_path=? WHERE LOWER(email)=?", (rel_path, email))
        db.commit()
    flash("Avatar diperbarui.", "success")
    return redirect(request.referrer or url_for("web.dashboard"))

@bp.post("/avatar/delete")
def avatar_delete():
    if not session.get("user_id") and not session.get("is_admin"):
        flash("Silakan login terlebih dahulu.", "error")
        return redirect(url_for("web.login"))

    db = get_db()
    if session.get("is_admin"):
        if session.get("admin_id"):
            db.execute("UPDATE admins SET avatar_path='' WHERE id=?", (session["admin_id"],))
        elif session.get("admin_email"):
            db.execute("UPDATE admins SET avatar_path='' WHERE LOWER(email)=?", (session["admin_email"].lower(),))
        db.commit()
        flash("Avatar admin dihapus.", "success")
        return redirect(request.referrer or url_for("web.admin_dashboard"))

    email = (session.get("formal_email") or "").strip().lower()
    if not email:
        u = db.execute("SELECT email FROM users WHERE id=?", (session["user_id"],)).fetchone()
        email = (u["email"] or "").strip().lower() if u else ""
    if email:
        db.execute("UPDATE user_accounts SET avatar_path='' WHERE LOWER(email)=?", (email,))
        db.commit()
    flash("Avatar dihapus.", "success")
    return redirect(request.referrer or url_for("web.dashboard"))

# ===== DASHBOARD USER =====
@bp.route("/dashboard")
def dashboard():
    uid = session.get("user_id")
    if not uid:
        flash("Sesi habis. Silakan login lagi.", "error")
        return redirect(url_for("web.login"))

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if user is None:
        session.clear()
        flash("Data akun tidak ditemukan. Silakan login kembali.", "error")
        return redirect(url_for("web.login"))

    at_date = current_sim_date()
    gaji_int = int(user["gaji"] or 0)
    limits = compute_limits(gaji_int, at_date, user["id"])
    mk = limits["periode_key"]
        # KPI baru: Sisa Plafon URG (plafon - total_sukses)
    sisa_plafon_urg = max(int(limits.get("plafon", 0)) - int(limits.get("total_sukses", 0)), 0)


    rows = db.execute(
        """SELECT t.id, t.tanggal, t.nominal, t.admin_fee, t.status, t.product, t.created_at,
                  t.keterangan, t.cancel_until,
                  COALESCE(p.no_rekening,'') AS no_rekening,
                  COALESCE(p.no_telp,'') AS no_telp
           FROM transactions t
           JOIN users u ON u.id = t.user_id
           LEFT JOIN pegawai p ON LOWER(p.email)=LOWER(u.email)
           WHERE t.user_id=? AND t.periode=?
           ORDER BY t.created_at DESC, t.id DESC
           LIMIT 20""",
        (user["id"], mk),
    ).fetchall()

    pegawai_info = None
    try:
        email = (user["email"] or "").strip().lower()
        if email:
            pegawai_info = db.execute(
                "SELECT no_rekening, no_telp FROM pegawai WHERE LOWER(email)=LOWER(?)",
                (email,),
            ).fetchone()
    except Exception:
        pegawai_info = None

    total_nom   = sum(int(r["nominal"] or 0) for r in rows if r["status"] == "sukses")
    total_admin = sum(int(r["admin_fee"] or 0) for r in rows if r["status"] == "sukses")

    # hitung sisa detik countdown pembatalan untuk tiap transaksi on-proses
    now = datetime.now()
    remaining_map = {}
    for r in rows:
        remaining = 0
        if r["status"] == "on-proses" and r["cancel_until"]:
            try:
                cu = datetime.fromisoformat(r["cancel_until"])
                delta = (cu - now).total_seconds()
                remaining = int(delta) if delta > 0 else 0
            except Exception:
                remaining = 0
        remaining_map[r["id"]] = remaining

    try:
        account_name = user["name"] or user["email"] or "Akun"
    except Exception:
        # kalau suatu saat tipe-nya dict, tetap aman
        account_name = (user.get("name") or user.get("email") or "Akun")

    enabled_products = get_enabled_products()
    avatar_url = None
    try:
        email = (session.get("formal_email") or user["email"] or "").strip().lower()
        if email:
            row = db.execute(
                "SELECT avatar_path FROM user_accounts WHERE LOWER(email)=?",
                (email,),
            ).fetchone()
            if row and row["avatar_path"]:
                avatar_url = url_for("static", filename=row["avatar_path"])
    except Exception:
        avatar_url = None

    return render_template(
        "dashboard.html",
        user=user,
        at_date=at_date,
        mk=mk,
        limits=limits,
        rows=rows,
        total_nom=total_nom,
        total_admin=total_admin,
        account_name=account_name,
        remaining_map=remaining_map,
        sisa_plafon_urg=sisa_plafon_urg,
        enabled_products=enabled_products,
        avatar_url=avatar_url,
        pegawai_info=pegawai_info,
    )

@bp.route("/settings", methods=["GET", "POST"])
def settings_account():
    # wajib login user formal
    if "user_id" not in session:
        flash("Silakan login terlebih dahulu.", "error")
        return redirect(url_for("web.login"))

    db = get_db()

    # temukan akun formal (user_accounts) via sesi login formal
    # prioritas: formal_email → kalau tidak ada, fallback ke email di 'users'
    formal_email = (session.get("formal_email") or "").strip().lower()
    if not formal_email:
        # fallback dengan relasi users -> user_accounts via email yang sama
        u = db.execute("SELECT email FROM users WHERE id=?", (session["user_id"],)).fetchone()
        formal_email = (u["email"] or "").strip().lower() if u else ""

    acc = None
    if formal_email:
        acc = db.execute("SELECT id, email, password_hash FROM user_accounts WHERE LOWER(email)=?", (formal_email,)).fetchone()

    if not acc:
        flash("Akun formal Anda belum tersedia. Hubungi admin untuk registrasi.", "error")
        return redirect(url_for("web.dashboard"))

    if request.method == "POST":
        old_pw = request.form.get("old_password") or ""
        new_pw = request.form.get("new_password") or ""
        new_pw2 = request.form.get("new_password2") or ""

        if not check_password_hash(acc["password_hash"], old_pw):
            flash("Password lama tidak cocok.", "error")
            return render_template("settings.html")

        if not password_ok(new_pw):
            flash("Password baru minimal 6 karakter.", "error")
            return render_template("settings.html")

        if new_pw != new_pw2:
            flash("Konfirmasi password baru tidak cocok.", "error")
            return render_template("settings.html")

        db.execute("UPDATE user_accounts SET password_hash=? WHERE id=?", (generate_password_hash(new_pw), acc["id"]))
        db.commit()
        flash("Password berhasil diperbarui.", "success")
        return redirect(url_for("web.dashboard"))

    return render_template("settings.html")


# =========================================================
# ===================== PENCAIRAN =========================
# =========================================================
@bp.route("/tarik-gaji", methods=["GET", "POST"])
def tarik_gaji():
    if "user_id" not in session:
        flash("Silakan login terlebih dahulu.", "error")
        return redirect(url_for("web.login"))

    admin_fee_base = current_app.config["ADMIN_FEE"]
    admin_fee_per_day = current_app.config["ADMIN_FEE_PER_DAY"]
    ppn_enabled = get_ppn_enabled()
    db      = get_db()
    user    = get_user_by_id(session["user_id"])
    at_date = current_sim_date()
    limits  = compute_limits(int(user["gaji"] or 0), at_date, user["id"])
    enabled_products = get_enabled_products()
    selected_product = enabled_products[0] if enabled_products else "reg"

    # ---- HARD GATE: akun formal harus aktif sekarang (cek langsung ke DB) ----
    fresh_active = get_formal_status()
    if fresh_active == 0:  # non-aktif
        session["formal_active"] = 0
        flash("Akun Anda belum diaktifkan admin. Pengajuan tarik gaji terkunci.", "error")
        return redirect(url_for("web.dashboard", tanggal=at_date.isoformat()))
    elif fresh_active == 1:
        session["formal_active"] = 1

    # ===================== POST =====================
    if request.method == "POST":
        today    = date.today()
        last_day = calendar.monthrange(today.year, today.month)[1]

        # --- ambil + validasi tanggal ---
        try:
            day = int(request.form.get("tanggal") or today.day)
        except ValueError:
            day = today.day
        if day < 1 or day > last_day:
            flash(f"Tanggal tidak valid (1-{last_day}).", "error")
            return render_template("tarik_gaji.html",
                                   user=user, at_date=at_date, limits=limits,
                                   ADMIN_FEE=admin_fee_base, ADMIN_FEE_PER_DAY=admin_fee_per_day,
                                   ppn_enabled=ppn_enabled,
                                   enabled_products=enabled_products,
                                   selected_product=selected_product)

        at_day  = date(today.year, today.month, day)
        produk  = (request.form.get("produk") or "reg").strip().lower()  # 'reg' | 'urg'
        if produk not in enabled_products:
            flash("Produk tidak aktif. Pilih produk lain.", "error")
            return render_template("tarik_gaji.html",
                                   user=user, at_date=at_day,
                                   limits=compute_limits(int(user["gaji"] or 0), at_day, user["id"]),
                                   ADMIN_FEE=admin_fee_base, ADMIN_FEE_PER_DAY=admin_fee_per_day,
                                   ppn_enabled=ppn_enabled,
                                   enabled_products=enabled_products,
                                   selected_product=selected_product)
        selected_product = produk
        nominal = parse_int(request.form.get("nominal"), 0)
        ket     = (request.form.get("keterangan") or "").strip()
        urg_lock_until = None  # default, hanya terisi bila produk URG


        if nominal <= 0:
            flash("Nominal tarik gaji wajib > 0.", "error")
            return render_template("tarik_gaji.html",
                                   user=user, at_date=at_day,
                                   limits=compute_limits(int(user["gaji"] or 0), at_day, user["id"]),
                                   ADMIN_FEE=admin_fee_base, ADMIN_FEE_PER_DAY=admin_fee_per_day,
                                   ppn_enabled=ppn_enabled,
                                   enabled_products=enabled_products,
                                   selected_product=selected_product)

        # --- Limit untuk hari yang diminta ---
        # {plafon, limit_harian, hari_ke, total_sukses, saldo, periode_key, siklus}
        lim_day = compute_limits(int(user["gaji"] or 0), at_day, user["id"])

        # --- Rule: 1x REG + 1x URG maksimum per hari (Hapus)
        #exists = db.execute("""
            #SELECT 1 FROM transactions
            #WHERE user_id=? AND tanggal=? AND product=? AND status NOT IN ('ditolak','dibatalkan')
            #LIMIT 1
        #""", (user["id"], at_day.isoformat(), produk)).fetchone()
        #if exists:
            #label = "REG" if produk == "reg" else "URG"
            #flash(f"Pengajuan {label} untuk tanggal ini sudah ada. Maksimal 1x per hari.", "error")
            #return render_template("tarik_gaji.html",
                                   #user=user, at_date=at_day, limits=lim_day,
                                   #ADMIN_FEE=ADMIN_FEE, ADMIN_FEE_PER_DAY=ADMIN_FEE_PER_DAY)

        # --- Validasi & fee ---
        if produk == "reg":
            # untuk REG pakai saldo harian (sudah memperhitungkan siklus A/B)
            if nominal > lim_day["saldo"]:
                flash(f"Permintaan melebihi limit plafon harian. Sisa hari ini: {rupiah_format(lim_day['saldo'])}.", "error")
                return render_template("tarik_gaji.html",
                                       user=user, at_date=at_day, limits=lim_day,
                                       ADMIN_FEE=admin_fee_base, ADMIN_FEE_PER_DAY=admin_fee_per_day,
                                       ppn_enabled=ppn_enabled,
                                       enabled_products=enabled_products,
                                       selected_product=selected_product)
            admin_fee = apply_ppn(admin_fee_base)
		
        else:
            # ————— URG (adil: limit = sisa plafon; fee = REG-portion + URG-portion) —————

            # 1) Cek lock URG sebelumnya di periode yang sama
            #last_urg = None
            #try:
                # kalau DB lama belum punya kolom urg_lock_until, ALTER TABLE dulu
                #cols = [row[1] for row in db.execute("PRAGMA table_info(transactions)").fetchall()]
                #if "urg_lock_until" not in cols:
                    #db.execute("ALTER TABLE transactions ADD COLUMN urg_lock_until TEXT")
                    #db.commit()

                #last_urg = db.execute("""
                    #SELECT tanggal, urg_lock_until
                    #FROM transactions
                    #WHERE user_id=? AND periode=? AND product='urg'
                      #AND status IN ('sukses','on-proses')
                    #ORDER BY tanggal DESC, id DESC
                    #LIMIT 1
                #""", (user["id"], lim_day["periode_key"])).fetchone()
            #except Exception as e:
                #print("WARN: gagal cek/membuat kolom urg_lock_until:", e)

            #if last_urg and last_urg["urg_lock_until"]:
                #try:
                    #lock_until = date.fromisoformat(last_urg["urg_lock_until"])
                #except Exception:
                    #lock_until = None

                #if lock_until is not None and at_day <= lock_until:
                    #flash(
                        #f"Pengajuan URG belum boleh. Masa pemakaian URG sebelumnya sampai {lock_until.strftime('%d-%m-%Y')}.",
                        #"error"
                    #)
                    #return render_template(
                        #"tarik_gaji.html",
                        #user=user, at_date=at_day, limits=lim_day,
                        #ADMIN_FEE=ADMIN_FEE, ADMIN_FEE_PER_DAY=ADMIN_FEE_PER_DAY,
                        #last_rek=last_rek
                    #)

            # 2) Hitung limit, split REG/URG, fee dan hari lock
            plafon        = int(lim_day["plafon"] or 0)
            total_sukses  = int(lim_day["total_sukses"] or 0)
            limit_harian  = int(lim_day["limit_harian"] or 0)
            hari_ke       = int(lim_day["hari_ke"] or 1)  # A: tgl, B: hari posisi 1..30
            sisa_plafon   = max(plafon - total_sukses, 0)

            # Limit URG adil: murni sisa plafon
            limit_urg_max = sisa_plafon
            if nominal > limit_urg_max:
                flash(
                    f"Permintaan melebihi limit URG. Maksimal URG saat ini: {rupiah_format(limit_urg_max)} (= sisa plafon).",
                    "error"
                )
                return render_template(
                    "tarik_gaji.html",
                    user=user, at_date=at_day, limits=lim_day,
                    ADMIN_FEE=admin_fee_base, ADMIN_FEE_PER_DAY=admin_fee_per_day,
                    ppn_enabled=ppn_enabled,
                    enabled_products=enabled_products,
                    selected_product=selected_product
                )

            # Saldo REG tersedia s.d. HARI INI
            saldo_reg_tersedia = max(limit_harian * hari_ke - total_sukses, 0)

            # Split nominal
            reg_portion = min(nominal, saldo_reg_tersedia)
            urg_portion = max(nominal - reg_portion, 0)

            # Fee gabungan
            fee_reg = admin_fee_base if reg_portion > 0 else 0
            fee_urg = math.ceil(urg_portion / limit_harian) * admin_fee_base if limit_harian > 0 else 0

            admin_fee = apply_ppn(fee_reg + fee_urg)

            # Hitung masa lock hanya dari porsi URG (maju X hari)
            #if limit_harian > 0 and urg_portion > 0:
                #hari_urg_lock = math.ceil(urg_portion / limit_harian)
                #urg_lock_until = (at_day + timedelta(days=hari_urg_lock)).isoformat()
            #else:
                #urg_lock_until = None    
              
        # --- Window pembatalan 25 detik ---
        cancel_until = (datetime.now() + timedelta(seconds=25)).isoformat(timespec="seconds")

        # --- Simpan transaksi on-proses ---
        db.execute("""
            INSERT INTO transactions
            (user_id, tanggal, periode, nominal, admin_fee, status, keterangan, created_at, product, cancel_until, urg_lock_until)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (
            user["id"],
            at_day.isoformat(),
            lim_day["periode_key"],       # periode mengikuti tanggal yang dipilih
            nominal,
            admin_fee,
            "on-proses",
            ket,
            datetime.now().isoformat(timespec="seconds"),
            produk,
            cancel_until,
            urg_lock_until
        ))
        db.commit()


        # --- Kirim notifikasi email (best-effort) ---
        try:
            # ambil metadata pegawai via email user
            peg = db.execute("""
                SELECT p.nama, p.email, p.perusahaan, p.jabatan
                FROM users u
                JOIN pegawai p ON LOWER(p.email)=LOWER(u.email)
                WHERE u.id=?
            """, (user["id"],)).fetchone()

            sub = f"[Dana-Talangan] Pengajuan baru ({produk.upper()})"
            body = (
                f"Tanggal : {at_day.isoformat()}\n"
                f"Pegawai : {(peg['nama'] if peg else user['name'])} <{(peg['email'] if peg else user['email'])}>\n"
                f"Perusahaan/Jabatan : {(peg['perusahaan'] if peg and peg['perusahaan'] else '-')}"
                f" / {(peg['jabatan'] if peg and peg['jabatan'] else '-')}\n"
                f"Nominal : {rupiah_format(nominal)}\n"
                f"Admin   : {rupiah_format(admin_fee)}\n"
                f"Produk  : {produk.upper()}\n"
                f"Status  : on-proses\n"
                f"Catatan : {ket or '-'}\n"
            )
            enqueue_email(sub, body)
        except Exception as e:
            print("[WARN] Notifikasi email di-skip:", e)

        # Simpan tanggal simulasi & kembali ke dashboard
        session["sim_date"] = at_day.isoformat()
        flash("Pengajuan direkam dan masuk antrian admin (status: on-proses).", "success")
        return redirect(url_for("web.dashboard", tanggal=at_day.isoformat()))

    # ===================== GET =====================
    return render_template("tarik_gaji.html",
                           user=user, at_date=at_date, limits=limits,
                           ADMIN_FEE=admin_fee_base, ADMIN_FEE_PER_DAY=admin_fee_per_day,
                           ppn_enabled=ppn_enabled,
                           enabled_products=enabled_products,
                           selected_product=selected_product)

# Redirect URL lama agar tidak memutus link yang sudah ada
@bp.route("/pencairan", methods=["GET", "POST"])
def pencairan_redirect():
    return redirect(url_for("web.tarik_gaji", **request.args))



# ===== Pembatalan user (selama belum di-approve admin) =====
@bp.post("/tx/<int:txid>/cancel")
def tx_cancel(txid):
    if "user_id" not in session:
        flash("Silakan login.", "error")
        return redirect(url_for("web.login"))
    db = get_db()
    row = db.execute("SELECT id, user_id, status, cancel_until FROM transactions WHERE id=?", (txid,)).fetchone()
    if not row or row["user_id"] != session["user_id"]:
        flash("Transaksi tidak ditemukan.", "error")
        return redirect(url_for("web.dashboard"))
    if row["status"] != "on-proses":
        flash("Transaksi sudah diproses admin.", "info")
        return redirect(url_for("web.dashboard"))
    db.execute("UPDATE transactions SET status='dibatalkan' WHERE id=?", (txid,))
    db.commit()
    flash("Transaksi dibatalkan.", "info")
    return redirect(url_for("web.dashboard"))

# ===== API status transaksi (dipakai polling countdown di dashboard) =====
@bp.get("/api/tx_status")
def api_tx_status():
    if "user_id" not in session:
        return {"ok": False, "err": "unauth"}, 401

    ids_raw = (request.args.get("ids") or "").strip()
    try:
        ids = [int(x) for x in ids_raw.split(",") if x.strip().isdigit()]
    except Exception:
        ids = []

    if not ids:
        return {"ok": True, "items": []}

    db = get_db()
    rows = db.execute(
        """SELECT id, user_id, tanggal, status, cancel_until, product, nominal, admin_fee
           FROM transactions
           WHERE id IN (%s)""" % ",".join("?"*len(ids)),
        ids
    ).fetchall()

    now = datetime.now()
    items = []
    for r in rows:
        # hitung sisa detik cancel window
        remaining = 0
        if r["cancel_until"]:
            try:
                cu = datetime.fromisoformat(r["cancel_until"])
                delta = (cu - now).total_seconds()
                remaining = int(delta) if delta > 0 else 0
            except Exception:
                remaining = 0

        items.append({
            "id": r["id"],
            "status": r["status"],
            "remaining": remaining
        })

    return {"ok": True, "items": items}

# =========================================================
# ================== MODUL ADMIN ==========================
# =========================================================

@bp.route("/admin/login", methods=["GET", "POST"], endpoint="admin_login")
def admin_login():
    return redirect(url_for("web.login"))


@bp.post("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    session.pop("admin_name", None)
    flash("Anda telah logout admin.", "info")
    return redirect(url_for("web.login"))

# --- Admin: Pegawai CRUD ---
@bp.route("/admin/pegawai", methods=["GET"], endpoint="admin_pegawai")
def admin_pegawai():
    ret = require_admin()
    if ret: return ret
    db = get_db()

    # pastikan kolom 'perusahaan' ada
    try:
        db.execute("SELECT perusahaan FROM pegawai LIMIT 1").fetchone()
    except Exception:
        db.execute("ALTER TABLE pegawai ADD COLUMN perusahaan TEXT DEFAULT ''")
        db.commit()
    # pastikan kolom 'no_rekening' ada
    try:
        db.execute("SELECT no_rekening FROM pegawai LIMIT 1").fetchone()
    except Exception:
        db.execute("ALTER TABLE pegawai ADD COLUMN no_rekening TEXT DEFAULT ''")
        db.commit()
    # pastikan kolom 'no_telp' ada
    try:
        db.execute("SELECT no_telp FROM pegawai LIMIT 1").fetchone()
    except Exception:
        db.execute("ALTER TABLE pegawai ADD COLUMN no_telp TEXT DEFAULT ''")
        db.commit()

    q = (request.args.get("q") or "").strip()
    f_company = (request.args.get("company") or "").strip()

    base_sql = """
        SELECT id, nama, email, jabatan, gaji, status_aktif,
               COALESCE(perusahaan,'') AS perusahaan,
               COALESCE(no_rekening,'') AS no_rekening,
               COALESCE(no_telp,'') AS no_telp,
               siklus_gaji,
               created_at
        FROM pegawai
        WHERE 1=1
    """
    params = []
    if q:
        like = f"%{q}%"
        base_sql += " AND (nama LIKE ? OR email LIKE ? OR jabatan LIKE ? OR COALESCE(perusahaan,'') LIKE ?)"
        params += [like, like, like, like]
    if f_company:
        base_sql += " AND COALESCE(perusahaan,'') = ?"
        params.append(f_company)
    base_sql += " ORDER BY id DESC"

    rows = db.execute(base_sql, params).fetchall()
    companies = [
        r[0] for r in db.execute(
            "SELECT DISTINCT COALESCE(perusahaan,'') FROM pegawai WHERE COALESCE(perusahaan,'') <> '' ORDER BY perusahaan"
        ).fetchall()
    ]
    total_len = db.execute("SELECT COUNT(*) FROM pegawai").fetchone()[0]

    return render_template("admin_pegawai.html",
                           rows=rows, q=q, companies=companies, f_company=f_company, total=total_len)


@bp.route("/admin/pegawai/add", methods=["POST"], endpoint="admin_pegawai_add")
def admin_pegawai_add():
    ret = require_admin()
    if ret: return ret

    nama        = (request.form.get("nama") or "").strip()
    email       = (request.form.get("email") or "").strip().lower()
    jabatan     = (request.form.get("jabatan") or "").strip()
    perusahaan  = (request.form.get("perusahaan") or "").strip()
    no_rekening = (request.form.get("no_rekening") or "").strip()
    no_telp     = (request.form.get("no_telp") or "").strip()
    gaji        = parse_int(request.form.get("gaji"), 0)
    status      = 1 if request.form.get("status") == "1" else 0
    # NEW: baca & validasi siklus_gaji (default B)
    siklus      = (request.form.get("siklus_gaji") or "B").strip().upper()
    if siklus not in ("A", "B"):
        siklus = "B"

    if not nama or not email:
        flash("Nama dan email wajib diisi.", "error")
        return redirect(url_for("web.admin_pegawai"))

    db = get_db()
    exists = db.execute("SELECT 1 FROM pegawai WHERE email=? OR nama=?", (email, nama)).fetchone()
    if exists:
        flash("Nama atau email sudah terdaftar.", "error")
        return redirect(url_for("web.admin_pegawai"))

    db.execute("""
        INSERT INTO pegawai (nama, email, jabatan, gaji, status_aktif, perusahaan, no_rekening, no_telp, siklus_gaji, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (nama, email, jabatan, gaji, status, perusahaan, no_rekening, no_telp, siklus, datetime.now().isoformat(timespec="seconds")))
    db.commit()

    flash("Pegawai ditambahkan.", "success")
    return redirect(url_for("web.admin_pegawai"))

@bp.route("/admin/pegawai/<int:pid>/update", methods=["POST"], endpoint="admin_pegawai_update")
def admin_pegawai_update(pid):
    ret = require_admin()
    if ret: return ret
    nama       = (request.form.get("nama") or "").strip()
    email      = (request.form.get("email") or "").strip().lower()
    jabatan    = (request.form.get("jabatan") or "").strip()
    perusahaan = (request.form.get("perusahaan") or "").strip()
    no_rekening = (request.form.get("no_rekening") or "").strip()
    no_telp    = (request.form.get("no_telp") or "").strip()
    gaji       = parse_int(request.form.get("gaji"), 0)
    status     = 1 if request.form.get("status") == "1" else 0
    siklus     = (request.form.get("siklus_gaji") or "A").strip().upper()
    if siklus not in ("A","B"): siklus = "A"

    db = get_db()
    row = db.execute("SELECT email FROM pegawai WHERE id=?", (pid,)).fetchone()
    old_email = (row["email"] or "").strip().lower() if row else ""
    # Cek bentrok nama/email dengan record lain
    exists = db.execute("SELECT id FROM pegawai WHERE (email=? OR nama=?) AND id<>?",
                        (email, nama, pid)).fetchone()
    if exists:
        flash("Nama/email bentrok dengan data lain.", "error")
        return redirect(url_for("web.admin_pegawai"))

    # Update master pegawai (termasuk siklus_gaji)
    db.execute("""UPDATE pegawai
                  SET nama=?, email=?, jabatan=?, gaji=?, status_aktif=?, perusahaan=?, no_rekening=?, no_telp=?, siklus_gaji=?
                  WHERE id=?""",
               (nama, email, jabatan, gaji, status, perusahaan, no_rekening, no_telp, siklus, pid))

    # Sinkronkan status + email ke akun formal agar login ikut email terbaru
    db.execute(
        "UPDATE user_accounts SET status_aktif=?, email=? WHERE pegawai_id=?",
        (status, email, pid),
    )
    if old_email and old_email != email:
        db.execute("UPDATE users SET email=? WHERE LOWER(email)=?", (email, old_email))
    db.execute("UPDATE users SET name=?, gaji=? WHERE LOWER(email)=?", (nama, gaji, email))

    db.commit()
    flash("Data pegawai diperbarui dan disinkron ke akun formal.", "success")
    return redirect(url_for("web.admin_pegawai"))

@bp.route("/admin/pegawai/<int:pid>/delete", methods=["POST"])
def admin_pegawai_delete(pid: int):
    # Guard admin (versi fungsional, jangan pakai decorator)
    ret = require_admin()
    if ret:
        return ret

    db = get_db()
    try:
        db.execute("PRAGMA foreign_keys = ON;")
    except Exception:
        pass

    try:
        cur = db.execute("SELECT * FROM pegawai WHERE id=?", (pid,))
        row = cur.fetchone()
        if not row:
            flash("Pegawai tidak ditemukan.", "error")
            return redirect(url_for("web.admin_pegawai"))

        # ---- 1) Arsipkan snapshot pegawai (aman, tidak ganggu skema) ----
        db.execute("""
            CREATE TABLE IF NOT EXISTS pegawai_archive (
                pegawai_id INTEGER,
                snapshot   TEXT,
                deleted_at TEXT
            )
        """)
        try:
            # sqlite Row → dict → JSON
            snap = json.dumps(dict(row))
        except Exception:
            snap = "{}"
        db.execute(
            "INSERT INTO pegawai_archive (pegawai_id, snapshot, deleted_at) VALUES (?,?,datetime('now'))",
            (pid, snap)
        )

        # ---- 2) Hapus semua relasi anak yang mengacu ke pegawai ----
        # 2a) Kumpulkan tabel2 dalam DB
        tables = [r["name"] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()]

        # 2b) Helper: cek apakah tabel memiliki kolom tertentu
        def has_column(tname: str, col: str) -> bool:
            try:
                cols = [c["name"] for c in db.execute(f"PRAGMA table_info({tname})").fetchall()]
                return col in cols
            except Exception:
                return False

        # 2c) Hapus semua baris dengan kolom 'pegawai_id' = pid (kecuali tabel master & arsip)
        for t in tables:
            if t in ("pegawai", "pegawai_archive"):
                continue
            if has_column(t, "pegawai_id"):
                db.execute(f"DELETE FROM {t} WHERE pegawai_id=?", (pid,))

        # 2d) Tangani relasi via akun user (user_id) berdasarkan email pegawai
        peg_email = (row["email"] or "").strip().lower()
        user_ids = [r["id"] for r in db.execute(
            "SELECT id FROM users WHERE LOWER(email)=?",
            (peg_email,)
        ).fetchall()]
        if user_ids:
            ids_sql = ",".join([str(i) for i in user_ids])
            for t in tables:
                if t in ("user_accounts", "pegawai", "pegawai_archive"):
                    continue
                if has_column(t, "user_id"):
                    db.execute(f"DELETE FROM {t} WHERE user_id IN ({ids_sql})")
            # hapus akun user setelah anak2nya
            db.execute("DELETE FROM user_accounts WHERE pegawai_id=?", (pid,))

        # ---- 3) Hapus master pegawai ----
        db.execute("DELETE FROM pegawai WHERE id=?", (pid,))

        db.commit()
        flash("Pegawai dan seluruh data terkait telah DIHAPUS permanen.", "success")

    except sqlite3.IntegrityError as e:
        db.rollback()
        flash(f"Gagal hapus permanen karena constraint database: {e}", "error")
    except Exception as e:
        db.rollback()
        flash(f"Gagal hapus permanen: {e}", "error")

    return redirect(url_for("web.admin_pegawai"))


# =========================================================
# ======================= RIWAYAT =========================
# =========================================================
@bp.route("/riwayat", endpoint="riwayat")
def riwayat_view():
    if "user_id" not in session:
        flash("Silakan login terlebih dahulu.", "error")
        return redirect(url_for("web.login"))

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
    if user is None:
        session.clear()
        flash("Sesi tidak valid. Silakan login lagi.", "error")
        return redirect(url_for("web.login"))

    at_date = current_sim_date()
    limits_u = compute_limits(int(user["gaji"] or 0), at_date, user["id"])
    requested_periode = request.args.get("periode")
    if not requested_periode or requested_periode == "last-6":
        mk = at_date.strftime("%Y-%m")
        selected_periode = "last-6"
    else:
        mk = requested_periode
        selected_periode = mk

    try:
        base_year, base_month = [int(x) for x in mk.split("-", 1)]
        base_date = date(base_year, base_month, 1)
    except Exception:
        base_date = at_date.replace(day=1)
        mk = base_date.strftime("%Y-%m")
        selected_periode = "last-6"

    last_periods = [month_key(add_months(base_date, -i)) for i in range(6)]
    periode_options = [{"value": "last-6", "label": "6 Periode Terakhir"}]
    periode_options += [{"value": p, "label": format_period_label(p)} for p in last_periods]

    if selected_periode == "last-6":
        periods_for_query = last_periods
    else:
        periods_for_query = [mk]

    placeholders = ",".join(["?"] * len(periods_for_query))

    rows = db.execute(
        f"""SELECT t.tanggal, t.periode, t.nominal, t.admin_fee, t.status, t.keterangan, t.product,
                    COALESCE(p.no_rekening,'') AS no_rekening
             FROM transactions t
             JOIN users u ON u.id = t.user_id
             LEFT JOIN pegawai p ON LOWER(p.email)=LOWER(u.email)
             WHERE t.user_id=? AND t.periode IN ({placeholders})
             ORDER BY t.periode DESC, t.tanggal DESC, t.id DESC""",
        (user["id"], *periods_for_query),
    ).fetchall()

    total_nom   = sum(int(r["nominal"] or 0) for r in rows if r["status"] == "sukses")
    total_admin = sum(int(r["admin_fee"] or 0) for r in rows if r["status"] == "sukses")

    # Penjelasan periode contoh berdasarkan siklus & periode yang dipilih
    a_start = base_date
    a_end = date(base_date.year, base_date.month, calendar.monthrange(base_date.year, base_date.month)[1])
    b_start = date(base_date.year, base_date.month, 16)
    b_end = date(add_months(base_date, 1).year, add_months(base_date, 1).month, 15)

    return render_template(
        "riwayat.html",
        user=user,
        periode=selected_periode,
        periode_list=last_periods,
        periode_options=periode_options,
        rows=rows,
        total_nom=total_nom,
        total_admin=total_admin,
        periode_a_info=f"{format_short_date(a_start)} – {format_short_date(a_end)}",
        periode_b_info=f"{format_short_date(b_start)} – {format_short_date(b_end)}",
    )

# =========================================================
# ================ ADMIN DASHBOARD (REKAP) ================
# =========================================================
@bp.route("/admin/dashboard")
def admin_dashboard():
    ret = require_admin()
    if ret:
        return ret

    admin_fee_base = current_app.config["ADMIN_FEE"]
    db = get_db()
    enabled_products = get_enabled_products()
    ppn_enabled = get_ppn_enabled()
    today = date.today()

    # Bulan berjalan (kalender) utk tampilan dashboard
    mk = today.strftime("%Y-%m")
    first_day = date(today.year, today.month, 1)
    # hitung first day next month utk batas eksklusif
    if today.month == 12:
        first_day_next = date(today.year + 1, 1, 1)
    else:
        first_day_next = date(today.year, today.month + 1, 1)
    s_first = first_day.isoformat()
    s_next  = first_day_next.isoformat()

    sim_today = current_sim_date()
    periode_key = f"{sim_today.year}-{sim_today.month:02d}"

    def add_months(d: date, delta: int) -> date:
        y = d.year + (d.month - 1 + delta) // 12
        m = (d.month - 1 + delta) % 12 + 1
        return date(y, m, 1)

    trend_start = add_months(date(today.year, today.month, 1), -5)
    trend_start_key = trend_start.strftime("%Y-%m")
    cache_key = f"admin_kpi:{s_first}:{s_next}:{periode_key}:{trend_start_key}"
    cached_kpi = get_cache(cache_key)
    if cached_kpi:
        (
            total_pegawai,
            total_register,
            reg_aktif,
            eligible,
            trx_count,
            trx_sum,
            unique_borrowers,
            not_borrowed,
            admin_fee_reg_total,
            admin_fee_urg_total,
            admin_fee_total,
            pending_count,
            cycle_a,
            cycle_b,
            inactive_count,
            chart_labels,
            chart_values,
            trend_labels,
            trend_values,
            cohort_rows,
        ) = cached_kpi
    else:
        # --- KPI dasar
        total_pegawai  = db.execute("SELECT COUNT(*) FROM pegawai").fetchone()[0]
        total_register = db.execute("SELECT COUNT(*) FROM user_accounts").fetchone()[0]
        reg_aktif      = db.execute("SELECT COUNT(*) FROM user_accounts WHERE status_aktif=1").fetchone()[0]
        eligible       = db.execute("SELECT COUNT(*) FROM pegawai WHERE status_aktif=1").fetchone()[0]

        # --- KPI transaksi untuk bulan kalender berjalan (berdasar TANGGAL, bukan periode)
        trx_count = db.execute("""
            SELECT COUNT(*) FROM transactions
            WHERE tanggal >= ? AND tanggal < ?
        """, (s_first, s_next)).fetchone()[0]

        trx_sum = db.execute("""
            SELECT COALESCE(SUM(nominal),0) FROM transactions
            WHERE status='sukses' AND tanggal >= ? AND tanggal < ?
        """, (s_first, s_next)).fetchone()[0]

        # Borrowers unik bulan ini (sukses atau on-proses)
        unique_borrowers = db.execute("""
            SELECT COUNT(DISTINCT user_id) FROM transactions
            WHERE tanggal >= ? AND tanggal < ? AND status IN ('sukses','on-proses')
        """, (s_first, s_next)).fetchone()[0]

        # Pegawai yg BELUM mencairkan (pakai jumlah akun register aktif sebagai basis)
        not_borrowed = max(total_register - unique_borrowers, 0)

        # --- total admin fee periode ini, dipisah REG & URG lalu dijumlahkan ---
        row_fee = db.execute("""
            SELECT
              COALESCE(SUM(CASE WHEN product='reg' THEN admin_fee END), 0) AS fee_reg,
              COALESCE(SUM(CASE WHEN product='urg' THEN admin_fee END), 0) AS fee_urg
            FROM transactions
            WHERE periode = ?
              AND status IN ('sukses', 'on-proses')
        """, (periode_key,)).fetchone()

        admin_fee_reg_total  = int(row_fee["fee_reg"] or 0)
        admin_fee_urg_total  = int(row_fee["fee_urg"] or 0)
        admin_fee_total      = admin_fee_reg_total + admin_fee_urg_total

        # Jumlah on-proses yang sedang menunggu (tampilkan SEMUA yang masih hidup - tak dibatasi periode,
        # supaya admin selalu melihat antrian real-time lintas siklus)
        pending_count = db.execute("""
            SELECT COUNT(*) FROM transactions WHERE status='on-proses'
        """).fetchone()[0]

        # KPI siklus + tidak aktif
        cycle_a = db.execute(
            "SELECT COUNT(*) FROM pegawai WHERE status_aktif=1 AND COALESCE(siklus_gaji,'A')='A'"
        ).fetchone()[0]
        cycle_b = db.execute(
            "SELECT COUNT(*) FROM pegawai WHERE status_aktif=1 AND COALESCE(siklus_gaji,'A')='B'"
        ).fetchone()[0]
        inactive_count = db.execute(
            "SELECT COUNT(*) FROM pegawai WHERE status_aktif=0"
        ).fetchone()[0]

        # --- Data grafik (total sukses per hari di bulan kalender)
        chart_data = db.execute("""
            SELECT substr(tanggal, 9, 2) AS hari, SUM(nominal) AS total
            FROM transactions
            WHERE status='sukses' AND tanggal >= ? AND tanggal < ?
            GROUP BY hari ORDER BY hari
        """, (s_first, s_next)).fetchall()
        chart_labels = [r["hari"] for r in chart_data]
        chart_values = [r["total"] for r in chart_data]

        # --- Trend 6 bulan terakhir (berdasar periode)
        trend_months = [add_months(trend_start, i).strftime("%Y-%m") for i in range(6)]
        trend_map = {m: 0 for m in trend_months}
        trend_rows = db.execute("""
            SELECT periode, COALESCE(SUM(nominal),0) AS total
            FROM transactions
            WHERE status='sukses' AND periode >= ?
            GROUP BY periode
        """, (trend_start_key,)).fetchall()
        for r in trend_rows:
            if r["periode"] in trend_map:
                trend_map[r["periode"]] = int(r["total"] or 0)
        trend_labels = trend_months
        trend_values = [trend_map[m] for m in trend_months]

        # --- Cohort sederhana: bulan pertama transaksi vs repeat bulan+1
        cohort_rows = []
        cohort_activity = db.execute("""
            SELECT user_id, periode
            FROM transactions
            WHERE status IN ('sukses','on-proses') AND periode >= ?
        """, (trend_start_key,)).fetchall()
        first_period = {}
        activity_set = set()
        for r in cohort_activity:
            uid = r["user_id"]
            per = r["periode"]
            activity_set.add((uid, per))
            if uid not in first_period or per < first_period[uid]:
                first_period[uid] = per

        for idx, cohort in enumerate(trend_months[:-1]):
            users = [u for u, p in first_period.items() if p == cohort]
            total = len(users)
            next_month = trend_months[idx + 1]
            repeat = sum(1 for u in users if (u, next_month) in activity_set)
            rate = int(round((repeat / total) * 100)) if total else 0
            cohort_rows.append({
                "cohort": cohort,
                "total": total,
                "repeat": repeat,
                "rate": rate
            })

        set_cache(
            cache_key,
            (
                total_pegawai,
                total_register,
                reg_aktif,
                eligible,
                trx_count,
                trx_sum,
                unique_borrowers,
                not_borrowed,
                admin_fee_reg_total,
                admin_fee_urg_total,
                admin_fee_total,
                pending_count,
                cycle_a,
                cycle_b,
                inactive_count,
                chart_labels,
                chart_values,
                trend_labels,
                trend_values,
                cohort_rows,
            ),
            ttl_seconds=10,
        )

    # --- Transaksi terbaru bulan berjalan (pakai tanggal bulanan)
    recent = db.execute("""
        SELECT t.tanggal, t.created_at, t.nominal, t.admin_fee, t.status, t.product, u.name AS nama
        FROM transactions t
        JOIN users u ON u.id=t.user_id
        WHERE t.tanggal >= ? AND t.tanggal < ?
        ORDER BY t.created_at DESC, t.id DESC
        LIMIT 10
    """, (s_first, s_next)).fetchall()

    # --- Antrian on-proses REG & URG (jangan pakai periode—ambil yang benar2 on-proses)
    pending_reg = db.execute("""
        SELECT t.id, t.tanggal, t.created_at, t.nominal, t.admin_fee, t.product,
               COALESCE(p.no_rekening, '') AS no_rekening,
               COALESCE(p.no_telp, '') AS no_telp,
               u.name AS nama,
               COALESCE(p.jabatan, '') AS jabatan,
               COALESCE(p.perusahaan, '') AS perusahaan
        FROM transactions t
        JOIN users u ON u.id=t.user_id
        LEFT JOIN pegawai p ON LOWER(p.email)=LOWER(u.email)
        WHERE t.status='on-proses' AND t.product='reg'
        ORDER BY t.created_at ASC, t.id ASC
    """).fetchall()

    pending_urg = db.execute("""
        SELECT t.id, t.tanggal, t.created_at, t.nominal, t.admin_fee, t.product,
               COALESCE(p.no_rekening, '') AS no_rekening,
               COALESCE(p.no_telp, '') AS no_telp,
               u.name AS nama,
               COALESCE(p.jabatan, '') AS jabatan,
               COALESCE(p.perusahaan, '') AS perusahaan
        FROM transactions t
        JOIN users u ON u.id=t.user_id
        LEFT JOIN pegawai p ON LOWER(p.email)=LOWER(u.email)
        WHERE t.status='on-proses' AND t.product='urg'
        ORDER BY t.created_at ASC, t.id ASC
    """).fetchall()

    queue_stats = get_queue_stats()
    admin_avatar_url = None
    try:
        if session.get("admin_id"):
            row = db.execute(
                "SELECT avatar_path FROM admins WHERE id=?",
                (session["admin_id"],),
            ).fetchone()
        elif session.get("admin_email"):
            row = db.execute(
                "SELECT avatar_path FROM admins WHERE LOWER(email)=?",
                (session["admin_email"].lower(),),
            ).fetchone()
        else:
            row = None
        if row and row["avatar_path"]:
            admin_avatar_url = url_for("static", filename=row["avatar_path"])
    except Exception:
        admin_avatar_url = None

    return render_template(
        "admin_dashboard.html",
        mk=mk,
        total_pegawai=total_pegawai,
        total_register=total_register,
        reg_aktif=reg_aktif,
        eligible=eligible,
        trx_count=trx_count,
        trx_sum=trx_sum,
        cycle_a=cycle_a,
        cycle_b=cycle_b,
        not_registered=max(total_pegawai - total_register, 0),
        inactive_count=inactive_count,
        pending_count=pending_count,
        not_borrowed=not_borrowed,          # <-- sebelumnya kosong; sekarang diisi
        recent=recent,
        pending_reg=pending_reg,
        pending_urg=pending_urg,
        ADMIN_FEE=admin_fee_base,
        admin_fee_total=admin_fee_total,
        admin_fee_reg_total=admin_fee_reg_total,
        admin_fee_urg_total=admin_fee_urg_total,
        periode_key=periode_key,
        chart_labels=chart_labels,
        chart_values=chart_values,
        trend_labels=trend_labels,
        trend_values=trend_values,
        cohort_rows=cohort_rows,
        queue_stats=queue_stats,
        enabled_products=enabled_products,
        ppn_enabled=ppn_enabled,
        avatar_url=admin_avatar_url,
    )

# =========================================================
# ================= ADMIN RIWAYAT TRANSAKSI ===============
# =========================================================
@bp.get("/admin/riwayat")
def admin_riwayat():
    ret = require_admin()
    if ret:
        return ret

    q = (request.args.get("q") or "").strip()
    status = (request.args.get("status") or "").strip()
    product = (request.args.get("product") or "").strip()
    start_raw = (request.args.get("start") or "").strip()
    end_raw = (request.args.get("end") or "").strip()

    today = date.today()
    default_start = add_months(date(today.year, today.month, 1), -5)
    default_end = today

    def parse_date(raw, fallback):
        if not raw:
            return fallback
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except Exception:
            return None

    start_dt = parse_date(start_raw, default_start)
    end_dt = parse_date(end_raw, default_end)
    if start_dt is None or end_dt is None:
        flash("Tanggal filter tidak valid. Gunakan format YYYY-MM-DD.", "error")
        start_dt, end_dt = default_start, default_end

    if start_dt > end_dt:
        start_dt, end_dt = end_dt, start_dt

    sql = """
        SELECT t.id, t.tanggal, t.periode, t.nominal, t.admin_fee, t.status, t.product,
               t.keterangan, t.created_at,
               u.name AS nama, u.email AS email_user,
               COALESCE(p.perusahaan,'') AS perusahaan,
               COALESCE(p.jabatan,'') AS jabatan,
               COALESCE(p.no_rekening,'') AS no_rekening
        FROM transactions t
        JOIN users u ON u.id = t.user_id
        LEFT JOIN pegawai p ON LOWER(p.email) = LOWER(u.email)
        WHERE t.tanggal >= ? AND t.tanggal <= ?
    """
    params = [start_dt.isoformat(), end_dt.isoformat()]

    if q:
        sql += """ AND (
            LOWER(u.name) LIKE ? OR LOWER(u.email) LIKE ?
            OR LOWER(COALESCE(p.perusahaan,'')) LIKE ?
            OR LOWER(COALESCE(p.jabatan,'')) LIKE ?
            OR LOWER(COALESCE(p.no_rekening,'')) LIKE ?
        )"""
        q_like = f"%{q.lower()}%"
        params.extend([q_like, q_like, q_like, q_like, q_like])

    if status:
        sql += " AND t.status = ?"
        params.append(status)

    if product:
        sql += " AND t.product = ?"
        params.append(product)

    sql += " ORDER BY t.tanggal DESC, t.id DESC"

    rows = get_db().execute(sql, params).fetchall()

    total_nom = sum(int(r["nominal"] or 0) for r in rows if r["status"] == "sukses")
    total_admin = sum(int(r["admin_fee"] or 0) for r in rows if r["status"] == "sukses")

    return render_template(
        "admin_riwayat.html",
        rows=rows,
        q=q,
        status=status,
        product=product,
        start=start_dt.isoformat(),
        end=end_dt.isoformat(),
        total_nom=total_nom,
        total_admin=total_admin,
    )

# =========================================================
# ==================== ADMIN export csv ======================
@bp.get("/admin/export")
def admin_export():
    ret = require_admin()
    if ret: return ret

    # Filter opsional
    periode = (request.args.get("periode") or "").strip()   # "YYYY-MM" atau "" = semua
    product = (request.args.get("product") or "").strip()   # "reg"/"urg"/""
    status  = (request.args.get("status") or "").strip()    # "sukses"/"on-proses"/"ditolak"/"dibatalkan"/""

    # Join yang benar: t.user_id -> users.id, lalu cocokkan pegawai via email (LEFT JOIN)
    sql = """
        SELECT t.id, t.tanggal, t.periode,
               u.name   AS pegawai,
               u.email  AS email_user,
               COALESCE(p.perusahaan,'') AS perusahaan,
               COALESCE(p.jabatan,'')    AS jabatan,
               COALESCE(p.no_rekening,'') AS no_rekening,
               t.product, t.nominal, t.admin_fee, t.status, t.keterangan, t.created_at
      FROM transactions t
      JOIN users u         ON u.id = t.user_id
      LEFT JOIN pegawai p  ON LOWER(p.email) = LOWER(u.email)
      WHERE 1=1
    """
    params = []
    if periode:
        sql += " AND t.periode = ?"
        params.append(periode)
    if product:
        sql += " AND t.product = ?"
        params.append(product)
    if status:
        sql += " AND t.status = ?"
        params.append(status)
    sql += " ORDER BY t.periode DESC, t.tanggal DESC, t.id DESC"

    rows = get_db().execute(sql, params).fetchall()

    # Buat CSV in-memory (UTF-8-SIG nyaman di Excel)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["ID","Tanggal","Periode","Pegawai","Email","Perusahaan","Jabatan","No Rekening",
                "Produk","Nominal","Admin","Status","Keterangan","Dibuat"])
    for r in rows:
        w.writerow([
            r["id"], r["tanggal"], r["periode"], r["pegawai"], r["email_user"],
            r["perusahaan"], r["jabatan"], r["no_rekening"], r["product"], r["nominal"], r["admin_fee"],
            r["status"], (r["keterangan"] or ""), r["created_at"]
        ])

    data = buf.getvalue().encode("utf-8-sig")
    from flask import Response
    fname = "export_dana_talangan"
    if periode: fname += f"_{periode}"
    if product: fname += f"_{product}"
    if status:  fname += f"_{status}"
    fname += ".csv"

    return Response(
        data,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'}
    )


@bp.get("/admin/export_range")
def admin_export_range():
    ret = require_admin()
    if ret: return ret

    start_raw = (request.args.get("start") or "").strip()
    end_raw = (request.args.get("end") or "").strip()
    siklus = (request.args.get("siklus") or "all").strip().upper()

    try:
        start_dt = datetime.strptime(start_raw, "%Y-%m-%d").date()
        end_dt = datetime.strptime(end_raw, "%Y-%m-%d").date()
    except Exception:
        flash("Tanggal awal/akhir tidak valid. Gunakan format YYYY-MM-DD.", "error")
        return redirect(url_for("web.admin_dashboard"))

    if start_dt > end_dt:
        flash("Tanggal awal tidak boleh lebih besar dari tanggal akhir.", "error")
        return redirect(url_for("web.admin_dashboard"))

    if siklus not in ("A", "B", "ALL"):
        siklus = "ALL"

    sql = """
        SELECT t.id, t.tanggal, t.periode,
               u.name   AS pegawai,
               u.email  AS email_user,
               COALESCE(p.perusahaan,'') AS perusahaan,
               COALESCE(p.jabatan,'')    AS jabatan,
               COALESCE(p.no_rekening,'') AS no_rekening,
               COALESCE(p.siklus_gaji,'A') AS siklus,
               t.product, t.nominal, t.admin_fee, t.status, t.keterangan, t.created_at
      FROM transactions t
      JOIN users u         ON u.id = t.user_id
      LEFT JOIN pegawai p  ON LOWER(p.email) = LOWER(u.email)
      WHERE t.tanggal >= ? AND t.tanggal <= ?
    """
    params = [start_dt.isoformat(), end_dt.isoformat()]

    if siklus in ("A", "B"):
        sql += " AND COALESCE(p.siklus_gaji,'A') = ?"
        params.append(siklus)

    sql += " ORDER BY t.tanggal DESC, t.id DESC"

    rows = get_db().execute(sql, params).fetchall()

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["ID","Tanggal","Periode","Pegawai","Email","Perusahaan","Jabatan","No Rekening","Siklus",
                "Produk","Nominal","Admin","Status","Keterangan","Dibuat"])
    for r in rows:
        w.writerow([
            r["id"], r["tanggal"], r["periode"], r["pegawai"], r["email_user"],
            r["perusahaan"], r["jabatan"], r["no_rekening"], r["siklus"], r["product"], r["nominal"],
            r["admin_fee"], r["status"], (r["keterangan"] or ""), r["created_at"]
        ])

    data = buf.getvalue().encode("utf-8-sig")
    from flask import Response
    fname = f"export_dana_talangan_{start_dt.isoformat()}_to_{end_dt.isoformat()}"
    if siklus in ("A", "B"):
        fname += f"_siklus_{siklus}"
    fname += ".csv"

    return Response(
        data,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'}
    )



# =========================================================
# ==================== ADMIN SETTING ======================
# =========================================================
@bp.route("/admin/settings", methods=["GET", "POST"])
def admin_settings():
    ret = require_admin()
    if ret:
        return ret

    db = get_db()
    ppn_enabled = get_ppn_enabled()

    # coba ambil admin dari session id/email; kalau tidak ada, ambil admin pertama
    adm = None
    if session.get("admin_id"):
        adm = db.execute("SELECT id, name, email, password_hash FROM admins WHERE id=?", (session["admin_id"],)).fetchone()
    if not adm and session.get("admin_email"):
        adm = db.execute("SELECT id, name, email, password_hash FROM admins WHERE LOWER(email)=?", (session["admin_email"].lower(),)).fetchone()
    if not adm:
        adm = db.execute("SELECT id, name, email, password_hash FROM admins ORDER BY id LIMIT 1").fetchone()

    if not adm:
        flash("Data admin belum ada. Inisialisasi gagal.", "error")
        return redirect(url_for("web.admin_dashboard"))

    if request.method == "POST":
        form_type = request.form.get("form_type") or "password"
        if form_type == "ppn":
            enabled = request.form.get("ppn_enabled") == "1"
            set_ppn_enabled(enabled)
            flash("Pengaturan PPN diperbarui.", "success")
            return redirect(url_for("web.admin_settings"))

        old_pw = request.form.get("old_password") or ""
        new_pw = request.form.get("new_password") or ""
        new_pw2 = request.form.get("new_password2") or ""

        # izinkan verifikasi menggunakan hash di DB ATAU password ENV (untuk admin default)
        env_ok = (old_pw == current_app.config["ADMIN_PASSWORD"])
        db_ok  = check_password_hash(adm["password_hash"], old_pw)
        if not (env_ok or db_ok):
            flash("Password lama tidak cocok.", "error")
            return render_template("admin_settings.html", admin=adm, ppn_enabled=ppn_enabled)

        if not password_ok(new_pw):
            flash("Password baru minimal 6 karakter.", "error")
            return render_template("admin_settings.html", admin=adm, ppn_enabled=ppn_enabled)

        if new_pw != new_pw2:
            flash("Konfirmasi password baru tidak cocok.", "error")
            return render_template("admin_settings.html", admin=adm, ppn_enabled=ppn_enabled)

        db.execute("UPDATE admins SET password_hash=? WHERE id=?", (generate_password_hash(new_pw), adm["id"]))
        db.commit()

        flash("Password admin berhasil diperbarui. Mulai sekarang Anda bisa login menggunakan kredensial DB.", "success")
        return redirect(url_for("web.admin_dashboard"))

    return render_template("admin_settings.html", admin=adm, ppn_enabled=ppn_enabled)


# =========================================================
# ==================== ADMIN RESET ========================
# =========================================================
@bp.post("/admin/reset")
def admin_reset_data():
    ret = require_admin()
    if ret:
        return ret

    db = get_db()
    # reset data operasional saja: users & transactions
    db.execute("DELETE FROM transactions")
    db.execute("DELETE FROM users")
    db.commit()
    flash("Data operasional (users & transaksi) dibersihkan.", "info")
    return redirect(url_for("web.admin_dashboard"))

@bp.post("/admin/reset_all")
def admin_reset_all():
    ret = require_admin()
    if ret:
        return ret

    db = get_db()
    db.execute("DELETE FROM transactions")
    db.execute("DELETE FROM users")
    db.execute("DELETE FROM user_accounts")
    db.execute("CREATE TABLE IF NOT EXISTS pegawai_archive (pegawai_id INTEGER, snapshot TEXT, deleted_at TEXT)")
    db.execute("DELETE FROM pegawai_archive")
    db.execute("DELETE FROM pegawai")
    db.commit()
    flash("Data operasional dan master pegawai dibersihkan.", "info")
    return redirect(url_for("web.admin_dashboard"))


@bp.post("/admin/products")
def admin_products():
    ret = require_admin()
    if ret:
        return ret

    enabled = request.form.getlist("products")
    enabled = [p for p in enabled if p in ("reg", "urg")]
    if not enabled:
        flash("Minimal satu produk harus aktif.", "error")
        return redirect(url_for("web.admin_dashboard"))

    ppn_enabled = "1" in request.form.getlist("ppn_enabled")
    set_enabled_products(enabled)
    set_ppn_enabled(ppn_enabled)
    flash("Pengaturan produk diperbarui.", "success")
    return redirect(url_for("web.admin_dashboard"))


# ===== Approve / Reject =====
@bp.post("/admin/tx/<int:txid>/approve")
def admin_tx_approve(txid):
    ret = require_admin()
    if ret: return ret
    db = get_db()
    db.execute("UPDATE transactions SET status='sukses' WHERE id=? AND status='on-proses'", (txid,))
    db.commit()
    flash("Transaksi diset sebagai SUKSES.", "success")
    return redirect(url_for("web.admin_dashboard"))

@bp.post("/admin/tx/<int:txid>/reject")
def admin_tx_reject(txid):
    ret = require_admin()
    if ret: return ret
    db = get_db()
    db.execute("UPDATE transactions SET status='ditolak' WHERE id=? AND status='on-proses'", (txid,))
    db.commit()
    flash("Transaksi ditolak.", "info")
    return redirect(url_for("web.admin_dashboard"))

# =========================================================
# ================ MODUL REGISTER + SIGNIN ================
# =========================================================
@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name  = (request.form.get("name")  or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        pw    = request.form.get("password") or ""
        pw2   = request.form.get("password2") or ""

        if not name or not email or not pw or not pw2:
            flash("Semua field wajib diisi.", "error"); return render_template("register.html")
        if len(pw) < 6:
            flash("Password minimal 6 karakter.", "error"); return render_template("register.html")
        if pw != pw2:
            flash("Konfirmasi password tidak cocok.", "error"); return render_template("register.html")

        db = get_db()
        p = db.execute("SELECT * FROM pegawai WHERE email=?", (email,)).fetchone()
        if not p:
            flash("Email Anda belum terdaftar di master pegawai. Hubungi Admin/HR.", "error")
            return render_template("register.html")

        exists = db.execute("SELECT 1 FROM user_accounts WHERE email=?", (email,)).fetchone()
        if exists:
            flash("Email sudah memiliki akun. Silakan masuk.", "error")
            return redirect(url_for("web.login"))

        status = int(p["status_aktif"] or 0)
        db.execute("""INSERT INTO user_accounts (pegawai_id, name, email, password_hash, status_aktif, created_at, register_ip)
                      VALUES (?,?,?,?,?,?,?)""",
                   (p["id"], name, email, generate_password_hash(pw), status,
                    datetime.now().isoformat(timespec="seconds"), request.remote_addr))
        db.commit()

        if status == 1:
            flash("Registrasi berhasil dan akun AKTIF. Silakan masuk.", "success")
        else:
            flash("Registrasi berhasil. Status: menunggu persetujuan admin.", "info")
        return redirect(url_for("web.login"))

    return render_template("register.html")

@bp.route("/reset", methods=["POST"], endpoint="reset")
def reset_db():
    session.clear()
    db = get_db()
    db.execute("DELETE FROM transactions")
    db.execute("DELETE FROM users")
    db.commit()
    flash("Semua data sudah dibersihkan.", "info")
    return redirect(url_for("web.login"))


