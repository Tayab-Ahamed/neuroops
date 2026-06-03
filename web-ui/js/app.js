/* ============================================================
   NEUROOPS — ORBITAL COMMAND HUB — app.js
   Full-featured Autonomous AI SRE Engine Dashboard
   ============================================================ */
'use strict';

// ── API Config ────────────────────────────────────────────────
const API = {
  detector:   'http://localhost:8001',
  agent:      'http://localhost:8002',
  remediator: 'http://localhost:8003',
};
const REFRESH_MS = 5000;

// ── State ─────────────────────────────────────────────────────
let state = {
  demoMode:        false,
  currentPage:     'command',
  currentIncident: null,
  traceVisible:    false,
  services: { detector: 'loading', agent: 'loading', remediator: 'loading' },
  alerts:       [],
  incidents:    [],
  mttr:         null,
  cost:         null,
  sla:          null,
  trendData:    { p50: [], p95: [] },
};

// ── Demo Data ─────────────────────────────────────────────────
const DEMO_INCIDENTS = [
  {
    incident_id: 'INC-001',
    service: 'backend',
    hypothesis: 'Backend pod <strong>backend-6d8f7b9c4-xkz2p</strong> was deleted by LitmusChaos pod-delete experiment. IsolationForest anomaly score <strong>-0.891</strong> confirms abnormal behaviour. Kubernetes reported CrashLoopBackOff within 14s.',
    confidence: 0.91,
    recommended_action: 'restart_pod',
    requires_human_approval: false,
    tokens_used: 4850,
    mttr_seconds: 65.0,
    created_at: Math.floor(Date.now() / 1000) - 900,
    status: 'resolved',
    trace: [
      { step:1, agent:'Detective',    action:'Queried Prometheus — p99 latency spike to 892ms',           findings:{ anomaly_score:-0.891, metric:'http_request_duration_p99' } },
      { step:2, agent:'Topologist',   action:'Traced Jaeger spans — bottleneck at backend pod',           findings:{ bottleneck:'backend-6d8f7b9c4-xkz2p', trace_id:'abc123ef' } },
      { step:3, agent:'Historian',    action:'Scanned GitHub deployments — no recent deploys found',      findings:{ suspect_commit:null, recent_deploys:0 } },
      { step:4, agent:'Log Analyser', action:'Scraped container logs — OOMKilled & CrashLoopBackOff',    findings:{ error_logs:['OOMKilled','CrashLoopBackOff'] } },
      { step:5, agent:'Supervisor',   action:'Synthesised findings — autonomous restart approved',        findings:{ likely_origin:'pod-delete chaos experiment' } },
    ]
  },
  {
    incident_id: 'INC-002',
    service: 'frontend',
    hypothesis: 'Frontend CPU utilisation reached <strong>94% of limit</strong>. IsolationForest anomaly score <strong>-0.763</strong>. Ridge Regression forecasts continued saturation for 4+ minutes. Scaling to 3 replicas resolves the pressure.',
    confidence: 0.82,
    recommended_action: 'scale_replicas',
    requires_human_approval: false,
    tokens_used: 5340,
    mttr_seconds: 96.4,
    created_at: Math.floor(Date.now() / 1000) - 3600,
    status: 'resolved',
    trace: [
      { step:1, agent:'Detective',    action:'CPU at 94% — anomaly score -0.763 on frontend',            findings:{ anomaly_score:-0.763, metric:'cpu_usage_percent' } },
      { step:2, agent:'Topologist',   action:'High latency traced on frontend→backend calls',             findings:{ bottleneck:'frontend', trace_id:'def456ab' } },
      { step:3, agent:'Historian',    action:'Detected cpu-hog LitmusChaos experiment in cluster',        findings:{ suspect_commit:'chaos/cpu-hog.yaml', recent_deploys:1 } },
      { step:4, agent:'Log Analyser', action:'No app errors — resource exhaustion confirmed',              findings:{ error_logs:[] } },
      { step:5, agent:'Supervisor',   action:'Scale-out approved — autonomous execution triggered',        findings:{ likely_origin:'cpu-hog chaos experiment' } },
    ]
  },
  {
    incident_id: 'INC-003',
    service: 'backend',
    hypothesis: 'Backend memory at <strong>87% of limit</strong> with OOMKill pressure. Confidence <strong>0.74</strong> is below autonomous threshold of 0.80. Human operator approval required before scaling to prevent cascading failures.',
    confidence: 0.74,
    recommended_action: 'scale_replicas',
    requires_human_approval: true,
    tokens_used: 5920,
    mttr_seconds: 123.7,
    created_at: Math.floor(Date.now() / 1000) - 7200,
    status: 'pending',
    trace: [
      { step:1, agent:'Detective',    action:'Memory 87% — OOMKill pressure anomaly detected',            findings:{ anomaly_score:-0.712, metric:'memory_usage_percent' } },
      { step:2, agent:'Topologist',   action:'Traced downstream impact to database-stub queries',          findings:{ bottleneck:'backend', trace_id:'ghi789cd' } },
      { step:3, agent:'Historian',    action:'No recent deploys — chaos injection suspected',              findings:{ suspect_commit:null, recent_deploys:0 } },
      { step:4, agent:'Log Analyser', action:'OOMKilled events confirmed in pod logs',                    findings:{ error_logs:['OOMKilled','memory limit exceeded'] } },
      { step:5, agent:'Supervisor',   action:'P2 gate triggered — human approval required',               findings:{ likely_origin:'memory-hog chaos experiment' } },
    ]
  },
  {
    incident_id: 'INC-004',
    service: 'database-stub',
    hypothesis: 'Database-stub P99 latency reached <strong>502ms</strong> (baseline: 38ms). Network latency injection of <strong>500ms</strong> confirmed via Jaeger trace correlation. Restart recommended pending human approval.',
    confidence: 0.68,
    recommended_action: 'restart_pod',
    requires_human_approval: true,
    tokens_used: 6840,
    mttr_seconds: 163.3,
    created_at: Math.floor(Date.now() / 1000) - 21600,
    status: 'pending',
    trace: [
      { step:1, agent:'Detective',    action:'P99 latency 502ms on database-stub — score -0.634',         findings:{ anomaly_score:-0.634, metric:'http_request_duration_p99' } },
      { step:2, agent:'Topologist',   action:'Jaeger shows 500ms artificial delay on db-stub connections',findings:{ bottleneck:'database-stub', trace_id:'jkl012ef' } },
      { step:3, agent:'Historian',    action:'network-latency chaos experiment detected in events',        findings:{ suspect_commit:'chaos/network-latency.yaml' } },
      { step:4, agent:'Log Analyser', action:'No app errors — pure network injection confirmed',           findings:{ error_logs:[] } },
      { step:5, agent:'Supervisor',   action:'Restart recommended — approval required (conf: 0.68)',       findings:{ likely_origin:'network-latency chaos experiment' } },
    ]
  },
];

