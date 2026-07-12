/* ─── カテゴリカラー（内訳バーと対応） ──────────── */
const CATEGORY_COLORS = {
  waiting: 'var(--c-wait)',
  cust:    'var(--c-cust)',
  sup:     'var(--c-sup)',
  missed:  'var(--c-miss)',
};

/* ─── 定数 ────────────────────────────────────────── */
const DETAIL_CONFIG = {
  started: {
    title: '開発・対応開始 案件一覧',
    cols: [
      { key: 'cd',              label: 'プロジェクトCD' },
      { key: 'client',          label: '取引先名' },
      { key: 'name',            label: 'PJ名' },
      { key: 'sales',           label: '営業担当者' },
      { key: 'pm',              label: 'PM担当者' },
      { key: 'start_date',      label: '開発開始日' },
      { key: 'delivery_date',   label: '納品予定日 最終' },
      { key: 'completion_date', label: '納品日' },
    ],
  },
  completed: {
    title: '検収完了・対応完了 案件一覧',
    cols: [  // 完了一覧（納品日あり）
      { key: 'cd',              label: 'プロジェクトCD' },
      { key: 'client',          label: '取引先名' },
      { key: 'name',            label: 'PJ名' },
      { key: 'sales',           label: '営業担当者' },
      { key: 'pm',              label: 'PM担当者' },
      { key: 'start_date',      label: '開発開始日' },
      { key: 'delivery_date',   label: '納品予定日 最終' },
      { key: 'completion_date', label: '納品日' },
    ],
    incomplete_cols: [  // 未完了一覧（進捗率バー）
      { key: 'cd',            label: 'プロジェクトCD' },
      { key: 'client',        label: '取引先名' },
      { key: 'name',          label: 'PJ名' },
      { key: 'sales',         label: '営業担当者' },
      { key: 'pm',            label: 'PM担当者' },
      { key: 'start_date',    label: '開発開始日' },
      { key: 'delivery_date', label: '納品予定日 最終' },
      { key: 'progress',      label: '進捗率' },
    ],
  },
  scheduled: {
    title: '今週の検収完了予定 案件一覧',
    cols: [  // 進捗率バー
      { key: 'cd',            label: 'プロジェクトCD' },
      { key: 'client',        label: '取引先名' },
      { key: 'name',          label: 'PJ名' },
      { key: 'sales',         label: '営業担当者' },
      { key: 'pm',            label: 'PM担当者' },
      { key: 'start_date',    label: '開発開始日' },
      { key: 'delivery_date', label: '納品予定日 最終' },
      { key: 'progress',      label: '進捗率' },
    ],
  },
};

/* ─── 状態 ────────────────────────────────────────── */
let currentData       = null;
let _forecastHasData  = false;
let currentDateIso    = null;
let currentDetailType = null;

/* ─── ユーティリティ ──────────────────────────────── */
function setText(id, v) {
  const el = document.getElementById(id);
  if (el) el.textContent = v;
}

function countUp(el, target) {
  if (isNaN(target)) { el.textContent = target; return; }
  const dur = 700, t0 = performance.now();
  (function tick(t) {
    const p = Math.min((t - t0) / dur, 1);
    const e = 1 - Math.pow(1 - p, 3);
    el.textContent = Math.round(target * e);
    if (p < 1) requestAnimationFrame(tick);
  })(t0);
}

function isoToDisplay(iso) {
  // "2026-06-02" → "6月2日"
  const [, m, d] = iso.split('-');
  return `${parseInt(m)}月${parseInt(d)}日`;
}

function isoToYear(iso) {
  return iso.split('-')[0] + '年';
}

/* ─── 日付リスト（サイドバー） ───────────────────── */
async function loadIndex() {
  try {
    const resp = await fetch('data/index.json?t=' + Date.now());
    if (!resp.ok) throw new Error();
    const dates = await resp.json();
    renderSidebar(dates);
    if (dates.length > 0) selectDate(dates[0]);
    else loadLatest();
  } catch {
    loadLatest();
  }
}

