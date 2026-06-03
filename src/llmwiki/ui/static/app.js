const ENDPOINTS = {
  session: "/api/session",
  status: "/api/status",
  sources: "/api/sources",
  runs: "/api/runs",
  pages: "/api/pages",
  config: "/api/config",
  jobs: "/api/jobs",
  askJobs: "/api/ask/jobs",
  claims: "/api/evidence/claims",
  relationships: "/api/evidence/relationships",
  sourceDetailBase: "/api/sources/",
  pageDetailBase: "/api/pages/",
  claimDetailBase: "/api/evidence/claims/",
  addSource: "/api/sources/add",
  ask: "/api/ask",
  synthesisPreviewSuffix: "/synthesis/preview",
  synthesisWritebackSuffix: "/synthesis/writeback"
};

const state = {
  actionToken: "",
  pollTimer: null,
  latestAskJobId: "",
  latestPreviewJobId: "",
  sources: [],
  pages: []
};

async function fetchJson(path, options = {}) {
  const response = await fetch(path, options);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.message || payload.error || "请求失败");
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
  state.sources = sources.sources || [];
  state.pages = pages.pages || [];
  renderStatus(status);
  renderConfig(config);
  renderSources(state.sources);
  renderRuns(runs.runs || []);
  renderPages(state.pages);
  renderWikiBrowser(state.pages);
  renderJobs(jobs.jobs || []);
  renderResearchJobs(askJobs.jobs || []);
  renderWarnings(collectWarnings(status, sources, runs, pages, config, jobs, askJobs));
  updateJobPolling(jobs.jobs || []);
  loadClaimBrowser().catch((error) => {
    setText("claim-browser-count", "加载失败");
    renderWarnings([{ category: "evidence", message: error.message }]);
  });
}

async function submitAddSource(event) {
  event.preventDefault();
  const source = document.querySelector("#source-input")?.value || "";
  const parser = document.querySelector("#parser-select")?.value || "";
  setText("add-source-status", "正在排队...");
  try {
    const payload = await postWithToken(ENDPOINTS.addSource, { source, parser });
    setText("add-source-status", `资料源任务已排队：${payload.job.job_id}`);
    document.querySelector("#source-input").value = "";
    await loadDashboard();
  } catch (error) {
    setText("add-source-status", "失败");
    renderWarnings([{ category: "资料源", message: error.message }]);
  }
}

async function submitAsk(event) {
  event.preventDefault();
  const question = document.querySelector("#ask-question")?.value || "";
  const limit = document.querySelector("#ask-limit")?.value || "8";
  const source_id = document.querySelector("#ask-source-id")?.value || "";
  const page_type = document.querySelector("#ask-page-type")?.value || "";
  const confidence = document.querySelector("#ask-confidence")?.value || "";
  setText("ask-status", "正在排队...");
  try {
    const payload = await postWithToken(ENDPOINTS.ask, { question, limit, source_id, page_type, confidence });
    state.latestAskJobId = payload.job.job_id;
    setText("ask-status", `问答任务已排队：${payload.job.job_id}`);
    await loadDashboard();
  } catch (error) {
    setText("ask-status", "失败");
    renderWarnings([{ category: "问答", message: error.message }]);
  }
}

async function submitSynthesisPreview() {
  if (!state.latestAskJobId) {
    setText("synthesis-status", "需要先完成一次成功回答。");
    setText("synthesis-preview-text", "需要先完成一次成功回答。");
    renderWarnings([{ category: "综合", message: "需要先完成一次成功回答。" }]);
    return;
  }
  setText("synthesis-status", "正在排队综合预览...");
  try {
    const payload = await postWithToken(`${ENDPOINTS.ask}/${state.latestAskJobId}${ENDPOINTS.synthesisPreviewSuffix}`, {});
    state.latestPreviewJobId = payload.job.job_id;
    setText("synthesis-status", `综合预览任务已排队：${payload.job.job_id}`);
    await loadDashboard();
  } catch (error) {
    setText("synthesis-status", "综合预览提交失败");
    setText("synthesis-preview-text", `综合预览提交失败\n原因：${error.message}`);
    renderWarnings([{ category: "综合", message: error.message }]);
  }
}

