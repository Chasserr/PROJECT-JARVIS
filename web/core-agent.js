/* JARVIS Core Agent — presentation only.
 *
 * Every number on this panel is derived from a live Core response:
 *   /api/core/runs    -> agent runs, their plans, step records and approvals
 *   /api/core/agents  -> the real roster status produced by runtime probes
 *   /api/core/tools   -> the registered tool list and effective permissions
 *   /api/health       -> model, provider, memory count and core database health
 *
 * There is no invented progress, timestamp or agent state here. When a value
 * cannot be derived the panel shows an explicit empty or error state instead.
 */
(() => {
  const panel = document.getElementById('coreAgentPanel');
  if (!panel) return;

  const el = (id) => document.getElementById(id);
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const ROLE_LABELS = {
    orchestrator: 'Orchestrator', engineer: 'Software Engineer', research: 'Research Agent',
    security: 'Security Agent', testing: 'Testing Agent', browser: 'Browser Agent',
    desktop: 'Desktop Agent', creative: 'Creative Agent', memory: 'Memory Agent',
    critic: 'Critic Agent', writer: 'Documentation Agent',
  };

  const state = {
    runs: [], agents: [], tools: [], health: null,
    selected: null, errors: {}, busy: false, started: false,
  };

  /* ---------------- helpers ---------------- */
  function text(tag, value, cls) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    node.textContent = value === null || value === undefined ? '' : String(value);
    return node;
  }

  function svg(tag, attrs) {
    const node = document.createElementNS(SVG_NS, tag);
    Object.entries(attrs || {}).forEach(([key, value]) => node.setAttribute(key, value));
    return node;
  }

  function svgText(parent, x, y, value, cls, anchor) {
    const node = svg('text', { x, y, class: cls || 'ca-axis', 'text-anchor': anchor || 'middle' });
    node.textContent = value;
    parent.append(node);
  }

  function empty(node, message) {
    node.replaceChildren(text('p', message, 'ca-empty'));
  }

  function error(node, message) {
    node.replaceChildren(text('p', message, 'ca-error'));
  }

  function roleLabel(id) {
    return ROLE_LABELS[id] || (id ? id.replace(/[-_]/g, ' ') : 'Orchestrator');
  }

  function statusLabel(status) {
    return String(status || 'unknown').replace(/_/g, ' ').toUpperCase();
  }

  async function call(path, body) {
    if (typeof window.coreApi === 'function') return window.coreApi(path, body);
    const response = await fetch(path, {
      method: body === undefined ? 'GET' : 'POST',
      headers: { 'Content-Type': 'application/json' },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    const data = await response.json().catch(() => ({ error: 'Invalid response from JARVIS Core' }));
    if (!response.ok && !(response.status === 409 && data.status === 'awaiting_approval')) {
      throw new Error(data.error || data.detail || ('Core request failed: ' + response.status));
    }
    return data;
  }

  /* ---------------- status pill ---------------- */
  function setStatus(kind, message) {
    const pill = el('coreAgentStatus');
    const label = el('caStatusText');
    if (label) label.textContent = message;
    if (!pill) return;
    pill.className = 'ca-status ca-status--' + kind;
  }

  function setBusy(busy) {
    state.busy = busy;
    const button = el('refreshCoreRuns');
    if (button) button.disabled = busy;
  }

  /* ---------------- data ---------------- */
  async function load() {
    if (state.busy) return;
    setBusy(true);
    if (!state.started) setStatus('unknown', 'Checking Core…');
    const [runs, agents, tools, health] = await Promise.allSettled([
      call('/api/core/runs'), call('/api/core/agents'), call('/api/core/tools'), call('/api/health'),
    ]);

    state.errors = {};
    if (runs.status === 'fulfilled') {
      state.runs = Array.isArray(runs.value?.runs) ? runs.value.runs : [];
    } else {
      state.runs = [];
      state.errors.runs = runs.reason?.message || 'Core runs unavailable';
    }
    if (agents.status === 'fulfilled') {
      state.agents = Array.isArray(agents.value?.agents) ? agents.value.agents : [];
    } else {
      state.agents = [];
      state.errors.agents = agents.reason?.message || 'Agent roster unavailable';
    }
    if (tools.status === 'fulfilled') {
      state.tools = Array.isArray(tools.value) ? tools.value : [];
    } else {
      state.tools = [];
      state.errors.tools = tools.reason?.message || 'Tool list unavailable';
    }
    state.health = health.status === 'fulfilled' ? health.value : null;
    if (health.status !== 'fulfilled') state.errors.health = 'Health endpoint unavailable';

    if (!state.runs.some((run) => run.run_id === state.selected)) {
      const active = state.runs.find((run) => run.status === 'running' || run.status === 'awaiting_approval');
      state.selected = (active || state.runs[0] || {}).run_id || null;
    }
    state.started = true;
    setBusy(false);

    if (state.errors.runs) setStatus('offline', 'Core unreachable');
    else if (state.errors.agents) setStatus('partial', 'Core online · roster unverified');
    else setStatus('online', 'Core online · ' + state.tools.length + ' tools');

    render();
  }

  /* ---------------- KPIs ---------------- */
  function renderKpis() {
    const runs = state.runs;
    const active = runs.filter((run) => run.status === 'running' || run.status === 'awaiting_approval');
    const completed = runs.filter((run) => run.status === 'completed');
    const failed = runs.filter((run) => run.status === 'failed');
    const finished = completed.length + failed.length;
    const roles = new Set(active.map((run) => run.role || 'orchestrator'));

    const set = (id, value, note) => {
      const node = el(id);
      const noteNode = el(id + 'Note');
      if (node) node.textContent = value;
      if (noteNode) noteNode.textContent = note;
    };

    if (state.errors.runs) {
      set('caKpiActive', '—', 'core unreachable');
      set('caKpiCompleted', '—', 'core unreachable');
      set('caKpiAgents', '—', 'core unreachable');
      set('caKpiSuccess', '—', 'core unreachable');
      return;
    }
    set('caKpiActive', active.length, active.length ? 'running or awaiting approval' : 'nothing in flight');
    set('caKpiCompleted', completed.length, runs.length ? 'of ' + runs.length + ' recent runs' : 'no runs yet');
    set('caKpiAgents', roles.size, roles.size ? 'roles in active runs' : 'no active runs');
    set('caKpiSuccess', finished ? Math.round((completed.length / finished) * 100) + '%' : '—',
      finished ? completed.length + ' completed / ' + finished + ' finished' : 'no finished runs');
  }

  /* ---------------- charts ---------------- */
  function renderExecutionChart() {
    const host = el('caExecutionChart');
    if (!host) return;
    if (state.errors.runs) return error(host, state.errors.runs);
    if (!state.runs.length) return empty(host, 'No runs yet. Submit a task below and this chart fills from real step records.');

    const recent = state.runs.slice(0, 12).reverse();
    const counts = recent.map((run) => (run.steps || []).length);
    const max = Math.max(1, ...counts);
    const W = 560; const H = 150; const L = 26; const R = 12; const T = 14; const B = 22;
    const spanX = W - L - R;
    const spanY = H - T - B;
    const x = (index) => (counts.length === 1 ? L + spanX / 2 : L + (spanX * index) / (counts.length - 1));
    const y = (value) => T + spanY * (1 - value / max);

    const root = svg('svg', { viewBox: '0 0 ' + W + ' ' + H, role: 'img' });
    const defs = svg('defs');
    const fill = svg('linearGradient', { id: 'caExecFill', x1: '0', y1: '0', x2: '0', y2: '1' });
    fill.append(svg('stop', { offset: '0%', 'stop-color': '#8b5cff', 'stop-opacity': '.55' }));
    fill.append(svg('stop', { offset: '100%', 'stop-color': '#8b5cff', 'stop-opacity': '0' }));
    const line = svg('linearGradient', { id: 'caExecLine', x1: '0', y1: '0', x2: '1', y2: '0' });
    line.append(svg('stop', { offset: '0%', 'stop-color': '#7a5cff' }));
    line.append(svg('stop', { offset: '100%', 'stop-color': '#4ce0ff' }));
    defs.append(fill, line);
    root.append(defs);

    for (let step = 0; step <= 3; step += 1) {
      const value = (max / 3) * step;
      const gy = y(value);
      root.append(svg('line', { x1: L, y1: gy, x2: W - R, y2: gy, stroke: 'rgba(255,255,255,.07)', 'stroke-width': '1' }));
      svgText(root, L - 6, gy + 3, Math.round(value), 'ca-axis', 'end');
    }

    const points = counts.map((value, index) => [x(index), y(value)]);
    const area = 'M' + points[0][0] + ',' + (H - B) + ' ' +
      points.map((point) => 'L' + point[0] + ',' + point[1]).join(' ') +
      ' L' + points[points.length - 1][0] + ',' + (H - B) + ' Z';
    root.append(svg('path', { d: area, fill: 'url(#caExecFill)' }));
    root.append(svg('path', {
      d: 'M' + points.map((point) => point[0] + ',' + point[1]).join(' L'),
      fill: 'none', stroke: 'url(#caExecLine)', 'stroke-width': '2.2', 'stroke-linejoin': 'round',
    }));
    points.forEach((point, index) => {
      root.append(svg('circle', {
        cx: point[0], cy: point[1], r: '3.2', fill: '#0b0918', stroke: '#b28bff', 'stroke-width': '2',
      }));
      svgText(root, point[0], H - 6, counts[index], 'ca-axis');
    });
    host.replaceChildren(root);
  }

  function renderWorkloadChart() {
    const host = el('caWorkloadChart');
    if (!host) return;
    if (state.errors.runs) return error(host, state.errors.runs);
    if (!state.runs.length) return empty(host, 'No delegated work yet. Workload appears once Core records runs.');

    const counts = {};
    state.runs.forEach((run) => {
      const key = run.role || 'orchestrator';
      counts[key] = (counts[key] || 0) + 1;
    });
    const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 7);
    const max = Math.max(1, ...entries.map((entry) => entry[1]));
    const W = 380; const H = 150; const L = 10; const R = 10; const T = 12; const B = 30;
    const slot = (W - L - R) / entries.length;
    const barWidth = Math.min(30, slot * 0.55);

    const root = svg('svg', { viewBox: '0 0 ' + W + ' ' + H, role: 'img' });
    const defs = svg('defs');
    const gradient = svg('linearGradient', { id: 'caWorkFill', x1: '0', y1: '1', x2: '0', y2: '0' });
    gradient.append(svg('stop', { offset: '0%', 'stop-color': '#3f2a8f' }));
    gradient.append(svg('stop', { offset: '100%', 'stop-color': '#8f6bff' }));
    defs.append(gradient);
    root.append(defs);

    entries.forEach(([role, count], index) => {
      const height = ((H - T - B) * count) / max;
      const bx = L + slot * index + (slot - barWidth) / 2;
      root.append(svg('rect', {
        x: bx, y: H - B - height, width: barWidth, height: Math.max(3, height),
        rx: '5', fill: 'url(#caWorkFill)', opacity: '0.95',
      }));
      svgText(root, bx + barWidth / 2, H - B - height - 4, count, 'ca-axis');
      const label = roleLabel(role);
      svgText(root, bx + barWidth / 2, H - 12, label.length > 11 ? label.slice(0, 10) + '…' : label, 'ca-bar-label');
    });
    host.replaceChildren(root);
  }

  /* ---------------- current task ---------------- */
  function runChips() {
    const host = el('caRunChips');
    if (!host) return;
    host.replaceChildren();
    if (!state.runs.length) return;
    state.runs.slice(0, 6).forEach((run, index) => {
      const chip = text('button', '#' + (index + 1), 'ca-chip' + (run.run_id === state.selected ? ' is-active' : ''));
      chip.type = 'button';
      chip.title = (statusLabel(run.status) + ' · ' + run.goal).slice(0, 240);
      chip.setAttribute('aria-label', 'Show run ' + (index + 1) + ': ' + statusLabel(run.status));
      chip.onclick = () => { state.selected = run.run_id; render(); };
      host.append(chip);
    });
  }

  function ring(percent) {
    const wrapper = document.createElement('div');
    wrapper.className = 'ca-ring';
    const root = svg('svg', { viewBox: '0 0 104 104', role: 'img', 'aria-label': 'Plan progress' });
    const defs = svg('defs');
    const gradient = svg('linearGradient', { id: 'caRingGrad', x1: '0', y1: '0', x2: '1', y2: '1' });
    gradient.append(svg('stop', { offset: '0%', 'stop-color': '#8f6bff' }));
    gradient.append(svg('stop', { offset: '100%', 'stop-color': '#4ce0ff' }));
    defs.append(gradient);
    root.append(defs);
    const radius = 44;
    const circumference = 2 * Math.PI * radius;
    root.append(svg('circle', { class: 'ca-ring-track', cx: '52', cy: '52', r: String(radius), fill: 'none', 'stroke-width': '9' }));
    if (percent !== null) {
      root.append(svg('circle', {
        class: 'ca-ring-value', cx: '52', cy: '52', r: String(radius), fill: 'none', 'stroke-width': '9',
        'stroke-dasharray': (circumference * percent) / 100 + ' ' + circumference,
      }));
    }
    const center = document.createElement('div');
    center.className = 'ca-ring-text';
    center.append(text('b', percent === null ? '—' : percent + '%'));
    center.append(text('small', 'plan'));
    wrapper.append(root, center);
    return wrapper;
  }

  function renderCurrentTask() {
    const host = el('caCurrentTask');
    if (!host) return;
    if (state.errors.runs) return error(host, state.errors.runs);
    const run = state.runs.find((item) => item.run_id === state.selected);
    if (!run) return empty(host, 'No active task. Submit a mission below to start a Core run.');

    const planned = Array.isArray(run.plan?.steps) ? run.plan.steps : [];
    const executed = Array.isArray(run.steps) ? run.steps : [];
    const percent = planned.length ? Math.min(100, Math.round((executed.length / planned.length) * 100)) : null;

    const body = document.createElement('div');
    body.className = 'ca-task-body';
    body.append(text('p', run.goal, 'ca-task-goal'));

    const meta = document.createElement('div');
    meta.className = 'ca-task-meta';
    meta.append(text('span', statusLabel(run.status), 'ca-tag ca-tag--' + String(run.status || 'unknown')));
    meta.append(text('span', roleLabel(run.role), 'ca-tag'));
    if (executed.length || planned.length) {
      meta.append(text('span', executed.length + ' / ' + planned.length + ' steps', 'ca-tag'));
    }
    if (run.attempt) meta.append(text('span', 'attempt ' + run.attempt, 'ca-tag'));
    body.append(meta);

    if (planned.length) {
      const list = document.createElement('ol');
      list.className = 'ca-plan';
      planned.forEach((step, index) => {
        const record = executed.find((item) => item.index === index) || executed[index];
        const cls = record ? (record.ok ? 'is-done' : 'is-failed') : 'is-pending';
        const suffix = record ? (record.ok ? ' · ok' : ' · failed') : ' · pending';
        const ms = record && record.duration_ms ? ' · ' + record.duration_ms + ' ms' : '';
        list.append(text('li', step.tool + suffix + ms, cls));
      });
      body.append(list);
    }

    if (percent !== null) {
      const bar = document.createElement('div');
      bar.className = 'ca-progress';
      const fill = document.createElement('span');
      fill.style.width = percent + '%';
      bar.append(fill);
      body.append(bar);
    }

    if (run.status === 'awaiting_approval' && run.approval) {
      const box = document.createElement('div');
      box.className = 'ca-approval';
      box.append(text('b', 'Permission required: ' + run.approval.permission));
      box.append(text('p', 'JARVIS wants to run: ' + run.approval.tool));
      const args = document.createElement('pre');
      args.textContent = JSON.stringify(run.approval.args, null, 2);
      box.append(args);
      const actions = document.createElement('div');
      actions.className = 'ca-actions';
      const approve = text('button', 'APPROVE THIS STEP', 'ca-btn ca-btn--approve');
      approve.type = 'button';
      approve.onclick = async () => {
        if (!confirm('Approve this exact JARVIS Core tool step?')) return;
        approve.disabled = true;
        try { await call('/api/core/runs/' + run.run_id + '/approve', {}); await load(); }
        catch (err) { alert(err.message); approve.disabled = false; }
      };
      const reject = text('button', 'REJECT RUN', 'ca-btn ca-btn--reject');
      reject.type = 'button';
      reject.onclick = async () => {
        if (!confirm('Reject this step and stop the run?')) return;
        reject.disabled = true;
        try { await call('/api/core/runs/' + run.run_id + '/reject', {}); await load(); }
        catch (err) { alert(err.message); reject.disabled = false; }
      };
      actions.append(approve, reject);
      box.append(actions);
      body.append(box);
    } else if (run.status === 'running') {
      const cancel = text('button', 'CANCEL RUN', 'ca-btn');
      cancel.type = 'button';
      cancel.onclick = async () => {
        if (!confirm('Cancel this JARVIS Core run?')) return;
        cancel.disabled = true;
        try { await call('/api/core/runs/' + run.run_id + '/cancel', {}); await load(); }
        catch (err) { alert(err.message); cancel.disabled = false; }
      };
      body.append(cancel);
    }

    if (run.answer) body.append(text('p', run.answer, 'ca-task-goal'));
    if (run.error) body.append(text('p', run.error, 'ca-error'));

    host.replaceChildren(ring(percent), body);
  }

  /* ---------------- agents ---------------- */
  function renderAgents() {
    const host = el('caDelegatedAgents');
    const hint = el('caAgentsHint');
    if (!host) return;
    if (state.errors.agents) return error(host, state.errors.agents);
    const specialists = state.agents.filter((agent) => agent.id !== 'orchestrator');
    if (!specialists.length) return empty(host, 'No specialist roster returned by Core.');

    const delegated = new Set(state.runs.map((run) => run.role).filter(Boolean));
    if (hint) hint.textContent = delegated.size + ' delegated recently';

    const rows = specialists.slice().sort((a, b) => {
      const sa = (delegated.has(a.id) ? 0 : 1) * 2 + (a.status === 'connected' ? 0 : 1);
      const sb = (delegated.has(b.id) ? 0 : 1) * 2 + (b.status === 'connected' ? 0 : 1);
      return sa - sb || String(a.name).localeCompare(String(b.name));
    });
    host.replaceChildren(...rows.map((agent) => {
      const row = document.createElement('div');
      row.className = 'ca-agent-row' + (delegated.has(agent.id) ? ' is-delegated' : '');
      row.title = agent.status_detail || agent.backend || '';
      row.append(text('span', agent.name, 'ca-agent-name'));
      const status = document.createElement('span');
      status.className = 'ca-agent-state ca-agent-state--' + (agent.status || 'idle');
      status.append(document.createElement('i'));
      status.append(document.createTextNode(agent.status || 'unknown'));
      row.append(status);
      return row;
    }));
  }

  /* ---------------- health ---------------- */
  function renderHealth() {
    const host = el('caSystemHealth');
    if (!host) return;
    const health = state.health || {};
    const core = health.agent_core || {};
    const connected = state.agents.filter((agent) => agent.status === 'connected').length;
    const rows = [];

    const row = (label, value, ratio, tone) => {
      const wrapper = document.createElement('div');
      wrapper.className = 'ca-health-row';
      wrapper.append(text('span', label), text('b', value));
      if (typeof ratio === 'number') {
        const bar = document.createElement('div');
        bar.className = 'ca-health-bar' + (tone ? ' ' + tone : '');
        const fill = document.createElement('span');
        fill.style.width = Math.max(0, Math.min(100, ratio)) + '%';
        bar.append(fill);
        wrapper.append(bar);
      }
      rows.push(wrapper);
    };

    row('Core engine', state.errors.runs ? 'unreachable' : 'online');
    if (state.errors.health) row('Model runtime', 'unverified');
    else row('Model', health.model || 'unknown', null, '');
    if (core.database !== undefined) row('Database', core.database ? 'ok' : 'degraded', null, core.database ? '' : 'is-bad');
    if (state.agents.length) {
      row('Agents connected', connected + ' / ' + state.agents.length, (connected / state.agents.length) * 100,
        connected === 0 ? 'is-bad' : connected < state.agents.length ? 'is-warn' : '');
    } else {
      row('Agents connected', 'unverified');
    }
    row('Registered tools', state.errors.tools ? 'unverified' : String(state.tools.length));
    if (health.memory_count !== undefined) row('Memories', String(health.memory_count));

    host.replaceChildren(...rows);
  }

  /* ---------------- log ---------------- */
  function renderLog() {
    const host = el('caExecutionLog');
    if (!host) return;
    if (state.errors.runs) return error(host, state.errors.runs);
    const run = state.runs.find((item) => item.run_id === state.selected);
    if (!run) return empty(host, 'No Core run selected. The log fills from real step records.');

    const rows = [];
    const add = (textValue, kind, mark) => {
      rows.push({ text: textValue, kind: kind || '', mark: mark || '' });
    };

    add('Run status: ' + statusLabel(run.status), 'is-run', run.status === 'failed' ? '×' : '•');
    if (run.role) add('Routed to ' + roleLabel(run.role), 'is-run', '•');
    const planned = Array.isArray(run.plan?.steps) ? run.plan.steps : [];
    if (planned.length) add('Plan ready · ' + planned.length + ' step(s)', 'is-run', '•');
    const executed = Array.isArray(run.steps) ? run.steps : [];
    executed.forEach((step, index) => {
      const ms = step.duration_ms ? ' · ' + step.duration_ms + ' ms' : '';
      add('#' + (index + 1) + ' ' + step.tool + (step.ok ? ' · ok' : ' · failed') + ms,
        step.ok ? '' : 'is-failed', step.ok ? '✓' : '✕');
    });
    planned.forEach((step, index) => {
      if (executed.some((record) => record.index === index) || executed[index]) return;
      add('#' + (index + 1) + ' ' + step.tool + ' · pending', 'is-pending', '○');
    });
    if (run.approval) add('Waiting for approval: ' + run.approval.tool, 'is-pending', '○');
    if (run.answer) add('Answer: ' + String(run.answer).slice(0, 220), 'is-run', '✓');
    if (run.error) add('Error: ' + String(run.error).slice(0, 220), 'is-failed', '✕');

    host.replaceChildren(...rows.map((entry, index) => {
      const row = document.createElement('div');
      row.className = 'ca-log-row ' + entry.kind;
      row.append(text('span', String(index + 1).padStart(2, '0'), 'ca-log-seq'));
      const body = document.createElement('span');
      body.className = 'ca-log-text';
      body.textContent = entry.text;
      row.append(body);
      row.append(text('span', entry.mark, 'ca-log-mark'));
      return row;
    }));
  }

  /* ---------------- tools ---------------- */
  function renderTools() {
    const host = el('caTools');
    const hint = el('caToolsHint');
    if (!host) return;
    if (state.errors.tools) return error(host, state.errors.tools);
    const counts = {};
    state.runs.forEach((run) => (run.steps || []).forEach((step) => {
      counts[step.tool] = (counts[step.tool] || 0) + 1;
    }));
    const used = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 14);
    if (hint) hint.textContent = used.length ? used.length + ' used · ' + state.tools.length + ' registered' : state.tools.length + ' registered';

    if (!used.length) {
      return empty(host, state.tools.length
        ? 'No tool has executed yet in the recent runs. ' + state.tools.length + ' tools are registered and permitted by Core.'
        : 'No tools reported by Core.');
    }
    const permissions = {};
    state.tools.forEach((tool) => { permissions[tool.name] = tool.permission; });
    host.replaceChildren(...used.map(([name, count]) => {
      const permission = permissions[name] || '';
      const chip = document.createElement('span');
      chip.className = 'ca-tool' + (permission === 'confirm' ? ' ca-tool--confirm' : '');
      chip.title = (permission ? permission + ' · ' : '') + count + ' call(s) in recent runs';
      chip.append(text('b', name));
      chip.append(text('span', '×' + count));
      return chip;
    }));
  }

  function render() {
    renderKpis();
    renderExecutionChart();
    renderWorkloadChart();
    runChips();
    renderCurrentTask();
    renderAgents();
    renderHealth();
    renderLog();
    renderTools();
  }

  /* ---------------- mission form ---------------- */
  const form = el('coreRunForm');
  if (form) {
    form.onsubmit = async (event) => {
      event.preventDefault();
      const input = el('coreGoal');
      const button = el('coreRunSubmit');
      const goal = input ? input.value.trim() : '';
      if (!goal) return;
      if (button) { button.disabled = true; }
      setStatus('partial', 'Planning…');
      try {
        const run = await call('/api/core/runs', { goal });
        if (input) input.value = '';
        state.selected = run.run_id || state.selected;
        await load();
        setStatus(run.status === 'awaiting_approval' ? 'partial' : run.status === 'completed' ? 'online' : 'partial',
          run.status === 'awaiting_approval' ? 'Approval required · review the pending step'
            : run.status === 'completed' ? 'Run completed' : 'Run status: ' + statusLabel(run.status));
      } catch (err) {
        setStatus('offline', err.message);
        alert(err.message);
        await load();
      } finally {
        if (button) { button.disabled = false; }
      }
    };
  }

  /* ---------------- execution modes ---------------- */
  const MODE_IDS = { caModeAutonomous: 'autonomous', caModeSupervised: 'supervised', caModeManual: 'manual' };
  const modeNote = (text) => { const target = el('caModeNote'); if (target) target.textContent = text || ''; };

  const renderMode = (state) => {
    if (!state || !state.mode) return;
    Object.entries(MODE_IDS).forEach(([id, value]) => {
      const button = el(id);
      if (!button) return;
      const active = state.mode === value;
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-checked', active ? 'true' : 'false');
      button.removeAttribute('aria-disabled');
      const option = (state.available || []).find((item) => item.id === value);
      const small = button.querySelector('small');
      if (small && option && option.detail) small.textContent = option.detail;
    });
    if (state.detail) modeNote(state.detail);
  };

  const loadMode = async () => {
    try {
      const response = await fetch('/api/core/agent/mode');
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || data.detail || `Core returned ${response.status}`);
      renderMode(data);
    } catch (err) {
      modeNote('Execution mode unknown: ' + err.message);
    }
  };

  const setMode = async (mode, button) => {
    if (button) button.disabled = true;
    try {
      const response = await fetch('/api/core/agent/mode', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || data.detail || `Core refused the change (${response.status})`);
      renderMode(data);
    } catch (err) {
      modeNote('Could not switch to ' + mode + ': ' + err.message);
    } finally {
      if (button) button.disabled = false;
    }
  };

  Object.entries(MODE_IDS).forEach(([id, value]) => {
    const button = el(id);
    if (button) button.onclick = () => setMode(value, button);
  });
  loadMode();

  /* ---------------- controls ---------------- */
  const settingsButton = el('caSettings');
  if (settingsButton) {
    settingsButton.onclick = () => {
      panel.classList.add('hidden');
      el('settings')?.classList.remove('hidden');
    };
  }
  const closeButton = el('closeCoreAgent');
  if (closeButton) closeButton.onclick = () => panel.classList.add('hidden');
  const refreshButton = el('refreshCoreRuns');
  if (refreshButton) refreshButton.onclick = () => load();

  const micButton = el('caMic');
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (micButton) {
    if (!Recognition) {
      micButton.disabled = true;
      micButton.title = 'Dictation requires Chrome or Edge';
    } else {
      micButton.onclick = () => {
        const input = el('coreGoal');
        const recogniser = new Recognition();
        recogniser.lang = 'en-US';
        recogniser.interimResults = false;
        recogniser.maxAlternatives = 1;
        micButton.classList.add('is-listening');
        recogniser.onresult = (event) => {
          const phrase = event.results?.[0]?.[0]?.transcript || '';
          if (input && phrase) input.value = (input.value ? input.value + ' ' : '') + phrase.trim();
        };
        recogniser.onend = () => micButton.classList.remove('is-listening');
        recogniser.onerror = () => micButton.classList.remove('is-listening');
        try { recogniser.start(); } catch { micButton.classList.remove('is-listening'); }
      };
    }
  }

  /* ---------------- live refresh while open ---------------- */
  window.refreshCoreRuns = load;
  const tick = () => {
    if (!panel.classList.contains('hidden')) load();
  };
  setInterval(tick, 5000);
  document.getElementById('coreAgentBtn')?.addEventListener('click', () => load());
})();
