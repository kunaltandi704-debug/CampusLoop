const state = { user: null, csrf: "", tokenValuePaise: 10, page: "home", chat: [], chatPending: false, activityQuery: "", activityCategory: "", activityView: "list", calendarOffset: 0, activityEditing: null, adminActivities: [], adminWeekStart: null, isRegister: false };
const $ = (selector, root = document) => root.querySelector(selector);
const appRoot = $("#app");

function esc(value = "") {
  return String(value).replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
}
function toast(message, isError = false) {
  const node = $("#toast");
  node.textContent = message;
  node.className = `toast show${isError ? " error" : ""}`;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => node.className = "toast", 3200);
}
async function api(url, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (state.csrf && options.method && options.method !== "GET") headers["X-CSRF-Token"] = state.csrf;
  if (options.body && !(options.body instanceof FormData)) headers["Content-Type"] = "application/json";
  const response = await fetch(url, { credentials: "same-origin", ...options, headers });
  const result = response.status === 204 ? {} : await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.error || `Request failed (${response.status}).`);
  return result;
}
const money = value => `₹${Number(value || 0).toFixed(2)}`;
const tokenValue = tokens => money(Number(tokens || 0) * state.tokenValuePaise / 100);
const dateShort = value => {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
};
const dateTime = value => {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
};
const statusClass = status => String(status).toLowerCase().replace(/\s+/g, "-");
const navItems = [
  ["home", "⌂", "Overview"],
  ["rewards", "✦", "Rewards & menu"],
  ["orders", "▤", "My orders"],
  ["attendance", "✓", "Attendance"],
  ["activities", "◷", "Activities"],
  ["contribute", "✎", "Create & earn"],
  ["assistant", "✧", "Gemma assistant"],
];
function pageTitle(page) { return ({ home: "Your campus, in the loop", rewards: "Canteen rewards", orders: "My orders", attendance: "My attendance", teacher: "Teacher attendance", "attendance-admin": "Attendance management", activities: "Campus activities", contribute: "Create for campus", assistant: "Ask Gemma 4", admin: "Campus operations" })[page] || "CampusLoop"; }
function shell() {
  const first = esc((state.user.name || "Student").split(/\s+/)[0]);
  const sidebar = (mobile = false) => `<nav class="${mobile ? "mobile-nav" : "nav-list"}" aria-label="${mobile ? "Mobile" : "Main"} navigation">${navItems.map(([id, icon, label]) => `<button class="nav-btn ${state.page === id ? "active" : ""}" data-page="${id}"><span class="nav-icon">${icon}</span><span>${label}</span></button>`).join("")}${state.user.is_teacher ? `<button class="nav-btn ${state.page === "teacher" ? "active" : ""}" data-page="teacher"><span class="nav-icon">▣</span><span>Teacher desk</span></button>` : ""}${state.user.role === "admin" ? `<button class="nav-btn ${state.page === "admin" ? "active" : ""}" data-page="admin"><span class="nav-icon">⚙</span><span>Admin studio</span></button><button class="nav-btn ${state.page === "attendance-admin" ? "active" : ""}" data-page="attendance-admin"><span class="nav-icon">✓</span><span>Attendance admin</span></button>` : ""}</nav>`;
  appRoot.innerHTML = `<div class="layout">
    <aside class="sidebar"><div class="brand"><span class="brand-mark">C</span><span>CampusLoop<small>Campus, connected</small></span></div>
      <div><p class="nav-label">Workspace</p>${sidebar()}</div>
      <div class="sidebar-bottom"><div class="sample-note">🌱 <strong>Demo mode</strong><br>Sample activities are clearly labeled and not verified college events.</div>
        <div class="profile-chip"><span class="avatar">${first.charAt(0)}</span><span class="profile-text">${first}<small>${esc(state.user.role === "admin" ? "Campus admin" : state.user.email)}</small></span><button class="logout" data-action="logout" title="Log out" aria-label="Log out">↗</button></div></div>
    </aside>
    <main class="main"><header class="topbar"><div><p class="eyebrow">CampusLoop / ${state.user.role === "admin" && ["admin", "attendance-admin"].includes(state.page) ? "Admin" : "Student"}</p><h1>${pageTitle(state.page)}</h1></div><div class="top-actions"><span class="date-pill">◷ &nbsp;${new Date().toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })}</span><button class="btn ghost small header-logout" data-action="logout">↗ <span>Log out</span></button></div></header><section id="page-content"><div class="empty"><span class="spinner"></span><p>Loading your campus...</p></div></section></main>
    ${sidebar(true)}
  </div>`;
  loadPage();
}
function authView() {
  appRoot.innerHTML = `<div class="auth-wrap"><section class="auth-side"><div class="brand"><span class="brand-mark">C</span><span>CampusLoop</span></div><div><p class="eyebrow" style="color:#d7f067">Earn. Create. Belong.</p><h1>Your everyday campus life, rewarded.</h1><p>One loop for campus events, creative contributions, canteen treats, and the community that connects them.</p></div><small>CampusLoop · Gemma 4 powered</small></section>
    <section class="auth-content"><div class="auth-card"><p class="eyebrow">${state.isRegister ? "Join the community" : "Welcome back"}</p><h2>${state.isRegister ? "Create your student account" : "Sign in to your campus"}</h2><form id="auth-form" class="form-grid">${state.isRegister ? `<div class="field"><label for="name">Full name</label><input id="name" name="name" autocomplete="name" required maxlength="80"></div>` : ""}<div class="field"><label for="email">Email address</label><input id="email" name="email" type="email" autocomplete="email" required></div><div class="field"><label for="password">Password</label><input id="password" name="password" type="password" minlength="8" autocomplete="${state.isRegister ? "new-password" : "current-password"}" required></div><button class="btn" type="submit">${state.isRegister ? "Create account" : "Sign in"} <span>→</span></button></form><p class="muted" style="margin-top:17px">${state.isRegister ? "Already have an account?" : "New to CampusLoop?"} <button class="link-btn" data-action="toggle-auth">${state.isRegister ? "Sign in" : "Register"}</button></p><div class="demo-box"><strong>Demo accounts</strong><br>Student: student@campusloop.demo &nbsp; / &nbsp; CampusLoop123!<br>Admin: admin@campusloop.demo &nbsp; / &nbsp; CampusLoop123!<br><small>Change demo passwords before any real deployment.</small></div></div></section></div>`;
}
async function loadPage() {
  const container = $("#page-content");
  if (!container) return;
  try {
    if (state.page === "home") await renderHome(container);
    else if (state.page === "rewards") await renderRewards(container);
    else if (state.page === "orders") await renderOrders(container);
    else if (state.page === "attendance") await renderAttendance(container);
    else if (state.page === "teacher") await renderTeacherDesk(container);
    else if (state.page === "attendance-admin") await renderAttendanceAdmin(container);
    else if (state.page === "activities") await renderActivities(container);
    else if (state.page === "contribute") await renderContributions(container);
    else if (state.page === "assistant") renderAssistant(container);
    else if (state.page === "admin") await renderAdmin(container);
  } catch (error) {
    container.innerHTML = `<div class="panel empty"><div class="empty-icon">!</div><strong>We couldn't load this page.</strong><p>${esc(error.message)}</p><button class="btn soft" data-action="reload">Try again</button></div>`;
  }
}
async function renderHome(root) {
  const [dash, rewards, activities] = await Promise.all([api("/api/dashboard"), api("/api/rewards"), api("/api/activities")]);
  const active = activities.filter(item => item.state === "Ongoing");
  const upcoming = activities.filter(item => item.state === "Upcoming");
  const recent = dash.recent_activity;
  const attendance = dash.attendance;
  const attendanceSummary = `<section class="panel attendance-card"><div class="attendance-summary"><div><p class="eyebrow">Weekly attendance · ${esc(attendance.timezone)}</p><h2>${attendance.percentage.toFixed(2)}%</h2><p class="muted">${attendance.sessions_attended} of ${attendance.sessions_held} finalized class sessions attended · week of ${dateShort(attendance.week_start)}</p></div><div class="attendance-tier"><span class="status ${attendance.eligible_for_processing ? "ready" : "pending"}">${attendance.eligible_for_processing ? `${attendance.eligible_reward_tokens} tokens eligible` : `Preview: ${attendance.tier_preview_tokens} tokens`}</span><small>${attendance.eligible_for_processing ? "Completed week and all sessions finalized" : `No payment before the week closes and sessions are finalized`}</small></div></div><div class="row"><small class="muted">${attendance.next_threshold ? `Next threshold: ${attendance.next_threshold}%` : "Top attendance tier reached"}</small><button class="link-btn" data-page="attendance">View attendance history →</button></div></section>`;
  root.innerHTML = `<div class="hero panel"><p class="eyebrow">Your next campus moment</p><h2>Small actions. Good things in the loop.</h2><p>Show up, share your creativity, and turn campus participation into canteen treats.</p><button class="btn light" data-page="activities">Explore activities <span>→</span></button></div>
  <div class="grid stats"><article class="stat-card"><div class="stat-head">Available tokens <span class="stat-coin">✦</span></div><div class="stat-value">${dash.user.balance.toLocaleString()}</div><div class="stat-note">Your balance is verified from the token ledger</div></article><article class="stat-card"><div class="stat-head">Reward value <span class="stat-coin">₹</span></div><div class="stat-value">${tokenValue(dash.user.balance)}</div><div class="stat-note">Base rate: 100 tokens = ₹10 reward value</div></article><article class="stat-card"><div class="stat-head">Campus moments <span class="stat-coin">◷</span></div><div class="stat-value">${active.length + upcoming.length}</div><div class="stat-note">${active.length} ongoing · ${upcoming.length} upcoming</div></article></div>
  ${attendanceSummary}
  <div class="grid content-grid"><div class="grid"><section class="panel"><div class="section-head"><h2>Good things to redeem</h2><button class="link-btn" data-page="rewards">Browse all →</button></div><div class="grid reward-grid">${rewardCards(rewards.slice(0, 4), dash.user.balance)}</div></section>
  <section class="panel"><div class="section-head"><h2>Campus activity</h2><button class="link-btn" data-page="activities">See calendar →</button></div>${activityList(activities.slice(0, 3))}</section></div>
  <section class="panel"><div class="section-head"><h2>Recent activity</h2><button class="link-btn" data-action="ledger">View ledger</button></div>${recent.length ? `<div class="list">${recent.map(tx => `<div class="row"><span><strong>${esc(tx.reason)}</strong><small class="muted" style="display:block">${dateTime(tx.created_at)}</small></span><strong style="color:${tx.entry_type === "credit" ? "var(--green)" : "var(--red)"}">${tx.entry_type === "credit" ? "+" : "−"}${tx.amount} tokens · ${tokenValue(tx.amount)}</strong></div>`).join("")}</div>` : empty("Your token activity will appear here.")}</section></div>`;
}
function rewardCards(rewards, balance) {
  const icons = ["🥤", "☕", "🥪", "🍋", "🥣", "🍪"];
  if (!rewards.length) return empty("No rewards are available right now.");
  return rewards.map((reward, index) => `<article class="reward-card"><div class="reward-art">${icons[index % icons.length]}</div><h3>${esc(reward.name)}</h3><p>${esc(reward.description || "Canteen reward")}</p><div class="reward-foot"><span class="price">✦ ${reward.token_price} tokens <small class="muted">· ${tokenValue(reward.token_price)}</small></span><button class="btn small ${balance < reward.token_price ? "ghost" : ""}" data-action="redeem" data-id="${reward.id}" ${balance < reward.token_price ? "disabled" : ""}>${balance < reward.token_price ? "Need more" : "Redeem"}</button></div></article>`).join("");
}
async function renderRewards(root) {
  const [rewards, menu, dash] = await Promise.all([api("/api/rewards"), api("/api/menu"), api("/api/dashboard")]);
  root.innerHTML = `<p class="muted">Browse available rewards or build a canteen order. Every redemption and order uses your verified token balance.</p><section class="panel" style="margin:18px 0"><div class="section-head"><div><p class="eyebrow">Reward catalogue</p><h2 style="margin:0">Treat yourself</h2></div><span class="tag">✦ ${dash.user.balance} tokens · ${tokenValue(dash.user.balance)}</span></div><div class="grid reward-grid">${rewardCards(rewards, dash.user.balance)}</div></section>
  <section class="panel"><div class="section-head"><div><p class="eyebrow">Canteen menu</p><h2 style="margin:0">Build an order</h2></div><span class="muted">Select quantities · pay with tokens</span></div><form id="order-form"><div class="table-wrap"><table><thead><tr><th>Menu item</th><th>Price</th><th>Quantity</th></tr></thead><tbody>${menu.map(item => `<tr><td><strong>${esc(item.name)}</strong><div class="muted">${esc(item.description)}</div></td><td class="price">✦ ${item.token_price} tokens<br><small class="muted">${tokenValue(item.token_price)}</small></td><td><input type="number" min="0" max="20" value="0" aria-label="${esc(item.name)} quantity" data-menu-qty="${item.id}" style="width:72px;border:1px solid var(--line);border-radius:8px;padding:8px"></td></tr>`).join("")}</tbody></table></div><div class="row" style="margin-top:15px"><span class="muted">Order is charged atomically when placed. Pending orders can be cancelled for a full refund.</span><button class="btn" type="submit">Place order →</button></div></form></section>`;
}
async function renderOrders(root) {
  const orders = await api("/api/orders");
  root.innerHTML = `<p class="muted">Order history shown here comes directly from your account records. Pending orders can be cancelled for a full refund.</p><section class="panel" style="margin-top:18px"><div class="section-head"><h2>Order history</h2><button class="btn soft small" data-page="rewards">Order from canteen</button></div>${orders.length ? `<div class="list">${orders.map(order => `<article class="activity-card"><div class="activity-date"><b>✦</b><span>${dateShort(order.created_at)}</span></div><div class="activity-body"><div class="row"><strong>Order ${esc(order.id.slice(0, 8).toUpperCase())}</strong><span class="status ${statusClass(order.status)}">${esc(order.status)}</span></div><p class="order-items">${order.items.map(item => `${item.quantity}× ${esc(item.item_name)} · ${item.unit_token_price} tokens (${tokenValue(item.unit_token_price)})`).join("<br>")}</p><div class="row"><small class="muted">${dateTime(order.created_at)}</small><span class="price">−${order.token_cost} tokens · ${tokenValue(order.token_cost)}</span>${order.status === "Pending" ? `<button class="btn danger small" data-action="cancel-order" data-id="${esc(order.id)}">Cancel & refund</button>` : ""}</div></div></article>`).join("")}</div>` : empty("Your orders will show up here after checkout.")}</section>`;
}
async function renderAttendance(root) {
  const data = await api("/api/attendance/me");
  const week = data.current_week;
  root.innerHTML = `<p class="muted">Attendance uses teacher-recorded class sessions and the configured college timezone (${esc(data.timezone)}). Bonuses are issued only after the week is complete and every session is finalized.</p>
  <div class="grid stats"><article class="stat-card"><div class="stat-head">Current week <span class="stat-coin">✓</span></div><div class="stat-value">${week.percentage.toFixed(2)}%</div><div class="stat-note">${week.sessions_attended} attended / ${week.sessions_held} held · ${week.week_start}</div></article><article class="stat-card"><div class="stat-head">Tier preview <span class="stat-coin">✦</span></div><div class="stat-value">${week.tier_preview_tokens} tokens</div><div class="stat-note">${tokenValue(week.tier_preview_tokens)} reward value · not payable until finalized</div></article><article class="stat-card"><div class="stat-head">Eligibility <span class="stat-coin">◷</span></div><div class="stat-value" style="font-size:18px">${week.eligible_for_processing ? "Ready to process" : "Not yet complete"}</div><div class="stat-note">${week.next_threshold ? `Next tier threshold: ${week.next_threshold}%` : "Highest tier threshold reached"}</div></article></div>
  <section class="panel" style="margin-bottom:18px"><div class="section-head"><h2>Weekly reward history</h2><span class="tag">100 tokens = ₹10</span></div>${data.history.length ? `<div class="table-wrap"><table><thead><tr><th>Week starting</th><th>Attendance</th><th>Sessions</th><th>Original award</th><th>After audited adjustments</th></tr></thead><tbody>${data.history.map(item => `<tr><td>${esc(item.week_start)}</td><td>${Number(item.attendance_percentage).toFixed(2)}%</td><td>${item.sessions_attended}/${item.sessions_held}</td><td>${item.reward_tokens} tokens · ${tokenValue(item.reward_tokens)}</td><td><strong>${item.current_reward_tokens} tokens · ${tokenValue(item.current_reward_tokens)}</strong></td></tr>`).join("")}</tbody></table></div>` : empty("No completed weekly attendance rewards yet.")}</section>
  <section class="panel"><div class="section-head"><h2>Class-wise attendance</h2><span class="tag">${data.timezone}</span></div>${data.class_records.length ? `<div class="table-wrap"><table><thead><tr><th>Course / section</th><th>Subject</th><th>Class</th><th>Session</th><th>Status</th><th>Record finalized</th></tr></thead><tbody>${data.class_records.map(record => `<tr><td>${esc(record.course_name)} / ${esc(record.section_name)}</td><td>${esc(record.subject_name)}</td><td>${esc(record.class_name)}</td><td>${dateTime(record.starts_at)}</td><td><span class="status ${record.status === "Present" ? "ready" : "rejected"}">${esc(record.status)}</span></td><td>${record.finalized ? "Yes" : "No"}</td></tr>`).join("")}</tbody></table></div>` : empty("Class records will appear after you are enrolled and attendance is recorded.")}</section>`;
}
async function renderTeacherDesk(root) {
  const sessions = await api("/api/teacher/sessions");
  root.innerHTML = `<p class="muted">Only classes assigned by an admin are shown. Record attendance once per student and session; finalization requires every enrolled student to be marked. Corrected entries always retain an audit record.</p>${sessions.length ? `<div class="list">${sessions.map(item => `<section class="panel"><div class="section-head"><div><p class="eyebrow">${esc(item.course_name)} · ${esc(item.section_name)} · ${esc(item.subject_name)}</p><h2>${esc(item.class_name)}</h2><small class="muted">${dateTime(item.starts_at)} – ${dateTime(item.ends_at)} · ${item.finalized ? "Finalized" : "Open"}</small></div><span class="status ${item.finalized ? "ready" : "pending"}">${item.finalized ? "Finalized" : "Attendance open"}</span></div>${item.students.length ? `<form class="teacher-attendance-form" data-session="${item.session_id}"><div class="table-wrap"><table><thead><tr><th>Student</th><th>Entry / correction</th></tr></thead><tbody>${item.students.map(student => `<tr><td>${esc(student.name)}</td><td>${student.attendance_id ? `<span class="status ${student.status === "Present" ? "ready" : "rejected"}">${esc(student.status)}</span> <span class="correction-fields"><select name="status" data-correction-status="${student.attendance_id}"><option ${student.status === "Present" ? "selected" : ""}>Present</option><option ${student.status === "Absent" ? "selected" : ""}>Absent</option></select><input name="reason" data-correction-reason="${student.attendance_id}" placeholder="Reason for correction"><button type="button" class="btn ghost small" data-action="correct-attendance" data-id="${student.attendance_id}">Correct</button></span>` : `<label class="attendance-mark"><span class="sr-only">${esc(student.name)} status</span><select name="status-${student.student_id}" data-attendance-student="${student.student_id}" ${item.finalized ? "disabled" : ""}><option>Present</option><option>Absent</option></select></label>`}</td></tr>`).join("")}</tbody></table></div>${!item.finalized ? `<div class="form-actions"><button class="btn">Save unrecorded attendance</button><button type="button" class="btn soft" data-action="finalize-attendance" data-id="${item.session_id}">Finalize session</button></div>` : ""}</form>` : empty("No students are enrolled in this class section.")}</section>`).join("")}</div>` : `<section class="panel">${empty("No assigned attendance sessions are available.")}</section>`}`;
}
async function renderAttendanceAdmin(root) {
  const overview = await api("/api/admin/overview");
  const weekQuery = state.adminWeekStart ? `?week_start=${encodeURIComponent(state.adminWeekStart)}` : "";
  const report = await api(`/api/admin/attendance${weekQuery}`);
  state.adminWeekStart = report.week_start;
  const sections = [...new Map(overview.attendance_classes.map(item => [item.section_id, item])).values()];
  const classOptions = overview.attendance_classes.map(item => `<option value="${item.id}">${esc(item.course_name)} / ${esc(item.section_name)} · ${esc(item.subject_name)}</option>`).join("");
  const studentOptions = overview.attendance_students.map(item => `<option value="${item.id}">${esc(item.name)} · ${esc(item.email)}</option>`).join("");
  const sectionOptions = sections.map(item => `<option value="${item.section_id}">${esc(item.course_name)} / ${esc(item.section_name)}</option>`).join("");
  root.innerHTML = `<p class="muted">Create classes and sessions, enroll students, assign teacher accounts, review completion and issue one highest qualifying tier for each completed week. Timezone: <strong>${esc(report.timezone)}</strong>; reward week runs Monday 00:00 to next Monday 00:00 local time.</p>
  <div class="grid content-grid"><section class="panel"><div class="section-head"><h2>Class setup</h2></div><form id="attendance-class-form" class="form-grid"><div class="field"><label>Course</label><input name="course" required placeholder="B.Tech Computer Science"></div><div class="field"><label>Section</label><input name="section" required placeholder="Section A"></div><div class="field"><label>Subject</label><input name="subject" required placeholder="Data Structures"></div><div class="field"><label>Class label</label><input name="class_name" required placeholder="DS - Section A"></div><button class="btn">Create / update class</button></form>
  <form id="attendance-enroll-form" class="form-grid" style="margin-top:20px"><div class="field"><label>Section</label><select name="section_id" required>${sectionOptions}</select></div><div class="field"><label>Student</label><select name="student_id" required>${studentOptions}</select></div><button class="btn soft">Enroll student</button></form></section>
  <section class="panel"><div class="section-head"><h2>Teacher & session setup</h2></div><p class="muted">Assign an existing student account as a teacher for a class. This enables attendance tools only for assigned classes.</p><form id="attendance-teacher-form" class="form-grid"><div class="field"><label>Class</label><select name="class_id" required>${classOptions}</select></div><div class="field"><label>Teacher account</label><select name="teacher_id" required>${studentOptions}</select></div><button class="btn soft">Assign teacher</button></form><form id="attendance-session-form" class="form-grid" style="margin-top:20px"><div class="field full"><label>Class</label><select name="class_id" required>${classOptions}</select></div><div class="field"><label>Starts (${esc(report.timezone)})</label><input type="datetime-local" name="starts_at" required></div><div class="field"><label>Ends (${esc(report.timezone)})</label><input type="datetime-local" name="ends_at" required></div><button class="btn">Schedule class session</button></form></section></div>
  <section class="panel" style="margin-top:18px"><div class="section-head"><div><p class="eyebrow">Weekly reward processing</p><h2 style="margin:0">Eligibility review</h2></div><span class="tag">${report.week_complete ? "Week complete" : "Current week is still open"}</span></div><form id="attendance-week-form" class="toolbar"><label class="field">Monday week start (college local)<input type="date" name="week_start" value="${esc(report.week_start)}" required></label><button class="btn ghost" type="submit">Load eligibility</button><button class="btn" type="button" data-action="process-attendance-week" ${report.week_complete ? "" : "disabled"}>Issue eligible weekly rewards</button></form><p class="muted">Tiers: 70–79.99% = 200 tokens (${tokenValue(200)}); 80–89.99% = 300 tokens (${tokenValue(300)}); 90–100% = 500 tokens (${tokenValue(500)}). Below 70% = 0. Every student's sessions must be finalized.</p>${report.students.length ? `<div class="table-wrap"><table><thead><tr><th>Student</th><th>Attendance</th><th>Sessions</th><th>Tier preview</th><th>State</th><th>Issued / adjusted</th><th>Adjustment</th></tr></thead><tbody>${report.students.map(student => `<tr><td>${esc(student.student_name)}<small class="muted" style="display:block">${esc(student.student_email)}</small></td><td>${student.percentage.toFixed(2)}%</td><td>${student.sessions_attended}/${student.sessions_held}</td><td>${student.tier_preview_tokens} tokens · ${tokenValue(student.tier_preview_tokens)}</td><td><span class="status ${student.status === "Eligible" ? "ready" : student.status === "Incomplete" ? "pending" : ""}">${esc(student.status)}</span></td><td>${student.current_reward_tokens === null ? "—" : `${student.current_reward_tokens} tokens · ${tokenValue(student.current_reward_tokens)}`}</td><td>${student.issued_reward_tokens !== null ? `<form class="attendance-adjust-form" data-student="${student.student_id}" data-week="${esc(report.week_start)}"><input name="reason" placeholder="Authorized reason" required><button class="btn ghost small">Adjust</button></form>` : "—"}</td></tr>`).join("")}</tbody></table></div>` : empty("Enroll students and record class sessions to review attendance.")}</section>
  <section class="panel" style="margin-top:18px"><div class="section-head"><h2>Correction audit</h2><span class="tag">${overview.attendance_corrections.length} recent</span></div>${overview.attendance_corrections.length ? `<div class="table-wrap"><table><thead><tr><th>Student / class</th><th>Change</th><th>Reason</th><th>By</th><th>Time</th></tr></thead><tbody>${overview.attendance_corrections.map(item => `<tr><td>${esc(item.student_name)} / ${esc(item.class_name)}</td><td>${esc(item.previous_status)} → ${esc(item.corrected_status)}</td><td>${esc(item.reason)}</td><td>${esc(item.corrected_by)}</td><td>${dateTime(item.corrected_at)}</td></tr>`).join("")}</tbody></table></div>` : empty("Authorized attendance corrections will appear here.")}</section>`;
}
function activityList(items) {
  if (!items.length) return empty("No upcoming or ongoing activities match yet.");
  return `<div class="list">${items.map(item => `<article class="activity-card"><div class="activity-date"><b>${new Date(item.start_at).toLocaleDateString(undefined, { day: "2-digit" })}</b><span>${new Date(item.start_at).toLocaleDateString(undefined, { month: "short" })}</span></div><div class="activity-body"><div class="row"><h3>${esc(item.title)}</h3><span class="status">${esc(item.state)}</span></div><p>${esc(item.description)}</p><div class="row"><small class="muted">${esc(item.category)} · ${esc(item.venue)} · ${dateTime(item.start_at)}</small>${item.reward_tokens ? `<span class="price">+${item.reward_tokens} tokens · ${tokenValue(item.reward_tokens)}</span>` : ""}</div>${item.is_sample ? `<p class="sample-note" style="margin:8px 0 0">Demo sample · not a verified college event</p>` : ""}<div style="margin-top:9px">${item.participation_status ? `<span class="status ${statusClass(item.participation_status)}">Participation: ${esc(item.participation_status)}</span>` : `<button class="btn soft small" data-action="participate" data-id="${item.id}">Request participation review</button>`}</div></div></article>`).join("")}</div>`;
}
async function renderActivities(root) {
  const query = encodeURIComponent(state.activityQuery);
  const category = encodeURIComponent(state.activityCategory);
  const activities = await api(`/api/activities?q=${query}&category=${category}`);
  root.innerHTML = `<p class="muted">Explore approved opportunities to participate, learn, volunteer, and create. Demo samples are labeled, not presented as verified events.</p><section class="panel" style="margin-top:18px"><div class="toolbar"><input id="activity-search" class="search-input" value="${esc(state.activityQuery)}" placeholder="Search activities, venue, organizer…"><select id="activity-category" class="search-input" style="max-width:190px"><option value="">All categories</option>${["Workshop", "Competition", "College Fest", "Volunteering", "Other"].map(cat => `<option ${state.activityCategory === cat ? "selected" : ""}>${cat}</option>`).join("")}</select><button class="btn soft" data-action="filter-activities">Search</button><button class="btn ghost" data-action="toggle-calendar">${state.activityView === "list" ? "▦ Month view" : "☷ List view"}</button></div>${state.activityView === "list" ? activityList(activities) : calendarView(activities)}</section>`;
}
function calendarView(activities) {
  const month = new Date();
  month.setDate(1);
  month.setMonth(month.getMonth() + state.calendarOffset);
  const year = month.getFullYear(), monthIndex = month.getMonth(), count = new Date(year, monthIndex + 1, 0).getDate();
  const firstDay = new Date(year, monthIndex, 1).getDay();
  const events = activities.filter(item => {
    const date = new Date(item.start_at);
    return date.getFullYear() === year && date.getMonth() === monthIndex;
  });
  const cells = Array.from({ length: firstDay }, () => `<div class="calendar-cell blank"></div>`);
  for (let day = 1; day <= count; day++) {
    const matches = events.filter(item => new Date(item.start_at).getDate() === day);
    cells.push(`<div class="calendar-cell"><strong>${day}</strong>${matches.map(item => `<span class="calendar-event" title="${esc(item.title)}">${esc(item.title)}</span>`).join("")}</div>`);
  }
  return `<div class="calendar-toolbar"><button class="btn ghost small" data-action="month-shift" data-delta="-1">←</button><strong>${month.toLocaleDateString(undefined, { month: "long", year: "numeric" })}</strong><button class="btn ghost small" data-action="month-shift" data-delta="1">→</button></div><div class="calendar-grid">${["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map(day => `<div class="calendar-weekday">${day}</div>`).join("")}${cells.join("")}</div><div style="margin-top:20px">${activityList(events)}</div>`;
}
async function renderContributions(root) {
  const submissions = await api("/api/submissions");
  root.innerHTML = `<div class="split"><section class="panel"><p class="eyebrow">Share your creativity</p><h2>Make something for campus</h2><p class="muted">Submit original artwork for college events or canteen promotions. Admins review each contribution; tokens are awarded once after approval.</p><form id="submission-form" class="form-grid" enctype="multipart/form-data"><div class="field full"><label for="contrib-title">Artwork title</label><input id="contrib-title" name="title" required maxlength="100" placeholder="e.g. Fest night, under the stars"></div><div class="field"><label for="contrib-category">Category</label><select id="contrib-category" name="category"><option>Event Poster</option><option>Canteen Promotion</option><option>Banner</option></select></div><div class="field"><label for="contrib-image">Artwork file (PNG, JPG, WebP · max 5 MB)</label><input id="contrib-image" name="image" type="file" accept=".png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp" required></div><div class="field full"><label for="contrib-description">Description</label><textarea id="contrib-description" name="description" required maxlength="1000" placeholder="Tell us what inspired it and where it could be used."></textarea></div><div class="field full"><button class="btn" type="submit">Submit for review →</button></div></form></section>
  <section class="panel"><div class="section-head"><h2>My submissions</h2><span class="tag">${submissions.length} total</span></div>${submissions.length ? `<div class="list">${submissions.map(item => `<article class="activity-card"><img src="${esc(item.image_url)}" alt="${esc(item.title)}" style="width:70px;height:70px;object-fit:cover;border-radius:11px"><div class="activity-body"><div class="row"><strong>${esc(item.title)}</strong><span class="status ${statusClass(item.status)}">${esc(item.status)}</span></div><p>${esc(item.category)} · ${dateShort(item.created_at)}</p>${item.status === "Approved" ? `<span class="price">+${item.reward_tokens} tokens earned · ${tokenValue(item.reward_tokens)}</span>` : ""}</div></article>`).join("")}</div>` : empty("Your submitted artwork and review status will appear here.")}</section></div>`;
}
function renderAssistant(root) {
  root.innerHTML = `<section class="panel chat-shell"><div class="chat-head"><span class="gemma-mark">G4</span><div><h3 style="margin:0">CampusLoop assistant</h3><small class="muted">Powered by Gemma 4 · ${"gemma-4-26b-a4b-it"}</small></div><span class="status" style="margin-left:auto">Verified app data</span></div><div class="chat-messages" id="chat-messages" aria-live="polite" aria-label="Conversation"></div><div class="toolbar" id="chat-prompts">${["What rewards can I afford?", "How do weekly attendance bonuses work?", "What's coming up on campus?", "Where is my latest order?"].map(prompt => `<button class="btn ghost small" data-action="ask-prompt" data-message="${esc(prompt)}">${esc(prompt)}</button>`).join("")}</div><form id="chat-form" class="chat-input"><textarea id="chat-message" maxlength="1000" placeholder="Ask about your campus… (Enter to send, Shift+Enter for a new line)" autocomplete="off" rows="1" required aria-label="Your message"></textarea><button class="btn" type="submit" aria-label="Send message">Send ↗</button></form></section><p class="muted" style="margin-top:11px">Gemma sees only relevant verified information for your question. No fallback model is used.</p>`;
  const messages = $("#chat-messages");
  if (state.chat.length) {
    state.chat.forEach(message => appendChatBubble(messages, message.role, message.text, message.error));
    $("#chat-prompts").hidden = true;
  } else {
    appendChatBubble(messages, "assistant", `Hi ${(state.user.name || "there").split(" ")[0]}! Ask me about earning or redeeming tokens, attendance bonus tiers, campus activities, affordable canteen rewards, or your own order status. I only use verified app data and can’t change account records.`);
  }
  if (state.chatPending) appendChatBubble(messages, "assistant", "Gemma 4 is thinking…").classList.add("thinking");
  $("#chat-message").disabled = state.chatPending;
  $("#chat-form button[type='submit']").disabled = state.chatPending;
  scrollChatToLatest(messages);
}
function appendChatBubble(container, role, text, isError = false) {
  const bubble = document.createElement("div");
  bubble.className = `bubble ${role}${isError ? " error" : ""}`;
  bubble.textContent = text;
  container.append(bubble);
  return bubble;
}
function scrollChatToLatest(container) {
  container.scrollTop = container.scrollHeight;
}
async function renderAdmin(root) {
  if (state.user.role !== "admin") throw new Error("Admin access required.");
  const data = await api("/api/admin/overview");
  state.adminActivities = data.activities;
  root.innerHTML = `<p class="muted">Manage catalog prices, canteen service, creative reviews, activity listings, and the configured contribution reward.</p>
  <div class="grid content-grid" style="margin-top:18px"><section class="panel"><div class="section-head"><h2>Order management</h2><span class="tag">${data.orders.length} orders</span></div>${data.orders.length ? `<div class="list">${data.orders.map(order => `<article class="activity-card"><div class="activity-body"><div class="row"><strong>${esc(order.id.slice(0, 8).toUpperCase())} · ${esc(order.status)}</strong><span class="price">${order.token_cost} tokens</span></div><p>${order.items.map(item => `${item.quantity}× ${esc(item.item_name)}`).join(" · ")}<br>${dateTime(order.created_at)}</p><label class="field">Update status<select data-order-status="${esc(order.id)}">${["Pending", "Preparing", "Ready", "Completed", "Cancelled"].map(s => `<option ${s === order.status ? "selected" : ""}>${s}</option>`).join("")}</select></label></div></article>`).join("")}</div>` : empty("No orders yet.")}</section>
  <section class="panel"><div class="section-head"><h2>Contribution rewards</h2></div><p class="muted">Tokens awarded once for each approved submission.</p><form id="contribution-setting-form" class="row"><label class="field" style="max-width:150px">Tokens per approval<input type="number" name="reward_tokens" min="0" max="10000" value="${data.contribution_reward}" required></label><button class="btn" type="submit">Save reward</button></form>
  <div class="section-head" style="margin-top:25px"><h2>Artwork review</h2><span class="tag">${data.submissions.filter(s => s.status === "Pending Review").length} pending</span></div>${data.submissions.length ? `<div class="list">${data.submissions.map(item => `<article class="activity-card"><img src="${esc(item.image_url)}" alt="${esc(item.title)}" style="width:66px;height:66px;object-fit:cover;border-radius:10px"><div class="activity-body"><div class="row"><strong>${esc(item.title)}</strong><span class="status ${statusClass(item.status)}">${esc(item.status)}</span></div><p>${esc(item.student_name)} · ${esc(item.category)} · ${dateShort(item.created_at)}<br>${esc(item.description)}</p>${item.status === "Pending Review" ? `<button class="btn soft small" data-action="review" data-id="${esc(item.id)}" data-status="Approved">Approve (+${data.contribution_reward})</button> <button class="btn danger small" data-action="review" data-id="${esc(item.id)}" data-status="Rejected">Reject</button>` : ""}</div></article>`).join("")}</div>` : empty("No artwork submissions yet.")}</section></div>
  <div class="grid content-grid" style="margin-top:18px"><section class="panel"><div class="section-head"><h2>Reward prices</h2></div><p class="muted">Reward value is derived at the fixed rate: 1 token = ₹0.10.</p><div class="list">${data.rewards.map(reward => `<form class="row admin-reward-form" data-id="${reward.id}"><strong>${esc(reward.name)}</strong><label class="muted">Tokens <input type="number" name="token_price" min="1" value="${reward.token_price}" style="width:75px;padding:7px;border:1px solid var(--line);border-radius:7px"></label><span class="price">${tokenValue(reward.token_price)}</span><button class="btn ghost small">Save</button></form>`).join("")}</div><form id="add-reward-form" class="form-grid" style="margin-top:17px"><div class="field"><label>New reward</label><input name="name" placeholder="Reward name" required></div><div class="field"><label>Description</label><input name="description" placeholder="Short description"></div><div class="field"><label>Token price</label><input name="token_price" type="number" min="1" required></div><div><span class="muted">Rupee value is auto-calculated</span></div><button class="btn">Add reward</button></form></section>
  <section class="panel"><div class="section-head"><h2>Menu prices</h2></div><div class="list">${data.menu.map(item => `<form class="row admin-menu-form" data-id="${item.id}"><strong>${esc(item.name)}</strong><label class="muted">Tokens <input type="number" name="token_price" min="1" value="${item.token_price}" style="width:85px;padding:7px;border:1px solid var(--line);border-radius:7px"></label><button class="btn ghost small">Save</button></form>`).join("")}</div><form id="add-menu-form" class="form-grid" style="margin-top:17px"><div class="field"><label>Menu item</label><input name="name" required></div><div class="field"><label>Description</label><input name="description"></div><div class="field"><label>Token price</label><input name="token_price" type="number" min="1" required></div><button class="btn">Add menu item</button></form></section></div>
  <section class="panel" style="margin-top:18px"><div class="section-head"><h2>Academic calendar</h2><span class="tag">${data.activities.length} activities</span></div><form id="activity-form" data-editing="${state.activityEditing || ""}" class="form-grid"><div class="field"><label>Title</label><input name="title" required></div><div class="field"><label>Category</label><select name="category">${["Workshop", "Competition", "College Fest", "Volunteering", "Other"].map(x => `<option>${x}</option>`).join("")}</select></div><div class="field"><label>Start</label><input name="start_at" type="datetime-local" required></div><div class="field"><label>End</label><input name="end_at" type="datetime-local" required></div><div class="field"><label>Venue</label><input name="venue" required></div><div class="field"><label>Organizer</label><input name="organizer" required></div><div class="field"><label>Optional reward tokens</label><input name="reward_tokens" type="number" min="0" value="0"></div><div class="field"><label>Description</label><input name="description" required></div><div class="field full"><label>Participation instructions</label><textarea name="instructions" required></textarea></div><div class="field full"><button class="btn">${state.activityEditing ? "Save activity changes" : "Add activity"}</button> ${state.activityEditing ? `<button type="button" class="btn ghost" data-action="cancel-activity-edit">Cancel edit</button>` : ""}</div></form><div class="list" style="margin-top:20px">${data.activities.map(item => `<article class="activity-card"><div class="activity-body"><div class="row"><strong>${esc(item.title)} ${item.is_sample ? `<span class="status pending">Demo sample</span>` : ""}</strong><span><button class="btn ghost small" data-action="edit-activity" data-id="${item.id}">Edit</button> <button class="btn danger small" data-action="delete-activity" data-id="${item.id}">Delete</button></span></div><p>${esc(item.category)} · ${dateTime(item.start_at)} · ${esc(item.venue)} · ${item.reward_tokens} tokens</p><small class="muted">${esc(item.instructions)}</small></div></article>`).join("")}</div></section>
  <section class="panel" style="margin-top:18px"><div class="section-head"><h2>Participation review</h2><span class="tag">${data.participations.filter(p => p.status === "Pending Review").length} pending</span></div>${data.participations.length ? `<div class="list">${data.participations.map(item => `<article class="activity-card"><div class="activity-body"><div class="row"><strong>${esc(item.activity_title)} · ${esc(item.student_name)}</strong><span class="status ${statusClass(item.status)}">${esc(item.status)}</span></div><p>${dateTime(item.created_at)} · ${item.reward_tokens} tokens</p>${item.status === "Pending Review" ? `<button class="btn soft small" data-action="review-participation" data-id="${item.id}" data-status="Approved">Approve (+${item.configured_reward || "activity"})</button> <button class="btn danger small" data-action="review-participation" data-id="${item.id}" data-status="Rejected">Reject</button>` : ""}</div></article>`).join("")}</div>` : empty("No participation requests yet.")}</section>`;
}
function empty(text) { return `<div class="empty"><div class="empty-icon">✧</div>${esc(text)}</div>`; }
async function refreshSession() {
  const info = await api("/api/session");
  state.user = info.user;
  state.csrf = info.csrf_token || state.csrf;
  state.tokenValuePaise = info.token_value_paise || 10;
  if (state.user) shell(); else authView();
}
async function runAction(button) {
  const action = button.dataset.action;
  try {
    if (action === "toggle-auth") { state.isRegister = !state.isRegister; authView(); }
    else if (action === "logout") { await api("/api/logout", { method: "POST", body: "{}" }); state.user = null; state.csrf = ""; state.chat = []; await refreshSession(); }
    else if (action === "reload") loadPage();
    else if (action === "finalize-attendance") {
      await api(`/api/teacher/sessions/${button.dataset.id}/finalize`, { method: "POST", body: "{}" });
      toast("Attendance session finalized.");
      loadPage();
    }
    else if (action === "correct-attendance") {
      const id = button.dataset.id;
      const form = button.closest(".correction-fields");
      await api(`/api/teacher/attendance/${id}`, {
        method: "PATCH",
        body: JSON.stringify({
          status: form.querySelector(`[data-correction-status="${id}"]`).value,
          reason: form.querySelector(`[data-correction-reason="${id}"]`).value.trim(),
        }),
      });
      toast("Attendance corrected and audit entry recorded.");
      loadPage();
    }
    else if (action === "process-attendance-week") {
      const week_start = $("#attendance-week-form").elements.week_start.value;
      const result = await api("/api/admin/attendance/process-week", { method: "POST", body: JSON.stringify({ week_start }) });
      toast(`${result.issued.length} weekly reward(s) issued.`);
      loadPage();
    }
    else if (action === "ledger") {
      const entries = await api("/api/ledger");
      const content = entries.length ? entries.map(tx => `${tx.entry_type === "credit" ? "+" : "−"}${tx.amount} tokens (${tx.entry_type === "credit" ? "+" : "−"}${tokenValue(tx.amount)}) · ${tx.reason} · ${dateTime(tx.created_at)}`).join("\n") : "No token transactions yet.";
      window.alert(`Token ledger\n\n${content}`);
    }
    else if (action === "redeem") {
      button.disabled = true;
      await api(`/api/rewards/${button.dataset.id}/redeem`, { method: "POST", body: JSON.stringify({ idempotency_key: crypto.randomUUID() }) });
      toast("Reward redeemed. Your balance is updated.");
      shell();
    }
    else if (action === "cancel-order") {
      if (!window.confirm("Cancel this pending order and refund its tokens?")) return;
      await api(`/api/orders/${button.dataset.id}/cancel`, { method: "POST", body: "{}" });
      toast("Order cancelled and tokens refunded.");
      loadPage();
    }
    else if (action === "filter-activities") {
      state.activityQuery = $("#activity-search").value.trim();
      state.activityCategory = $("#activity-category").value;
      loadPage();
    }
    else if (action === "toggle-calendar") {
      state.activityView = state.activityView === "list" ? "calendar" : "list";
      loadPage();
    }
    else if (action === "month-shift") {
      state.calendarOffset += Number(button.dataset.delta);
      loadPage();
    }
    else if (action === "participate") {
      await api(`/api/activities/${button.dataset.id}/participate`, { method: "POST", body: "{}" });
      toast("Participation sent for admin review.");
      loadPage();
    }
    else if (action === "review-participation") {
      await api(`/api/admin/participations/${button.dataset.id}`, { method: "PATCH", body: JSON.stringify({ status: button.dataset.status }) });
      toast(`Participation ${button.dataset.status.toLowerCase()}.`);
      loadPage();
    }
    else if (action === "edit-activity") {
      const item = state.adminActivities.find(activity => activity.id === Number(button.dataset.id));
      if (!item) throw new Error("Activity not found.");
      state.activityEditing = item.id;
      const form = $("#activity-form");
      const local = value => {
        const date = new Date(value);
        return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
      };
      for (const key of ["title", "category", "venue", "organizer", "description", "instructions", "reward_tokens"]) form.elements[key].value = item[key];
      form.elements.start_at.value = local(item.start_at);
      form.elements.end_at.value = local(item.end_at);
      form.dataset.editing = item.id;
      form.querySelector('button[type="submit"],button:not([type])').textContent = "Save activity changes";
      form.scrollIntoView({ behavior: "smooth", block: "center" });
    }
    else if (action === "cancel-activity-edit") {
      state.activityEditing = null;
      loadPage();
    }
    else if (action === "review") {
      await api(`/api/admin/submissions/${button.dataset.id}`, { method: "PATCH", body: JSON.stringify({ status: button.dataset.status }) });
      toast(`Submission ${button.dataset.status.toLowerCase()}.`);
      loadPage();
    }
    else if (action === "delete-activity") {
      if (!window.confirm("Delete this activity from the calendar?")) return;
      await api(`/api/admin/activities/${button.dataset.id}`, { method: "DELETE" });
      if (state.activityEditing === Number(button.dataset.id)) state.activityEditing = null;
      toast("Activity deleted.");
      loadPage();
    }
    else if (action === "ask-prompt") {
      const input = $("#chat-message");
      if (input) { input.value = button.dataset.message; $("#chat-form").requestSubmit(); }
    }
  } catch (error) { toast(error.message, true); if (state.page === "admin" || state.page === "orders") loadPage(); }
}
document.addEventListener("click", event => {
  const pageButton = event.target.closest("[data-page]");
  if (pageButton) { state.page = pageButton.dataset.page; shell(); return; }
  const actionButton = event.target.closest("[data-action]");
  if (actionButton) runAction(actionButton);
});
document.addEventListener("keydown", event => {
  if (event.target.id === "chat-message" && event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    if (!state.chatPending) event.target.form.requestSubmit();
  }
});
document.addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.target;
  if (form.id === "chat-form" && state.chatPending) return;
  const button = form.querySelector('button[type="submit"],button:not([type])');
  try {
    if (button) button.disabled = true;
    if (form.id === "auth-form") {
      const formData = new FormData(form);
      const path = state.isRegister ? "/api/register" : "/api/login";
      const user = await api(path, { method: "POST", body: JSON.stringify(Object.fromEntries(formData)) });
      state.user = user.user;
      state.csrf = user.csrf_token || state.csrf;
      state.tokenValuePaise = user.token_value_paise || 10;
      state.isRegister = false;
      state.page = "home";
      shell();
    } else if (form.id === "order-form") {
      const items = [...form.querySelectorAll("[data-menu-qty]")].map(input => ({ item_id: Number(input.dataset.menuQty), quantity: Number(input.value) })).filter(item => item.quantity > 0);
      if (!items.length) throw new Error("Choose at least one item.");
      await api("/api/orders", { method: "POST", body: JSON.stringify({ items, idempotency_key: crypto.randomUUID() }) });
      toast("Order placed. Tokens deducted from your wallet.");
      state.page = "orders";
      shell();
    } else if (form.id === "submission-form") {
      const payload = new FormData(form);
      const response = await fetch("/api/submissions", { method: "POST", headers: { "X-CSRF-Token": state.csrf }, body: payload, credentials: "same-origin" });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.error || "Artwork could not be submitted.");
      toast("Artwork submitted for review.");
      loadPage();
    } else if (form.id === "chat-form") {
      const input = $("#chat-message");
      const message = input.value.trim();
      if (!message) return;
      state.chatPending = true;
      state.chat.push({ role: "user", text: message });
      input.value = "";
      const messages = $("#chat-messages");
      appendChatBubble(messages, "user", message);
      const loading = appendChatBubble(messages, "assistant", "Gemma 4 is thinking…");
      loading.classList.add("thinking");
      $("#chat-prompts").hidden = true;
      input.disabled = true;
      button.disabled = true;
      scrollChatToLatest(messages);
      try {
        const answer = await api("/api/assistant", { method: "POST", body: JSON.stringify({ message }) });
        state.chat.push({ role: "assistant", text: answer.answer });
        loading.textContent = answer.answer;
      } catch (error) {
        state.chat.push({ role: "assistant", text: error.message, error: true });
        loading.textContent = error.message;
        loading.classList.add("error");
      } finally {
        state.chatPending = false;
        if (input.isConnected) input.disabled = false;
        if (button.isConnected) button.disabled = false;
      }
      loading.classList.remove("thinking");
      if (loading.isConnected) scrollChatToLatest(messages);
      else if (state.page === "assistant") renderAssistant($("#page-content"));
      return;
    } else if (form.id === "contribution-setting-form") {
      const reward_tokens = Number(new FormData(form).get("reward_tokens"));
      await api("/api/admin/settings/contribution-reward", { method: "PATCH", body: JSON.stringify({ reward_tokens }) });
      toast("Contribution reward updated.");
      loadPage();
    } else if (form.classList.contains("admin-reward-form")) {
      const fields = Object.fromEntries(new FormData(form));
      await api(`/api/admin/rewards/${form.dataset.id}`, { method: "PATCH", body: JSON.stringify({ token_price: Number(fields.token_price) }) });
      toast("Reward price updated.");
    } else if (form.id === "add-reward-form") {
      const fields = Object.fromEntries(new FormData(form));
      await api("/api/admin/rewards", { method: "POST", body: JSON.stringify({ ...fields, token_price: Number(fields.token_price) }) });
      toast("Reward added.");
      loadPage();
    } else if (form.classList.contains("admin-menu-form")) {
      const fields = Object.fromEntries(new FormData(form));
      await api(`/api/admin/menu/${form.dataset.id}`, { method: "PATCH", body: JSON.stringify({ token_price: Number(fields.token_price) }) });
      toast("Menu price updated.");
    } else if (form.id === "add-menu-form") {
      const fields = Object.fromEntries(new FormData(form));
      await api("/api/admin/menu", { method: "POST", body: JSON.stringify({ ...fields, token_price: Number(fields.token_price) }) });
      toast("Menu item added.");
      loadPage();
    } else if (form.id === "activity-form") {
      const fields = Object.fromEntries(new FormData(form));
      fields.start_at = new Date(fields.start_at).toISOString();
      fields.end_at = new Date(fields.end_at).toISOString();
      fields.reward_tokens = Number(fields.reward_tokens);
      const editing = form.dataset.editing;
      await api(editing ? `/api/admin/activities/${editing}` : "/api/admin/activities", { method: editing ? "PUT" : "POST", body: JSON.stringify(fields) });
      state.activityEditing = null;
      toast(editing ? "Activity updated." : "Activity added to the calendar.");
      loadPage();
    } else if (form.id === "attendance-class-form") {
      await api("/api/admin/classes", { method: "POST", body: JSON.stringify(Object.fromEntries(new FormData(form))) });
      toast("Class created or updated.");
      loadPage();
    } else if (form.id === "attendance-enroll-form") {
      const fields = Object.fromEntries(new FormData(form));
      await api("/api/admin/enrollments", { method: "POST", body: JSON.stringify({ section_id: Number(fields.section_id), student_id: Number(fields.student_id) }) });
      toast("Student enrolled.");
      loadPage();
    } else if (form.id === "attendance-teacher-form") {
      const fields = Object.fromEntries(new FormData(form));
      await api("/api/admin/teacher-assignments", { method: "POST", body: JSON.stringify({ class_id: Number(fields.class_id), teacher_id: Number(fields.teacher_id) }) });
      toast("Teacher assigned.");
      loadPage();
    } else if (form.id === "attendance-session-form") {
      const fields = Object.fromEntries(new FormData(form));
      await api("/api/admin/sessions", { method: "POST", body: JSON.stringify({ class_id: Number(fields.class_id), starts_at: fields.starts_at, ends_at: fields.ends_at }) });
      toast("Class session scheduled.");
      loadPage();
    } else if (form.classList.contains("teacher-attendance-form")) {
      const records = [...form.querySelectorAll("[data-attendance-student]")].map(input => ({
        student_id: Number(input.dataset.attendanceStudent),
        status: input.value,
      }));
      if (!records.length) throw new Error("There are no unrecorded students in this session.");
      await api(`/api/teacher/sessions/${form.dataset.session}/attendance`, { method: "POST", body: JSON.stringify({ records }) });
      toast(`${records.length} attendance record(s) saved.`);
      loadPage();
    } else if (form.id === "attendance-week-form") {
      state.adminWeekStart = new FormData(form).get("week_start");
      loadPage();
    } else if (form.classList.contains("attendance-adjust-form")) {
      const reason = new FormData(form).get("reason").trim();
      await api(`/api/admin/attendance/rewards/${form.dataset.student}/${form.dataset.week}/adjust`, {
        method: "POST",
        body: JSON.stringify({ reason, idempotency_key: crypto.randomUUID() }),
      });
      toast("Attendance reward adjustment recorded with an audit trail.");
      loadPage();
    } else return;
  } catch (error) { toast(error.message, true); }
  finally { if (button && document.contains(button)) button.disabled = false; }
});
document.addEventListener("change", async event => {
  const select = event.target.closest("[data-order-status]");
  if (!select) return;
  try {
    await api(`/api/admin/orders/${select.dataset.orderStatus}`, { method: "PATCH", body: JSON.stringify({ status: select.value }) });
    toast("Order status updated.");
    loadPage();
  } catch (error) { toast(error.message, true); loadPage(); }
});
(async function start() {
  try { await refreshSession(); }
  catch (error) { appRoot.innerHTML = `<div class="panel empty">${esc(error.message)} <button class="btn" onclick="location.reload()">Retry</button></div>`; }
})();
