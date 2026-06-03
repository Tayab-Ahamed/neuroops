/* ============================================================
   NEUROOPS LIVE OPERATIONS ENGINE — app.js
   Connects to detector (:8001), agent (:8002), remediator (:8003)
   Falls back to premium DEMO MODE when services are offline
   Implements high-fidelity 3D tilt, canvas particle physics,
   and animated multi-agent reasoning chains
   ============================================================ */

'use strict';

// ── Config ───────────────────────────────────────────────────
const API = {
  detector:   'http://localhost:8001',
  agent:      'http://localhost:8002',
  remediator: 'http://localhost:8003',
};

const REFRESH_MS   = 5000;
const DEMO_MODE_KEY = 'neuroops-demo';

// ── State ────────────────────────────────────────────────────
let state = {
  demoMode: false,
  currentPage: 'dashboard',
  currentIncident: null,
  services: { detector: 'loading', agent: 'loading', remediator: 'loading' },
  alerts: [],
  incidents: [],
  mttr: null,
  cost: null,
  sla: null,
  refreshInterval: null,
  trendData: { p50: [], p95: [] },
  demoTick: 0,
};

// ── Demo Data ─────────────────────────────────────────────────
const DEMO_INCIDENTS = [
  {
    incident_id: 'inc-pod-del-001',
    service: 'backend',
    hypothesis: 'Backend pod (backend-6d8f7b9c4-xkz2p) was deleted by LitmusChaos pod-delete experiment. IsolationForest anomaly score -0.891 confirms abnormal behaviour. Kubernetes reported CrashLoopBackOff state within 14s.',
    confidence: 0.91,
    recommended_action: 'restart_pod',
    requires_human_approval: false,
    tokens_used: 4850,
    mttr_seconds: 65.0,
    created_at: Date.now() / 1000 - 3600,
    trace: [
      { step: 1, agent: 'Detective', action: 'Queried Prometheus metrics — p99 latency spike to 892ms', findings: { anomaly_score: -0.891, metric: 'http_request_duration_p99' } },
      { step: 2, agent: 'Topologist', action: 'Traced Jaeger spans — bottleneck identified at backend pod', findings: { bottleneck: 'backend-6d8f7b9c4-xkz2p', trace_id: 'abc123' } },
      { step: 3, agent: 'Historian', action: 'Scanned GitHub deployments — no recent deploys found', findings: { suspect_commit: null, recent_deploys: 0 } },
      { step: 4, agent: 'Log Analyser', action: 'Scraped container logs — OOMKilled found in events', findings: { error_logs: ['OOMKilled', 'CrashLoopBackOff'] } },
      { step: 5, agent: 'Supervisor', action: 'Synthesised findings — high confidence pod failure', findings: { likely_origin: 'pod-delete chaos experiment' } },
    ]
  },
  {
    incident_id: 'inc-cpu-hog-002',
    service: 'frontend',
    hypothesis: 'Frontend service CPU utilisation reached 94% of limit. IsolationForest anomaly score -0.763 with Ridge Regression forecasting continued saturation for next 4 minutes. Scaling to 3 replicas recommended.',
    confidence: 0.82,
    recommended_action: 'scale_replicas',
    requires_human_approval: false,
    tokens_used: 5340,
    mttr_seconds: 96.4,
    created_at: Date.now() / 1000 - 7200,
    trace: [
      { step: 1, agent: 'Detective', action: 'Queried CPU metrics — 94% utilisation detected on frontend', findings: { anomaly_score: -0.763, metric: 'cpu_usage_percent' } },
      { step: 2, agent: 'Topologist', action: 'Analysed trace spans — high latency on frontend → backend calls', findings: { bottleneck: 'frontend', trace_id: 'def456' } },
      { step: 3, agent: 'Historian', action: 'Checked GitHub — cpu-hog LitmusChaos experiment found', findings: { suspect_commit: 'chaos/cpu-hog.yaml applied', recent_deploys: 1 } },
      { step: 4, agent: 'Log Analyser', action: 'Reviewed logs — no application errors, resource exhaustion confirmed', findings: { error_logs: [] } },
      { step: 5, agent: 'Supervisor', action: 'Recommended scale-out — autonomous execution approved', findings: { likely_origin: 'cpu-hog chaos experiment' } },
    ]
  },
  {
    incident_id: 'inc-mem-hog-003',
    service: 'backend',
    hypothesis: 'Backend memory utilisation at 87% of limit with OOMKill pressure detected. Confidence at 0.74 — below autonomous threshold. Human operator approval required before scaling to prevent accidental cascading.',
    confidence: 0.74,
    recommended_action: 'scale_replicas',
    requires_human_approval: true,
    tokens_used: 5920,
    mttr_seconds: 123.7,
    created_at: Date.now() / 1000 - 14400,
    trace: [
      { step: 1, agent: 'Detective', action: 'Memory usage 87% — OOMKill pressure anomaly detected', findings: { anomaly_score: -0.712, metric: 'memory_usage_percent' } },
      { step: 2, agent: 'Topologist', action: 'Traced downstream impact to database-stub queries', findings: { bottleneck: 'backend', trace_id: 'ghi789' } },
      { step: 3, agent: 'Historian', action: 'No recent deployments found — chaos injection confirmed', findings: { suspect_commit: null, recent_deploys: 0 } },
      { step: 4, agent: 'Log Analyser', action: 'OOMKilled events in pod logs confirmed', findings: { error_logs: ['OOMKilled', 'memory limit exceeded'] } },
      { step: 5, agent: 'Supervisor', action: 'P2 gate triggered — human approval required for scale action', findings: { likely_origin: 'memory-hog chaos experiment' } },
    ]
  },
  {
    incident_id: 'inc-net-lat-004',
    service: 'database-stub',
    hypothesis: 'Database-stub P99 latency reached 502ms (baseline: 38ms). Network latency injection of 500ms detected via Jaeger trace correlation. Restart of database-stub pod recommended pending operator approval.',
    confidence: 0.68,
    recommended_action: 'restart_pod',
    requires_human_approval: true,
    tokens_used: 6840,
    mttr_seconds: 163.3,
    created_at: Date.now() / 1000 - 28800,
    trace: [
      { step: 1, agent: 'Detective', action: 'P99 latency 502ms detected on database-stub — anomaly score -0.634', findings: { anomaly_score: -0.634, metric: 'http_request_duration_p99' } },
      { step: 2, agent: 'Topologist', action: 'Jaeger traces show 500ms artificial delay on db-stub connections', findings: { bottleneck: 'database-stub', trace_id: 'jkl012' } },
      { step: 3, agent: 'Historian', action: 'network-latency chaos experiment detected in cluster events', findings: { suspect_commit: 'chaos/network-latency.yaml applied' } },
      { step: 4, agent: 'Log Analyser', action: 'No application errors — pure network injection confirmed', findings: { error_logs: [] } },
      { step: 5, agent: 'Supervisor', action: 'Recommend restart — human approval required (confidence 0.68)', findings: { likely_origin: 'network-latency chaos experiment' } },
    ]
  },
];

