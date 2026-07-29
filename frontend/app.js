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
  const r = await fetch(path, { headers: sessionAuthHeaders() });
  if (!r.ok) throw new Error(`${path} -> ${r.status}`);
  return r.json();
}
async function apiPost(path, body, extraHeaders = {}) {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...sessionAuthHeaders(), ...extraHeaders },
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
    headers: { "Content-Type": "application/json", ...sessionAuthHeaders() },
    body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => null);
  if (!r.ok) throw new Error((data && data.detail) || `HTTP ${r.status}`);
  return data;
}
async function apiDelete(path) {
  const r = await fetch(path, { method: "DELETE", headers: sessionAuthHeaders() });
  const data = await r.json().catch(() => null);
  if (!r.ok) throw new Error((data && data.detail) || `HTTP ${r.status}`);
  return data;
}

function sessionAuthHeaders() {
  const token = sessionStorage.getItem("cia_access_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// ---------------------------------------------------------------------------
// 状态（本地会话模拟）
// ---------------------------------------------------------------------------
// 每次进入都强制重新登录：启动即清空登录态，不记住（演示更可控）
(function clearLoginStateOnBoot() {
  ["cia_uid", "cia_logged", "cia_is_test", "cia_is_admin", "cia_user_meta"].forEach((k) =>
    localStorage.removeItem(k)
  );
  sessionStorage.removeItem("cia_admin_token");
  sessionStorage.removeItem("cia_access_token");
})();

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
  detailReturn: "#/hall", // 详情页返回目标视图（默认大厅；从推荐进入时为 #/recommend）
  hallReadiness: "all",
  isTest: localStorage.getItem("cia_is_test") === "1",
  isAdmin: localStorage.getItem("cia_is_admin") === "1",
  portfolioPlans: [],
  portfolioData: null,
  projects: [],
  projectView: localStorage.getItem("cia_project_view") || "list",
  projectCalendarCursor: null,
  radarFilter: "all",
  radarStatus: null,
};

const CAT_LABEL = {
  programming: "程序设计", modeling: "数学建模",
  innovation: "创新创业", software: "软件作品",
  english: "外语竞赛", math: "数学竞技",
  electronics: "电子设计", robotics_ai: "机器人与AI",
  data: "数据科学", design: "艺术设计",
  business: "财经商科", engineering: "机械工程",
  life_science: "生科医药", physics: "物理",
  chem_env: "化工环境",
};
const STATUS_LABEL = {
  highly_suitable: "高度适合", suitable: "比较适合",
  marginal: "可参加·需补充", not_prioritized: "不优先推荐",
  candidate_only: "候选信息·未评分",
  ineligible: "不符合·一票否决",
};

// ---------------------------------------------------------------------------
// 路由
// ---------------------------------------------------------------------------
function showView(name) {
  $$(".view").forEach((v) => v.classList.add("hidden"));
  $("#view-" + name).classList.remove("hidden");
  $$(".topnav nav a").forEach((a) => {
    a.classList.toggle("active", a.dataset.nav === name);
  });
  // 智能问答页全屏沉浸：移除容器边距，让视图占满 topnav 下方全部空间
  document.body.classList.toggle("agent-fullscreen", name === "agent");
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
    if (!state.isAdmin) {
      toast("无权限访问该页面");
      location.hash = "#/hall";
      return;
    }
    showView("admin");
    renderAdminView();
    return;
  }
  if (parts[0] === "projects") {
    showView("projects");
    renderProjects();
    return;
  }
  if (parts[0] === "portfolio") {
    showView("portfolio");
    renderPortfolio();
    return;
  }
  if (parts[0] === "radar") {
    showView("radar");
    renderRadar();
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
// 质量驾驶舱：冻结评测与运行态指标不混算
// ---------------------------------------------------------------------------
function qualityRate(value) {
  const n = Number(value);
  return Number.isFinite(n) ? `${n.toFixed(n % 1 ? 1 : 0)}%` : "—";
}

function qualityGate(label, enabled, detail) {
  return `<article class="quality-gate ${enabled ? "is-on" : "is-off"}">
    <span>${enabled ? "✓" : "!"}</span><div><b>${escapeHtml(label)}</b><small>${escapeHtml(detail)}</small></div>
  </article>`;
}

async function renderQuality() {
  const host = $("#quality-dashboard");
  host.innerHTML = '<div class="quality-loading"><span></span><b>正在核对冻结报告与实时指标</b></div>';
  let data;
  try {
    data = await apiGet("/api/system/quality");
  } catch (error) {
    host.innerHTML = `<div class="quality-error"><b>质量数据暂时不可用</b><span>${escapeHtml(error.message)}</span></div>`;
    return;
  }

  const formal = data.formal_checks || {};
  const regression = data.regression || {};
  const golden = data.golden_set || {};
  const runtime = data.runtime || {};
  const formalMetrics = data.formal_metrics || {};
  const formalPassed = Number(formal.passed || 0);
  const formalTotal = Number(formal.total || 0);
  const regressionPassed = Number(regression.passed || 0);
  const regressionTotal = Number(regression.tests_run || 0);
  const frozenRate = formalTotal ? Math.round(formalPassed / formalTotal * 100) : 0;
  const metricLabels = {
    deadline_consistency: "截止日期一致率",
    eligibility_accuracy: "资格判断准确率",
    citation_accuracy: "官方证据引用正确率",
    unverified_block_rate: "未核验赛事拦截率",
    insufficient_refusal_rate: "证据不足安全处理率",
  };
  const metricCards = Object.entries(metricLabels).map(([key, label]) => {
    const item = formalMetrics[key] || {};
    return `<article class="quality-metric-card">
      <div><span>${escapeHtml(label)}</span><b>${qualityRate(item.rate)}</b></div>
      <small>${Number(item.passed || 0)} / ${Number(item.total || 0)} 固定用例通过</small>
      <i><em style="width:${Math.max(0, Math.min(100, Number(item.rate || 0)))}%"></em></i>
    </article>`;
  }).join("");

  const scoreEvidence = [
    ["30", "落地价值", "赛事情报 → 个性化推荐 → 参赛项目"],
    ["25", "任务闭环", "输入、处理、输出、兜底全链路留痕"],
    ["20", "工程质量", `${regressionTotal || 48} 项回归、日志、健康检查与降级`],
    ["15", "交互体验", "运行剧场与四种项目视图"],
    ["10", "安全合规", "签名会话、SSRF、最小数据与人工审核"],
  ].map(([weight, label, detail]) => `<article><strong>${weight}</strong><div><b>${label}</b><span>${detail}</span></div></article>`).join("");

  host.innerHTML = `
    <section class="quality-hero-grid">
      <article class="quality-frozen-panel">
        <header><div><span>FROZEN EVALUATION</span><h3>冻结评测快照</h3></div><em>${escapeHtml(data.evaluated_at || "未记录")}</em></header>
        <div class="quality-ring" style="--quality-rate:${frozenRate * 3.6}deg"><div><strong>${frozenRate}</strong><small>SCORE</small></div></div>
        <div class="quality-frozen-stats">
          <span><b>${formalPassed}/${formalTotal || "—"}</b><small>正式指标</small></span>
          <span><b>${regressionPassed}/${regressionTotal || "—"}</b><small>自动回归</small></span>
          <span><b>${Number(golden.cases || 0)}</b><small>金标问题</small></span>
        </div>
        <p>这是固定数据与固定代码上的可复现结果，不伪装成实时指标。</p>
      </article>
      <article class="quality-live-panel">
        <header><div><span>LIVE RUNTIME</span><h3>当前运行态</h3></div><em><i></i> LIVE</em></header>
        <div class="quality-live-stats">
          <span><small>监控来源</small><b>${Number(runtime.source_count || 0)}</b></span>
          <span><small>高健康来源</small><b>${Number(runtime.healthy_sources || 0)}</b></span>
          <span><small>待人工审核</small><b>${Number(runtime.pending_human_reviews || 0)}</b></span>
        </div>
        <div class="quality-gates">
          ${qualityGate("人工审核门禁", !!runtime.manual_review_gate, "关键事实不自动覆盖")}
          ${qualityGate("SSRF 网络防护", !!runtime.ssrf_protection, "拦截内网与非授权目标")}
          ${qualityGate("签名用户会话", !!runtime.signed_user_sessions, "画像、项目与历史按用户隔离")}
        </div>
      </article>
    </section>
    <section class="quality-section">
      <div class="quality-section-head"><div><span>FORMAL METRICS</span><h3>五类可量化质量门禁</h3></div><small>固定评测集</small></div>
      <div class="quality-metric-grid">${metricCards}</div>
    </section>
    <section class="quality-bottom-grid">
      <article class="quality-section quality-golden-panel">
        <div class="quality-section-head"><div><span>GOLDEN SET</span><h3>${Number(golden.cases || 0)} 条问答金标集</h3></div><small>防回归</small></div>
        <div class="quality-golden-stats">
          <span><b>${qualityRate(golden.intent_accuracy)}</b><small>意图准确率</small></span>
          <span><b>${qualityRate(golden.citation_recall)}</b><small>引用召回率</small></span>
          <span><b>${qualityRate(golden.gate_consistency)}</b><small>门控一致率</small></span>
        </div>
      </article>
      <article class="quality-section quality-score-panel">
        <div class="quality-section-head"><div><span>JUDGING MATRIX</span><h3>评审分值证据映射</h3></div><small>总分 100</small></div>
        <div class="quality-score-list">${scoreEvidence}</div>
      </article>
    </section>
    <footer class="quality-integrity-note"><span>◇</span><p><b>数据诚信声明</b>${escapeHtml(data.note || "冻结评测与实时运行态分开展示。")}</p></footer>`;
}

// ---------------------------------------------------------------------------
// 画像页
// ---------------------------------------------------------------------------
async function renderProfile() {
  updateUserChip();
  renderTestPanel();
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
  revealAdminNav();
}

function monogram(name) {
  const value = String(name || "U").trim();
  return Array.from(value).slice(0, 2).join("").toUpperCase();
}

// ---------------------------------------------------------------------------
// 赛事大厅
// ---------------------------------------------------------------------------
// 专业匹配等级：2=明确包含该专业，1=不限专业(面向所有人)，0=不匹配
function compMatchLevel(c, major) {
  if (!major) return 0;
  if (!c.allowed_majors || c.allowed_majors.length === 0) return 1; // 不限专业
  return c.allowed_majors.includes(major) ? 2 : 0;
}

// 报名状态标签：基于时间字段判断，给「已截止 / 已开赛 / 已结束」加灰色标识，
// 与后端 recommend_for_user 的时间门控（只推报名中）前后呼应。
function competitionStatus(c) {
  const today = new Date().toISOString().slice(0, 10);
  const sd = c.competition_start_date, ed = c.competition_end_date;
  const rd = c.registration_deadline, sub = c.submission_deadline;
  if (sd && sd <= today) return { label: "已开赛", cls: "status-progress" };
  if (ed && ed < today) return { label: "已结束", cls: "status-ended" };
  if (rd && rd < today) return { label: "报名已截止", cls: "status-closed" };
  if (!rd && sub && sub < today) return { label: "报名已截止", cls: "status-closed" };
  return { label: "报名中", cls: "status-open" };
}
function statusTag(c) {
  const s = competitionStatus(c);
  return `<span class="tag ${s.cls}">${s.label}</span>`;
}

function compCardHtml(c, matchLevel) {
  const majorTag = matchLevel === 2
    ? `<span class="tag major-match">匹配你的专业</span>`
    : (matchLevel === 1 ? `<span class="tag major-open">不限专业</span>` : "");
  return `<article class="card comp-card" data-id="${escapeHtml(c.competition_id)}" tabindex="0">
      <div class="comp-card-main">
        <div class="comp-kicker">${escapeHtml(c.competition_id)}</div>
        <div class="comp-title">${escapeHtml(c.competition_name)}</div>
        <div class="comp-meta">
          <span class="tag cat">${CAT_LABEL[c.category] || c.category}</span>
          <span class="tag year">${c.document_year}</span>
          ${statusTag(c)}
          <span class="tag ${c.recommendation_ready ? "status-verified" : "status-unverified"}">${c.recommendation_ready ? "可正式推荐" : "待核验候选"}</span>
          ${majorTag}
        </div>
        <div class="card-open-hint">点击查看详情 ›</div>
      </div>
      <div class="comp-card-side"><span>报名截止</span><strong>${escapeHtml(c.registration_deadline || "未明确")}</strong><i aria-hidden="true">→</i></div>
    </article>`;
}

async function renderHall() {
  // 拉取全部赛事（用于专业匹配与年份下拉）
  let all;
  try {
    all = await apiGet("/api/competitions");
  } catch (err) {
    $("#hall-list").innerHTML = `<div class="card">加载失败：${escapeHtml(err.message)}</div>`;
    return;
  }
  state.competitions = all;

  // 年份下拉
  const years = Array.from(new Set(all.map((c) => c.document_year))).sort((a, b) => b - a);
  const yearSel = $("#filter-year");
  const cur = yearSel.value;
  yearSel.innerHTML = `<option value="">全部年份</option>` +
    years.map((y) => `<option value="${y}">${y}</option>`).join("");
  if (cur) yearSel.value = cur;

  // 用户专业画像（已登录且已填写画像时生效）
  let major = null;
  if (state.uid) {
    try {
      const p = await apiGet(`/api/users/${encodeURIComponent(state.uid)}/profile`);
      major = p && p.major ? p.major : null;
    } catch (_) { major = null; }
  }
  const levelOf = (c) => compMatchLevel(c, major);

  // 应用类别/年份筛选（客户端，便于专业优先排序）
  const cat = $("#filter-cat").value;
  const year = $("#filter-year").value;
  const list = all.filter((c) =>
    (!cat || c.category === cat)
    && (!year || String(c.document_year) === String(year))
    && (state.hallReadiness === "all"
      || (state.hallReadiness === "ready" && c.recommendation_ready)
      || (state.hallReadiness === "candidate" && !c.recommendation_ready))
  );

  if (!list.length) {
    $("#hall-list").innerHTML = `<div class="card muted">暂无符合条件的赛事。</div>`;
    return;
  }

  // 按「专业匹配优先 → 报名截止临近优先」排序
  const byDeadline = (a, b) => {
    const da = a.registration_deadline || "9999", db = b.registration_deadline || "9999";
    return da < db ? -1 : da > db ? 1 : 0;
  };
  const sorted = list.slice().sort((a, b) => {
    const la = levelOf(a), lb = levelOf(b);
    if (la !== lb) return lb - la;
    return byDeadline(a, b);
  });

  // 顶部「为你推荐」区块（跨筛选，取专业匹配度最高的若干项）
  let strip = "";
  if (major && state.hallReadiness === "all") {
    const matched = all
      .map((c) => ({ c, l: levelOf(c) }))
      .filter((x) => x.l > 0 && x.c.recommendation_ready)
      .sort((a, b) => b.l - a.l || byDeadline(a.c, b.c))
      .slice(0, 6);
    if (matched.length) {
      strip = `<div class="reco-strip">
        <div class="reco-head">与你专业相关 · ${escapeHtml(major)} · ${matched.length} 项可正式推荐赛事</div>
        <div class="cards reco-cards">${matched.map((x) => compCardHtml(x.c, x.l)).join("")}</div>
      </div>`;
    }
  }

  $("#hall-list").innerHTML = strip + sorted.map((c) => compCardHtml(c, levelOf(c))).join("");

  $$("#hall-list .comp-card").forEach((el) => {
    el.addEventListener("click", () => {
      state.detailReturn = "#/hall";
      location.hash = "#/detail/" + el.dataset.id;
    });
    el.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") el.click();
    });
  });
}

