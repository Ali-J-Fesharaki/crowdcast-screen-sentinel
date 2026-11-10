/**
 * CrowdCast Screen Sentinel Frontend Controller
 */

let state = {
  windows: [],
  focusedWindow: null,
  config: {},
  luma: {},
  agentRunning: false,
  agentPid: null,
  filter: 'all',
  searchQuery: '',
};

let pollTimer = null;

// DOM Elements
const elVmName = document.getElementById('vm-name-display');
const elAgentStatus = document.getElementById('agent-status-badge');
const elAgentStatusText = document.getElementById('agent-status-text');
const elBlackoutBanner = document.getElementById('blackout-banner');
const elBlackoutBannerDesc = document.getElementById('blackout-banner-desc');
const elBtnBannerFix = document.getElementById('btn-banner-fix');

const elStatTotal = document.getElementById('stat-total-windows');
const elStatMonitored = document.getElementById('stat-monitored-windows');
const elStatBlackout = document.getElementById('stat-blackout-count');
const elStatLuma = document.getElementById('stat-luma-mean');
const elStatLumaStatus = document.getElementById('stat-luma-status');
const elCardBlackout = document.getElementById('card-blackout-count');

const elCountAll = document.getElementById('count-all');
const elCountBlackout = document.getElementById('count-blackout');
const elCountMonitored = document.getElementById('count-monitored');

const elTableBody = document.getElementById('windows-table-body');
const elSearchInput = document.getElementById('window-search');
const elPreviewImage = document.getElementById('preview-image');
const elPreviewTag = document.getElementById('preview-luma-tag');
const elPreviewSource = document.getElementById('preview-source');
const elPreviewStats = document.getElementById('preview-stats');
const elPreviewVerdict = document.getElementById('preview-verdict');

// Modals & Buttons
const elModalSettings = document.getElementById('settings-modal');
const elBtnOpenSettings = document.getElementById('btn-open-settings');
const elBtnSaveSettings = document.getElementById('btn-save-settings');
const elBtnWhitelistAll = document.getElementById('btn-whitelist-all');
const elBtnRestartAgent = document.getElementById('btn-restart-agent');
const elBtnRefresh = document.getElementById('btn-refresh');
const elBtnSampleNow = document.getElementById('btn-sample-now');

// Safeguards Elements
const elRuleCaptureAll = document.getElementById('rule-capture-all');
const elRuleBlankUntracked = document.getElementById('rule-blank-untracked');
const elRuleIdleTimeout = document.getElementById('rule-idle-timeout');

// Toast Notification
function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.innerText = message;
  container.appendChild(toast);
  setTimeout(() => {
    toast.remove();
  }, 4000);
}

// Fetch Full System State
async function fetchState() {
  try {
    const res = await fetch('/api/status');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    state.windows = data.windows || [];
    state.focusedWindow = data.focused_window || null;
    state.config = data.config || {};
    state.luma = data.luma || {};
    state.agentRunning = data.agent_running;
    state.agentPid = data.agent_pid;

    renderUI(data);
  } catch (err) {
    console.error('Error fetching sentinel state:', err);
    elAgentStatusText.innerText = 'قطع ارتباط با سرور';
    elAgentStatus.className = 'badge badge-status stopped';
  }
}

