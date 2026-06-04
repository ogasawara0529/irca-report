#!/usr/bin/env python3
"""
irca-report Flask サーバー
- 静的ファイル・データファイルを配信
- POST /api/collect : 指定日付でFileMakerからデータ集計して保存
"""
import base64
import json
import logging
import os
import requests as req
from datetime import date
from flask import Flask, jsonify, request, send_from_directory, session, redirect
from functools import wraps
from pathlib import Path
from urllib.parse import quote
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / 'data'

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler(BASE_DIR / 'server.log', encoding='utf-8'),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)

# ── 設定読み込み ─────────────────────────────────────────────
_env_path = BASE_DIR / 'config.env'
if _env_path.exists():
    for _line in _env_path.read_text(encoding='utf-8').splitlines():
        _line = _line.strip()
        if _line and not _line.startswith('#') and '=' in _line:
            _k, _, _v = _line.partition('=')
            os.environ.setdefault(_k.strip(), _v.strip())

FM_HOST               = os.environ.get('FM_HOST', '')
FM_DATABASE           = os.environ.get('FM_DATABASE', '')
FM_LAYOUT             = os.environ.get('FM_LAYOUT', '')
FM_USER               = os.environ.get('FM_USER', '')
FM_PASSWORD           = os.environ.get('FM_PASSWORD', '')
FM_VERIFY_SSL         = os.environ.get('FM_VERIFY_SSL', 'true').lower() != 'false'
CUSTOMER_KEYWORDS     = [k.strip() for k in os.environ.get('CUSTOMER_REASON_KEYWORDS', 'お客様都合').split(',')]
FM_FIELD_PROJECT_NAME  = os.environ.get('FM_FIELD_PROJECT_NAME', 'プロジェクト名')
FM_DATE_FORMAT         = os.environ.get('FM_DATE_FORMAT', 'YYYYMD')
FM_LAYOUT_BREAKDOWN    = os.environ.get('FM_LAYOUT_BREAKDOWN', FM_LAYOUT)
PORT                   = int(os.environ.get('PORT', os.environ.get('SERVER_PORT', '5001')))

BASE_URL                  = f'https://{FM_HOST}/fmi/data/v1/databases/{FM_DATABASE}'
LAYOUT_ENCODED            = quote(FM_LAYOUT)
LAYOUT_BREAKDOWN_ENCODED  = quote(FM_LAYOUT_BREAKDOWN)
PROJECT_TYPE   = 'プロジェクト型'
PORTAL_NAME    = 'プロジェクト_納品日変更履歴'

SECRET_KEY = os.environ.get('SECRET_KEY', 'irca-change-this-secret-key')

app = Flask(__name__)
app.secret_key = SECRET_KEY

# DB モジュールをインポート（DATABASE_URL が設定されていれば使用）
import db as _db
_db.DATABASE_URL = os.environ.get('DATABASE_URL', '')
USE_DB = bool(_db.DATABASE_URL)

if USE_DB:
    try:
        _db.init_db()
        # 初回起動時にデフォルト管理者が存在しなければ作成
        if _db.account_count() == 0:
            _db.create_account('admin', generate_password_hash('admin', method='pbkdf2:sha256'), role='admin')
            logger.info('デフォルト管理者アカウントを作成しました (admin/admin)')
        logger.info('Neon DB 接続成功')
    except Exception as e:
        logger.error(f'Neon DB 接続失敗: {e}')
        USE_DB = False


# ── 認証デコレータ ─────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session:
            if request.path.startswith('/api/'):
                return jsonify({'error': 'unauthorized'}), 401
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'error': 'unauthorized'}), 401
        if session['user'].get('role') != 'admin':
            return jsonify({'error': 'forbidden'}), 403
        return f(*args, **kwargs)
    return decorated


# ── CORS ヘッダー（IIS との共存用）───────────────────────────
@app.after_request
def add_cors(resp):
    resp.headers['Access-Control-Allow-Origin']  = '*'
    resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return resp

@app.route('/api/collect', methods=['OPTIONS'])
def collect_options():
    return '', 204


# ── ユーティリティ ────────────────────────────────────────────
def fm_date(d: date) -> str:
    """FileMaker クエリ・更新用（FM_DATE_FORMAT に従う）"""
    if FM_DATE_FORMAT == 'MDY':
        return f'{d.month}/{d.day}/{d.year}'
    return f'{d.year}/{d.month}/{d.day}'

