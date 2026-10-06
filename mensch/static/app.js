const state = { user: null, employees: [], notes: [], activeNoteId: null, view: "ask", threadHtml: null };
const $ = (sel) => document.querySelector(sel);

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const initials = (name) => (name || "?").split(" ").map((p) => p[0]).slice(0, 2).join("").toUpperCase();
const hue = (name) => [...(name || "")].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7);
const avatar = (name, size = "") =>
  `<span class="avatar ${size}" style="background:hsl(${hue(name)} 75% 92%);color:hsl(${hue(name)} 45% 32%)">${esc(initials(name))}</span>`;
const firstName = (name) => (name || "").split(" ")[0];
const ago = (iso) => {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return new Date(iso).toLocaleDateString();
};
const ICON = {
  link: '<svg viewBox="0 0 24 24"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>',
  lock: '<svg viewBox="0 0 24 24"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>',
  book: '<svg viewBox="0 0 24 24"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>',
  spark: '<svg viewBox="0 0 24 24"><path d="M12 3l1.9 5.8L20 10l-6.1 1.2L12 17l-1.9-5.8L4 10l6.1-1.2z"/></svg>',
};

// Minimal formatting: paragraphs, numbered/bulleted lists, `code`.
function formatText(text) {
  const inline = (s) => esc(s).replace(/`([^`]+)`/g, "<code>$1</code>");
  const out = [];
  let list = null;
  for (const raw of String(text || "").split("\n")) {
    const line = raw.trim();
    const m = line.match(/^(\d+[.)]|[-*•])\s+(.*)$/);
    if (m) {
      const type = /\d/.test(m[1]) ? "ol" : "ul";
      if (list !== type) { if (list) out.push(`</${list}>`); out.push(`<${type}>`); list = type; }
      out.push(`<li>${inline(m[2])}</li>`);
      continue;
    }
    if (list) { out.push(`</${list}>`); list = null; }
    if (line) out.push(`<p>${inline(line)}</p>`);
  }
  if (list) out.push(`</${list}>`);
  return out.join("");
}

async function api(path, { method = "GET", body } = {}) {
  const res = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json", ...(state.user ? { "X-User-Id": state.user } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch {}
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return res.status === 204 ? null : res.json();
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.add("hidden"), 3000);
}

const employeeById = (id) => state.employees.find((e) => e.id === id);

// ---------- navigation ----------
function show(view) {
  state.view = view;
  document.querySelectorAll("nav button").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("hidden", v.id !== `view-${view}`));
  ({ ask: loadQuestions, inbox: loadInbox, notes: loadNotes, experts: loadMap, memory: loadMemory, profile: loadProfile })[view]();
}
document.querySelectorAll("nav button").forEach((b) => b.addEventListener("click", () => show(b.dataset.view)));

// ---------- users ----------
async function loadUsers() {
  state.employees = await api("/api/employees");
  const saved = Number(localStorage.getItem("mensch-user"));
  state.user = state.employees.some((e) => e.id === saved) ? saved : state.employees[0]?.id;
  $("#user-select").innerHTML = state.employees
    .map((e) => `<option value="${e.id}" ${e.id === state.user ? "selected" : ""}>${esc(e.name)} · ${esc(e.title)}</option>`)
    .join("");
  renderMe();
}
function renderMe() {
  const me = employeeById(state.user);
  if (!me) return;
  $("#me-avatar").outerHTML = `<span id="me-avatar">${avatar(me.name)}</span>`;
  $("#me-name").textContent = me.name;
  $("#me-title").textContent = me.title;
}
$("#user-select").addEventListener("change", (e) => {
  state.user = Number(e.target.value);
  localStorage.setItem("mensch-user", state.user);
  state.activeNoteId = null;
  state.threadHtml = null;
  renderMe();
  refreshInboxCount();
  show(state.view);
});

// ---------- ask ----------
const SUGGESTIONS = [
  ["Finance", "How do I get my travel expenses reimbursed?"],
  ["Sales", "Who approves a discount above 20%?"],
  ["Legal", "How do I sign an NDA with a new vendor?"],
];
$("#suggestions").innerHTML = SUGGESTIONS
  .map(([tag, q]) => `<button type="button" class="suggestion" data-q="${esc(q)}"><span>${esc(tag)}</span>${esc(q)}</button>`)
  .join("");
$("#suggestions").addEventListener("click", (e) => {
  const b = e.target.closest(".suggestion");
  if (!b) return;
  $("#ask-input").value = b.dataset.q;
  $("#ask-form").requestSubmit();
});
const input = $("#ask-input");
input.addEventListener("input", () => { input.style.height = "auto"; input.style.height = `${input.scrollHeight}px`; });
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#ask-form").requestSubmit(); }
});
$("#ask-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = e.target.querySelector(".send");
  btn.disabled = true;
  try {
    await api("/api/ask", { method: "POST", body: { question: input.value } });
    input.value = "";
    input.style.height = "auto";
    await loadQuestions(true);
  } catch (err) { toast(err.message); }
  btn.disabled = false;
});

function sourceChips(q) {
  return `<div class="source-chips">${q.sources
    .map((s, i) => `<button type="button" class="source-chip" data-src="${q.id}-${i}">${s.person ? avatar(s.person, "sm") : ""}
        ${s.kind === "private_note" ? `${ICON.lock} ${esc(firstName(s.person))}'s notes` : `${ICON.book} ${esc(s.person ? `${firstName(s.person)}'s answer` : "Memory")}`}
      </button>`).join("")}</div>
    ${q.sources.map((s, i) => `<div class="source-detail hidden" id="src-${q.id}-${i}"><b>${esc(s.label)}</b>\n${esc(s.snippet)}</div>`).join("")}`;
}

