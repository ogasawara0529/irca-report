#!/usr/bin/env python3
import base64
import json
import logging
import os
import requests
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote

BASE_DIR = Path(__file__).parent

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler(BASE_DIR / 'collect.log', encoding='utf-8'),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)

# config.env を読み込む（存在する場合）
_env_path = BASE_DIR / 'config.env'
if _env_path.exists():
    for _line in _env_path.read_text(encoding='utf-8').splitlines():
        _line = _line.strip()
        if _line and not _line.startswith('#') and '=' in _line:
            _k, _, _v = _line.partition('=')
            os.environ.setdefault(_k.strip(), _v.strip())

FM_HOST     = os.environ['FM_HOST']
FM_DATABASE = os.environ['FM_DATABASE']
FM_LAYOUT   = os.environ['FM_LAYOUT']
FM_USER     = os.environ['FM_USER']
FM_PASSWORD = os.environ['FM_PASSWORD']
FM_VERIFY_SSL         = os.environ.get('FM_VERIFY_SSL', 'true').lower() != 'false'
CUSTOMER_KEYWORDS     = [k.strip() for k in os.environ.get('CUSTOMER_REASON_KEYWORDS', 'お客様都合').split(',')]
FM_FIELD_PROJECT_NAME  = os.environ.get('FM_FIELD_PROJECT_NAME', 'プロジェクト名')
FM_DATE_FORMAT         = os.environ.get('FM_DATE_FORMAT', 'YYYYMD')
FM_LAYOUT_BREAKDOWN    = os.environ.get('FM_LAYOUT_BREAKDOWN', FM_LAYOUT)

BASE_URL                 = f'https://{FM_HOST}/fmi/data/v1/databases/{FM_DATABASE}'
LAYOUT_ENCODED           = quote(FM_LAYOUT)
LAYOUT_BREAKDOWN_ENCODED = quote(FM_LAYOUT_BREAKDOWN)
STATE_FILE     = BASE_DIR / 'state.json'
DATA_DIR       = BASE_DIR / 'data'
PROJECT_TYPE   = 'プロジェクト型'


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


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding='utf-8'))
    return {}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')


class FileMakerClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.verify = FM_VERIFY_SSL
        self.token = None

    def __enter__(self):
        self.login()
        return self

    def __exit__(self, *_):
        self.logout()

    def login(self):
        creds = base64.b64encode(f'{FM_USER}:{FM_PASSWORD}'.encode()).decode()
        resp = self.session.post(
            f'{BASE_URL}/sessions',
            headers={'Authorization': f'Basic {creds}', 'Content-Type': 'application/json'},
            json={},
            timeout=30,
        )
        resp.raise_for_status()
        self.token = resp.json()['response']['token']
        logger.info('FileMaker ログイン成功')

    def logout(self):
        if not self.token:
            return
        try:
            self.session.delete(
                f'{BASE_URL}/sessions/{self.token}',
                headers={'Authorization': f'Bearer {self.token}'},
                timeout=10,
            )
        except Exception:
            pass
        logger.info('FileMaker ログアウト')
        self.token = None

    def _find(self, query: list, limit: int = 100000, portal: list = None) -> dict:
        body = {'query': query, 'limit': str(limit)}
        if portal:
            body['portal'] = portal
        resp = self.session.post(
            f'{BASE_URL}/layouts/{LAYOUT_ENCODED}/_find',
            headers={'Authorization': f'Bearer {self.token}', 'Content-Type': 'application/json'},
            json=body,
            timeout=60,
        )
        data = resp.json()
        code = str(data.get('messages', [{}])[0].get('code', '0'))

        # 検索結果 0 件
        if code == '401':
            return {'response': {'dataInfo': {'foundCount': 0}, 'data': []}}

        # ポータルがレイアウトに存在しない → ポータルなしで再試行
        if code == '110' and portal:
            logger.warning(f'ポータルがレイアウトに存在しません。ポータルなしで再試行します。')
            return self._find(query, limit, portal=None)

        resp.raise_for_status()
        return data

    def count(self, query: list) -> int:
        return self._find(query)['response']['dataInfo']['foundCount']

    def records_breakdown(self, query: list, portal: list = None) -> list:
        """内訳専用レイアウト（プロジェクト詳細）で検索"""
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
            return []
        return data['response']['data']

    def records(self, query: list, portal: list = None) -> list:
        return self._find(query, portal=portal)['response']['data']

    def update(self, record_id: str, field_data: dict):
        resp = self.session.patch(
            f'{BASE_URL}/layouts/{LAYOUT_ENCODED}/records/{record_id}',
            headers={'Authorization': f'Bearer {self.token}', 'Content-Type': 'application/json'},
            json={'fieldData': field_data},
            timeout=30,
        )
        resp.raise_for_status()


