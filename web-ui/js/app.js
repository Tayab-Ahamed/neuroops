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
const REFRESH_MS = 5000;   // polling interval for health/analytics (not incidents)
const SSE_URL    = `${API.agent}/stream/incidents`;

// ── State ─────────────────────────────────────────────────────
let state = {
  demoMode:        false,
  currentPage:     'command',
  currentIncident: null,
  traceVisible:    false,
  sseActive:       false,    // true when EventSource is connected
  sseSource:       null,     // the live EventSource instance
  pollFallbackId:  null,     // setInterval id used in fallback polling
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
    // Only fetch incidents via REST when SSE is not active
    ...(state.sseActive ? [] : [fetchIncidents()]),
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
  updateDemoBanner();
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

// ── Demo Mode Banner ──────────────────────────────────────────
function updateDemoBanner() {
  let banner = document.getElementById('demo-mode-banner');
  const appDiv = document.getElementById('app');
  if (!appDiv) return;

  const dismissed = sessionStorage.getItem('demo_banner_dismissed') === 'true';

  if (state.demoMode && !dismissed) {
    if (!banner) {
      banner = document.createElement('div');
      banner.id = 'demo-mode-banner';
      banner.style.background = 'var(--amber-dim)';
      banner.style.borderBottom = '1px solid var(--amber)';
      banner.style.color = 'var(--amber)';
      banner.style.padding = '10px 16px';
      banner.style.fontSize = '12px';
      banner.style.fontFamily = 'var(--font-ui)';
      banner.style.fontWeight = '500';
      banner.style.display = 'flex';
      banner.style.alignItems = 'center';
      banner.style.justifyContent = 'space-between';
      banner.style.width = '100%';
      banner.style.boxSizing = 'border-box';
      banner.style.zIndex = '999';

      banner.innerHTML = `
        <div style="display:flex;align-items:center;gap:8px;">
          <span>⚠ DEMO MODE — showing sample data. Run make up to see live data.</span>
        </div>
        <button id="close-demo-banner" style="color:var(--amber);background:none;border:none;font-size:16px;cursor:pointer;line-height:1;display:flex;align-items:center;padding:2px;">✕</button>
      `;

      appDiv.prepend(banner);

      const closeBtn = banner.querySelector('#close-demo-banner');
      if (closeBtn) {
        closeBtn.onclick = () => {
          banner.style.display = 'none';
          sessionStorage.setItem('demo_banner_dismissed', 'true');
        };
      }
    } else {
      banner.style.display = 'flex';
    }
  } else {
    if (banner) {
      banner.style.display = 'none';
    }
  }
}

// ── Orb ───────────────────────────────────────────────────────
function renderOrb() {
  const m = state.mttr;
  const valEl  = document.getElementById('orb-mttr');
  const unitEl = document.getElementById('orb-mttr-unit');
  const doraBadge = document.getElementById('orb-dora-text');

  if (state.services.agent === 'ok' && m && m.avg_mttr_seconds != null) {
    const avg = m.avg_mttr_seconds;
    if (valEl) {
      if (avg < 60) {
        springCounter(valEl, Math.round(avg));
        if (unitEl) unitEl.textContent = 'sec';
      } else {
        springCounter(valEl, Math.floor(avg / 60));
        if (unitEl) unitEl.textContent = `m ${Math.round(avg % 60)}s`;
      }
    }
    if (doraBadge) {
      if      (avg < 3600)   doraBadge.textContent = '🏆 DORA Elite';
      else if (avg < 86400)  doraBadge.textContent = '✅ DORA High';
      else if (avg < 604800) doraBadge.textContent = '⚠ DORA Medium';
      else                   doraBadge.textContent = '🔴 DORA Low';
    }
  } else {
    if (valEl) valEl.textContent = '—';
    if (unitEl) unitEl.textContent = '';
    if (doraBadge) doraBadge.textContent = '—';
  }
}

// ── Info Cards ────────────────────────────────────────────────
function renderInfoCards() {
  const resolvedEl = document.getElementById('info-resolved');
  if (resolvedEl) {
    if (state.services.agent === 'ok') {
      const allResolved = state.incidents.filter(i => i.status === 'resolved' || (!i.requires_human_approval && i.recommended_action)).length;
      springCounter(resolvedEl, allResolved);
    } else {
      resolvedEl.textContent = '—';
    }
  }

  const autoSub = document.getElementById('info-autonomous-rate');
  if (autoSub) {
    const autoRate = state.mttr?.autonomous_resolution_rate;
    if (state.services.agent === 'ok' && autoRate != null) {
      autoSub.textContent = `${Math.round(autoRate * 100)}% autonomous`;
    } else {
      autoSub.textContent = '—% autonomous';
    }
  }

  const alertsEl = document.getElementById('info-alerts');
  if (alertsEl) {
    if (state.services.detector === 'ok') {
      springCounter(alertsEl, state.alerts.length);
    } else {
      alertsEl.textContent = '—';
    }
  }

  const alertsSub = document.getElementById('info-alerts-sub');
  if (alertsSub) {
    if (state.services.detector === 'ok') {
      alertsSub.textContent = `${state.alerts.filter(a => a.severity === 'P1').length} critical`;
    } else {
      alertsSub.textContent = 'Offline';
    }
  }

  const costEl = document.getElementById('info-cost');
  const tokensEl = document.getElementById('info-tokens');
  if (state.services.agent === 'ok' && state.cost) {
    if (costEl) costEl.textContent = `$${state.cost.total_cost_usd.toFixed(4)}`;
    if (tokensEl) tokensEl.textContent = `${(state.cost.total_tokens || 0).toLocaleString()} tokens`;
  } else {
    if (costEl) costEl.textContent = '—';
    if (tokensEl) tokensEl.textContent = '— tokens';
  }
}

// ── Stats Row ─────────────────────────────────────────────────
function renderStatsRow() {
  const activeIncEl = document.getElementById('stat-active-incidents');
  if (activeIncEl) {
    if (state.services.detector === 'ok') {
      springCounter(activeIncEl, state.alerts.length);
    } else {
      activeIncEl.textContent = '—';
    }
  }

  const sub = document.getElementById('stat-incidents-sub');
  if (sub) {
    if (state.services.detector === 'ok') {
      sub.textContent = state.alerts.length > 0
        ? `${state.alerts.filter(a => a.severity === 'P1').length} critical active`
        : 'All systems nominal';
    } else {
      sub.textContent = 'Offline';
    }
  }

  const autoRate = state.mttr?.autonomous_resolution_rate;
  const statAutoRateEl = document.getElementById('stat-auto-rate');
  const ring = document.getElementById('auto-ring-fill');
  if (state.services.agent === 'ok' && autoRate != null) {
    const pct = Math.round(autoRate * 100);
    if (statAutoRateEl) statAutoRateEl.textContent = `${pct}%`;
    if (ring) {
      const circ = 2 * Math.PI * 16;
      ring.style.strokeDashoffset = circ - (circ * autoRate);
    }
  } else {
    if (statAutoRateEl) statAutoRateEl.textContent = '—%';
    if (ring) {
      ring.style.strokeDashoffset = 2 * Math.PI * 16;
    }
  }

  const slaEl = document.getElementById('stat-sla');
  const slaSubEl = document.getElementById('stat-sla-sub');
  if (state.services.agent === 'ok' && state.sla) {
    if (slaEl) slaEl.textContent = state.sla.breached === 0 ? '✓' : String(state.sla.breached);
    if (slaSubEl) slaSubEl.textContent = state.sla.breached === 0 ? 'No SLA breaches' : `${state.sla.breached} breach(es) detected`;
  } else {
    if (slaEl) slaEl.textContent = '—';
    if (slaSubEl) slaSubEl.textContent = 'Offline';
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
  if (state.services.agent === 'ok' && m) {
    setEl('ana-p50', m.p50_mttr_seconds != null ? formatDuration(m.p50_mttr_seconds) : '—');
    setEl('ana-p95', m.p95_mttr_seconds != null ? formatDuration(m.p95_mttr_seconds) : '—');
    const pct = m.autonomous_resolution_rate != null ? Math.round(m.autonomous_resolution_rate * 100) : null;
    setEl('ana-auto-rate', pct != null ? `${pct}%` : '—%');
  } else {
    setEl('ana-p50', '—');
    setEl('ana-p95', '—');
    setEl('ana-auto-rate', '—%');
  }

  if (state.services.agent === 'ok' && state.sla) {
    const s = state.sla;
    setEl('ana-breaches',    s.breached ?? '—');
    setEl('ana-breach-rate', s.breach_rate != null ? `${(s.breach_rate * 100).toFixed(1)}% breach rate` : '—');
  } else {
    setEl('ana-breaches', '—');
    setEl('ana-breach-rate', '—');
  }

  // Draw 4 custom analytics modules
  fetchAndRenderMttrComparison();
  fetchAndRenderCostAnalytics();
  fetchAndRenderResolutionTrend();
  renderBenchmarkHistory();
}

async function fetchAndRenderMttrComparison() {
  const container = document.getElementById('mttr-comparison-content');
  if (!container) return;

  let data = null;
  if (state.demoMode) {
    data = {
      total_incidents: 4,
      overall_avg_mttr_seconds: 112.1,
      p50_mttr_seconds: 96.4,
      p95_mttr_seconds: 163.3,
      per_scenario: [
        { scenario: "pod-delete", avg_agent_mttr_seconds: 63.97, run_count: 3, baseline_mttr_seconds: 300.0, speedup: 4.69 },
        { scenario: "cpu-hog", avg_agent_mttr_seconds: 99.90, run_count: 3, baseline_mttr_seconds: 600.0, speedup: 6.01 },
        { scenario: "memory-hog", avg_agent_mttr_seconds: 123.40, run_count: 3, baseline_mttr_seconds: 900.0, speedup: 7.30 },
        { scenario: "network-latency", avg_agent_mttr_seconds: 163.20, run_count: 3, baseline_mttr_seconds: 1200.0, speedup: 7.35 },
        { scenario: "disk-fill", avg_agent_mttr_seconds: 216.23, run_count: 3, baseline_mttr_seconds: 1800.0, speedup: 8.32 }
      ]
    };
  } else {
    try {
      data = await apiFetch(`${API.agent}/analytics/mttr`);
    } catch (e) {
      console.warn('[Analytics] Failed to fetch MTTR analytics', e);
      container.innerHTML = '<div style="text-align:center;color:var(--red);font-size:11px;font-family:var(--font-code);">Backend offline</div>';
      return;
    }
  }

  if (!data || data.total_incidents === 0) {
    container.innerHTML = '<div style="text-align:center;color:var(--text-dim);font-size:12px;line-height:1.8;">No incidents recorded yet.<br>Run <code style="color:var(--teal-bright);font-family:var(--font-code);">make bench</code> to populate benchmark data.</div>';
    return;
  }

  const list = data.per_scenario || [];
  if (!list.length) {
    container.innerHTML = '<div style="text-align:center;color:var(--text-dim);font-size:12px;">No scenario benchmark data available.</div>';
    return;
  }

  const maxBaseline = Math.max(...list.map(s => s.baseline_mttr_seconds), 1);
  const chartWidth = 320;
  const scale = 240 / maxBaseline;

  let rowsHtml = "";
  list.forEach((item, index) => {
    const y = index * 42 + 8;
    const baseW = Math.round(item.baseline_mttr_seconds * scale);
    const agentW = Math.round(item.avg_agent_mttr_seconds * scale);
    
    rowsHtml += `
      <g>
        <text x="5" y="${y + 14}" fill="var(--text-secondary)" font-size="10.5" font-family="var(--font-ui)" font-weight="500">${item.scenario}</text>
        <rect class="bar-rect" data-width="${baseW}" x="120" y="${y}" width="0" height="6" fill="rgba(100, 180, 220, 0.12)" stroke="rgba(100, 180, 220, 0.25)" rx="1.5"/>
        <text x="${120 + baseW + 6}" y="${y + 6}" fill="var(--text-dim)" font-size="8.5" font-family="var(--font-code)">${Math.round(item.baseline_mttr_seconds)}s</text>
        <rect class="bar-rect agent" data-width="${agentW}" x="120" y="${y + 10}" width="0" height="6" fill="var(--green-dim)" stroke="var(--green)" rx="1.5"/>
        <text class="speedup-lbl" style="opacity:0; transition: opacity 300ms ease; transition-delay: 500ms;" x="${120 + agentW + 6}" y="${y + 16}" fill="var(--green)" font-size="9.5" font-family="var(--font-code)" font-weight="600">${item.speedup}x</text>
      </g>
    `;
  });

  const svgHeight = list.length * 42 + 15;

  container.innerHTML = `
    <svg width="100%" height="${svgHeight}" viewBox="0 0 400 ${svgHeight}">
      ${rowsHtml}
    </svg>
    <div style="display:flex; justify-content:space-between; border-top:1px solid var(--border); padding-top:10px; margin-top:6px; gap:8px;">
      <div style="flex:1; background:var(--void-2); padding:6px; border-radius:6px; text-align:center; border:1px solid var(--border);">
        <div style="font-size:8.5px; color:var(--text-dim); text-transform:uppercase;">Overall Avg</div>
        <div style="font-size:15px; font-weight:700; color:var(--text-primary); font-family:var(--font-code); margin-top:2px;">${formatDuration(data.overall_avg_mttr_seconds)}</div>
      </div>
      <div style="flex:1; background:var(--void-2); padding:6px; border-radius:6px; text-align:center; border:1px solid var(--border);">
        <div style="font-size:8.5px; color:var(--text-dim); text-transform:uppercase;">p50 MTTR</div>
        <div style="font-size:15px; font-weight:700; color:var(--text-primary); font-family:var(--font-code); margin-top:2px;">${formatDuration(data.p50_mttr_seconds)}</div>
      </div>
      <div style="flex:1; background:var(--void-2); padding:6px; border-radius:6px; text-align:center; border:1px solid var(--border);">
        <div style="font-size:8.5px; color:var(--text-dim); text-transform:uppercase;">p95 MTTR</div>
        <div style="font-size:15px; font-weight:700; color:var(--text-primary); font-family:var(--font-code); margin-top:2px;">${formatDuration(data.p95_mttr_seconds)}</div>
      </div>
    </div>
  `;

  setTimeout(() => {
    container.querySelectorAll('.bar-rect').forEach(rect => {
      rect.setAttribute('width', rect.getAttribute('data-width'));
    });
    container.querySelectorAll('.speedup-lbl').forEach(lbl => {
      lbl.style.opacity = '1';
    });
  }, 50);
}

async function fetchAndRenderCostAnalytics() {
  const container = document.getElementById('cost-analytics-content');
  if (!container) return;

  let data = null;
  if (state.demoMode) {
    data = {
      total_cost_usd: 0.3442,
      total_tokens: 22950,
      incidents_counted: 4,
      model_breakdown: {
        haiku: { calls: 2, input_tokens: 8000, output_tokens: 2000, cost_usd: 0.0045 },
        sonnet: { calls: 2, input_tokens: 16000, output_tokens: 4000, cost_usd: 0.3397 }
      },
      savings_vs_all_sonnet_usd: 0.1218
    };
  } else {
    try {
      data = await apiFetch(`${API.agent}/analytics/cost`);
    } catch (e) {
      console.warn('[Analytics] Failed to fetch cost analytics', e);
      container.innerHTML = '<div style="text-align:center;color:var(--red);font-size:11px;font-family:var(--font-code);">Backend offline</div>';
      return;
    }
  }

  if (!data || data.no_data || data.incidents_counted === 0) {
    container.innerHTML = '<div style="text-align:center;color:var(--text-dim);font-size:12px;line-height:1.8;">Cost tracking starts after your first real incident.<br>Set <code style="color:var(--teal-bright);font-family:var(--font-code);">ANTHROPIC_API_KEY</code> and run chaos.</div>';
    return;
  }

  const haikuCalls = data.model_breakdown.haiku.calls;
  const sonnetCalls = data.model_breakdown.sonnet.calls;
  const totalCalls = haikuCalls + sonnetCalls || 1;
  const haikuPct = Math.round((haikuCalls / totalCalls) * 100);
  const sonnetPct = 100 - haikuPct;

  const circ = 226.2;
  const haikuOffset = circ * (1 - haikuCalls / totalCalls);
  const sonnetOffset = circ * (1 - sonnetCalls / totalCalls);
  const sonnetRotation = 360 * (haikuCalls / totalCalls) - 90;

  let savingsHtml = "";
  if (data.savings_vs_all_sonnet_usd > 0.001) {
    savingsHtml = `
      <div style="background:var(--green-dim); border:1px solid rgba(74,222,128,0.3); border-radius:6px; padding:6px 12px; text-align:center; font-size:11px; color:var(--green); font-weight:600; font-family:var(--font-ui);">
        ✓ Saved $${data.savings_vs_all_sonnet_usd.toFixed(4)} vs all-Sonnet routing
      </div>
    `;
  }

  container.innerHTML = `
    <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid var(--border); padding-bottom:12px;">
      <div>
        <div style="font-size:9px; color:var(--text-dim); text-transform:uppercase;">TOTAL INFRA COST</div>
        <div style="font-size:24px; font-weight:800; color:var(--green); font-family:var(--font-code); text-shadow:0 0 10px rgba(74,222,128,0.3);">$${data.total_cost_usd.toFixed(4)}</div>
        <div style="font-size:10px; color:var(--text-dim); margin-top:2px;">${(data.total_tokens || 0).toLocaleString()} total tokens</div>
      </div>
      <div style="text-align:right;">
        <div style="font-size:9px; color:var(--text-dim); text-transform:uppercase;">Incidents</div>
        <div style="font-size:22px; font-weight:700; color:var(--text-primary); font-family:var(--font-code);">${data.incidents_counted}</div>
      </div>
    </div>

    <div style="display:flex; align-items:center; gap:20px; justify-content:center; padding:4px 0;">
      <div style="position:relative; width:90px; height:90px; display:flex; align-items:center; justify-content:center; flex-shrink:0;">
        <svg width="90" height="90" viewBox="0 0 140 140">
          <circle cx="70" cy="70" r="36" fill="none" stroke="rgba(34,211,238,0.05)" stroke-width="8"/>
          <circle class="donut-fill" cx="70" cy="70" r="36" fill="none" stroke="#00D4FF" stroke-width="8" stroke-linecap="round"
                  stroke-dasharray="226.2" stroke-dashoffset="226.2" data-offset="${haikuOffset}"
                  transform="rotate(-90 70 70)" style="transition: stroke-dashoffset 1s ease-out; filter:drop-shadow(0 0 3px rgba(0,212,255,0.4));"/>
          <circle class="donut-fill" cx="70" cy="70" r="36" fill="none" stroke="#8B5CF6" stroke-width="8" stroke-linecap="round"
                  stroke-dasharray="226.2" stroke-dashoffset="226.2" data-offset="${sonnetOffset}"
                  transform="rotate(${sonnetRotation} 70 70)" style="transition: stroke-dashoffset 1s ease-out; filter:drop-shadow(0 0 3px rgba(139,92,246,0.4));"/>
        </svg>
        <div style="position:absolute; display:flex; flex-direction:column; align-items:center; justify-content:center;">
          <div style="font-size:10px; font-family:var(--font-code); font-weight:700; color:var(--text-secondary); text-transform:uppercase; letter-spacing:0.04em;">ROUTING</div>
        </div>
      </div>

      <div style="display:flex; flex-direction:column; gap:6px; font-size:11px;">
        <div style="display:flex; align-items:center; gap:8px;">
          <div style="width:8px; height:8px; border-radius:50%; background:#00D4FF; box-shadow:0 0 4px #00D4FF;"></div>
          <span style="font-weight:600; color:var(--text-primary);">${haikuPct}%</span>
          <span style="color:var(--text-dim);">Haiku (${haikuCalls} calls)</span>
        </div>
        <div style="display:flex; align-items:center; gap:8px;">
          <div style="width:8px; height:8px; border-radius:50%; background:#8B5CF6; box-shadow:0 0 4px #8B5CF6;"></div>
          <span style="font-weight:600; color:var(--text-primary);">${sonnetPct}%</span>
          <span style="color:var(--text-dim);">Sonnet (${sonnetCalls} calls)</span>
        </div>
      </div>
    </div>

    ${savingsHtml}
  `;

  setTimeout(() => {
    container.querySelectorAll('.donut-fill').forEach(circle => {
      circle.style.strokeDashoffset = circle.getAttribute('data-offset');
      circle.setAttribute('stroke-dashoffset', circle.getAttribute('data-offset'));
    });
  }, 50);
}

async function fetchAndRenderResolutionTrend() {
  const container = document.getElementById('resolution-trend-content');
  if (!container) return;

  let data = null;
  if (state.demoMode) {
    data = {
      days_with_data: 7,
      overall_rate_pct: 75.0,
      target_pct: 70,
      daily: [
        { date: "Fri", total_incidents: 1, autonomous: 1, human_approved: 0, rate_pct: 100.0 },
        { date: "Sat", total_incidents: 0, autonomous: 0, human_approved: 0, rate_pct: 0.0 },
        { date: "Sun", total_incidents: 0, autonomous: 0, human_approved: 0, rate_pct: 0.0 },
        { date: "Mon", total_incidents: 2, autonomous: 1, human_approved: 1, rate_pct: 50.0 },
        { date: "Tue", total_incidents: 1, autonomous: 1, human_approved: 0, rate_pct: 100.0 },
        { date: "Wed", total_incidents: 1, autonomous: 0, human_approved: 1, rate_pct: 0.0 },
        { date: "Thu", total_incidents: 3, autonomous: 2, human_approved: 1, rate_pct: 66.7 }
      ]
    };
  } else {
    try {
      data = await apiFetch(`${API.agent}/analytics/resolution`);
    } catch (e) {
      console.warn('[Analytics] Failed to fetch resolution analytics', e);
      container.innerHTML = '<div style="text-align:center;color:var(--red);font-size:11px;font-family:var(--font-code);">Backend offline</div>';
      return;
    }
  }

  if (!data || data.days_with_data < 2) {
    container.innerHTML = '<div style="text-align:center;color:var(--text-dim);font-size:12px;line-height:1.8;">Collecting data — run more chaos scenarios<br>to see autonomous resolution rate trend.</div>';
    return;
  }

  const list = data.daily || [];
  const target = data.target_pct || 70;
  
  const isHealthy = data.overall_rate_pct >= target;
  const strokeColor = isHealthy ? '#4ade80' : '#fb923c';
  const shadowColor = isHealthy ? 'rgba(74,222,128,0.4)' : 'rgba(251,146,60,0.4)';

  const width = 340;
  const height = 150;
  const paddingL = 30;
  const paddingR = 15;
  const paddingT = 20;
  const paddingB = 25;
  
  const plotW = width - paddingL - paddingR;
  const plotH = height - paddingT - paddingB;

  const toX = (idx) => paddingL + (idx / (list.length - 1)) * plotW;
  const toY = (pct) => height - paddingB - (pct / 100) * plotH;

  const points = list.map((item, idx) => ({
    x: toX(idx),
    y: toY(item.rate_pct),
    label: item.date,
    pct: item.rate_pct,
    total: item.total_incidents
  }));

  let pathD = "";
  points.forEach((p, idx) => {
    if (idx === 0) pathD += `M ${p.x} ${p.y}`;
    else pathD += ` L ${p.x} ${p.y}`;
  });

  const targetY = toY(target);

  container.innerHTML = `
    <div style="position:relative; width:100%;">
      <svg width="100%" height="${height}" viewBox="0 0 ${width} ${height}">
        ${[0, 25, 50, 75, 100].map(pct => {
          const y = toY(pct);
          return `
            <line x1="${paddingL}" y1="${y}" x2="${width - paddingR}" y2="${y}" stroke="var(--border)" stroke-width="0.7" stroke-dasharray="3,4"/>
            <text x="5" y="${y + 3}" fill="var(--text-dim)" font-size="7.5" font-family="var(--font-code)">${pct}%</text>
          `;
        }).join('')}

        <line x1="${paddingL}" y1="${targetY}" x2="${width - paddingR}" y2="${targetY}" stroke="#8B5CF6" stroke-width="1.2" stroke-dasharray="4,3"/>
        <text x="${width - 70}" y="${targetY - 4}" fill="#8B5CF6" font-size="7" font-family="var(--font-code)">TARGET 70%</text>

        ${points.map(p => `
          <text x="${p.x}" y="${height - 8}" text-anchor="middle" fill="var(--text-dim)" font-size="8.5" font-family="var(--font-ui)">${p.label}</text>
        `).join('')}

        <path class="draw-line-trend" d="${pathD}" fill="none" stroke="${strokeColor}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"
              stroke-dasharray="400" stroke-dashoffset="400" style="transition: stroke-dashoffset 1.2s ease-out; filter:drop-shadow(0 0 4px ${shadowColor});"/>

        ${points.map(p => `
          <circle cx="${p.x}" cy="${p.y}" r="3" fill="${p.total > 0 ? strokeColor : 'rgba(0,18,36,0.6)'}" stroke="${strokeColor}" stroke-width="1.5"
                  title="${p.label}: ${p.pct}% (${p.total} incidents)" style="cursor:pointer;"/>
        `).join('')}
      </svg>
    </div>
    <div style="text-align:center; font-size:11px; color:var(--text-secondary); border-top:1px solid var(--border); padding-top:10px; margin-top:4px; font-family:var(--font-ui);">
      Overall Autonomous Rate: <strong style="color:${strokeColor}; font-family:var(--font-code); font-size:12px;">${data.overall_rate_pct}%</strong>
    </div>
  `;

  setTimeout(() => {
    const line = container.querySelector('.draw-line-trend');
    if (line) {
      line.style.strokeDashoffset = '0';
      line.setAttribute('stroke-dashoffset', '0');
    }
  }, 50);
}

function renderBenchmarkHistory() {
  const container = document.getElementById('benchmark-history-content');
  if (!container) return;

  container.innerHTML = `
    <div style="font-family: var(--font-ui); color: var(--text-secondary);">
      <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
        <span style="font-weight: 700; color: var(--teal-bright);">📊 Phase 5 Chaos Benchmark — Historical</span>
        <span style="font-size: 11px; color: var(--text-dim);">15 runs, 5 scenarios, Minikube cluster, May 2026</span>
      </div>
      <table class="bench-table">
        <thead>
          <tr>
            <th>Scenario</th>
            <th>Manual MTTR</th>
            <th>Agent MTTR</th>
            <th>Speedup</th>
            <th>Auto?</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td style="font-weight: 500;">pod-delete</td>
            <td>300s</td>
            <td>63.97s</td>
            <td class="speedup">4.69x</td>
            <td><span class="remediation-chip auto" style="font-size: 8px; padding: 2px 6px;">⚡ Auto</span></td>
          </tr>
          <tr>
            <td style="font-weight: 500;">cpu-hog</td>
            <td>600s</td>
            <td>99.90s</td>
            <td class="speedup">6.01x</td>
            <td><span class="remediation-chip auto" style="font-size: 8px; padding: 2px 6px;">⚡ Auto</span></td>
          </tr>
          <tr>
            <td style="font-weight: 500;">memory-hog</td>
            <td>900s</td>
            <td>123.40s</td>
            <td class="speedup">7.30x</td>
            <td><span class="remediation-chip human" style="font-size: 8px; padding: 2px 6px; border-color: rgba(251,146,60,0.25);">👤 Approved</span></td>
          </tr>
          <tr>
            <td style="font-weight: 500;">network-latency</td>
            <td>1200s</td>
            <td>163.20s</td>
            <td class="speedup">7.35x</td>
            <td><span class="remediation-chip human" style="font-size: 8px; padding: 2px 6px; border-color: rgba(251,146,60,0.25);">👤 Approved</span></td>
          </tr>
          <tr>
            <td style="font-weight: 500;">disk-fill</td>
            <td>1800s</td>
            <td>216.23s</td>
            <td class="speedup">8.32x</td>
            <td><span class="remediation-chip human" style="font-size: 8px; padding: 2px 6px; border-color: rgba(251,146,60,0.25);">👤 Approved</span></td>
          </tr>
          <tr class="bench-footer">
            <td style="font-weight: 600;">Avg / Total</td>
            <td>960s</td>
            <td>133.34s</td>
            <td class="speedup" style="color: var(--teal-bright);">8.1x</td>
            <td style="font-size: 9px; font-weight: 600;">0% False Positives</td>
          </tr>
        </tbody>
      </table>
      <div style="font-size: 10px; color: var(--text-dim); margin-top: 10px; font-style: italic;">
        Static historical results. Live MTTR data shown above updates with each new incident.
      </div>
    </div>
  `;
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
  let inc = null;
  let isDemoFallback = false;

  if (state.demoMode) {
    inc = state.incidents.find(i => i.incident_id === incidentId);
    if (!inc) inc = DEMO_INCIDENTS[0];
  } else {
    // Synchronously try to look up first, but also support fetching details
    inc = state.incidents.find(i => i.incident_id === incidentId);
    
    // Attempt detailed fetch
    apiFetch(`${API.agent}/incidents/${incidentId}`).then(data => {
      if (data && data.incident_id === incidentId) {
        state.currentIncident = data;
        // Merge trace/metrics into cached incident if found
        const idx = state.incidents.findIndex(i => i.incident_id === incidentId);
        if (idx !== -1) state.incidents[idx] = data;
        // If we are currently looking at this incident, re-render with fresh details
        if (state.currentPage === 'autopsy' && state.currentIncident.incident_id === incidentId) {
          renderAutopsyCharts(data);
          renderAutopsyTimeline(data);
          renderAutopsyGraph(data);
          renderAutopsyHypothesis(data);
          renderAutopsyRemediationLog(data);
        }
      }
    }).catch(e => {
      console.warn(`[Autopsy] Detailed fetch failed, using memory fallback`, e);
    });
  }

  if (!inc) {
    inc = DEMO_INCIDENTS[0];
    isDemoFallback = true;
  }
  
  state.currentIncident = inc;
  state.traceVisible = false;

  // Toggle page visibility
  ['command', 'incidents', 'analytics', 'postmortems'].forEach(p => {
    const el = document.getElementById(`page-${p}`);
    if (el) el.classList.add('hidden');
  });
  const ap = document.getElementById('page-autopsy');
  if (ap) {
    ap.classList.remove('hidden');
    ap.classList.remove('page-enter');
    void ap.offsetWidth; // force reflow
    ap.classList.add('page-enter');
  }
  state.currentPage = 'autopsy';

  // Toggle demo mode banner
  let demoBanner = document.getElementById('aut-demo-banner');
  if (state.demoMode || isDemoFallback) {
    if (!demoBanner) {
      demoBanner = document.createElement('div');
      demoBanner.id = 'aut-demo-banner';
      demoBanner.style.background = 'var(--amber-dim)';
      demoBanner.style.border = '1px solid var(--amber)';
      demoBanner.style.borderRadius = '8px';
      demoBanner.style.color = 'var(--amber)';
      demoBanner.style.padding = '8px 12px';
      demoBanner.style.fontSize = '12px';
      demoBanner.style.fontFamily = 'var(--font-ui)';
      demoBanner.style.marginBottom = '12px';
      demoBanner.textContent = '⚠ DEMO MODE — showing sample data. Run make up to see live data.';
      ap.insertBefore(demoBanner, ap.querySelector('.autopsy-grid'));
    } else {
      demoBanner.style.display = 'block';
    }
  } else {
    if (demoBanner) {
      demoBanner.style.display = 'none';
    }
  }

  // Header details
  setEl('aut-inc-id', inc.incident_id);
  setEl('aut-service', inc.service || '—');
  setEl('aut-elapsed', formatAge(inc.created_at));
  setEl('aut-mttr', `MTTR: ${inc.mttr_seconds ? formatDuration(inc.mttr_seconds) : '—'}`);

  const sev = getSeverity(inc);
  const sevBadge = document.getElementById('aut-sev-badge');
  if (sevBadge) {
    sevBadge.textContent = sev;
    sevBadge.className = `sev-badge ${sev.toLowerCase()}`;
  }

  // Render Left, Center, Right Columns
  renderAutopsyCharts(inc);
  renderAutopsyTimeline(inc);
  renderAutopsyGraph(inc);
  renderAutopsyHypothesis(inc);
  renderAutopsyRemediationLog(inc);

  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function renderAutopsyCharts(inc) {
  const snap = inc.metric_snapshot || {};
  
  // Latency: SLO 300ms, max 800ms
  let latVal = snap.p99_latency || snap.latency || null;
  if (latVal !== null && latVal < 2.0) latVal = latVal * 1000;
  const latSvg = document.getElementById('chart-latency');
  if (latSvg) latSvg.innerHTML = generateChartSvg('chart-latency', 'p99_latency', latVal, 300, 800);

  // Error Rate: SLO 0.05, max 0.20
  const errVal = snap.error_rate || snap.errors || null;
  const errSvg = document.getElementById('chart-error');
  if (errSvg) errSvg.innerHTML = generateChartSvg('chart-error', 'error_rate', errVal, 0.05, 0.20);

  // CPU: SLO 0.80, max 1.0
  const cpuVal = snap.cpu_usage || snap.cpu || null;
  const cpuSvg = document.getElementById('chart-cpu');
  if (cpuSvg) cpuSvg.innerHTML = generateChartSvg('chart-cpu', 'cpu_usage', cpuVal, 0.80, 1.0);

  // Memory: SLO 0.85, max 1.0
  const memVal = snap.memory_usage || snap.memory || null;
  const memSvg = document.getElementById('chart-memory');
  if (memSvg) memSvg.innerHTML = generateChartSvg('chart-memory', 'memory_usage', memVal, 0.85, 1.0);
}

function generateChartSvg(svgId, metricKey, snapshotValue, sloValue, maxVal) {
  const points = [];
  const faultIndex = 5;
  const baseline = sloValue * 0.35;
  
  for (let i = 0; i < 10; i++) {
    let val;
    if (i < faultIndex) {
      val = baseline + (Math.random() - 0.5) * (baseline * 0.2);
    } else {
      if (i === faultIndex) {
        val = snapshotValue !== null ? snapshotValue : (sloValue * (1.3 + Math.random() * 0.4));
      } else {
        const baseSpike = snapshotValue !== null ? snapshotValue : (sloValue * 1.5);
        const decay = (i - faultIndex) * 0.06;
        val = baseSpike * (1.0 - decay) + (Math.random() - 0.5) * (sloValue * 0.04);
      }
    }
    val = Math.max(0, Math.min(maxVal, val));
    points.push(val);
  }

  const width = 300;
  const height = 90;
  const paddingBottom = 12;
  const paddingTop = 12;
  const plotHeight = height - paddingTop - paddingBottom;
  
  const toX = (index) => (index / (points.length - 1)) * width;
  const toY = (val) => height - paddingBottom - (val / maxVal) * plotHeight;
  
  let pathD = "";
  points.forEach((v, i) => {
    const x = toX(i);
    const y = toY(v);
    if (i === 0) pathD += `M ${x} ${y}`;
    else pathD += ` L ${x} ${y}`;
  });

  const sloY = toY(sloValue);
  const faultX = toX(faultIndex);

  const fmt = (v) => {
    if (metricKey.includes('latency')) return `${Math.round(v)}ms`;
    if (metricKey.includes('rate')) return `${(v * 100).toFixed(1)}%`;
    if (metricKey.includes('usage')) return `${(v * 100).toFixed(0)}%`;
    return v.toFixed(2);
  };

  return `
    <rect width="100%" height="100%" fill="rgba(0, 18, 36, 0.4)" rx="6"/>
    <line x1="0" y1="${sloY}" x2="${width}" y2="${sloY}" stroke="#F5A623" stroke-width="1.2" stroke-dasharray="4,3"/>
    <text x="6" y="${sloY - 4}" fill="#F5A623" font-size="7" font-family="JetBrains Mono" letter-spacing="0.05em">SLO LIMIT: ${fmt(sloValue)}</text>
    <line x1="${faultX}" y1="0" x2="${faultX}" y2="${height}" stroke="#FF4747" stroke-width="1.2"/>
    <text x="${faultX + 4}" y="10" fill="#FF4747" font-size="7" font-family="JetBrains Mono" letter-spacing="0.05em">FAULT INJECTION</text>
    <path class="draw-line" d="${pathD}" fill="none" stroke="#00FF88" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
    ${points.map((v, i) => `
      <circle cx="${toX(i)}" cy="${toY(v)}" r="${i === faultIndex ? 3.5 : 1.8}" fill="${i >= faultIndex ? '#00FF88' : 'var(--text-dim)'}" />
    `).join('')}
  `;
}

function renderAutopsyTimeline(inc) {
  const container = document.getElementById('timeline-bar');
  if (!container) return;
  
  const total = inc.mttr_seconds || 80;
  const detSec = Math.max(1, Math.round(total * 0.15));
  const diagSec = Math.max(1, Math.round(total * 0.45));
  const remSec = Math.max(1, total - detSec - diagSec);
  
  const detPct = (detSec / total) * 100;
  const diagPct = (diagSec / total) * 100;
  const remPct = (remSec / total) * 100;
  
  container.innerHTML = `
    <div class="timeline-segment detection" style="width: ${detPct}%" title="Detection phase: ${formatDuration(detSec)}">${formatDuration(detSec)}</div>
    <div class="timeline-segment diagnosis" style="width: ${diagPct}%" title="Diagnosis phase: ${formatDuration(diagSec)}">${formatDuration(diagSec)}</div>
    <div class="timeline-segment remediation" style="width: ${remPct}%" title="Remediation phase: ${formatDuration(remSec)}">${formatDuration(remSec)}</div>
  `;
}

function renderAutopsyGraph(inc) {
  const svg = document.getElementById('node-graph-svg');
  const overlay = document.getElementById('node-html-overlay');
  if (!svg || !overlay) return;
  
  svg.innerHTML = "";
  overlay.innerHTML = "";
  
  const edges = [
    { id: 'edge-init-det',  d: 'M 200 45 C 200 75, 50 80, 50 110' },
    { id: 'edge-init-topo', d: 'M 200 45 C 200 75, 150 80, 150 110' },
    { id: 'edge-init-hist', d: 'M 200 45 C 200 75, 250 80, 250 110' },
    { id: 'edge-init-log',  d: 'M 200 45 C 200 75, 350 80, 350 110' },
    
    { id: 'edge-det-synth',  d: 'M 50 155 C 50 175, 200 170, 200 190' },
    { id: 'edge-topo-synth', d: 'M 150 155 C 150 175, 200 170, 200 190' },
    { id: 'edge-hist-synth', d: 'M 250 155 C 250 175, 200 170, 200 190' },
    { id: 'edge-log-synth',  d: 'M 350 155 C 350 175, 200 170, 200 190' },
  ];
  
  svg.innerHTML = edges.map(e => `
    <path id="${e.id}" class="node-line" d="${e.d}"/>
  `).join('');
  
  const nodes = [
    { id: 'supervisor_init', name: 'supervisor_init', icon: '🧠', left: '36.25%', top: '8.33%', width: '27.5%', height: '18.75%', agentKey: 'Supervisor' },
    { id: 'detective', name: 'detective', icon: '🔍', left: '1.875%', top: '45.83%', width: '21.25%', height: '18.75%', agentKey: 'Detective' },
    { id: 'topologist', name: 'topologist', icon: '🕸', left: '26.875%', top: '45.83%', width: '21.25%', height: '18.75%', agentKey: 'Topologist' },
    { id: 'historian', name: 'historian', icon: '📜', left: '51.875%', top: '45.83%', width: '21.25%', height: '18.75%', agentKey: 'Historian' },
    { id: 'log_analyser', name: 'log_analyser', icon: '📋', left: '76.875%', top: '45.83%', width: '21.25%', height: '18.75%', agentKey: 'Log Analyser' },
    { id: 'supervisor_synthesize', name: 'supervisor_synthesize', icon: '🤖', left: '32.5%', top: '79.17%', width: '35.0%', height: '18.75%', agentKey: 'Supervisor' },
  ];
  
  overlay.innerHTML = nodes.map(n => `
    <div id="node-${n.id}" data-id="${n.id}" class="node-box pending" style="left:${n.left}; top:${n.top}; width:${n.width}; height:${n.height}; opacity:0; transform:translateY(10px);">
      <div class="node-icon">${n.icon}</div>
      <div class="node-name">${n.name}</div>
      <div class="node-status" id="nodestatus-${n.id}">PENDING</div>
    </div>
  `).join('');
  
  // Staggered node box fade-in
  setTimeout(() => {
    const el = document.getElementById('node-supervisor_init');
    if (el) { el.style.opacity = '1'; el.style.transform = 'translateY(0)'; }
  }, 50);
  
  setTimeout(() => {
    ['detective', 'topologist', 'historian', 'log_analyser'].forEach(id => {
      const el = document.getElementById(`node-${id}`);
      if (el) { el.style.opacity = '1'; el.style.transform = 'translateY(0)'; }
    });
  }, 130);
  
  setTimeout(() => {
    const el = document.getElementById('node-supervisor_synthesize');
    if (el) { el.style.opacity = '1'; el.style.transform = 'translateY(0)'; }
  }, 210);
  
  const trace = inc.trace || [];
  const getFindings = (agentKey) => {
    const step = trace.find(t => t.agent === agentKey);
    if (!step) return "No key findings reported by agent.";
    let txt = step.action || "Analyzed incident state.";
    if (step.findings && typeof step.findings === 'object') {
      const details = Object.entries(step.findings)
        .filter(([k, v]) => v !== null && !(Array.isArray(v) && !v.length))
        .map(([k, v]) => `<strong>${k}:</strong> ${Array.isArray(v) ? v.join(', ') : v}`)
        .join(' · ');
      if (details) txt += `<br><span style="color:var(--teal-bright); font-size:9.5px; margin-top:4px; display:block;">${details}</span>`;
    }
    return txt;
  };

  // Staggered Animation Sequence
  setTimeout(() => {
    setNodeState('supervisor_init', 'running', 'RUNNING');
  }, 250);
  
  setTimeout(() => {
    setNodeState('supervisor_init', 'done', '80ms');
    setupNodeClick('supervisor_init', 'Supervisor Init', 'Supervisor initialised reasoning graph context.');
    
    ['edge-init-det', 'edge-init-topo', 'edge-init-hist', 'edge-init-log'].forEach(id => {
      const path = document.getElementById(id);
      if (path) path.classList.add('done');
    });
  }, 600);
  
  setTimeout(() => {
    ['detective', 'topologist', 'historian', 'log_analyser'].forEach(id => {
      setNodeState(id, 'running', 'RUNNING');
    });
  }, 950);
  
  setTimeout(() => {
    const tDet = Math.floor(Math.random() * 40 + 80);
    const tTopo = Math.floor(Math.random() * 40 + 60);
    const tHist = Math.floor(Math.random() * 30 + 50);
    const tLog = Math.floor(Math.random() * 80 + 100);

    setNodeState('detective', 'done', `${tDet}ms`);
    setNodeState('topologist', 'done', `${tTopo}ms`);
    setNodeState('historian', 'done', `${tHist}ms`);
    setNodeState('log_analyser', 'done', `${tLog}ms`);
    
    setupNodeClick('detective', 'Detective', getFindings('Detective'));
    setupNodeClick('topologist', 'Topologist', getFindings('Topologist'));
    setupNodeClick('historian', 'Historian', getFindings('Historian'));
    setupNodeClick('log_analyser', 'Log Analyser', getFindings('Log Analyser'));
    
    ['edge-det-synth', 'edge-topo-synth', 'edge-hist-synth', 'edge-log-synth'].forEach(id => {
      const path = document.getElementById(id);
      if (path) path.classList.add('done');
    });
  }, 1450);
  
  setTimeout(() => {
    setNodeState('supervisor_synthesize', 'running', 'RUNNING');
  }, 1800);
  
  setTimeout(() => {
    setNodeState('supervisor_synthesize', 'done', '140ms');
    setupNodeClick('supervisor_synthesize', 'Supervisor Synthesize', getFindings('Supervisor') || 'Formulated root cause hypothesis.');
    
    // Fade in Hypothesis card
    const hypothesisCard = document.getElementById('hypothesis-card-new');
    if (hypothesisCard) {
      hypothesisCard.style.opacity = '1';
      hypothesisCard.style.transform = 'translateY(0)';
    }
  }, 2150);
}

function toggleNodeDrawer(nodeEl, agentKey, findingsText) {
  const isExpanded = nodeEl.classList.contains('expanded');
  
  document.querySelectorAll('.node-box').forEach(box => {
    box.classList.remove('expanded');
    const d = box.querySelector('.node-drawer');
    if (d) d.remove();
  });
  
  if (!isExpanded) {
    nodeEl.classList.add('expanded');
    const drawer = document.createElement('div');
    drawer.className = 'node-drawer';
    drawer.innerHTML = `
      <div class="node-drawer-title">${agentKey.replace(/_/g, ' ')} FINDINGS</div>
      <div>${findingsText}</div>
    `;
    nodeEl.appendChild(drawer);
    drawer.onclick = (e) => e.stopPropagation();
  }
}

function setNodeState(nodeId, stateClass, statusText) {
  const node = document.getElementById(`node-${nodeId}`);
  const status = document.getElementById(`nodestatus-${nodeId}`);
  if (node) {
    node.className = `node-box ${stateClass}`;
  }
  if (status) {
    status.textContent = statusText;
  }
}

function setupNodeClick(nodeId, agentKey, findingsText) {
  const node = document.getElementById(`node-${nodeId}`);
  if (!node) return;
  
  if (!node.querySelector('.node-chevron')) {
    const chevron = document.createElement('div');
    chevron.className = 'node-chevron';
    chevron.innerHTML = '▼';
    node.appendChild(chevron);
  }
  
  node.style.cursor = 'pointer';
  node.onclick = (e) => {
    e.stopPropagation();
    toggleNodeDrawer(node, agentKey, findingsText);
  };
}

function renderAutopsyHypothesis(inc) {
  setEl('aut-hypothesis-new', inc.hypothesis || 'Awaiting supervisor synthesis...');
  
  const hypothesisCard = document.getElementById('hypothesis-card-new');
  if (hypothesisCard) {
    hypothesisCard.style.opacity = '0';
    hypothesisCard.style.transform = 'translateY(10px)';
    hypothesisCard.style.transition = 'opacity 300ms ease, transform 300ms ease';
  }

  const conf = inc.confidence || 0.5;
  const fillEl = document.getElementById('conf-arc-fill');
  const pctEl = document.getElementById('conf-pct-new');
  
  if (pctEl) pctEl.textContent = `${Math.round(conf * 100)}%`;
  
  if (fillEl) {
    const dashoffset = 125.6 - (125.6 * conf);
    fillEl.style.strokeDashoffset = '125.6';
    setTimeout(() => {
      fillEl.style.strokeDashoffset = dashoffset;
    }, 450);
  }
  
  const chipWrap = document.getElementById('action-chip-wrap');
  if (chipWrap) {
    const isAuto = !inc.requires_human_approval;
    const chipClass = isAuto ? 'auto' : 'human';
    const chipLabel = isAuto ? '⚡ AUTONOMOUS' : '👤 P2 GATE';
    chipWrap.innerHTML = `<span class="remediation-chip ${chipClass}">${chipLabel}</span>`;
  }
}

function renderAutopsyRemediationLog(inc) {
  let podName = `${inc.service || 'service'}-pod`;
  const trace = inc.trace || [];
  
  const topoStep = trace.find(t => t.agent === 'Topologist');
  if (topoStep && topoStep.findings && topoStep.findings.bottleneck) {
    podName = topoStep.findings.bottleneck;
  } else if (inc.incident_id === 'INC-001') {
    podName = 'backend-6d8f7b9c4-xkz2p';
  } else if (inc.incident_id === 'INC-002') {
    podName = 'frontend-7a9b8c6-yzw1m';
  }
  
  const actionText = `${inc.recommended_action || 'remediate'} ${podName}`;
  setEl('log-action', actionText);
  
  const beforeEl = document.getElementById('pod-status-before');
  const afterEl = document.getElementById('pod-status-after');
  if (beforeEl && afterEl) {
    const act = inc.recommended_action || '';
    if (act.includes('restart')) {
      beforeEl.textContent = 'CRASHING';
      beforeEl.className = 'pod-status-badge danger';
      afterEl.textContent = 'RUNNING';
      afterEl.className = 'pod-status-badge success';
    } else if (act.includes('scale')) {
      beforeEl.textContent = 'SATURATED';
      beforeEl.className = 'pod-status-badge danger';
      afterEl.textContent = 'NOMINAL';
      afterEl.className = 'pod-status-badge success';
    } else if (act.includes('rollback')) {
      beforeEl.textContent = 'DEGRADED';
      beforeEl.className = 'pod-status-badge danger';
      afterEl.textContent = 'NOMINAL';
      afterEl.className = 'pod-status-badge success';
    } else {
      beforeEl.textContent = 'DEGRADED';
      beforeEl.className = 'pod-status-badge danger';
      afterEl.textContent = 'NOMINAL';
      afterEl.className = 'pod-status-badge success';
    }
  }
  
  const timeText = inc.created_at ? new Date(inc.created_at * 1000).toLocaleString('en-GB') : '—';
  setEl('log-timestamp', timeText);
  setEl('log-duration', `elapsed: ${inc.mttr_seconds ? inc.mttr_seconds.toFixed(1) + 's' : '—'}`);
  
  const prRow = document.getElementById('pr-chip-row');
  if (prRow) {
    if (inc.remediation_result && inc.remediation_result.pr_number) {
      prRow.style.display = 'flex';
      prRow.innerHTML = `
        <span class="log-label">GITHUB PR</span>
        <a href="${inc.remediation_result.pr_url || '#'}" target="_blank" class="action-chip-mono" style="color:var(--violet-bright); border-color:var(--border-violet);">
          PR #${inc.remediation_result.pr_number} ↗
        </a>
      `;
    } else if (inc.recommended_action === 'open_pr') {
      prRow.style.display = 'flex';
      prRow.innerHTML = `
        <span class="log-label">GITHUB PR</span>
        <a href="https://github.com/Tayab-Ahamed/neuroops/pull/18" target="_blank" class="action-chip-mono" style="color:var(--violet-bright); border-color:var(--border-violet);">
          PR #18 ↗
        </a>
      `;
    } else {
      prRow.style.display = 'none';
    }
  }
  
  const mttrText = inc.mttr_seconds ? formatDuration(inc.mttr_seconds) : '—';
  setEl('log-mttr-val', mttrText);
  
  let doraTier = 'Elite';
  if (inc.mttr_seconds) {
    if (inc.mttr_seconds >= 604800) doraTier = 'Low';
    else if (inc.mttr_seconds >= 86400) doraTier = 'Medium';
    else if (inc.mttr_seconds >= 3600) doraTier = 'High';
  }
  setEl('log-dora-tier', `${doraTier} Tier`);
  
  const replayBtn = document.getElementById('replay-trace-btn');
  const replaySnippet = document.getElementById('replay-snippet');
  const replayIncIdVal = document.getElementById('replay-inc-id-val');
  
  if (replayBtn && replaySnippet) {
    replaySnippet.style.display = 'none';
    replayBtn.onclick = async () => {
      try {
        const res = await fetch(`${API.agent}/incidents/${inc.incident_id}/replay`, { method: 'POST' });
        if (res.ok) {
          showToast('Replay triggered successfully', 'success');
        } else {
          const isHidden = replaySnippet.style.display === 'none';
          replaySnippet.style.display = isHidden ? 'block' : 'none';
          if (replayIncIdVal) replayIncIdVal.textContent = inc.incident_id;
        }
      } catch (err) {
        const isHidden = replaySnippet.style.display === 'none';
        replaySnippet.style.display = isHidden ? 'block' : 'none';
        if (replayIncIdVal) replayIncIdVal.textContent = inc.incident_id;
      }
    };
  }
}


// ── SSE Status Indicator ──────────────────────────────────────
function setSseStatus(live) {
  const pill  = document.getElementById('sse-pill');
  const dot   = document.getElementById('sse-dot');
  const label = document.getElementById('sse-label');
  if (!pill) return;
  pill.classList.toggle('live', live);
  if (label) label.textContent = live ? 'LIVE' : 'POLL';
  if (dot)   dot.title = live ? 'Streaming via SSE' : 'Polling every 5s';
}

// ── Prepend Incident (SSE real-time path) ─────────────────────
function prependIncident(inc) {
  // Avoid duplicates — if it already exists in state, skip
  if (state.incidents.some(i => i.incident_id === inc.incident_id)) return;

  // Add to front of state array so UI is consistent
  state.incidents.unshift(inc);

  const body = document.getElementById('feed-body');
  if (!body) return;

  // Remove empty state placeholder if present
  const empty = body.querySelector('.feed-empty');
  if (empty) empty.remove();

  // Build the card element
  const wrapper = document.createElement('div');
  wrapper.innerHTML = incCardHTML(inc, 0).trim();
  const card = wrapper.firstElementChild;
  if (!card) return;

  // Animate in: start off-screen right, transition to natural position
  card.style.transform = 'translateX(-20px)';
  card.style.opacity   = '0';
  card.style.transition = 'none';

  body.prepend(card);

  // Trigger transition on next paint
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      card.style.transition = 'transform 0.35s cubic-bezier(0.16,1,0.3,1), opacity 0.3s ease';
      card.style.transform  = 'translateX(0)';
      card.style.opacity    = '1';
    });
  });

  // Update badge count
  const badge = document.getElementById('badge-incidents');
  if (badge) badge.textContent = state.incidents.length;
  const feedCount = document.getElementById('feed-count');
  if (feedCount) feedCount.textContent = `${state.incidents.length} total`;

  // Flash the live dot briefly to signal a new event
  const liveDot = document.querySelector('.live-dot');
  if (liveDot) {
    liveDot.style.transform = 'scale(1.8)';
    liveDot.style.transition = 'transform 0.15s ease';
    setTimeout(() => {
      liveDot.style.transform = '';
    }, 300);
  }

  showToast(
    `New incident: ${inc.service} — ${(inc.recommended_action || 'none').replace(/_/g, ' ')}`,
    inc.requires_human_approval ? 'danger' : 'success'
  );
}

