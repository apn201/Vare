"use strict";

const $ = (s, el = document) => el.querySelector(s);

const EXAMPLES = {
  film: "Finally saw Dune: Part Two in IMAX. Villeneuve shoots the desert like a cathedral, Hans Zimmer's score rattled my ribs " +
    "and Austin Butler's Feyd-Rautha stole every scene he was in. Going back to reread Frank Herbert before Messiah comes out.",
  music: "Billie Eilish at the O2 last night. Twenty thousand people screaming every word of Birds of a Feather, " +
    "Finneas grinning at the piano. The Hit Me Hard and Soft songs hit even harder live. Haven't felt a room like that since Lorde's Melodrama tour.",
  tv: "Binged the new season of The Bear in two nights. Carmy is still spiralling, Sydney finally gets her moment, " +
    "and that Chicago Italian beef still looks like the best sandwich on earth. Jeremy Allen White deserves every award.",
  linkedin: "Excited to share that our team has wrapped up a successful Q3! We focused on cross-functional alignment, " +
    "streamlined our onboarding process and improved customer satisfaction scores by 12%. " +
    "Grateful for a team that shows up every day. Onwards to Q4!",
};

const MARK = { llm: "◆", qloo_direct: "●", qloo_profile: "■", qloo_inferred: "◆●" };
const MARK_LABEL = {
  llm: "llm: from the language model only",
  qloo_direct: "qloo_direct: in the text (or implied by it), confirmed by Qloo",
  qloo_profile: "qloo_profile: Qloo's own tag for the subject",
  qloo_inferred: "qloo_inferred: an association from Qloo Insights",
};

const form = $("#form");
$("#mcp-url").textContent = new URL("mcp", location.href).href;
const text = $("#text");
const go = $("#go");
const adv = $("#advanced");
let last = null;

function norm(s) {
  return s.toLowerCase().replace(/^#/, "").replace(/[^0-9a-zÀ-ɏ]+/g, "");
}

function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k === "text") e.textContent = v;
    else e.setAttribute(k, v);
  }
  for (const k of kids) if (k != null) e.append(k);
  return e;
}

// ---- input helpers ------------------------------------------------------

text.addEventListener("input", () => { $("#chars").textContent = `${text.value.length} / 4000`; });
document.querySelectorAll("[data-example]").forEach((b) =>
  b.addEventListener("click", () => {
    text.value = EXAMPLES[b.dataset.example];
    text.dispatchEvent(new Event("input"));
    if (b.dataset.example === "linkedin") form.destination.value = "linkedin";
    text.focus();
  }));
adv.addEventListener("change", () => {
  $("#adv-state").textContent = adv.checked ? "ON" : "OFF";
  $("#trace").hidden = !(adv.checked && last && last.trace);
});

// ---- generate -------------------------------------------------------------

form.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const body = {
    text: text.value.trim(),
    destination: form.destination.value,
    mode: form.mode.value,
    advanced: adv.checked,
  };
  if (!body.text) { setStatus("Paste some text first."); text.focus(); return; }

  go.disabled = true;
  $("#progress").hidden = false;
  setStatus("Running both paths. The Qloo path makes several API calls; this usually takes a few seconds.");
  try {
    const res = await fetch("api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => null);
    if (!res.ok) {
      const msg = data && data.detail ? (Array.isArray(data.detail) ? data.detail.map((d) => d.msg).join("; ") : data.detail) : res.statusText;
      setStatus(`Request rejected (${res.status}): ${msg}`);
      return;
    }
    last = data;
    render(data);
    setStatus("");
  } catch (e) {
    setStatus(`Could not reach the server: ${e.message}`);
  } finally {
    go.disabled = false;
    $("#progress").hidden = true;
  }
});

function setStatus(s) { $("#status").textContent = s; }

// ---- results -------------------------------------------------------------

function render(data) {
  const c = data.comparison;
  const mode = data.mode;
  const aKeys = new Set(keys(c.baseline));
  renderCol($("#col-a"), c.baseline, mode, null, data.destination);
  renderCol($("#col-b"), c.experimental, mode, aKeys, data.destination);
  $("#overlap").textContent = c.overlap_count;
  $("#novelty").textContent = c.novelty_count;
  $("#latency").textContent = (c.total_latency_ms / 1000).toFixed(1) + "s";
  $("#detail").hidden = true;
  $("#results").hidden = false;
  document.querySelectorAll(".legend").forEach((l) => (l.hidden = mode !== "tags"));

  if (data.trace) renderTrace(data.trace);
  $("#trace").hidden = !(adv.checked && data.trace);
}

function keys(path) {
  if (path.tags) return path.tags.map((t) => norm(t.tag));
  return (path.topics || []).map((t) => norm(t.topic));
}

