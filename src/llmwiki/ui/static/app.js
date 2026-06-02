const ENDPOINTS = {
  session: "/api/session",
  status: "/api/status",
  sources: "/api/sources",
  runs: "/api/runs",
  pages: "/api/pages",
  config: "/api/config",
  jobs: "/api/jobs",
  addSource: "/api/sources/add"
};

const state = {
  actionToken: "",
  pollTimer: null
};

async function fetchJson(path, options = {}) {
  const response = await fetch(path, options);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.message || payload.error || "Request failed");
  }
  return payload;
}

async function loadSession() {
  const session = await fetchJson(ENDPOINTS.session);
  state.actionToken = session.action_token || "";
}

async function loadDashboard() {
  if (!state.actionToken) {
    await loadSession();
  }
  const [status, sources, runs, pages, config, jobs] = await Promise.all([
    fetchJson(ENDPOINTS.status),
    fetchJson(ENDPOINTS.sources),
    fetchJson(ENDPOINTS.runs),
    fetchJson(ENDPOINTS.pages),
    fetchJson(ENDPOINTS.config),
    fetchJson(ENDPOINTS.jobs)
  ]);
  renderStatus(status);
  renderConfig(config);
  renderSources(sources.sources || []);
  renderRuns(runs.runs || []);
  renderPages(pages.pages || []);
  renderJobs(jobs.jobs || []);
  renderWarnings(collectWarnings(status, sources, runs, pages, config, jobs));
  updateJobPolling(jobs.jobs || []);
}

async function submitAddSource(event) {
  event.preventDefault();
  const source = document.querySelector("#source-input")?.value || "";
  const parser = document.querySelector("#parser-select")?.value || "";
  setText("add-source-status", "Queueing...");
  try {
    const payload = await fetchJson(ENDPOINTS.addSource, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-LLMWiki-UI-Token": state.actionToken
      },
      body: JSON.stringify({ source, parser })
    });
    setText("add-source-status", `Queued ${payload.job.job_id}`);
    document.querySelector("#source-input").value = "";
    await loadDashboard();
  } catch (error) {
    setText("add-source-status", "Failed");
    renderWarnings([{ category: "source", message: error.message }]);
  }
}

function renderStatus(status) {
  setText("workspace-root", status.workspace_root || "Workspace unavailable");
  setText("status-value", status.status || "unknown");
  setText("sources-count", String((status.counts && status.counts.sources) || 0));
  setText("claims-count", String((status.counts && status.counts.claims) || 0));
  setText("pages-count", String((status.counts && status.counts.pages) || 0));
  const latest = (status.latest_runs || [])[0];
  setText("latest-run", latest ? `${latest.run_id} (${latest.status})` : "None");
}

function renderConfig(config) {
  const llm = config.llm || {};
  const embedding = config.embedding || {};
  const parser = config.parser || {};
  const vector = config.vector || {};
  setText("llm-status", `${llm.provider || "unknown"} / ${llm.model || "no model"} / key ${llm.api_key_present ? "present" : "missing"}`);
  setText("embedding-status", `${embedding.provider || "unknown"} / ${embedding.model || "no model"} / ${embedding.enabled ? "enabled" : "disabled"}`);
  setText("parser-status", `${parser.default_backend || "unknown"} -> ${parser.fallback_backend || "none"} / MinerU ${parser.mineru_available ? "available" : "unavailable"}`);
  setText("vector-status", vector.index_present ? `present / ${vector.chunk_count || 0} chunks` : "not built");
}

function renderSources(sources) {
  setText("sources-table-count", `${sources.length} rows`);
  const rows = sources.map((source) => `
    <tr>
      <td><strong>${escapeHtml(source.title || source.source_id)}</strong><span>${escapeHtml(source.source_id)}</span></td>
      <td>${escapeHtml(source.source_type || "")}</td>
      <td>${escapeHtml(source.status || "")}<span>${escapeHtml(source.latest_job_status || "")}</span></td>
      <td>${escapeHtml(source.parser_backend || "n/a")}${source.parser_fallback ? `<span>fallback: ${escapeHtml(source.parser_fallback)}</span>` : ""}</td>
      <td>${escapeHtml(source.latest_run_id || "none")}<span>${escapeHtml(source.latest_run_status || source.latest_job_id || "")}</span></td>
    </tr>
  `);
  setTable("sources-table", rows, 5);
}