function personCard(emp, sub, statusHtml) {
  return `<div class="person-card">${avatar(emp.name, "lg")}<div class="who">
    <div class="name">${esc(emp.name)}</div><div class="sub">${sub}</div></div>${statusHtml || ""}</div>`;
}

function botTurn(q) {
  const pending = q.requests.find((r) => r.status === "pending");
  const passed = q.requests.filter((r) => r.status === "declined");
  const history = passed.length
    ? `<div class="history">${passed.map((r) => `${esc(firstName(r.expert.name))} didn't know`).join(" · ")}${pending ? ` → asked ${esc(firstName(pending.expert.name))}` : ""}</div>`
    : "";
  let body = "";
  if (q.status === "answered") {
    const top = q.sources[0];
    const where = top?.kind === "private_note" ? `${esc(top.person)}'s private notes` : top?.person ? `an earlier answer from ${esc(top.person)}` : "company memory";
    body = `<p class="bot-lead">Found it in <b>${where}</b>.</p>
      <div class="answer-card">${formatText(q.answer)}</div>
      <div class="meta-row">${sourceChips(q)}
        <span class="row"><span class="muted small">${Math.round(q.confidence * 100)}% match</span>
        ${pending ? "" : `<button class="link-btn" data-escalate="${q.id}">Not quite? Ask ${top?.person ? esc(firstName(top.person)) : "a person"}</button>`}</span>
      </div>`;
    if (pending) {
      body += `<p class="bot-lead" style="margin-top:16px">I've asked <b>${esc(pending.expert.name)}</b> to follow up.</p>
        ${personCard(pending.expert, esc(pending.expert.title), '<span class="status waiting">Waiting</span>')}`;
    }
  } else if (q.status === "routed" && pending) {
    body = `<p class="bot-lead">Nobody has written this down yet, so I asked the person most likely to know.</p>
      ${personCard(pending.expert, `${esc(pending.expert.title)} · ${esc(pending.reason)}`, '<span class="status waiting">Waiting for reply</span>')}
      ${history}`;
  } else if (q.status === "expert_answered" && q.answered_by) {
    body = `<p class="bot-lead"><b>${esc(q.answered_by.name)}</b> answered your question. I've saved it so the next person gets it right away.</p>
      <div class="answer-card">
        <div class="row" style="margin-bottom:10px">${avatar(q.answered_by.name, "sm")}<span class="small"><b>${esc(q.answered_by.name)}</b> <span class="muted">· ${esc(q.answered_by.title)}</span></span></div>
        ${formatText(q.answer)}
        ${q.pointers ? `<div class="pointer">${ICON.link}<span>${esc(q.pointers)}</span></div>` : ""}
      </div>${history}`;
  } else {
    body = `<p class="bot-lead">I couldn't find anyone who knows this yet. Try rephrasing, or add the answer to company memory once you have it.</p>
      ${q.sources.length ? `<div class="meta-row">${sourceChips(q)}</div>` : ""}${history}
      <div class="meta-row"><span></span><button class="link-btn" data-escalate="${q.id}">Try asking someone</button></div>`;
  }
  return `<div class="bot-msg"><span class="bot">M</span><div class="bot-body">${body}</div></div>`;
}