def calc_dates(today: date, state: dict) -> dict:
    last_str = state.get('last_report_date')
    if last_str:
        # 前回の報告日から今週直前（日曜）まで（スキップ週も自動対応）
        last_report = date.fromisoformat(last_str.replace('/', '-'))
        prev_start  = last_report
        prev_end    = today - timedelta(days=1)
    else:
        # 初回実行：先週月曜〜日曜
        prev_start  = today - timedelta(days=7)
        prev_end    = today - timedelta(days=1)
        last_report = prev_start

    return {
        'report_date': today,
        'prev_start':  prev_start,
        'prev_end':    prev_end,
        'this_start':  today,
        'this_end':    today + timedelta(days=6),
        'last_report': last_report,
    }


def _parse_fm_date(s):
    """FileMaker の日付文字列を Python date に変換（MDY/YYYYMD 両対応）"""
    if not s:
        return None
    try:
        parts = str(s).replace('-', '/').split('/')
        if len(parts) == 3:
            if FM_DATE_FORMAT == 'MDY':
                return date(int(parts[2]), int(parts[0]), int(parts[1]))
            else:
                return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except Exception:
        return None


def _detail_started(rec: dict) -> dict:
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


def _detail(rec: dict, date_field: str) -> dict:
    fd = rec['fieldData']
    return {
        'name':   fd.get(FM_FIELD_PROJECT_NAME, ''),
        'date':   fd.get(date_field, ''),
        'status': fd.get('status', ''),
    }