const DEMO_ALERTS = [
  { service: 'backend', severity: 'P1', anomaly_score: -0.891, timestamp: Date.now() / 1000 - 120, correlation_id: 'corr-001' },
  { service: 'frontend', severity: 'P2', anomaly_score: -0.763, timestamp: Date.now() / 1000 - 480, correlation_id: 'corr-002' },
  { service: 'database-stub', severity: 'P2', anomaly_score: -0.634, timestamp: Date.now() / 1000 - 900, correlation_id: 'corr-003' },
];

const DEMO_MTTR = {
  total_incidents: 4,
  autonomous_count: 2,
  avg_mttr_seconds: 112.1,
  p50_mttr_seconds: 96.4,
  p95_mttr_seconds: 163.3,
  p99_mttr_seconds: 216.4,
  autonomous_resolution_rate: 0.5,
  per_service: {
    backend: { avg_mttr: 94.3, count: 2 },
    frontend: { avg_mttr: 96.4, count: 1 },
    'database-stub': { avg_mttr: 163.3, count: 1 },
  }
};

const DEMO_COST = {
  total_incidents: 4,
  total_tokens: 22950,
  total_cost_usd: 0.3442,
  avg_tokens_per_incident: 5737,
  avg_cost_per_incident: 0.0861,
  manual_sre_cost_usd: 281.3,
  savings_usd: 280.96,
};

const DEMO_SLA = {
  total_resolved: 4,
  breached: 0,
  breach_rate: 0.0,
  autonomous_resolution_rate: 0.5,
  target_met: true,
};