function renderSidebar(dates) {
  const list = document.getElementById('date-list');
  if (!dates.length) {
    list.innerHTML = '<li class="sidebar__loading">データなし</li>';
    return;
  }
  const latest = dates[0];
  list.innerHTML = dates.map(iso => `
    <li class="sidebar__item" id="item-${iso}" onclick="selectDate('${iso}')">
      <div class="sidebar__item-info">
        <span class="sidebar__item-date">${isoToDisplay(iso)}</span>
        <span class="sidebar__item-sub">${isoToYear(iso)}</span>
      </div>
      ${iso === latest ? `
      <div class="sb-actions">
        <button class="sb-btn sb-btn--edit"
          onclick="event.stopPropagation();openEditModal('${iso}')"
          title="修正">修正</button>
        <button class="sb-btn sb-btn--update"
          onclick="event.stopPropagation();updateReport('${iso}',this)"
          title="現在の情報で再集計">更新</button>
        <button class="sb-btn sb-btn--delete"
          onclick="event.stopPropagation();deleteReport('${iso}')"
          title="削除">削除</button>
      </div>` : ''}
    </li>
  `).join('');
}

async function selectDate(iso) {
  if (iso === currentDateIso) return;
  currentDateIso = iso;

  // アクティブ切り替え
  document.querySelectorAll('.sidebar__item')
    .forEach(el => el.classList.remove('active'));
  const item = document.getElementById('item-' + iso);
  if (item) {
    item.classList.add('active');
    item.scrollIntoView({ block: 'nearest' });
  }

  closeDetail();
  closeBreakdown();
  try {
    const resp = await fetch('data/reports/' + iso + '.json?t=' + Date.now());
    if (!resp.ok) throw new Error();
    render(await resp.json());
  } catch {
    loadLatest();
  }
}

async function loadLatest() {
  try {
    const resp = await fetch('data/report.json?t=' + Date.now());
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    render(await resp.json());
  } catch (e) {
    setText('report-meta', 'データを取得できませんでした: ' + e.message);
  }
}

