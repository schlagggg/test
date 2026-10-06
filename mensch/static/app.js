const state = { user: null, employees: [], notes: [], activeNoteId: null, view: "ask" };
const $ = (sel) => document.querySelector(sel);

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const initials = (name) => name.split(" ").map((p) => p[0]).slice(0, 2).join("").toUpperCase();
const ago = (iso) => {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString();
};

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

const STATUS_LABEL = {
  answered: "Answered by Mensch AI",
  expert_answered: "Answered by a colleague",
  routed: "Asking a colleague",
  unanswered: "No one found yet",
  pending: "Waiting for you",
  declined: "Passed",
  closed: "Closed",
};
const pill = (status, label) => `<span class="pill ${status}">${esc(label || STATUS_LABEL[status] || status)}</span>`;

// ---------- navigation ----------
function show(view) {
  state.view = view;
  document.querySelectorAll(".sidebar button").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("hidden", v.id !== `view-${view}`));
  ({ ask: loadQuestions, inbox: loadInbox, notes: loadNotes, experts: loadMap, memory: loadMemory, profile: loadProfile })[view]();
}
document.querySelectorAll(".sidebar button").forEach((b) => b.addEventListener("click", () => show(b.dataset.view)));

// ---------- users ----------
async function loadUsers() {
  state.employees = await api("/api/employees");
  const saved = Number(localStorage.getItem("mensch-user"));
  state.user = state.employees.some((e) => e.id === saved) ? saved : state.employees[0]?.id;
  $("#user-select").innerHTML = state.employees
    .map((e) => `<option value="${e.id}" ${e.id === state.user ? "selected" : ""}>${esc(e.name)} — ${esc(e.title)}</option>`)
    .join("");
}
$("#user-select").addEventListener("change", (e) => {
  state.user = Number(e.target.value);
  localStorage.setItem("mensch-user", state.user);
  state.activeNoteId = null;
  refreshInboxCount();
  show(state.view);
});

// ---------- ask ----------
const SUGGESTIONS = [
  "How do I get my travel expenses reimbursed?",
  "Who approves a discount above 20%?",
  "How do I sign an NDA with a new vendor?",
];
$("#suggestions").innerHTML = SUGGESTIONS.map((s) => `<span class="chip">${esc(s)}</span>`).join("");
$("#suggestions").addEventListener("click", (e) => {
  if (e.target.classList.contains("chip")) $("#ask-input").value = e.target.textContent;
});
$("#ask-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#ask-form").requestSubmit(); }
});
$("#ask-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = e.target.querySelector("button[type=submit]");
  btn.disabled = true;
  try {
    const q = await api("/api/ask", { method: "POST", body: { question: $("#ask-input").value } });
    $("#ask-input").value = "";
    if (q.status === "routed") toast(`Asked ${q.requests.at(-1).expert.name} for you`);
    await loadQuestions();
  } catch (err) { toast(err.message); }
  btn.disabled = false;
});

function questionCard(q) {
  const pending = q.requests.find((r) => r.status === "pending");
  let label = STATUS_LABEL[q.status];
  if (q.status === "routed" && pending) label = `Asked ${pending.expert.name}`;
  if (q.status === "expert_answered" && q.answered_by) label = `Answered by ${q.answered_by.name}`;
  const answer = q.answer
    ? `<div class="answer">${esc(q.answer)}</div>`
    : q.status === "routed"
      ? `<p class="meta">Mensch AI couldn't find a confident answer, so it asked a colleague who should know. You'll see the answer here.</p>`
      : q.status === "unanswered"
        ? `<p class="meta">Nobody matched this question yet. Try rephrasing, or add the answer to company memory once you find it.</p>`
        : "";
  const pointers = q.pointers && q.status === "expert_answered" ? `<p class="meta">More info: ${esc(q.pointers)}</p>` : "";
  const sourceTitle = q.status === "answered" ? "Sources" : "Possibly related";
  const sources = q.sources.length && q.status !== "expert_answered"
    ? `<div class="sources"><div class="meta">${sourceTitle}:</div>${q.sources
        .map((s) => `<details><summary>${esc(s.label)}</summary><pre>${esc(s.snippet)}</pre></details>`).join("")}</div>`
    : "";
  const routing = q.requests.length
    ? `<ul class="routing">${q.requests
        .map((r) => `<li>${pill(r.status, r.status === "pending" ? "waiting" : r.status)} <b>${esc(r.expert.name)}</b> <span class="meta">— ${esc(r.reason)}</span></li>`)
        .join("")}</ul>`
    : "";
  const canEscalate = !pending && q.status !== "expert_answered";
  return `<div class="card">
    <div class="q-head"><div class="q-text">${esc(q.text)}</div>${pill(q.status, label)}</div>
    ${answer}${pointers}${sources}${routing}
    <div class="row" style="justify-content:space-between;margin-top:8px">
      <span class="meta">${ago(q.created_at)}${q.status === "answered" ? ` · confidence ${Math.round(q.confidence * 100)}%` : ""}</span>
      ${canEscalate ? `<button class="link" data-escalate="${q.id}">${q.status === "answered" ? "Not helpful? Ask a person" : "Try another person"}</button>` : ""}
    </div>
  </div>`;
}