def display_date(d: date) -> str:
    """JSON 保存・表示用（常に YYYY/M/D）"""
    return f'{d.year}/{d.month}/{d.day}'

def convert_fm_date(s: str) -> str:
    """FileMaker から返ってきた日付を表示用 YYYY/M/D に変換"""
    if not s:
        return s
    if FM_DATE_FORMAT == 'MDY':
        try:
            parts = s.split('/')
            if len(parts) == 3:
                return f'{parts[2]}/{int(parts[0])}/{int(parts[1])}'
        except Exception:
            pass
    return s

def _parse_fm_date(s):
    if not s:
        return None
    try:
        parts = str(s).replace('-', '/').split('/')
        if len(parts) == 3:
            if FM_DATE_FORMAT == 'MDY':
                # M/D/YYYY 形式
                return date(int(parts[2]), int(parts[0]), int(parts[1]))
            else:
                # YYYY/M/D 形式
                return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except Exception:
        return None

def _detail(rec: dict) -> dict:
    fd = rec['fieldData']
    return {
        'cd':              fd.get('プロジェクトCD', ''),
        'client':          fd.get('取引先名', ''),
        'name':            fd.get(FM_FIELD_PROJECT_NAME, ''),
        'sales':           fd.get('営業担当者', ''),
        'pm':              fd.get('PM担当者', ''),
        'start_date':      convert_fm_date(fd.get('開発開始日', '')),
        'delivery_date':   convert_fm_date(fd.get('納品予定日_最終', '')),
        'completion_date': convert_fm_date(fd.get('納品日', '')),
        'progress':        fd.get('開発完了率_入力', ''),
        'dept':            fd.get('PM担当者_所属課', ''),
    }


# ── FileMaker クライアント ────────────────────────────────────
class FMClient:
    def __init__(self):
        self.session = req.Session()
        self.session.verify = FM_VERIFY_SSL
        self.token = None

    def __enter__(self):
        creds = base64.b64encode(f'{FM_USER}:{FM_PASSWORD}'.encode()).decode()
        resp = self.session.post(
            f'{BASE_URL}/sessions',
            headers={'Authorization': f'Basic {creds}', 'Content-Type': 'application/json'},
            json={}, timeout=30,
        )
        resp.raise_for_status()
        self.token = resp.json()['response']['token']
        logger.info('FileMaker ログイン成功')
        return self

    def __exit__(self, *_):
        if self.token:
            try:
                self.session.delete(
                    f'{BASE_URL}/sessions/{self.token}',
                    headers={'Authorization': f'Bearer {self.token}'}, timeout=10,
                )
            except Exception:
                pass
            self.token = None

    def _find(self, query, portal=None):
        body = {'query': query, 'limit': '100000'}
        if portal:
            body['portal'] = portal
        logger.debug(f'_find query: {json.dumps(query, ensure_ascii=False)}')
        resp = self.session.post(
            f'{BASE_URL}/layouts/{LAYOUT_ENCODED}/_find',
            headers={'Authorization': f'Bearer {self.token}', 'Content-Type': 'application/json'},
            json=body, timeout=60,
        )
        try:
            data = resp.json()
        except Exception:
            resp.raise_for_status()
            return {}

        code = str(data.get('messages', [{}])[0].get('code', '0'))
        msg  = data.get('messages', [{}])[0].get('message', '')

        if code == '401':
            logger.info('検索結果 0 件')
            return {'response': {'dataInfo': {'foundCount': 0}, 'data': []}}

        # ポータルがレイアウトに存在しない → ポータルなしで再試行
        if code == '110' and portal:
            logger.warning(f'ポータル {portal} がレイアウトに存在しません。ポータルなしで再試行します。')
            return self._find(query, portal=None)

        if resp.status_code >= 400 or (code != '0'):
            logger.error(f'FileMaker エラー HTTP={resp.status_code} code={code}: {msg}')
            logger.error(f'  query: {json.dumps(query, ensure_ascii=False)}')
            raise Exception(f'FileMaker エラー (code {code}): {msg}')

        return data

    def records(self, query, portal=None):
        return self._find(query, portal=portal)['response']['data']

    def records_breakdown(self, query, portal=None):
        """内訳用：プロジェクト詳細レイアウトで検索（ポータルあり）"""
        body = {'query': query, 'limit': '100000'}
        if portal:
            body['portal'] = portal
        resp = self.session.post(
            f'{BASE_URL}/layouts/{LAYOUT_BREAKDOWN_ENCODED}/_find',
            headers={'Authorization': f'Bearer {self.token}', 'Content-Type': 'application/json'},
            json=body, timeout=60,
        )
        data = resp.json()
        code = str(data.get('messages', [{}])[0].get('code', '0'))
        if code == '401':
            return []
        if code == '110' and portal:
            logger.warning('内訳レイアウトにポータルが存在しません。ポータルなしで再試行します。')
            return self.records_breakdown(query, portal=None)
        if resp.status_code >= 400 or (code != '0'):
            logger.error(f'内訳レイアウトエラー code={code}')
            return []
        return data['response']['data']

    def update(self, record_id, field_data):
        logger.debug(f'update record {record_id}: {field_data}')
        resp = self.session.patch(
            f'{BASE_URL}/layouts/{LAYOUT_ENCODED}/records/{record_id}',
            headers={'Authorization': f'Bearer {self.token}', 'Content-Type': 'application/json'},
            json={'fieldData': field_data}, timeout=30,
        )
        try:
            data = resp.json()
            code = str(data.get('messages', [{}])[0].get('code', '0'))
            msg  = data.get('messages', [{}])[0].get('message', '')
            if resp.status_code >= 400 or (code != '0'):
                raise Exception(f'FileMaker update エラー (code {code}): {msg}')
        except Exception as e:
            if 'update エラー' in str(e):
                raise
            resp.raise_for_status()