/* ─── メイン描画 ──────────────────────────────────── */
function render(d) {
  currentData = d;

  const isMulti     = d.period.start !== d.last_report_date;
  const periodLabel = d.period.start + ' 〜 ' + d.period.end + (isMulti ? '（2週分）' : '');

  setText('report-meta',  '報告日: ' + d.report_date + '　' + periodLabel);
  setText('note-prev',    periodLabel);
  setText('note-prev2',   periodLabel);
  setText('note-this',    d.this_week_period.start + ' 〜 ' + d.this_week_period.end);

  ['num-started', 'num-completed', 'num-scheduled'].forEach((id, i) => {
    const el = document.getElementById(id);
    if (el) countUp(el, [d.counts.started, d.counts.completed, d.counts.scheduled][i]);
  });

  // ② サブ表示：完了件数（先週③内の完了数 / 報告日_朝会がセットされた実件数）
  const bd    = d.last_week_breakdown;
  const subEl = document.getElementById('sub-completed');
  if (subEl) {
    subEl.textContent = bd.total > 0 ? `（${bd.done}/${bd.total}）` : '';
  }

  renderBars(d.last_week_breakdown);
  setText('breakdown-meta',
    '合計 ' + d.last_week_breakdown.total + ' 件　報告日: ' + d.last_report_date);

  renderBreakdownPie(d.last_week_breakdown);
  renderFutureWeeks(d.future_weeks || []);
  setText('footer-updated',
    '最終更新: ' + new Date().toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' }));

  updateKpiMode();
}

/* ─── 横棒グラフ ──────────────────────────────────── */
function renderBars(bd) {
  const max = bd.total || 1;
  [
    { bar: 'bar-done',     cnt: 'cnt-done',     pct: 'pct-done',     n: bd.done },
    { bar: 'bar-waiting',  cnt: 'cnt-waiting',  pct: 'pct-waiting',  n: bd.waiting },
    { bar: 'bar-customer', cnt: 'cnt-customer', pct: 'pct-customer', n: bd.customer_reason },
    { bar: 'bar-sup',      cnt: 'cnt-sup',      pct: 'pct-sup',      n: bd.sup_reason },
    { bar: 'bar-missed',   cnt: 'cnt-missed',   pct: 'pct-missed',   n: bd.missed_update },
  ].forEach(r => {
    const fill = document.getElementById(r.bar);
    const p    = bd.total > 0 ? (r.n / max * 100) : 0;
    if (fill) requestAnimationFrame(() => { fill.style.width = p.toFixed(1) + '%'; });
    setText(r.cnt, r.n + ' 件');
    setText(r.pct, p.toFixed(0) + '%');
  });
}

/* ─── 詳細パネル ──────────────────────────────────── */
function showDetail(type) {
  if (!currentData) return;

  const panel = document.getElementById('detail-panel');

  // 同じカードを再クリックしたら閉じる
  if (currentDetailType === type && panel && !panel.hidden) {
    closeDetail();
    return;
  }

  currentDetailType = type;

  if (type !== 'completed' && breakdownFilter) {
    breakdownFilter = null;
    updateBarHighlight();
  }

  const COLOR_MAP = { started: 'blue', completed: 'teal', scheduled: 'orange' };
  if (panel) {
    panel.className = panel.className.replace(/\bdetail--\w+/g, '').trim();
    panel.classList.add('detail--' + (COLOR_MAP[type] || 'blue'));
  }

  const breakdown = document.getElementById('breakdown-panel');
  if (breakdown) breakdown.hidden = type !== 'completed';

  renderDetailContent(type);

  if (panel) {
    panel.hidden = false;
    updateKpiMode();
  }
}

/* ─── 詳細パネル 描画（フィルター対応） ────────────── */
function renderDetailContent(type) {
  const d   = currentData;
  const cfg = DETAIL_CONFIG[type];
  const bd  = d.last_week_breakdown;
  const SECTION_LABELS = { started: '開始一覧', completed: '完了一覧', scheduled: '予定一覧' };
  const periodMap = {
    started:   d.period.start + ' 〜 ' + d.period.end,
    completed: d.period.start + ' 〜 ' + d.period.end,
    scheduled: d.this_week_period.start + ' 〜 ' + d.this_week_period.end,
  };
  setText('detail-period', periodMap[type]);

  const mainHead  = document.getElementById('detail-main-head');
  const empty     = document.getElementById('detail-empty');
  const table     = document.getElementById('detail-table');
  const tbody     = document.getElementById('detail-tbody');
  const thead     = document.getElementById('detail-thead');
  const incSection = document.getElementById('detail-incomplete');

  if (type === 'completed' && breakdownFilter) {
    // ── フィルターモード ──────────────────────────────
    const fl = FILTER_LABELS[breakdownFilter];

    if (breakdownFilter === 'done') {
      // complete_details が空の場合は details.completed を代替使用
      const records = (bd.complete_details && bd.complete_details.length > 0)
        ? bd.complete_details
        : (d.details && d.details.completed ? d.details.completed : []);
      setText('detail-title', `${cfg.title}（${records.length}件）─ ${fl}`);
      if (mainHead) { mainHead.innerHTML = `完了一覧 <span class="detail__sub-badge">${records.length}件</span>`; mainHead.hidden = false; }
      if (thead) thead.innerHTML = '<tr>' + cfg.cols.map(c => `<th>${c.label}</th>`).join('') + '</tr>';
      if (records.length === 0) { table.hidden = true; empty.hidden = false; }
      else { empty.hidden = true; table.hidden = false; if (tbody) tbody.innerHTML = renderGroupedRows(records, cfg.cols); }
      if (incSection) incSection.hidden = true;

    } else {
      const filtered = (bd.incomplete_details || []).filter(r => r.category === breakdownFilter);
      setText('detail-title', `${cfg.title}（${filtered.length}件）─ ${fl}`);
      if (mainHead) mainHead.hidden = true;
      table.hidden = true; empty.hidden = true;
      if (incSection) {
        const iCols = cfg.incomplete_cols || cfg.cols;
        const badge = document.getElementById('incomplete-count');
        if (badge) badge.textContent = filtered.length + '件';
        const ie = document.getElementById('detail-empty-incomplete');
        const it = document.getElementById('detail-table-incomplete');
        const ith = document.getElementById('detail-thead-incomplete');
        const itb = document.getElementById('detail-tbody-incomplete');
        if (ith) ith.innerHTML = '<tr>' + iCols.map(c => `<th>${c.label}</th>`).join('') + '</tr>';
        if (filtered.length === 0) { if (it) it.hidden = true; if (ie) ie.hidden = false; }
        else { if (ie) ie.hidden = true; if (it) it.hidden = false; if (itb) itb.innerHTML = renderGroupedRows(filtered, iCols); }
        incSection.hidden = false;
      }
    }

  } else {
    // ── 通常モード（フィルターなし） ──────────────────
    const records = (d.details || {})[type] || [];
    setText('detail-title', cfg.title + '（' + records.length + '件）');
    if (mainHead) { mainHead.innerHTML = SECTION_LABELS[type] + ' <span class="detail__sub-badge">' + records.length + '件</span>'; mainHead.hidden = false; }
    if (thead) thead.innerHTML = '<tr>' + cfg.cols.map(c => `<th>${c.label}</th>`).join('') + '</tr>';
    if (records.length === 0) { table.hidden = true; empty.hidden = false; }
    else { empty.hidden = true; table.hidden = false; if (tbody) tbody.innerHTML = renderGroupedRows(records, cfg.cols); }

    if (type === 'completed' && incSection) {
      renderIncompleteTable(bd.incomplete_details || [], cfg.incomplete_cols || cfg.cols);
      incSection.hidden = false;
    } else if (incSection) {
      incSection.hidden = true;
    }
  }
}

/* ─── 進捗バーセル描画 ────────────────────────────── */
function progressCell(value, signal) {
  const raw = parseFloat(String(value || '').replace('%', '').trim()) || 0;
  // FileMaker フィールドは 0〜1 の小数なので 100 倍してパーセントに変換
  const pct = Math.min(Math.max(Math.round(raw * 100), 0), 100);
  // 状態信号（赤/黄/緑）に合わせた薄めの色
  const color = signal === '赤' ? '#f87171'
              : signal === '黄' ? '#fcd34d'
              : signal === '緑' ? '#4ade80'
              : pct >= 100     ? '#4ade80'
              : pct >= 50      ? '#fcd34d'
              :                  '#f87171';
  return `<td>
    <div class="prog-wrap">
      <div class="prog-fill" style="width:${pct}%;background:${color}"></div>
      <span class="prog-label">${value !== '' && value != null ? pct + '%' : '–'}</span>
    </div>
  </td>`;
}

/* ─── グループ別行描画 ────────────────────────────── */
function renderGroupedRows(records, cols) {
  if (!records.length) return '';

  // PM担当者_所属課 でソート（五十音順）
  const sorted = [...records].sort((a, b) =>
    (a.dept || '').localeCompare(b.dept || '', 'ja')
  );

  // グループ化
  const groups = [];
  sorted.forEach(row => {
    const dept = row.dept || '（未設定）';
    if (!groups.length || groups[groups.length - 1].dept !== dept) {
      groups.push({ dept, rows: [] });
    }
    groups[groups.length - 1].rows.push(row);
  });

  const span = cols.length;
  return groups.map(({ dept, rows }) =>
    `<tr class="group-header"><td colspan="${span}">${dept}<span class="group-count">${rows.length}件</span></td></tr>` +
    rows.map(r => renderTableRow(r, cols)).join('')
  ).join('');
}

function renderTableRow(row, cols) {
  return '<tr>' + cols.map(c => {
    const val = row[c.key] || '–';
    if (c.key === 'progress') return progressCell(row[c.key], row.signal);
    if (c.key === 'cd' && row.category) {
      const color = CATEGORY_COLORS[row.category] || 'var(--muted)';
      return `<td><span class="cd-dot" style="background:${color}"></span>${val}</td>`;
    }
    return `<td>${val}</td>`;
  }).join('') + '</tr>';
}

/* ─── 未完了テーブル描画 ──────────────────────────── */
function renderIncompleteTable(records, cols) {
  const empty = document.getElementById('detail-empty-incomplete');
  const table = document.getElementById('detail-table-incomplete');
  const thead = document.getElementById('detail-thead-incomplete');
  const tbody = document.getElementById('detail-tbody-incomplete');
  const badge = document.getElementById('incomplete-count');

  if (badge) badge.textContent = records.length + '件';

  if (records.length === 0) {
    if (table) table.hidden = true;
    if (empty) empty.hidden = false;
    return;
  }
  if (empty) empty.hidden = true;
  if (table) table.hidden = false;

  if (thead) thead.innerHTML =
    '<tr>' + cols.map(c => `<th>${c.label}</th>`).join('') + '</tr>';

  if (tbody) tbody.innerHTML = renderGroupedRows(records, cols);
}

function closeDetail() {
  const panel = document.getElementById('detail-panel');
  if (panel) panel.hidden = true;
  const breakdown = document.getElementById('breakdown-panel');
  if (breakdown) breakdown.hidden = true;
  currentDetailType = null;
  if (breakdownFilter) { breakdownFilter = null; updateBarHighlight(); }
  updateKpiMode();
}

function closeBreakdown() {
  const breakdown = document.getElementById('breakdown-panel');
  if (breakdown) breakdown.hidden = true;

  if (breakdownFilter) {
    breakdownFilter = null;
    updateBarHighlight();
    if (currentDetailType === 'completed') renderDetailContent('completed');
  }

  updateKpiMode();
}

function updateKpiMode() {
  const kpiRow = document.querySelector('.kpi-row');
  if (!kpiRow) return;
  const panel         = document.getElementById('detail-panel');
  const detailVisible = panel && !panel.hidden;

  const chartSection    = document.getElementById('chart-section');
  const forecastSection = document.getElementById('forecast-section');

  // カードは常に縮小サイズ固定
  kpiRow.classList.remove('kpi-row--expanded');
  kpiRow.querySelectorAll('.kpi').forEach(k => { k.style.minHeight = ''; });

  if (detailVisible) {
    // 一覧表示中：グラフ・予定セクションは非表示
    if (chartSection)    chartSection.hidden    = true;
    if (forecastSection) forecastSection.hidden = true;
  } else {
    // 一覧非表示：グラフ・予定セクションを表示
    if (chartSection) {
      const wasHidden = chartSection.hidden;
      chartSection.hidden = false;
      if (wasHidden) loadChartData();
    }
    if (forecastSection) forecastSection.hidden = !_forecastHasData;
  }
}

// ウィンドウリサイズ時はキャッシュをリセット
window.addEventListener('resize', () => { updateKpiMode(); });

function reload() {
  closeDetail();
  if (currentDateIso) selectDate(currentDateIso);
  else loadLatest();
}

/* ─── モーダルのモード管理 ────────────────────────── */
let modalMode    = 'new';   // 'new' | 'edit'
let editDateIso  = null;

/* ─── 内訳フィルター ──────────────────────────────── */
let breakdownFilter = null; // null | 'done' | 'waiting' | 'cust' | 'sup' | 'missed'
const FILTER_LABELS = { done: '完了', waiting: '検収待', cust: 'お客様都合', sup: 'sup都合', missed: '更新漏れ' };
const FILTER_ROWS   = ['done', 'waiting', 'cust', 'sup', 'missed'];

function updateBarHighlight() {
  FILTER_ROWS.forEach(k => {
    const el = document.getElementById('brow-' + k);
    if (el) el.classList.toggle('bar-row--active', breakdownFilter === k);
  });
}

function applyBreakdownFilter(category) {
  if (!currentData) return;

  if (breakdownFilter === category) {
    // 同じカテゴリを再クリック → フィルタ解除して全件表示
    breakdownFilter = null;
    updateBarHighlight();
    const panel = document.getElementById('detail-panel');
    if (panel && !panel.hidden && currentDetailType === 'completed') {
      renderDetailContent('completed');
    }
    return;
  }

  breakdownFilter = category;
  updateBarHighlight();

  // 案件一覧パネルを開く（②モード）
  const panel = document.getElementById('detail-panel');
  currentDetailType = 'completed';
  panel.className = panel.className.replace(/\bdetail--\w+/g, '').trim();
  panel.classList.add('detail--teal');

  renderDetailContent('completed');
  panel.hidden = false;
  updateKpiMode();
  panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

/* ─── API ベース URL ──────────────────────────────── */
// 常に同一オリジン（Flask がすべてを提供）
function apiUrl(path) {
  return path;
}

/* ─── 更新（現在の期間で再集計） ─────────────────── */
async function updateReport(dateIso, btn) {
  const orig = btn.textContent;
  btn.textContent = '…';
  btn.disabled = true;

  try {
    const d = await fetch(`data/reports/${dateIso}.json?t=${Date.now()}`).then(r => r.json());

    const payload = {
      report_date:   jpToISO(d.report_date),
      original_date: dateIso,
      period1_start: jpToISO(d.period.start),
      period1_end:   jpToISO(d.period.end),
      period2_start: jpToISO(d.period.start),
      period2_end:   jpToISO(d.period.end),
      period3_start: jpToISO(d.this_week_period.start),
      period3_end:   jpToISO(d.this_week_period.end),
    };

    const result = await fetch('/api/collect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).then(r => r.json());

    if (!result.success) throw new Error(result.error);

    const newDates = await fetch('data/index.json?t=' + Date.now()).then(r => r.json());
    renderSidebar(newDates);
    currentDateIso = null;  // 同一日付でも強制再取得
    selectDate(result.date_iso);

  } catch (e) {
    alert('更新に失敗しました: ' + e.message);
    btn.textContent = orig;
    btn.disabled = false;
  }
}

/* ─── 削除 ────────────────────────────────────────── */
async function deleteReport(dateIso) {
  if (!confirm(`${isoToYear(dateIso)} ${isoToDisplay(dateIso)} を削除しますか？\nこの操作は取り消せません。`)) return;

  try {
    const result = await fetch('/api/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ date_iso: dateIso }),
    }).then(r => r.json());

    if (!result.success) throw new Error(result.error);

    const newDates = await fetch('data/index.json?t=' + Date.now()).then(r => r.json());
    renderSidebar(newDates);

    if (currentDateIso === dateIso) {
      closeDetail();
      const bp = document.getElementById('breakdown-panel');
      if (bp) bp.hidden = true;
      currentDateIso = null;
      currentData    = null;
      if (newDates.length > 0) selectDate(newDates[0]);
    }

  } catch (e) {
    alert('削除に失敗しました: ' + e.message);
  }
}

/* ─── 新規登録モーダル ────────────────────────────── */
function toISO(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

/* FM日付 "2026/5/25" → ISO "2026-05-25" */
function jpToISO(s) {
  if (!s) return '';
  const p = s.split('/');
  return `${p[0]}-${p[1].padStart(2,'0')}-${p[2].padStart(2,'0')}`;
}

/* モーダルのタイトル・ボタンをセット */
function setModalMode(mode) {
  modalMode = mode;
  document.querySelector('.modal__title').textContent =
    mode === 'edit' ? 'データ修正' : '新規データ登録';
  document.getElementById('btn-register').textContent =
    mode === 'edit' ? '反映' : '登録';
}

/* 修正ボタン → 既存データ読み込みでモーダルを開く */
async function openEditModal(dateIso) {
  editDateIso = dateIso;
  try {
    // データファイルはページと同じサーバー（静的）から取得
    const resp = await fetch(`data/reports/${dateIso}.json?t=${Date.now()}`);
    if (!resp.ok) throw new Error('データを取得できませんでした');
    const d = await resp.json();

    document.getElementById('f-report-date').value   = jpToISO(d.report_date);
    document.getElementById('f-period1-start').value = jpToISO(d.period.start);
    document.getElementById('f-period1-end').value   = jpToISO(d.period.end);
    document.getElementById('f-period2-start').value = jpToISO(d.period.start);
    document.getElementById('f-period2-end').value   = jpToISO(d.period.end);
    document.getElementById('f-period3-start').value = jpToISO(d.this_week_period.start);
    document.getElementById('f-period3-end').value   = jpToISO(d.this_week_period.end);

    document.getElementById('register-error').hidden = true;
    setModalMode('edit');
    document.getElementById('register-modal').hidden = false;

  } catch (e) {
    alert('エラー: ' + e.message);
  }
}

function openRegisterModal() {
  editDateIso = null;
  setModalMode('new');
  // 直近の月曜を基準に日付を自動入力
  const today      = new Date();
  const dow        = today.getDay();
  const diffMon    = dow === 0 ? -6 : 1 - dow;
  const thisMonday = new Date(today); thisMonday.setDate(today.getDate() + diffMon);
  const lastMonday = new Date(thisMonday); lastMonday.setDate(thisMonday.getDate() - 7);
  const lastSunday = new Date(thisMonday); lastSunday.setDate(thisMonday.getDate() - 1);
  const nextSunday = new Date(thisMonday); nextSunday.setDate(thisMonday.getDate() + 6);

  document.getElementById('f-report-date').value   = toISO(thisMonday);
  document.getElementById('f-period1-start').value = toISO(lastMonday);
  document.getElementById('f-period1-end').value   = toISO(lastSunday);
  document.getElementById('f-period2-start').value = toISO(lastMonday);
  document.getElementById('f-period2-end').value   = toISO(lastSunday);
  document.getElementById('f-period3-start').value = toISO(thisMonday);
  document.getElementById('f-period3-end').value   = toISO(nextSunday);

  const err = document.getElementById('register-error');
  err.hidden = true;

  document.getElementById('register-modal').hidden = false;
}

function closeRegisterModal() {
  document.getElementById('register-modal').hidden = true;
  editDateIso = null;
}

// モーダル外クリックで閉じる
document.addEventListener('click', function(e) {
  const overlay = document.getElementById('register-modal');
  if (e.target === overlay) closeRegisterModal();
});

async function submitRegister() {
  const btn = document.getElementById('btn-register');
  const err = document.getElementById('register-error');
  err.hidden = true;

  const payload = {
    report_date:   document.getElementById('f-report-date').value,
    original_date: modalMode === 'edit' ? editDateIso : null,  // 修正元の日付
    period1_start: document.getElementById('f-period1-start').value,
    period1_end:   document.getElementById('f-period1-end').value,
    period2_start: document.getElementById('f-period2-start').value,
    period2_end:   document.getElementById('f-period2-end').value,
    period3_start: document.getElementById('f-period3-start').value,
    period3_end:   document.getElementById('f-period3-end').value,
  };

  // 必須チェック（original_date は null でも可）
  const dateFields = ['report_date','period1_start','period1_end','period2_start','period2_end','period3_start','period3_end'];
  if (dateFields.some(k => !payload[k])) {
    err.textContent = 'すべての日付を入力してください。';
    err.hidden = false;
    return;
  }

  btn.disabled    = true;
  btn.textContent = '登録中...';

  try {
    const resp = await fetch(apiUrl('/api/collect'), {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(payload),
    });

    const result = await resp.json();
    if (!result.success) throw new Error(result.error || 'サーバーエラー');

    closeRegisterModal();

    // サイドバーを更新して新しい日付を選択
    const newDates = await fetch('data/index.json?t=' + Date.now())
      .then(r => r.json());
    renderSidebar(newDates);
    selectDate(result.date_iso);

  } catch (e) {
    err.textContent = '登録に失敗しました: ' + e.message;
    err.hidden = false;
  } finally {
    btn.disabled    = false;
    btn.textContent = modalMode === 'edit' ? '反映' : '登録';
  }
}

/* ─── 内訳 ドーナツ円グラフ ──────────────────────── */
function renderBreakdownPie(bd) {
  const canvas = document.getElementById('breakdown-pie');
  if (!canvas) return;
  if (_breakdownPieChart) { _breakdownPieChart.destroy(); _breakdownPieChart = null; }

  const values = [bd.done, bd.waiting, bd.customer_reason, bd.sup_reason, bd.missed_update];
  if (values.every(v => v === 0)) return;

  // セグメント上にパーセントを描画するカスタムプラグイン
  const pctLabelPlugin = {
    id: 'pctLabel',
    afterDatasetsDraw(chart) {
      const { ctx, data } = chart;
      const total = data.datasets[0].data.reduce((a, b) => a + b, 0);
      if (!total) return;
      chart.getDatasetMeta(0).data.forEach((arc, i) => {
        const value = data.datasets[0].data[i];
        const pct = Math.round(value / total * 100);
        if (pct < 5) return; // 小さすぎるセグメントは省略
        const pos = arc.tooltipPosition();
        ctx.save();
        ctx.font = 'bold 10px sans-serif';
        ctx.fillStyle = '#fff';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(pct + '%', pos.x, pos.y);
        ctx.restore();
      });
    },
  };

  _breakdownPieChart = new Chart(canvas, {
    type: 'doughnut',
    data: {
      labels: ['完了', '検収待', 'お客様都合', 'sup都合', '更新漏れ'],
      datasets: [{
        data: values,
        backgroundColor: ['#22c55e', '#eab308', '#0ea5e9', '#a855f7', '#ef4444'],
        borderWidth: 2,
        borderColor: '#ffffff',
        hoverBorderWidth: 3,
      }],
    },
    plugins: [pctLabelPlugin],
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: '58%',
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => ` ${ctx.label}：${ctx.raw}件 (${Math.round(ctx.raw / bd.total * 100)}%)`,
          },
        },
      },
    },
  });
}