// ── Interactive Background Canvas ───────────────────────────
function initCanvas() {
  const canvas = document.getElementById('bg-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  let w, h, particles = [];

  function resize() {
    w = canvas.width = window.innerWidth;
    h = canvas.height = window.innerHeight;
  }

  function createParticles() {
    particles = [];
    const count = Math.floor((w * h) / 16000);
    for (let i = 0; i < count; i++) {
      particles.push({
        x: Math.random() * w,
        y: Math.random() * h,
        vx: (Math.random() - 0.5) * 0.12,
        vy: (Math.random() - 0.5) * 0.12,
        r: Math.random() * 1.5 + 0.4,
        alpha: Math.random() * 0.4 + 0.15,
        color: Math.random() > 0.55 ? 'violet' : 'cyan', // Dual color nodes
      });
    }
  }

  function drawGrid() {
    const gap = 80;
    ctx.strokeStyle = 'rgba(124, 58, 237, 0.02)';
    ctx.lineWidth = 0.5;
    for (let x = 0; x < w; x += gap) {
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
    }
    for (let y = 0; y < h; y += gap) {
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
    }
  }

  function draw() {
    ctx.clearRect(0, 0, w, h);
    drawGrid();

    particles.forEach(p => {
      p.x += p.vx;
      p.y += p.vy;
      if (p.x < 0) p.x = w;
      if (p.x > w) p.x = 0;
      if (p.y < 0) p.y = h;
      if (p.y > h) p.y = 0;

      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fillStyle = p.color === 'violet' ? `rgba(124, 58, 237, ${p.alpha})` : `rgba(0, 212, 255, ${p.alpha})`;
      ctx.fill();
    });

    // Draw interactive web links
    for (let i = 0; i < particles.length; i++) {
      for (let j = i + 1; j < particles.length; j++) {
        const dx = particles[i].x - particles[j].x;
        const dy = particles[i].y - particles[j].y;
        const dist = Math.sqrt(dx*dx + dy*dy);
        if (dist < 110) {
          ctx.beginPath();
          const strength = (1 - dist/110) * 0.08;
          ctx.strokeStyle = particles[i].color === 'violet' 
            ? `rgba(124, 58, 237, ${strength})` 
            : `rgba(0, 212, 255, ${strength})`;
          ctx.lineWidth = 0.5;
          ctx.moveTo(particles[i].x, particles[i].y);
          ctx.lineTo(particles[j].x, particles[j].y);
          ctx.stroke();
        }
      }
    }

    requestAnimationFrame(draw);
  }

  window.addEventListener('resize', () => { resize(); createParticles(); });
  resize();
  createParticles();
  draw();
}

// ── Real-time 3D Card Hover Tilt ───────────────────────────
function initCardTilt() {
  const cards = document.querySelectorAll('.stat-card, .health-card, .panel-card, .mttr-ring-card, .cost-card, .trend-card');
  
  cards.forEach(card => {
    card.addEventListener('mousemove', e => {
      const rect = card.getBoundingClientRect();
      const x = e.clientX - rect.left - rect.width / 2;
      const y = e.clientY - rect.top - rect.height / 2;
      
      // Calculate smooth tilt perspective
      card.style.transform = `perspective(1000px) rotateX(${-y / 15}deg) rotateY(${x / 15}deg) scale3d(1.018, 1.018, 1.018)`;
      card.style.transition = 'none'; // Instant response
    });
    
    card.addEventListener('mouseleave', () => {
      card.style.transform = 'perspective(1000px) rotateX(0deg) rotateY(0deg) scale3d(1, 1, 1)';
      card.style.transition = 'transform 0.4s cubic-bezier(0.16, 1, 0.3, 1)';
    });
  });
}

// ── Clock ─────────────────────────────────────────────────────
function startClock() {
  const el = document.getElementById('clock');
  const tick = () => {
    if (el) el.textContent = new Date().toLocaleTimeString('en-GB', { hour12: false });
    setTimeout(tick, 1000);
  };
  tick();
}

// ── Navigation ────────────────────────────────────────────────
function navigate(page, el) {
  if (el) {
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    el.classList.add('active');
  }

  ['dashboard','incidents','analytics','postmortems'].forEach(p => {
    const el = document.getElementById(`page-${p}`);
    if (el) el.classList.toggle('hidden', p !== page);
  });

  state.currentPage = page;

  const titles = {
    dashboard: 'Live <span>Dashboard</span>',
    incidents: 'Incident <span>Log</span>',
    analytics: 'DORA <span>Analytics</span>',
    postmortems: 'Post-Mortem <span>Reports</span>',
  };
  const titleEl = document.getElementById('page-title');
  if (titleEl) titleEl.innerHTML = titles[page] || page;

  if (page === 'incidents') renderAllIncidents();
  if (page === 'analytics') renderAnalyticsPage();
}

// ── API Fetch ─────────────────────────────────────────────────
async function apiFetch(url, timeout = 4000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const res = await fetch(url, { signal: controller.signal });
    clearTimeout(timer);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (e) {
    clearTimeout(timer);
    throw e;
  }
}

// ── Demo Mode Control ─────────────────────────────────────────
function toggleDemoMode() {
  state.demoMode = !state.demoMode;
  const btn = document.getElementById('btn-demo-mode');
  if (btn) {
    btn.textContent = state.demoMode ? '⬡ Live Mode' : '⚡ Demo Mode';
    btn.classList.toggle('btn-primary', !state.demoMode);
    btn.classList.toggle('btn-ghost', state.demoMode);
  }
  if (state.demoMode) {
    loadDemoData();
    showToast('⚡ Demo mode active — synthetic incident dataset simulated', 'info');
  } else {
    showToast('Connecting to live Microservices...', 'info');
    refresh();
  }
}

function loadDemoData() {
  state.alerts = DEMO_ALERTS;
  state.incidents = DEMO_INCIDENTS;
  state.mttr = DEMO_MTTR;
  state.cost = DEMO_COST;
  state.sla = DEMO_SLA;

  // Set services online
  ['detector','agent','remediator'].forEach(svc => {
    state.services[svc] = 'ok';
    setServiceStatus(svc, 'ok');
  });

  // Demo stats
  setEl('det-model', '✓ Active');
  setEl('det-alerts', '3 active');
  setEl('det-groups', '2 groups');
  setEl('det-score', '-0.891');

  setEl('agent-incidents', '4 stored');
  setEl('agent-tokens', '22,950');
  setEl('agent-p50', '96.4s');
  setEl('agent-sla', '✓ MET');

  setEl('rem-actions', '6 total');
  setEl('rem-k8s', '✓ Yes');
  setEl('rem-flap', '0');
  setEl('rem-last', 'restart_pod');

  updateUI();

  // Synthetic trend line
  state.trendData.p50 = [82, 70, 96, 60, 92, 110, 96, 60, 84, 96];
  state.trendData.p95 = [125, 115, 163, 90, 155, 185, 163, 90, 125, 163];
  drawTrendChart();
}

// ── Refresh Engine ────────────────────────────────────────────
async function refresh() {
  if (state.demoMode) return;

  const dot = document.getElementById('refresh-dot');
  if (dot) dot.classList.add('spinning');

  const label = document.getElementById('refresh-label');

  await Promise.allSettled([
    fetchDetectorHealth(),
    fetchAgentHealth(),
    fetchRemediatorHealth(),
    fetchAlerts(),
    fetchIncidents(),
    fetchMTTR(),
    fetchCost(),
    fetchSLA(),
  ]);

  updateUI();

  const now = new Date().toLocaleTimeString('en-GB', { hour12: false });
  if (label) label.textContent = `Synced: ${now}`;
  setEl('health-updated', `Last check: ${now}`);

  if (dot) dot.classList.remove('spinning');
}

function triggerManualRefresh() {
  if (state.demoMode) { loadDemoData(); return; }
  refresh();
}

// ── Service API Invocations ────────────────────────────────────
async function fetchDetectorHealth() {
  try {
    const data = await apiFetch(`${API.detector}/health`);
    state.services.detector = 'ok';
    setServiceStatus('detector', 'ok');
    setEl('det-model', data.model_loaded ? '✓ Active' : '✗ Degrading');
    setEl('det-alerts', `${(data.alerts_active || 0)} active`);
    setEl('det-groups', `${data.correlated_groups || 0} correlated`);
    setEl('det-score', data.latest_anomaly_score !== undefined ? data.latest_anomaly_score.toFixed(3) : '—');
  } catch (e) {
    state.services.detector = 'down';
    setServiceStatus('detector', 'down');
  }
}

async function fetchAgentHealth() {
  try {
    const data = await apiFetch(`${API.agent}/health`);
    state.services.agent = 'ok';
    setServiceStatus('agent', 'ok');
    setEl('agent-incidents', `${data.persisted_incidents || 0} stored`);
  } catch (e) {
    state.services.agent = 'down';
    setServiceStatus('agent', 'down');
  }
}

async function fetchRemediatorHealth() {
  try {
    const data = await apiFetch(`${API.remediator}/health`);
    state.services.remediator = 'ok';
    setServiceStatus('remediator', 'ok');
    setEl('rem-actions', `${data.actions_count || 0} total`);
    setEl('rem-k8s', data.k8s_configured ? '✓ Connected' : '✗ Disconnected');
  } catch (e) {
    state.services.remediator = 'down';
    setServiceStatus('remediator', 'down');
  }
}

async function fetchAlerts() {
  try {
    const data = await apiFetch(`${API.detector}/alerts`);
    state.alerts = Array.isArray(data) ? data : [];
  } catch (e) { state.alerts = []; }
}

async function fetchIncidents() {
  try {
    const data = await apiFetch(`${API.agent}/incidents?limit=20`);
    state.incidents = Array.isArray(data) ? data : [];
  } catch (e) { state.incidents = []; }
}

async function fetchMTTR() {
  try { state.mttr = await apiFetch(`${API.agent}/analytics/mttr`); }
  catch (e) { state.mttr = null; }
}

async function fetchCost() {
  try { state.cost = await apiFetch(`${API.agent}/analytics/cost`); }
  catch (e) { state.cost = null; }
}

async function fetchSLA() {
  try { state.sla = await apiFetch(`${API.agent}/analytics/sla`); }
  catch (e) { state.sla = null; }
}

// ── Service Status Ring Renderer ─────────────────────────────
function setServiceStatus(svc, status) {
  const card = document.getElementById(`card-${svc}`);
  const ring = document.getElementById(`ring-${svc}`);
  const badge = document.getElementById(`badge-${svc}`);
  const icon = document.getElementById(`icon-${svc}`);

  if (!card) return;

  card.className = `health-card status-${status}`;

  if (ring) {
    ring.className = `health-ring-fill ${status}`;
    const circumference = 2 * Math.PI * 22;
    const fill = status === 'ok' ? circumference : status === 'degraded' ? circumference * 0.6 : 0;
    ring.style.strokeDashoffset = circumference - fill;
  }

  if (badge) {
    badge.className = `health-status-badge ${status}`;
    const labels = { ok: '✓ Online', degraded: '⚠ Degraded', down: '✗ Offline', loading: '⌛ Checking' };
    badge.textContent = labels[status] || status;
  }

  const icons = { detector: '⬡', agent: '◈', remediator: '◎' };
  if (icon) icon.textContent = icons[svc] || '?';
}

// ── Update All Dashboard Metrics ─────────────────────────────
function updateUI() {
  updateStats();
  renderAlerts();
  renderIncidents();
  updateSLARing();
  updateCostPanel();
  updateTrendData();
  updateGlobalStatus();
}

function updateGlobalStatus() {
  const anyDown = Object.values(state.services).some(s => s === 'down');
  const anyDegraded = Object.values(state.services).some(s => s === 'degraded');
  const alertCount = state.alerts.length;

  const dot = document.getElementById('global-status-dot');
  const text = document.getElementById('global-status-text');

  if (anyDown || alertCount > 2) {
    if (dot) { dot.className = 'status-dot danger'; }
    if (text) { text.textContent = 'CRITICAL'; text.style.color = 'var(--red)'; }
  } else if (anyDegraded || alertCount > 0) {
    if (dot) { dot.className = 'status-dot warning'; }
    if (text) { text.textContent = 'DEGRADED'; text.style.color = 'var(--amber)'; }
  } else {
    if (dot) { dot.className = 'status-dot'; }
    if (text) { text.textContent = 'NOMINAL'; text.style.color = 'var(--green)'; }
  }

  const badge = document.getElementById('badge-incidents');
  if (badge) badge.textContent = state.incidents.length;
}

function updateStats() {
  animateCounter('stat-alerts', state.alerts.length);

  const resolved = state.incidents.filter(i => i.recommended_action && i.recommended_action !== 'none').length;
  animateCounter('stat-resolved', resolved);

  const alertsCount = document.getElementById('alerts-count');
  if (alertsCount) alertsCount.textContent = `${state.alerts.length} alert${state.alerts.length !== 1 ? 's' : ''}`;

  const incCount = document.getElementById('incidents-count');
  if (incCount) incCount.textContent = `${state.incidents.length} total`;

  if (state.mttr) {
    const avgMttr = state.mttr.avg_mttr_seconds;
    if (avgMttr !== null && avgMttr !== undefined) {
      const display = avgMttr < 60 ? Math.round(avgMttr) : (avgMttr / 60).toFixed(1);
      const unit = avgMttr < 60 ? 's' : 'min';
      setEl('stat-mttr', display);
      setEl('stat-mttr-unit', unit);
    }

    const autoRate = state.mttr.autonomous_resolution_rate;
    if (autoRate !== null) {
      setEl('stat-autonomous-rate', `${(autoRate * 100).toFixed(0)}%`);
    }

    const avgSec = state.mttr.avg_mttr_seconds;
    let tier = '';
    if (avgSec < 3600)        tier = '🏆 DORA Elite (<1h)';
    else if (avgSec < 86400)  tier = '✅ DORA High (<1d)';
    else if (avgSec < 604800) tier = '⚠ DORA Medium';
    else                      tier = '🔴 DORA Low';
    setEl('stat-dora-tier', tier);
  }

  if (state.cost) {
    const cost = state.cost.total_cost_usd;
    setEl('stat-cost', cost !== undefined ? cost.toFixed(4) : '0.00');
    setEl('stat-tokens', `${(state.cost.total_tokens || 0).toLocaleString()} tokens used`);
  }
}

// ── Render Alerts List ─────────────────────────────────────────
function renderAlerts() {
  const list = document.getElementById('alerts-list');
  if (!list) return;

  if (!state.alerts || state.alerts.length === 0) {
    list.innerHTML = `<div class="empty-state">
      <div class="empty-state-icon">✓</div>
      <div class="empty-state-text">All systems nominal.<br>No active operations alerts.</div>
    </div>`;
    return;
  }

  list.innerHTML = state.alerts.map(a => {
    const sev = a.severity || (a.anomaly_score < -0.8 ? 'P1' : a.anomaly_score < -0.6 ? 'P2' : 'P3');
    const age = formatAge(a.timestamp);
    const score = typeof a.anomaly_score === 'number' ? a.anomaly_score.toFixed(3) : '—';
    const corrId = a.correlation_id ? `<span style="font-family:var(--font-mono);font-size:9px;color:var(--text-muted);">group: ${a.correlation_id}</span>` : '';
    return `<div class="alert-item">
      <div class="alert-sev ${sev}"></div>
      <div class="alert-content">
        <div class="alert-top">
          <span class="alert-service">${a.service || '—'}</span>
          <span class="alert-time">${age}</span>
        </div>
        <div style="display:flex;align-items:center;gap:6px;margin-top:2px;">
          <span class="sev-chip ${sev}">${sev}</span>
          <span class="alert-score">score: ${score}</span>
          ${corrId}
        </div>
      </div>
    </div>`;
  }).join('');
}

// ── Render Incident Feeds ──────────────────────────────────────
function renderIncidents() {
  const list = document.getElementById('incidents-list');
  if (!list) return;
  renderIncidentList(list, state.incidents.slice(0, 8));
}

function renderAllIncidents() {
  const list = document.getElementById('all-incidents-list');
  const count = document.getElementById('all-incidents-count');
  if (!list) return;
  if (count) count.textContent = `${state.incidents.length} total`;
  renderIncidentList(list, state.incidents);
}

function renderIncidentList(container, incidents) {
  if (!incidents || incidents.length === 0) {
    container.innerHTML = `<div class="empty-state">
      <div class="empty-state-icon">⬡</div>
      <div class="empty-state-text">No operational incidents catalogued.<br>Listening for service anomalies...</div>
    </div>`;
    return;
  }

  container.innerHTML = incidents.map(inc => {
    const autonomous = !inc.requires_human_approval;
    const iconClass = autonomous ? 'autonomous' : (inc.recommended_action === 'none' ? 'failed' : 'human');
    const iconText = autonomous ? '⚡' : '👤';
    const conf = inc.confidence || 0;
    const confClass = conf >= 0.8 ? 'high' : conf >= 0.6 ? 'medium' : 'low';
    const confPct = Math.round(conf * 100);
    const action = inc.recommended_action || 'none';
    const mttrStr = inc.mttr_seconds ? formatDuration(inc.mttr_seconds) : '—';
    const age = formatAge(inc.created_at);

    return `<div class="incident-item" onclick="openIncidentModal('${inc.incident_id}')">
      <div class="incident-icon-wrap ${iconClass}">${iconText}</div>
      <div class="incident-info">
        <div class="incident-top">
          <span class="incident-id">${inc.incident_id}</span>
          <span class="incident-service">${inc.service || '—'}</span>
          <span style="font-size:10px;color:var(--text-muted);margin-left:auto;">${age}</span>
        </div>
        <div class="incident-action">${action.replace(/_/g,' ')} · ${inc.hypothesis ? inc.hypothesis.substring(0,60) + '...' : 'Under analysis'}</div>
      </div>
      <div class="incident-right">
        <div class="confidence-bar-wrap">
          <div class="confidence-bar ${confClass}" style="width:${confPct}%"></div>
        </div>
        <div class="confidence-pct">${confPct}% confidence</div>
        <div class="mttr-badge">${mttrStr}</div>
      </div>
    </div>`;
  }).join('');
}

// ── SLA Ring Graphic Renderer ─────────────────────────────────
function updateSLARing() {
  if (!state.sla && !state.mttr) return;
  const rate = (state.sla?.autonomous_resolution_rate || state.mttr?.autonomous_resolution_rate || 0);
  const pct = Math.round(rate * 100);

  setEl('sla-pct-text', `${pct}%`);

  const ring = document.getElementById('sla-ring-fill');
  if (ring) {
    const circumference = 2 * Math.PI * 36;
    const offset = circumference - (circumference * rate);
    ring.style.strokeDashoffset = offset;
    ring.style.stroke = rate >= 0.7 ? 'var(--green)' : rate >= 0.4 ? 'var(--amber)' : 'var(--red)';
  }

  if (state.mttr) {
    setEl('mttr-p50', state.mttr.p50_mttr_seconds !== null ? formatDuration(state.mttr.p50_mttr_seconds) : '—');
    setEl('mttr-p95', state.mttr.p95_mttr_seconds !== null ? formatDuration(state.mttr.p95_mttr_seconds) : '—');
    setEl('mttr-p99', state.mttr.p99_mttr_seconds !== null ? formatDuration(state.mttr.p99_mttr_seconds) : '—');
  }
}

// ── AI LLM Cost Accounting ────────────────────────────────────
function updateCostPanel() {
  if (!state.cost) return;
  const c = state.cost;
  setEl('cost-total', `$${(c.total_cost_usd || 0).toFixed(4)}`);
  setEl('cost-tokens', (c.total_tokens || 0).toLocaleString());
  setEl('cost-avg', c.avg_cost_per_incident !== undefined ? `$${c.avg_cost_per_incident.toFixed(4)}` : '—');
  setEl('cost-manual', c.manual_sre_cost_usd !== undefined ? `~$${c.manual_sre_cost_usd.toFixed(2)}` : '—');
  setEl('cost-savings', c.savings_usd !== undefined ? `~$${c.savings_usd.toFixed(2)}` : '—');
}

// ── MTTR Trend Line Chart Drawing ─────────────────────────────
function updateTrendData() {
  if (!state.mttr) return;
  const p50 = state.mttr.p50_mttr_seconds;
  const p95 = state.mttr.p95_mttr_seconds;
  if (p50 !== null && p50 !== undefined) {
    state.trendData.p50.push(p50);
    if (state.trendData.p50.length > 10) state.trendData.p50.shift();
  }
  if (p95 !== null && p95 !== undefined) {
    state.trendData.p95.push(p95);
    if (state.trendData.p95.length > 10) state.trendData.p95.shift();
  }
  drawTrendChart();
}

function drawTrendChart() {
  const canvas = document.getElementById('trend-canvas');
  if (!canvas) return;

  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = rect.width * dpr;
  canvas.height = 160 * dpr;
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);

  const W = rect.width;
  const H = 160;
  const p50 = state.trendData.p50;
  const p95 = state.trendData.p95;

  if (p50.length < 2) {
    ctx.fillStyle = 'rgba(22, 16, 45, 0.2)';
    ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = 'rgba(124, 58, 237, 0.4)';
    ctx.font = '11px JetBrains Mono';
    ctx.textAlign = 'center';
    ctx.fillText('Syncing metric anomalies...', W/2, H/2);
    return;
  }

  const allVals = [...p50, ...p95];
  const minV = Math.min(...allVals) * 0.8;
  const maxV = Math.max(...allVals) * 1.2;

  function toX(i, total) { return (i / (total - 1)) * W; }
  function toY(v) { return H - ((v - minV) / (maxV - minV)) * H * 0.78 - H * 0.11; }

  function drawLine(data, color, fillColor) {
    if (data.length < 2) return;
    ctx.beginPath();
    data.forEach((v, i) => {
      const x = toX(i, data.length);
      const y = toY(v);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = color;
    ctx.lineWidth = 2.5;
    ctx.lineJoin = 'round';
    ctx.stroke();

    // Fill area below
    ctx.lineTo(toX(data.length - 1, data.length), H);
    ctx.lineTo(toX(0, data.length), H);
    ctx.closePath();
    const grad = ctx.createLinearGradient(0, 0, 0, H);
    grad.addColorStop(0, fillColor);
    grad.addColorStop(1, 'transparent');
    ctx.fillStyle = grad;
    ctx.fill();
  }

  // Draw background grid lines
  for (let i = 0; i <= 4; i++) {
    const y = H * (i / 4) * 0.78 + H * 0.11;
    ctx.strokeStyle = 'rgba(124, 58, 237, 0.08)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(W, y);
    ctx.stroke();
  }

  drawLine(p95, '#f59e0b', 'rgba(245, 158, 11, 0.06)');
  drawLine(p50, '#7c3aed', 'rgba(124, 58, 237, 0.1)');

  // Dots at final coordinates
  [{ data: p50, color: '#7c3aed' }, { data: p95, color: '#f59e0b' }].forEach(({ data, color }) => {
    if (!data.length) return;
    const x = toX(data.length - 1, data.length);
    const y = toY(data[data.length - 1]);
    ctx.beginPath();
    ctx.arc(x, y, 4.5, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();
    ctx.strokeStyle = '#030208';
    ctx.lineWidth = 2;
    ctx.stroke();
  });
}

// ── Analytics Page Rendering ──────────────────────────────────
function renderAnalyticsPage() {
  if (state.mttr) {
    const m = state.mttr;
    setEl('ana-p50', m.p50_mttr_seconds !== null ? Math.round(m.p50_mttr_seconds) : '—');
    setEl('ana-p95', m.p95_mttr_seconds !== null ? Math.round(m.p95_mttr_seconds) : '—');
    setEl('ana-auto', m.autonomous_resolution_rate !== null ? Math.round(m.autonomous_resolution_rate * 100) : '—');

    const avgSec = m.avg_mttr_seconds;
    let tier = '';
    if (avgSec < 3600)        tier = '🏆 Elite Performer';
    else if (avgSec < 86400)  tier = '✅ High Performer';
    else if (avgSec < 604800) tier = '⚠ Medium Performer';
    else                      tier = '🔴 Low Performer';
    setEl('dora-tier-display', tier);

    // Per-service breakdown
    const breakdown = document.getElementById('per-service-breakdown');
    if (breakdown && m.per_service) {
      breakdown.innerHTML = Object.entries(m.per_service).map(([svc, data]) => {
        const mttr = typeof data.avg_mttr === 'number' ? data.avg_mttr.toFixed(1) : '—';
        const pct = Math.min(100, Math.round((data.avg_mttr || 0) / 200 * 100));
        return `<div style="display:flex;flex-direction:column;gap:5px;">
          <div style="display:flex;justify-content:space-between;font-size:12px;">
            <span style="color:var(--text-secondary);font-weight:600;">${svc}</span>
            <span style="font-family:var(--font-mono);color:var(--text-primary);">${mttr}s</span>
          </div>
          <div style="height:5px;background:rgba(22, 16, 45, 0.5);border-radius:3px;overflow:hidden;">
            <div style="height:100%;width:${pct}%;background:var(--violet);border-radius:3px;transition:width 1s ease;"></div>
          </div>
        </div>`;
      }).join('');
    }
  }

  if (state.sla) {
    const s = state.sla;
    setEl('ana-breach', s.breached || 0);
    setEl('ana-breach-rate', s.breach_rate !== null ? `${(s.breach_rate * 100).toFixed(1)}% breach rate` : '—');
  }

  if (state.cost) {
    const c = state.cost;
    setEl('ana-cost-total', `$${(c.total_cost_usd || 0).toFixed(4)}`);
    setEl('ana-total-inc', c.total_incidents || '—');
    setEl('ana-total-tok', (c.total_tokens || 0).toLocaleString());
    setEl('ana-avg-cost', c.avg_cost_per_incident !== undefined ? `$${c.avg_cost_per_incident.toFixed(4)}` : '—');
    setEl('ana-manual', c.manual_sre_cost_usd !== undefined ? `~$${c.manual_sre_cost_usd.toFixed(2)}` : '—');
  }
}

// ── Multi-Agent Reasoning Graph Modal ────────────────────────
function openIncidentModal(incidentId) {
  const inc = state.incidents.find(i => i.incident_id === incidentId);
  if (!inc) return;
  state.currentIncident = inc;

  setEl('modal-title', `RCA Diagnostics: ${incidentId}`);
  setEl('modal-subtitle', `Service: ${inc.service || '—'} · ${formatAge(inc.created_at)}`);

  const conf = inc.confidence || 0;
  const confStyle = conf >= 0.8 ? 'color:var(--green)' : conf >= 0.6 ? 'color:var(--amber)' : 'color:var(--red)';
  const grid = document.getElementById('modal-detail-grid');
  if (grid) {
    grid.innerHTML = [
      ['Incident ID', incidentId],
      ['Service Cluster', inc.service || '—'],
      ['AI Confidence', `<span style="${confStyle}">${Math.round(conf * 100)}%</span>`],
      ['Remediation', inc.recommended_action || 'none'],
      ['MTTR Clock', inc.mttr_seconds ? formatDuration(inc.mttr_seconds) : 'Analyzing...'],
      ['Tokens Drifty', inc.tokens_used ? (inc.tokens_used).toLocaleString() : '—'],
      ['Human Policy', inc.requires_human_approval ? '<span style="color:var(--amber)">P2 Gate Required</span>' : '<span style="color:var(--green)">Autonomous ✓</span>'],
      ['Execution Gate', inc.requires_human_approval ? '👤 Manual Approval' : '⚡ Auto-Remediation'],
    ].map(([label, val]) => `
      <div class="detail-row">
        <div class="detail-label">${label}</div>
        <div class="detail-value">${val}</div>
      </div>
    `).join('');
  }

  const hyp = document.getElementById('modal-hypothesis');
  if (hyp) hyp.innerHTML = inc.hypothesis || 'Awaiting supervisor synthesization...';

  buildReasoningGraph(inc.trace || []);
  renderTraceSteps(inc.trace || []);

  const approveBtn = document.getElementById('modal-approve-btn');
  const rejectBtn = document.getElementById('modal-reject-btn');
  if (approveBtn) approveBtn.style.display = inc.requires_human_approval ? '' : 'none';
  if (rejectBtn) rejectBtn.style.display = inc.requires_human_approval ? '' : 'none';

  const overlay = document.getElementById('modal-overlay');
  if (overlay) {
    overlay.classList.add('open');
    document.body.style.overflow = 'hidden';
  }

  animateReasoningGraph(inc.trace || []);
}

function buildReasoningGraph(trace) {
  const container = document.getElementById('modal-reasoning-graph');
  if (!container) return;

  const agents = [
    { key: 'Detective', icon: '🔍' },
    { key: 'Topologist', icon: '🕸' },
    { key: 'Historian', icon: '📜' },
    { key: 'Log Analyser', icon: '📋' },
    { key: 'Supervisor', icon: '🧠' },
  ];

  container.innerHTML = agents.map((agent, i) => {
    const isLast = i === agents.length - 1;
    const connector = isLast ? '' : `
      <div class="node-connector">
        <div class="connector-line" id="conn-${i}"></div>
        <div class="connector-arrow"></div>
      </div>`;
    return `
      <div class="agent-node" id="node-${i}" data-agent="${agent.key}">
        <div class="agent-node-box">
          <div class="agent-node-icon">${agent.icon}</div>
          <div class="agent-node-label">${agent.key}</div>
        </div>
        <div class="node-status waiting" id="node-status-${i}">Waiting</div>
      </div>
      ${connector}`;
  }).join('');
}

function animateReasoningGraph(trace) {
  const nodes = document.querySelectorAll('.agent-node');
  nodes.forEach(n => {
    n.classList.remove('active','done');
    const status = n.querySelector('.node-status');
    if (status) { status.className = 'node-status waiting'; status.textContent = 'Waiting'; }
  });

  const connectors = document.querySelectorAll('.connector-line');
  connectors.forEach(c => c.classList.remove('active'));

  if (!trace || trace.length === 0) return;

  const totalNodes = document.querySelectorAll('.agent-node').length;
  const maxSteps = Math.min(trace.length, totalNodes);

  for (let i = 0; i < maxSteps; i++) {
    setTimeout(() => {
      const node = document.getElementById(`node-${i}`);
      const statusEl = document.getElementById(`node-status-${i}`);
      const conn = document.getElementById(`conn-${i}`);

      if (i > 0) {
        const prev = document.getElementById(`node-${i-1}`);
        const prevStatus = document.getElementById(`node-status-${i-1}`);
        if (prev) prev.classList.replace('active','done');
        if (prevStatus) { prevStatus.className = 'node-status complete'; prevStatus.textContent = 'Done ✓'; }
      }

      if (node) node.classList.add('active');
      if (statusEl) { statusEl.className = 'node-status running'; statusEl.textContent = 'Running...'; }
      if (conn) conn.classList.add('active');

      if (i === maxSteps - 1) {
        setTimeout(() => {
          if (node) node.classList.replace('active','done');
          if (statusEl) { statusEl.className = 'node-status complete'; statusEl.textContent = 'Done ✓'; }
        }, 700);
      }
    }, i * 650);
  }
}

function renderTraceSteps(trace) {
  const list = document.getElementById('modal-trace-list');
  if (!list) return;
  if (!trace || trace.length === 0) {
    list.innerHTML = '<div style="color:var(--text-muted);font-size:12px;">Trace logs not generated.</div>';
    return;
  }
  list.innerHTML = trace.map(step => {
    const findings = typeof step.findings === 'object' ? Object.entries(step.findings)
      .filter(([,v]) => v !== null && v !== undefined && !(Array.isArray(v) && v.length === 0))
      .map(([k,v]) => `<span style="color:var(--text-secondary)">${k}:</span> <span style="color:var(--violet)">${Array.isArray(v) ? v.join(', ') : v}</span>`)
      .join(' · ') : '';
    return `<div style="display:flex;gap:var(--gap-md);padding:var(--gap-sm) var(--gap-md);background:rgba(22, 16, 45, 0.2);border-radius:var(--r-md);border:1px solid var(--border);align-items:flex-start;">
      <div style="font-family:var(--font-mono);font-size:11px;color:var(--violet);font-weight:700;flex-shrink:0;min-width:20px;">${step.step}</div>
      <div style="flex:1;">
        <div style="font-family:var(--font-display);font-size:12px;font-weight:700;color:var(--text-primary);margin-bottom:2px;">${step.agent}</div>
        <div style="font-size:11px;color:var(--text-secondary);">${step.action}</div>
        ${findings ? `<div style="font-size:10px;margin-top:4px;font-family:var(--font-mono);">${findings}</div>` : ''}
      </div>
    </div>`;
  }).join('');
}

function closeModal(event) {
  if (event && event.target !== document.getElementById('modal-overlay')) return;
  const overlay = document.getElementById('modal-overlay');
  if (overlay) overlay.classList.remove('open');
  document.body.style.overflow = '';
  state.currentIncident = null;
}

function approveAction() {
  const inc = state.currentIncident;
  if (!inc) return;
  closeModal();
  showToast(`✓ Autonomous remediation approved: executing ${inc.recommended_action} on ${inc.service}`, 'success');
}

function rejectAction() {
  const inc = state.currentIncident;
  if (!inc) return;
  closeModal();
  showToast(`✕ SRE Action rejected for incident ${inc.incident_id}`, 'danger');
}

// ── Toast Engine ──────────────────────────────────────────────
function showToast(msg, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  const icons = { success: '✓', danger: '✕', info: 'ℹ' };
  toast.innerHTML = `<span style="font-size:16px;">${icons[type]||'ℹ'}</span><span>${msg}</span>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.animation = 'toast-out 0.3s ease forwards';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// ── DOM Helpers ───────────────────────────────────────────────
function setEl(id, val) {
  const el = document.getElementById(id);
  if (el) el.innerHTML = val;
}

function formatAge(ts) {
  if (!ts) return '—';
  const diff = Math.floor(Date.now() / 1000 - ts);
  if (diff < 60)   return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff/60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff/3600)}h ago`;
  return `${Math.floor(diff/86400)}d ago`;
}

function formatDuration(seconds) {
  if (!seconds) return '—';
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  if (seconds < 3600) return `${Math.floor(seconds/60)}m ${Math.floor(seconds%60)}s`;
  return `${Math.floor(seconds/3600)}h ${Math.floor((seconds%3600)/60)}m`;
}

function animateCounter(id, target) {
  const el = document.getElementById(id);
  if (!el) return;
  const current = parseFloat(el.textContent) || 0;
  if (current === target) return;
  const diff = target - current;
  const steps = 30; // High-fidelity animation ticks
  let step = 0;
  
  // Non-linear spring-like counter rollups
  const interval = setInterval(() => {
    step++;
    const progress = step / steps;
    const springVal = 1 - Math.pow(1 - progress, 3); // Cubic ease-out
    
    el.textContent = Math.round(current + diff * springVal);
    if (step >= steps) { el.textContent = target; clearInterval(interval); }
  }, 16);
}

function openServiceDetail(svc) {
  const urls = {
    detector: `${API.detector}/docs`,
    agent: `${API.agent}/docs`,
    remediator: `${API.remediator}/docs`,
  };
  window.open(urls[svc], '_blank');
}

// ── Keyboard Shortcuts ─────────────────────────────────────────
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') closeModal();
  if (e.key === 'd' && !e.ctrlKey && !e.metaKey) { const nav = document.getElementById('nav-dashboard'); navigate('dashboard', nav); }
  if (e.key === 'i' && !e.ctrlKey && !e.metaKey) { const nav = document.getElementById('nav-incidents'); navigate('incidents', nav); }
  if (e.key === 'a' && !e.ctrlKey && !e.metaKey) { const nav = document.getElementById('nav-analytics'); navigate('analytics', nav); }
});

// ── Engine Initialization ─────────────────────────────────────
function init() {
  initCanvas();
  startClock();

  state.refreshInterval = setInterval(refresh, REFRESH_MS);

  // Load live check; if failing, immediately swap to Demo mode
  refresh().then(() => {
    const allDown = Object.values(state.services).every(s => s === 'down');
    if (allDown && !state.demoMode) {
      showToast('⚡ NeuroOps microservices offline — activating Demo Mode dataset', 'info');
      setTimeout(() => {
        if (!state.demoMode) {
          state.demoMode = true;
          const btn = document.getElementById('btn-demo-mode');
          if (btn) { btn.textContent = '⬡ Live Mode'; btn.classList.remove('btn-primary'); btn.classList.add('btn-ghost'); }
          loadDemoData();
          initCardTilt(); // Attach 3D tilt triggers once loaded
        }
      }, 800);
    } else {
      initCardTilt(); // Attach tilt triggers to live mode cards
    }
  });

  window.addEventListener('resize', () => {
    setTimeout(drawTrendChart, 150);
  });
}

document.addEventListener('DOMContentLoaded', init);