$("#filter-cat").addEventListener("change", renderHall);
$("#filter-year").addEventListener("change", renderHall);
$$('.hall-trust-filter button').forEach((button) => button.addEventListener("click", () => {
  state.hallReadiness = button.dataset.readiness;
  $$('.hall-trust-filter button').forEach((item) => item.classList.toggle("active", item === button));
  renderHall();
}));

// ---------------------------------------------------------------------------
// 赛事详情
// ---------------------------------------------------------------------------
async function renderDetail(id) {
  // 根据来源更新「返回」链接（从推荐进入 → 返回推荐；其余 → 返回大厅）
  const backEl = document.querySelector("#view-detail .back");
  if (backEl) {
    const ret = state.detailReturn || "#/hall";
    backEl.setAttribute("href", ret);
    backEl.textContent = ret === "#/recommend" ? "← 返回推荐" : ret === "#/portfolio" ? "← 返回作战地图" : "← 返回大厅";
  }
  let detail;
  try {
    detail = await apiGet("/api/competitions/" + encodeURIComponent(id));
  } catch (err) {
    $("#detail-content").innerHTML = `<div class="card">加载失败：${escapeHtml(err.message)}</div>`;
    return;
  }
  const c = detail.competition;
  // recommendation_ready 同时包含“仍可报名”的时效门控；来源可信状态需要
  // 单独展示，避免已截止但证据完整的赛事被误标为“关键证据待补充”。
  const sourceReady = c.data_status === "verified"
    && c.trusted_level === "A"
    && c.official_source_status === "found";
  const kv = (k, v) =>
    `<div class="kv"><span class="k">${escapeHtml(k)}</span><span class="v">${v}</span></div>`;

  const grades = c.allowed_grades && c.allowed_grades.length ? c.allowed_grades.join("、") : "不限年级";
  const majors = c.allowed_majors && c.allowed_majors.length ? c.allowed_majors.join("、") : "不限专业";
  const teamTxt = `${c.team_min ?? 1}—${c.team_max ?? 1} 人${c.team_required ? "（组队赛）" : "（个人或组队）"}`;

  // 适合谁参加（基于资格要求自动拼接）
  const whoItems = [];
  if (c.eligible_students && c.eligible_students.length) whoItems.push(c.eligible_students.join("、") + "可参加");
  if (grades !== "不限年级") whoItems.push(grades);
  if (majors !== "不限专业") whoItems.push(majors);
  whoItems.push(teamTxt);
  const whoText = whoItems.join("；") + "。";

  // 比赛时间范围
  let compRange = null;
  if (c.competition_start_date && c.competition_end_date) compRange = `${c.competition_start_date} 至 ${c.competition_end_date}`;
  else if (c.competition_start_date) compRange = `${c.competition_start_date} 起`;
  else if (c.competition_end_date) compRange = `至 ${c.competition_end_date}`;

  // 关键时间（按时间顺序排列）
  const keyTimeItems = [];
  if (c.registration_deadline) keyTimeItems.push({ label: "报名截止", date: c.registration_deadline });
  if (c.submission_deadline) keyTimeItems.push({ label: "提交截止", date: c.submission_deadline });
  if (compRange) keyTimeItems.push({ label: "比赛时间", date: compRange });
  if (c.result_announcement_date) keyTimeItems.push({ label: "成绩公布", date: String(c.result_announcement_date) });
  const keyTimeHtml = keyTimeItems.length
    ? keyTimeItems.map((t) => `<div class="kv"><span class="k">${escapeHtml(t.label)}</span><span class="v">${escapeHtml(t.date)}</span></div>`).join("")
    : `<div class="muted">暂无时间安排</div>`;

  // 奖项设置（奖项 + 比例）
  let awardHtml = "";
  if (c.award_distribution && c.award_distribution.length) {
    const rows = c.award_distribution.map((a) =>
      `<div class="award-row"><span class="award-name">${escapeHtml(a.award)}</span><span class="award-prop">${escapeHtml(a.proportion || "—")}</span></div>`
    ).join("");
    awardHtml = `<div class="kv kv-awards"><span class="k">奖项设置</span><span class="v">${rows}</span></div>`;
  } else if (c.award_settings) {
    awardHtml = `<div class="kv"><span class="k">奖项设置</span><span class="v">${escapeHtml(c.award_settings)}</span></div>`;
  }

  // 顶部“访问官网”链接
  const officialUrl = c.official_source_url || (detail.sources && detail.sources[0] && detail.sources[0].url) || "";


  $("#detail-content").innerHTML = `
    <div class="card">
      <div class="detail-head"><div>
      <div class="comp-title detail-title">${escapeHtml(c.competition_name)}</div>
      <div class="comp-meta">
        <span class="tag cat">${CAT_LABEL[c.category] || c.category}</span>
        <span class="tag year">${c.document_year}</span>
        ${statusTag(c)}
        ${(c.official_source_status === "not_found") ? `<span class="tag src-unverified">未找到官方来源</span>` : (sourceReady ? `<span class="tag src-verified">官网证据已确认</span>` : `<span class="tag src-unverified">关键证据待补充</span>`)}
      </div>
      </div>
      <div class="detail-actions">
        ${officialUrl ? `<a class="btn ghost" href="${escapeHtml(officialUrl)}" target="_blank" rel="noopener">访问官网</a>` : ""}
        ${detail.recommendation_ready ? `<button id="join-project" class="btn primary">加入我的项目</button>` : ""}
      </div>
    </div>

    ${!sourceReady ? `<div class="verify-warn">
      <strong>候选信息，不参与资格判断或匹配评分</strong>
      <div>${escapeHtml((detail.readiness_reasons || []).join("；") || "关键证据待补充")}。请访问官网核对最新通知。</div>
    </div>` : ""}

    ${c.official_source_status === "not_found" ? `
    <div class="verify-warn">
      <strong>⚠ 未找到官方链接</strong>
      <div>本赛事未能核实到官方来源，以上数据来源待确认，请勿当作定论。</div>
      ${c.notes ? `<details><summary>查看核实说明</summary><div>${escapeHtml(c.notes)}</div></details>` : ""}
    </div>` : ""}

    ${c.brief_description ? `<div class="section"><h3>比赛简介</h3><div class="card"><p class="brief-desc" style="line-height:1.7;color:#30343a;margin:0;white-space:pre-wrap;">${escapeHtml(c.brief_description)}</p></div></div>` : ""}

    <div class="section"><h3>适合谁参加</h3><div class="card"><p class="who-text" style="line-height:1.7;color:#30343a;margin:0;">${escapeHtml(whoText)}</p></div></div>

    <div class="section"><h3>资格要求</h3><div class="card">
      ${kv("参赛对象", (c.eligible_students || []).join("、") || "—")}
      ${kv("年级要求", grades)}
      ${kv("专业要求", majors)}
      ${kv("团队规模", teamTxt)}
    </div></div>

    <div class="section"><h3>关键时间</h3><div class="card">
      ${keyTimeHtml}
      ${awardHtml}
    </div></div>

    <div class="section"><h3>材料与能力</h3><div class="card">
      ${(c.required_materials && c.required_materials.length) ? kv("所需材料", c.required_materials.join("、")) : ""}
      ${(c.required_skills && c.required_skills.length) ? kv("所需技能", c.required_skills.join("、")) : ""}
      ${(c.evaluation_dimensions && c.evaluation_dimensions.length) ? kv("评价维度", c.evaluation_dimensions.join("、")) : ""}
    </div></div>

    <div class="section source-note"><p class="muted">以上信息来自赛事官方通知，请以学校官网或赛事官网最新发布为准。</p></div>
  `;

  const joinButton = $("#join-project");
  if (joinButton) joinButton.addEventListener("click", () => joinProject(c.competition_id));
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
  box.innerHTML = hits.map((h) => {
    const page = (h.page === null || h.page === undefined) ? "未定位" : `第 ${h.page} 页`;
    return `<div class="card" style="margin-bottom:8px;">
      <div class="row between">
        <span class="tag fact">命中字段：${escapeHtml(h.field)}</span>
        <span class="muted">${page}</span>
      </div>
      <p style="margin:8px 0 0;background:#f8fafc;border-left:3px solid var(--fact);padding:10px;border-radius:6px;">${escapeHtml(h.source_text)}</p>
    </div>`;
  }).join("");
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
  $("#recommend-hint").textContent = recs.length
    ? `已按你的专业、技能、经历、组队条件与可投入时间排序，共 ${recs.length} 项可报名赛事。`
    : "当前没有同时满足参赛资格和报名时间的赛事。";

  // 排序：可推荐在前
  const order = { highly_suitable: 0, suitable: 1, marginal: 2, not_prioritized: 3, candidate_only: 4, ineligible: 5 };
  recs.sort((a, b) => (order[a.recommendation_status] ?? 9) - (order[b.recommendation_status] ?? 9));

  $("#recommend-list").innerHTML = recs.map((r) => {
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
      r.pending_review ? `<span class="tag pending">来源待核实</span>` : "",
    ].join("");
    return `<article class="card rec-card rec-${escapeHtml(r.recommendation_status)}" data-id="${escapeHtml(r.competition_id)}">
      <div class="rec-head">
        <div><div class="comp-kicker">${escapeHtml(r.competition_id)}</div><div class="comp-title">${escapeHtml(r.competition_name)}</div></div>
        <div class="score-pill"><span>匹配度</span><strong>${score}</strong></div>
      </div>
      <div class="comp-meta">${tags}</div>
      ${gate}
      ${explain ? `<details class="rec-why"><summary>为何推荐 · ${Object.keys(r.explanation || {}).length} 项匹配<span>点击展开</span></summary><ul class="explain">${explain}</ul></details>` : ""}
      ${r.recommendation_status === "candidate_only" ? `<div class="muted" style="font-size:12px;margin-top:6px;">该赛事仅作为候选信息展示，暂未纳入匹配评分。</div>` : ""}
      <div class="row">
        <button class="btn ghost detail-btn" data-id="${escapeHtml(r.competition_id)}">查看详情</button>
        ${r.eligible ? `<button class="btn primary join-btn" data-id="${escapeHtml(r.competition_id)}">加入我的项目</button>` : ""}
      </div>
    </article>`;
  }).join("");

  $$("#recommend-list .join-btn").forEach((btn) => {
    btn.addEventListener("click", () => joinProject(btn.dataset.id));
  });
  $$("#recommend-list .detail-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.detailReturn = "#/recommend";
      location.hash = "#/detail/" + btn.dataset.id;
    });
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
// 科创机会组合优化
// ---------------------------------------------------------------------------
async function renderPortfolio() {
  const box = $("#portfolio-plans");
  const map = $("#innovation-map");
  if (!state.uid || !state.consent) {
    $("#portfolio-summary").innerHTML = '<div class="empty-state"><b>需要个人画像</b><span>保存并授权画像后，系统才能计算时间与能力约束。</span></div>';
    if (map) map.innerHTML = '<div class="map-empty">保存画像后生成个性化作战路线</div>';
    box.innerHTML = "";
    return;
  }
  $("#portfolio-summary").innerHTML = '<div class="portfolio-loading">正在枚举可行组合并检查每周容量…</div>';
  if (map) map.innerHTML = '<div class="map-loading"><span></span>正在绘制作战路线…</div>';
  box.innerHTML = "";
  const payload = {
    max_competitions: Number($("#portfolio-max").value),
    horizon_weeks: Number($("#portfolio-horizon").value),
    goal: $("#portfolio-goal").value,
  };
  const hours = Number($("#portfolio-hours").value || 0);
  if (hours > 0) payload.weekly_hours_override = hours;
  let data;
  try {
    data = await apiPost(`/api/users/${encodeURIComponent(state.uid)}/portfolio/optimize`, payload);
  } catch (e) {
    $("#portfolio-summary").innerHTML = `<div class="empty-state"><b>暂时无法规划</b><span>${escapeHtml(e.message)}</span></div>`;
    if (map) map.innerHTML = '<div class="map-empty">组合求解完成后生成路线图</div>';
    return;
  }
  state.portfolioData = data;
  state.portfolioPlans = data.plans || [];
  const selected = state.portfolioPlans.reduce((n, p) => n + (p.items || []).length, 0);
  $("#portfolio-summary").innerHTML = `<div class="portfolio-callout"><span>本次求解完成</span><b>3 种策略 · ${selected} 个入选席位</b><small>基于画像匹配、资格、报名时间和每周容量求解；来源状态仅作提示，工时为系统估算。</small></div>`;
  renderMissionMap(data);
  box.innerHTML = state.portfolioPlans.map((plan) => {
    const weeks = [];
    for (const item of (plan.items || [])) {
      (item.weekly_load || []).forEach((v, i) => { weeks[i] = (weeks[i] || 0) + Number(v || 0); });
    }
    const bars = weeks.map((v, i) => {
      const pct = Math.min(100, v / Math.max(plan.capacity_hours || 1, 1) * 100);
      return `<span title="第${i + 1}周 ${v.toFixed(1)}h"><i style="height:${Math.max(4, pct)}%"></i></span>`;
    }).join("");
    const items = (plan.items || []).map((item) => `<article class="portfolio-item">
      <div><b>${escapeHtml(item.competition_name)}</b><span>${item.deadline ? `截止 ${escapeHtml(item.deadline)}` : "截止时间待确认"}</span></div>
      <strong>${Math.round(item.match_score)}</strong>
      <small>${escapeHtml((item.reasons || []).join(" · "))}</small>
    </article>`).join("");
    const notes = [...(plan.conflicts || []), ...(plan.binding_constraints || [])];
    return `<section class="portfolio-plan plan-${escapeHtml(plan.mode)}">
      <header><div><span>${escapeHtml(plan.mode.toUpperCase())}</span><h3>${escapeHtml(plan.label)}</h3></div><div class="portfolio-value"><small>组合价值</small><strong>${Math.round(plan.total_value || 0)}</strong></div></header>
      <div class="portfolio-metrics"><span>峰值 ${plan.peak_weekly_load}h/周</span><span>容量利用 ${plan.utilization}%</span><span>风险 ${plan.risk_score}</span></div>
      <div class="weekly-chart" aria-label="每周投入热力图">${bars || '<span class="muted">暂无可行赛事</span>'}</div>
      <div class="portfolio-items">${items || '<div class="empty-state"><b>当前无可行组合</b><span>可提高周可用时间或切换策略。</span></div>'}</div>
      ${notes.length ? `<div class="portfolio-notes">${notes.map((n) => `<span>⚠ ${escapeHtml(n)}</span>`).join("")}</div>` : ""}
      ${(plan.items || []).length ? `<button class="btn primary portfolio-apply" data-mode="${escapeHtml(plan.mode)}">采用这套方案</button>` : ""}
      <details><summary>查看未入选原因</summary><ul>${(plan.excluded_reasons || []).map((n) => `<li>${escapeHtml(n)}</li>`).join("") || "<li>暂无</li>"}</ul></details>
    </section>`;
  }).join("");
  $$(".portfolio-apply", box).forEach((button) => button.addEventListener("click", () => applyPortfolio(button.dataset.mode)));
}