// Render Complete UI
function renderUI(data) {
  // 1. Navigation Badges
  elVmName.innerText = data.vm_name || 'crowd-vm';
  if (data.agent_running) {
    elAgentStatus.className = 'badge badge-status running';
    elAgentStatusText.innerText = `ریکوردر فعال (PID: ${data.agent_pid || '?'})`;
  } else {
    elAgentStatus.className = 'badge badge-status stopped';
    elAgentStatusText.innerText = 'ریکوردر متوقف است';
  }

  // 2. Blackout Banner Check
  const activeBlackoutWindow = state.windows.find(w => w.blackout_status === 'ACTIVE_BLACKOUT');
  if (activeBlackoutWindow) {
    elBlackoutBanner.classList.remove('hidden');
    elBlackoutBannerDesc.innerHTML = `پنجره فعال <strong>${activeBlackoutWindow.display_name}</strong> (${activeBlackoutWindow.wm_class}) به دلیل عدم حضور در لیست نظارت، با صفحه ۱۰۰٪ سیاه ضبط می‌شود!`;
    elBtnBannerFix.onclick = () => fixBlackout(activeBlackoutWindow.wm_class);
  } else {
    elBlackoutBanner.classList.add('hidden');
  }

  // 3. Stats Grid
  const total = state.windows.length;
  const monitored = state.windows.filter(w => w.is_monitored).length;
  const blackouts = state.windows.filter(w => w.blackout_status !== 'SAFE').length;

  elStatTotal.innerText = total;
  elStatMonitored.innerText = monitored;
  elStatBlackout.innerText = blackouts;
  elCountAll.innerText = total;
  elCountMonitored.innerText = monitored;
  elCountBlackout.innerText = blackouts;

  if (blackouts > 0) {
    elCardBlackout.classList.add('has-alert');
  } else {
    elCardBlackout.classList.remove('has-alert');
  }

  // Luma stats
  if (data.luma && data.luma.success) {
    const mean = data.luma.mean;
    elStatLuma.innerText = mean.toFixed(1);
    if (data.luma.is_black) {
      elStatLumaStatus.innerHTML = '<span style="color:#ef4444">🚨 استریم سیاه (Mean < 1.0)</span>';
    } else {
      elStatLumaStatus.innerHTML = '<span style="color:#10b981">🟢 ویدیو در حال ضبط فعال</span>';
    }

    elPreviewTag.innerText = `Mean: ${mean.toFixed(1)} | Min: ${data.luma.min} | Max: ${data.luma.max}`;
    elPreviewSource.innerText = (data.luma.video_source || '').split('/').pop() || '-';
    elPreviewStats.innerText = `${data.luma.min} / ${data.luma.max} / ${mean.toFixed(1)}`;

    if (data.luma.is_black) {
      elPreviewVerdict.className = 'badge badge-status stopped';
      elPreviewVerdict.innerText = 'کاملاً سیاه (Blackout)';
    } else {
      elPreviewVerdict.className = 'badge badge-status running';
      elPreviewVerdict.innerText = 'طبیعی و شفاف (Valid)';
    }
  } else {
    elStatLuma.innerText = '0.0';
    elStatLumaStatus.innerText = 'در انتظار فریم ضبط...';
  }

  // 4. Render Safeguards Check
  renderSafeguards(data.config);

  // 4.1 Render Tehran Upload Schedule
  if (data.upload_schedule && data.upload_schedule.tehran_time) {
    const sched = data.upload_schedule;
    const timeOnly = sched.tehran_time.split(' ')[1] || '';
    const elTehranTime = document.getElementById('stat-tehran-time');
    const elTehranStatus = document.getElementById('stat-tehran-status');
    const elCardSched = document.getElementById('card-tehran-schedule');
    
    if (elTehranTime) elTehranTime.innerText = `${timeOnly} (تهران)`;
    if (elTehranStatus) {
      if (sched.is_window_open) {
        elTehranStatus.innerHTML = `<span style="color:#10b981; font-weight:700;">🟢 ${sched.status_fa}</span><br><small>${sched.next_event_fa}</small>`;
        if (elCardSched) elCardSched.style.borderColor = 'rgba(16, 185, 129, 0.5)';
      } else {
        elTehranStatus.innerHTML = `<span style="color:#f59e0b; font-weight:700;">⏸️ ${sched.status_fa}</span><br><small>${sched.next_event_fa}</small>`;
        if (elCardSched) elCardSched.style.borderColor = 'rgba(245, 158, 11, 0.4)';
      }
    }
  }

  // 5. Render Windows Table
  renderWindowsTable();
}

