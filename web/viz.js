/* JARVIS Visuals — every mark on screen is drawn from a live API payload.
   Nothing here is decorative filler: if a request fails the panel says so
   instead of inventing a value. */
(function () {
  "use strict";

  var REFRESH_MS = 30000;
  var NS = "http://www.w3.org/2000/svg";
  var timer = null;
  var loading = false;
  var mounted = false;
  var panel, body, stampEl, errorEl, closeBtn;

  var data = { agents: null, tools: null, sources: null, runs: null, health: null, errors: [] };

  function svg(tag, attrs) {
    var node = document.createElementNS(NS, tag);
    Object.keys(attrs || {}).forEach(function (key) { node.setAttribute(key, attrs[key]); });
    return node;
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function statusColor(state) {
    if (state === "connected") return "#4ade80";
    if (state === "partial") return "#fbbf24";
    if (state === "blocked" || state === "error") return "#f87171";
    return "#94a3b8";
  }

  async function getJSON(url) {
    var response = await fetch(url, { headers: { Accept: "application/json" }, cache: "no-store" });
    var payload = {};
    try { payload = await response.json(); } catch (err) { payload = {}; }
    if (!response.ok) {
      throw new Error(payload.error || payload.detail || ("HTTP " + response.status));
    }
    return payload;
  }

  function section(title, hint) {
    var box = el("section", "viz-card");
    var head = el("header", "viz-card-head");
    head.appendChild(el("h3", null, title));
    if (hint) head.appendChild(el("span", "viz-hint", hint));
    box.appendChild(head);
    return box;
  }

  function buildPanel() {
    panel = el("div", "viz-overlay");
    panel.id = "jarvisViz";
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-modal", "true");
    panel.setAttribute("aria-label", "JARVIS visual intelligence");
    panel.hidden = true;

    var bar = el("div", "viz-bar");
    var title = el("div", "viz-title");
    title.appendChild(el("span", "viz-dot"));
    title.appendChild(el("strong", null, "Visual Intelligence"));
    bar.appendChild(title);

    var actions = el("div", "viz-actions");
    stampEl = el("span", "viz-stamp", "not loaded");
    actions.appendChild(stampEl);
    var refreshBtn = el("button", "viz-btn", "Refresh");
    refreshBtn.type = "button";
    refreshBtn.addEventListener("click", function () { refresh(true); });
    actions.appendChild(refreshBtn);
    closeBtn = el("button", "viz-btn viz-close", "Close");
    closeBtn.type = "button";
    closeBtn.addEventListener("click", close);
    actions.appendChild(closeBtn);
    bar.appendChild(actions);
    panel.appendChild(bar);

    errorEl = el("div", "viz-errors");
    errorEl.hidden = true;
    panel.appendChild(errorEl);

    body = el("div", "viz-grid");
    panel.appendChild(body);
    document.body.appendChild(panel);
  }

  function clearRailActive() {
    document.querySelectorAll(".rail-item").forEach(function (item) {
      item.classList.remove("active");
    });
  }

  function renderConstellation(agents) {
    var card = section("Agent constellation", agents.length + " roles");
    var width = 660, height = 440, cx = width / 2, cy = height / 2 - 4, radius = 152;
    var chart = svg("svg", {
      viewBox: "0 0 " + width + " " + height,
      class: "viz-svg",
      role: "img",
      "aria-label": "Specialist agents arranged around the orchestrator, coloured by live status"
    });

    var defs = svg("defs", {});
    var glow = svg("radialGradient", { id: "vizCore" });
    glow.appendChild(svg("stop", { offset: "0%", "stop-color": "#f0abfc" }));
    glow.appendChild(svg("stop", { offset: "100%", "stop-color": "#7c3aed" }));
    defs.appendChild(glow);
    chart.appendChild(defs);

    var activeRun = (data.runs && data.runs.runs || []).find(function (run) {
      return run.status === "running" || run.status === "awaiting_approval";
    });
    var activeRole = activeRun && activeRun.role;

    agents.forEach(function (agent, index) {
      var angle = (index / agents.length) * Math.PI * 2 - Math.PI / 2;
      var x = cx + Math.cos(angle) * radius;
      var y = cy + Math.sin(angle) * radius;
      var edge = svg("line", {
        x1: cx, y1: cy, x2: x, y2: y,
        stroke: statusColor(agent.status),
        "stroke-opacity": activeRole === agent.id ? 0.95 : 0.28,
        "stroke-width": activeRole === agent.id ? 2.4 : 1.2,
        class: activeRole === agent.id ? "viz-edge viz-edge-live" : "viz-edge"
      });
      chart.appendChild(edge);

      var group = svg("g", { class: "viz-node", tabindex: "0", role: "listitem" });
      group.appendChild(svg("circle", {
        cx: x, cy: y, r: 24, fill: "rgba(10,6,22,0.92)",
        stroke: statusColor(agent.status), "stroke-width": 2
      }));
      group.appendChild(svg("circle", {
        cx: x, cy: y, r: 6, fill: statusColor(agent.status)
      }));
      var label = svg("text", {
        x: x, y: y + 40, "text-anchor": "middle", class: "viz-label"
      });
      label.textContent = agent.name
        .replace("Chief Orchestrator", "Orchestrator")
        .replace(/ Agent$/, "");
      group.appendChild(label);
      var tip = svg("title", {});
      tip.textContent = agent.name + " — " + agent.status + (agent.status_detail ? " — " + agent.status_detail : "");
      group.appendChild(tip);
      chart.appendChild(group);
    });

    chart.appendChild(svg("circle", {
      cx: cx, cy: cy, r: 46, fill: "url(#vizCore)", opacity: 0.9,
      class: activeRun ? "viz-core viz-core-live" : "viz-core"
    }));
    var coreLabel = svg("text", { x: cx, y: cy + 4, "text-anchor": "middle", class: "viz-core-label" });
    coreLabel.textContent = "JARVIS";
    chart.appendChild(coreLabel);

    card.appendChild(chart);

    var legend = el("div", "viz-legend");
    ["connected", "partial", "blocked"].forEach(function (state) {
      var item = el("span", "viz-legend-item");
      var dot = el("i");
      dot.style.background = statusColor(state);
      item.appendChild(dot);
      item.appendChild(document.createTextNode(state));
      legend.appendChild(item);
    });
    if (activeRun) {
      legend.appendChild(el("span", "viz-live", "live: " + (activeRole || "orchestrator")));
    }
    card.appendChild(legend);
    return card;
  }

  function renderTools(tools) {
    var card = section("Tool surface", tools.length + " registered");
    var counts = {};
    (data.agents || []).forEach(function (agent) {
      counts[agent.id] = agent.available_tools.length;
    });
    var max = Math.max.apply(null, Object.keys(counts).map(function (key) { return counts[key]; }).concat([1]));
    var list = el("div", "viz-bars");
    Object.keys(counts).forEach(function (id) {
      var row = el("div", "viz-bar-row");
      row.appendChild(el("span", "viz-bar-label", id));
      var track = el("div", "viz-track");
      var fill = el("div", "viz-fill");
      fill.style.width = Math.round((counts[id] / max) * 100) + "%";
      track.appendChild(fill);
      row.appendChild(track);
      row.appendChild(el("span", "viz-bar-value", String(counts[id])));
      list.appendChild(row);
    });
    card.appendChild(list);

    var gated = tools.filter(function (tool) { return tool.permission === "confirm"; });
    card.appendChild(el(
      "p", "viz-note",
      gated.length + " of " + tools.length + " tools pause for approval before acting."
    ));
    return card;
  }

  function renderSources(sources) {
    var card = section("Data sources", sources.length + " configured");
    var list = el("div", "viz-sources");
    sources.forEach(function (source) {
      var row = el("div", "viz-source");
      var dot = el("i", "viz-source-dot");
      dot.style.background = statusColor(source.state === "connected" ? "connected" : source.state === "error" ? "error" : "off");
      row.appendChild(dot);
      var text = el("div", "viz-source-text");
      text.appendChild(el("strong", null, source.label));
      text.appendChild(el("span", null, source.state + (source.detail ? " · " + source.detail : "")));
      row.appendChild(text);
      var scopes = el("span", "viz-scope", source.scopes.join(", "));
      row.appendChild(scopes);
      list.appendChild(row);
    });
    card.appendChild(list);
    return card;
  }

  function renderRuns(runs) {
    var card = section("Recent runs", runs.length + " recorded");
    if (!runs.length) {
      card.appendChild(el("p", "viz-note", "No agent runs yet. Start one from the Workflows panel."));
      return card;
    }
    var list = el("div", "viz-runs");
    runs.slice(0, 6).forEach(function (run) {
      var row = el("div", "viz-run");
      var chip = el("span", "viz-chip", run.status);
      chip.style.borderColor = statusColor(run.status === "completed" ? "connected" : run.status === "failed" ? "blocked" : "partial");
      row.appendChild(chip);
      var text = el("div", "viz-run-text");
      text.appendChild(el("strong", null, run.role || "orchestrator"));
      text.appendChild(el("span", null, (run.goal || "").slice(0, 110)));
      row.appendChild(text);
      row.appendChild(el("span", "viz-run-steps", String((run.steps || []).length) + " steps"));
      list.appendChild(row);
    });
    card.appendChild(list);
    return card;
  }

  function renderSystem(health) {
    var card = section("Runtime", "live");
    var rows = [
      ["provider", health.provider || "unknown"],
      ["model", health.model || "unknown"],
      ["memories", String(health.memory_count != null ? health.memory_count : "—")],
      ["core tools", String((data.tools || []).length)],
      ["sources live", String((data.sources || []).filter(function (s) { return s.state === "connected"; }).length)]
    ];
    var list = el("dl", "viz-stats");
    rows.forEach(function (pair) {
      list.appendChild(el("dt", null, pair[0]));
      list.appendChild(el("dd", null, pair[1]));
    });
    card.appendChild(list);
    return card;
  }

  function render() {
    body.textContent = "";
    if (data.agents) body.appendChild(renderConstellation(data.agents));
    if (data.tools) body.appendChild(renderTools(data.tools));
    if (data.sources) body.appendChild(renderSources(data.sources));
    if (data.runs) body.appendChild(renderRuns(data.runs.runs || []));
    if (data.health) body.appendChild(renderSystem(data.health));

    if (data.errors.length) {
      errorEl.hidden = false;
      errorEl.textContent = "Unavailable: " + data.errors.join(" · ");
    } else {
      errorEl.hidden = true;
      errorEl.textContent = "";
    }
    stampEl.textContent = "updated " + new Date().toLocaleTimeString();
  }

  async function refresh(force) {
    if (loading && !force) return;
    loading = true;
    data.errors = [];
    var jobs = [
      ["agents", "/api/core/agents", function (payload) { data.agents = payload.agents || []; }],
      ["tools", "/api/core/tools", function (payload) { data.tools = payload || []; }],
      ["sources", "/api/core/connectors", function (payload) { data.sources = payload.sources || []; }],
      ["runs", "/api/core/runs", function (payload) { data.runs = payload || { runs: [] }; }],
      ["health", "/api/health", function (payload) { data.health = payload || {}; }]
    ];
    await Promise.all(jobs.map(async function (job) {
      try {
        job[2](await getJSON(job[1]));
      } catch (err) {
        data.errors.push(job[0] + ": " + (err && err.message ? err.message : "failed"));
      }
    }));
    loading = false;
    if (!panel.hidden) render();
  }

  function open() {
    if (!mounted) { buildPanel(); mounted = true; }
    panel.hidden = false;
    clearRailActive();
    var railBtn = document.getElementById("railVisuals");
    if (railBtn) railBtn.classList.add("active");
    refresh(true);
    if (timer) clearInterval(timer);
    timer = setInterval(function () { if (!panel.hidden) refresh(false); }, REFRESH_MS);
    if (closeBtn) closeBtn.focus();
  }

  function close() {
    if (!panel) return;
    panel.hidden = true;
    if (timer) { clearInterval(timer); timer = null; }
    var railBtn = document.getElementById("railVisuals");
    if (railBtn) railBtn.classList.remove("active");
    var chat = document.querySelector('[data-nav="chat"]');
    if (chat) chat.classList.add("active");
  }

  function init() {
    var railButton = document.getElementById("railVisuals");
    if (railButton) railButton.addEventListener("click", open);
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && panel && !panel.hidden) close();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  window.JarvisViz = { open: open, close: close, refresh: refresh };
})();