async function loadQuestions() {
  const qs = await api("/api/questions");
  $("#questions").innerHTML = qs.length ? qs.map(questionCard).join("") : `<div class="empty">You haven't asked anything yet.</div>`;
}
$("#questions").addEventListener("click", async (e) => {
  const id = e.target.dataset.escalate;
  if (!id) return;
  try {
    const q = await api(`/api/questions/${id}/escalate`, { method: "POST" });
    const r = q.requests.find((x) => x.status === "pending");
    toast(r ? `Asked ${r.expert.name}` : "No one else to ask yet");
    loadQuestions();
  } catch (err) { toast(err.message); }
});

// ---------- inbox ----------
function requestCard(r) {
  const q = r.question;
  if (r.status !== "pending") {
    return `<div class="card"><div class="q-head"><div><div class="q-text">${esc(q.text)}</div>
      <div class="meta">from ${esc(q.asker.name)} · ${ago(r.created_at)}</div></div>${pill(r.status, r.status)}</div>
      ${r.answer ? `<div class="answer">${esc(r.answer)}</div>` : ""}</div>`;
  }
  return `<form class="card" data-request="${r.id}">
    <div class="q-head"><div><div class="q-text">${esc(q.text)}</div>
      <div class="meta">${esc(q.asker.name)} asked · ${ago(r.created_at)}</div></div>${pill("pending")}</div>
    <p class="meta">Why you: ${esc(r.reason)}</p>
    <textarea name="answer" rows="3" placeholder="Your answer" required></textarea>
    <input name="pointers" placeholder="Where can they find more info? (link, doc, folder, person) — optional" />
    <div class="row end">
      <button type="button" data-decline="${r.id}">I don't know — ask someone else</button>
      <button class="primary">Send answer</button>
    </div>
  </form>`;
}
async function loadInbox() {
  const reqs = await api("/api/inbox");
  $("#inbox").innerHTML = reqs.length ? reqs.map(requestCard).join("") : `<div class="empty">Nothing to answer. Nice.</div>`;
  setInboxCount(reqs);
}
$("#inbox").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  try {
    await api(`/api/requests/${f.dataset.request}/answer`, {
      method: "POST", body: { answer: f.answer.value, pointers: f.pointers.value },
    });
    toast("Answer sent and remembered");
    loadInbox();
  } catch (err) { toast(err.message); }
});
$("#inbox").addEventListener("click", async (e) => {
  const id = e.target.dataset.decline;
  if (!id) return;
  try {
    const res = await api(`/api/requests/${id}/decline`, { method: "POST" });
    toast(res.rerouted_to ? `Passed on to ${res.rerouted_to.name}` : "Passed — no one else matched");
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
  if (!state.notes.some((n) => n.id === state.activeNoteId)) state.activeNoteId = state.notes[0]?.id ?? null;
  renderNotes();
}
function renderNotes() {
  $("#notes-list").innerHTML = state.notes
    .map((n) => `<li data-note="${n.id}" class="${n.id === state.activeNoteId ? "active" : ""}">${esc(n.title)}<small>edited ${ago(n.updated_at)}</small></li>`)
    .join("") || `<li class="meta">No notes yet.</li>`;
  const note = state.notes.find((n) => n.id === state.activeNoteId);
  $("#note-title").value = note?.title ?? "";
  $("#note-body").value = note?.body ?? "";
  $("#delete-note").classList.toggle("hidden", !note);
}
$("#notes-list").addEventListener("click", (e) => {
  const li = e.target.closest("li[data-note]");
  if (!li) return;
  state.activeNoteId = Number(li.dataset.note);
  renderNotes();
});
$("#new-note").addEventListener("click", () => {
  state.activeNoteId = null;
  renderNotes();
  $("#note-title").focus();
});
$("#note-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = { title: $("#note-title").value, body: $("#note-body").value };
  try {
    const n = state.activeNoteId
      ? await api(`/api/notes/${state.activeNoteId}`, { method: "PUT", body })
      : await api("/api/notes", { method: "POST", body });
    state.activeNoteId = n.id;
    toast("Saved");
    loadNotes();
  } catch (err) { toast(err.message); }
});
$("#delete-note").addEventListener("click", async () => {
  if (!state.activeNoteId || !confirm("Delete this note?")) return;
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
    .map((p) => `<div class="card person"><div class="person-head"><span class="avatar">${initials(p.employee.name)}</span>
      <div><div class="name">${esc(p.employee.name)}</div><div class="meta">${esc(p.employee.title)} · ${esc(p.employee.team)}</div></div></div>
      <div class="chips">${p.topics.map((t) => `<span class="chip" data-topic="${esc(t)}">${esc(t)}</span>`).join("")}</div></div>`)
    .join("");
}
async function findExperts(q) {
  const res = await api(`/api/experts?q=${encodeURIComponent(q)}`);
  $("#expert-results").innerHTML = res.length
    ? res.map((x, i) => `<div class="card expert-result"><div class="person-head"><span class="avatar">${initials(x.employee.name)}</span>
        <div><div class="name"><b>${esc(x.employee.name)}</b> <span class="meta">${esc(x.employee.title)}</span>${i === 0 ? ' <span class="badge">best match</span>' : ""}</div>
        <div class="meta">${esc(x.reasons.join("; "))} — matched: ${esc(x.matched_topics.join(", "))}</div></div></div>
        <a class="meta" href="mailto:${esc(x.employee.email)}">${esc(x.employee.email)}</a></div>`).join("")
    : `<div class="empty">No one matches “${esc(q)}” yet.</div>`;
}
$("#expert-form").addEventListener("submit", (e) => { e.preventDefault(); findExperts($("#expert-input").value); });
document.querySelector("#view-experts").addEventListener("click", (e) => {
  const t = e.target.dataset.topic;
  if (!t) return;
  $("#expert-input").value = t;
  findExperts(t);
  window.scrollTo({ top: 0, behavior: "smooth" });
});

// ---------- memory ----------
const SOURCE_LABEL = { chat: "from chat", expert: "expert answer", manual: "added manually" };
async function loadMemory(q) {
  const items = await api(`/api/memory${q ? `?q=${encodeURIComponent(q)}` : ""}`);
  $("#memory-list").innerHTML = items.length
    ? items.map((k) => `<div class="card"><div class="q-head"><div class="q-text">${esc(k.question)}</div>
        <span class="pill closed">${esc(SOURCE_LABEL[k.source] || k.source)}</span></div>
        <div class="answer">${esc(k.answer)}</div>
        <div class="meta">${k.answered_by ? `Answered by ${esc(k.answered_by.name)}` : "Unknown author"}${k.asked_by ? ` · asked by ${esc(k.asked_by.name)}` : ""}${k.pointers ? ` · More info: ${esc(k.pointers)}` : ""} · ${ago(k.created_at)}</div></div>`).join("")
    : `<div class="empty">Nothing found.</div>`;
}
$("#memory-search").addEventListener("submit", (e) => { e.preventDefault(); loadMemory($("#memory-q").value); });
$("#memory-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/api/memory", { method: "POST", body: { question: $("#mem-q").value, answer: $("#mem-a").value, pointers: $("#mem-p").value } });
    e.target.reset();
    toast("Remembered");
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
  $("#llm-badge").textContent = health.llm ? "LLM answers on" : "Extractive mode";
  await loadUsers();
  show("ask");
  refreshInboxCount();
  setInterval(() => {
    refreshInboxCount();
    if (state.view === "ask") loadQuestions();
  }, 5000);
})();