def collect(client: FileMakerClient, d: dict) -> dict:
    today_fm     = fm_date(d['report_date'])       # FileMaker 更新・クエリ用
    today_str    = display_date(d['report_date'])  # JSON 保存・表示用
    prev_range   = f"{fm_date(d['prev_start'])}...{fm_date(d['prev_end'])}"
    this_range   = f"{fm_date(d['this_start'])}...{fm_date(d['this_end'])}"
    last_rep_fm  = fm_date(d['last_report'])       # FileMaker クエリ用
    last_rep_str = display_date(d['last_report'])  # JSON 保存・表示用
    prev_end_str = display_date(d['prev_end'])

    # ① 開発・対応開始案件数（詳細も取得）
    recs_1  = client.records([{'プロジェクト区分': PROJECT_TYPE, '開発開始日': prev_range}])
    count_1 = len(recs_1)
    logger.info(f'① 開始: {count_1} 件')

    # ② 検収完了・対応完了・追加受注案件数（詳細も取得）
    recs_2  = client.records([{'プロジェクト区分': PROJECT_TYPE, '納品日': prev_range}])
    count_2 = len(recs_2)
    logger.info(f'② 完了: {count_2} 件')

    # ③ 検収完了予定件数（今週納品予定）→ 報告日_朝会 を本日で更新
    recs_3  = client.records([{'プロジェクト区分': PROJECT_TYPE, '納品予定日_最終': this_range}])
    count_3 = len(recs_3)
    logger.info(f'③ 今週予定: {count_3} 件 → 報告日_朝会 を {today_fm} に更新')
    for rec in recs_3:
        client.update(rec['recordId'], {'報告日_朝会': today_fm})

    # 先週③の内訳（内訳専用レイアウトで取得）
    PORTAL_NAME = 'プロジェクト_納品日変更履歴'
    base        = {'プロジェクト区分': PROJECT_TYPE, '報告日_朝会': last_rep_fm}
    all_bd_recs = client.records_breakdown([base], portal=[PORTAL_NAME])
    total_bd    = len(all_bd_recs)

    count_done   = 0
    count_wait   = 0
    count_cust   = 0
    count_sup    = 0
    count_missed = 0
    incomplete_details = []

    for rec in all_bd_recs:
        fd           = rec['fieldData']
        delivery_day = _parse_fm_date(fd.get('納品日', ''))

        if delivery_day and d['prev_start'] <= delivery_day <= d['prev_end']:
            count_done += 1
        elif fd.get('status', '') == '納品済・検収待':
            count_wait += 1
            detail = _detail_started(rec)
            detail['category'] = 'waiting'
            incomplete_details.append(detail)
        else:
            final_day = _parse_fm_date(fd.get('納品予定日_最終', ''))
            if final_day and final_day > d['prev_end']:
                portal_rows = rec.get('portalData', {}).get(PORTAL_NAME, [])
                reason = ''
                if portal_rows:
                    reason = portal_rows[-1].get(f'{PORTAL_NAME}::納品日変更理由', '') or ''
                if any(kw in reason for kw in CUSTOMER_KEYWORDS):
                    count_cust += 1
                    cat = 'cust'
                else:
                    count_sup += 1
                    cat = 'sup'
            else:
                count_missed += 1
                cat = 'missed'
            detail = _detail_started(rec)
            detail['category'] = cat
            incomplete_details.append(detail)

    logger.info(
        f'先週内訳 - 完了:{count_done} 検収待:{count_wait} '
        f'お客様:{count_cust} sup:{count_sup} 更新漏れ:{count_missed}'
    )

    return {
        'report_date':      today_str,
        'period':           {'start': display_date(d['prev_start']), 'end': prev_end_str},
        'this_week_period': {'start': display_date(d['this_start']), 'end': display_date(d['this_end'])},
        'last_report_date': last_rep_str,
        'counts': {
            'started':   count_1,
            'completed': count_2,
            'scheduled': count_3,
        },
        'last_week_breakdown': {
            'total':              total_bd,
            'prev_scheduled':     d.get('prev_scheduled', 0),
            'done':               count_done,
            'waiting':            count_wait,
            'customer_reason':    count_cust,
            'sup_reason':         count_sup,
            'missed_update':      count_missed,
            'incomplete_details': incomplete_details,
        },
        'details': {
            'started':   [_detail_started(r) for r in recs_1],
            'completed': [_detail_started(r) for r in recs_2],
            'scheduled': [_detail_started(r) for r in recs_3],
        },
    }


def main():
    today = date.today()
    state = load_state()
    d     = calc_dates(today, state)

    logger.info(
        f'報告日: {d["report_date"]}  '
        f'先週: {d["prev_start"]} 〜 {d["prev_end"]}  '
        f'今週: {d["this_start"]} 〜 {d["this_end"]}'
    )

    DATA_DIR.mkdir(exist_ok=True)

    # 前回レポートの③予定件数を取得
    prev_scheduled = 0
    prev_file = DATA_DIR / 'reports' / f'{d["last_report"].isoformat()}.json'
    if prev_file.exists():
        try:
            prev_data = json.loads(prev_file.read_text(encoding='utf-8'))
            prev_scheduled = prev_data.get('counts', {}).get('scheduled', 0)
        except Exception:
            pass
    d['prev_scheduled'] = prev_scheduled

    with FileMakerClient() as client:
        result = collect(client, d)

    # 最新レポートとして保存
    out = DATA_DIR / 'report.json'
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')

    # 履歴として日付ごとに保存
    reports_dir = DATA_DIR / 'reports'
    reports_dir.mkdir(exist_ok=True)
    date_iso = today.isoformat()
    (reports_dir / f'{date_iso}.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8'
    )

    # 日付インデックスを更新
    index_path = DATA_DIR / 'index.json'
    dates_list = json.loads(index_path.read_text(encoding='utf-8')) if index_path.exists() else []
    if date_iso not in dates_list:
        dates_list.append(date_iso)
        dates_list.sort(reverse=True)
        index_path.write_text(json.dumps(dates_list, ensure_ascii=False), encoding='utf-8')

    logger.info(f'出力: {out}  履歴: {reports_dir / date_iso}.json')

    save_state({'last_report_date': today.isoformat()})
    logger.info('完了')


if __name__ == '__main__':
    main()
