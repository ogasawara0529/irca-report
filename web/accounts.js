let currentUser = null;

/* ─── 起動 ──────────────────────────────────────────── */
async function init() {
  const me = await fetch('/api/me').then(r => r.json()).catch(() => null);
  if (!me) { location.href = '/login'; return; }
  currentUser = me;
  document.getElementById('current-user').textContent = me.username;
  loadAccounts();
}

/* ─── 一覧取得 ──────────────────────────────────────── */
async function loadAccounts() {
  const accounts = await fetch('/api/accounts').then(r => r.json());
  const tbody = document.getElementById('ac-tbody');
  tbody.innerHTML = accounts.map(a => `
    <tr>
      <td>${a.no}</td>
      <td>${a.created_at}</td>
      <td style="font-weight:600">${a.username}</td>
      <td><span class="status-badge ${a.status === 'active' ? 'status-active' : 'status-inactive'}">
        ${a.status === 'active' ? '利用中' : '停止中'}
      </span></td>
      <td><span class="role-badge ${a.role === 'admin' ? 'role-admin' : 'role-user'}">
        ${a.role === 'admin' ? '管理者' : 'ユーザー'}
      </span></td>
      <td>
        <div class="ac-actions">
          <button class="ac-btn ac-btn--edit" onclick="openEditModal(${a.no})">変更</button>
          <button class="ac-btn ${a.status === 'active' ? 'ac-btn--stop' : 'ac-btn--toggle'}"
            onclick="toggleStatus(${a.no}, '${a.status}')">
            ${a.status === 'active' ? '利用停止' : '利用開始'}
          </button>
          <button class="ac-btn ac-btn--del" onclick="deleteAccount(${a.no}, '${a.username}')"
            ${a.no === currentUser.no ? 'disabled title="自分自身は削除できません"' : ''}>削除</button>
        </div>
      </td>
    </tr>
  `).join('');
}

/* ─── モーダル ──────────────────────────────────────── */
function openModal() {
  document.getElementById('modal-title').textContent = '新規登録';
  document.getElementById('modal-save-btn').textContent = '登録';
  document.getElementById('edit-no').value = '';
  document.getElementById('f-username').value = '';
  document.getElementById('f-password').value = '';
  document.getElementById('f-role').value = 'user';
  document.getElementById('f-status').value = 'active';
  document.getElementById('pw-hint').hidden = true;
  document.getElementById('modal-error').hidden = true;
  document.getElementById('ac-modal').hidden = false;
}

function openEditModal(no) {
  fetch('/api/accounts').then(r => r.json()).then(accounts => {
    const a = accounts.find(x => x.no === no);
    if (!a) return;
    document.getElementById('modal-title').textContent = 'アカウント変更';
    document.getElementById('modal-save-btn').textContent = '更新';
    document.getElementById('edit-no').value = no;
    document.getElementById('f-username').value = a.username;
    document.getElementById('f-password').value = '';
    document.getElementById('f-role').value = a.role;
    document.getElementById('f-status').value = a.status;
    document.getElementById('pw-hint').hidden = false;
    document.getElementById('modal-error').hidden = true;
    document.getElementById('ac-modal').hidden = false;
  });
}

function closeModal() {
  document.getElementById('ac-modal').hidden = true;
}

/* ─── 保存（新規・更新） ────────────────────────────── */
async function saveAccount() {
  const btn      = document.getElementById('modal-save-btn');
  const err      = document.getElementById('modal-error');
  const no       = document.getElementById('edit-no').value;
  const username = document.getElementById('f-username').value.trim();
  const password = document.getElementById('f-password').value;
  const role     = document.getElementById('f-role').value;
  const status   = document.getElementById('f-status').value;

  err.hidden = true;
  btn.disabled = true;

  try {
    let resp;
    if (no) {
      // 更新
      resp = await fetch(`/api/accounts/${no}`, {
        method:  'PUT',
        headers: {'Content-Type': 'application/json'},
        body:    JSON.stringify({ username, password: password || undefined, role, status }),
      });
    } else {
      // 新規
      resp = await fetch('/api/accounts', {
        method:  'POST',
        headers: {'Content-Type': 'application/json'},
        body:    JSON.stringify({ username, password, role, status }),
      });
    }
    const data = await resp.json();
    if (data.success) {
      closeModal();
      loadAccounts();
    } else {
      err.textContent = data.error;
      err.hidden = false;
    }
  } catch (e) {
    err.textContent = '通信エラーが発生しました';
    err.hidden = false;
  } finally {
    btn.disabled = false;
  }
}

/* ─── ステータス切り替え ─────────────────────────────── */
async function toggleStatus(no, currentStatus) {
  const newStatus = currentStatus === 'active' ? 'inactive' : 'active';
  const resp = await fetch(`/api/accounts/${no}`, {
    method:  'PUT',
    headers: {'Content-Type': 'application/json'},
    body:    JSON.stringify({ status: newStatus }),
  });
  const data = await resp.json();
  if (data.success) loadAccounts();
  else alert('変更に失敗しました: ' + data.error);
}

/* ─── 削除 ──────────────────────────────────────────── */
async function deleteAccount(no, username) {
  if (!confirm(`「${username}」を削除しますか？\nこの操作は取り消せません。`)) return;
  const resp = await fetch(`/api/accounts/${no}`, { method: 'DELETE' });
  const data = await resp.json();
  if (data.success) loadAccounts();
  else alert('削除に失敗しました: ' + data.error);
}

/* ─── ログアウト ─────────────────────────────────────── */
async function doLogout() {
  await fetch('/api/logout', { method: 'POST' });
  location.href = '/login';
}

init();
