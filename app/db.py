import os
import sqlite3
from datetime import datetime

from flask import current_app, g
from werkzeug.security import generate_password_hash


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(
            current_app.config["DB_PATH"],
            detect_types=sqlite3.PARSE_DECLTYPES,
            timeout=30.0,
            check_same_thread=False,
        )
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON;")
        g.db.execute("PRAGMA journal_mode=WAL;")
        g.db.execute("PRAGMA synchronous=NORMAL;")
        g.db.execute("PRAGMA busy_timeout=30000;")
    return g.db


def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript("""
        -- AKUN MODE PROYEK (lama): tetap dipakai untuk simulasi gaji langsung
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE,
            gaji INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        );

        -- Tambahkan kolom 'product' & 'cancel_until' bila belum ada
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            tanggal TEXT NOT NULL,            -- YYYY-MM-DD
            periode TEXT NOT NULL,            -- YYYY-MM
            nominal INTEGER NOT NULL,
            admin_fee INTEGER NOT NULL,
            status TEXT NOT NULL,             -- 'sukses' | 'ditolak' | 'on-proses' | 'dibatalkan'
            keterangan TEXT,
            rekening_tujuan TEXT DEFAULT '',
            rekening_tujuan_label TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            product TEXT DEFAULT 'reg',       -- 'reg' | 'urg'
            cancel_until TEXT,                -- ISO timestamp, window pembatalan
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        -- === Admin & Pegawai master ===
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            avatar_path TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS pegawai (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            id_pegawai TEXT DEFAULT '',
            nama TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            jabatan TEXT,
            gaji INTEGER DEFAULT 0,
            status_aktif INTEGER DEFAULT 0,
            perusahaan TEXT DEFAULT '',
            no_rekening TEXT DEFAULT '',
            no_rekening_lain TEXT DEFAULT '',
            rekening_ewallet TEXT DEFAULT '',
            no_telp TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );

        -- === Akun pegawai formal (email+password) ===
        CREATE TABLE IF NOT EXISTS user_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pegawai_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            status_aktif INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            register_ip TEXT,
            avatar_path TEXT DEFAULT '',
            FOREIGN KEY (pegawai_id) REFERENCES pegawai(id)
        );

        -- === App settings (global) ===
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        -- === Lightweight test writes (for /txn/test) ===
        CREATE TABLE IF NOT EXISTS txn_tests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL
        );

        -- === App settings (global) ===
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        -- ==== Indexes to speed up first-time queries / lookups ====
        CREATE INDEX IF NOT EXISTS idx_trx_user_periode
            ON transactions(user_id, periode);

        CREATE INDEX IF NOT EXISTS idx_trx_user_periode_status_tanggal
            ON transactions(user_id, periode, status, tanggal);

        CREATE INDEX IF NOT EXISTS idx_users_name ON users(name);
        CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

        CREATE INDEX IF NOT EXISTS idx_trx_tanggal
            ON transactions(tanggal);

        CREATE INDEX IF NOT EXISTS idx_trx_status
            ON transactions(status);

        CREATE INDEX IF NOT EXISTS idx_trx_status_tanggal
            ON transactions(status, tanggal);

        CREATE INDEX IF NOT EXISTS idx_trx_product
            ON transactions(product);
    """)

    db.commit()

    _migrate_users_email_unique(db)
    _fix_transactions_fk_users_old(db)

    # === MIGRASI: tambahkan kolom id_pegawai bila belum ada ===
    try:
        db.execute("ALTER TABLE pegawai ADD COLUMN id_pegawai TEXT DEFAULT ''")
        db.commit()
        print("[DB] kolom id_pegawai ditambahkan.")
    except Exception:
        pass
    try:
        db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_pegawai_id_pegawai "
            "ON pegawai(id_pegawai) WHERE id_pegawai <> ''"
        )
        db.commit()
    except Exception:
        pass

    # === MIGRASI: tambahkan kolom siklus_gaji bila belum ada ===
    try:
        db.execute("ALTER TABLE pegawai ADD COLUMN siklus_gaji TEXT DEFAULT 'A'")
        db.commit()
        print("[DB] kolom siklus_gaji ditambahkan.")
    except sqlite3.OperationalError:
        pass
    # === MIGRASI: tambahkan kolom no_rekening bila belum ada ===
    try:
        db.execute("ALTER TABLE pegawai ADD COLUMN no_rekening TEXT DEFAULT ''")
        db.commit()
        print("[DB] kolom no_rekening ditambahkan.")
    except sqlite3.OperationalError:
        pass
    # === MIGRASI: tambahkan kolom rekening bank lain bila belum ada ===
    try:
        db.execute("ALTER TABLE pegawai ADD COLUMN no_rekening_lain TEXT DEFAULT ''")
        db.commit()
        print("[DB] kolom no_rekening_lain ditambahkan.")
    except sqlite3.OperationalError:
        pass
    # === MIGRASI: tambahkan kolom rekening e-wallet bila belum ada ===
    try:
        db.execute("ALTER TABLE pegawai ADD COLUMN rekening_ewallet TEXT DEFAULT ''")
        db.commit()
        print("[DB] kolom rekening_ewallet ditambahkan.")
    except sqlite3.OperationalError:
        pass
    # === MIGRASI: tambahkan kolom no_telp bila belum ada ===
    try:
        db.execute("ALTER TABLE pegawai ADD COLUMN no_telp TEXT DEFAULT ''")
        db.commit()
        print("[DB] kolom no_telp ditambahkan.")
    except sqlite3.OperationalError:
        pass
    # === MIGRASI: tambahkan kolom avatar_path bila belum ada ===
    try:
        db.execute("ALTER TABLE user_accounts ADD COLUMN avatar_path TEXT DEFAULT ''")
        db.commit()
        print("[DB] kolom avatar_path (user_accounts) ditambahkan.")
    except sqlite3.OperationalError:
        pass
    try:
        db.execute("ALTER TABLE admins ADD COLUMN avatar_path TEXT DEFAULT ''")
        db.commit()
        print("[DB] kolom avatar_path (admins) ditambahkan.")
    except sqlite3.OperationalError:
        pass

    # seed admin default jika kosong
    admin = db.execute("SELECT id FROM admins LIMIT 1").fetchone()
    if not admin:
        db.execute(
            "INSERT INTO admins (name, email, password_hash, created_at) VALUES (?,?,?,?)",
            (
                "Administrator",
                "admin@example.com",
                generate_password_hash("admin123"),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        db.commit()

    # seed default product visibility (reg, urg)
    has_setting = db.execute(
        "SELECT 1 FROM app_settings WHERE key='enabled_products' LIMIT 1"
    ).fetchone()
    if not has_setting:
        db.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?)",
            ("enabled_products", "reg,urg"),
        )
        db.commit()

    # --- harden: tambah kolom 'notified_onproses' bila belum ada ---
    try:
        db.execute("ALTER TABLE transactions ADD COLUMN notified_onproses INTEGER DEFAULT 0")
        db.commit()
    except Exception:
        pass

    # --- kolom lock URG (tanggal sampai kapan URG mengunci hak ke depan) ---
    try:
        db.execute("ALTER TABLE transactions ADD COLUMN urg_lock_until TEXT")
        db.commit()
    except Exception:
        pass

    # --- rekening tujuan yang dipilih saat transaksi dibuat ---
    try:
        db.execute("ALTER TABLE transactions ADD COLUMN rekening_tujuan TEXT DEFAULT ''")
        db.commit()
        print("[DB] kolom rekening_tujuan ditambahkan.")
    except Exception:
        pass
    try:
        db.execute("ALTER TABLE transactions ADD COLUMN rekening_tujuan_label TEXT DEFAULT ''")
        db.commit()
        print("[DB] kolom rekening_tujuan_label ditambahkan.")
    except Exception:
        pass


