import csv
import io
import os
import threading
import time
from datetime import date, datetime

from app.db import get_db
from app.services.email_service import send_email


_scheduler_started = False

EXPORT_INTERVAL_SECONDS = 2 * 24 * 60 * 60
LAST_RUN_KEY = "export_csv_last_run"


def _get_setting(db, key: str):
    row = db.execute(
        "SELECT value FROM app_settings WHERE key=? LIMIT 1",
        (key,),
    ).fetchone()
    return row["value"] if row else None


def _set_setting(db, key: str, value: str):
    cur = db.execute(
        "UPDATE app_settings SET value=? WHERE key=?",
        (value, key),
    )
    if cur.rowcount == 0:
        db.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?)",
            (key, value),
        )
    db.commit()


def _current_period_range():
    today = date.today()
    start = date(today.year, today.month, 1)
    if today.month == 12:
        end = date(today.year + 1, 1, 1)
    else:
        end = date(today.year, today.month + 1, 1)
    return start, end


def _build_csv_bytes(rows):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "ID",
            "Tanggal",
            "Periode",
            "ID Pegawai",
            "Pegawai",
            "Email",
            "Perusahaan",
            "Jabatan",
            "No Rekening",
            "Produk",
            "Nominal",
            "Admin",
            "Status",
            "Keterangan",
            "Dibuat",
        ]
    )
    for r in rows:
        writer.writerow(
            [
                r["id"],
                r["tanggal"],
                r["periode"],
                r["id_pegawai"],
                r["pegawai"],
                r["email_user"],
                r["perusahaan"],
                r["jabatan"],
                r["no_rekening"],
                r["product"],
                r["nominal"],
                r["admin_fee"],
                r["status"],
                r["keterangan"] or "",
                r["created_at"],
            ]
        )
    return buf.getvalue().encode("utf-8-sig")


def _export_current_period_csv():
    db = get_db()
    start, end = _current_period_range()
    rows = db.execute(
        """
        SELECT t.id, t.tanggal, t.periode,
               u.name AS pegawai,
               u.email AS email_user,
               COALESCE(p.id_pegawai,'') AS id_pegawai,
               COALESCE(p.perusahaan,'') AS perusahaan,
               COALESCE(p.jabatan,'') AS jabatan,
               COALESCE(p.no_rekening,'') AS no_rekening,
               t.product, t.nominal, t.admin_fee, t.status, t.keterangan, t.created_at
        FROM transactions t
        JOIN users u ON u.id = t.user_id
        LEFT JOIN pegawai p ON LOWER(p.email) = LOWER(u.email)
        WHERE t.tanggal >= ? AND t.tanggal < ?
        ORDER BY t.tanggal DESC, t.id DESC
        """,
        (start.isoformat(), end.isoformat()),
    ).fetchall()
    data = _build_csv_bytes(rows)

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    out_dir = os.path.join(root, "data", "csv")
    os.makedirs(out_dir, exist_ok=True)
    period_label = start.strftime("%Y-%m")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"export_periode_{period_label}_{stamp}.csv"
    full_path = os.path.join(out_dir, filename)
    with open(full_path, "wb") as f:
        f.write(data)
    return filename, full_path, data, start, end, len(rows)


def _should_run(db):
    last = _get_setting(db, LAST_RUN_KEY)
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(last)
    except Exception:
        return True
    return (datetime.now() - last_dt).total_seconds() >= EXPORT_INTERVAL_SECONDS


def _run_export_job(app):
    with app.app_context():
        db = get_db()
        if not _should_run(db):
            return
        filename, full_path, data, start, end, total_rows = _export_current_period_csv()
        period_label = start.strftime("%Y-%m")
        subject = f"[Auto Export] CSV Periode {period_label}"
        body = (
            f"Export otomatis periode berjalan.\n"
            f"Periode: {start.isoformat()} s.d {end.isoformat()} (eksklusif)\n"
            f"Total baris: {total_rows}\n"
            f"File: {full_path}\n"
        )
        sent = send_email(
            subject,
            body,
            attachments=[
                {
                    "filename": filename,
                    "content": data,
                    "mimetype": "text/csv",
                }
            ],
        )
        if sent:
            _set_setting(db, LAST_RUN_KEY, datetime.now().isoformat(timespec="seconds"))
        else:
            app.logger.warning("[EXPORT] email gagal, last_run tidak diperbarui.")


def start_export_scheduler(app, interval_seconds=3600):
    global _scheduler_started
    if _scheduler_started:
        return
    _scheduler_started = True

    def _loop():
        while True:
            try:
                _run_export_job(app)
            except Exception as exc:
                app.logger.warning(f"[EXPORT] scheduler gagal: {exc}")
            time.sleep(interval_seconds)

    thread = threading.Thread(target=_loop, daemon=True)
    thread.start()