function renderCol(col, path, mode, otherKeys, destination) {
  const sub = $(".sub", col);
  sub.textContent = mode === "tags"
    ? (otherKeys ? "Culturally expanded tags" : "Generated tags")
    : (otherKeys ? "Topics from Qloo cultural signals" : "Topics from the LLM alone");
  const err = $(".error", col);
  err.hidden = !path.error;
  err.textContent = path.error || "";
  const items = $(".items", col);
  items.replaceChildren();

  if (mode === "tags") {
    for (const t of path.tags || []) {
      const novel = otherKeys && !otherKeys.has(norm(t.tag));
      const chip = el("button", { type: "button", class: `chip ${t.source}${novel ? " novel" : ""}`, "aria-pressed": "false",
        title: novel ? "Not in the conventional column" : "" },
        el("i", { class: "mk" + (t.source === "llm" ? "" : " q"), "aria-hidden": "true", text: MARK[t.source] + " " }),
        "#" + t.tag);
      chip.addEventListener("click", () => showDetail(chip, t, novel));
      items.append(chip);
    }
  } else {
    for (const t of path.topics || []) {
      items.append(el("div", { class: "topic" },
        el("b", { text: t.topic }),
        el("p", { text: t.connection }),
        el("p", { class: "basis", text: t.cultural_basis })));
    }
  }
  const n = path.count;
  $(".count", col).textContent = `${n} ${mode === "tags" ? "tag" : "topic"}${n === 1 ? "" : "s"}`;
  const copy = $(".copy", col);
  copy.disabled = n === 0;
  copy.onclick = () => copyOut(path, mode, destination, copy);
}

function showDetail(chip, t, novel) {
  const d = $("#detail");
  const wasOpen = chip.getAttribute("aria-pressed") === "true";
  document.querySelectorAll(".chip[aria-pressed=true]").forEach((c) => c.setAttribute("aria-pressed", "false"));
  if (wasOpen) { d.hidden = true; return; }
  chip.setAttribute("aria-pressed", "true");
  const dl = el("dl", {},
    el("dt", { text: "tag" }), el("dd", { text: t.tag }),
    el("dt", { text: "source" }), el("dd", { text: MARK[t.source] + " " + MARK_LABEL[t.source] }),
    el("dt", { text: "explanation" }), el("dd", { text: t.explanation || "(none: the conventional path returns tags without reasons)" }),
    el("dt", { text: "evidence" }), el("dd", { text: t.evidence || "(none)" }));
  if (novel) dl.append(el("dt", { text: "novelty" }), el("dd", { text: "not in the conventional column" }));
  d.replaceChildren(dl);
  d.hidden = false;
}

async function copyOut(path, mode, destination, btn) {
  let out;
  if (mode === "tags") {
    const tags = (path.tags || []).map((t) => t.tag);
    out = destination === "general" ? tags.join(", ")
      : tags.map((t) => "#" + t.replace(/[^\p{L}\p{N}_]+/gu, "")).join(" ");
  } else {
    out = (path.topics || []).map((t) => `${t.topic}\n  ${t.connection}\n  ${t.cultural_basis}`).join("\n\n");
  }
  try {
    await navigator.clipboard.writeText(out);
    flash(btn, "Copied");
  } catch {
    window.prompt("Copy:", out);
  }
}

function flash(btn, msg) {
  const old = btn.textContent;
  btn.textContent = msg;
  setTimeout(() => (btn.textContent = old), 1200);
}

// ---- trace -----------------------------------------------------------------

function renderTrace(stages) {
  const box = $("#stages");
  box.replaceChildren();
  stages.forEach((s) => {
    const badges = [];
    if (s.latency_ms != null) badges.push(el("span", { class: "badge", text: `${s.latency_ms} ms` }));
    if (s.response_summary && s.response_summary.cached) badges.push(el("span", { class: "badge cache", text: "cached" }));
    if (s.response_summary && s.response_summary.count != null) badges.push(el("span", { class: "badge", text: `${s.response_summary.count} items` }));
    if (s.tokens_used) badges.push(el("span", { class: "badge", text: `${s.tokens_used} tok` }));
    if (s.error) badges.push(el("span", { class: "badge err", text: "error" }));
    const summary = el("summary", {}, el("span", { class: "name", text: s.stage }), ...badges);
    const body = el("div", { class: "body" });
    const add = (label, value) => {
      if (value == null || (Array.isArray(value) && !value.length)) return;
      body.append(el("h3", { text: label }), el("pre", { text: typeof value === "string" ? value : JSON.stringify(value, null, 2) }));
    };
    if (s.endpoint) add("request", `${s.method || "GET"} ${s.endpoint}`);
    add("params", s.params);
    add("model", s.model);
    add("error", s.error);
    add("prompt", s.prompt);
    add("response", s.response_summary);
    add("items returned", s.raw_items);
    add("selected", s.selected);
    add("rejected", s.rejected);
    box.append(el("details", { class: "stage" }, summary, body));
  });
}