async function submitSynthesisWriteback() {
  if (!state.latestAskJobId) {
    setText("synthesis-status", "需要先完成一次成功回答。");
    renderWarnings([{ category: "综合", message: "需要先完成一次成功回答。" }]);
    return;
  }
  const writeback_mode = document.querySelector("#writeback-mode")?.value || "auto";
  setText("synthesis-status", "正在排队写回草稿...");
  try {
    const payload = await postWithToken(`${ENDPOINTS.ask}/${state.latestAskJobId}${ENDPOINTS.synthesisWritebackSuffix}`, { writeback_mode });
    setText("synthesis-status", `写回草稿任务已排队：${payload.job.job_id}`);
    await loadDashboard();
  } catch (error) {
    setText("synthesis-status", "写回草稿提交失败");
    renderWarnings([{ category: "综合", message: error.message }]);
  }
}

async function loadClaimBrowser(event) {
  if (event) {
    event.preventDefault();
  }
  const params = {
    query: document.querySelector("#claim-query")?.value || "",
    source_id: document.querySelector("#claim-filter-source")?.value || "",
    page_type: document.querySelector("#claim-filter-page-type")?.value || "",
    confidence: document.querySelector("#claim-filter-confidence")?.value || "",
    relationship_type: document.querySelector("#claim-filter-relationship")?.value || ""
  };
  const payload = await fetchJson(`${ENDPOINTS.claims}${buildQuery(params)}`);
  renderClaimBrowser(payload.claims || [], payload.total || 0);
}

function submitWikiBrowser(event) {
  event.preventDefault();
  renderWikiBrowser(state.pages || []);
}

async function loadClaimDetail(claimId) {
  if (!claimId) {
    return;
  }
  setText("browser-detail-status", `正在加载声明：${claimId}`);
  const payload = await fetchJson(`${ENDPOINTS.claimDetailBase}${encodeURIComponent(claimId)}`);
  renderClaimDetail(payload);
}

async function loadSourceDetail(sourceId) {
  if (!sourceId) {
    return;
  }
  setText("browser-detail-status", `正在加载资料源：${sourceId}`);
  const payload = await fetchJson(`${ENDPOINTS.sourceDetailBase}${encodeURIComponent(sourceId)}`);
  renderSourceDetail(payload);
}

async function loadPageDetail(pageId) {
  if (!pageId) {
    return;
  }
  setText("browser-detail-status", `正在加载页面：${pageId}`);
  const payload = await fetchJson(`${ENDPOINTS.pageDetailBase}${encodeURIComponent(pageId)}`);
  renderPageDetail(payload);
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

function buildQuery(params) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    const text = String(value || "").trim();
    if (text) {
      search.set(key, text);
    }
  });
  const query = search.toString();
  return query ? `?${query}` : "";
}

function renderStatus(status) {
  setText("workspace-root", status.workspace_root || "工作区不可用");
  setText("status-value", status.status || "unknown");
  setText("sources-count", String((status.counts && status.counts.sources) || 0));
  setText("claims-count", String((status.counts && status.counts.claims) || 0));
  setText("pages-count", String((status.counts && status.counts.pages) || 0));
  const latest = (status.latest_runs || [])[0];
  setText("latest-run", latest ? `${latest.run_id} (${latest.status})` : "无");
}

function renderConfig(config) {
  const llm = config.llm || {};
  const embedding = config.embedding || {};
  const parser = config.parser || {};
  const vector = config.vector || {};
  setText("llm-status", `${llm.provider || "unknown"} / ${llm.model || "no model"} / 密钥 ${llm.api_key_present ? "present" : "missing"}`);
  setText("embedding-status", `${embedding.provider || "unknown"} / ${embedding.model || "no model"} / ${embedding.enabled ? "enabled" : "disabled"}`);
  setText("parser-status", `${parser.default_backend || "unknown"} -> ${parser.fallback_backend || "none"} / MinerU ${parser.mineru_available ? "available" : "unavailable"}`);
  setText("vector-status", vector.index_present ? `present / ${vector.chunk_count || 0} chunks` : "not built");
}