// Render Safeguard List
function renderSafeguards(cfg) {
  if (!cfg) return;

  // Rule 1: capture_all
  if (cfg.capture_all) {
    elRuleCaptureAll.querySelector('.icon').innerText = '❌';
    elRuleCaptureAll.querySelector('strong').innerText = 'خطای capture_all فعال است!';
    elRuleCaptureAll.querySelector('strong').style.color = '#ef4444';
  } else {
    elRuleCaptureAll.querySelector('.icon').innerText = '✅';
    elRuleCaptureAll.querySelector('strong').innerText = 'capture_all غیرفعال است (ایمن)';
    elRuleCaptureAll.querySelector('strong').style.color = '#10b981';
  }

  // Rule 2: blank_video_on_untracked_app
  if (cfg.blank_video_on_untracked_app) {
    elRuleBlankUntracked.querySelector('.icon').innerText = '⚠️';
    elRuleBlankUntracked.querySelector('strong').innerText = 'blank_on_untracked فعال است (ریسک)';
    elRuleBlankUntracked.querySelector('strong').style.color = '#f59e0b';
  } else {
    elRuleBlankUntracked.querySelector('.icon').innerText = '✅';
    elRuleBlankUntracked.querySelector('strong').innerText = 'حفظ فریم فعال است (ایمن)';
    elRuleBlankUntracked.querySelector('strong').style.color = '#10b981';
  }

  // Rule 3: idle_timeout_secs
  if ((cfg.idle_timeout_secs || 0) >= 600 || cfg.idle_timeout_secs === 0) {
    elRuleIdleTimeout.querySelector('.icon').innerText = '✅';
    elRuleIdleTimeout.querySelector('strong').innerText = `تایم‌اوت مناسب (${cfg.idle_timeout_secs || 0}s)`;
    elRuleIdleTimeout.querySelector('strong').style.color = '#10b981';
  } else {
    elRuleIdleTimeout.querySelector('.icon').innerText = '⚠️';
    elRuleIdleTimeout.querySelector('strong').innerText = `تایم‌اوت کوتاه (${cfg.idle_timeout_secs}s)`;
    elRuleIdleTimeout.querySelector('strong').style.color = '#f59e0b';
  }
}