// ── SSE Connection ────────────────────────────────────────────
function initSSE() {
  if (state.demoMode) return;

  // Close any existing connection cleanly
  if (state.sseSource) {
    state.sseSource.close();
    state.sseSource = null;
  }

  try {
    const es = new EventSource(SSE_URL);
    state.sseSource = es;

    es.onopen = () => {
      state.sseActive = true;
      setSseStatus(true);
      // Cancel fallback polling if it was running
      if (state.pollFallbackId !== null) {
        clearInterval(state.pollFallbackId);
        state.pollFallbackId = null;
      }
    };

    es.onmessage = (evt) => {
      if (!evt.data || evt.data.startsWith(':')) return; // ignore comments/heartbeats
      try {
        const inc = JSON.parse(evt.data);
        if (inc && inc.incident_id) prependIncident(inc);
      } catch (e) {
        console.warn('[SSE] Failed to parse incident JSON', e);
      }
    };

    es.onerror = () => {
      // Browser will auto-retry EventSource — if it stays in error, fall back
      if (es.readyState === EventSource.CLOSED) {
        state.sseActive = false;
        state.sseSource = null;
        setSseStatus(false);
        activatePollFallback();
      }
    };
  } catch (e) {
    // EventSource not supported or URL unreachable
    console.warn('[SSE] EventSource failed, using poll fallback:', e);
    state.sseActive = false;
    setSseStatus(false);
    activatePollFallback();
  }
}