async function loadQuestions(scroll = false) {
  const qs = (await api("/api/questions")).reverse();
  $("#ask-empty").classList.toggle("hidden", qs.length > 0);
  $("#suggestions").classList.toggle("hidden", qs.length > 0);
  const html = qs.map((q) => `<div class="turn"><div class="user-msg">${esc(q.text)}</div>${botTurn(q)}</div>`).join("");
  if (html === state.threadHtml) return;
  const firstRender = state.threadHtml === null;
  state.threadHtml = html;
  $("#thread").innerHTML = html;
  $("#thread").classList.toggle("hidden", !qs.length);
  if (scroll || firstRender) $("main").scrollTop = $("main").scrollHeight;
}
$("#thread").addEventListener("click", async (e) => {
  const chip = e.target.closest("[data-src]");
  if (chip) { $(`#src-${chip.dataset.src}`).classList.toggle("hidden"); return; }
  const id = e.target.dataset.escalate;
  if (!id) return;
  try {
    const q = await api(`/api/questions/${id}/escalate`, { method: "POST" });
    const r = q.requests.find((x) => x.status === "pending");
    toast(r ? `Asked ${r.expert.name}` : "No one else to ask yet");
    loadQuestions(true);
  } catch (err) { toast(err.message); }
});

// ---------- inbox ----------
function requestCard(r) {
  const q = r.question;
  const head = `<div class="req-head">${avatar(q.asker.name)}<div class="who"><b>${esc(q.asker.name)}</b>
    <span class="muted"> asked you · ${ago(r.created_at)}</span></div>
    ${r.status === "pending" ? '<span class="status waiting">Needs answer</span>' : r.status === "answered" ? '<span class="status done">Answered</span>' : `<span class="status passed">${esc(r.status)}</span>`}</div>`;
  if (r.status !== "pending") {
    return `<div class="card">${head}<p class="req-q">${esc(q.text)}</p>${r.answer ? `<div class="req-answer">${esc(r.answer)}</div>` : ""}</div>`;
  }
  return `<form class="card" data-request="${r.id}">${head}
    <p class="req-q">${esc(q.text)}</p>
    <div class="why">${ICON.spark}<span><b>Why you:</b> ${esc(r.reason)}</span></div>
    <div class="req-form">
      <textarea name="answer" rows="3" placeholder="Write your answer…" required></textarea>
      <input name="pointers" placeholder="Where can they find more? Link, doc, folder or person (optional)" />
      <div class="req-actions">
        <button type="button" class="btn ghost" data-decline="${r.id}">I don't know, ask someone else</button>
        <button class="btn primary">Send answer</button>
      </div>
    </div>
  </form>`;
}
async function loadInbox() {
  const reqs = await api("/api/inbox");
  $("#inbox").innerHTML = reqs.length ? reqs.map(requestCard).join("") : `<div class="empty">You're all caught up.</div>`;
  setInboxCount(reqs);
}
$("#inbox").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  try {
    await api(`/api/requests/${f.dataset.request}/answer`, { method: "POST", body: { answer: f.answer.value, pointers: f.pointers.value } });
    toast("Answer sent and saved to memory");
    loadInbox();
  } catch (err) { toast(err.message); }
});
$("#inbox").addEventListener("click", async (e) => {
  const id = e.target.dataset.decline;
  if (!id) return;
  try {
    const res = await api(`/api/requests/${id}/decline`, { method: "POST" });
    toast(res.rerouted_to ? `Passed on to ${res.rerouted_to.name}` : "Passed. No one else matched.");
    loadInbox();
  } catch (err) { toast(err.message); }
});
function setInboxCount(reqs) {
  const n = reqs.filter((r) => r.status === "pending").length;
  $("#inbox-count").textContent = n;
  $("#inbox-count").classList.toggle("hidden", n === 0);
}
async function refreshInboxCount() {
  try { setInboxCount(await api("/api/inbox")); } catch {}
}