// Render Windows Table with Filtering
function renderWindowsTable() {
  const query = state.searchQuery.toLowerCase();
  let list = state.windows;

  // Filter chips
  if (state.filter === 'blackout') {
    list = list.filter(w => w.blackout_status !== 'SAFE');
  } else if (state.filter === 'monitored') {
    list = list.filter(w => w.is_monitored);
  }

  // Search filter
  if (query) {
    list = list.filter(w =>
      (w.title || '').toLowerCase().includes(query) ||
      (w.wm_class || '').toLowerCase().includes(query) ||
      (w.display_name || '').toLowerCase().includes(query)
    );
  }

  if (list.length === 0) {
    elTableBody.innerHTML = `
      <tr>
        <td colspan="5" style="text-align:center; padding: 30px; color: var(--text-muted);">
          هیچ پنجره‌ای مطابق با این فیلتر یافت نشد.
        </td>
      </tr>
    `;
    return;
  }

  elTableBody.innerHTML = list.map(w => {
    let rowClass = '';
    if (w.blackout_status === 'ACTIVE_BLACKOUT') rowClass = 'row-blackout-active';
    else if (w.blackout_status === 'BLACKOUT_RISK') rowClass = 'row-blackout-risk';

    // Status Badge
    let statusBadge = '';
    if (w.blackout_status === 'ACTIVE_BLACKOUT') {
      statusBadge = `
        <div class="eval-status">
          <span class="eval-badge status-danger">🔴 ضبط کاملاً سیاه</span>
          <span class="eval-reason">${w.blackout_reason_fa}</span>
        </div>
      `;
    } else if (w.blackout_status === 'BLACKOUT_RISK') {
      statusBadge = `
        <div class="eval-status">
          <span class="eval-badge status-warning">🟡 خطر ضبط سیاه</span>
          <span class="eval-reason">${w.blackout_reason_fa}</span>
        </div>
      `;
    } else {
      statusBadge = `
        <div class="eval-status">
          <span class="eval-badge status-safe">🟢 در حال نظارت و ایمن</span>
          <span class="eval-reason">${w.blackout_reason_fa}</span>
        </div>
      `;
    }

    // Focus indicator
    const focusHtml = w.is_focused
      ? `<span class="focus-indicator active">🎯 در فوکوس کنونی</span>`
      : `<span class="focus-indicator inactive">پس‌زمینه</span>`;

    // Action buttons
    let actionButtons = '';
    if (w.can_one_click_fix) {
      actionButtons += `
        <button class="btn btn-xs btn-fix" onclick="fixBlackout('${w.wm_class}')" title="رفع مشکل سیاه و افزودن فوری به نظارت">
          ⚡ حل مشکل صفحه سیاه
        </button>
      `;
    }

    if (!w.is_monitored) {
      actionButtons += `
        <button class="btn btn-xs btn-secondary" onclick="addToMonitoring('${w.wm_class}')" title="افزودن به لیست مجاز ریکوردر">
          ➕ نظارت
        </button>
      `;
    } else {
      actionButtons += `
        <button class="btn btn-xs btn-remove" onclick="removeFromMonitoring('${w.wm_class}')" title="حذف از لیست مجاز">
          ➖ حذف
        </button>
      `;
    }

    actionButtons += `
      <button class="btn btn-xs btn-secondary" onclick="focusWindow('${w.wm_class}')" title="آوردن پنجره به صفحه اول">
        🎯 فوکوس
      </button>
    `;

    return `
      <tr class="${rowClass}">
        <td>
          <div class="app-info">
            <div class="app-icon-wrap">${getAppIcon(w.icon)}</div>
            <div>
              <div class="app-title-text" title="${escapeHtml(w.title)}">${escapeHtml(w.title || w.display_name)}</div>
              <div class="app-id-sub">برنامه: ${w.display_name} | PID: ${w.pid} | ID: ${w.window_id}</div>
            </div>
          </div>
        </td>
        <td>
          <code class="code-badge">${escapeHtml(w.wm_class)}</code>
        </td>
        <td>${focusHtml}</td>
        <td>${statusBadge}</td>
        <td>
          <div class="actions-cell">
            ${actionButtons}
          </div>
        </td>
      </tr>
    `;
  }).join('');
}

// Icon helper
function getAppIcon(type) {
  const map = {
    'code': '💻',
    'terminal': '📟',
    'globe': '🌐',
    'folder': '📁',
    'bot': '🤖',
    'book-open': '📖',
    'file-text': '📝',
  };
  return map[type] || '🪟';
}

function escapeHtml(text) {
  if (!text) return '';
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// API Actions
window.fixBlackout = async function(wmClass) {
  showToast(`در حال اعمال رفع مشکل صفحه سیاه برای ${wmClass}...`, 'info');
  try {
    const res = await fetch('/api/windows/fix', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ wm_class: wmClass })
    });
    const data = await res.json();
    if (data.success) {
      showToast(data.message_fa || 'مشکل صفحه سیاه برطرف شد!', 'success');
      await fetchState();
      refreshPreview();
    } else {
      showToast(data.error || 'خطا در حل مشکل صفحه سیاه', 'error');
    }
  } catch (err) {
    showToast(`خطای شبکه: ${err.message}`, 'error');
  }
};

window.addToMonitoring = async function(wmClass) {
  try {
    const res = await fetch('/api/windows/add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ wm_class: wmClass })
    });
    const data = await res.json();
    if (data.success) {
      showToast(data.message_fa || 'به نظارت اضافه شد', 'success');
      fetchState();
    } else {
      showToast(data.error || 'خطا در افزودن', 'error');
    }
  } catch (err) {
    showToast(err.message, 'error');
  }
};

window.removeFromMonitoring = async function(wmClass) {
  try {
    const res = await fetch('/api/windows/remove', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ wm_class: wmClass })
    });
    const data = await res.json();
    if (data.success) {
      showToast(data.message_fa || 'از نظارت حذف شد', 'info');
      fetchState();
    } else {
      showToast(data.error || 'خطا در حذف', 'error');
    }
  } catch (err) {
    showToast(err.message, 'error');
  }
};

