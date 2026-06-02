const ENDPOINTS = {
  session: "/api/session",
  status: "/api/status",
  sources: "/api/sources",
  runs: "/api/runs",
  pages: "/api/pages",
  config: "/api/config",
  jobs: "/api/jobs",
  askJobs: "/api/ask/jobs",
  addSource: "/api/sources/add",
  ask: "/api/ask",
  synthesisPreviewSuffix: "/synthesis/preview",
  synthesisWritebackSuffix: "/synthesis/writeback"
};

const state = {
  actionToken: "",
  pollTimer: null,
  latestAskJobId: "",
  latestPreviewJobId: ""
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
  const [status, sources, runs, pages, config, jobs, askJobs] = await Promise.all([
    fetchJson(ENDPOINTS.status),
    fetchJson(ENDPOINTS.sources),
    fetchJson(ENDPOINTS.runs),
    fetchJson(ENDPOINTS.pages),
    fetchJson(ENDPOINTS.config),
    fetchJson(ENDPOINTS.jobs),
    fetchJson(ENDPOINTS.askJobs)
  ]);
  renderStatus(status);
  renderConfig(config);
  renderSources(sources.sources || []);
  renderRuns(runs.runs || []);
  renderPages(pages.pages || []);
  renderJobs(jobs.jobs || []);
  renderResearchJobs(askJobs.jobs || []);
  renderWarnings(collectWarnings(status, sources, runs, pages, config, jobs, askJobs));
  updateJobPolling(jobs.jobs || []);
}

async function submitAddSource(event) {
  event.preventDefault();
  const source = document.querySelector("#source-input")?.value || "";
  const parser = document.querySelector("#parser-select")?.value || "";
  setText("add-source-status", "Queueing...");
  try {
    const payload = await postWithToken(ENDPOINTS.addSource, { source, parser });
    setText("add-source-status", `Queued ${payload.job.job_id}`);
    document.querySelector("#source-input").value = "";
    await loadDashboard();
  } catch (error) {
    setText("add-source-status", "Failed");
    renderWarnings([{ category: "source", message: error.message }]);
  }
}

async function submitAsk(event) {
  event.preventDefault();
  const question = document.querySelector("#ask-question")?.value || "";
  const limit = document.querySelector("#ask-limit")?.value || "8";
  const source_id = document.querySelector("#ask-source-id")?.value || "";
  const page_type = document.querySelector("#ask-page-type")?.value || "";
  const confidence = document.querySelector("#ask-confidence")?.value || "";
  setText("ask-status", "Queueing...");
  try {
    const payload = await postWithToken(ENDPOINTS.ask, { question, limit, source_id, page_type, confidence });
    state.latestAskJobId = payload.job.job_id;
    setText("ask-status", `Queued ${payload.job.job_id}`);
    await loadDashboard();
  } catch (error) {
    setText("ask-status", "Failed");
    renderWarnings([{ category: "ask", message: error.message }]);
  }
}

async function submitSynthesisPreview() {
  if (!state.latestAskJobId) {
    renderWarnings([{ category: "synthesis", message: "No answered ask job is selected." }]);
    return;
  }
  setText("synthesis-status", "Queueing preview...");
  try {
    const payload = await postWithToken(`${ENDPOINTS.ask}/${state.latestAskJobId}${ENDPOINTS.synthesisPreviewSuffix}`, {});
    state.latestPreviewJobId = payload.job.job_id;
    setText("synthesis-status", `Preview queued ${payload.job.job_id}`);
    await loadDashboard();
  } catch (error) {
    setText("synthesis-status", "Preview failed");
    renderWarnings([{ category: "synthesis", message: error.message }]);
  }
}

async function submitSynthesisWriteback() {
  if (!state.latestAskJobId) {
    renderWarnings([{ category: "synthesis", message: "No answered ask job is selected." }]);
    return;
  }
  const writeback_mode = document.querySelector("#writeback-mode")?.value || "auto";
  setText("synthesis-status", "Queueing writeback...");
  try {
    const payload = await postWithToken(`${ENDPOINTS.ask}/${state.latestAskJobId}${ENDPOINTS.synthesisWritebackSuffix}`, { writeback_mode });
    setText("synthesis-status", `Writeback queued ${payload.job.job_id}`);
    await loadDashboard();
  } catch (error) {
    setText("synthesis-status", "Writeback failed");
    renderWarnings([{ category: "synthesis", message: error.message }]);
  }
}

