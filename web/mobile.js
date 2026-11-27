(() => {
  const $ = (selector) => document.querySelector(selector);
  const messages = [];
  let busy = false;
  let pendingClose = null;
  let voiceOn = localStorage.getItem('jarvis.mobile.voice') !== 'off';
  let currentTab = 'chat';
  let seenRuns = null;
  let audio = null;

  const el = (tag, value, cls) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (value !== undefined && value !== null) node.textContent = String(value);
    return node;
  };

  function toast(message) {
    const node = $('#toast');
    if (!node) return;
    node.textContent = message;
    node.hidden = false;
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => { node.hidden = true; }, 5000);
    if ('Notification' in window && Notification.permission === 'granted') {
      try { new Notification('JARVIS', { body: message, tag: 'jarvis-run' }); } catch { /* iOS needs an installed web app */ }
    }
  }

  async function api(url, body) {
    const response = await fetch(url, {
      method: body === undefined ? 'GET' : 'POST',
      headers: { 'Content-Type': 'application/json' },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    const data = await response.json().catch(() => ({ error: 'Invalid response from JARVIS' }));
    if (!response.ok && !(response.status === 409 && data.status === 'awaiting_approval')) {
      throw new Error(data.error || data.detail || 'Request failed');
    }
    return data;
  }

  /* ---------------- chat ---------------- */
  function bubble(role, text) {
    const box = $('#messages');
    box.append(el('div', text, 'bubble ' + role));
    box.scrollTop = box.scrollHeight;
  }

  async function speak(text) {
    const clean = String(text || '').trim();
    if (!clean || !voiceOn) return;
    if (audio) { try { audio.pause(); } catch { /* already stopped */ } audio = null; }
    if ('speechSynthesis' in window) speechSynthesis.cancel();
    try {
      const response = await fetch('/api/voice/speak', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: clean, voice: 'af_bella' }),
      });
      if (!response.ok) throw new Error('voice unavailable');
      const blob = await response.blob();
      audio = new Audio(URL.createObjectURL(blob));
      await audio.play();
      return;
    } catch {
      if (!('speechSynthesis' in window)) return;
      const utterance = new SpeechSynthesisUtterance(clean);
      utterance.lang = 'en-US';
      speechSynthesis.speak(utterance);
    }
  }

  async function health() {
    try {
      const data = await api('/api/health');
      $('#dot').style.background = data.lm_studio || data.ollama ? '#63e3b1' : '#e4b86d';
      $('#status').textContent = data.lm_studio || data.ollama ? 'AI CONNECTED' : 'MODEL OFFLINE';
      $('#model').textContent = 'MODEL · ' + (data.model || 'UNKNOWN');
    } catch {
      $('#status').textContent = 'SERVER OFFLINE';
      $('#model').textContent = 'LOCAL AI · UNAVAILABLE';
    }
  }

  function normalizeCommand(value) {
    return String(value || '').trim().toLowerCase().replace(/[?!.,;:]+$/g, '').replace(/\s+/g, ' ');
  }

  async function runLocalCommand(text) {
    const query = normalizeCommand(text);
    if (/^(what apps are running|what applications are running|show running apps|list running apps|running apps)$/.test(query)) {
      const data = await api('/api/running');
      const names = [...new Set((data.apps || []).map((item) => item.name).filter(Boolean))].sort();
      return names.length
        ? 'These applications have visible windows open: ' + names.join(', ') + '.'
        : "I couldn't find any applications with visible windows open.";
    }
    if (/^(what is the weather|what's the weather|weather|weather in zaragoza|what's the weather in zaragoza|what is the weather in zaragoza)$/.test(query)) {
      const data = await api('/api/weather');
      return 'Current weather in ' + data.location + ': ' + data.temperature + '°C, ' + data.condition + '. Feels like ' + data.feels_like + '°C. Humidity ' + data.humidity + '%, wind ' + data.wind_kmh + ' km/h.';
    }
    if (/^(what time is it|what time is it in zaragoza|time|current time)$/.test(query)) {
      const data = await api('/api/time');
      return 'The current time in Zaragoza is ' + new Intl.DateTimeFormat('en-US', { timeZone: 'Europe/Madrid', hour: 'numeric', minute: '2-digit', hour12: true }).format(new Date(data.time)) + '.';
    }
    if (/^(show my reminders|show reminders|list reminders|my reminders|reminders)$/.test(query)) {
      const data = await api('/api/reminders');
      const items = data.reminders || [];
      if (!items.length) return "You don't have any reminders saved yet.";
      return 'Your reminders: ' + items.map((item) => (item.done ? 'Completed: ' : 'Pending: ') + item.task + (item.due ? ' ( ' + item.due + ' )' : '')).join('; ') + '.';
    }
    return null;
  }

  async function send(raw) {
    const text = String(raw || '').trim();
    if (!text || busy) return;
    busy = true;
    $('#prompt').value = '';
    bubble('user', text);
    messages.push({ role: 'user', content: text });
    $('#state').textContent = 'THINKING';
    try {
      let answer = null;
      let match;
      if (pendingClose) {
        if (/^(yes|confirm|do it|close it)$/i.test(normalizeCommand(text))) {
          const app = pendingClose;
          pendingClose = null;
          const data = await api('/api/desktop/close', { app, confirm: true });
          answer = data.message;
        } else if (/^(no|cancel|stop)$/i.test(normalizeCommand(text))) {
          pendingClose = null;
          answer = "Okay, I'll leave it open.";
        } else {
          answer = 'Please reply YES to confirm closing ' + pendingClose + ', or NO to cancel.';
        }
      }
      if (!answer && (match = text.match(/^(?:open|launch|start|run)\s+(.+?)[.!?]*$/i))) {
        const data = await api('/api/desktop/open', { app: match[1].trim() });
        answer = 'Opening ' + data.app + '.';
      }
      if (!answer && (match = text.match(/^(?:close|quit|exit)\s+(.+?)[.!?]*$/i))) {
        pendingClose = match[1].replace(/\s+app$/i, '').trim();
        answer = 'Do you want me to close ' + pendingClose + '? Reply YES to confirm or NO to cancel. Save your work first.';
      }
      if (!answer) answer = await runLocalCommand(text);
      if (!answer) {
        const data = await api('/api/chat', { messages });
        answer = data.reply;
      }
      messages.push({ role: 'assistant', content: answer });
      bubble('assistant', answer);
      speak(answer);
    } catch (error) {
      bubble('assistant', "I couldn't complete that: " + error.message);
    } finally {
      busy = false;
      $('#state').textContent = 'SYSTEM STANDBY';
    }
  }

  /* ---------------- tabs ---------------- */
  function showTab(name) {
    currentTab = name;
    document.querySelectorAll('.view').forEach((view) => {
      view.classList.toggle('is-active', view.id === 'view-' + name);
    });
    document.querySelectorAll('.tab').forEach((tab) => {
      const active = tab.dataset.tab === name;
      tab.classList.toggle('is-active', active);
      if (active) tab.setAttribute('aria-current', 'page');
      else tab.removeAttribute('aria-current');
    });
    if (name === 'agents') refreshRuns();
    if (name === 'files') refreshReports();
    if (name === 'line') refreshLine();
  }

  /* ---------------- agents ---------------- */
  function pill(status) {
    return el('span', String(status || 'unknown').replace(/_/g, ' '), 'pill ' + status);
  }

  function runCard(run) {
    const card = el('div', undefined, 'run');
    const head = el('div', undefined, 'run-head');
    head.append(pill(run.status));
    head.append(el('small', (run.role || 'orchestrator').replace(/-/g, ' '), 'run-meta'));
    card.append(head);
    card.append(el('p', run.goal, 'run-goal'));

    const planned = run.plan && Array.isArray(run.plan.steps) ? run.plan.steps.length : 0;
    const executed = Array.isArray(run.steps) ? run.steps.length : 0;
    if (planned) {
      const bar = el('div', undefined, 'bar');
      const fill = el('span');
      fill.style.width = Math.min(100, Math.round((executed / planned) * 100)) + '%';
      bar.append(fill);
      card.append(bar);
      card.append(el('div', executed + ' of ' + planned + ' steps executed', 'run-meta'));
    }
    if (run.answer) card.append(el('p', String(run.answer).slice(0, 400), 'run-goal'));
    if (run.error) card.append(el('p', String(run.error).slice(0, 240), 'run-goal bad'));

    if (run.status === 'awaiting_approval' && run.approval) {
      const actions = el('div', undefined, 'run-actions');
      const approve = el('button', 'APPROVE ' + run.approval.tool, 'approve');
      approve.onclick = async () => {
        if (!confirm('Approve this exact Core tool step?')) return;
        approve.disabled = true;
        try { await api('/api/core/runs/' + run.run_id + '/approve', {}); await refreshRuns(); }
        catch (error) { toast(error.message); approve.disabled = false; }
      };
      const reject = el('button', 'REJECT', 'reject');
      reject.onclick = async () => {
        if (!confirm('Reject this step and stop the run?')) return;
        reject.disabled = true;
        try { await api('/api/core/runs/' + run.run_id + '/reject', {}); await refreshRuns(); }
        catch (error) { toast(error.message); reject.disabled = false; }
      };
      actions.append(approve, reject);
      card.append(actions);
    } else if (run.status === 'running') {
      const actions = el('div', undefined, 'run-actions');
      const cancel = el('button', 'CANCEL RUN');
      cancel.onclick = async () => {
        if (!confirm('Cancel this Core run?')) return;
        cancel.disabled = true;
        try { await api('/api/core/runs/' + run.run_id + '/cancel', {}); await refreshRuns(); }
        catch (error) { toast(error.message); cancel.disabled = false; }
      };
      actions.append(cancel);
      card.append(actions);
    }
    return card;
  }

  async function refreshRuns() {
    const host = $('#runList');
    try {
      const data = await api('/api/core/runs');
      const runs = Array.isArray(data.runs) ? data.runs : [];
      notifyTransitions(runs);
      host.replaceChildren();
      if (!runs.length) {
        host.append(el('p', 'No agent runs yet. Delegate a task above to start one.', 'note'));
      } else {
        runs.slice(0, 6).forEach((run) => host.append(runCard(run)));
      }
    } catch (error) {
      host.replaceChildren(el('p', error.message, 'note bad'));
    }
  }

  function notifyTransitions(runs) {
    if (seenRuns) {
      runs.forEach((run) => {
        const before = seenRuns[run.run_id];
        if (before && before !== run.status && (run.status === 'completed' || run.status === 'failed')) {
          toast(run.status === 'completed' ? 'Task completed: ' + String(run.goal).slice(0, 70) : 'Task failed: ' + String(run.goal).slice(0, 70));
        }
      });
    }
    seenRuns = Object.fromEntries(runs.map((run) => [run.run_id, run.status]));
  }

  async function refreshAgents() {
    const host = $('#agentList');
    try {
      const data = await api('/api/core/agents');
      const agents = (Array.isArray(data.agents) ? data.agents : []).filter((agent) => agent.id !== 'orchestrator');
      host.replaceChildren();
      if (!agents.length) { host.append(el('p', 'No agent roster returned by Core.', 'note')); return; }
      agents.forEach((agent) => {
        const row = el('div', undefined, 'row');
        row.append(el('span', agent.name, 'name'));
        const state = el('span', agent.status || 'unknown', 'state-dot ' + (agent.status || 'idle'));
        state.prepend(el('i'));
        row.append(state);
        host.append(row);
      });
    } catch (error) {
      host.replaceChildren(el('p', error.message, 'note bad'));
    }
  }

  async function delegate(goal) {
    const button = $('#delegate button');
    button.disabled = true;
    try {
      await api('/api/core/runs', { goal });
      $('#goal').value = '';
      toast('Task accepted by JARVIS Core.');
      await refreshRuns();
    } catch (error) {
      toast(error.message);
    } finally {
      button.disabled = false;
    }
  }

  /* ---------------- files ---------------- */
  async function refreshReports() {
    const host = $('#reportList');
    try {
      const data = await api('/api/reports');
      const reports = Array.isArray(data.reports) ? data.reports : [];
      host.replaceChildren();
      if (!reports.length) { host.append(el('p', 'No reports yet. Ask JARVIS to generate one.', 'note')); return; }
      reports.forEach((report) => {
        const row = el('div', undefined, 'row file-row');
        const link = el('a', report.name);
        link.href = '/api/reports/' + encodeURIComponent(report.name);
        link.target = '_blank';
        link.rel = 'noopener';
        row.append(link, el('small', Math.max(1, Math.round(report.size / 1024)) + ' KB'));
        host.append(row);
      });
    } catch (error) {
      host.replaceChildren(el('p', error.message, 'note bad'));
    }
  }

  function renderFiles(host, files) {
    host.replaceChildren();
    if (!files.length) { host.append(el('p', 'No matching files.', 'note')); return; }
    files.slice(0, 20).forEach((file) => host.append(el('div', file, 'row file-row')));
  }

  async function searchFiles(query, host) {
    if (!query.trim()) return;
    try {
      const data = await api('/api/files/search', { query: query.trim() });
      renderFiles(host, Array.isArray(data.files) ? data.files.map((file) => String(file)) : []);
    } catch (error) {
      host.replaceChildren(el('p', error.message, 'note bad'));
    }
  }

  /* ---------------- phone line ---------------- */
  async function refreshLine() {
    const host = $('#lineCard');
    try {
      const data = await api('/api/core/telephony');
      host.replaceChildren();
      host.classList.remove('muted');
      const rows = [
        ['Provider', data.provider || 'none'],
        ['Status', data.configured ? 'ready to receive calls' : 'not configured'],
        ['Voice', (data.voice || '—') + ' · ' + (data.language || '—')],
        ['Authorised callers', String(data.authorised_callers ?? 0)],
      ];
      rows.forEach(([key, value]) => {
        const row = el('div', undefined, 'kv');
        row.append(el('span', key), el('b', value, data.configured ? 'ok' : ''));
        host.append(row);
      });
      if (Array.isArray(data.missing) && data.missing.length) {
        host.append(el('p', 'Missing: ' + data.missing.join(', '), 'note warn'));
      }
    } catch (error) {
      host.replaceChildren(el('p', error.message, 'note bad'));
    }
  }

  /* ---------------- wiring ---------------- */
  $('#chat').addEventListener('submit', (event) => { event.preventDefault(); send($('#prompt').value); });
  $('#clear').onclick = () => {
    messages.length = 0;
    $('#messages').replaceChildren();
    bubble('assistant', 'Conversation cleared.');
  };
  document.querySelectorAll('[data-command]').forEach((button) => {
    button.onclick = () => send(button.dataset.command);
  });
  $('#open').onclick = () => { const value = $('#appName').value.trim(); if (value) send('open ' + value); };
  $('#close').onclick = () => { const value = $('#closeName').value.trim(); if (value) send('close ' + value); };
  $('#typeSend').onclick = async () => {
    const text = $('#typeText').value;
    if (!text) return;
    try {
      const data = await api('/api/computer/action', { action: 'type', text });
      toast('Typed ' + (data.characters || text.length) + ' characters into the active window.');
    } catch (error) { toast(error.message); }
  };
  $('#inspect').onclick = async () => {
    const host = $('#inspectResult');
    try {
      const data = await api('/api/computer/inspect');
      host.classList.remove('muted');
      const controls = (data.controls || []).slice(0, 12).map((item) => item.type + ' ' + item.name);
      host.textContent = data.window ? 'Active window: ' + data.window + (controls.length ? ' · ' + controls.join('; ') : '') : 'No active window detected.';
    } catch (error) { host.textContent = error.message; }
  };
  $('#runSearchGo').onclick = () => searchFiles($('#runSearch').value, $('#runSearchResult'));
  $('#fileForm').addEventListener('submit', (event) => { event.preventDefault(); searchFiles($('#fileQuery').value, $('#fileResults')); });
  $('#refreshAgents').onclick = () => { refreshRuns(); refreshAgents(); };
  $('#refreshReports').onclick = refreshReports;
  $('#refreshLine').onclick = refreshLine;
  $('#delegate').addEventListener('submit', (event) => {
    event.preventDefault();
    const goal = $('#goal').value.trim();
    if (goal.length >= 8) delegate(goal);
    else toast('Describe the task in at least 8 characters.');
  });
  $('#speakToggle').onclick = () => {
    voiceOn = !voiceOn;
    localStorage.setItem('jarvis.mobile.voice', voiceOn ? 'on' : 'off');
    $('#speakToggle').textContent = voiceOn ? 'VOICE REPLIES ON' : 'VOICE REPLIES OFF';
    $('#speakToggle').setAttribute('aria-pressed', String(voiceOn));
  };
  if (!('Notification' in window)) $('#refreshAgents').title = 'Notifications need an installed web app on iOS';
  document.querySelectorAll('.tab').forEach((tab) => { tab.onclick = () => showTab(tab.dataset.tab); });

  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  $('#voice').onclick = () => {
    if (!Recognition) {
      bubble('assistant', "Voice input isn't supported in this browser. Use the message box; spoken replies are still available.");
      return;
    }
    const recogniser = new Recognition();
    recogniser.lang = 'en-US';
    recogniser.interimResults = false;
    recogniser.onstart = () => { $('#state').textContent = 'LISTENING'; $('#voice').classList.add('listening'); };
    recogniser.onresult = (event) => send(event.results[0][0].transcript);
    recogniser.onerror = (event) => bubble('assistant', 'Microphone issue: ' + event.error);
    recogniser.onend = () => { $('#voice').classList.remove('listening'); if (!busy) $('#state').textContent = 'SYSTEM STANDBY'; };
    try { recogniser.start(); } catch (error) { bubble('assistant', error.message); }
  };

  $('#speakToggle').textContent = voiceOn ? 'VOICE REPLIES ON' : 'VOICE REPLIES OFF';
  $('#speakToggle').setAttribute('aria-pressed', String(voiceOn));
  health();
  setInterval(health, 15000);
  setInterval(() => {
    if (currentTab === 'agents' && !document.hidden) refreshRuns();
  }, 6000);
  refreshAgents();
})();
