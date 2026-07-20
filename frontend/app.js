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
async function apiPost(path, body, extraHeaders = {}) {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...extraHeaders },
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
  currentEvidence: [], // 引用证据索引（供弹窗 / 角标定位）
  detailReturn: "#/hall", // 详情页返回目标视图（默认大厅；从推荐进入时为 #/recommend）
  hallReadiness: "all",
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
// 引用证据弹窗
// ---------------------------------------------------------------------------
// 引用证据索引已并入 state（见上方 state 容器）

function openCiteModal(i) {
  const e = state.currentEvidence[i];
  if (!e) return;
  const page = e.page === null || e.page === undefined ? "未定位" : `第 ${e.page} 页`;
  $("#cite-body").innerHTML = `
    <div class="kv"><span class="k">佐证字段</span><span class="v">${escapeHtml(e.field)}</span></div>
    <div class="kv"><span class="k">文档</span><span class="v">${escapeHtml(e.document_name || "—")}</span></div>
    <div class="kv"><span class="k">页码</span><span class="v">${page}</span></div>
    <div class="kv"><span class="k">获取日期</span><span class="v">${escapeHtml(e.acquired_date || "—")}</span></div>
    <div class="kv"><span class="k">官方链接</span><span class="v">${
      e.source_url ? `<a href="${escapeHtml(e.source_url)}" target="_blank" rel="noopener">${escapeHtml(e.source_url)}</a>` : "—"
    }</span></div>
    <div class="section"><h3>原文片段</h3>
      <p style="background:#f8fafc;border-left:3px solid var(--fact);padding:10px;border-radius:6px;">${escapeHtml(e.source_text)}</p>
    </div>`;
  $("#cite-modal").classList.remove("hidden");
}

function citeChips(evidence) {
  state.currentEvidence = evidence || [];
  if (!state.currentEvidence.length) return `<span class="muted">（暂无引用证据）</span>`;
  return state.currentEvidence.map((e, i) =>
    `<span class="cite-chip" data-cite="${i}" title="点击查看原文证据">引用 ${i + 1}</span>`
  ).join("");
}