function missionNodeState(item, plan) {
  const explicit = String(item.status || item.state || "").toLowerCase();
  if (["blocked", "ineligible", "expired", "stale"].includes(explicit)) return "blocked";
  if (["warning", "risk", "at_risk", "review"].includes(explicit)) return "risk";
  if (["done", "completed"].includes(explicit)) return "done";
  const deadline = item.deadline ? new Date(`${item.deadline}T00:00:00`) : null;
  const days = deadline && !Number.isNaN(deadline.getTime()) ? Math.ceil((deadline.getTime() - Date.now()) / 86400000) : null;
  if ((days !== null && days >= 0 && days <= 14) || Number(item.match_score || 100) < 70 || Number(plan.risk_score || 0) >= 60) return "risk";
  return "ready";
}

function normalizeMissionRoutes(data) {
  const rawRoutes = Array.isArray(data && data.routes) ? data.routes : (data && data.plans) || [];
  const defaults = [
    { mode: "steady", label: "稳妥路线", items: [], risk_score: 0 },
    { mode: "balanced", label: "均衡路线", items: [], risk_score: 0 },
    { mode: "sprint", label: "冲刺路线", items: [], risk_score: 0 },
  ];
  return defaults.map((fallback, index) => {
    const route = rawRoutes.find((item) => item.mode === fallback.mode) || rawRoutes[index] || fallback;
    // 地图先展示“这套组合实际选中了哪些赛事”；技能、材料、里程碑仍保留在项目详情中。
    // 这样避免把一个赛事的十余个内部节点全部挤在同一条路线，失去决策可读性。
    const rawNodes = (Array.isArray(route.items) && route.items.length)
      ? route.items
      : (route.roadmap_nodes || route.nodes || route.competitions || []);
    const nodes = Array.isArray(rawNodes) ? rawNodes.map((node, nodeIndex) => {
      if (typeof node === "string") return { competition_id: node, competition_name: node, order: nodeIndex };
      return {
        ...node,
        competition_id: node.competition_id || (node.node_type === "competition" ? String(node.node_id || "").replace(/^competition:/, "") : ""),
        competition_name: node.competition_name || node.label || node.name || node.node_id || "路线节点",
        deadline: node.deadline || node.due_date,
        status: node.status,
        detail: node.reason || node.detail,
        order: nodeIndex,
      };
    }) : [];
    return { ...fallback, ...route, mode: route.mode || fallback.mode, label: route.label || route.title || fallback.label, nodes };
  });
}

function renderMissionMap(data) {
  const host = $("#innovation-map");
  if (!host) return;
  const routes = normalizeMissionRoutes(data || {});
  const routeStatus = (route) => {
    if (!route.nodes.length) return { key: "blocked", label: "无可行组合" };
    const risky = route.nodes.filter((node) => missionNodeState(node, route) === "risk").length;
    return risky ? { key: "risk", label: `${risky} 个风险节点` } : { key: "ready", label: "路线可执行" };
  };
  host.innerHTML = routes.map((route, routeIndex) => {
    const status = routeStatus(route);
    const nodes = [
      { kind: "origin", competition_name: "个人画像", detail: "能力 / 时间" },
      ...route.nodes,
      { kind: "destination", competition_name: "执行工作台", detail: "任务 / 日历" },
    ];
    const path = routeIndex === 1
      ? "M 30 54 C 210 12, 330 96, 500 54 S 790 12, 970 54"
      : routeIndex === 0
        ? "M 30 54 C 240 84, 360 20, 535 54 S 790 78, 970 54"
        : "M 30 54 C 210 8, 400 104, 570 48 S 810 22, 970 54";
    return `<article class="mission-route route-${escapeHtml(route.mode)} status-${status.key}">
      <header>
        <div><span>ROUTE ${String(routeIndex + 1).padStart(2, "0")}</span><h4>${escapeHtml(route.label)}</h4></div>
        <div class="route-vitals"><b>${Math.round(Number(route.total_value || 0))}</b><span>组合价值</span><em>${escapeHtml(status.label)}</em></div>
      </header>
      <div class="route-canvas" style="--node-count:${nodes.length}">
        <svg viewBox="0 0 1000 108" preserveAspectRatio="none" aria-hidden="true"><path class="route-shadow" d="${path}"></path><path class="route-path" d="${path}"></path></svg>
        <div class="route-nodes">
          ${nodes.map((node, index) => {
            const stateKey = node.kind ? (node.kind === "origin" ? "done" : status.key) : missionNodeState(node, route);
            const score = node.match_score ?? node.score;
            const detail = node.detail || (node.deadline ? `截止 ${node.deadline}` : (node.reasons || [])[0]) || (score !== undefined ? `匹配 ${Math.round(score)}` : "待进入工作台");
            const id = node.competition_id || node.id || "";
            return `<button type="button" class="mission-node node-${stateKey} ${node.kind ? `node-${node.kind}` : ""}" ${id ? `data-map-cid="${escapeHtml(id)}"` : (node.kind === "destination" ? 'data-map-target="projects"' : "")}>
              <span class="node-orbit"><i>${index === 0 ? "◎" : index === nodes.length - 1 ? "→" : String(index).padStart(2, "0")}</i></span>
              <b>${escapeHtml(node.competition_name || node.name || `机会 ${index}`)}</b>
              <small>${escapeHtml(String(detail).slice(0, 42))}</small>
              ${stateKey === "risk" ? '<em>RISK</em>' : stateKey === "blocked" ? '<em>BLOCKED</em>' : ""}
            </button>`;
          }).join("")}
        </div>
      </div>
      <footer><span>峰值 ${escapeHtml(route.peak_weekly_load ?? "—")}h/周</span><span>容量利用 ${escapeHtml(route.utilization ?? "—")}%</span><span>${escapeHtml((route.binding_constraints || [])[0] || "约束检查通过")}</span></footer>
    </article>`;
  }).join("");
  $$("[data-map-cid]", host).forEach((button) => button.addEventListener("click", () => {
    state.detailReturn = "#/portfolio";
    location.hash = `#/detail/${encodeURIComponent(button.dataset.mapCid)}`;
  }));
  $$("[data-map-target='projects']", host).forEach((button) => button.addEventListener("click", () => { location.hash = "#/projects"; }));
}

async function applyPortfolio(mode) {
  const plan = state.portfolioPlans.find((item) => item.mode === mode);
  if (!plan) return;
  try {
    await apiPost(`/api/users/${encodeURIComponent(state.uid)}/portfolio/apply`, {
      competition_ids: plan.items.map((item) => item.competition_id),
    });
    toast(`已采用${plan.label}方案并加入我的项目`);
    location.hash = "#/projects";
  } catch (e) {
    toast("组合状态已变化，请重新计算");
    renderPortfolio();
  }
}

$("#portfolio-run").addEventListener("click", renderPortfolio);