const DEMO_ALERTS = [
  { service:'backend',       severity:'P1', anomaly_score:-0.891, timestamp: Math.floor(Date.now()/1000) - 180,  correlation_id:'corr-001' },
  { service:'frontend',      severity:'P2', anomaly_score:-0.763, timestamp: Math.floor(Date.now()/1000) - 960,  correlation_id:'corr-002' },
  { service:'database-stub', severity:'P2', anomaly_score:-0.634, timestamp: Math.floor(Date.now()/1000) - 1800, correlation_id:'corr-003' },
];

const DEMO_MTTR = {
  total_incidents: 4, autonomous_count: 2, avg_mttr_seconds: 112.1,
  p50_mttr_seconds: 96.4, p95_mttr_seconds: 163.3, p99_mttr_seconds: 216.4,
  autonomous_resolution_rate: 0.5,
  per_service: {
    backend:         { avg_mttr: 94.3,  count: 2 },
    frontend:        { avg_mttr: 96.4,  count: 1 },
    'database-stub': { avg_mttr: 163.3, count: 1 },
  }
};

const DEMO_COST = {
  total_incidents: 4, total_tokens: 22950, total_cost_usd: 0.3442,
  avg_tokens_per_incident: 5737, avg_cost_per_incident: 0.0861,
  manual_sre_cost_usd: 281.3, savings_usd: 280.96,
};

const DEMO_SLA = {
  total_resolved: 4, breached: 0, breach_rate: 0.0,
  autonomous_resolution_rate: 0.5, target_met: true,
};

const AGENT_CONFIG = [
  { key: 'Detective',    icon: '🔍', color: '#22d3ee' },
  { key: 'Topologist',   icon: '🕸',  color: '#a855f7' },
  { key: 'Historian',    icon: '📜', color: '#22d3ee' },
  { key: 'Log Analyser', icon: '📋', color: '#a855f7' },
  { key: 'Supervisor',   icon: '🧠', color: '#4ade80' },
];

// ── Neural Constellation Canvas ───────────────────────────────
function initCanvas() {
  const canvas = document.getElementById('bg-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  let W, H, nodes = [];

  function resize() {
    W = canvas.width  = window.innerWidth;
    H = canvas.height = window.innerHeight;
    spawnNodes();
  }

  function spawnNodes() {
    nodes = [];
    const count = Math.floor((W * H) / 14000);
    for (let i = 0; i < count; i++) {
      const isMajor = Math.random() < 0.2;
      nodes.push({
        x:  Math.random() * W,
        y:  Math.random() * H,
        vx: (Math.random() - 0.5) * 0.1,
        vy: (Math.random() - 0.5) * 0.1,
        r:  isMajor ? Math.random() * 2 + 1 : Math.random() * 0.8 + 0.2,
        alpha: isMajor ? 0.45 : 0.18,
        // Alternate teal and violet
        isTeal: Math.random() < 0.65,
        isMajor,
      });
    }
  }

  function draw() {
    ctx.clearRect(0, 0, W, H);
    // Connections
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const dx = nodes[i].x - nodes[j].x;
        const dy = nodes[i].y - nodes[j].y;
        const dist = Math.sqrt(dx*dx + dy*dy);
        const threshold = (nodes[i].isMajor || nodes[j].isMajor) ? 130 : 80;
        if (dist < threshold) {
          const a = (1 - dist / threshold) * 0.06;
          ctx.beginPath();
          ctx.strokeStyle = `rgba(34,211,238,${a})`;
          ctx.lineWidth = 0.5;
          ctx.moveTo(nodes[i].x, nodes[i].y);
          ctx.lineTo(nodes[j].x, nodes[j].y);
          ctx.stroke();
        }
      }
    }
    // Nodes
    nodes.forEach(n => {
      n.x += n.vx; n.y += n.vy;
      if (n.x < 0) n.x = W; if (n.x > W) n.x = 0;
      if (n.y < 0) n.y = H; if (n.y > H) n.y = 0;
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
      ctx.fillStyle = n.isTeal
        ? `rgba(34,211,238,${n.alpha})`
        : `rgba(168,85,247,${n.alpha})`;
      ctx.fill();
      if (n.isMajor) {
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.r * 3, 0, Math.PI * 2);
        ctx.fillStyle = n.isTeal
          ? 'rgba(34,211,238,0.03)'
          : 'rgba(168,85,247,0.03)';
        ctx.fill();
      }
    });
    requestAnimationFrame(draw);
  }

  window.addEventListener('resize', resize);
  resize();
  draw();
}

// ── 3D Card Tilt Effect ───────────────────────────────────────
function bindCardTilt() {
  document.querySelectorAll('.stat-glass, .orb-info-card').forEach(el => {
    el.onmousemove = (e) => {
      const rect = el.getBoundingClientRect();
      const dx = (e.clientX - rect.left  - rect.width  / 2) / (rect.width  / 2);
      const dy = (e.clientY - rect.top   - rect.height / 2) / (rect.height / 2);
      el.style.transform = `perspective(800px) rotateX(${-dy * 6}deg) rotateY(${dx * 6}deg) scale3d(1.02,1.02,1.02)`;
    };
    el.onmouseleave = () => {
      el.style.transition = 'transform 0.4s cubic-bezier(0.16,1,0.3,1)';
      el.style.transform = '';
      setTimeout(() => { el.style.transition = ''; }, 400);
    };
  });
}

// ── Live Clock ────────────────────────────────────────────────
function startClock() {
  const el = document.getElementById('clock');
  const tick = () => {
    if (el) el.textContent = new Date().toLocaleTimeString('en-GB', { hour12: false });
    setTimeout(tick, 1000);
  };
  tick();
}

// ── Navigation ────────────────────────────────────────────────
function navigate(page, tabEl) {
  document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
  if (tabEl) tabEl.classList.add('active');

  const pages = ['command', 'incidents', 'analytics', 'postmortems', 'autopsy'];
  pages.forEach(p => {
    const el = document.getElementById(`page-${p}`);
    if (el) el.classList.toggle('hidden', p !== page);
  });

  state.currentPage = page;

  if (page === 'incidents')  renderIncidentsPage();
  if (page === 'analytics')  { renderAnalyticsPage(); setTimeout(drawTrendChart, 50); }
  if (page === 'postmortems') renderPostmortems();
  if (page !== 'autopsy')    setTimeout(bindCardTilt, 100);
}