// ---------- notes ----------
async function loadNotes() {
  state.notes = await api("/api/notes");
  if (state.activeNoteId !== "new" && !state.notes.some((n) => n.id === state.activeNoteId)) state.activeNoteId = state.notes[0]?.id ?? "new";
  renderNotes();
}
function renderNotes() {
  $("#notes-list").innerHTML = state.notes
    .map((n) => `<li data-note="${n.id}" class="${n.id === state.activeNoteId ? "active" : ""}">${esc(n.title)}<small>Edited ${ago(n.updated_at)}</small></li>`)
    .join("") || `<li class="muted">No notes yet</li>`;
  const note = state.notes.find((n) => n.id === state.activeNoteId);
  $("#note-title").value = note?.title ?? "";
  $("#note-body").value = note?.body ?? "";
  $("#note-status").innerHTML = note ? `${ICON.lock.replace("<svg", '<svg style="width:12px;height:12px;vertical-align:-1px"')} Private · last saved ${ago(note.updated_at)}` : "New note";
  $("#delete-note").classList.toggle("hidden", !note);
}
$("#notes-list").addEventListener("click", (e) => {
  const li = e.target.closest("li[data-note]");
  if (!li) return;
  state.activeNoteId = Number(li.dataset.note);
  renderNotes();
});
$("#new-note").addEventListener("click", () => {
  state.activeNoteId = "new";
  renderNotes();
  $("#note-title").focus();
});
$("#note-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = { title: $("#note-title").value, body: $("#note-body").value };
  try {
    const n = typeof state.activeNoteId === "number"
      ? await api(`/api/notes/${state.activeNoteId}`, { method: "PUT", body })
      : await api("/api/notes", { method: "POST", body });
    state.activeNoteId = n.id;
    toast("Saved");
    loadNotes();
  } catch (err) { toast(err.message); }
});
$("#delete-note").addEventListener("click", async () => {
  if (typeof state.activeNoteId !== "number" || !confirm("Delete this note?")) return;
  await api(`/api/notes/${state.activeNoteId}`, { method: "DELETE" });
  state.activeNoteId = null;
  loadNotes();
});

