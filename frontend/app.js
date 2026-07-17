"use strict";

// ---------------------------------------------------------------------------
// 基础工具
// ---------------------------------------------------------------------------
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

function escapeHtml(s) {
  if (s === null || s === undefined) return "";
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.add("hidden"), 2200);
}

async function apiGet(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path} -> ${r.status}`);
  return r.json();
}
async function apiPost(path, body) {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  let data = null;
  try { data = await r.json(); } catch (_) {}
  if (!r.ok) {
    const detail = (data && data.detail) || `HTTP ${r.status}`;
    throw new Error(detail);
  }
  return data;
}
async function apiPatch(path, body) {
  const r = await fetch(path, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => null);
  if (!r.ok) throw new Error((data && data.detail) || `HTTP ${r.status}`);
  return data;
}
async function apiDelete(path) {
  const r = await fetch(path, { method: "DELETE" });
  const data = await r.json().catch(() => null);
  if (!r.ok) throw new Error((data && data.detail) || `HTTP ${r.status}`);
  return data;
}

// ---------------------------------------------------------------------------
// 状态（本地会话模拟）
// ---------------------------------------------------------------------------
function _loadUserMeta() {
  try { return JSON.parse(localStorage.getItem("cia_user_meta") || "null"); }
  catch (_) { return null; }
}
const state = {
  uid: localStorage.getItem("cia_uid") || null,
  loggedIn: localStorage.getItem("cia_logged") === "1",
  userMeta: _loadUserMeta(),        // {display_name, avatar, persona}
  consent: localStorage.getItem("cia_consent_" + (localStorage.getItem("cia_uid") || "")) === "1",
  profile: null,
  competitions: [],
  evidenceCache: {}, // competition_id -> [evidence]
};

const CAT_LABEL = {
  programming: "程序设计", modeling: "数学建模",
  innovation: "创新创业", software: "软件作品",
};
const STATUS_LABEL = {
  highly_suitable: "高度适合", suitable: "比较适合",
  marginal: "可参加·需补充", not_prioritized: "不优先推荐",
  candidate_only: "候选信息·未评分",
  ineligible: "不符合·一票否决",
};
const FACTTAG_CLASS = {
  "官方规则": "fact", "系统计算": "system",
  "智能建议": "suggest", "待人工确认": "pending",
};

// ---------------------------------------------------------------------------
// 引用证据弹窗
// ---------------------------------------------------------------------------
let currentEvidence = [];

function openCiteModal(i) {
  const e = currentEvidence[i];
  if (!e) return;
  const page = e.page === null || e.page === undefined ? "未定位" : `第 ${e.page} 页`;
  $("#cite-body").innerHTML = `
    <div class="kv"><span class="k">佐证字段</span><span class="v">${escapeHtml(e.field)}</span></div>
    <div class="kv"><span class="k">文档</span><span class="v">${escapeHtml(e.document_name || "—")}</span></div>
    <div class="kv"><span class="k">页码</span><span class="v">${page}</span></div>
    <div class="kv"><span class="k">可信等级</span><span class="v">${escapeHtml(e.trusted_level || "—")} 级</span></div>
    <div class="kv"><span class="k">获取日期</span><span class="v">${escapeHtml(e.acquired_date || "—")}</span></div>
    <div class="kv"><span class="k">最后核验</span><span class="v">${escapeHtml(e.last_verified_at || "—")}</span></div>
    <div class="kv"><span class="k">官方链接</span><span class="v">${
      e.source_url ? `<a href="${escapeHtml(e.source_url)}" target="_blank" rel="noopener">${escapeHtml(e.source_url)}</a>` : "—"
    }</span></div>
    <div class="section"><h3>原文片段</h3>
      <p style="background:#f8fafc;border-left:3px solid var(--fact);padding:10px;border-radius:6px;">${escapeHtml(e.source_text)}</p>
    </div>`;
  $("#cite-modal").classList.remove("hidden");
}

function citeChips(evidence) {
  currentEvidence = evidence || [];
  if (!currentEvidence.length) return `<span class="muted">（暂无引用证据）</span>`;
  return currentEvidence.map((e, i) =>
    `<span class="cite-chip" data-cite="${i}" title="点击查看原文证据">引用 ${i + 1}</span>`
  ).join("");
}

// 依据 field 过滤出对应证据角标
function chipsForField(evidence, field) {
  const list = (evidence || []).filter((e) => e.field === field);
  if (!list.length) return "";
  return " " + list.map((e, i) => {
    const idx = currentEvidence.indexOf(e);
    return `<span class="cite-chip" data-cite="${idx}" title="点击查看原文证据">${escapeHtml(e.field)}</span>`;
  }).join("");
}

// ---------------------------------------------------------------------------
// 路由
// ---------------------------------------------------------------------------
function showView(name) {
  $$(".view").forEach((v) => v.classList.add("hidden"));
  $("#view-" + name).classList.remove("hidden");
  $$(".topnav nav a").forEach((a) => {
    a.classList.toggle("active", a.dataset.nav === name);
  });
}

function router() {
  const hash = location.hash || "#/hall";
  const parts = hash.replace(/^#\//, "").split("/");
  if (parts[0] === "agent") {
    showView("agent");
    renderAgentView();
    return;
  }
  if (parts[0] === "admin") {
    showView("admin");
    renderAdminView();
    return;
  }
  if (parts[0] === "projects") {
    showView("projects");
    renderProjects();
    return;
  }
  if (parts[0] === "detail" && parts[1]) {
    showView("detail");
    renderDetail(parts[1]);
  } else if (parts[0] === "profile") {
    showView("profile");
    renderProfile();
  } else if (parts[0] === "recommend") {
    showView("recommend");
    renderRecommend();
  } else {
    showView("hall");
    renderHall();
  }
}

// ---------------------------------------------------------------------------
// 画像页
// ---------------------------------------------------------------------------
async function renderProfile() {
  updateUserChip();
  if (!state.consent) { openConsentModal(); return; }
  try {
    const p = await apiGet(`/api/users/${state.uid}/profile`);
    $("#f-education").value = p.education_level;
    $("#f-grade").value = p.grade;
    $("#f-major").value = p.major;
    $("#f-hours").value = p.weekly_available_hours;
    $("#f-team").value = p.expected_team_size;
    $("#f-skills").value = (p.skills || []).join(", ");
    $("#f-exp").value = (p.experiences || []).join(", ");
    $("#f-consent").checked = true;
    $("#profile-msg").textContent = "已加载已保存画像。";
    $("#profile-msg").className = "msg ok";
  } catch (_) {
    $("#profile-msg").textContent = "尚未保存画像，请填写后保存。";
    $("#profile-msg").className = "msg";
  }
}

$("#profile-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const consent = $("#f-consent").checked;
  if (!consent) {
    $("#profile-msg").textContent = "请先勾选隐私授权。";
    $("#profile-msg").className = "msg err";
    return;
  }
  const payload = {
    user_id: state.uid,
    education_level: $("#f-education").value,
    grade: $("#f-grade").value,
    major: $("#f-major").value,
    skills: $("#f-skills").value.split(",").map((s) => s.trim()).filter(Boolean),
    experiences: $("#f-exp").value.split(",").map((s) => s.trim()).filter(Boolean),
    weekly_available_hours: Number($("#f-hours").value) || 0,
    expected_team_size: Number($("#f-team").value) || 1,
    privacy_consent: true,
  };
  try {
    await apiPost(`/api/users/${state.uid}/profile`, payload);
    localStorage.setItem("cia_consent_" + state.uid, "1");
    state.consent = true;
    state.profile = payload;
    updateUserChip();
    $("#profile-msg").textContent = "已保存到数据库。";
    $("#profile-msg").className = "msg ok";
    toast("画像已保存");
  } catch (err) {
    $("#profile-msg").textContent = "保存失败：" + err.message;
    $("#profile-msg").className = "msg err";
  }
});

$("#profile-delete").addEventListener("click", async () => {
  if (!state.uid || !confirm("确认删除个人画像及全部项目数据？赛事与官方证据不会被删除。")) return;
  try {
    await apiDelete(`/api/users/${encodeURIComponent(state.uid)}/profile`);
    localStorage.removeItem("cia_consent_" + state.uid);
    state.consent = false;
    state.profile = null;
    toast("画像与项目数据已删除");
    logout();
  } catch (err) {
    toast("删除失败：" + err.message);
  }
});

// ---------------------------------------------------------------------------
// 隐私授权弹窗
// ---------------------------------------------------------------------------
function openConsentModal() {
  $("#consent-modal").classList.remove("hidden");
}
$("#consent-check").addEventListener("change", (e) => {
  $("#consent-ok").disabled = !e.target.checked;
});
$("#consent-ok").addEventListener("click", () => {
  if (!$("#consent-check").checked) return;
  localStorage.setItem("cia_consent_" + state.uid, "1");
  state.consent = true;
  $("#consent-modal").classList.add("hidden");
  updateUserChip();
  renderProfile();
});
$("#consent-cancel").addEventListener("click", () => {
  $("#consent-modal").classList.add("hidden");
  toast("您可继续浏览公开赛事");
});

function updateUserChip() {
  const chip = $("#user-chip");
  const switchBtn = $("#switch-user-btn");
  if (!state.loggedIn || !state.uid) {
    chip.textContent = "未登录";
    chip.title = "";
    if (switchBtn) switchBtn.classList.add("hidden");
    return;
  }
  const m = state.userMeta || {};
  const name = m.display_name || state.uid;
  const avatar = monogram(name);
  chip.innerHTML = `<span class="chip-avatar">${escapeHtml(avatar)}</span>` +
    `<span class="chip-name">${escapeHtml(name)}</span>`;
  chip.title = m.persona || "";
  if (switchBtn) switchBtn.classList.remove("hidden");
}

function monogram(name) {
  const value = String(name || "U").trim();
  return Array.from(value).slice(0, 2).join("").toUpperCase();
}

// ---------------------------------------------------------------------------
// 赛事大厅
// ---------------------------------------------------------------------------
async function renderHall() {
  const cat = $("#filter-cat").value;
  const year = $("#filter-year").value;
  let url = "/api/competitions";
  const qs = [];
  if (cat) qs.push("category=" + encodeURIComponent(cat));
  if (year) qs.push("year=" + encodeURIComponent(year));
  if (qs.length) url += "?" + qs.join("&");

  let list;
  try {
    list = await apiGet(url);
  } catch (err) {
    $("#hall-list").innerHTML = `<div class="card">加载失败：${escapeHtml(err.message)}</div>`;
    return;
  }
  state.competitions = list;

  // 年份下拉
  const years = Array.from(new Set(list.map((c) => c.document_year))).sort((a, b) => b - a);
  const yearSel = $("#filter-year");
  const cur = yearSel.value;
  yearSel.innerHTML = `<option value="">全部年份</option>` +
    years.map((y) => `<option value="${y}">${y}</option>`).join("");
  if (cur) yearSel.value = cur;

  if (!list.length) {
    $("#hall-list").innerHTML = `<div class="card muted">暂无赛事。</div>`;
    return;
  }
  $("#hall-list").innerHTML = list.map((c) => {
    const pending = c.data_status !== "verified";
    const trustCls = "trust-" + (c.trusted_level || "C");
    return `<article class="card comp-card ${pending ? "is-pending" : "is-verified"}" data-id="${escapeHtml(c.competition_id)}" tabindex="0">
      <div class="comp-card-main">
        <div class="comp-kicker">${escapeHtml(c.competition_id)}</div>
        <div class="comp-title">${escapeHtml(c.competition_name)}</div>
        <div class="comp-meta">
          <span class="tag cat">${CAT_LABEL[c.category] || c.category}</span>
          <span class="tag year">${c.document_year}</span>
          <span class="tag ${trustCls}">可信 ${escapeHtml(c.trusted_level || "C")} 级</span>
          ${pending ? `<span class="tag pending">待人工确认</span>` : `<span class="tag status-verified">已确认</span>`}
        </div>
      </div>
      <div class="comp-card-side"><span>报名截止</span><strong>${escapeHtml(c.registration_deadline || "未明确")}</strong><i aria-hidden="true">→</i></div>
    </article>`;
  }).join("");

  $$("#hall-list .comp-card").forEach((el) => {
    el.addEventListener("click", () => {
      location.hash = "#/detail/" + el.dataset.id;
    });
    el.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") el.click();
    });
  });
}

$("#filter-cat").addEventListener("change", renderHall);
$("#filter-year").addEventListener("change", renderHall);

// ---------------------------------------------------------------------------
// 赛事详情
// ---------------------------------------------------------------------------
async function renderDetail(id) {
  let detail;
  try {
    detail = await apiGet("/api/competitions/" + encodeURIComponent(id));
  } catch (err) {
    $("#detail-content").innerHTML = `<div class="card">加载失败：${escapeHtml(err.message)}</div>`;
    return;
  }
  const c = detail.competition;
  const ev = c.evidence || [];
  // 重新构建全局 evidence 索引（保证 data-cite 指向正确）
  currentEvidence = ev;

  const pending = c.data_status !== "verified";
  const trustCls = "trust-" + (c.trusted_level || "C");

  const kv = (k, v, field) =>
    `<div class="kv"><span class="k">${escapeHtml(k)}</span><span class="v">${v}${
      field ? chipsForField(ev, field) : ""
    }</span></div>`;

  const grades = c.allowed_grades && c.allowed_grades.length ? c.allowed_grades.join("、") : "不限年级";
  const majors = c.allowed_majors && c.allowed_majors.length ? c.allowed_majors.join("、") : "不限专业";
  const teamTxt = `${c.team_min ?? 1}—${c.team_max ?? 1} 人${c.team_required ? "（组队赛）" : "（个人或组队）"}`;

  const timelineHtml = (detail.timeline || []).map((t) =>
    `<div class="kv"><span class="k">${escapeHtml(t.label)}</span><span class="v">${escapeHtml(t.event_date || t.date_text || "—")}</span></div>`
  ).join("") || `<div class="muted">暂无时间轴</div>`;

  const reqHtml = (detail.requirements || []).map((r) => {
    const cls = FACTTAG_CLASS[r.tag] || "system";
    return `<div class="kv"><span class="tag ${cls}">${escapeHtml(r.tag)}</span><span class="v">${escapeHtml(r.text)}</span></div>`;
  }).join("");

  const sourcesHtml = (detail.sources || []).map((s) =>
    `<div class="kv"><span class="k">${escapeHtml(s.name || "来源")}</span><span class="v">${
      s.url ? `<a href="${escapeHtml(s.url)}" target="_blank" rel="noopener">${escapeHtml(s.url)}</a>` : "—"
    }（获取 ${escapeHtml(s.acquired_date || "—")}）</span></div>`
  ).join("");

  const evHtml = ev.length ? ev.map((e, i) =>
    `<div class="kv"><span class="k">${escapeHtml(e.field)}</span><span class="v">
      <span class="cite-chip" data-cite="${i}">查看依据</span>
      <span class="muted">${escapeHtml((e.document_name || "") + (e.page ? " 第" + e.page + "页" : ""))}</span>
    </span></div>`
  ).join("") : `<div class="muted">暂无引用证据</div>`;

  const legend = `<div class="factnote">
    <span class="tag fact">官方规则</span>
    <span class="tag system">系统计算</span>
    <span class="tag suggest">智能建议</span>
    <span class="tag pending">待人工确认</span>
  </div>`;

  $("#detail-content").innerHTML = `
    <div class="card">
      <div class="detail-head"><div>
      <div class="comp-title detail-title">${escapeHtml(c.competition_name)}</div>
      <div class="comp-meta">
        <span class="tag cat">${CAT_LABEL[c.category] || c.category}</span>
        <span class="tag year">${c.document_year}</span>
        <span class="tag ${trustCls}">可信 ${escapeHtml(c.trusted_level || "C")} 级</span>
        ${pending ? `<span class="tag pending">待人工确认</span>` : `<span class="tag status-verified">已确认</span>`}
        ${detail.verification && detail.verification.note ? `<span class="muted">${escapeHtml(detail.verification.note)}</span>` : ""}
      </div>
      </div><button id="join-project" class="btn primary" ${pending ? "disabled" : ""}>加入我的项目</button></div>
      ${pending ? `<div class="verification-alert">该信息仍待人工确认，报名前请访问官方页面复核。最后核验：${escapeHtml(c.last_verified_at || "—")}</div>` : ""}
    </div>

    <div class="section"><h3>资格要求</h3><div class="card">
      ${kv("参赛对象", (c.eligible_students || []).join("、") || "—", "eligible_students")}
      ${kv("年级要求", grades, "allowed_grades")}
      ${kv("专业要求", majors, "allowed_majors")}
      ${kv("团队规模", teamTxt, "team_max")}
    </div></div>

    <div class="section"><h3>时间要求</h3><div class="card">
      ${kv("报名截止", escapeHtml(c.registration_deadline || "未明确"), "registration_deadline")}
      ${kv("提交截止", escapeHtml(c.submission_deadline || "未明确"), "submission_deadline")}
    </div></div>

    <div class="section"><h3>材料与能力</h3><div class="card">
      ${kv("所需材料", (c.required_materials || []).join("、") || "—", "required_materials")}
      ${kv("所需技能", (c.required_skills || []).join("、") || "—", "required_skills")}
      ${kv("评价维度", (c.evaluation_dimensions || []).join("、") || "—", "")}
    </div></div>

    <div class="section"><h3>时间轴</h3><div class="card">${timelineHtml}</div></div>

    <div class="section"><h3>要求条目（事实 / 计算 / 建议 分层）</h3><div class="card">${reqHtml}</div>${legend}</div>

    <div class="section"><h3>来源与可信</h3><div class="card">
      ${kv("数据状态", `<span class="tag status-${escapeHtml(c.data_status)}">${escapeHtml(c.data_status)}</span>`, "")}
      ${kv("版本", escapeHtml(c.doc_version || "—"), "")}
      ${kv("最后核验", escapeHtml(c.last_verified_at || "—"), "")}
      ${sourcesHtml}
    </div></div>

    <div class="section"><h3>引用证据（点击角标查看原文）</h3><div class="card">${evHtml}</div></div>

    <div class="section"><h3>官方规则检索（赛事隔离 RAG）</h3>
      <div class="card">
        <p class="muted" style="margin-top:0;">仅在本赛事（${escapeHtml(c.competition_id)}）范围内检索，不会串入其他赛事或年份的规则。命中结果给出原文与官方链接。</p>
        <div class="row">
          <input id="rag-q" type="text" placeholder="如：团队人数要求 / 报名截止 / 需要哪些材料" style="flex:1;min-width:220px;" />
          <button id="rag-btn" class="btn primary">检索</button>
        </div>
        <div class="row" style="gap:6px;flex-wrap:wrap;margin-top:6px;">
          ${["团队人数要求", "报名截止时间", "参赛对象", "需要提交哪些材料"].map((s) =>
            `<span class="rag-example tag" data-q="${escapeHtml(s)}" style="cursor:pointer;">${escapeHtml(s)}</span>`
          ).join("")}
        </div>
        <div id="rag-result" style="margin-top:10px;"></div>
      </div>
    </div>
  `;

  $$("#detail-content .cite-chip").forEach((el) => {
    el.addEventListener("click", () => openCiteModal(Number(el.dataset.cite)));
  });
  $("#join-project").addEventListener("click", () => joinProject(c.competition_id));

  // RAG 检索交互
  const runRag = () => ragSearch(c.competition_id, c.document_year);
  $("#rag-btn").addEventListener("click", runRag);
  $("#rag-q").addEventListener("keydown", (e) => { if (e.key === "Enter") runRag(); });
  $$("#detail-content .rag-example").forEach((el) => {
    el.addEventListener("click", () => { $("#rag-q").value = el.dataset.q; runRag(); });
  });
}

// 赛事隔离 RAG 检索：结果复用引用弹窗
async function ragSearch(compId, year) {
  const q = ($("#rag-q").value || "").trim();
  const box = $("#rag-result");
  if (!q) { box.innerHTML = `<div class="muted">请输入检索问题。</div>`; return; }
  box.innerHTML = `<div class="muted">检索中…</div>`;
  const url = `/api/rag/search?competition_id=${encodeURIComponent(compId)}&q=${encodeURIComponent(q)}`
    + (year ? `&year=${encodeURIComponent(year)}` : "") + `&top_k=3`;
  let hits;
  try {
    hits = await apiGet(url);
  } catch (err) {
    box.innerHTML = `<div class="muted">检索失败：${escapeHtml(err.message)}</div>`;
    return;
  }
  if (!hits.length) {
    box.innerHTML = `<div class="card" style="border-left:3px solid var(--pending);">
      当前资料不足，无法可靠确认该问题。建议查看赛事官方网站或联系官方咨询。</div>`;
    return;
  }
  // 追加到全局证据数组，复用弹窗
  const base = currentEvidence.length;
  hits.forEach((h) => currentEvidence.push(h));
  box.innerHTML = hits.map((h, i) => {
    const idx = base + i;
    const page = (h.page === null || h.page === undefined) ? "未定位" : `第 ${h.page} 页`;
    return `<div class="card" style="margin-bottom:8px;">
      <div class="row between">
        <span class="tag fact">命中字段：${escapeHtml(h.field)}</span>
        <span class="cite-chip" data-cite="${idx}">查看依据（${page} · ${escapeHtml(h.trusted_level || "A")}级）</span>
      </div>
      <p style="margin:8px 0 0;background:#f8fafc;border-left:3px solid var(--fact);padding:10px;border-radius:6px;">${escapeHtml(h.source_text)}</p>
    </div>`;
  }).join("");
  bindCiteChips(box);
}

// ---------------------------------------------------------------------------
// 我的推荐
// ---------------------------------------------------------------------------
async function renderRecommend() {
  if (!state.consent) {
    $("#recommend-hint").textContent = "请先在「我的画像」中阅读并同意隐私授权，再查看个性化推荐。";
    $("#recommend-list").innerHTML = "";
    return;
  }
  let recs;
  try {
    recs = await apiGet(`/api/users/${state.uid}/recommendations`);
  } catch (err) {
    $("#recommend-hint").textContent = "暂无个性化画像，请先保存画像。";
    $("#recommend-list").innerHTML = "";
    return;
  }
  const formalCount = recs.filter((r) => r.eligible).length;
  const candidateCount = recs.filter((r) => r.recommendation_status === "candidate_only").length;
  $("#recommend-hint").textContent = `共 ${recs.length} 项赛事：${formalCount} 项正式推荐，${candidateCount} 项待核验候选。只有已核验且通过硬性门控的赛事才会评分。`;

  // 排序：可推荐在前
  const order = { highly_suitable: 0, suitable: 1, marginal: 2, not_prioritized: 3, candidate_only: 4, ineligible: 5 };
  recs.sort((a, b) => (order[a.recommendation_status] ?? 9) - (order[b.recommendation_status] ?? 9));

  $("#recommend-list").innerHTML = recs.map((r, idx) => {
    const score = r.score === null ? "—" : Math.round(r.score * 10) / 10;
    const statusCls = r.recommendation_status === "ineligible" ? "status-stale"
      : r.recommendation_status === "highly_suitable" ? "status-verified"
      : "status-unverified";
    const gate = (r.gate_reasons || []).map((g) =>
      `<div class="gate-reason">✕ ${escapeHtml(g.reason)}${g.possible_action ? `（${escapeHtml(g.possible_action)}）` : ""}</div>`
    ).join("");
    const explain = Object.entries(r.explanation || {}).map(([k, v]) => {
      const val = Array.isArray(v) ? v.join("；") : String(v);
      return `<li><b>${escapeHtml(k)}：</b>${escapeHtml(val)}</li>`;
    }).join("");
    const tags = [
      `<span class="tag ${statusCls}">${STATUS_LABEL[r.recommendation_status] || r.recommendation_status}</span>`,
      r.urgent ? `<span class="tag urgent">临近截止</span>` : "",
      r.pending_review ? `<span class="tag pending">待人工确认</span>` : "",
    ].join("");
    return `<article class="card rec-card rec-${escapeHtml(r.recommendation_status)}" data-id="${escapeHtml(r.competition_id)}" data-idx="${idx}">
      <div class="rec-head">
        <div><div class="comp-kicker">${escapeHtml(r.competition_id)}</div><div class="comp-title">${escapeHtml(r.competition_name)}</div></div>
        <div class="score-pill"><span>匹配度</span><strong>${score}</strong></div>
      </div>
      <div class="comp-meta">${tags}</div>
      ${gate}
      ${explain ? `<ul class="explain">${explain}</ul>` : ""}
      ${r.recommendation_status === "candidate_only" ? `<div class="muted" style="font-size:12px;margin-top:6px;">该赛事仅作为候选信息展示，完成人工核验前不会进行资格判断或匹配评分。</div>` : ""}
      <div class="row"><button class="btn cite-btn" data-id="${escapeHtml(r.competition_id)}">查看官方依据</button>
      ${r.eligible && !r.pending_review ? `<button class="btn primary join-btn" data-id="${escapeHtml(r.competition_id)}">加入我的项目</button>` : ""}</div>
      <div class="cite-list" id="cite-${idx}" style="margin-top:8px;"></div>
    </article>`;
  }).join("");

  $$("#recommend-list .cite-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = btn.closest(".rec-card").querySelector(".cite-list");
      loadCitations(btn.dataset.id, target);
    });
  });
  $$("#recommend-list .join-btn").forEach((btn) => {
    btn.addEventListener("click", () => joinProject(btn.dataset.id));
  });
}

async function joinProject(competitionId) {
  if (!state.consent || !state.uid) {
    toast("请先保存并授权个人画像");
    location.hash = "#/profile";
    return;
  }
  try {
    await apiPost(`/api/users/${encodeURIComponent(state.uid)}/projects`, { competition_id: competitionId });
    toast("已加入我的项目");
    location.hash = "#/projects";
  } catch (err) {
    toast(err.message);
  }
}

// ---------------------------------------------------------------------------
// 我的项目：任务、材料、状态与日历
// ---------------------------------------------------------------------------
const PROJECT_STATUS = { planned: "待开始", in_progress: "进行中", completed: "已完成" };

async function renderProjects() {
  const box = $("#project-list");
  if (!state.consent || !state.uid) {
    box.innerHTML = '<div class="empty-state">请先保存个人画像，再管理参赛项目。</div>';
    return;
  }
  let projects;
  try {
    projects = await apiGet(`/api/users/${encodeURIComponent(state.uid)}/projects`);
  } catch (err) {
    box.innerHTML = `<div class="empty-state">${escapeHtml(err.message)}</div>`;
    return;
  }
  if (!projects.length) {
    box.innerHTML = '<div class="empty-state"><b>还没有参赛项目</b><span>从赛事详情或正式推荐中点击“加入我的项目”。</span></div>';
    return;
  }
  box.innerHTML = projects.map((p) => {
    const tasks = p.items.filter((i) => i.item_type === "task");
    const materials = p.items.filter((i) => i.item_type === "material");
    const done = p.items.filter((i) => i.status === "done").length;
    const pct = p.items.length ? Math.round(done / p.items.length * 100) : 0;
    const renderItems = (items, empty) => items.length ? items.map((i) => `
      <div class="project-item ${i.status === "done" ? "done" : ""}">
        <input class="item-toggle" type="checkbox" data-pid="${p.project_id}" data-iid="${i.item_id}" ${i.status === "done" ? "checked" : ""} />
        <span class="item-title">${escapeHtml(i.title)}</span>
        <span class="item-date">${escapeHtml(i.due_date || "无截止")}</span>
        <button class="icon-btn item-delete" data-pid="${p.project_id}" data-iid="${i.item_id}" title="删除条目">×</button>
      </div>`).join("") : `<div class="item-empty">${empty}</div>`;
    return `<article class="project-card project-${escapeHtml(p.status)}" data-pid="${p.project_id}">
      <header class="project-head">
        <div><div class="project-kicker">${p.document_year} · ${escapeHtml(p.competition_id)}</div>
        <h3>${escapeHtml(p.competition_name)}</h3></div>
        <div class="project-actions">
          <select class="project-status" data-pid="${p.project_id}">
            ${Object.entries(PROJECT_STATUS).map(([value, label]) => `<option value="${value}" ${p.status === value ? "selected" : ""}>${label}</option>`).join("")}
          </select>
          <a class="btn" href="/api/users/${encodeURIComponent(state.uid)}/projects/${p.project_id}/calendar.ics">导出 ICS</a>
          <button class="btn danger project-delete" data-pid="${p.project_id}">删除项目</button>
        </div>
      </header>
      <div class="deadline-strip"><span>报名截止 <b>${escapeHtml(p.registration_deadline || "未明确")}</b></span><span>提交截止 <b>${escapeHtml(p.submission_deadline || "未明确")}</b></span></div>
      <div class="progress-line"><span style="width:${pct}%"></span></div><div class="progress-copy">已完成 ${done}/${p.items.length} · ${pct}%</div>
      <div class="project-columns">
        <section><h4>任务计划</h4>${renderItems(tasks, "暂无任务")}</section>
        <section><h4>材料清单</h4>${renderItems(materials, "官方通知未列明材料")}</section>
      </div>
      <form class="item-form" data-pid="${p.project_id}">
        <select name="item_type"><option value="task">任务</option><option value="material">材料</option></select>
        <input name="title" maxlength="200" placeholder="添加任务或材料" required />
        <input name="due_date" type="date" />
        <button class="btn" type="submit">添加</button>
      </form>
    </article>`;
  }).join("");

  $$(".project-status", box).forEach((el) => el.addEventListener("change", async () => {
    await apiPatch(`/api/users/${encodeURIComponent(state.uid)}/projects/${el.dataset.pid}`, { status: el.value });
    toast("项目状态已更新");
  }));
  $$(".item-toggle", box).forEach((el) => el.addEventListener("change", async () => {
    await apiPatch(`/api/users/${encodeURIComponent(state.uid)}/projects/${el.dataset.pid}/items/${el.dataset.iid}`, { status: el.checked ? "done" : "todo" });
    renderProjects();
  }));
  $$(".item-delete", box).forEach((el) => el.addEventListener("click", async () => {
    await apiDelete(`/api/users/${encodeURIComponent(state.uid)}/projects/${el.dataset.pid}/items/${el.dataset.iid}`);
    renderProjects();
  }));
  $$(".project-delete", box).forEach((el) => el.addEventListener("click", async () => {
    if (!confirm("确认删除这个项目及其任务和材料？")) return;
    await apiDelete(`/api/users/${encodeURIComponent(state.uid)}/projects/${el.dataset.pid}`);
    renderProjects();
  }));
  $$(".item-form", box).forEach((form) => form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(form);
    await apiPost(`/api/users/${encodeURIComponent(state.uid)}/projects/${form.dataset.pid}/items`, {
      item_type: data.get("item_type"), title: data.get("title"), due_date: data.get("due_date") || null,
    });
    renderProjects();
  }));
}

async function loadCitations(compId, target) {
  if (target.dataset.loaded) { target.classList.toggle("hidden"); return; }
  if (state.evidenceCache[compId]) {
    target.innerHTML = renderEvidenceList(state.evidenceCache[compId]);
    bindCiteChips(target);
    target.dataset.loaded = "1";
    return;
  }
  try {
    const detail = await apiGet("/api/competitions/" + encodeURIComponent(compId));
    const ev = detail.competition.evidence || [];
    state.evidenceCache[compId] = ev;
    target.innerHTML = renderEvidenceList(ev);
    bindCiteChips(target);
    target.dataset.loaded = "1";
  } catch (err) {
    target.innerHTML = `<div class="muted">加载依据失败：${escapeHtml(err.message)}</div>`;
  }
}

function renderEvidenceList(ev) {
  if (!ev.length) return `<div class="muted">暂无引用证据</div>`;
  // 临时加入全局索引以便点击
  const base = currentEvidence.length;
  ev.forEach((e) => currentEvidence.push(e));
  return ev.map((e, i) => {
    const idx = base + i;
    return `<div class="kv"><span class="k">${escapeHtml(e.field)}</span><span class="v">
      <span class="cite-chip" data-cite="${idx}">查看依据</span>
      <span class="muted">${escapeHtml((e.document_name || "") + (e.page ? " 第" + e.page + "页" : ""))}</span>
    </span></div>`;
  }).join("");
}
function bindCiteChips(root) {
  $$(".cite-chip", root).forEach((el) => {
    el.addEventListener("click", () => openCiteModal(Number(el.dataset.cite)));
  });
}

// ---------------------------------------------------------------------------
// 引用弹窗关闭
// ---------------------------------------------------------------------------
$("#cite-close").addEventListener("click", () => $("#cite-modal").classList.add("hidden"));
$("#cite-modal").addEventListener("click", (e) => {
  if (e.target.id === "cite-modal") $("#cite-modal").classList.add("hidden");
});
$("#consent-modal").addEventListener("click", (e) => {
  if (e.target.id === "consent-modal") $("#consent-modal").classList.add("hidden");
});

// ---------------------------------------------------------------------------
// 智能问答 Agent 闭环
// ---------------------------------------------------------------------------
async function renderAgentView() {
  // 确保赛事列表已加载（直接从该页进入时下拉需要数据）
  if (!state.competitions.length) {
    try { state.competitions = await apiGet("/api/competitions"); } catch (_) {}
  }
  // 填充赛事下拉
  const sel = $("#agent-cid");
  if (sel && (!sel.dataset.filled || state.competitions.length)) {
    const opts = [`<option value="">自动识别</option>`].concat(
      (state.competitions || []).map((c) =>
        `<option value="${escapeHtml(c.competition_id)}">${escapeHtml(c.competition_name)}（${c.document_year}）</option>`
      )
    );
    sel.innerHTML = opts.join("");
    sel.dataset.filled = "1";
  }
}

// 将答案文本中的 [1][2] 角标渲染为可点击引用
function renderAnswerWithCites(text, citeBase) {
  // text 中的 [n] 对应 citations 的索引（n-1），渲染为可点击 <span>
  return escapeHtml(text).replace(/\[(\d+)\]/g, (m, num) => {
    const idx = citeBase + (Number(num) - 1);
    return `<span class="cite" data-cite="${idx}">[${num}]</span>`;
  });
}

function cleanAgentAnswer(text) {
  return String(text || "")
    .replace(/\n+\s*[—-]+\s*引用来源\s*[—-]+\s*\n[\s\S]*$/u, "")
    .trim();
}

const INTENT_LABEL = {
  qa: "规则问答", detail: "赛事介绍", recommend: "个性化推荐",
  team: "组队文案", unknown: "需要补充信息",
};

async function agentAsk() {
  const qEl = $("#agent-q");
  const q = (qEl.value || "").trim();
  if (!q) { toast("请输入问题"); return; }
  const sendBtn = $("#agent-send");
  if (sendBtn.disabled) return;
  const useProfile = $("#agent-use-profile").checked;
  const cid = $("#agent-cid").value;
  const uid = (useProfile && state.consent) ? state.uid : null;

  const log = $("#agent-log");
  const emptyState = $("#agent-empty");
  if (emptyState) emptyState.remove();

  sendBtn.disabled = true;
  sendBtn.classList.add("is-loading");
  sendBtn.textContent = "·";
  qEl.value = "";
  qEl.style.height = "auto";

  const qRow = document.createElement("div");
  qRow.className = "msg-row msg-row-user";
  qRow.innerHTML = `<div class="msg-q">${escapeHtml(q)}</div>`;
  log.appendChild(qRow);

  const aRow = document.createElement("div");
  aRow.className = "msg-row msg-row-agent";
  aRow.innerHTML = `<div class="msg-a agent-loading"><span class="agent-loading-dot"></span>正在检索赛事与官方依据</div>`;
  log.appendChild(aRow);
  log.scrollTop = log.scrollHeight;

  let url = `/api/agent/ask?question=${encodeURIComponent(q)}&top_k=4`;
  if (uid) url += `&user_id=${encodeURIComponent(uid)}`;
  if (cid) url += `&competition_id=${encodeURIComponent(cid)}`;

  let data;
  try {
    data = await apiGet(url);
  } catch (err) {
    aRow.innerHTML = `<div class="msg-a agent-error"><strong>暂时无法完成回答</strong><p>${escapeHtml(err.message)}</p></div>`;
    sendBtn.disabled = false;
    sendBtn.classList.remove("is-loading");
    sendBtn.textContent = "↑";
    qEl.focus();
    return;
  }

  // 引用：追加到全局证据数组，供弹窗复用
  const base = currentEvidence.length;
  (data.citations || []).forEach((c) => currentEvidence.push(c));

  const pendingTag = data.pending_review ? `<span class="pending-tag">待人工确认</span>` : "";
  const intentTag = `<span class="intent-tag">${INTENT_LABEL[data.intent] || data.intent} · ${escapeHtml(data.resolved_name || "自动识别赛事")}</span>${pendingTag}`;

  const refsHtml = (data.citations && data.citations.length)
    ? `<details class="refs"><summary>官方依据 <span>${data.citations.length} 条</span></summary><div class="refs-list">` + data.citations.map((c, i) => {
        const page = (c.page === null || c.page === undefined) ? "未定位" : `第 ${c.page} 页`;
        const lvl = (c.trusted_level || "C");
        return `<div class="ref"><span class="cite" data-cite="${base + i}">[${i + 1}]</span>
          <span class="lvl ${lvl}">${lvl}级</span>
          <span>${escapeHtml(c.document_name || "官方通知")} · ${escapeHtml(page)}</span>
          <div class="muted" style="margin-top:4px;">${escapeHtml((c.source_text || "").slice(0, 80))}</div></div>`;
      }).join("") + `</div></details>`
    : "";

  const traceHtml = (data.trace && data.trace.length)
    ? `<details class="trace"><summary>查看处理依据</summary>
        <ol>${data.trace.map((t) => `<li>${escapeHtml(t)}</li>`).join("")}</ol></details>`
    : "";

  aRow.innerHTML = `<div class="msg-a">
    <div class="agent-answer-head"><span class="agent-answer-mark">CI</span><strong>校园科创智能体</strong>${intentTag}</div>
    <div class="agent-answer-body">${renderAnswerWithCites(cleanAgentAnswer(data.answer), base)}</div>
    ${refsHtml}
    ${traceHtml}
  </div>`;

  // 绑定角标点击
  $$(".cite", aRow).forEach((el) => {
    el.addEventListener("click", () => openCiteModal(Number(el.dataset.cite)));
  });
  log.scrollTop = log.scrollHeight;
  sendBtn.disabled = false;
  sendBtn.classList.remove("is-loading");
  sendBtn.textContent = "↑";
  qEl.focus();
}

$("#agent-send").addEventListener("click", agentAsk);
$("#agent-q").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); agentAsk(); } });
$("#agent-q").addEventListener("input", (e) => {
  e.currentTarget.style.height = "auto";
  e.currentTarget.style.height = `${Math.min(e.currentTarget.scrollHeight, 160)}px`;
});
$$("#agent-chips .chip").forEach((el) => {
  el.addEventListener("click", () => {
    $("#agent-q").value = el.dataset.q;
    $("#agent-q").focus();
  });
});

// ---------------------------------------------------------------------------
// 数据维护闭环（上传 → 解析 → 引用关联 → 确认入库）
// ---------------------------------------------------------------------------
let admFileId = null;
let admDocName = null;
let admBlocks = [];
let admEvidence = [];

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = String(reader.result);
      const comma = dataUrl.indexOf(",");
      resolve(comma >= 0 ? dataUrl.slice(comma + 1) : dataUrl);
    };
    reader.onerror = () => reject(new Error("读取失败"));
    reader.readAsDataURL(file);
  });
}
function csv(s) {
  return (s || "").split(/[,，]/).map((x) => x.trim()).filter(Boolean);
}
function todayStr() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function setAdminStep(step) {
  $$(".pipeline-steps span").forEach((el, index) => {
    el.classList.toggle("active", index + 1 === step);
    el.classList.toggle("complete", index + 1 < step || step > 3);
  });
}

function renderAdminView() {
  admFileId = null; admDocName = null; admBlocks = []; admEvidence = [];
  $("#adm-parse-msg").textContent = "";
  $("#adm-step2").classList.add("hidden");
  $("#adm-step3").classList.add("hidden");
  $("#adm-blocks").innerHTML = "";
  $("#adm-save-msg").textContent = "";
  renderAdminEvidence();
  setAdminStep(1);
}

async function adminParse() {
  const fileInput = $("#adm-file");
  if (!fileInput.files.length) { toast("请先选择 PDF/Word 文件"); return; }
  $("#adm-parse-msg").textContent = "读取文件中…";
  const file = fileInput.files[0];
  let b64;
  try {
    b64 = await fileToBase64(file);
  } catch (e) {
    $("#adm-parse-msg").textContent = "文件读取失败：" + e.message;
    return;
  }
  let up;
  try {
    up = await apiPost("/api/admin/upload", { filename: file.name, content_base64: b64 });
  } catch (e) {
    $("#adm-parse-msg").textContent = "上传失败：" + e.message;
    return;
  }
  admFileId = up.file_id; admDocName = up.filename;
  const payload = {
    file_id: up.file_id,
    category: $("#adm-cat").value,
    document_year: Number($("#adm-year").value),
  };
  let data;
  try {
    data = await apiPost("/api/admin/parse", payload);
  } catch (e) {
    $("#adm-parse-msg").textContent = "解析失败：" + e.message;
    return;
  }
  admBlocks = data.blocks || [];
  renderAdminBlocks(admBlocks);
  prefillAdminForm(data.suggestions || {}, data.document_year);
  renderAdminEvidence();
  $("#adm-step2").classList.remove("hidden");
  $("#adm-step3").classList.remove("hidden");
  setAdminStep(2);
  $("#adm-parse-msg").textContent = `解析完成：${data.block_count} 个文本块；已按关键词预抽取部分字段`;
  if (!$("#adm-name").value) $("#adm-name").value = data.document_name || "";
}

function renderAdminBlocks(blocks) {
  const box = $("#adm-blocks");
  if (!blocks.length) {
    box.innerHTML = '<p class="muted">未解析到文本块（可能是扫描版 PDF 或空文档）。</p>';
    return;
  }
  const fieldOpts = `
    <option value="team_max">团队人数</option>
    <option value="registration_deadline">报名截止</option>
    <option value="submission_deadline">提交截止</option>
    <option value="eligible_students">参赛对象</option>
    <option value="required_skills">所需技能</option>
    <option value="required_materials">所需材料</option>
    <option value="official">官方来源</option>`;
  box.innerHTML = blocks.map((b) => `
    <div class="block" data-i="${b.index}">
      <div class="block-meta">[第 ${b.page} 页 · 第 ${b.paragraph_index} 段]</div>
      <div class="block-text">${escapeHtml(b.text)}</div>
      <div class="block-act">
        <select class="adm-ev-field">${fieldOpts}</select>
        <button class="btn small adm-ev-btn" data-i="${b.index}">引用</button>
      </div>
    </div>`).join("");
  $$(".adm-ev-btn", box).forEach((btn) => {
    btn.addEventListener("click", () => {
      const i = Number(btn.dataset.i);
      const b = admBlocks[i];
      const field = btn.previousElementSibling.value;
      admEvidence.push({
        field,
        page: b.page,
        source_text: b.text,
        document_name: admDocName,
        source_url: ($("#adm-url").value || "").trim() || null,
        acquired_date: todayStr(),
        last_verified_at: todayStr(),
        trusted_level: "A",
      });
      renderAdminEvidence();
      toast("已关联「" + field + "」引用");
    });
  });
}

function renderAdminEvidence() {
  const box = $("#adm-evidence");
  if (!admEvidence.length) {
    box.innerHTML = '<p class="muted">尚未关联引用。在上方文本块点击「引用」后，该原文会作为字段级证据随赛事入库，问答时可由用户点击核对。</p>';
    return;
  }
  box.innerHTML = `<h4>已关联证据（${admEvidence.length}）</h4>` + admEvidence.map((e, i) => `
    <div class="ev-item">
      <span class="ev-field">${escapeHtml(e.field)}</span>
      <span class="ev-text">${escapeHtml((e.source_text || "").slice(0, 50))}…</span>
      <button class="ev-del" data-i="${i}">×</button>
    </div>`).join("");
  $$(".ev-del", box).forEach((b) => b.addEventListener("click", () => {
    admEvidence.splice(Number(b.dataset.i), 1);
    renderAdminEvidence();
  }));
}

function prefillAdminForm(s, year) {
  if (s.team && s.team.required) {
    $("#adm-team-required").checked = true;
    if (s.team.min) $("#adm-tmin").value = s.team.min;
    if (s.team.max) $("#adm-tmax").value = s.team.max;
  }
  if (s.registration_deadline && s.registration_deadline.value) {
    $("#adm-reg").value = s.registration_deadline.value;
  }
  if (s.submission_deadline && s.submission_deadline.value) {
    $("#adm-sub").value = s.submission_deadline.value;
  }
  if (s.eligible && s.eligible.value) {
    $$(".adm-education").forEach((el) => {
      if (el.dataset.value === s.eligible.value) el.checked = true;
    });
  }
}

$("#adm-parse").addEventListener("click", adminParse);

$("#adm-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const id = $("#adm-id").value.trim();
  const name = $("#adm-name").value.trim();
  if (!id || !name) { toast("请填写赛事ID和赛事名称"); return; }
  const elig = $$(".adm-education:checked").map((el) => el.dataset.value);
  const urlVal = ($("#adm-url").value || "").trim();
  const comp = {
    competition_id: id,
    competition_name: name,
    document_year: Number($("#adm-year").value) || 2026,
    category: $("#adm-cat").value,
    organizer: ($("#adm-organizer").value || "").trim() || null,
    eligible_students: elig,
    allowed_grades: null,
    allowed_majors: null,
    team_required: $("#adm-team-required").checked,
    team_min: $("#adm-tmin").value ? Number($("#adm-tmin").value) : null,
    team_max: $("#adm-tmax").value ? Number($("#adm-tmax").value) : null,
    registration_deadline: $("#adm-reg").value || null,
    submission_deadline: $("#adm-sub").value || null,
    required_materials: csv($("#adm-materials").value),
    evaluation_dimensions: [],
    required_skills: csv($("#adm-skills").value),
    official_source_url: urlVal || null,
    source_acquired_date: todayStr(),
    trusted_level: "A",
    data_status: "verified",
    last_verified_at: todayStr(),
    evidence: admEvidence,
    doc_version: `${$("#adm-year").value || 2026}_v1`,
  };
  $("#adm-save-msg").textContent = "入库中…";
  setAdminStep(3);
  try {
    const d = await apiPost("/api/admin/competitions", comp);
    $("#adm-save-msg").textContent = `✓ 已入库 ${d.competition_id}（${d.data_status}，证据 ${d.evidence_count} 条，RAG ${d.rag_chunks} 块）`;
    $("#adm-save-msg").className = "msg ok";
    setAdminStep(4);
    toast("入库成功，已刷新检索库");
  } catch (err) {
    $("#adm-save-msg").textContent = "入库失败：" + err.message;
    $("#adm-save-msg").className = "msg";
  }
});

// ---------------------------------------------------------------------------
// 登录界面（选择特色身份 / 自定义登录）—— 每个人特色不一样
// ---------------------------------------------------------------------------
function openLogin() {
  $("#login-overlay").classList.remove("hidden");
  loadLoginUsers();
}
function closeLogin() {
  $("#login-overlay").classList.add("hidden");
}

async function loadLoginUsers() {
  const box = $("#login-users");
  let users;
  try {
    users = await apiGet("/api/users");
  } catch (err) {
    box.innerHTML = `<div class="muted" style="padding:16px;">加载身份失败：${escapeHtml(err.message)}</div>`;
    return;
  }
  if (!users.length) {
    box.innerHTML = `<div class="muted" style="padding:16px;">暂无预置身份，请在下方自定义登录。</div>`;
    return;
  }
  box.innerHTML = users.map((u) => {
    const skills = (u.skills || []).slice(0, 4).map((s) => `<span class="uc-skill">${escapeHtml(s)}</span>`).join("");
    const team = u.expected_team_size > 1 ? `${u.expected_team_size}人队` : "个人赛";
    const name = u.display_name || u.user_id;
    return `<button type="button" class="user-card" data-uid="${escapeHtml(u.user_id)}"
        data-avatar="${escapeHtml(monogram(name))}"
        data-name="${escapeHtml(u.display_name || u.user_id)}"
        data-persona="${escapeHtml(u.persona || "")}">
      <div class="uc-top">
        <span class="uc-avatar">${escapeHtml(monogram(name))}</span>
        <div class="uc-idwrap">
          <div class="uc-name">${escapeHtml(u.display_name || u.user_id)}</div>
          <div class="uc-persona">${escapeHtml(u.persona || "")}</div>
        </div>
      </div>
      <div class="uc-meta">
        <span class="uc-tag">${escapeHtml(u.education_level)}·${escapeHtml(u.grade)}</span>
        <span class="uc-tag">${escapeHtml(u.major)}</span>
        <span class="uc-tag">${escapeHtml(team)}</span>
        <span class="uc-tag">周${u.weekly_available_hours}h</span>
      </div>
      <div class="uc-skills">${skills || '<span class="muted">暂无技能标签</span>'}</div>
    </button>`;
  }).join("");

  $$("#login-users .user-card").forEach((el) => {
    el.addEventListener("click", () => {
      loginAs(el.dataset.uid, {
        display_name: el.dataset.name,
        avatar: el.dataset.avatar,
        persona: el.dataset.persona,
      }, false);
    });
  });
}

async function loginAs(uid, meta, isCustom) {
  uid = (uid || "").trim();
  if (!uid) { toast("请输入用户名"); return; }
  state.uid = uid;
  state.loggedIn = true;
  state.userMeta = meta || null;
  state.profile = null;
  state.evidenceCache = {};
  localStorage.setItem("cia_uid", uid);
  localStorage.setItem("cia_logged", "1");
  localStorage.setItem("cia_user_meta", JSON.stringify(state.userMeta || {}));

  // 判定该用户是否已授权并有画像（决定 consent 与落地页）
  let hasProfile = false;
  try {
    const p = await apiGet(`/api/users/${encodeURIComponent(uid)}/profile`);
    hasProfile = true;
    state.profile = p;
    state.consent = !!p.privacy_consent;
    // 自定义登录但服务端已有更完整展示信息时，回填 chip
    if (!state.userMeta || !state.userMeta.display_name) {
      state.userMeta = { display_name: p.display_name || uid, avatar: monogram(p.display_name || uid), persona: p.persona || "" };
      localStorage.setItem("cia_user_meta", JSON.stringify(state.userMeta));
    }
  } catch (_) {
    hasProfile = false;
    state.consent = localStorage.getItem("cia_consent_" + uid) === "1";
  }
  if (state.consent) localStorage.setItem("cia_consent_" + uid, "1");

  closeLogin();
  updateUserChip();
  toast(`已登录：${(state.userMeta && state.userMeta.display_name) || uid}`);

  // 已有画像的示例身份 → 直达「我的推荐」直观展示千人千面；新用户 → 去填画像
  if (hasProfile && state.consent) {
    location.hash = "#/recommend";
  } else {
    location.hash = "#/profile";
  }
  router();
}

function logout() {
  localStorage.removeItem("cia_uid");
  localStorage.removeItem("cia_logged");
  localStorage.removeItem("cia_user_meta");
  state.uid = null;
  state.loggedIn = false;
  state.userMeta = null;
  state.consent = false;
  state.profile = null;
  state.evidenceCache = {};
  updateUserChip();
  openLogin();
}

$("#login-custom-btn").addEventListener("click", () => {
  const id = ($("#login-custom-id").value || "").trim();
  if (!id) { toast("请输入用户名"); return; }
  loginAs(id, { display_name: id, avatar: monogram(id), persona: "自定义用户" }, true);
});
$("#login-custom-id").addEventListener("keydown", (e) => {
  if (e.key === "Enter") $("#login-custom-btn").click();
});
$("#switch-user-btn").addEventListener("click", logout);

// ---------------------------------------------------------------------------
// 启动
// ---------------------------------------------------------------------------
window.addEventListener("hashchange", router);
window.addEventListener("DOMContentLoaded", () => {
  updateUserChip();
  if (!state.loggedIn || !state.uid) {
    openLogin();
    return; // 未登录不进入主应用
  }
  router();
});