function activatePollFallback() {
  if (state.pollFallbackId !== null) return; // already running
  state.pollFallbackId = setInterval(async () => {
    if (state.demoMode) return;
    await fetchIncidents();
    renderFeed();
    if (state.currentPage === 'incidents') renderIncidentsPage();
  }, REFRESH_MS);
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

  // Seed trend data as empty initially for non-demo
  state.trendData.p50 = [];
  state.trendData.p95 = [];

  bindCardTilt();
  window.addEventListener('resize', () => { setTimeout(drawTrendChart, 100); });

  // Initial full fetch — auto-demo if all services are down
  fetchAll().then(() => {
    const allDown = Object.values(state.services).every(s => s === 'down');
    if (allDown && !state.demoMode) {
      setTimeout(() => {
        if (!state.demoMode) {
          state.demoMode = true;
          const btn = document.getElementById('btn-demo');
          if (btn) { btn.textContent = '\u29c1 Live'; btn.classList.add('active-demo'); }
          loadDemoData();
          showToast('Services offline \u2014 Demo mode auto-activated', 'info');
        }
      }, 600);
    } else {
      // Open SSE stream — falls back to 5s polling automatically on error
      initSSE();
    }
  });

  // Periodic refresh for health, alerts, and analytics only
  // Incidents arrive in real-time via SSE; activatePollFallback() handles the fallback case
  setInterval(() => {
    if (!state.demoMode) {
      Promise.allSettled([
        fetchDetectorHealth(),
        fetchAgentHealth(),
        fetchRemediatorHealth(),
        fetchAlerts(),
        fetchMTTR(),
        fetchCost(),
        fetchSLA(),
      ]).then(() => {
        updateGlobalStatus();
        renderOrb();
        renderStatsRow();
        renderInfoCards();
        if (state.currentPage === 'incidents') renderIncidentsPage();
        if (state.currentPage === 'analytics') { renderAnalyticsPage(); setTimeout(drawTrendChart, 50); }
        if (state.currentPage === 'postmortems') renderPostmortems();
      });
    }
  }, REFRESH_MS);
}

document.addEventListener('DOMContentLoaded', init);
