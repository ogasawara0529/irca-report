"""
Neon (PostgreSQL) データベース操作モジュール
JSON ファイルの代わりに全データを PostgreSQL に保存する
"""
import json
import os
import psycopg2
import psycopg2.extras
from contextlib import contextmanager

DATABASE_URL = os.environ.get('DATABASE_URL', '')


@contextmanager
def get_conn():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """テーブルを作成（存在しない場合のみ）"""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                date_iso DATE PRIMARY KEY,
                data JSONB NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                no SERIAL PRIMARY KEY,
                created_at DATE NOT NULL DEFAULT CURRENT_DATE,
                username VARCHAR(100) UNIQUE NOT NULL,
                password_hash VARCHAR(256) NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'active',
                role VARCHAR(20) NOT NULL DEFAULT 'user'
            )
        """)


# ── レポート操作 ──────────────────────────────────────────────

def save_report(date_iso: str, data: dict):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO reports (date_iso, data)
            VALUES (%s, %s)
            ON CONFLICT (date_iso) DO UPDATE SET data = EXCLUDED.data
        """, (date_iso, json.dumps(data, ensure_ascii=False)))


def load_report(date_iso: str):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT data FROM reports WHERE date_iso = %s", (date_iso,))
        row = cur.fetchone()
        return row[0] if row else None


def get_latest_report():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT data FROM reports ORDER BY date_iso DESC LIMIT 1")
        row = cur.fetchone()
        return row[0] if row else None


def get_prev_report(date_iso: str):
    """指定日付より前の直近レポートを取得"""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT data FROM reports WHERE date_iso < %s ORDER BY date_iso DESC LIMIT 1",
            (date_iso,)
        )
        row = cur.fetchone()
        return row[0] if row else None


def get_index():
    """全レポート日付のリスト（降順）"""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT date_iso::text FROM reports ORDER BY date_iso DESC")
        return [row[0] for row in cur.fetchall()]


def get_last_report_date():
    """最新レポートの日付文字列 (YYYY-MM-DD)"""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT date_iso::text FROM reports ORDER BY date_iso DESC LIMIT 1")
        row = cur.fetchone()
        return row[0] if row else None


def delete_report(date_iso: str):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM reports WHERE date_iso = %s", (date_iso,))


# ── アカウント操作 ────────────────────────────────────────────

def get_accounts():
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("SELECT * FROM accounts ORDER BY no")
        return [dict(row) for row in cur.fetchall()]


def get_account_by_username(username: str):
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("SELECT * FROM accounts WHERE username = %s", (username,))
        row = cur.fetchone()
        return dict(row) if row else None


def create_account(username, password_hash, role='user', status='active'):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO accounts (username, password_hash, status, role)
            VALUES (%s, %s, %s, %s) RETURNING no
        """, (username, password_hash, status, role))
        return cur.fetchone()[0]


def update_account(no: int, fields: dict):
    if not fields:
        return
    sets = ', '.join(f"{k} = %s" for k in fields)
    vals = list(fields.values()) + [no]
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE accounts SET {sets} WHERE no = %s", vals)


def delete_account_by_no(no: int):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM accounts WHERE no = %s", (no,))


def account_count():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM accounts")
        return cur.fetchone()[0]