/* ─── 今後4週の検収完了予定 ──────────────────────── */
function jpDateFromSlash(s) {
  if (!s) return '';
  const parts = s.split('/');
  return parts.length === 3 ? `${parseInt(parts[1])}月${parseInt(parts[2])}日` : s;
}

function renderFutureWeeks(weeks) {
  const section   = document.getElementById('forecast-section');
  const container = document.getElementById('forecast-cards');
  if (!section || !container) return;

  if (!weeks || weeks.length === 0) {
    _forecastHasData = false;
    section.hidden   = true;
    return;
  }

  _forecastHasData    = true;
  container.innerHTML = weeks.map((w, i) => `
    <div class="forecast-card">
      <span class="forecast-card__badge">+${i + 1}週</span>
      <div class="forecast-card__period">${jpDateFromSlash(w.period.start)} 〜 ${jpDateFromSlash(w.period.end)}</div>
      <div class="forecast-card__num-row">
        <span class="forecast-card__num">${w.count}</span>
        <span class="forecast-card__unit">件</span>
      </div>
    </div>
  `).join('');
}

/* ─── 折れ線グラフ ────────────────────────────────── */
let _chartInstance     = null;
let _breakdownPieChart = null;

async function loadChartData() {
  try {
    const allDates = await fetch('data/index.json?t=' + Date.now()).then(r => r.json());
    const recent   = allDates.slice(0, 7).reverse();   // 最大7件・古い順

    const reports = await Promise.all(
      recent.map(iso =>
        fetch(`data/reports/${iso}.json`).then(r => r.json()).catch(() => null)
      )
    );

    const labels    = recent.map(iso => isoToDisplay(iso));
    const started   = reports.map(r => r ? r.counts.started   : null);
    const completed = reports.map(r => r ? r.counts.completed : null);
    const scheduled = reports.map(r => r ? r.counts.scheduled : null);

    renderChart(labels, started, completed, scheduled);
  } catch (e) {
    console.error('グラフ読み込みエラー:', e);
  }
}