function renderSources(sources) {
  setText("sources-table-count", `${sources.length} 行`);
  const rows = sources.map((source) => `
    <tr>
      <td><button type="button" class="link-button" data-source-id="${escapeHtml(source.source_id || "")}">${escapeHtml(source.title || source.source_id)}</button><span>${escapeHtml(source.source_id)}</span></td>
      <td>${escapeHtml(source.source_type || "")}</td>
      <td>${escapeHtml(source.status || "")}<span>${escapeHtml(source.latest_job_status || "")}</span></td>
      <td>${escapeHtml(source.parser_backend || "n/a")}${source.parser_fallback ? `<span>fallback: ${escapeHtml(source.parser_fallback)}</span>` : ""}</td>
      <td>${escapeHtml(source.latest_run_id || "none")}<span>${escapeHtml(source.latest_run_status || source.latest_job_id || "")}</span></td>
    </tr>
  `);
  setTable("sources-table", rows, 5);
}

function renderJobs(jobs) {
  setText("jobs-table-count", `${jobs.length} 行`);
  const active = jobs.filter((job) => job.status === "pending" || job.status === "running");
  setText(
    "active-job-strip",
    active.length ? `${active.length} 个运行中的任务：${active.map((job) => job.job_id).join(", ")}` : "没有运行中的任务。"
  );
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
  const previewJob = jobs.find((job) => job.job_type === "synthesis_preview");
  if (askJob) {
    state.latestAskJobId = askJob.job_id;
    renderAnswer(askJob.result || {});
  }
  if (previewJob) {
    state.latestPreviewJobId = previewJob.job_id;
    if (previewJob.status === "failed") {
      renderSynthesisPreviewFailure(previewJob);
    } else if (previewJob.result && previewJob.result.preview_status) {
      renderSynthesisPreview(previewJob.result || {});
    }
  }
}