// ── Fetchers ──────────────────────────────────────────────────
async function apiFetch(url, timeout = 4000) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeout);
  try {
    const res = await fetch(url, { signal: ctrl.signal });
    clearTimeout(t);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (e) { clearTimeout(t); throw e; }
}

async function fetchAll() {
  if (state.demoMode) return;
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
  renderAll();
  updateGlobalStatus();
}

async function fetchDetectorHealth() {
  try {
    const d = await apiFetch(`${API.detector}/health`);
    state.services.detector = 'ok';
    setServiceCapsule('detector', 'ok', `score: ${d.latest_anomaly_score?.toFixed(3) ?? '—'}`);
    updateOrbDot('detector', 'ok');
  } catch {
    state.services.detector = 'down';
    setServiceCapsule('detector', 'danger', 'Offline');
    updateOrbDot('detector', 'danger');
  }
}

async function fetchAgentHealth() {
  try {
    const d = await apiFetch(`${API.agent}/health`);
    state.services.agent = 'ok';
    setServiceCapsule('agent', 'ok', `${d.persisted_incidents ?? 0} incidents`);
    updateOrbDot('agent', 'ok');
  } catch {
    state.services.agent = 'down';
    setServiceCapsule('agent', 'danger', 'Offline');
    updateOrbDot('agent', 'danger');
  }
}

async function fetchRemediatorHealth() {
  try {
    const d = await apiFetch(`${API.remediator}/health`);
    state.services.remediator = 'ok';
    setServiceCapsule('remediator', 'ok', `${d.actions_count ?? 0} actions`);
    updateOrbDot('remediator', 'ok');
  } catch {
    state.services.remediator = 'down';
    setServiceCapsule('remediator', 'danger', 'Offline');
    updateOrbDot('remediator', 'danger');
  }
}

async function fetchAlerts() {
  try {
    const d = await apiFetch(`${API.detector}/alerts`);
    state.alerts = Array.isArray(d) ? d : [];
  } catch { state.alerts = []; }
}

async function fetchIncidents() {
  try {
    const d = await apiFetch(`${API.agent}/incidents?limit=20`);
    state.incidents = Array.isArray(d) ? d : [];
  } catch { state.incidents = []; }
}

async function fetchMTTR() {
  try { state.mttr = await apiFetch(`${API.agent}/analytics/mttr`); }
  catch { state.mttr = null; }
}

async function fetchCost() {
  try { state.cost = await apiFetch(`${API.agent}/analytics/cost`); }
  catch { state.cost = null; }
}

async function fetchSLA() {
  try { state.sla = await apiFetch(`${API.agent}/analytics/sla`); }
  catch { state.sla = null; }
}

// ── Service Capsule Helper ────────────────────────────────────
function setServiceCapsule(svc, status, metric) {
  const port = { detector: 8001, agent: 8002, remediator: 8003 }[svc];
  const cap  = document.getElementById(`cap-${svc}`);
  const dot  = document.getElementById(`capdot-${svc}`);
  const met  = document.getElementById(`capmet-${svc}`);
  if (!cap) return;
  cap.className = `service-capsule ${status === 'ok' ? '' : status}`.trim();
  if (dot) dot.className = `capsule-dot ${status === 'ok' ? '' : status}`.trim();
  if (met) met.textContent = `:${port} · ${metric}`;
}

function updateOrbDot(svc, status) {
  const el = document.getElementById(`orbdot-${svc}`);
  if (el) el.className = `service-dot ${status === 'ok' ? '' : status}`.trim();
}

// Build service dots on orb outer ring
function buildServiceDots() {
  const container = document.getElementById('service-dots');
  if (!container) return;
  const r = 175; // half of 350px ring
  const svcs = [
    { key: 'detector',   angle: 90 },
    { key: 'agent',      angle: 210 },
    { key: 'remediator', angle: 330 },
  ];
  container.innerHTML = svcs.map(s => {
    const rad = (s.angle * Math.PI) / 180;
    const x = 175 + r * Math.cos(rad);
    const y = 175 + r * Math.sin(rad);
    return `<div class="service-dot-item" style="position:absolute;left:${x}px;top:${y}px;transform:translate(-50%,-50%);">
      <div class="service-dot loading" id="orbdot-${s.key}"></div>
    </div>`;
  }).join('');
}

// ── Global Status Pill ────────────────────────────────────────
function updateGlobalStatus() {
  const anyDown  = Object.values(state.services).some(s => s === 'down');
  const allDown  = Object.values(state.services).every(s => s === 'down');
  const p1Count  = state.alerts.filter(a => a.severity === 'P1').length;
  const pill     = document.getElementById('global-status-pill');
  const text     = document.getElementById('global-status-text');
  const badge    = document.getElementById('badge-incidents');

  if (!pill) return;

  if (p1Count > 0 || (anyDown && !state.demoMode)) {
    pill.className = 'nav-status-pill critical';
    if (text) text.textContent = 'CRITICAL';
  } else if (state.alerts.length > 0 || anyDown) {
    pill.className = 'nav-status-pill warning';
    if (text) text.textContent = 'DEGRADED';
  } else {
    pill.className = 'nav-status-pill';
    if (text) text.textContent = 'NOMINAL';
  }

  if (badge) badge.textContent = state.incidents.length;
}

// ── Demo Mode ─────────────────────────────────────────────────
function toggleDemoMode() {
  state.demoMode = !state.demoMode;
  const btn = document.getElementById('btn-demo');
  if (btn) {
    btn.textContent = state.demoMode ? '⬡ Live' : '⚡ Demo';
    btn.classList.toggle('active-demo', state.demoMode);
  }
  if (state.demoMode) {
    loadDemoData();
    showToast('Demo mode — synthetic incident data active', 'info');
  } else {
    showToast('Reconnecting to live services...', 'info');
    // Reset service states
    Object.keys(state.services).forEach(k => { state.services[k] = 'loading'; });
    setServiceCapsule('detector',   'loading', 'Checking...');
    setServiceCapsule('agent',      'loading', 'Checking...');
    setServiceCapsule('remediator', 'loading', 'Checking...');
    fetchAll();
  }
}

function loadDemoData() {
  state.alerts    = DEMO_ALERTS;
  state.incidents = DEMO_INCIDENTS;
  state.mttr      = DEMO_MTTR;
  state.cost      = DEMO_COST;
  state.sla       = DEMO_SLA;

  setServiceCapsule('detector',   'ok', 'Anomaly score: -0.891');
  setServiceCapsule('agent',      'ok', '4 incidents stored');
  setServiceCapsule('remediator', 'ok', '6 actions executed');
  updateOrbDot('detector',   'ok');
  updateOrbDot('agent',      'ok');
  updateOrbDot('remediator', 'ok');
  Object.keys(state.services).forEach(k => { state.services[k] = 'ok'; });

  state.trendData.p50 = [88, 72, 96, 64, 96, 112, 96, 64, 88, 96, 80, 96];
  state.trendData.p95 = [130, 120, 163, 96, 163, 196, 163, 96, 130, 163, 120, 163];

  renderAll();
}