# ── 集計ロジック ─────────────────────────────────────────────
def run_collect(report_date, p1s, p1e, p2s, p2e, p3s, p3e, last_report, prev_scheduled=0) -> dict:
    today_fm     = fm_date(report_date)      # FileMaker 更新・クエリ用
    today_str    = display_date(report_date) # JSON 保存・表示用
    range1       = f'{fm_date(p1s)}...{fm_date(p1e)}'
    range2       = f'{fm_date(p2s)}...{fm_date(p2e)}'
    range3       = f'{fm_date(p3s)}...{fm_date(p3e)}'
    last_rep_fm  = fm_date(last_report)      # FileMaker クエリ用
    last_rep_str = display_date(last_report) # JSON 保存・表示用

    with FMClient() as client:
        recs_1 = client.records([{'プロジェクト区分': PROJECT_TYPE, '開発開始日': range1}])
        recs_2 = client.records([{'プロジェクト区分': PROJECT_TYPE, '納品日':      range2}])
        recs_3 = client.records([{'プロジェクト区分': PROJECT_TYPE, '納品予定日_最終': range3}])

        for rec in recs_3:
            client.update(rec['recordId'], {'報告日_朝会': today_fm})
        logger.info(f'① {len(recs_1)}件  ② {len(recs_2)}件  ③ {len(recs_3)}件  報告日_朝会更新完了')

        # 先週③の内訳（内訳専用レイアウトで取得）
        base        = {'プロジェクト区分': PROJECT_TYPE, '報告日_朝会': last_rep_fm}
        all_bd_recs = client.records_breakdown([base], portal=[PORTAL_NAME])

    count_done = count_wait = count_cust = count_sup = count_missed = 0
    complete_details  = []
    incomplete_details = []

    for rec in all_bd_recs:
        fd           = rec['fieldData']
        delivery_day = _parse_fm_date(fd.get('納品日', ''))

        if delivery_day and p2s <= delivery_day <= p2e:
            count_done += 1
            d_rec = _detail(rec); d_rec['category'] = 'done'
            complete_details.append(d_rec)
        elif fd.get('status', '') == '納品済・検収待':
            count_wait += 1
            d = _detail(rec); d['category'] = 'waiting'
            incomplete_details.append(d)
        else:
            final_day = _parse_fm_date(fd.get('納品予定日_最終', ''))
            if final_day and final_day > p2e:
                portal_rows = rec.get('portalData', {}).get(PORTAL_NAME, [])
                reason = ''
                if portal_rows:
                    reason = portal_rows[-1].get(f'{PORTAL_NAME}::納品日変更理由', '') or ''
                cat = 'cust' if any(kw in reason for kw in CUSTOMER_KEYWORDS) else 'sup'
                if cat == 'cust': count_cust += 1
                else:             count_sup  += 1
            else:
                count_missed += 1
                cat = 'missed'
            d = _detail(rec); d['category'] = cat
            incomplete_details.append(d)

    logger.info(f'内訳 完了:{count_done} 検収待:{count_wait} お客様:{count_cust} sup:{count_sup} 漏れ:{count_missed}')

    return {
        'report_date':      today_str,
        'period':           {'start': display_date(p1s), 'end': display_date(p1e)},
        'this_week_period': {'start': display_date(p3s), 'end': display_date(p3e)},
        'last_report_date': last_rep_str,
        'counts':           {'started': len(recs_1), 'completed': len(recs_2), 'scheduled': len(recs_3)},
        'last_week_breakdown': {
            'total':          len(all_bd_recs),   # 内訳計算用（報告日_朝会がセットされた実件数）
            'prev_scheduled': prev_scheduled,      # ②サブ表示の Y（前回レポートの③件数）
            'done':              count_done, 'waiting': count_wait,
            'customer_reason':   count_cust, 'sup_reason': count_sup,
            'missed_update':     count_missed,
            'complete_details':  complete_details,
            'incomplete_details': incomplete_details,
        },
        'details': {
            'started':   [_detail(r) for r in recs_1],
            'completed': [_detail(r) for r in recs_2],
            'scheduled': [_detail(r) for r in recs_3],
        },
    }