// ---------- who knows what ----------
async function loadMap() {
  const m = await api("/api/expertise-map");
  $("#topic-cloud").innerHTML = m.topics
    .map((t) => `<span class="chip" data-topic="${esc(t.topic)}" title="${esc(t.people.map((p) => p.name).join(", "))}">${esc(t.topic)}</span>`)
    .join("");
  $("#people").innerHTML = m.people
    .map((p) => `<div class="card person"><div class="head">${avatar(p.employee.name, "lg")}
      <div><div class="name">${esc(p.employee.name)}</div><div class="sub">${esc(p.employee.title)} · ${esc(p.employee.team)}</div></div></div>
      <div class="chips">${p.topics.map((t) => `<span class="chip small" data-topic="${esc(t)}">${esc(t)}</span>`).join("")}</div></div>`)
    .join("");
}
async function findExperts(q) {
  const res = await api(`/api/experts?q=${encodeURIComponent(q)}`);
  $("#expert-results").innerHTML = res.length
    ? res.map((x, i) => `<div class="card expert">${avatar(x.employee.name, "lg")}
        <div class="who"><div class="name">${esc(x.employee.name)}${i === 0 ? '<span class="best">Best match</span>' : ""}</div>
        <div class="sub">${esc(x.employee.title)} · ${esc(x.reasons.join(", "))}</div>
        <div class="chips" style="margin-top:8px">${x.matched_topics.map((t) => `<span class="chip small static">${esc(t)}</span>`).join("")}</div></div>
        <a class="btn" href="mailto:${esc(x.employee.email)}">Contact</a></div>`).join("")
    : `<div class="empty">No one matches “${esc(q)}” yet.</div>`;
}
$("#expert-form").addEventListener("submit", (e) => { e.preventDefault(); findExperts($("#expert-input").value); });
$("#view-experts").addEventListener("click", (e) => {
  const t = e.target.dataset.topic;
  if (!t) return;
  $("#expert-input").value = t;
  findExperts(t);
  $("main").scrollTo({ top: 0, behavior: "smooth" });
});

// ---------- memory ----------
const SOURCE_LABEL = { chat: "From chat", expert: "Expert answer", manual: "Added manually" };
async function loadMemory(q) {
  const items = await api(`/api/memory${q ? `?q=${encodeURIComponent(q)}` : ""}`);
  $("#memory-list").innerHTML = items.length
    ? items.map((k) => `<div class="card"><div class="mem-q">${esc(k.question)}</div><div class="mem-a">${esc(k.answer)}</div>
        <div class="mem-meta"><span class="tag ${esc(k.source)}">${esc(SOURCE_LABEL[k.source] || k.source)}</span>
        ${k.answered_by ? `${avatar(k.answered_by.name, "sm")} ${esc(k.answered_by.name)}` : "Unknown author"}
        ${k.pointers ? `· ${esc(k.pointers)}` : ""} · ${ago(k.created_at)}</div></div>`).join("")
    : `<div class="empty">Nothing found.</div>`;
}
$("#memory-search").addEventListener("submit", (e) => { e.preventDefault(); loadMemory($("#memory-q").value); });
$("#memory-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/api/memory", { method: "POST", body: { question: $("#mem-q").value, answer: $("#mem-a").value, pointers: $("#mem-p").value } });
    e.target.reset();
    toast("Saved to memory");
    loadMemory();
  } catch (err) { toast(err.message); }
});
$("#chat-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const res = await api("/api/memory/ingest-chat", { method: "POST", body: { text: $("#chat-text").value } });
    $("#chat-result").textContent = `Learned ${res.created.length} Q&A pair(s).` +
      (res.unknown_authors.length ? ` Unknown people (add them under Profile & team): ${res.unknown_authors.join(", ")}` : "");
    loadMemory();
  } catch (err) { toast(err.message); }
});

// ---------- profile ----------
async function loadProfile() {
  const me = await api("/api/me");
  $("#skills-input").value = me.skills.join(", ");
}
$("#skills-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  await api("/api/me/skills", { method: "PUT", body: { skills: $("#skills-input").value.split(",") } });
  toast("Skills saved");
});
$("#employee-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/api/employees", {
      method: "POST",
      body: { name: $("#emp-name").value, email: $("#emp-email").value, title: $("#emp-title").value,
              team: $("#emp-team").value, skills: $("#emp-skills").value.split(",") },
    });
    e.target.reset();
    toast("Teammate added");
    await loadUsers();
  } catch (err) { toast(err.message); }
});

// ---------- boot ----------
(async function init() {
  const health = await api("/api/health");
  $("#llm-badge").textContent = health.llm ? "Answers written by AI from company sources" : "Answers are quoted directly from company sources";
  await loadUsers();
  show("ask");
  refreshInboxCount();
  setInterval(() => {
    refreshInboxCount();
    if (state.view === "ask") loadQuestions();
  }, 5000);
})();