// ── Render All ────────────────────────────────────────────────
function renderAll() {
  renderOrb();
  renderInfoCards();
  renderStatsRow();
  renderFeed();
  updateGlobalStatus();
  if (state.currentPage === 'incidents')  renderIncidentsPage();
  if (state.currentPage === 'analytics')  { renderAnalyticsPage(); setTimeout(drawTrendChart, 50); }
  if (state.currentPage === 'postmortems') renderPostmortems();
  setTimeout(bindCardTilt, 100);
}

// ── Orb ───────────────────────────────────────────────────────
function renderOrb() {
  const m = state.mttr;
  if (!m || m.avg_mttr_seconds == null) return;
  const avg = m.avg_mttr_seconds;

  const valEl  = document.getElementById('orb-mttr');
  const unitEl = document.getElementById('orb-mttr-unit');

  if (valEl) {
    if (avg < 60) {
      springCounter(valEl, Math.round(avg), '');
      if (unitEl) unitEl.textContent = 'sec';
    } else {
      springCounter(valEl, Math.floor(avg / 60), '');
      if (unitEl) unitEl.textContent = `m ${Math.round(avg % 60)}s`;
    }
  }

  const doraBadge = document.getElementById('orb-dora-text');
  if (doraBadge) {
    if      (avg < 3600)   doraBadge.textContent = '🏆 DORA Elite';
    else if (avg < 86400)  doraBadge.textContent = '✅ DORA High';
    else if (avg < 604800) doraBadge.textContent = '⚠ DORA Medium';
    else                   doraBadge.textContent = '🔴 DORA Low';
  }
}

// ── Info Cards ────────────────────────────────────────────────
function renderInfoCards() {
  const allResolved = state.incidents.filter(i => i.status === 'resolved' || (!i.requires_human_approval && i.recommended_action)).length;
  springCounter(document.getElementById('info-resolved'), allResolved, '');

  const autoRate = state.mttr?.autonomous_resolution_rate;
  const autoSub  = document.getElementById('info-autonomous-rate');
  if (autoSub && autoRate != null) autoSub.textContent = `${Math.round(autoRate * 100)}% autonomous`;

  springCounter(document.getElementById('info-alerts'), state.alerts.length, '');
  const alertsSub = document.getElementById('info-alerts-sub');
  if (alertsSub) alertsSub.textContent = `${state.alerts.filter(a=>a.severity==='P1').length} critical`;

  if (state.cost) {
    setEl('info-cost', `$${state.cost.total_cost_usd.toFixed(4)}`);
    setEl('info-tokens', `${(state.cost.total_tokens || 0).toLocaleString()} tokens`);
  }
}

// ── Stats Row ─────────────────────────────────────────────────
function renderStatsRow() {
  springCounter(document.getElementById('stat-active-incidents'), state.alerts.length, '');
  const sub = document.getElementById('stat-incidents-sub');
  if (sub) sub.textContent = state.alerts.length > 0
    ? `${state.alerts.filter(a=>a.severity==='P1').length} critical active`
    : 'All systems nominal';

  const autoRate = state.mttr?.autonomous_resolution_rate;
  if (autoRate != null) {
    const pct = Math.round(autoRate * 100);
    setEl('stat-auto-rate', `${pct}%`);
    const ring = document.getElementById('auto-ring-fill');
    if (ring) {
      const circ = 2 * Math.PI * 16;
      ring.style.strokeDashoffset = circ - (circ * autoRate);
    }
  }

  if (state.sla) {
    setEl('stat-sla',     state.sla.breached === 0 ? '✓' : String(state.sla.breached));
    setEl('stat-sla-sub', state.sla.breached === 0 ? 'No SLA breaches' : `${state.sla.breached} breach(es) detected`);
  }
}

// ── Neural Activity Feed ──────────────────────────────────────
function renderFeed() {
  const body  = document.getElementById('feed-body');
  const count = document.getElementById('feed-count');
  if (!body) return;

  const items = state.incidents;
  if (count) count.textContent = `${items.length} total`;

  if (!items.length) {
    body.innerHTML = `
      <div class="feed-empty">
        <div class="feed-empty-icon">⬡</div>
        <div class="feed-empty-text">No incidents detected.<br>Neural network is watching...</div>
      </div>`;
    return;
  }

  body.innerHTML = items.map((inc, idx) => incCardHTML(inc, idx)).join('');
}

function incCardHTML(inc, idx = 0) {
  const sev       = getSeverity(inc);
  const conf      = inc.confidence || 0;
  const confPct   = Math.round(conf * 100);
  const confClass = conf >= 0.8 ? 'high' : conf >= 0.6 ? 'medium' : 'low';
  const auto      = !inc.requires_human_approval;
  const age       = formatAge(inc.created_at);
  const mttr      = inc.mttr_seconds ? formatDuration(inc.mttr_seconds) : '—';
  const action    = (inc.recommended_action || 'none').replace(/_/g, ' ');

  const agents = AGENT_CONFIG.map((a, i) => {
    const done = (inc.trace || []).some(t => t.agent === a.key);
    return `<div class="agent-mini ${done ? 'done' : ''}" title="${a.key}">${a.icon}</div>
      ${i < AGENT_CONFIG.length - 1 ? `<div class="agent-chain-connector ${done ? 'active' : ''}"></div>` : ''}`;
  }).join('');

  return `
    <div class="inc-card sev-${sev.toLowerCase()}" onclick="openAutopsy('${inc.incident_id}')" style="animation-delay:${idx*60}ms">
      <div class="inc-card-top">
        <div>
          <div class="inc-id">${inc.incident_id}</div>
          <div class="inc-service">${inc.service || '—'}</div>
        </div>
        <div class="inc-age">${age}</div>
      </div>
      <div class="inc-badges">
        <span class="sev-badge ${sev.toLowerCase()}">${sev}</span>
        <span class="mode-badge ${auto ? '' : 'human'}">${auto ? '⚡ AUTO' : '👤 P2 GATE'}</span>
        <span class="font-code text-dim" style="font-size:9px;margin-left:auto;">${action} · ${mttr}</span>
      </div>
      <div class="agent-chain">${agents}</div>
      <div class="conf-row">
        <span class="conf-label">Confidence</span>
        <div class="conf-bar-track"><div class="conf-bar-fill ${confClass}" style="width:${confPct}%"></div></div>
        <span class="conf-pct">${confPct}%</span>
      </div>
    </div>`;
}