// ---------------------------------------------------------------------------
// 动态赛事雷达
// ---------------------------------------------------------------------------
function radarTime(value) {
  if (!value) return "尚未扫描";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function radarFreshnessHours(value) {
  if (!value) return Infinity;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? Infinity : Math.max(0, (Date.now() - date.getTime()) / 3600000);
}

function radarHealthForWatch(watch) {
  const status = String(watch.last_status || "new");
  const failures = Number(watch.consecutive_failures || 0);
  const freshness = radarFreshnessHours(watch.last_checked_at);
  let score = status === "ok" ? 100 : status === "new" ? 78 : status === "error" ? 52 : 24;
  score -= Math.min(35, failures * 10);
  if (freshness !== Infinity && freshness > Number(watch.interval_hours || 24) * 2) score -= 15;
  return Math.max(5, Math.min(100, Math.round(score)));
}

function radarWatchRules(watch) {
  const explicit = watch.rules || watch.trigger_rules || watch.watch_rules;
  if (Array.isArray(explicit) && explicit.length) {
    return explicit.map((rule) => typeof rule === "string" ? rule : (rule.label || rule.name || rule.expression || JSON.stringify(rule)));
  }
  return [
    `${String(watch.source_type || "auto").toUpperCase()} 抓取`,
    watch.css_selector ? `限定区域 ${watch.css_selector}` : "全文规范化比对",
    `每 ${watch.interval_hours || 24} 小时扫描`,
    "关键字段必须人工审核",
  ];
}

function renderRadarDiff(value) {
  const text = String(value || "暂无文本差异");
  return text.split("\n").map((line) => {
    const cls = line.startsWith("+") && !line.startsWith("+++") ? "diff-add"
      : line.startsWith("-") && !line.startsWith("---") ? "diff-remove" : "";
    return `<span class="${cls}">${escapeHtml(line || " ")}</span>`;
  }).join("");
}

function radarDismissedSet() {
  try { return new Set(JSON.parse(localStorage.getItem(`cia_radar_dismissed_${state.uid || "guest"}`) || "[]")); }
  catch (_) { return new Set(); }
}

function dismissRadarInbox(key) {
  const dismissed = radarDismissedSet();
  dismissed.add(String(key));
  localStorage.setItem(`cia_radar_dismissed_${state.uid || "guest"}`, JSON.stringify(Array.from(dismissed).slice(-100)));
  renderRadar();
}

function buildRadarInbox(status, alerts) {
  const dismissed = radarDismissedSet();
  const eventById = Object.fromEntries((status.events || []).map((event) => [String(event.event_id), event]));
  const items = [];
  if (state.isAdmin) {
    (status.events || []).filter((event) => event.status === "pending").forEach((event) => items.push({
      key: `event-${event.event_id}`, kind: "review", event_id: event.event_id,
      competition_id: event.competition_id, title: event.competition_name,
      message: event.summary, severity: event.severity || "medium", created_at: event.detected_at,
      source_url: event.source_url, event,
    }));
  }
  (alerts || []).filter((alert) => ["pending", "replan_requested"].includes(alert.status || "pending")).forEach((alert) => {
    const event = eventById[String(alert.event_id)] || {};
    items.push({
      key: `alert-${alert.alert_id}`, kind: "impact", alert_id: alert.alert_id,
      event_id: alert.event_id, competition_id: alert.competition_id,
      title: alert.title, message: alert.message, severity: event.severity || "high",
      created_at: alert.created_at, source_url: event.source_url, event,
    });
  });
  return items.filter((item) => !dismissed.has(item.key)).sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")));
}

async function radarCreateTask(key) {
  const item = (state.radarInboxItems || []).find((entry) => entry.key === key);
  if (!item) return;
  if (item.alert_id && state.uid) {
    try {
      await apiPost(`/api/users/${encodeURIComponent(state.uid)}/alerts/${encodeURIComponent(item.alert_id)}/action`, {
        action: "create_task", note: "从雷达收件箱转为执行任务",
      });
      dismissRadarInbox(key);
      toast("情报已转为项目任务，并保留来源链");
      return;
    } catch (error) {
      toast(`创建任务失败：${error.message}`);
      return;
    }
  }
  let project = state.projects.find((entry) => entry.competition_id === item.competition_id);
  if (!project && state.uid) {
    try {
      state.projects = await apiGet(`/api/users/${encodeURIComponent(state.uid)}/projects`);
      project = state.projects.find((entry) => entry.competition_id === item.competition_id);
    } catch (_) {}
  }
  if (!project) {
    toast("该赛事尚未加入项目，先查看赛事详情");
    state.detailReturn = "#/radar";
    location.hash = `#/detail/${encodeURIComponent(item.competition_id)}`;
    return;
  }
  const changes = item.event && item.event.proposed_changes ? Object.values(item.event.proposed_changes) : [];
  const dated = changes.find((change) => change && /^\d{4}-\d{2}-\d{2}$/.test(String(change.value || "")));
  try {
    await apiPost(`/api/users/${encodeURIComponent(state.uid)}/projects/${project.project_id}/items`, {
      item_type: "task",
      title: `处理雷达情报：${item.message || item.title}`.slice(0, 200),
      due_date: dated ? dated.value : null,
    });
    dismissRadarInbox(key);
    toast("情报已转为项目任务");
  } catch (error) { toast(`创建任务失败：${error.message}`); }
}

async function radarActOnAlert(alertId, action, key) {
  if (!state.uid || !alertId) return;
  try {
    const result = await apiPost(`/api/users/${encodeURIComponent(state.uid)}/alerts/${encodeURIComponent(alertId)}/action`, {
      action,
      note: action === "replan" ? "从雷达收件箱请求重新规划" : "已处理雷达收件箱事项",
    });
    if (action === "replan" || result.replan_required) {
      toast("已标记重新规划，正在打开组合求解器");
      location.hash = "#/portfolio";
    } else {
      if (key) dismissRadarInbox(key);
      else renderRadar();
      toast(action === "accept" ? "已接受变化并解除相关阻塞" : "已忽略该变化");
    }
  } catch (error) { toast(error.message); }
}

async function renderRadar() {
  $("#radar-run").classList.toggle("hidden", !state.isAdmin);
  $("#radar-demo").classList.toggle("hidden", !state.isAdmin);
  const requests = [apiGet("/api/radar/status")];
  if (state.uid && state.consent) requests.push(apiGet(`/api/users/${encodeURIComponent(state.uid)}/alerts`));
  if (state.uid && state.consent) requests.push(apiGet(`/api/users/${encodeURIComponent(state.uid)}/projects`));
  const results = await Promise.allSettled(requests);
  if (results[0].status !== "fulfilled") {
    const e = results[0].reason;
    $("#radar-events").innerHTML = `<div class="empty-state"><b>雷达暂不可用</b><span>${escapeHtml(e.message)}</span></div>`;
    return;
  }
  const data = results[0].value || {};
  const alertsPayload = results[1] && results[1].status === "fulfilled" ? results[1].value : { alerts: [] };
  if (results[2] && results[2].status === "fulfilled") state.projects = results[2].value || [];
  state.radarStatus = data;
  const watches = Array.isArray(data.watches) ? data.watches : [];
  const events = Array.isArray(data.events) ? data.events : [];
  const healthy = data.healthy_count ?? watches.filter((watch) => ["new", "ok"].includes(watch.last_status)).length;
  const pending = data.pending_count ?? events.filter((event) => event.status === "pending").length;
  $("#radar-watch-count").textContent = data.watch_count ?? watches.length;
  $("#radar-healthy-count").textContent = healthy;
  $("#radar-pending-count").textContent = pending;

  const healthScores = watches.map(radarHealthForWatch);
  const healthScore = healthScores.length ? Math.round(healthScores.reduce((sum, value) => sum + value, 0) / healthScores.length) : 0;
  const degraded = watches.filter((watch) => ["error", "stale"].includes(watch.last_status)).length;
  const stale = watches.filter((watch) => radarFreshnessHours(watch.last_checked_at) > Number(watch.interval_hours || 24) * 2).length;
  const signal = healthScore >= 90 ? "NOMINAL" : healthScore >= 65 ? "DEGRADED" : "CRITICAL";
  $("#radar-signal").textContent = `SIGNAL ${signal}`;
  $("#radar-signal").dataset.signal = signal.toLowerCase();
  $("#radar-health-overview").innerHTML = `<div class="health-dial" style="--health:${healthScore}"><div><b>${healthScore}</b><span>HEALTH</span></div></div>
    <div class="health-facts"><span><b>${healthy}</b>正常来源</span><span><b>${degraded}</b>降级来源</span><span><b>${stale}</b>超时来源</span><span><b>${watches.reduce((sum, watch) => sum + Number(watch.consecutive_failures || 0), 0)}</b>连续失败</span></div>
    <div class="health-stream">${watches.slice(0, 6).map((watch) => `<span title="${escapeHtml(watch.competition_name || watch.competition_id)}"><i style="width:${radarHealthForWatch(watch)}%"></i><b>${escapeHtml(String(watch.competition_name || watch.competition_id).slice(0, 9))}</b><em>${radarHealthForWatch(watch)}</em></span>`).join("") || '<small>尚无健康样本</small>'}</div>`;

  $("#radar-rules").innerHTML = watches.slice(0, 5).map((watch, index) => `<article>
    <header><span>${String(index + 1).padStart(2, "0")}</span><b>${escapeHtml(watch.competition_name || watch.competition_id)}</b><em>${watch.enabled === false ? "PAUSED" : "ACTIVE"}</em></header>
    <div>${radarWatchRules(watch).map((rule) => `<span>${escapeHtml(rule)}</span>`).join("")}</div>
  </article>`).join("") || '<div class="command-empty">尚未配置监控规则</div>';

  state.radarInboxItems = buildRadarInbox({ ...data, events }, alertsPayload.alerts || []);
  $("#radar-inbox-count").textContent = `${state.radarInboxItems.length} NEW`;
  $("#radar-inbox").innerHTML = state.radarInboxItems.slice(0, 6).map((item) => `<article class="inbox-item severity-${escapeHtml(item.severity)}">
    <span class="inbox-signal">${item.kind === "review" ? "REVIEW" : "IMPACT"}</span>
    <div><b>${escapeHtml(item.title || item.competition_id)}</b><p>${escapeHtml(item.message || "官方来源发生变化")}</p><small>${escapeHtml(radarTime(item.created_at))}</small></div>
    <div class="inbox-actions">
      ${item.kind === "review" && state.isAdmin ? `<button class="inbox-primary radar-inbox-review" data-key="${escapeHtml(item.key)}" data-id="${item.event_id}" data-action="approve">确认</button><button class="radar-inbox-review" data-key="${escapeHtml(item.key)}" data-id="${item.event_id}" data-action="reject">忽略</button>` : `<button class="inbox-primary radar-to-task" data-key="${escapeHtml(item.key)}">转任务</button>${item.alert_id ? `<button class="radar-alert-action" data-key="${escapeHtml(item.key)}" data-id="${item.alert_id}" data-action="accept">接受</button><button class="radar-alert-action" data-key="${escapeHtml(item.key)}" data-id="${item.alert_id}" data-action="replan">重规划</button>` : ""}<button class="radar-open-project" data-cid="${escapeHtml(item.competition_id)}">打开项目</button><button class="radar-dismiss" data-key="${escapeHtml(item.key)}">稍后</button>`}
    </div>
  </article>`).join("") || '<div class="command-empty"><b>情报已清空</b><span>新的规则变化会在这里等待处置</span></div>';

  $("#radar-watches").innerHTML = watches.map((watch) => {
    const status = ({ new: "等待基线", ok: "正常", error: "暂时异常", stale: "连续失败" })[watch.last_status] || watch.last_status;
    const health = radarHealthForWatch(watch);
    return `<div class="radar-watch"><span class="radar-dot status-${escapeHtml(watch.last_status)}"></span><div><b>${escapeHtml(watch.competition_name || watch.competition_id)}</b><a href="${escapeHtml(watch.source_url)}" target="_blank" rel="noopener">${escapeHtml(watch.source_url)}</a><span class="watch-tags"><i>${escapeHtml(String(watch.source_type || "auto").toUpperCase())}</i><i>${watch.interval_hours || 24}H</i>${watch.css_selector ? '<i>SELECTOR</i>' : ""}</span></div><small><b>${health}</b>${escapeHtml(status)} · ${escapeHtml(radarTime(watch.last_checked_at))}</small></div>`;
  }).join("") || '<div class="empty-state"><b>尚未配置监控来源</b><span>管理员可从已核验赛事创建监控项。</span></div>';

  const filteredEvents = events.filter((event) => state.radarFilter === "all"
    || (state.radarFilter === "pending" && event.status === "pending")
    || (state.radarFilter === "high" && event.severity === "high"));
  $$('[data-radar-filter]').forEach((button) => button.classList.toggle("active", button.dataset.radarFilter === state.radarFilter));
  $("#radar-events").innerHTML = filteredEvents.map((event) => {
    const pending = event.status === "pending";
    const severity = event.severity || "low";
    return `<article class="radar-event severity-${escapeHtml(severity)}">
      <header><div><span>${escapeHtml(severity.toUpperCase())}</span><b>${escapeHtml(event.competition_name || event.competition_id)}</b></div><em>${escapeHtml(({ pending: "待审核", approved: "已确认", rejected: "已忽略" })[event.status] || event.status)}</em></header>
      <p>${escapeHtml(event.summary)}</p>
      ${(event.affected_fields || []).length ? `<div class="radar-fields">影响字段：${event.affected_fields.map(escapeHtml).join("、")}</div>` : ""}
      <div class="event-meta"><span>◷ ${escapeHtml(radarTime(event.detected_at))}</span><span>${escapeHtml(event.change_type || "content_change")}</span>${event.source_url ? `<a href="${escapeHtml(event.source_url)}" target="_blank" rel="noopener">官方来源 ↗</a>` : ""}</div>
      <details><summary>查看新旧原文差异</summary><pre class="radar-diff">${renderRadarDiff(event.diff_text)}</pre></details>
      ${pending && state.isAdmin ? `<div class="row"><button class="btn primary radar-review" data-id="${event.event_id}" data-action="approve">确认变化</button><button class="btn ghost radar-review" data-id="${event.event_id}" data-action="reject">忽略</button></div>` : ""}
    </article>`;
  }).join("") || '<div class="empty-state"><b>当前筛选下没有情报</b><span>首次扫描会建立可信基线，后续扫描才产生差异事件。</span></div>';
  $$(".radar-review", $("#radar-events")).forEach((button) => button.addEventListener("click", () => reviewRadarEvent(button.dataset.id, button.dataset.action)));
  $$(".radar-inbox-review", $("#radar-inbox")).forEach((button) => button.addEventListener("click", async () => {
    await reviewRadarEvent(button.dataset.id, button.dataset.action);
  }));
  $$(".radar-to-task", $("#radar-inbox")).forEach((button) => button.addEventListener("click", () => radarCreateTask(button.dataset.key)));
  $$(".radar-alert-action", $("#radar-inbox")).forEach((button) => button.addEventListener("click", () => radarActOnAlert(button.dataset.id, button.dataset.action, button.dataset.key)));
  $$(".radar-dismiss", $("#radar-inbox")).forEach((button) => button.addEventListener("click", () => dismissRadarInbox(button.dataset.key)));
  $$(".radar-open-project", $("#radar-inbox")).forEach((button) => button.addEventListener("click", () => {
    state.projectFocus = button.dataset.cid;
    state.projectView = "list";
    localStorage.setItem("cia_project_view", "list");
    location.hash = "#/projects";
  }));
}

async function reviewRadarEvent(eventId, action) {
  if (action === "approve" && !window.confirm("确认将确定性识别出的关键字段写入赛事事实，并提醒相关项目？")) return;
  try {
    await apiPost(`/api/admin/radar/events/${eventId}/review`, { action, note: "通过态势中心审核" }, adminHeaders());
    toast(action === "approve" ? "变化已确认并完成影响通知" : "变化已忽略");
    renderRadar();
  } catch (e) { toast(e.message); }
}

$("#radar-run").addEventListener("click", async () => {
  try {
    const result = await apiPost("/api/admin/radar/run", {}, adminHeaders());
    toast(`扫描完成：${result.checked} 个来源，发现 ${result.changed} 项变化`);
    renderRadar();
  } catch (e) { toast(e.message); }
});

$("#radar-demo").addEventListener("click", async () => {
  try {
    const status = await apiGet("/api/radar/status");
    const watch = (status.watches || [])[0];
    if (!watch) { toast("尚无可演示的监控来源"); return; }
    const first = `<main><h1>赛事官方通知</h1><p>报名截止时间：2026年09月30日</p><p>参赛对象：在校本科生</p></main>`;
    const changed = `<main><h1>赛事官方通知（更新）</h1><p>报名截止时间调整为：2026年09月20日</p><p>参赛对象：在校本科生</p></main>`;
    await apiPost("/api/admin/radar/run", { watch_ids: [watch.watch_id], demo_content_by_watch: { [watch.watch_id]: first } }, adminHeaders());
    await apiPost("/api/admin/radar/run", { watch_ids: [watch.watch_id], demo_content_by_watch: { [watch.watch_id]: changed } }, adminHeaders());
    toast("已生成一条待审核的截止日期变化");
    renderRadar();
  } catch (e) { toast(e.message); }
});

$$('[data-radar-filter]').forEach((button) => button.addEventListener("click", () => {
  state.radarFilter = button.dataset.radarFilter || "all";
  renderRadar();
}));

// ---------------------------------------------------------------------------
// 我的项目：任务、材料、状态与日历
// ---------------------------------------------------------------------------
const PROJECT_STATUS = { planned: "待开始", in_progress: "进行中", completed: "已完成" };

function projectDate(value) {
  if (!value) return null;
  const date = new Date(`${String(value).slice(0, 10)}T00:00:00`);
  return Number.isNaN(date.getTime()) ? null : date;
}

function isoDay(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function projectDependencyInfo(project, item) {
  const items = project.items || [];
  const tasks = items.filter((entry) => entry.item_type === "task").slice().sort((a, b) => Number(a.sort_order || 0) - Number(b.sort_order || 0));
  let raw = item.blocked_by ?? item.depends_on ?? item.depends_on_item_id ?? item.dependencies ?? item.dependency_ids ?? [];
  if (raw && !Array.isArray(raw)) raw = [raw];
  let dependencies = (raw || []).map((ref) => {
    if (ref && typeof ref === "object") {
      const found = items.find((entry) => String(entry.item_id) === String(ref.item_id ?? ref.id));
      return found || { item_id: ref.item_id ?? ref.id, title: ref.title || ref.name || "前置任务", status: ref.status || "todo" };
    }
    const found = items.find((entry) => String(entry.item_id) === String(ref) || entry.title === String(ref));
    return found || { item_id: ref, title: String(ref), status: "todo" };
  });
  // 现有后端尚未返回依赖字段时，以任务 sort_order 形成稳定的阶段链；显式契约上线后自动优先采用。
  if (!dependencies.length && item.item_type === "task") {
    const index = tasks.findIndex((entry) => String(entry.item_id) === String(item.item_id));
    if (index > 0) dependencies = [tasks[index - 1]];
  }
  const unresolved = dependencies.filter((entry) => !["done", "skipped"].includes(String(entry.status)));
  return {
    dependencies,
    unresolved,
    blocked: item.status !== "done" && item.status !== "skipped" && (item.is_blocked || item.blocked_reason || unresolved.length > 0),
  };
}

function projectOverview(projects) {
  const allItems = projects.flatMap((project) => (project.items || []).map((item) => ({ project, item, dependency: projectDependencyInfo(project, item) })));
  const completed = allItems.filter(({ item }) => item.status === "done").length;
  const blocked = allItems.filter(({ dependency }) => dependency.blocked).length;
  const now = new Date(); now.setHours(0, 0, 0, 0);
  const dueSoon = allItems.filter(({ item }) => {
    const due = projectDate(item.due_date);
    if (!due || item.status === "done") return false;
    const days = (due - now) / 86400000;
    return days >= 0 && days <= 14;
  }).length;
  return { allItems, completed, blocked, dueSoon, progress: allItems.length ? Math.round(completed / allItems.length * 100) : 0 };
}

function renderProjectSummary(projects) {
  const summary = $("#project-exec-summary");
  if (!summary) return;
  const stats = projectOverview(projects);
  const active = projects.filter((project) => project.status === "in_progress").length;
  summary.innerHTML = `<div class="exec-radar" style="--exec-progress:${stats.progress}"><span><b>${stats.progress}%</b><small>整体推进</small></span></div>
    <div class="exec-stat"><span>ACTIVE PROJECTS</span><b>${active}</b><small>${projects.length} 个参赛项目</small></div>
    <div class="exec-stat"><span>OPEN ITEMS</span><b>${stats.allItems.length - stats.completed}</b><small>${stats.completed} 项已完成</small></div>
    <div class="exec-stat ${stats.blocked ? "has-risk" : ""}"><span>BLOCKERS</span><b>${stats.blocked}</b><small>等待前置任务</small></div>
    <div class="exec-stat ${stats.dueSoon ? "has-warning" : ""}"><span>DUE IN 14D</span><b>${stats.dueSoon}</b><small>临近节点</small></div>`;
}

function renderProjectItems(project, items, empty) {
  if (!items.length) return `<div class="item-empty">${empty}</div>`;
  return items.map((item) => {
    const dependency = projectDependencyInfo(project, item);
    const dependencyLabel = dependency.dependencies.length ? `前置：${dependency.dependencies.map((entry) => entry.title).join("、")}` : "";
    return `<div class="project-item ${item.status === "done" ? "done" : ""} ${dependency.blocked ? "blocked" : ""}">
      <input class="item-toggle" type="checkbox" data-pid="${project.project_id}" data-iid="${item.item_id}" ${item.status === "done" ? "checked" : ""} ${dependency.blocked ? "disabled" : ""} />
      <span class="item-title">${escapeHtml(item.title)}${dependencyLabel ? `<small class="dependency-chip" title="${escapeHtml(dependencyLabel)}">${dependency.blocked ? "阻塞" : "依赖"} · ${escapeHtml(dependency.dependencies[0].title)}</small>` : ""}</span>
      <span class="item-date">${escapeHtml(item.due_date || "无截止")}</span>
      <button class="icon-btn item-delete" data-pid="${project.project_id}" data-iid="${item.item_id}" title="删除条目">×</button>
    </div>`;
  }).join("");
}

function renderProjectsList(projects) {
  return projects.map((p) => {
    const tasks = (p.items || []).filter((item) => item.item_type === "task");
    const materials = (p.items || []).filter((item) => item.item_type === "material");
    const done = (p.items || []).filter((item) => item.status === "done").length;
    const pct = p.items.length ? Math.round(done / p.items.length * 100) : 0;
    const blockers = (p.items || []).filter((item) => projectDependencyInfo(p, item).blocked).length;
    return `<article class="project-card project-${escapeHtml(p.status)} ${state.projectFocus === p.competition_id ? "is-focused" : ""}" data-pid="${p.project_id}" data-cid="${escapeHtml(p.competition_id)}">
      <header class="project-head">
        <div><div class="project-kicker">${p.document_year} · ${escapeHtml(p.competition_id)}</div>
        <h3>${escapeHtml(p.competition_name)}</h3><div class="project-healthline"><span class="status-${escapeHtml(p.status)}">${escapeHtml(PROJECT_STATUS[p.status] || p.status)}</span>${blockers ? `<em>${blockers} 个阻塞</em>` : ""}</div></div>
        <div class="project-actions">
          <select class="project-status" data-pid="${p.project_id}" aria-label="更新项目状态">
            ${Object.entries(PROJECT_STATUS).map(([value, label]) => `<option value="${value}" ${p.status === value ? "selected" : ""}>${label}</option>`).join("")}
          </select>
          <a class="btn" href="/api/users/${encodeURIComponent(state.uid)}/projects/${p.project_id}/calendar.ics">导出 ICS</a>
          <button class="btn danger project-delete" data-pid="${p.project_id}">删除项目</button>
        </div>
      </header>
      ${p.recommendation_ready ? "" : `<div class="project-trust-warning">来源状态已变化：${escapeHtml((p.readiness_reasons || []).join("；"))}。项目数据已保留，请重新核对官网。</div>`}
      <div class="deadline-strip"><span>报名截止 <b>${escapeHtml(p.registration_deadline || "未明确")}</b></span><span>提交截止 <b>${escapeHtml(p.submission_deadline || "未明确")}</b></span></div>
      <div class="progress-line"><span style="width:${pct}%"></span></div><div class="progress-copy">已完成 ${done}/${p.items.length} · ${pct}%</div>
      <div class="project-columns">
        <section><h4>任务计划 <span>${tasks.length}</span></h4>${renderProjectItems(p, tasks, "暂无任务")}</section>
        <section><h4>材料清单 <span>${materials.length}</span></h4>${renderProjectItems(p, materials, "官方通知未列明材料")}</section>
      </div>
      <form class="item-form" data-pid="${p.project_id}">
        <select name="item_type"><option value="task">任务</option><option value="material">材料</option></select>
        <input name="title" maxlength="200" placeholder="添加任务或材料" required />
        <input name="due_date" type="date" />
        <button class="btn" type="submit">添加</button>
      </form>
    </article>`;
  }).join("");
}

function renderProjectsBoard(projects) {
  const entries = projects.flatMap((project) => (project.items || []).map((item) => ({ project, item, dependency: projectDependencyInfo(project, item) })));
  const columns = [
    { key: "todo", label: "待执行", items: entries.filter(({ item, dependency }) => item.status !== "done" && !dependency.blocked) },
    { key: "blocked", label: "受阻", items: entries.filter(({ item, dependency }) => item.status !== "done" && dependency.blocked) },
    { key: "done", label: "已完成", items: entries.filter(({ item }) => item.status === "done") },
  ];
  return `<div class="execution-board">${columns.map((column) => `<section class="board-column board-${column.key}">
    <header><div><i></i><b>${column.label}</b></div><span>${column.items.length}</span></header>
    <div class="board-stack">${column.items.map(({ project, item, dependency }) => `<article class="board-item ${dependency.blocked ? "is-blocked" : ""}">
      <div class="board-item-top"><span>${item.item_type === "material" ? "材料" : "任务"}</span><em>${escapeHtml(project.document_year)}</em></div>
      <h4>${escapeHtml(item.title)}</h4><p>${escapeHtml(project.competition_name)}</p>
      ${dependency.blocked ? `<div class="board-blocker">↳ 等待 ${escapeHtml(dependency.unresolved[0].title)}</div>` : ""}
      <footer><span>${item.due_date ? `◷ ${escapeHtml(item.due_date)}` : "无截止"}</span><label title="切换完成状态"><input class="item-toggle" type="checkbox" data-pid="${project.project_id}" data-iid="${item.item_id}" ${item.status === "done" ? "checked" : ""} ${dependency.blocked ? "disabled" : ""}/><i></i></label></footer>
    </article>`).join("") || '<div class="board-empty">暂无条目</div>'}</div>
  </section>`).join("")}</div>`;
}

function collectProjectEvents(projects) {
  const events = [];
  projects.forEach((project) => {
    if (project.registration_deadline) events.push({ date: project.registration_deadline, title: "报名截止", kind: "official", project });
    if (project.submission_deadline) events.push({ date: project.submission_deadline, title: "提交截止", kind: "official urgent", project });
    (project.items || []).forEach((item) => {
      if (item.due_date) events.push({ date: item.due_date, title: item.title, kind: item.item_type, project, item });
    });
  });
  return events.filter((event) => projectDate(event.date)).sort((a, b) => String(a.date).localeCompare(String(b.date)));
}

function renderProjectsCalendar(projects) {
  const events = collectProjectEvents(projects);
  if (!state.projectCalendarCursor) {
    const nowKey = isoDay(new Date());
    const seed = events.find((event) => event.date >= nowKey) || events[0];
    const base = seed ? projectDate(seed.date) : new Date();
    state.projectCalendarCursor = new Date(base.getFullYear(), base.getMonth(), 1);
  }
  const cursor = state.projectCalendarCursor;
  const first = new Date(cursor.getFullYear(), cursor.getMonth(), 1);
  const start = new Date(first);
  start.setDate(1 - ((first.getDay() + 6) % 7));
  const eventMap = {};
  events.forEach((event) => { (eventMap[event.date] ||= []).push(event); });
  const days = Array.from({ length: 42 }, (_, index) => { const date = new Date(start); date.setDate(start.getDate() + index); return date; });
  const today = isoDay(new Date());
  return `<section class="execution-calendar">
    <header><button type="button" data-calendar-move="-1" aria-label="上个月">←</button><div><span>EXECUTION CALENDAR</span><h3>${cursor.getFullYear()} 年 ${cursor.getMonth() + 1} 月</h3></div><button type="button" data-calendar-move="1" aria-label="下个月">→</button></header>
    <div class="calendar-week"><span>周一</span><span>周二</span><span>周三</span><span>周四</span><span>周五</span><span>周六</span><span>周日</span></div>
    <div class="calendar-grid">${days.map((date) => {
      const key = isoDay(date); const dayEvents = eventMap[key] || [];
      return `<article class="calendar-day ${date.getMonth() !== cursor.getMonth() ? "is-outside" : ""} ${key === today ? "is-today" : ""}"><time>${date.getDate()}</time><div>${dayEvents.slice(0, 4).map((event) => `<span class="calendar-event event-${escapeHtml(event.kind.replace(" ", "-"))}" title="${escapeHtml(event.project.competition_name)} · ${escapeHtml(event.title)}"><i></i><b>${escapeHtml(event.title)}</b><small>${escapeHtml(event.project.competition_name)}</small></span>`).join("")}${dayEvents.length > 4 ? `<em>+${dayEvents.length - 4} 项</em>` : ""}</div></article>`;
    }).join("")}</div>
  </section>`;
}

function renderProjectsTimeline(projects) {
  const events = collectProjectEvents(projects);
  if (!events.length) return '<div class="empty-state"><b>暂无时间节点</b><span>为任务添加截止日期后即可生成时间线。</span></div>';
  let start = projectDate(events[0].date); let end = projectDate(events[events.length - 1].date);
  if ((end - start) < 30 * 86400000) end = new Date(start.getTime() + 30 * 86400000);
  const span = Math.max(1, end - start);
  const position = (date) => Math.max(1, Math.min(99, ((projectDate(date) - start) / span) * 100));
  return `<section class="execution-timeline">
    <header><div><span>MASTER TIMELINE</span><h3>跨赛事执行时间线</h3><small>点击节点查看完整任务</small></div><div><div class="timeline-legend" aria-label="时间线节点图例"><span class="legend-done"><i></i>已完成</span><span class="legend-task"><i></i>待办任务</span><span class="legend-official"><i></i>报名/官方节点</span><span class="legend-submit"><i></i>提交截止</span><span class="legend-material"><i></i>材料准备</span></div><b>${escapeHtml(isoDay(start))}</b><i></i><b>${escapeHtml(isoDay(end))}</b></div></header>
    <div class="timeline-scale">${[0, .25, .5, .75, 1].map((ratio) => { const date = new Date(start.getTime() + span * ratio); return `<span style="left:${ratio * 100}%">${date.getMonth() + 1}/${date.getDate()}</span>`; }).join("")}</div>
    <div class="timeline-lanes">${projects.map((project) => {
      const routeEvents = events.filter((event) => event.project.project_id === project.project_id);
      const positioned = routeEvents.map((event) => ({ ...event, position: position(event.date) })).sort((a, b) => a.position - b.position);
      const recentPositions = [];
      positioned.forEach((event) => {
        while (recentPositions.length && event.position - recentPositions[0] > 13) recentPositions.shift();
        event.stack = recentPositions.length % 4;
        recentPositions.push(event.position);
      });
      const blockers = (project.items || []).filter((item) => projectDependencyInfo(project, item).blocked);
      return `<article class="timeline-lane"><div class="timeline-label"><span>${escapeHtml(project.document_year)}</span><b>${escapeHtml(project.competition_name)}</b>${blockers.length ? `<em>${blockers.length} BLOCKED</em>` : ""}</div><div class="timeline-track-line">
        ${positioned.map((event) => `<button type="button" class="timeline-point point-${escapeHtml(event.kind.replace(" ", "-"))} ${event.item && event.item.status === "done" ? "is-done" : ""}" style="left:${event.position}%;--stack:${event.stack}" title="${escapeHtml(event.date)} · ${escapeHtml(event.title)}"><i></i><span>${escapeHtml(event.title)}</span><small>${escapeHtml(event.date)}</small></button>`).join("") || '<span class="timeline-no-date">暂无节点</span>'}
      </div></article>`;
    }).join("")}</div>
  </section>`;
}

function syncProjectViewSwitch() {
  $$("[data-project-view]").forEach((button) => {
    const active = button.dataset.projectView === state.projectView;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
}

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
    $("#project-exec-summary").innerHTML = "";
    box.innerHTML = '<div class="empty-state"><b>还没有参赛项目</b><span>从赛事详情或正式推荐中点击“加入我的项目”。</span></div>';
    return;
  }
  state.projects = projects;
  renderProjectSummary(projects);
  syncProjectViewSwitch();
  box.className = `project-list project-view-${state.projectView}`;
  box.innerHTML = state.projectView === "board" ? renderProjectsBoard(projects)
    : state.projectView === "calendar" ? renderProjectsCalendar(projects)
      : state.projectView === "timeline" ? renderProjectsTimeline(projects)
        : renderProjectsList(projects);

  // 同一时刻只在一个圆点旁显示浮动文字，避免密集任务名称互相遮挡。
  const timelineNodes = $$(".timeline-point", box);
  timelineNodes.forEach((node) => node.addEventListener("click", () => {
    const wasActive = node.classList.contains("is-active");
    timelineNodes.forEach((item) => item.classList.remove("is-active"));
    if (!wasActive) node.classList.add("is-active");
  }));

  $$(".project-status", box).forEach((el) => el.addEventListener("change", async () => {
    try {
      await apiPatch(`/api/users/${encodeURIComponent(state.uid)}/projects/${el.dataset.pid}`, { status: el.value });
      toast("项目状态已更新");
      renderProjects();
    } catch (error) { toast(error.message); }
  }));
  $$(".item-toggle", box).forEach((el) => el.addEventListener("change", async () => {
    try {
      await apiPatch(`/api/users/${encodeURIComponent(state.uid)}/projects/${el.dataset.pid}/items/${el.dataset.iid}`, { status: el.checked ? "done" : "todo" });
      renderProjects();
    } catch (error) { toast(error.message); }
  }));
  $$(".item-delete", box).forEach((el) => el.addEventListener("click", async () => {
    try {
      await apiDelete(`/api/users/${encodeURIComponent(state.uid)}/projects/${el.dataset.pid}/items/${el.dataset.iid}`);
      renderProjects();
    } catch (error) { toast(error.message); }
  }));
  $$(".project-delete", box).forEach((el) => el.addEventListener("click", async () => {
    if (!confirm("确认删除这个项目及其任务和材料？")) return;
    try {
      await apiDelete(`/api/users/${encodeURIComponent(state.uid)}/projects/${el.dataset.pid}`);
      renderProjects();
    } catch (error) { toast(error.message); }
  }));
  $$(".item-form", box).forEach((form) => form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(form);
    try {
      await apiPost(`/api/users/${encodeURIComponent(state.uid)}/projects/${form.dataset.pid}/items`, {
        item_type: data.get("item_type"), title: data.get("title"), due_date: data.get("due_date") || null,
      });
      renderProjects();
    } catch (error) { toast(error.message); }
  }));
  $$("[data-calendar-move]", box).forEach((button) => button.addEventListener("click", () => {
    const cursor = state.projectCalendarCursor || new Date();
    state.projectCalendarCursor = new Date(cursor.getFullYear(), cursor.getMonth() + Number(button.dataset.calendarMove), 1);
    renderProjects();
  }));
  if (state.projectFocus) {
    const focus = $$("[data-cid]", box).find((element) => element.dataset.cid === state.projectFocus);
    if (focus) focus.scrollIntoView({ behavior: "smooth", block: "center" });
    state.projectFocus = null;
  }
}