def save_report(result: dict, report_date: date) -> str:
    date_iso = report_date.isoformat()
    if USE_DB:
        _db.save_report(date_iso, result)
    else:
        # ファイルフォールバック
        DATA_DIR.mkdir(exist_ok=True)
        (DATA_DIR / 'reports').mkdir(exist_ok=True)
        out = json.dumps(result, ensure_ascii=False, indent=2)
        (DATA_DIR / 'report.json').write_text(out, encoding='utf-8')
        (DATA_DIR / 'reports' / f'{date_iso}.json').write_text(out, encoding='utf-8')
        index_path = DATA_DIR / 'index.json'
        dates_list = json.loads(index_path.read_text(encoding='utf-8')) if index_path.exists() else []
        if date_iso not in dates_list:
            dates_list.append(date_iso)
        dates_list.sort(reverse=True)
        index_path.write_text(json.dumps(dates_list, ensure_ascii=False), encoding='utf-8')
    logger.info(f'保存完了: {date_iso}')
    return date_iso


# ── API エンドポイント ────────────────────────────────────────
@app.route('/api/collect', methods=['POST'])
def api_collect():
    try:
        body = request.get_json()

        def pd(key):
            return date.fromisoformat(body[key])

        report_date = pd('report_date')
        p1s = pd('period1_start'); p1e = pd('period1_end')
        p2s = pd('period2_start'); p2e = pd('period2_end')
        p3s = pd('period3_start'); p3e = pd('period3_end')

        # 先週の報告日（DB優先）
        if USE_DB:
            prev_dates = [d for d in _db.get_index() if d < body['report_date']]
            last_report = date.fromisoformat(prev_dates[0]) if prev_dates else p1s
        else:
            index_path = DATA_DIR / 'index.json'
            dates_list = json.loads(index_path.read_text(encoding='utf-8')) if index_path.exists() else []
            prev = [d for d in dates_list if d < body['report_date']]
            last_report = date.fromisoformat(prev[0]) if prev else p1s

        original_date = body.get('original_date')

        # 前回レポートの③予定件数
        prev_scheduled = 0
        try:
            prev_data = _db.load_report(last_report.isoformat()) if USE_DB else None
            if not prev_data:
                prev_file = DATA_DIR / 'reports' / f'{last_report.isoformat()}.json'
                if prev_file.exists():
                    prev_data = json.loads(prev_file.read_text(encoding='utf-8'))
            if prev_data:
                prev_scheduled = prev_data.get('counts', {}).get('scheduled', 0)
                logger.info(f'前回③件数: {prev_scheduled}')
        except Exception:
            pass

        logger.info(f'登録開始 報告日:{report_date}  ①:{p1s}〜{p1e}  ②:{p2s}〜{p2e}  ③:{p3s}〜{p3e}')
        result   = run_collect(report_date, p1s, p1e, p2s, p2e, p3s, p3e, last_report, prev_scheduled)
        date_iso = save_report(result, report_date)

        # 報告日が変わった場合：古いレコードを削除
        if original_date and original_date != date_iso:
            if USE_DB:
                _db.delete_report(original_date)
            else:
                old_file = DATA_DIR / 'reports' / f'{original_date}.json'
                if old_file.exists():
                    old_file.unlink()
            logger.info(f'古いレポート削除: {original_date}')

        return jsonify({'success': True, 'date_iso': date_iso, 'data': result})

    except Exception as e:
        logger.exception('API エラー')
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/delete', methods=['POST'])
def api_delete():
    try:
        date_iso = request.get_json()['date_iso']

        if USE_DB:
            _db.delete_report(date_iso)
        else:
            report_file = DATA_DIR / 'reports' / f'{date_iso}.json'
            if report_file.exists():
                report_file.unlink()
            index_path = DATA_DIR / 'index.json'
            if index_path.exists():
                dates = json.loads(index_path.read_text(encoding='utf-8'))
                if date_iso in dates:
                    dates.remove(date_iso)
                    dates.sort(reverse=True)
                    index_path.write_text(json.dumps(dates, ensure_ascii=False), encoding='utf-8')

        logger.info(f'削除完了: {date_iso}')
        return jsonify({'success': True})

    except Exception as e:
        logger.exception('削除エラー')
        return jsonify({'success': False, 'error': str(e)}), 500