function getSeverity(inc) {
  if (inc.severity) return inc.severity.toUpperCase();
  if ((inc.requires_human_approval && inc.confidence < 0.75) || inc.confidence < 0.65) return 'P2';
  if (inc.confidence >= 0.85) return 'P1';
  return 'P2';
}

// ── Incidents Page ────────────────────────────────────────────
function renderIncidentsPage() {
  const list  = document.getElementById('incidents-full-list');
  const count = document.getElementById('inc-page-count');
  if (!list) return;
  if (count) count.textContent = `${state.incidents.length} incidents`;

  if (!state.incidents.length) {
    list.innerHTML = `<div class="feed-empty"><div class="feed-empty-icon">⬡</div><div class="feed-empty-text">No incidents yet.</div></div>`;
    return;
  }

  list.innerHTML = state.incidents.map(inc => {
    const sev       = getSeverity(inc);
    const conf      = inc.confidence || 0;
    const confPct   = Math.round(conf * 100);
    const confClass = conf >= 0.8 ? 'high' : conf >= 0.6 ? 'medium' : 'low';
    const auto      = !inc.requires_human_approval;
    const mttr      = inc.mttr_seconds ? formatDuration(inc.mttr_seconds) : '—';
    const action    = (inc.recommended_action || 'none').replace(/_/g, ' ');
    const preview   = stripHtml(inc.hypothesis || '').substring(0, 110);

    return `
      <div class="glass-panel" style="cursor:pointer;transition:all 0.3s;"
           onclick="openAutopsy('${inc.incident_id}')"
           onmouseover="this.style.borderColor='rgba(34,211,238,0.4)'"
           onmouseout="this.style.borderColor=''">
        <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:12px;">
          <div>
            <div class="font-code text-teal" style="font-size:12px;font-weight:600;">${inc.incident_id}</div>
            <div style="font-size:17px;font-weight:700;color:var(--text-primary);margin-top:2px;">${inc.service}</div>
          </div>
          <div style="display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end;align-items:center;">
            <span class="sev-badge ${sev.toLowerCase()}">${sev}</span>
            <span class="mode-badge ${auto ? '' : 'human'}">${auto ? '⚡ AUTO' : '👤 P2 GATE'}</span>
          </div>
        </div>
        <div style="font-size:12px;color:var(--text-secondary);line-height:1.6;">${preview}…</div>
        <div class="conf-row">
          <span class="conf-label">Confidence</span>
          <div class="conf-bar-track"><div class="conf-bar-fill ${confClass}" style="width:${confPct}%"></div></div>
          <span class="conf-pct">${confPct}%</span>
        </div>
        <div style="display:flex;gap:16px;font-size:10px;color:var(--text-dim);font-family:var(--font-code);flex-wrap:wrap;">
          <span>Action: <span style="color:var(--text-secondary)">${action}</span></span>
          <span>MTTR: <span style="color:var(--text-secondary)">${mttr}</span></span>
          <span>${inc.tokens_used ? inc.tokens_used.toLocaleString() + ' tokens' : ''}</span>
          <span style="margin-left:auto;">${formatAge(inc.created_at)}</span>
        </div>
      </div>`;
  }).join('');
}

// ── Analytics Page ────────────────────────────────────────────
function renderAnalyticsPage() {
  const m = state.mttr;
  if (m) {
    setEl('ana-p50', m.p50_mttr_seconds != null ? formatDuration(m.p50_mttr_seconds) : '—');
    setEl('ana-p95', m.p95_mttr_seconds != null ? formatDuration(m.p95_mttr_seconds) : '—');
    const pct = m.autonomous_resolution_rate != null ? Math.round(m.autonomous_resolution_rate * 100) : null;
    setEl('ana-auto-rate', pct != null ? `${pct}%` : '—%');

    const donut = document.getElementById('donut-fill');
    if (donut && m.autonomous_resolution_rate != null) {
      const circ = 2 * Math.PI * 36;
      donut.style.strokeDashoffset = circ - (circ * m.autonomous_resolution_rate);
      donut.className = `donut-fill ${m.autonomous_resolution_rate >= 0.7 ? 'green' : ''}`;
    }
    setEl('donut-pct',  pct != null ? `${pct}%` : '—%');
    setEl('mttr-p50',   m.p50_mttr_seconds != null ? formatDuration(m.p50_mttr_seconds) : '—');
    setEl('mttr-p95',   m.p95_mttr_seconds != null ? formatDuration(m.p95_mttr_seconds) : '—');
    setEl('mttr-p99',   m.p99_mttr_seconds != null ? formatDuration(m.p99_mttr_seconds) : '—');

    const avg = m.avg_mttr_seconds;
    let tier = '';
    if      (avg < 3600)   tier = '🏆 Elite Performer';
    else if (avg < 86400)  tier = '✅ High Performer';
    else if (avg < 604800) tier = '⚠ Medium Performer';
    else                   tier = '🔴 Low Performer';
    setEl('dora-tier', tier);

    // Per-service breakdown
    const bd = document.getElementById('service-breakdown');
    if (bd && m.per_service) {
      const maxMttr = Math.max(...Object.values(m.per_service).map(d => d.avg_mttr || 0), 1);
      bd.innerHTML = Object.entries(m.per_service).map(([svc, d]) => {
        const pctW = Math.round(((d.avg_mttr || 0) / maxMttr) * 100);
        return `<div class="breakdown-row">
          <span class="breakdown-name">${svc}</span>
          <div class="breakdown-bar-track"><div class="breakdown-bar-fill" style="width:${pctW}%"></div></div>
          <span class="breakdown-val">${formatDuration(d.avg_mttr || 0)}</span>
        </div>`;
      }).join('');
    }

    // Trend data accumulate
    if (m.p50_mttr_seconds != null) {
      state.trendData.p50.push(m.p50_mttr_seconds);
      if (state.trendData.p50.length > 12) state.trendData.p50.shift();
    }
    if (m.p95_mttr_seconds != null) {
      state.trendData.p95.push(m.p95_mttr_seconds);
      if (state.trendData.p95.length > 12) state.trendData.p95.shift();
    }
  }

  if (state.sla) {
    const s = state.sla;
    setEl('ana-breaches',    s.breached ?? '—');
    setEl('ana-breach-rate', s.breach_rate != null ? `${(s.breach_rate * 100).toFixed(1)}% breach rate` : '—');
  }

  if (state.cost) {
    const c = state.cost;
    setEl('ana-tokens',  (c.total_tokens || 0).toLocaleString());
    setEl('ana-cost',    `$${(c.total_cost_usd || 0).toFixed(4)}`);
    setEl('ana-manual',  c.manual_sre_cost_usd  ? `~$${c.manual_sre_cost_usd.toFixed(2)}`  : '—');
    setEl('ana-savings', c.savings_usd           ? `~$${c.savings_usd.toFixed(2)}`          : '—');
  }
}