$$('[data-project-view]').forEach((button) => button.addEventListener("click", () => {
  state.projectView = button.dataset.projectView || "list";
  localStorage.setItem("cia_project_view", state.projectView);
  syncProjectViewSwitch();
  renderProjects();
}));

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

// 将答案渲染为轻量 Markdown（**加粗**）的结构化文本
function renderAnswerWithCites(text) {
  let html = escapeHtml(text || "");
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\s*\[\d+\]/g, "");
  return html;
}

function cleanAgentAnswer(text) {
  return String(text || "")
    .replace(/\n+\s*[—-]+\s*引用来源\s*[—-]+\s*\n[\s\S]*$/u, "")
    .trim();
}

// ---------------------------------------------------------------------------
// 决策运行剧场：只呈现可审计的业务节点，不暴露模型隐式思维链
// ---------------------------------------------------------------------------
function traceStatusFromText(value) {
  const text = String(value || "").toLowerCase();
  if (/失败|异常|一票否决|阻断|error|failed|blocked|rejected/.test(text)) return "blocked";
  if (/跳过|兜底|回退|降级|未启用|无结果|待补充|需用户|fallback|skipped|degraded/.test(text)) return "fallback";
  if (/待审核|警告|近似|pending|warning|review/.test(text)) return "warning";
  if (/运行中|处理中|running|processing/.test(text)) return "running";
  return "success";
}