# ── 認証 API ─────────────────────────────────────────────────
@app.route('/api/login', methods=['POST'])
def api_login():
    body = request.get_json()
    username = (body.get('username') or '').strip()
    password = body.get('password') or ''

    user = _db.get_account_by_username(username) if USE_DB else next(
        (a for a in _load_accounts_file() if a['username'] == username), None
    )

    if not user or not check_password_hash(user['password_hash'], password):
        return jsonify({'success': False, 'error': 'アカウントまたはパスワードが正しくありません'}), 401
    if user['status'] != 'active':
        return jsonify({'success': False, 'error': 'このアカウントは停止中です'}), 403

    session['user'] = {'no': user['no'], 'username': user['username'], 'role': user['role']}
    logger.info(f'ログイン: {username}')
    return jsonify({'success': True, 'role': user['role']})

@app.route('/api/logout', methods=['POST'])
def api_logout():
    session.pop('user', None)
    return jsonify({'success': True})

@app.route('/api/me')
@login_required
def api_me():
    return jsonify(session['user'])


# ── アカウント管理 API ────────────────────────────────────────
@app.route('/api/accounts', methods=['GET'])
@admin_required
def api_accounts_list():
    accounts = _db.get_accounts() if USE_DB else _load_accounts_file()
    safe = [{k: v for k, v in a.items() if k != 'password_hash'} for a in accounts]
    # created_at を文字列に変換
    for a in safe:
        if hasattr(a.get('created_at'), 'isoformat'):
            a['created_at'] = a['created_at'].isoformat()
    return jsonify(safe)

@app.route('/api/accounts', methods=['POST'])
@admin_required
def api_accounts_create():
    try:
        body     = request.get_json()
        username = (body.get('username') or '').strip()
        password = body.get('password') or ''
        role     = body.get('role', 'user')
        status   = body.get('status', 'active')

        if not username or not password:
            return jsonify({'success': False, 'error': 'アカウントとパスワードは必須です'}), 400

        if USE_DB:
            if _db.get_account_by_username(username):
                return jsonify({'success': False, 'error': 'このアカウントは既に存在します'}), 400
            new_no = _db.create_account(username, generate_password_hash(password, method='pbkdf2:sha256'), role, status)
        else:
            accounts = _load_accounts_file()
            if any(a['username'] == username for a in accounts):
                return jsonify({'success': False, 'error': 'このアカウントは既に存在します'}), 400
            new_no = max((a['no'] for a in accounts), default=0) + 1
            accounts.append({'no': new_no, 'created_at': date.today().isoformat(), 'username': username,
                              'password_hash': generate_password_hash(password, method='pbkdf2:sha256'),
                              'status': status, 'role': role})
            _save_accounts_file(accounts)
        return jsonify({'success': True, 'no': new_no})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/accounts/<int:no>', methods=['PUT'])