// ── MTTR Trend Chart ──────────────────────────────────────────
function drawTrendChart() {
  const canvas = document.getElementById('trend-canvas');
  if (!canvas) return;
  const rect = canvas.getBoundingClientRect();
  if (!rect.width) return; // element not visible yet

  const dpr = window.devicePixelRatio || 1;
  canvas.width  = rect.width  * dpr;
  canvas.height = rect.height * dpr;
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  const W = rect.width, H = rect.height;
  const p50 = state.trendData.p50;
  const p95 = state.trendData.p95;

  ctx.fillStyle = 'rgba(0,18,36,0.4)';
  ctx.fillRect(0, 0, W, H);

  if (p50.length < 2) {
    ctx.fillStyle = 'rgba(100,180,220,0.3)';
    ctx.font = '11px JetBrains Mono, monospace';
    ctx.textAlign = 'center';
    ctx.fillText('Waiting for data...', W / 2, H / 2);
    return;
  }

  const all = [...p50, ...p95].filter(Boolean);
  const minV = Math.min(...all) * 0.8;
  const maxV = Math.max(...all) * 1.2;
  const toX = (i, len) => (i / (len - 1)) * W;
  const toY = v => H - ((v - minV) / (maxV - minV)) * H * 0.82 - H * 0.1;

  // Grid lines
  for (let i = 0; i <= 3; i++) {
    const y = H * 0.1 + H * 0.82 * (i / 3);
    ctx.strokeStyle = 'rgba(34,211,238,0.07)';
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 6]);
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
    ctx.setLineDash([]);
  }

  function drawSeriesLine(data, mainColor, fillAlpha) {
    if (data.length < 2) return;
    ctx.save();
    ctx.shadowColor = mainColor;
    ctx.shadowBlur  = 6;
    ctx.beginPath();
    data.forEach((v, i) => {
      if (i === 0) ctx.moveTo(toX(i, data.length), toY(v));
      else         ctx.lineTo(toX(i, data.length), toY(v));
    });
    ctx.strokeStyle = mainColor; ctx.lineWidth = 2; ctx.lineJoin = 'round'; ctx.stroke();

    // Area fill
    ctx.beginPath();
    data.forEach((v, i) => {
      if (i === 0) ctx.moveTo(toX(i, data.length), toY(v));
      else         ctx.lineTo(toX(i, data.length), toY(v));
    });
    ctx.lineTo(toX(data.length - 1, data.length), H);
    ctx.lineTo(0, H); ctx.closePath();
    const grad = ctx.createLinearGradient(0, 0, 0, H);
    grad.addColorStop(0, mainColor.replace(')', `, ${fillAlpha})`).replace('rgb', 'rgba'));
    grad.addColorStop(1, 'transparent');
    ctx.fillStyle = grad; ctx.fill();

    // End dot
    const ex = toX(data.length - 1, data.length);
    const ey = toY(data[data.length - 1]);
    ctx.beginPath(); ctx.arc(ex, ey, 4, 0, Math.PI * 2);
    ctx.fillStyle = mainColor; ctx.shadowBlur = 12; ctx.fill();
    ctx.restore();
  }

  drawSeriesLine(p95, 'rgb(168,85,247)', 0.08);
  drawSeriesLine(p50, 'rgb(34,211,238)', 0.12);

  // Legend
  ctx.shadowBlur = 0;
  [['rgb(34,211,238)', 'p50'], ['rgb(168,85,247)', 'p95']].forEach(([c, label], i) => {
    ctx.fillStyle = c; ctx.beginPath(); ctx.arc(12 + i * 60, 10, 4, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = 'rgba(100,180,220,0.6)'; ctx.font = '9px Space Grotesk, sans-serif';
    ctx.textAlign = 'left'; ctx.fillText(label, 20 + i * 60, 14);
  });
}

// ── Post-Mortems ──────────────────────────────────────────────
function renderPostmortems() {
  const list = document.getElementById('postmortems-list');
  if (!list) return;

  const resolved = state.incidents.filter(i => i.status === 'resolved' || (!i.requires_human_approval && i.recommended_action));
  if (!resolved.length) return; // keep default placeholder

  list.innerHTML = resolved.map(inc => {
    const mttr = inc.mttr_seconds ? formatDuration(inc.mttr_seconds) : '—';
    return `
      <div style="padding:16px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:16px;cursor:pointer;transition:background 0.2s;"
           onmouseover="this.style.background='rgba(34,211,238,0.04)'"
           onmouseout="this.style.background=''"
           onclick="openAutopsy('${inc.incident_id}')">
        <div style="width:3px;height:36px;background:var(--green);box-shadow:0 0 8px var(--green);border-radius:2px;flex-shrink:0;"></div>
        <div style="flex:1;">
          <div style="display:flex;align-items:center;gap:8px;">
            <span class="font-code" style="font-size:12px;color:var(--teal-bright);font-weight:600;">${inc.incident_id}</span>
            <span style="font-size:13px;font-weight:700;color:var(--text-primary);">${inc.service}</span>
            <span class="mode-badge" style="margin-left:auto;">⚡ AUTO-RESOLVED</span>
          </div>
          <div style="font-size:11px;color:var(--text-dim);margin-top:4px;font-family:var(--font-code);">
            MTTR: ${mttr} · Action: ${(inc.recommended_action||'—').replace(/_/g,' ')} · ${formatAge(inc.created_at)}
          </div>
        </div>
        <div style="font-size:20px;opacity:0.4;">▶</div>
      </div>`;
  }).join('');
}