function renderAnswer(result) {
  setText("answer-status", result.answer_status || "unknown");
  setText("answer-text", result.answer || "暂无回答文本。");
  setText("analysis-text", result.analysis || "暂无分析。");
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
      <td><button type="button" class="link-button" data-claim-id="${escapeHtml(citation.claim_id || "")}">${escapeHtml(citation.claim_id || "")}</button></td>
      <td><button type="button" class="link-button" data-source-id="${escapeHtml(citation.source_id || "")}">${escapeHtml(citation.source_id || "")}</button></td>
      <td>${escapeHtml(citation.citation_locator || "")}</td>
      <td>${escapeHtml(citation.page_path || "")}</td>
    </tr>
  `);
  setTable("citations-table", rows, 4);
}

function renderEvidence(contexts) {
  const rows = contexts.map((context) => `
    <tr>
      <td><button type="button" class="link-button" data-claim-id="${escapeHtml(context.claim_id || "")}">${escapeHtml(context.claim_id || "")}</button><span>${escapeHtml(context.claim_text || "")}</span></td>
      <td><button type="button" class="link-button" data-source-id="${escapeHtml(context.source_id || "")}">${escapeHtml(context.source_id || "")}</button></td>
      <td>${escapeHtml(context.citation_locator || "")}</td>
      <td>${escapeHtml(context.page_path || "")}</td>
    </tr>
  `);
  setTable("evidence-table", rows, 4);
}

function renderSynthesisPreview(result) {
  setText("synthesis-status", `预览状态：${result.preview_status || "preview"} / 动作：${result.action || "unknown"}`);
  setText("synthesis-preview-text", result.preview_text || JSON.stringify(result.synthesis_plan || {}, null, 2));
}

function renderSynthesisPreviewFailure(job) {
  const reason = job.failure_reason || job.result?.error || "未知失败原因";
  setText("synthesis-status", `综合预览失败：${job.job_id}`);
  setText("synthesis-preview-text", `综合预览失败\n任务：${job.job_id}\n原因：${reason}`);
}

function renderRuns(runs) {
  setText("runs-table-count", `${runs.length} 行`);
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
  setText("pages-table-count", `${pages.length} 行`);
  const rows = pages.map((page) => `
    <tr>
      <td><button type="button" class="link-button" data-page-id="${escapeHtml(page.page_id || "")}">${escapeHtml(page.title || page.page_id)}</button><span>${escapeHtml(page.page_id || "")}</span></td>
      <td>${escapeHtml(page.page_type || "")}</td>
      <td>${escapeHtml(page.path || "")}</td>
      <td>${escapeHtml(String(page.claim_count || 0))}</td>
    </tr>
  `);
  setTable("pages-table", rows, 4);
}

function renderClaimBrowser(claims, total) {
  setText("claim-browser-count", `${claims.length} / ${total} 行`);
  const rows = claims.map((claim) => `
    <tr>
      <td><button type="button" class="link-button" data-claim-id="${escapeHtml(claim.claim_id || "")}">${escapeHtml(claim.claim_id || "")}</button><span>${escapeHtml(claim.claim_text || "")}</span></td>
      <td><button type="button" class="link-button" data-source-id="${escapeHtml(claim.source_id || "")}">${escapeHtml(claim.source_title || claim.source_id || "")}</button><span>${escapeHtml(claim.source_id || "")}</span></td>
      <td>${escapeHtml(claim.confidence_status || "")}</td>
      <td>${escapeHtml((claim.relationship_types || []).join(", "))}</td>
      <td>${escapeHtml(claim.citation_locator || "")}<span>${escapeHtml(claim.page?.path || "")}</span></td>
    </tr>
  `);
  setTable("claim-browser-table", rows, 5);
}

function renderWikiBrowser(pages) {
  const query = (document.querySelector("#wiki-query")?.value || "").trim().toLowerCase();
  const pageType = document.querySelector("#wiki-page-type")?.value || "";
  const filtered = pages.filter((page) => {
    const matchesType = !pageType || page.page_type === pageType;
    const haystack = `${page.title || ""} ${page.page_id || ""} ${page.path || ""}`.toLowerCase();
    const matchesQuery = !query || haystack.includes(query);
    return matchesType && matchesQuery;
  });
  setText("wiki-browser-count", `${filtered.length} 行`);
  const rows = filtered.map((page) => `
    <tr>
      <td><button type="button" class="link-button" data-page-id="${escapeHtml(page.page_id || "")}">${escapeHtml(page.title || page.page_id)}</button><span>${escapeHtml(page.page_id || "")}</span></td>
      <td>${escapeHtml(page.page_type || "")}</td>
      <td>${escapeHtml(page.path || "")}</td>
      <td>${escapeHtml(String(page.claim_count || 0))}</td>
    </tr>
  `);
  setTable("wiki-browser-table", rows, 4);
}

function renderClaimDetail(payload) {
  const claim = payload.claim || {};
  const context = payload.locator_context || {};
  setText("browser-detail-title", "声明详情");
  setText("browser-detail-status", `${claim.claim_id || ""} / ${claim.confidence_status || ""}`);
  setDetailMeta([
    ["claim_id", claim.claim_id],
    ["source_id", claim.source_id],
    ["confidence_status", claim.confidence_status],
    ["citation_locator", claim.citation_locator],
    ["locator_status", context.status]
  ]);
  setText(
    "browser-detail-text",
    [
      "Catalog-Backed Claim",
      claim.claim_text || "",
      "",
      "Citation Context",
      context.text || "无可显示定位上下文。",
      "",
      ...(payload.warnings || []).map((warning) => `Warning: ${warning.message || ""}`)
    ].join("\n")
  );
  renderBrowserRelationships(payload.relationships || []);
  renderBrowserRelatedClaims([]);
}

function renderSourceDetail(payload) {
  const source = payload.source || {};
  setText("browser-detail-title", "资料源详情");
  setText("browser-detail-status", `${source.source_id || ""} / ${source.status || ""}`);
  setDetailMeta([
    ["source_id", source.source_id],
    ["source_type", source.source_type],
    ["status", source.status],
    ["raw_path", source.raw_path],
    ["normalized_path", source.normalized_path],
    ["latest_run", payload.latest_run?.run_id || ""]
  ]);
  setText(
    "browser-detail-text",
    [
      source.title || "",
      "",
      "Metadata",
      JSON.stringify(payload.metadata || {}, null, 2),
      "",
      "Sidecars",
      JSON.stringify(payload.sidecars || {}, null, 2)
    ].join("\n")
  );
  renderBrowserRelationships(payload.relationships || []);
  renderBrowserRelatedClaims(payload.claims || []);
}

function renderPageDetail(payload) {
  const page = payload.page || {};
  setText("browser-detail-title", "页面详情");
  setText("browser-detail-status", `${page.page_id || ""} / ${page.page_type || ""}`);
  setDetailMeta([
    ["page_id", page.page_id],
    ["page_type", page.page_type],
    ["path", page.path],
    ["markdown_is_evidence", String(Boolean(payload.markdown_is_evidence))],
    ["aliases", (payload.aliases || []).join(", ")]
  ]);
  setText(
    "browser-detail-text",
    [
      "Page Markdown",
      "这是当前 Wiki 页面文本，不等同于 formal evidence。",
      "",
      payload.markdown || "无页面文本。"
    ].join("\n")
  );
  renderBrowserRelationships(payload.relationships || []);
  renderBrowserRelatedClaims(payload.related_claims || []);
}

function setDetailMeta(items) {
  const target = document.querySelector("#browser-detail-meta");
  if (!target) {
    return;
  }
  target.innerHTML = items.map(([label, value]) => `
    <div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value || "")}</strong></div>
  `).join("");
}

function renderBrowserRelationships(relationships) {
  const rows = relationships.map((item) => `
    <tr>
      <td>${escapeHtml(item.subject_id || "")}<span>${escapeHtml(item.subject_title || "")}</span></td>
      <td>${escapeHtml(item.relationship_type || "")}</td>
      <td>${escapeHtml(item.object_id || "")}<span>${escapeHtml(item.object_title || "")}</span></td>
      <td><button type="button" class="link-button" data-claim-id="${escapeHtml(item.evidence_claim_id || "")}">${escapeHtml(item.evidence_claim_id || "")}</button><span>${escapeHtml(item.source_id || "")}</span></td>
    </tr>
  `);
  setTable("browser-relationships-table", rows, 4);
}

function renderBrowserRelatedClaims(claims) {
  const rows = claims.map((claim) => `
    <tr>
      <td><button type="button" class="link-button" data-claim-id="${escapeHtml(claim.claim_id || "")}">${escapeHtml(claim.claim_id || "")}</button><span>${escapeHtml(claim.claim_text || "")}</span></td>
      <td><button type="button" class="link-button" data-source-id="${escapeHtml(claim.source_id || "")}">${escapeHtml(claim.source_id || "")}</button></td>
      <td>${escapeHtml(claim.citation_locator || "")}</td>
    </tr>
  `);
  setTable("browser-related-claims-table", rows, 3);
}

function renderWarnings(warnings) {
  const list = document.querySelector("#warnings-list");
  if (!list) {
    return;
  }
  if (!warnings.length) {
    list.innerHTML = '<li class="muted">暂无警告。</li>';
    return;
  }
  list.innerHTML = warnings.map((warning) => `<li><strong>${escapeHtml(displayWarningCategory(warning.category))}</strong> ${escapeHtml(warning.message || "")}</li>`).join("");
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
  target.innerHTML = rows.length ? rows.join("") : `<tr><td colspan="${colspan}" class="muted">无数据。</td></tr>`;
}

function setList(id, items) {
  const target = document.querySelector(`#${id}`);
  if (!target) {
    return;
  }
  target.innerHTML = items.length ? items.map((item) => `<li>${escapeHtml(item)}</li>`).join("") : '<li class="muted">无。</li>';
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