@admin_required
def api_accounts_update(no):
    try:
        body = request.get_json()
        fields = {}
        if body.get('username'):
            if USE_DB:
                existing = _db.get_account_by_username(body['username'])
                if existing and existing['no'] != no:
                    return jsonify({'success': False, 'error': 'このアカウント名は既に使用されています'}), 400
            fields['username'] = body['username'].strip()
        if body.get('password'):
            fields['password_hash'] = generate_password_hash(body['password'], method='pbkdf2:sha256')
        if 'role'   in body: fields['role']   = body['role']
        if 'status' in body: fields['status'] = body['status']

        if USE_DB:
            _db.update_account(no, fields)
        else:
            accounts = _load_accounts_file()
            target = next((a for a in accounts if a['no'] == no), None)
            if not target:
                return jsonify({'success': False, 'error': '対象アカウントが見つかりません'}), 404
            target.update(fields)
            _save_accounts_file(accounts)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/accounts/<int:no>', methods=['DELETE'])
@admin_required
def api_accounts_delete(no):
    try:
        if session['user']['no'] == no:
            return jsonify({'success': False, 'error': '自分自身は削除できません'}), 400
        if USE_DB:
            _db.delete_account_by_no(no)
        else:
            accounts = [a for a in _load_accounts_file() if a['no'] != no]
            _save_accounts_file(accounts)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ── ファイルフォールバック ────────────────────────────────────
def _load_accounts_file():
    f = DATA_DIR / 'accounts.json'
    return json.loads(f.read_text(encoding='utf-8')) if f.exists() else []

def _save_accounts_file(accounts):
    DATA_DIR.mkdir(exist_ok=True)
    (DATA_DIR / 'accounts.json').write_text(json.dumps(accounts, ensure_ascii=False, indent=2), encoding='utf-8')


# ── データ配信（DB優先） ──────────────────────────────────────
@app.route('/data/index.json')
@login_required
def data_index():
    if USE_DB:
        return jsonify(_db.get_index())
    p = DATA_DIR / 'index.json'
    return jsonify(json.loads(p.read_text(encoding='utf-8')) if p.exists() else [])

@app.route('/data/report.json')
@login_required
def data_report_latest():
    if USE_DB:
        data = _db.get_latest_report()
        return jsonify(data) if data else (jsonify({}), 404)
    p = DATA_DIR / 'report.json'
    return jsonify(json.loads(p.read_text(encoding='utf-8'))) if p.exists() else (jsonify({}), 404)

@app.route('/data/reports/<date_iso>.json')
@login_required
def data_report_by_date(date_iso):
    if USE_DB:
        data = _db.load_report(date_iso)
        return jsonify(data) if data else (jsonify({}), 404)
    p = DATA_DIR / 'reports' / f'{date_iso}.json'
    return jsonify(json.loads(p.read_text(encoding='utf-8'))) if p.exists() else (jsonify({}), 404)


# ── 静的ファイル配信 ──────────────────────────────────────────
@app.route('/login')
def login_page():
    if 'user' in session:
        return redirect('/')
    return send_from_directory(BASE_DIR / 'web', 'login.html')

@app.route('/')
@login_required
def index():
    return send_from_directory(BASE_DIR / 'web', 'index.html')

@app.route('/accounts')
@login_required
def accounts_page():
    if session['user'].get('role') != 'admin':
        return redirect('/')
    return send_from_directory(BASE_DIR / 'web', 'accounts.html')

@app.route('/data/<path:path>')
@login_required
def serve_data(path):
    return send_from_directory(DATA_DIR, path)

# ログインページのアセットは認証不要
_PUBLIC = {'login.html', 'login.css', 'style.css'}

@app.route('/<path:path>')
def serve_static(path):
    if path in _PUBLIC or path.startswith('accounts'):
        return send_from_directory(BASE_DIR / 'web', path)
    if 'user' not in session:
        return redirect('/login')
    return send_from_directory(BASE_DIR / 'web', path)


if __name__ == '__main__':
    # DB は起動時に既に init_db() 済み
    logger.info(f'サーバー起動: port={PORT}')
    app.run(host='0.0.0.0', port=PORT, debug=False)