// ── Neural Autopsy Theater ────────────────────────────────────
function openAutopsy(incidentId) {
  const inc = state.incidents.find(i => i.incident_id === incidentId);
  if (!inc) { showToast('Incident not found', 'danger'); return; }
  state.currentIncident = inc;
  state.traceVisible    = false;

  // Full-page takeover
  ['command','incidents','analytics','postmortems'].forEach(p => {
    const el = document.getElementById(`page-${p}`);
    if (el) el.classList.add('hidden');
  });
  const ap = document.getElementById('page-autopsy');
  if (ap) ap.classList.remove('hidden');
  state.currentPage = 'autopsy';

  // Header
  setEl('aut-inc-id',  inc.incident_id);
  setEl('aut-service', inc.service || '—');
  setEl('aut-elapsed', formatAge(inc.created_at));
  setEl('aut-mttr',    `MTTR: ${inc.mttr_seconds ? formatDuration(inc.mttr_seconds) : '—'}`);

  const sev = getSeverity(inc);
  const sevBadge = document.getElementById('aut-sev-badge');
  if (sevBadge) { sevBadge.textContent = sev; sevBadge.className = `sev-badge ${sev.toLowerCase()}`; }

  // Hypothesis
  setEl('aut-hypothesis', inc.hypothesis || 'No AI diagnosis available.');

  // Confidence dial
  const conf = inc.confidence || 0;
  const confPct = Math.round(conf * 100);
  const confClass = conf >= 0.8 ? 'high' : conf >= 0.6 ? 'medium' : 'low';
  setEl('conf-pct', `${confPct}%`);

  const dialFill = document.getElementById('conf-dial-fill');
  if (dialFill) {
    const circ = 2 * Math.PI * 32;
    setTimeout(() => {
      dialFill.style.strokeDashoffset = circ - (circ * conf);
    }, 200);
    dialFill.className = `conf-dial-fill ${confClass}`;
  }

  const confInfoEl = document.getElementById('conf-info-text');
  if (confInfoEl) confInfoEl.textContent =
    conf >= 0.8 ? 'High confidence — autonomous action approved by Supervisor' :
    conf >= 0.6 ? 'Moderate confidence — human review recommended' :
    'Low confidence — explicit human approval required before action';

  // Build synaptic chain
  buildSynapticChain(inc.trace || []);

  // Render trace
  const tl = document.getElementById('trace-list');
  if (tl) tl.style.display = 'none';
  renderTraceSteps(inc.trace || []);

  // Console
  buildConsole(inc);

  // Approve/Reject visibility
  const approveBtn = document.getElementById('aut-approve-btn');
  const rejectBtn  = document.getElementById('aut-reject-btn');
  if (approveBtn) approveBtn.style.display = inc.requires_human_approval && inc.status !== 'resolved' ? '' : 'none';
  if (rejectBtn)  rejectBtn.style.display  = inc.requires_human_approval && inc.status !== 'resolved' ? '' : 'none';

  // Animate chain with stagger
  setTimeout(() => animateSynapticChain(inc.trace || []), 400);
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function buildSynapticChain(trace) {
  const chain = document.getElementById('synaptic-chain');
  if (!chain) return;
  chain.innerHTML = AGENT_CONFIG.map((agent, i) => `
    <div class="syn-node" id="synnode-${i}" data-agent="${agent.key}">
      <div class="syn-hex"><div class="syn-hex-inner">${agent.icon}</div></div>
      <div class="syn-node-label">${agent.key}</div>
      <div class="syn-node-status" id="synstatus-${i}">Waiting</div>
      <div class="syn-node-timing" id="syntiming-${i}">—</div>
    </div>
    ${i < AGENT_CONFIG.length - 1 ? `<div class="syn-connector" id="synconn-${i}"></div>` : ''}
  `).join('');
}

function animateSynapticChain(trace) {
  // Reset all
  for (let i = 0; i < AGENT_CONFIG.length; i++) {
    const n = document.getElementById(`synnode-${i}`);
    const s = document.getElementById(`synstatus-${i}`);
    const c = document.getElementById(`synconn-${i}`);
    const t = document.getElementById(`syntiming-${i}`);
    if (n) n.classList.remove('active', 'done');
    if (s) { s.className = 'syn-node-status'; s.textContent = 'Waiting'; }
    if (c) c.classList.remove('active');
    if (t) t.textContent = '—';
  }

  if (!trace.length) return;
  const steps = Math.min(trace.length, AGENT_CONFIG.length);

  for (let i = 0; i < steps; i++) {
    const timing = Math.floor(Math.random() * 150 + 40);
    setTimeout(() => {
      // Mark prev as done
      if (i > 0) {
        const pn = document.getElementById(`synnode-${i - 1}`);
        const ps = document.getElementById(`synstatus-${i - 1}`);
        if (pn) { pn.classList.remove('active'); pn.classList.add('done'); }
        if (ps) { ps.className = 'syn-node-status done'; ps.textContent = '✓ Done'; }
      }
      const n = document.getElementById(`synnode-${i}`);
      const s = document.getElementById(`synstatus-${i}`);
      const c = document.getElementById(`synconn-${i}`);
      const tEl = document.getElementById(`syntiming-${i}`);
      if (n) n.classList.add('active');
      if (s) { s.className = 'syn-node-status active'; s.textContent = 'Running...'; }
      if (c) c.classList.add('active');
      setTimeout(() => { if (tEl) tEl.textContent = `${timing}ms`; }, 250);

      // Mark last done
      if (i === steps - 1) {
        setTimeout(() => {
          if (n) { n.classList.remove('active'); n.classList.add('done'); }
          if (s) { s.className = 'syn-node-status done'; s.textContent = '✓ Done'; }
        }, 900);
      }
    }, i * 700 + 100);
  }
}

function renderTraceSteps(trace) {
  const list = document.getElementById('trace-list');
  if (!list) return;
  if (!trace.length) { list.innerHTML = '<div class="text-dim font-code" style="font-size:11px;">No trace data available.</div>'; return; }

  list.innerHTML = trace.map(step => {
    const findings = typeof step.findings === 'object'
      ? Object.entries(step.findings)
          .filter(([, v]) => v !== null && !(Array.isArray(v) && !v.length))
          .map(([k, v]) => `<span>${Array.isArray(v) ? v.join(', ') : v}</span>`)
          .join(' · ')
      : '';

    return `
      <div class="trace-step">
        <div class="trace-step-num">${step.step}</div>
        <div class="trace-step-body">
          <div class="trace-step-agent">${step.agent}</div>
          <div class="trace-step-action">${step.action}</div>
          ${findings ? `<div class="trace-step-findings font-code">${findings}</div>` : ''}
        </div>
      </div>`;
  }).join('');
}

function toggleTrace() {
  const list = document.getElementById('trace-list');
  const btn  = document.getElementById('trace-toggle-btn');
  if (!list) return;
  state.traceVisible = !state.traceVisible;
  list.style.display = state.traceVisible ? 'flex' : 'none';
  if (btn) btn.textContent = `Step-by-Step Trace ${state.traceVisible ? '▴' : '▾'}`;
}

function buildConsole(inc) {
  const actionMap = {
    restart_pod:     `kubectl rollout restart deployment/${inc.service}`,
    scale_replicas:  `kubectl scale deployment/${inc.service} --replicas=3`,
    rollback:        `kubectl rollout undo deployment/${inc.service}`,
    patch_configmap: `kubectl patch configmap ${inc.service}-config --patch '{}'`,
    open_pr:         `gh pr create --title "fix: ${inc.service} anomaly"`,
    none:            `echo "No action required — monitoring continues"`,
  };

  const cmdStr = actionMap[inc.recommended_action] || 'echo "Evaluating options..."';
  const cmdEl  = document.getElementById('console-cmd');
  const out1   = document.getElementById('console-out1');
  const out2   = document.getElementById('console-out2');
  const curLn  = document.getElementById('console-cursor-line');

  if (cmdEl) { cmdEl.textContent = ''; typeText(cmdEl, cmdStr, 35); }
  if (out1)  { out1.textContent = ''; setTimeout(() => out1.textContent = `→ Submitting to NeuroOps remediator...`,   cmdStr.length * 35 + 200); }
  if (out2)  { out2.textContent = ''; setTimeout(() => out2.textContent = `→ Confidence: ${Math.round((inc.confidence||0)*100)}% · ${(inc.tokens_used||0).toLocaleString()} tokens`,   cmdStr.length * 35 + 600); }
  if (curLn) { curLn.style.display = 'none'; setTimeout(() => { curLn.style.display = 'flex'; }, cmdStr.length * 35 + 1100); }
}

function typeText(el, text, delay = 35) {
  el.textContent = '';
  let i = 0;
  const iv = setInterval(() => {
    el.textContent += text[i++];
    if (i >= text.length) clearInterval(iv);
  }, delay);
}

function approveAction() {
  const inc = state.currentIncident;
  if (!inc) return;
  inc.status = 'resolved';
  showToast(`✓ Remediation approved: ${(inc.recommended_action||'').replace(/_/g,' ')} on ${inc.service}`, 'success');

  // Visual feedback in console
  const out1 = document.getElementById('console-out1');
  const out2 = document.getElementById('console-out2');
  if (out1) out1.textContent = '✓ Action dispatched — awaiting completion signal...';
  if (out2) out2.textContent = '→ NeuroOps remediator is executing the runbook';

  const approveBtn = document.getElementById('aut-approve-btn');
  const rejectBtn  = document.getElementById('aut-reject-btn');
  if (approveBtn) approveBtn.style.display = 'none';
  if (rejectBtn)  rejectBtn.style.display  = 'none';
}

function rejectAction() {
  const inc = state.currentIncident;
  if (!inc) return;
  inc.status = 'rejected';
  showToast(`✕ Action rejected for ${inc.incident_id} — escalating to SRE team`, 'danger');

  const approveBtn = document.getElementById('aut-approve-btn');
  const rejectBtn  = document.getElementById('aut-reject-btn');
  if (approveBtn) approveBtn.style.display = 'none';
  if (rejectBtn)  rejectBtn.style.display  = 'none';
}

// ── Spring Counter ────────────────────────────────────────────
function springCounter(el, target) {
  if (!el || target == null || isNaN(target)) return;
  const rawText = el.textContent.replace(/[^0-9.-]/g, '');
  const start   = parseFloat(rawText) || 0;
  if (start === target) { el.textContent = target; return; }
  const diff  = target - start;
  let step    = 0;
  const total = 28;
  const tick  = () => {
    step++;
    const t   = step / total;
    const ease = 1 - Math.pow(1 - t, 4);
    el.textContent = Math.round(start + diff * ease);
    if (step < total) requestAnimationFrame(tick);
    else el.textContent = target;
  };
  requestAnimationFrame(tick);
}

// ── Toast ─────────────────────────────────────────────────────
function showToast(msg, type = 'info') {
  const c = document.getElementById('toast-container');
  if (!c) return;
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  const icon = { success: '✓', danger: '✕', info: '⬡' }[type] || '⬡';
  toast.innerHTML = `<span class="toast-icon">${icon}</span><span>${msg}</span>`;
  c.appendChild(toast);
  setTimeout(() => {
    toast.style.animation = 'toast-out 0.4s var(--ease) forwards';
    setTimeout(() => toast.remove(), 400);
  }, 3500);
}

// ── Utilities ─────────────────────────────────────────────────
function setEl(id, val) {
  const el = document.getElementById(id);
  if (el) el.innerHTML = String(val);
}

function formatAge(ts) {
  if (!ts) return '—';
  const diff = Math.floor(Date.now() / 1000 - ts);
  if (diff < 60)    return `${diff}s ago`;
  if (diff < 3600)  return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function formatDuration(secs) {
  if (secs == null || secs === 0) return '—';
  if (secs < 60)   return `${secs.toFixed(1)}s`;
  if (secs < 3600) return `${Math.floor(secs/60)}m ${Math.round(secs%60)}s`;
  return `${Math.floor(secs/3600)}h ${Math.floor((secs%3600)/60)}m`;
}

function stripHtml(html) {
  const d = document.createElement('div');
  d.innerHTML = html;
  return d.textContent || '';
}

function openServiceDocs(svc) {
  window.open(`${API[svc]}/docs`, '_blank');
}

// ── Keyboard Shortcuts ────────────────────────────────────────
document.addEventListener('keydown', e => {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
  const map = {
    'd': ['command',     'tab-command'],
    'i': ['incidents',   'tab-incidents'],
    'a': ['analytics',   'tab-analytics'],
    'p': ['postmortems', 'tab-postmortems'],
  };
  if (map[e.key]) navigate(map[e.key][0], document.getElementById(map[e.key][1]));
  if (e.key === 'Escape' && state.currentPage === 'autopsy')
    navigate('command', document.getElementById('tab-command'));
});

// ── Init ──────────────────────────────────────────────────────
function init() {
  initCanvas();
  startClock();
  buildServiceDots();

  // Hide trace list initially
  const tl = document.getElementById('trace-list');
  if (tl) tl.style.display = 'none';

  // Seed trend data for demo
  state.trendData.p50 = [88, 72, 96, 64, 88, 112, 96, 64, 88, 96, 80, 96];
  state.trendData.p95 = [130, 120, 163, 96, 130, 196, 163, 96, 130, 163, 120, 163];

  bindCardTilt();
  window.addEventListener('resize', () => { setTimeout(drawTrendChart, 100); });

  // Initial fetch — auto-demo if all down
  fetchAll().then(() => {
    const allDown = Object.values(state.services).every(s => s === 'down');
    if (allDown && !state.demoMode) {
      setTimeout(() => {
        if (!state.demoMode) {
          state.demoMode = true;
          const btn = document.getElementById('btn-demo');
          if (btn) { btn.textContent = '⬡ Live'; btn.classList.add('active-demo'); }
          loadDemoData();
          showToast('Services offline — Demo mode auto-activated', 'info');
        }
      }, 600);
    }
  });

  // Refresh loop
  setInterval(fetchAll, REFRESH_MS);
}

document.addEventListener('DOMContentLoaded', init);