function displayWarningCategory(category) {
  const labels = {
    source: "资料源",
    ask: "问答",
    synthesis: "综合",
    evidence: "证据",
    browser: "浏览",
    dashboard: "工作台",
    general: "一般"
  };
  return labels[category] || category || "一般";
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

document.querySelector("#claim-browser-form")?.addEventListener("submit", (event) => {
  loadClaimBrowser(event).catch(showLoadError);
});

document.querySelector("#wiki-browser-form")?.addEventListener("submit", (event) => {
  submitWikiBrowser(event);
});

document.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof Element)) {
    return;
  }
  const claimButton = target.closest("[data-claim-id]");
  if (claimButton) {
    loadClaimDetail(claimButton.getAttribute("data-claim-id") || "").catch(showLoadError);
    return;
  }
  const sourceButton = target.closest("[data-source-id]");
  if (sourceButton) {
    loadSourceDetail(sourceButton.getAttribute("data-source-id") || "").catch(showLoadError);
    return;
  }
  const pageButton = target.closest("[data-page-id]");
  if (pageButton) {
    loadPageDetail(pageButton.getAttribute("data-page-id") || "").catch(showLoadError);
  }
});

function showLoadError(error) {
  setText("status-value", "error");
  renderWarnings([{ category: "工作台", message: `无法加载工作台：${error.message}` }]);
}

loadDashboard().catch(showLoadError);