window.focusWindow = async function(wmClass) {
  try {
    const res = await fetch('/api/windows/focus', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ wm_class: wmClass })
    });
    const data = await res.json();
    if (data.success) {
      showToast(`پنجره ${wmClass} به صفحه اول آورده شد`, 'info');
      setTimeout(fetchState, 1000);
    }
  } catch (err) {
    showToast(err.message, 'error');
  }
};

// Whitelist All Open
elBtnWhitelistAll.onclick = async () => {
  showToast('در حال ثبت تمام پنجره‌های باز در لیست مجاز...', 'info');
  try {
    const res = await fetch('/api/windows/whitelist-all', { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      showToast(data.message_fa || 'تمام پنجره‌ها اضافه شدند', 'success');
      await fetchState();
      refreshPreview();
    } else {
      showToast(data.error || 'خطا در انجام عملیات', 'error');
    }
  } catch (err) {
    showToast(err.message, 'error');
  }
};

// Restart Recorder
elBtnRestartAgent.onclick = async () => {
  showToast('در حال راه‌اندازی مجدد سرویس ضبط...', 'info');
  try {
    const res = await fetch('/api/agent/restart', { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      showToast('ریکوردر با موفقیت ریستارت شد', 'success');
      setTimeout(fetchState, 2000);
    } else {
      showToast('خطا در ریستارت ریکوردر', 'error');
    }
  } catch (err) {
    showToast(err.message, 'error');
  }
};

// Refresh preview image
function refreshPreview() {
  elPreviewImage.src = `/api/preview.png?t=${Date.now()}`;
}

elBtnSampleNow.onclick = async () => {
  showToast('در حال نمونه‌برداری فریم زنده...', 'info');
  try {
    await fetch('/api/luma');
    refreshPreview();
    fetchState();
  } catch (err) {
    showToast(err.message, 'error');
  }
};

// Search & Filter event listeners
elSearchInput.oninput = (e) => {
  state.searchQuery = e.target.value;
  renderWindowsTable();
};

document.querySelectorAll('.filter-chip').forEach(chip => {
  chip.onclick = () => {
    document.querySelectorAll('.filter-chip').forEach(c => c.classList.remove('active'));
    chip.classList.add('active');
    state.filter = chip.getAttribute('data-filter');
    renderWindowsTable();
  };
});

// Settings Modal
elBtnOpenSettings.onclick = () => {
  const cfg = state.config || {};
  document.getElementById('cfg-blank-untracked').checked = Boolean(cfg.blank_video_on_untracked_app);
  document.getElementById('cfg-capture-all').checked = Boolean(cfg.capture_all);
  document.getElementById('cfg-idle-timeout').value = cfg.idle_timeout_secs || 600;
  elModalSettings.classList.remove('hidden');
};

document.querySelectorAll('.modal-close, .modal-overlay').forEach(el => {
  el.onclick = () => elModalSettings.classList.add('hidden');
});

elBtnSaveSettings.onclick = async () => {
  const settings = {
    blank_video_on_untracked_app: document.getElementById('cfg-blank-untracked').checked,
    capture_all: document.getElementById('cfg-capture-all').checked,
    idle_timeout_secs: parseInt(document.getElementById('cfg-idle-timeout').value, 10) || 600
  };

  showToast('در حال ذخیره و اعمال تنظیمات در ماشین...', 'info');
  try {
    const res = await fetch('/api/settings/update', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(settings)
    });
    const data = await res.json();
    if (data.success) {
      showToast('تنظیمات با موفقیت در ماشین اعمال شد', 'success');
      elModalSettings.classList.add('hidden');
      await fetchState();
    } else {
      showToast(data.error || 'خطا در ذخیره تنظیمات', 'error');
    }
  } catch (err) {
    showToast(err.message, 'error');
  }
};

elBtnRefresh.onclick = () => {
  fetchState();
  refreshPreview();
  showToast('داده‌ها بروز شدند', 'info');
};

// Initial state fetch and polling loop (every 3.5s)
fetchState();
pollTimer = setInterval(fetchState, 3500);