function normalizeTraceStatus(value, fallbackText = "") {
  const key = String(value || "").toLowerCase();
  if (["ok", "done", "complete", "completed", "success", "passed", "verified"].includes(key)) return "success";
  if (["error", "failed", "blocked", "rejected", "denied"].includes(key)) return "blocked";
  if (["skip", "skipped", "fallback", "degraded"].includes(key)) return "fallback";
  if (["pending", "warning", "review", "needs_review"].includes(key)) return "warning";
  if (["running", "processing", "active"].includes(key)) return "running";
  return traceStatusFromText(fallbackText || value);
}

function traceDurationMs(step) {
  const raw = step.duration_ms ?? step.latency_ms ?? step.elapsed_ms ?? step.time_ms
    ?? (step.metrics && (step.metrics.duration_ms ?? step.metrics.latency_ms));
  if (Number.isFinite(Number(raw))) return Math.max(0, Number(raw));
  if (Number.isFinite(Number(step.duration_seconds))) return Math.max(0, Number(step.duration_seconds) * 1000);
  if (typeof step.duration === "number") return step.duration > 100 ? step.duration : step.duration * 1000;
  return null;
}

function traceEvidenceCount(step, detail = "") {
  const direct = step.evidence_count ?? step.citation_count ?? step.source_count ?? step.hit_count
    ?? (step.metrics && (step.metrics.evidence_count ?? step.metrics.hits));
  if (Number.isFinite(Number(direct))) return Number(direct);
  for (const key of ["evidence", "citations", "sources", "hits"]) {
    if (Array.isArray(step[key])) return step[key].length;
  }
  const match = String(detail || "").match(/(?:命中|召回|保留)\s*(\d+)\s*(?:条)?证据/);
  return match ? Number(match[1]) : 0;
}

function normalizeTraceStep(value, index, nameHint = "") {
  if (typeof value === "string" || typeof value === "number") {
    const detail = String(value).trim();
    const colon = detail.search(/[：:]/);
    const title = colon > 0 && colon < 18 ? detail.slice(0, colon).trim() : `执行节点 ${String(index + 1).padStart(2, "0")}`;
    return {
      title,
      detail: colon > 0 && colon < 18 ? detail.slice(colon + 1).trim() : detail,
      status: traceStatusFromText(detail), durationMs: null,
      evidenceCount: traceEvidenceCount({}, detail), version: "", fallback: "",
    };
  }
  const step = value && typeof value === "object" ? value : {};
  const title = step.title || step.label || step.name || step.node || step.step || step.stage || nameHint || `执行节点 ${String(index + 1).padStart(2, "0")}`;
  let detail = step.summary ?? step.message ?? step.detail ?? step.description ?? step.output_summary ?? "";
  if (detail && typeof detail === "object") {
    try { detail = JSON.stringify(detail); } catch (_) { detail = String(detail); }
  }
  if (!detail) {
    const safe = Object.entries(step).filter(([key]) => ![
      "title", "label", "name", "node", "step", "stage", "status", "state",
      "duration", "duration_ms", "latency_ms", "elapsed_ms", "metrics", "version",
      "doc_version", "data_version", "snapshot_version", "fallback", "fallback_reason",
    ].includes(key));
    detail = safe.slice(0, 3).map(([key, item]) => `${key}=${Array.isArray(item) ? item.length : String(item)}`).join(" · ");
  }
  const fallback = step.fallback_reason || step.degrade_reason || (typeof step.fallback === "string" ? step.fallback : "") || "";
  return {
    title: String(title), detail: String(detail || "已完成确定性处理"),
    status: normalizeTraceStatus(step.status || step.state || (step.fallback ? "fallback" : ""), `${detail} ${fallback}`),
    durationMs: traceDurationMs(step),
    evidenceCount: traceEvidenceCount(step, detail),
    version: String(step.version || step.doc_version || step.data_version || step.snapshot_version || step.model || ""),
    fallback: String(fallback),
  };
}

function normalizeTrace(trace) {
  if (trace === null || trace === undefined || trace === "") return [];
  let value = trace;
  if (typeof value === "string") {
    const text = value.trim();
    if ((text.startsWith("[") && text.endsWith("]")) || (text.startsWith("{") && text.endsWith("}"))) {
      try { value = JSON.parse(text); } catch (_) { value = text; }
    }
    if (typeof value === "string") {
      return value.split(/\s*(?:→|->|\n+)\s*/).filter(Boolean).map((item, index) => normalizeTraceStep(item, index));
    }
  }
  if (Array.isArray(value)) return value.map((item, index) => normalizeTraceStep(item, index));
  if (value && typeof value === "object") {
    const nested = value.steps || value.nodes || value.events || value.trace || value.timeline;
    if (Array.isArray(nested)) return nested.map((item, index) => normalizeTraceStep(item, index));
    if (nested && typeof nested === "object") {
      return Object.entries(nested).map(([key, item], index) => normalizeTraceStep(item, index, key));
    }
    const looksLikeStep = value.name || value.title || value.node || value.status || value.message;
    if (looksLikeStep) return [normalizeTraceStep(value, 0)];
    return Object.entries(value).map(([key, item], index) => normalizeTraceStep(item, index, key));
  }
  return [];
}

function formatTraceDuration(milliseconds) {
  if (milliseconds === null || milliseconds === undefined) return "—";
  return milliseconds < 1000 ? `${Math.round(milliseconds)}ms` : `${(milliseconds / 1000).toFixed(2)}s`;
}

function renderDecisionTheater(trace, payload = {}) {
  const steps = normalizeTrace(trace);
  if (!steps.length) return "";
  const totalDuration = steps.reduce((sum, step) => sum + Number(step.durationMs || 0), 0);
  // evidence_count 是每个节点执行到当前的快照，不能把各节点重复累加。
  // 优先使用后端本次运行汇总，兼容旧轨迹时取节点最大值。
  const reportedEvidence = payload.metrics && payload.metrics.evidence_count;
  const summaryEvidence = payload.trace_summary && payload.trace_summary.evidence_count;
  const evidenceTotal = Number.isFinite(Number(reportedEvidence))
    ? Number(reportedEvidence)
    : (Number.isFinite(Number(summaryEvidence))
      ? Number(summaryEvidence)
      : Math.max(0, ...steps.map((step) => Number(step.evidenceCount || 0))));
  const fallbackCount = steps.filter((step) => step.status === "fallback" || step.status === "blocked").length;
  const runId = payload.run_id || payload.trace_id || payload.request_id || "";
  const statusIcon = { success: "✓", running: "↻", warning: "!", fallback: "↘", blocked: "×" };
  return `<details class="decision-theater" open>
    <summary>
      <div><span class="theater-kicker">DECISION RUN THEATER</span><b>决策运行剧场</b><small>结构化业务轨迹 · 不展示模型隐式推理</small></div>
      <span class="theater-toggle">展开 / 收起</span>
    </summary>
    <div class="theater-dashboard">
      <div class="theater-metrics">
        <span><small>执行节点</small><b>${steps.length}</b></span>
        <span><small>证据命中</small><b>${evidenceTotal || (payload.citations || []).length || 0}</b></span>
        <span><small>兜底 / 阻断</small><b>${fallbackCount}</b></span>
        <span><small>节点耗时</small><b>${totalDuration ? formatTraceDuration(totalDuration) : "实时"}</b></span>
        ${runId ? `<button type="button" class="theater-run-id" data-copy-run="${escapeHtml(runId)}" title="复制运行 ID">RUN ${escapeHtml(String(runId).slice(0, 10))}</button>` : ""}
      </div>
      <ol class="theater-track">
        ${steps.map((step, index) => `<li class="theater-node status-${step.status}">
          <div class="theater-rail"><span>${statusIcon[step.status] || "·"}</span><i></i></div>
          <article>
            <header><small>NODE ${String(index + 1).padStart(2, "0")}</small><b>${escapeHtml(step.title)}</b><em>${escapeHtml(({ success: "完成", running: "运行中", warning: "待复核", fallback: "已兜底", blocked: "已阻断" })[step.status] || step.status)}</em></header>
            <p>${escapeHtml(step.detail)}</p>
            <footer>
              ${step.durationMs !== null ? `<span>◷ ${formatTraceDuration(step.durationMs)}</span>` : ""}
              ${step.evidenceCount ? `<span>◈ ${step.evidenceCount} 条证据</span>` : ""}
              ${step.version ? `<span>◇ ${escapeHtml(step.version)}</span>` : ""}
              ${step.fallback ? `<span class="node-fallback">兜底：${escapeHtml(step.fallback)}</span>` : ""}
            </footer>
          </article>
        </li>`).join("")}
      </ol>
    </div>
  </details>`;
}