def ensure_db():
    db_path = current_app.config["DB_PATH"]
    if not os.path.exists(db_path):
        open(db_path, "a").close()
    init_db()


def _migrate_users_email_unique(db):
    try:
        idx_list = db.execute("PRAGMA index_list('users')").fetchall()
        unique_indexes = [r for r in idx_list if int(r[2] or 0) == 1]
        has_unique_email = False
        has_unique_name = False
        for idx in unique_indexes:
            cols = [c[2] for c in db.execute(f"PRAGMA index_info('{idx[1]}')").fetchall()]
            if "email" in cols:
                has_unique_email = True
            if "name" in cols:
                has_unique_name = True

        if has_unique_email or not has_unique_name:
            return

        rows = db.execute("SELECT id, name, email, gaji, created_at FROM users ORDER BY id").fetchall()

        keep_by_email = {}
        duplicates = {}
        for r in rows:
            email = (r["email"] or "").strip()
            if not email:
                continue
            key = email.lower()
            if key in keep_by_email:
                duplicates[r["id"]] = keep_by_email[key]["id"]
            else:
                keep_by_email[key] = r

        db.execute("PRAGMA foreign_keys=OFF;")
        db.execute("ALTER TABLE users RENAME TO users_old;")
        db.execute("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE,
                gaji INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            );
        """)

        for r in rows:
            if r["id"] in duplicates:
                continue
            db.execute(
                "INSERT INTO users(id, name, email, gaji, created_at) VALUES (?,?,?,?,?)",
                (r["id"], r["name"], r["email"], r["gaji"], r["created_at"]),
            )

        for dup_id, keep_id in duplicates.items():
            db.execute("UPDATE transactions SET user_id=? WHERE user_id=?", (keep_id, dup_id))

        db.execute("DROP TABLE users_old;")
        db.execute("CREATE INDEX IF NOT EXISTS idx_users_name ON users(name);")
        db.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);")

        try:
            db.execute(
                "UPDATE sqlite_sequence SET seq=(SELECT MAX(id) FROM users) WHERE name='users'"
            )
        except Exception:
            pass

        db.commit()
        db.execute("PRAGMA foreign_keys=ON;")
    except Exception as e:
        db.rollback()
        try:
            db.execute("PRAGMA foreign_keys=ON;")
        except Exception:
            pass
        print(f"[DB] users migration skipped: {e}")


def _fix_transactions_fk_users_old(db):
    """
    Perbaiki foreign key transactions yang masih mengarah ke users_old
    akibat proses rename users pada migrasi sebelumnya.
    """
    try:
        fks = db.execute("PRAGMA foreign_key_list('transactions')").fetchall()
        if not any(r[2] == "users_old" for r in fks):
            return

        db.execute("PRAGMA foreign_keys=OFF;")
        db.execute("ALTER TABLE transactions RENAME TO transactions_old;")

        db.execute("""
            CREATE TABLE transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                tanggal TEXT NOT NULL,
                periode TEXT NOT NULL,
                nominal INTEGER NOT NULL,
                admin_fee INTEGER NOT NULL,
                status TEXT NOT NULL,
                keterangan TEXT,
                rekening_tujuan TEXT DEFAULT '',
                rekening_tujuan_label TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                product TEXT DEFAULT 'reg',
                cancel_until TEXT,
                notified_onproses INTEGER DEFAULT 0,
                urg_lock_until TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
        """)

        cols_old = [r[1] for r in db.execute("PRAGMA table_info('transactions_old')").fetchall()]
        cols_new = [
            "id",
            "user_id",
            "tanggal",
            "periode",
            "nominal",
            "admin_fee",
            "status",
            "keterangan",
            "rekening_tujuan",
            "rekening_tujuan_label",
            "created_at",
            "product",
            "cancel_until",
            "notified_onproses",
            "urg_lock_until",
        ]
        cols_copy = [c for c in cols_new if c in cols_old]
        if cols_copy:
            cols_csv = ",".join(cols_copy)
            db.execute(
                f"INSERT INTO transactions ({cols_csv}) SELECT {cols_csv} FROM transactions_old"
            )

        db.execute("DROP TABLE transactions_old;")
        db.execute("CREATE INDEX IF NOT EXISTS idx_trx_user_periode ON transactions(user_id, periode);")
        db.execute("CREATE INDEX IF NOT EXISTS idx_trx_user_periode_status_tanggal ON transactions(user_id, periode, status, tanggal);")
        db.execute("CREATE INDEX IF NOT EXISTS idx_trx_tanggal ON transactions(tanggal);")
        db.execute("CREATE INDEX IF NOT EXISTS idx_trx_status ON transactions(status);")
        db.execute("CREATE INDEX IF NOT EXISTS idx_trx_status_tanggal ON transactions(status, tanggal);")
        db.execute("CREATE INDEX IF NOT EXISTS idx_trx_product ON transactions(product);")

        try:
            db.execute(
                "UPDATE sqlite_sequence SET seq=(SELECT MAX(id) FROM transactions) WHERE name='transactions'"
            )
        except Exception:
            pass

        db.commit()
        db.execute("PRAGMA foreign_keys=ON;")
        print("[DB] transaksi FK users_old diperbaiki.")
    except Exception as e:
        db.rollback()
        try:
            db.execute("PRAGMA foreign_keys=ON;")
        except Exception:
            pass
        print(f"[DB] perbaikan FK transactions gagal: {e}")