function renderChart(labels, started, completed, scheduled) {
  const canvas = document.getElementById('trend-chart');
  if (!canvas) return;

  if (_chartInstance) { _chartInstance.destroy(); _chartInstance = null; }

  _chartInstance = new Chart(canvas, {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: '① 開発・対応開始',
          data: started,
          borderColor:     '#3b82f6',
          backgroundColor: 'rgba(59,130,246,0.08)',
          tension: 0.3, pointRadius: 5, pointHoverRadius: 7,
          fill: true,
        },
        {
          label: '② 検収完了・対応完了',
          data: completed,
          borderColor:     '#0d9488',
          backgroundColor: 'rgba(13,148,136,0.08)',
          tension: 0.3, pointRadius: 5, pointHoverRadius: 7,
          fill: true,
        },
        {
          label: '③ 今週予定',
          data: scheduled,
          borderColor:     '#f97316',
          backgroundColor: 'rgba(249,115,22,0.08)',
          tension: 0.3, pointRadius: 5, pointHoverRadius: 7,
          fill: true,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { position: 'top', labels: { font: { size: 11 } } },
      },
      scales: {
        y: {
          beginAtZero: true,
          ticks: { stepSize: 1, precision: 0 },
          grid: { color: 'rgba(0,0,0,0.05)' },
        },
        x: {
          grid: { display: false },
          ticks: { font: { size: 11 } },
        },
      },
    },
  });
}

/* ─── サイドバー開閉 ──────────────────────────────── */
function toggleSidebar() {
  document.querySelector('.sidebar').classList.toggle('sidebar--collapsed');
}

/* ─── ログイン状態の確認・topbar 設定 ───────────────── */
async function initUser() {
  const me = await fetch('/api/me').then(r => r.json()).catch(() => null);
  if (!me) { location.href = '/login'; return; }

  const userEl    = document.getElementById('topbar-user');
  const logoutBtn = document.getElementById('logout-btn');
  const acLink    = document.getElementById('accounts-link');

  if (userEl)    userEl.textContent = me.username;
  if (logoutBtn) logoutBtn.hidden = false;
  if (acLink && me.role === 'admin') acLink.hidden = false;
}

async function doLogout() {
  await fetch('/api/logout', { method: 'POST' });
  location.href = '/login';
}

/* ─── 起動 ────────────────────────────────────────── */
initUser();
loadIndex();
