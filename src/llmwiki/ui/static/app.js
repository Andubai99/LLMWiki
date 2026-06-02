const ENDPOINTS = {
  status: "/api/status",
  sources: "/api/sources",
  runs: "/api/runs",
  pages: "/api/pages",
  config: "/api/config"
};

async function fetchJson(path) {
  const response = await fetch(path);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.message || payload.error || "Request failed");
  }
  return payload;
}

async function loadDashboard() {
  const [status, sources, runs, pages, config] = await Promise.all([
    fetchJson(ENDPOINTS.status),
    fetchJson(ENDPOINTS.sources),
    fetchJson(ENDPOINTS.runs),
    fetchJson(ENDPOINTS.pages),
    fetchJson(ENDPOINTS.config)
  ]);
  renderStatus(status);
  renderConfig(config);
  renderSources(sources.sources || []);
  renderRuns(runs.runs || []);
  renderPages(pages.pages || []);
  renderWarnings(collectWarnings(status, sources, runs, pages, config));
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
      <td>${escapeHtml(source.status || "")}</td>
      <td>${escapeHtml(source.parser_backend || "n/a")}${source.parser_fallback ? `<span>fallback: ${escapeHtml(source.parser_fallback)}</span>` : ""}</td>
      <td>${escapeHtml(source.latest_run_id || "none")}<span>${escapeHtml(source.latest_run_status || "")}</span></td>
    </tr>
  `);
  setTable("sources-table", rows, 5);
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

function showLoadError(error) {
  setText("status-value", "error");
  renderWarnings([{ category: "dashboard", message: `Unable to load dashboard: ${error.message}` }]);
}

loadDashboard().catch(showLoadError);