function bindDecisionTheater(root) {
  $$("[data-copy-run]", root).forEach((button) => button.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(button.dataset.copyRun); toast("运行 ID 已复制"); }
    catch (_) { toast(`运行 ID：${button.dataset.copyRun}`); }
  }));
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

  const startTime = performance.now();

  let url = `/api/agent/ask?question=${encodeURIComponent(q)}&top_k=4`;
  if (uid) url += `&user_id=${encodeURIComponent(uid)}`;
  if (cid) url += `&competition_id=${encodeURIComponent(cid)}`;
  const mdlEl = document.getElementById("agent-model");
  const mdl = mdlEl && mdlEl.value ? mdlEl.value : "";
  if (mdl) url += `&model=${encodeURIComponent(mdl)}`;

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

  const citeList = Array.isArray(data.citations) ? data.citations : [];

  const intentTag = `<span class="intent-tag">${INTENT_LABEL[data.intent] || data.intent} · ${escapeHtml(data.resolved_name || "自动识别赛事")}</span>`;

  const traceHtml = renderDecisionTheater(data.trace, data);
  const agentTaskHtml = (uid && data.resolved_competition)
    ? `<div class="agent-action-strip"><span>把建议落到执行闭环</span><button type="button" class="btn primary agent-create-task" data-cid="${escapeHtml(data.resolved_competition)}" data-cite="${citeList[0] ? escapeHtml(citeList[0].citation_id || "") : ""}">一键转为我的任务</button></div>`
    : "";
  // 联网信息补充（与官方 [n] 引用区隔，明确标注仅供参考）
  const webResults = data.web_results || [];
  const webHtml = webResults.length
    ? `<div class="web-results">
        <div class="web-results-head">🌐 联网信息补充<span>仅供参考，请以官方 / 官网最新通知为准</span></div>
        <ul class="web-list">
          ${webResults.slice(0, 5).map((r) => `
            <li class="web-item">
              <a href="${escapeHtml(r.url || "#")}" target="_blank" rel="noopener" class="web-title">${escapeHtml(r.title || "相关网页")} ↗</a>
              ${r.snippet ? `<div class="web-snippet">${escapeHtml(r.snippet)}</div>` : ""}
              <div class="web-url muted">${escapeHtml(r.url || "")}</div>
            </li>`).join("")}
        </ul>
      </div>`
    : "";
  // 暂存本轮队友数据，供「邀 TA 组队」按钮取用
  currentTeammates = data.teammate_matches || [];
  const teammateHtml = (currentTeammates.length)
    ? `<div class="teammate-cards">
        <div class="teammate-cards-head">🤝 为你匹配的互补队友</div>
        ${currentTeammates.map((m, idx) => `
          <div class="teammate-card">
            <div class="tm-avatar">${escapeHtml(m.avatar || "🙂")}</div>
            <div class="tm-main">
              <div class="tm-name">${escapeHtml(m.display_name || m.user_id)} <span class="tm-score">互补度 ${Math.round(m.match_score)}</span></div>
              <div class="tm-sub">${escapeHtml(m.major)} · ${escapeHtml(m.grade)} · 每周 ${m.weekly_available_hours}h</div>
              ${m.persona ? `<div class="tm-persona">${escapeHtml(m.persona)}</div>` : ""}
              <div class="tm-skills">${(m.skills || []).map((s) => `<span class="tm-tag">${escapeHtml(s)}</span>`).join("")}</div>
              <ul class="tm-reasons">${(m.reasons || []).map((r) => `<li>${escapeHtml(r)}</li>`).join("")}</ul>
              <div class="tm-actions"><button type="button" class="tm-invite" data-idx="${idx}">🤝 邀 TA 组队</button></div>
            </div>
          </div>`).join("")}
      </div>`
    : "";
  const elapsed = ((performance.now() - startTime) / 1000).toFixed(2);
  const rawAnswer = cleanAgentAnswer(data.answer);
  const answerHtml = renderAnswerWithCites(rawAnswer);
  const isLong = rawAnswer.length > 400;
  const bodyClass = isLong ? "agent-answer-body is-collapsed" : "agent-answer-body";
  const expandBtn = isLong ? '<button type="button" class="agent-expand-btn" aria-expanded="false">显示更多 <span class="chevron" aria-hidden="true">▼</span></button>' : "";

  aRow.innerHTML = `<div class="agent-answer-mark" aria-hidden="true">CI</div>
  <div class="msg-a">
    <div class="agent-answer-head"><strong>校园科创智能体</strong>${intentTag}</div>
    <div class="${bodyClass}">${answerHtml}</div>
    ${expandBtn}
    ${webHtml}
    ${teammateHtml}
    ${agentTaskHtml}
    ${traceHtml}
    <div class="agent-meta"><span>处理耗时 ${elapsed}s</span><span>${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span></div>
  </div>`;

  bindDecisionTheater(aRow);
  const agentTaskButton = $(".agent-create-task", aRow);
  if (agentTaskButton) agentTaskButton.addEventListener("click", async () => {
    try {
      await apiPost(`/api/users/${encodeURIComponent(uid)}/tasks/from-agent`, {
        competition_id: agentTaskButton.dataset.cid,
        title: `执行建议：${(rawAnswer || "核对赛事信息").slice(0, 150)}`,
        source_citation_id: agentTaskButton.dataset.cite ? Number(agentTaskButton.dataset.cite) : null,
      });
      toast("已加入我的项目执行清单");
      agentTaskButton.disabled = true;
      agentTaskButton.textContent = "已转入任务";
    } catch (error) { toast(`转任务失败：${error.message}`); }
  });
  // 展开/收起长回答
  const expandBtnEl = aRow.querySelector(".agent-expand-btn");
  if (expandBtnEl) {
    expandBtnEl.addEventListener("click", () => {
      const body = aRow.querySelector(".agent-answer-body");
      const collapsed = body.classList.toggle("is-collapsed");
      body.classList.toggle("is-expanded", !collapsed);
      expandBtnEl.setAttribute("aria-expanded", String(!collapsed));
      expandBtnEl.innerHTML = collapsed
        ? '显示更多 <span class="chevron" aria-hidden="true">▼</span>'
        : '收起 <span class="chevron" aria-hidden="true">▲</span>';
    });
  }

  // 队友卡片「邀 TA 组队」
  aRow.querySelectorAll(".tm-invite").forEach((btn) => {
    btn.addEventListener("click", () => openInviteModal(Number(btn.dataset.idx)));
  });

  log.scrollTop = log.scrollHeight;
  sendBtn.disabled = false;
  sendBtn.classList.remove("is-loading");
  sendBtn.textContent = "↑";
  qEl.focus();
}

$("#agent-send").addEventListener("click", agentAsk);
$("#agent-q").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); agentAsk(); } });
// 模型选择器：启动时从 localStorage 恢复，变更即记忆
(function initModelSelect() {
  const mdl = document.getElementById("agent-model");
  if (!mdl) return;
  const saved = localStorage.getItem("agent_model");
  if (saved) mdl.value = saved;
  mdl.addEventListener("change", () => {
    localStorage.setItem("agent_model", mdl.value);
    refreshLlmStatus();
  });
  refreshLlmStatus();
})();

// 主题色选择器：启动时从 localStorage 恢复，点击即时切换
(function initThemePicker() {
  const view = document.getElementById("view-agent");
  const picker = document.querySelector(".agent-theme-picker");
  if (!view || !picker) return;
  const saved = localStorage.getItem("agent_theme");
  if (saved) view.dataset.theme = saved;
  picker.querySelectorAll("button").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.theme === view.dataset.theme);
    btn.addEventListener("click", () => {
      view.dataset.theme = btn.dataset.theme;
      localStorage.setItem("agent_theme", btn.dataset.theme);
      picker.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b === btn));
    });
  });
})();

// 读取后端 LLM 启用状态，更新输入框顶部状态点（解决"看不出是否接入模型"）
async function refreshLlmStatus() {
  const el = document.getElementById("agent-llm-status");
  const webEl = document.getElementById("agent-web-status");
  if (!el) return;
  const txt = el.querySelector(".agent-llm-text");
  try {
    const r = await apiGet("/api/agent/llm-status");
    const on = !!r.enabled;
    el.dataset.on = on ? "1" : "0";
    const mdl = (document.getElementById("agent-model") || {}).value || "";
    txt.textContent = on
      ? `智能润色已连接 · ${mdl || r.model || "LLM"}`
      : "未启用智能润色（标准答复）";
    // 联网搜索状态
    if (webEl) {
      const won = !!r.web_search_enabled;
      webEl.dataset.on = won ? "1" : "0";
      webEl.classList.toggle("web-off", !won);
      webEl.querySelector(".agent-llm-text").textContent = won
        ? `联网搜索已开启 · ${r.web_search_provider || "web"}`
        : "联网搜索关闭（纯本地）";
    }
  } catch (e) {
    el.dataset.on = "0";
    txt.textContent = "智能润色状态未知";
    if (webEl) {
      webEl.dataset.on = "0";
      webEl.querySelector(".agent-llm-text").textContent = "联网搜索状态未知";
    }
  }
}
$("#agent-q").addEventListener("input", (e) => {
  e.currentTarget.style.height = "auto";
  e.currentTarget.style.height = `${Math.min(e.currentTarget.scrollHeight, 160)}px`;
});
// 引导气泡：填入问题并直接发送（提升功能发现性 + 演示顺滑度）
function bindQuickChip(el) {
  el.addEventListener("click", () => {
    const q = el.dataset.q || "";
    if (!q) return;
    $("#agent-q").value = q;
    agentAsk();
  });
}
$$("#agent-chips .chip").forEach(bindQuickChip);
$$("#agent-quick .quick-chip").forEach(bindQuickChip);

// ---------------------------------------------------------------------------
// 队友卡片「邀 TA 组队」：基于双方画像 + 互补点生成可编辑邀请文案
// ---------------------------------------------------------------------------
let currentTeammates = [];   // 本轮 agent 返回的队友数据，供按钮取用

// 纯前端生成个性化邀约文案（稳定、离线可用、不依赖 LLM）
function buildInviteText(seeker, mate) {
  const hasMe = !!(seeker && (seeker.display_name || seeker.major));
  const meName = (seeker && seeker.display_name)
    || (seeker && seeker.major ? seeker.major + "专业的同学" : "");
  const meMajor = (seeker && seeker.major) || "";
  const meSkills = (seeker && seeker.skills && seeker.skills.length)
    ? `我${meMajor ? "（" + meMajor + "专业）" : ""}擅长 ${seeker.skills.slice(0, 3).join("、")}`
    : "";
  const mateName = mate.display_name || mate.user_id;
  const mateSkills = (mate.skills && mate.skills.length) ? mate.skills.slice(0, 3).join("、") : "";
  // 取互补理由里最具说服力的 1-2 条
  const comps = (mate.reasons || []).filter((r) => /互补|跨学科|搭配/.test(r)).slice(0, 2);
  const compText = comps.length
    ? comps.join("；") + "。"
    : ((mate.reasons && mate.reasons[0]) || "咱们的背景很互补");
  const head = hasMe ? `你好 ${mateName}！我是${meName}。` : `你好 ${mateName}！`;
  const mid = meSkills
    ? `${meSkills}，看到你是${mate.major}·${mate.grade}方向，擅长 ${mateSkills}。`
    : `看到你是${mate.major}·${mate.grade}方向，擅长 ${mateSkills}。`;
  return [
    head,
    mid,
    `咱们的匹配度有 ${Math.round(mate.match_score)} 分——${compText}`,
    `想邀请你一起组队参赛，方便的话加个联系方式聊聊？`,
  ].join("\n");
}

function openInviteModal(idx) {
  const mate = currentTeammates[idx];
  if (!mate) return;
  const ta = $("#invite-text");
  if (ta) ta.value = buildInviteText(state.profile, mate);
  const modal = $("#invite-modal");
  if (modal) modal.classList.remove("hidden");
}
function closeInviteModal() {
  const modal = $("#invite-modal");
  if (modal) modal.classList.add("hidden");
}
// 事件绑定（模态 + 卡片按钮在渲染后绑定）
(function bindInviteModal() {
  const close = $("#invite-close");
  if (close) close.addEventListener("click", closeInviteModal);
  const copy = $("#invite-copy");
  if (copy) copy.addEventListener("click", async () => {
    const ta = $("#invite-text");
    if (!ta) return;
    const txt = ta.value || "";
    try {
      await navigator.clipboard.writeText(txt);
      toast("邀请文案已复制");
    } catch (e) {
      ta.select();
      try { document.execCommand("copy"); toast("邀请文案已复制"); }
      catch (_) { toast("复制失败，请手动选择文本"); }
    }
  });
})();