async function postWithToken(path, body) {
  return fetchJson(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-LLMWiki-UI-Token": state.actionToken
    },
    body: JSON.stringify(body)
  });
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
      <td>${escapeHtml(job.source_input || job.question || job.parent_job_id || "")}<span>${escapeHtml(job.requested_parser || job.writeback_mode || "default")}</span></td>
      <td>${escapeHtml(job.status || "")}</td>
      <td>${escapeHtml(job.stage || "")}</td>
      <td>${escapeHtml(job.run_id || job.failure_stage || job.result?.answer_status || job.result?.preview_status || job.result?.writeback_status || "")}<span>${escapeHtml(job.failure_reason || job.source_id || "")}</span></td>
    </tr>
  `);
  setTable("jobs-table", rows, 5);
}

function renderResearchJobs(jobs) {
  const askJob = jobs.find((job) => job.job_type === "ask_question" && job.result && job.result.answer_status === "answered")
    || jobs.find((job) => job.job_type === "ask_question");
  const previewJob = jobs.find((job) => job.job_type === "synthesis_preview" && job.result && job.result.preview_status);
  if (askJob) {
    state.latestAskJobId = askJob.job_id;
    renderAnswer(askJob.result || {});
  }
  if (previewJob) {
    state.latestPreviewJobId = previewJob.job_id;
    renderSynthesisPreview(previewJob.result || {});
  }
}

function renderAnswer(result) {
  setText("answer-status", result.answer_status || "unknown");
  setText("answer-text", result.answer || "No answer text.");
  setText("analysis-text", result.analysis || "No analysis.");
  setList("answer-warnings", result.warnings || []);
  setList("answer-uncertainties", result.uncertainties || []);
  setList("answer-conflicts", result.conflicts || []);
  renderCitations(result.citations || []);
  renderEvidence(result.contexts || []);
  setText("planning-json", JSON.stringify(result.planning || {}, null, 2));
}

function renderCitations(citations) {
  const rows = citations.map((citation) => `
    <tr>
      <td>${escapeHtml(citation.claim_id || "")}</td>
      <td>${escapeHtml(citation.source_id || "")}</td>
      <td>${escapeHtml(citation.citation_locator || "")}</td>
      <td>${escapeHtml(citation.page_path || "")}</td>
    </tr>
  `);
  setTable("citations-table", rows, 4);
}

function renderEvidence(contexts) {
  const rows = contexts.map((context) => `
    <tr>
      <td><strong>${escapeHtml(context.claim_id || "")}</strong><span>${escapeHtml(context.claim_text || "")}</span></td>
      <td>${escapeHtml(context.source_id || "")}</td>
      <td>${escapeHtml(context.citation_locator || "")}</td>
      <td>${escapeHtml(context.page_path || "")}</td>
    </tr>
  `);
  setTable("evidence-table", rows, 4);
}

function renderSynthesisPreview(result) {
  setText("synthesis-status", `${result.preview_status || "preview"} / ${result.action || "unknown"}`);
  setText("synthesis-preview-text", result.preview_text || JSON.stringify(result.synthesis_plan || {}, null, 2));
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

function setList(id, items) {
  const target = document.querySelector(`#${id}`);
  if (!target) {
    return;
  }
  target.innerHTML = items.length ? items.map((item) => `<li>${escapeHtml(item)}</li>`).join("") : '<li class="muted">None.</li>';
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

document.querySelector("#ask-form")?.addEventListener("submit", (event) => {
  submitAsk(event).catch(showLoadError);
});

document.querySelector("#synthesis-preview-button")?.addEventListener("click", () => {
  submitSynthesisPreview().catch(showLoadError);
});

document.querySelector("#synthesis-writeback-button")?.addEventListener("click", () => {
  submitSynthesisWriteback().catch(showLoadError);
});

function showLoadError(error) {
  setText("status-value", "error");
  renderWarnings([{ category: "dashboard", message: `Unable to load dashboard: ${error.message}` }]);
}

loadDashboard().catch(showLoadError);