// 依据 field 过滤出对应证据角标
function chipsForField(evidence, field) {
  const list = (evidence || []).filter((e) => e.field === field);
  if (!list.length) return "";
  return " " + list.map((e, i) => {
    const idx = state.currentEvidence.indexOf(e);
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
    backEl.textContent = ret === "#/recommend" ? "← 返回推荐" : "← 返回大厅";
  }
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
  state.currentEvidence = ev;

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
        ${(c.official_source_status === "not_found") ? `<span class="tag src-unverified">未找到官方来源</span>` : (detail.recommendation_ready ? `<span class="tag src-verified">官网来源已确认</span>` : `<span class="tag src-unverified">关键证据待补充</span>`)}
      </div>
      </div>
      <div class="detail-actions">
        ${officialUrl ? `<a class="btn ghost" href="${escapeHtml(officialUrl)}" target="_blank" rel="noopener">访问官网</a>` : ""}
        ${detail.recommendation_ready ? `<button id="join-project" class="btn primary">加入我的项目</button>` : ""}
      </div>
    </div>

    ${!detail.recommendation_ready ? `<div class="verify-warn">
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
      ${kv("参赛对象", (c.eligible_students || []).join("、") || "—", "eligible_students")}
      ${kv("年级要求", grades, "allowed_grades")}
      ${kv("专业要求", majors, "allowed_majors")}
      ${kv("团队规模", teamTxt, "team_max")}
    </div></div>

    <div class="section"><h3>关键时间</h3><div class="card">
      ${keyTimeHtml}
      ${awardHtml}
    </div></div>

    <div class="section"><h3>材料与能力</h3><div class="card">
      ${(c.required_materials && c.required_materials.length) ? kv("所需材料", c.required_materials.join("、"), "required_materials") : ""}
      ${(c.required_skills && c.required_skills.length) ? kv("所需技能", c.required_skills.join("、"), "required_skills") : ""}
      ${(c.evaluation_dimensions && c.evaluation_dimensions.length) ? kv("评价维度", c.evaluation_dimensions.join("、")) : ""}
    </div></div>

    ${ev.length ? `<div class="section"><h3>官方依据</h3><div class="card">
      <details open>
        <summary>共 ${ev.length} 条来源证据<span>点击收起</span></summary>
        <div class="refs-list" style="padding-top:8px;">
          ${ev.map((e) => {
            const lvl = e.trust_level || e.trusted_level || "A";
            const lvlLabel = ({ A: "官网证据 A", B: "部分证据 B", C: "待核验 C" })[lvl] || lvl;
            const src = (e.document_name || "") + (e.page ? " 第" + e.page + "页" : "");
            return `<div class="ref">
              <span class="lvl ${lvl}">${lvlLabel}</span>
              <strong>${escapeHtml(e.field || "官方规则")}</strong>
              <div>${escapeHtml((e.source_text || "").slice(0, 180))}</div>
              <div class="muted">${escapeHtml(src)}${e.source_url ? ` · <a href="${escapeHtml(e.source_url)}" target="_blank" rel="noopener">官方链接 ↗</a>` : ""}</div>
            </div>`;
          }).join("")}
        </div>
      </details>
    </div></div>` : ""}
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
  // 追加到全局证据数组，复用弹窗
  const base = state.currentEvidence.length;
  hits.forEach((h) => state.currentEvidence.push(h));
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
    ? `共 ${recs.length} 项正式推荐；候选信息请前往赛事大厅查看。`
    : "当前没有同时通过官网来源、关键证据、资格与报名时间门控的赛事。";

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
      ${p.recommendation_ready ? "" : `<div class="project-trust-warning">来源状态已变化：${escapeHtml((p.readiness_reasons || []).join("；"))}。项目数据已保留，请重新核对官网。</div>`}
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
  const base = state.currentEvidence.length;
  ev.forEach((e) => state.currentEvidence.push(e));
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

// 将答案渲染为带 [n] 角标 + 轻量 Markdown（**加粗**）的结构化文本
function renderAnswerWithCites(text) {
  let html = escapeHtml(text || "");
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\[(\d+)\]/g, (m, n) => `<sup class="cite" data-cite="${Number(n) - 1}">[${n}]</sup>`);
  return html;
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

  // 引用：追加到全局证据数组，供弹窗复用
  const base = state.currentEvidence.length;
  (data.citations || []).forEach((c) => state.currentEvidence.push(c));

  const intentTag = `<span class="intent-tag">${INTENT_LABEL[data.intent] || data.intent} · ${escapeHtml(data.resolved_name || "自动识别赛事")}</span>`;

  const citeList = data.citations || [];
  const refsHtml = citeList.length
    ? `<div class="refs"><details open>
        <summary>官方依据 · ${citeList.length} 条<span>点击收起</span></summary>
        <div class="refs-list">
          ${citeList.map((c, i) => {
            const lvl = c.trust_level || c.trusted_level || "A";
            const lvlLabel = ({ A: "可信 A", B: "待核 B", C: "存疑 C" })[lvl] || lvl;
            const src = (c.document_name || "") + (c.page ? " 第" + c.page + "页" : "");
            const excerpt = (c.source_text || c.snippet || "").slice(0, 180);
            return `<div class="ref" id="ref-${i}">
              <span class="lvl ${lvl}">${lvlLabel}</span>
              <strong>${escapeHtml(c.field || "官方规则")}</strong>
              <div>${escapeHtml(excerpt)}</div>
              <div class="muted">${escapeHtml(src)}${c.source_url ? ` · <a href="${escapeHtml(c.source_url)}" target="_blank" rel="noopener">官方链接 ↗</a>` : ""}</div>
            </div>`;
          }).join("")}
        </div>
      </details></div>`
    : "";
  const traceHtml = "";
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
    ${refsHtml}
    ${teammateHtml}
    ${traceHtml}
    <div class="agent-meta"><span>处理耗时 ${elapsed}s</span><span>${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span></div>
  </div>`;

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

  // 角标点击：定位并高亮对应官方依据
  $$(".cite", aRow).forEach((el) => {
    el.addEventListener("click", () => {
      const det = aRow.querySelector(".refs details");
      if (det && !det.open) det.open = true;
      const ref = aRow.querySelector("#ref-" + el.dataset.cite);
      if (ref) {
        ref.scrollIntoView({ behavior: "smooth", block: "center" });
        const old = ref.style.background;
        ref.style.background = "#fff6da";
        setTimeout(() => { ref.style.background = old; }, 900);
      }
    });
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
  } catch (e) {
    el.dataset.on = "0";
    txt.textContent = "智能润色状态未知";
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
  admFileId = null; admDocName = null; admBlocks = []; admEvidence = [];
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
  const payload = {
    file_id: up.file_id,
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
