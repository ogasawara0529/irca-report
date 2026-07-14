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
        cur.execute("""
            CREATE TABLE IF NOT EXISTS report_items (
                id SERIAL PRIMARY KEY,
                date_iso DATE NOT NULL,
                subject VARCHAR(255),
                content TEXT NOT NULL,
                url TEXT,
                created_by VARCHAR(100),
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS report_item_files (
                id SERIAL PRIMARY KEY,
                report_item_id INTEGER NOT NULL REFERENCES report_items(id) ON DELETE CASCADE,
                filename VARCHAR(255) NOT NULL,
                content_type VARCHAR(100),
                data BYTEA NOT NULL,
                size INTEGER NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        # 旧カラム名（item_count）からの移行
        cur.execute("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'report_items' AND column_name = 'item_count'
        """)
        if cur.fetchone():
            cur.execute("ALTER TABLE report_items RENAME COLUMN item_count TO subject")
            cur.execute("ALTER TABLE report_items ALTER COLUMN subject TYPE VARCHAR(255) USING subject::VARCHAR(255)")


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


# ── 報告事項操作 ──────────────────────────────────────────────

def list_report_items(date_iso: str):
    """指定報告日の報告事項一覧（添付ファイルは一覧情報のみ、本体データは含まない）"""
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("""
            SELECT id, subject, content, url, created_by, created_at
            FROM report_items WHERE date_iso = %s ORDER BY id
        """, (date_iso,))
        items = [dict(row) for row in cur.fetchall()]
        for item in items:
            cur.execute("""
                SELECT id, filename, content_type, size FROM report_item_files
                WHERE report_item_id = %s ORDER BY id
            """, (item['id'],))
            item['files'] = [dict(row) for row in cur.fetchall()]
        return items


def get_report_item(item_id: int):
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("""
            SELECT id, date_iso, subject, content, url, created_by, created_at
            FROM report_items WHERE id = %s
        """, (item_id,))
        row = cur.fetchone()
        if not row:
            return None
        item = dict(row)
        cur.execute("""
            SELECT id, filename, content_type, size FROM report_item_files
            WHERE report_item_id = %s ORDER BY id
        """, (item_id,))
        item['files'] = [dict(r) for r in cur.fetchall()]
        return item


def create_report_item(date_iso: str, subject: str, content: str, url: str, created_by: str) -> int:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO report_items (date_iso, subject, content, url, created_by)
            VALUES (%s, %s, %s, %s, %s) RETURNING id
        """, (date_iso, subject, content, url, created_by))
        return cur.fetchone()[0]


def add_report_item_file(report_item_id: int, filename: str, content_type: str, data: bytes) -> int:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO report_item_files (report_item_id, filename, content_type, data, size)
            VALUES (%s, %s, %s, %s, %s) RETURNING id
        """, (report_item_id, filename, content_type, psycopg2.Binary(data), len(data)))
        return cur.fetchone()[0]


def get_report_item_file(file_id: int):
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("""
            SELECT filename, content_type, data FROM report_item_files WHERE id = %s
        """, (file_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def delete_report_item(item_id: int):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM report_items WHERE id = %s", (item_id,))