// ---------------------------------------------------------------------------
// 数据维护闭环（上传 → 解析 → 引用关联 → 确认入库）
// ---------------------------------------------------------------------------
let admFileId = null;
let admDocName = null;
let admDocumentId = null;
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

// 解析奖项比例文本：支持 "奖项 比例" 或 "奖项:比例"，多行/逗号/空格分隔
function parseAwardDistribution(s) {
  if (!s || !s.trim()) return [];
  const out = [];
  for (const line of s.split(/\n|[,，]/)) {
    const t = line.trim();
    if (!t) continue;
    const m = t.match(/^(.+?)[:：\s]+(.+)$/);
    if (m) {
      out.push({ award: m[1].trim(), proportion: m[2].trim() });
    } else {
      const parts = t.split(/\s+/);
      if (parts.length >= 2) {
        out.push({ award: parts.slice(0, -1).join(" "), proportion: parts[parts.length - 1] });
      } else {
        out.push({ award: t, proportion: "" });
      }
    }
  }
  return out;
}

function setAdminStep(step) {
  $$(".pipeline-steps span").forEach((el, index) => {
    el.classList.toggle("active", index + 1 === step);
    el.classList.toggle("complete", index + 1 < step || step > 3);
  });
}

function renderAdminView() {
  admFileId = null; admDocName = null; admDocumentId = null; admBlocks = []; admEvidence = [];
  $("#adm-parse-msg").textContent = "";
  $("#adm-step2").classList.add("hidden");
  $("#adm-step3").classList.add("hidden");
  $("#adm-blocks").innerHTML = "";
  $("#adm-save-msg").textContent = "";
  $("#adm-token").value = sessionStorage.getItem("cia_admin_token") || "";
  renderAdminEvidence();
  setAdminStep(1);
}

function adminHeaders() {
  const token = ($("#adm-token").value || "").trim();
  if (token) sessionStorage.setItem("cia_admin_token", token);
  return token ? { "X-Admin-Token": token } : {};
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
    up = await apiPost("/api/admin/upload", { filename: file.name, content_base64: b64 }, adminHeaders());
  } catch (e) {
    $("#adm-parse-msg").textContent = "上传失败：" + e.message;
    return;
  }
  admFileId = up.file_id; admDocName = up.filename;
  admDocumentId = up.document_id || null;
  const payload = {
    file_id: up.file_id,
    document_id: up.document_id,
    category: $("#adm-cat").value,
    document_year: Number($("#adm-year").value),
  };
  let data;
  try {
    data = await apiPost("/api/admin/parse", payload, adminHeaders());
  } catch (e) {
    $("#adm-parse-msg").textContent = "解析失败：" + e.message;
    return;
  }
  admBlocks = data.blocks || [];
  admDocumentId = data.document_id || admDocumentId;
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
    <option value="team_min">团队最少人数</option>
    <option value="team_max">团队最多人数</option>
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
    competition_start_date: $("#adm-comp-start").value || null,
    competition_end_date: $("#adm-comp-end").value || null,
    result_announcement_date: $("#adm-result").value || null,
    award_settings: $("#adm-award-settings").value.trim() || null,
    award_distribution: parseAwardDistribution($("#adm-award-distribution").value),
    brief_description: $("#adm-brief").value.trim() || null,
    required_materials: csv($("#adm-materials").value),
    evaluation_dimensions: [],
    required_skills: csv($("#adm-skills").value),
    official_source_url: urlVal || null,
    source_acquired_date: todayStr(),
    evidence: admEvidence,
    doc_version: `${$("#adm-year").value || 2026}_v1`,
  };
  $("#adm-save-msg").textContent = "入库中…";
  setAdminStep(3);
  try {
    const d = await apiPost("/api/admin/competitions", comp, adminHeaders());
    $("#adm-save-msg").textContent = `✓ 已入库 ${d.competition_id}（证据 ${d.evidence_count} 条，RAG ${d.rag_chunks} 块）`;
    $("#adm-save-msg").className = "msg ok";
    setAdminStep(4);
    toast("入库成功，已刷新检索库");
  } catch (err) {
    $("#adm-save-msg").textContent = "入库失败：" + err.message;
    $("#adm-save-msg").className = "msg";
  }
});

// ---------------------------------------------------------------------------
// 登录 / 注册（真密码）+ 测试账号学生类型切换 + 管理员门禁
// ---------------------------------------------------------------------------
function openLogin() {
  $("#login-overlay").classList.remove("hidden");
}
function closeLogin() {
  $("#login-overlay").classList.add("hidden");
}

// 管理员「数据维护」入口可见性：仅管理员令牌验证通过后显示
function revealAdminNav() {
  const nav = document.getElementById("nav-admin");
  if (!nav) return;
  nav.classList.toggle("hidden", !state.isAdmin);
}

async function doLogin(username, password) {
  const requestedHash = location.hash;
  let data;
  try {
    data = await apiPost("/api/auth/login", { username, password });
  } catch (e) {
    const msg = $("#login-msg");
    msg.textContent = "登录失败：" + e.message;
    msg.className = "msg err";
    return;
  }
  state.uid = data.username;
  sessionStorage.setItem("cia_access_token", data.access_token || "");
  state.loggedIn = true;
  state.isTest = !!data.is_test;
  state.profile = null;
  state.userMeta = {
    display_name: data.display_name || data.username,
    persona: data.persona || "",
    avatar: data.avatar || monogram(data.display_name || data.username),
  };
  localStorage.setItem("cia_uid", data.username);
  localStorage.setItem("cia_logged", "1");
  localStorage.setItem("cia_is_test", state.isTest ? "1" : "0");
  localStorage.setItem("cia_user_meta", JSON.stringify(state.userMeta));
  revealAdminNav();
  closeLogin();
  updateUserChip();
  toast(`已登录：${state.userMeta.display_name}`);

  // 拉取画像决定 consent 与落地页
  let hasProfile = false;
  try {
    const p = await apiGet(`/api/users/${encodeURIComponent(data.username)}/profile`);
    hasProfile = true;
    state.profile = p;
    state.consent = !!p.privacy_consent;
  } catch (_) {
    state.consent = localStorage.getItem("cia_consent_" + data.username) === "1";
  }
  if (state.consent) localStorage.setItem("cia_consent_" + data.username, "1");
  if (hasProfile && state.consent) location.hash = "#/recommend";
  else location.hash = "#/profile";
  router();
}

async function doRegister(username, password, displayName) {
  try {
    await apiPost("/api/auth/register", { username, password, display_name: displayName || null });
  } catch (e) {
    const msg = $("#register-msg");
    msg.textContent = "注册失败：" + e.message;
    msg.className = "msg err";
    return;
  }
  toast("注册成功，正在登录…");
  await doLogin(username, password);
}

// —— 登录 / 注册表单 ——
$$(".login-tab").forEach((btn) => btn.addEventListener("click", () => {
  const tab = btn.dataset.tab;
  $$(".login-tab").forEach((b) => b.classList.toggle("active", b === btn));
  $("#login-form").classList.toggle("hidden", tab !== "login");
  $("#register-form").classList.toggle("hidden", tab !== "register");
}));
$("#login-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const u = ($("#login-username").value || "").trim();
  const pw = $("#login-password").value || "";
  const msg = $("#login-msg");
  if (!u || !pw) { msg.textContent = "请输入用户名和密码"; msg.className = "msg err"; return; }
  msg.textContent = ""; msg.className = "msg";
  doLogin(u, pw);
});

// 仅本地开发：后端开关启用时返回临时管理员令牌。部署构建不设置开关，按钮会提示不可用。
$("#dev-admin-login").addEventListener("click", async () => {
  const msg = $("#login-msg");
  msg.textContent = "正在进入本地管理员调试模式…";
  msg.className = "msg";
  try {
    const data = await apiPost("/api/auth/dev-admin-login", {});
    await doLogin(data.username, "test123");
    state.isAdmin = true;
    localStorage.setItem("cia_is_admin", "1");
    sessionStorage.setItem("cia_admin_token", data.admin_token);
    revealAdminNav();
    toast("本地管理员调试模式已开启");
    location.hash = "#/admin";
  } catch (error) {
    msg.textContent = "本地管理员入口未启用：" + error.message;
    msg.className = "msg err";
  }
});
$("#register-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const u = ($("#reg-username").value || "").trim();
  const pw = $("#reg-password").value || "";
  const name = ($("#reg-name").value || "").trim();
  const msg = $("#register-msg");
  if (!u || !pw) { msg.textContent = "请输入用户名和密码"; msg.className = "msg err"; return; }
  msg.textContent = ""; msg.className = "msg";
  doRegister(u, pw, name);
});

// —— 管理员入口：输入令牌验证后开放「数据维护」 ——
$("#admin-entry-btn").addEventListener("click", async () => {
  const token = window.prompt("请输入管理员令牌：");
  if (!token) return;
  try {
    await apiPost("/api/admin/verify", { token });
    state.isAdmin = true;
    localStorage.setItem("cia_is_admin", "1");
    sessionStorage.setItem("cia_admin_token", token);
    revealAdminNav();
    toast("管理员已验证，已开放「数据维护」");
    location.hash = "#/admin";
  } catch (e) {
    toast("令牌无效：" + e.message);
  }
});

// —— 测试账号：切换学生类型（独立面板）——
async function renderTestPanel() {
  const panel = $("#test-switch-panel");
  if (!panel) return;
  if (!state.isTest) { panel.classList.add("hidden"); return; }
  panel.classList.remove("hidden");

  let currentKey = "";
  try {
    const p = await apiGet(`/api/users/${encodeURIComponent(state.uid)}/profile`);
    currentKey = (p.major || "") + "|" + (p.grade || "");
  } catch (_) {}

  let types;
  try {
    types = await apiGet("/api/student-types");
  } catch (e) {
    $("#test-types").innerHTML = `<div class="muted">加载学生类型失败</div>`;
    return;
  }
  $("#test-types").innerHTML = types.map((t) => {
    const skills = (t.skills || []).slice(0, 4).map((s) => `<span class="uc-skill">${escapeHtml(s)}</span>`).join("");
    const team = t.expected_team_size > 1 ? `${t.expected_team_size}人队` : "个人赛";
    const active = ((t.major || "") + "|" + (t.grade || "")) === currentKey ? " active" : "";
    return `<button type="button" class="user-card test-type-card${active}" data-uid="${escapeHtml(t.user_id)}">
      <div class="uc-top">
        <span class="uc-avatar">${escapeHtml(t.avatar || "🙂")}</span>
        <div class="uc-idwrap">
          <div class="uc-name">${escapeHtml(t.display_name || t.user_id)}</div>
          <div class="uc-persona">${escapeHtml(t.persona || "")}</div>
        </div>
      </div>
      <div class="uc-meta">
        <span class="uc-tag">${escapeHtml(t.education_level)}·${escapeHtml(t.grade)}</span>
        <span class="uc-tag">${escapeHtml(t.major)}</span>
        <span class="uc-tag">${escapeHtml(team)}</span>
      </div>
      <div class="uc-skills">${skills || '<span class="muted">暂无技能</span>'}</div>
    </button>`;
  }).join("");

  $$("#test-types .test-type-card").forEach((el) => {
    el.addEventListener("click", () => applyStudentType(el.dataset.uid));
  });
}

async function applyStudentType(uid) {
  let t;
  try {
    const all = await apiGet("/api/student-types");
    t = all.find((x) => x.user_id === uid);
  } catch (e) { toast("加载学生类型失败"); return; }
  if (!t) return;
  const payload = {
    user_id: state.uid,
    education_level: t.education_level,
    grade: t.grade,
    major: t.major,
    skills: t.skills || [],
    experiences: t.experiences || [],
    weekly_available_hours: t.weekly_available_hours,
    expected_team_size: t.expected_team_size,
    privacy_consent: true,
    display_name: "测试·" + (t.display_name || uid),
    persona: t.persona,
    avatar: t.avatar,
  };
  try {
    await apiPost(`/api/users/${encodeURIComponent(state.uid)}/profile`, payload);
    state.consent = true;
    localStorage.setItem("cia_consent_" + state.uid, "1");
    state.profile = payload;
    updateUserChip();
    toast("已切换为：" + (t.display_name || uid));
    const h = location.hash;
    if (h === "#/profile" || h === "#/recommend") router();
    else location.hash = "#/recommend";
  } catch (e) {
    toast("切换失败：" + e.message);
  }
}

function logout() {
  localStorage.removeItem("cia_uid");
  localStorage.removeItem("cia_logged");
  localStorage.removeItem("cia_user_meta");
  localStorage.removeItem("cia_is_test");
  localStorage.removeItem("cia_is_admin");
  sessionStorage.removeItem("cia_admin_token");
  sessionStorage.removeItem("cia_access_token");
  state.uid = null;
  state.loggedIn = false;
  state.userMeta = null;
  state.consent = false;
  state.isTest = false;
  state.isAdmin = false;
  state.profile = null;
  revealAdminNav();
  updateUserChip();
  openLogin();
}

$("#switch-user-btn").addEventListener("click", logout);

// ---------------------------------------------------------------------------
// 启动
// ---------------------------------------------------------------------------
window.addEventListener("hashchange", router);
window.addEventListener("DOMContentLoaded", () => {
  updateUserChip();
  revealAdminNav();
  if (!state.loggedIn || !state.uid) {
    openLogin();
    return; // 未登录不进入主应用
  }
  router();
});