function renderJobs(jobs) {
  setText("jobs-table-count", `${jobs.length} rows`);
  const active = jobs.filter((job) => job.status === "pending" || job.status === "running");
  setText("active-job-strip", active.length ? `${active.length} active job(s): ${active.map((job) => job.job_id).join(", ")}` : "No active jobs.");
  const rows = jobs.map((job) => `
    <tr>
      <td><strong>${escapeHtml(job.job_id)}</strong><span>${escapeHtml(job.created_at || "")}</span></td>
      <td>${escapeHtml(job.source_input || "")}<span>${escapeHtml(job.requested_parser || "default")}</span></td>
      <td>${escapeHtml(job.status || "")}</td>
      <td>${escapeHtml(job.stage || "")}</td>
      <td>${escapeHtml(job.run_id || job.failure_stage || "")}<span>${escapeHtml(job.failure_reason || job.source_id || "")}</span></td>
    </tr>
  `);
  setTable("jobs-table", rows, 5);
}

function renderRuns(runs) {
  setText("runs-table-count", `${runs.length} rows`);
  const rows = runs.map((run) => `
    <tr>
      <td><strong>${escapeHtml(run.run_id)}</strong><span>${escapeHtml(run.run_type || "")}</span></td>
      <td>${escapeHtml(run.source_id || "")}</td>
      <td>${escapeHtml(run.status || "")}</td>
      <td>${escapeHtml(run.failed_stage || run.trigger || "")}</td>
      <td>${escapeHtml(String(run.claim_count || 0))}</td>
    </tr>
  `);
  setTable("runs-table", rows, 5);
}

function renderPages(pages) {
  setText("pages-table-count", `${pages.length} rows`);
  const rows = pages.map((page) => `
    <tr>
      <td><strong>${escapeHtml(page.title || page.page_id)}</strong><span>${escapeHtml(page.page_id || "")}</span></td>
      <td>${escapeHtml(page.page_type || "")}</td>
      <td>${escapeHtml(page.path || "")}</td>
      <td>${escapeHtml(String(page.claim_count || 0))}</td>
    </tr>
  `);
  setTable("pages-table", rows, 4);
}

function renderWarnings(warnings) {
  const list = document.querySelector("#warnings-list");
  if (!list) {
    return;
  }
  if (!warnings.length) {
    list.innerHTML = '<li class="muted">No warnings.</li>';
    return;
  }
  list.innerHTML = warnings.map((warning) => `<li><strong>${escapeHtml(warning.category || "general")}</strong> ${escapeHtml(warning.message || "")}</li>`).join("");
}

function collectWarnings(...payloads) {
  return payloads.flatMap((payload) => payload.warnings || []);
}

function updateJobPolling(jobs) {
  const hasActive = jobs.some((job) => job.status === "pending" || job.status === "running");
  if (hasActive && !state.pollTimer) {
    state.pollTimer = setInterval(() => {
      loadDashboard().catch(showLoadError);
    }, 2000);
  }
  if (!hasActive && state.pollTimer) {
    clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
}

function setTable(id, rows, colspan) {
  const target = document.querySelector(`#${id}`);
  if (!target) {
    return;
  }
  target.innerHTML = rows.length ? rows.join("") : `<tr><td colspan="${colspan}" class="muted">No data.</td></tr>`;
}

function setText(id, value) {
  const target = document.querySelector(`#${id}`);
  if (target) {
    target.textContent = value;
  }
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

document.querySelector("#refresh-button")?.addEventListener("click", () => {
  loadDashboard().catch(showLoadError);
});

document.querySelector("#add-source-form")?.addEventListener("submit", (event) => {
  submitAddSource(event).catch(showLoadError);
});

function showLoadError(error) {
  setText("status-value", "error");
  renderWarnings([{ category: "dashboard", message: `Unable to load dashboard: ${error.message}` }]);
}

loadDashboard().catch(showLoadError);
