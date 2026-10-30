/* AEGIS-Care Sentinel view.
 *
 * Loaded after app.js and reuses its helpers ($, el, esc, api, toast, role).
 * Owns its own patrol loop: it runs only while the Sentinel tab is visible, so
 * a background tab never mutates state (autopilot) or spends model calls.
 */
"use strict";

(() => {
  const S = {
    started: false,
    timer: null,
    ticker: null,
    busy: false,
    last: null,
    lastTraceSig: "",
    lastAt: null,
    status: null,
    patients: [],
    openCase: null,
  };
  const INTERVAL = 8000;
  const KEY = "aegis-sentinel-v1";

  const SEV = { critical: "Critical", high: "High", medium: "Medium", low: "Low", info: "Info" };
  const PHASE = { observe: "Observe", detect: "Detect", correlate: "Correlate",
                  decide: "Decide", act: "Act", verify: "Verify",
                  understand: "Understand", resolve: "Resolve", corroborate: "Corroborate",
                  file: "File" };
  const EXAMPLES = [
    { label: "Wrong patient", text: (n) => `The assistant's handover for ${n} shows lab results I think belong to a different patient.` },
    { label: "Outdated value", text: (n) => `The summary for ${n} still shows the old blood pressure even though it was corrected this morning.` },
    { label: "Restricted info", text: (n) => `Registration staff could see a confidential screening note in ${n}'s summary that they should not be able to see.` },
  ];

  const prefs = () => {
    try { return JSON.parse(sessionStorage.getItem(KEY) || "{}"); } catch (e) { return {}; }
  };
  const savePrefs = (patch) => {
    try { sessionStorage.setItem(KEY, JSON.stringify({ ...prefs(), ...patch })); } catch (e) { /* blocked */ }
  };

  const ago = (iso) => {
    if (!iso) return "never";
    const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
    if (s < 5) return "just now";
    if (s < 60) return `${s}s ago`;
    const m = Math.round(s / 60);
    return m < 60 ? `${m} min ago` : `${Math.round(m / 60)} h ago`;
  };
  const name = (pid) => (S.last?.patient_names || {})[pid] || pid;
  const who = (pid) => pid ? `<b>${esc(name(pid))}</b> <code>${esc(pid)}</code>` : "—";
  const shortKey = (k) => String(k || "").replace(/^TR-/, "").replace(/@v(\d+)$/, " · v$1");
  const typeLabel = (t) => String(t || "memory").replace(/_/g, " ");
  const plural = (n, one, many) => `${n} ${n === 1 ? one : (many || one + "s")}`;

  /* ---------------- lifecycle ---------------- */
  window.sentinelViewChanged = (view) => {
    if (view === "sentinel") start();
    else stop();
  };

  function start() {
    if (!S.started) {
      S.started = true;
      bind();
      const p = prefs();
      $("sn-live").checked = p.live !== false;
      $("sn-autopilot").checked = !!p.autopilot;
      loadStatus();
      loadPatients();
    }
    patrol({ quiet: true });
    schedule();
    clearInterval(S.ticker);
    S.ticker = setInterval(tick, 1000);
  }

  function stop() {
    clearTimeout(S.timer);
    clearInterval(S.ticker);
    S.timer = null;
  }

  function schedule() {
    clearTimeout(S.timer);
    if (!$("sn-live").checked || !$("view-sentinel").classList.contains("active")) return;
    S.timer = setTimeout(async () => {
      if (document.visibilityState === "visible") await patrol({ quiet: true });
      schedule();
    }, INTERVAL);
  }

  function tick() {
    const meta = $("sn-posture-meta");
    if (!meta || !S.last) return;
    const live = $("sn-live").checked;
    meta.textContent = `Sweep #${S.last.patrol} · ${ago(S.lastAt)}` +
      (live ? " · live" : " · paused");
    $("sn-live-dot").classList.toggle("is-on", live);
  }

  function bind() {
    $("sn-patrol").addEventListener("click", () => patrol({ quiet: false }));
    $("sn-live").addEventListener("change", (e) => {
      savePrefs({ live: e.target.checked });
      schedule();
      tick();
    });
    $("sn-autopilot").addEventListener("change", (e) => {
      savePrefs({ autopilot: e.target.checked });
      toast(e.target.checked ? "Autopilot on" : "Autopilot off", {
        detail: e.target.checked
          ? "The Sentinel will contain memory incidents as soon as it finds them. It will still never refile a chart on its own."
          : "Containment plans will wait for your approval.",
        kind: e.target.checked ? "good" : "" });
      if (e.target.checked) patrol({ quiet: false });
    });
    $("sn-jump-report").addEventListener("click", () => {
      $("sn-report-panel").scrollIntoView({ behavior: "smooth", block: "start" });
      setTimeout(() => $("sn-report-text").focus({ preventScroll: true }), 350);
    });
    $("sn-drill").addEventListener("click", plantDrill);
    $("sn-report-form").addEventListener("submit", submitReport);

    $("sn-cases").addEventListener("click", (e) => {
      const contain = e.target.closest("[data-contain]");
      if (contain) return containCase(contain.dataset.contain, contain);
      const head = e.target.closest("[data-case-toggle]");
      if (head) {
        const id = head.dataset.caseToggle;
        S.openCase = S.openCase === id ? null : id;
        renderCases(S.last);
      }
    });
    $("sn-source").addEventListener("click", (e) => {
      const btn = e.target.closest("[data-refile]");
      if (btn) refile(btn.dataset.refile, btn.dataset.target, btn);
    });
    $("sn-contained").addEventListener("click", (e) => {
      const btn = e.target.closest("[data-cert]");
      if (!btn) return;
      const box = $(`cert-${btn.dataset.cert}`);
      if (box) {
        box.hidden = !box.hidden;
        btn.textContent = box.hidden ? "Show certificate" : "Hide certificate";
      }
    });
  }

  /* ---------------- data ---------------- */
  async function loadStatus() {
    try {
      S.status = await api("/api/sentinel/status");
      renderDetectors(null);
      renderModel(S.status.model);
    } catch (e) { /* patrol will surface errors */ }
  }

  async function loadPatients() {
    try {
      const data = await api("/api/patients?only_with_memory=false");
      S.patients = data.patients.map((p) => p.patient);
      $("sn-patient-list").innerHTML = S.patients
        .map((p) => `<option value="${esc(p.name)} · ${esc(p.id)}"></option>`).join("");
      renderExamples();
    } catch (e) { /* optional */ }
  }

  async function patrol({ quiet = true } = {}) {
    if (S.busy) return;
    S.busy = true;
    const btn = $("sn-patrol");
    btn.disabled = true;
    btn.classList.add("is-busy");
    $("sn-trace-meta").textContent = "sweeping…";
    try {
      const data = await api("/api/sentinel/patrol", {
        method: "POST",
        body: JSON.stringify({ autopilot: $("sn-autopilot").checked }),
      });
      const before = S.last;
      S.last = data;
      S.lastAt = data.at;
      render(data, before);
      if (!quiet && !data.acted.length) {
        toast(data.posture.label, { detail: `${plural(data.findings.length, "finding")} · ${plural(data.cases.length, "open case")}`,
          kind: data.posture.level === "clear" ? "good" : "" });
      }
      announceNew(before, data);
    } catch (e) {
      $("sn-trace-meta").textContent = "error";
      if (!quiet) toast("Patrol failed", { detail: e.message, kind: "bad" });
    } finally {
      S.busy = false;
      btn.disabled = false;
      btn.classList.remove("is-busy");
    }
  }

  function announceNew(before, data) {
    if (data.acted.length) {
      const rebuilt = data.acted.reduce((n, a) => n + a.repaired, 0);
      toast(`Autopilot contained ${plural(data.acted.length, "incident")}`, {
        detail: `${rebuilt} record(s) rebuilt from FHIR; re-scan verified.`, kind: "good", timeout: 7000 });
      return;
    }
    const prev = new Set((before?.cases || []).map((c) => c.case_id));
    const fresh = data.cases.filter((c) => !prev.has(c.case_id));
    if (before && fresh.length) {
      toast(`New: ${fresh[0].title}`, {
        detail: `${plural(fresh[0].members.length, "memory", "memories")} affected · ${SEV[fresh[0].severity]}`,
        kind: "bad", timeout: 8000 });
      const announcer = $("urgent-announcer");
      if (announcer) announcer.textContent = `Sentinel detected: ${fresh[0].title}`;
    }
    const found = (data.drills || []).filter((d) => d.status === "detected" &&
      !(before?.drills || []).some((b) => b.drill_id === d.drill_id && b.status === "detected"));
    found.forEach((d) => toast(`${d.drill_id} found`, {
      detail: `It was ${d.family_name}. Recall ${Math.round(d.score.recall * 100)}%, ${d.score.clean_flagged} clean record(s) flagged.`,
      kind: "good", timeout: 8000 }));
  }

  /* ---------------- rendering ---------------- */
  function render(data, before) {
    renderPosture(data);
    renderStats(data);
    renderBrief(data.brief);
    renderTrace(data);
    renderCases(data);
    renderSource(data);
    renderContained(data);
    renderDrills(data);
    renderDetectors(data);
    renderModel(data.model);
    tick();
  }

  function renderPosture(data) {
    const p = data.posture;
    const box = $("sn-posture");
    box.className = `sn-posture is-${p.level}`;
    $("sn-posture-label").textContent = p.label;
    // Blips: one per open case, placed deterministically around the scope.
    const blips = data.cases.slice(0, 8).map((c, i) => {
      const angle = (i * 137.5 + 20) * Math.PI / 180;
      const r = 18 + (i % 3) * 13;
      return `<circle cx="${(60 + r * Math.sin(angle)).toFixed(1)}" cy="${(60 - r * Math.cos(angle)).toFixed(1)}"
        r="${c.severity === "critical" ? 4.5 : 3.5}" class="sn-blip sev-${c.severity}"/>`;
    });
    $("sn-blips").innerHTML = blips.join("");
  }

  function renderStats(data) {
    const o = data.observed;
    const lineage = Math.round((o.lineage.coverage ?? 1) * 100);
    const items = [
      [o.memories, "memories watched", `${o.servable} servable`],
      [o.source_records.toLocaleString(), "source records", "registry"],
      [S.status?.detectors.length ?? 13, "detectors", `${data.elapsed_ms} ms sweep`],
      [`${lineage}%`, "lineage intact", o.lineage.unlinked ? `${o.lineage.unlinked} unlinked` : "fully linked"],
      [data.cases.length, "open cases", data.cases.length ? "needs action" : "none"],
      [(data.contained || []).length, "contained", "this session"],
    ];
    $("sn-stats").innerHTML = items.map(([v, l, s]) =>
      `<div class="sn-stat"><b>${esc(v)}</b><span>${esc(l)}</span><small>${esc(s)}</small></div>`).join("");
  }

  function renderBrief(b) {
    if (!b) return;
    const src = b.source === "gemini"
      ? `<span class="sn-src is-ai">Gemini brief</span>`
      : `<span class="sn-src">Local brief</span>`;
    $("sn-brief").innerHTML =
      `<div class="sn-brief-mark" aria-hidden="true"><i></i><i></i><i></i></div>
       <div class="sn-brief-body">
         <div class="sn-brief-top"><strong>${esc(b.headline)}</strong>${src}</div>
         <p>${esc(b.brief)}</p>
         <p class="sn-next"><span>Next</span> ${esc(b.next_step)}</p>
       </div>`;
  }

  function renderTrace(data) {
    const list = $("sn-trace");
    const sig = data.trace.map((t) => t.phase + t.text).join("|");
    $("sn-trace-meta").textContent = `sweep #${data.patrol} · ${data.elapsed_ms} ms`;
    if (sig === S.lastTraceSig) {
      list.querySelectorAll("li").forEach((li) => li.classList.add("is-shown"));
      return;
    }
    S.lastTraceSig = sig;
    list.innerHTML = "";
    data.trace.forEach((t, i) => {
      const li = el("li", `sn-step ph-${t.phase}${t.ok === false ? " is-bad" : ""}${t.ok ? " is-ok" : ""}`);
      li.innerHTML = `<span class="sn-step-phase">${esc(PHASE[t.phase] || t.phase)}</span>
        <span class="sn-step-text">${esc(t.text)}</span>
        <span class="sn-step-ms">${t.ms} ms</span>`;
      list.appendChild(li);
      // Progressive reveal: the trace reads as reasoning, not a dump.
      setTimeout(() => li.classList.add("is-shown"), 90 * i + 30);
    });
  }

  function renderCases(data) {
    const box = $("sn-cases");
    if (!data) return;
    $("sn-case-count").textContent = data.cases.length;
    $("sn-case-count").classList.toggle("is-hot", data.cases.length > 0);
    if (!data.cases.length) {
      box.innerHTML = `<div class="sn-empty"><b>No open memory incidents.</b>
        <span>Every servable memory passes every check. Plant a blind drill to see a hunt.</span></div>`;
      return;
    }
    if (!S.openCase || !data.cases.some((c) => c.case_id === S.openCase)) {
      S.openCase = data.cases[0].case_id;
    }
    box.innerHTML = data.cases.map((c) => {
      const open = c.case_id === S.openCase;
      const fam = c.family_name ? `<span class="sn-tag">Looks like ${esc(c.likely_family)} · ${esc(c.family_name)}</span>` : "";
      return `<article class="sn-case sev-${c.severity}${open ? " is-open" : ""}">
        <button class="sn-case-head" type="button" data-case-toggle="${esc(c.case_id)}" aria-expanded="${open}">
          <span class="sn-sev sev-${c.severity}">${SEV[c.severity]}</span>
          <span class="sn-case-title"><strong>${esc(c.title)}</strong>
            <small>${esc(c.case_id)} · ${plural(c.members.length, "memory", "memories")} · ${plural(c.patients.length, "patient")} · confidence ${Math.round(c.confidence * 100)}%</small></span>
          <span class="sn-caret" aria-hidden="true">▾</span>
        </button>
        ${open ? `<div class="sn-case-body">
          <div class="sn-case-meta">${fam}
            ${c.patients.map((p) => `<span class="sn-tag">${who(p)}</span>`).join("")}
            ${c.task_id ? `<span class="sn-tag">task <code>${esc(c.task_id)}</code></span>` : ""}</div>
          <ol class="sn-chain">${c.members.map((m) => `
            <li class="${m.root ? "is-root" : ""}">
              <span class="sn-node" aria-hidden="true"></span>
              <div>
                <div class="sn-chain-top"><b>${esc(typeLabel(m.type))}</b>
                  <span class="sn-owner">${esc(typeLabel(m.owner))} runtime</span>
                  ${m.root ? `<span class="sn-root">root cause</span>` : ""}</div>
                <p>${esc(m.summary)}</p>
                ${evidence(m.evidence)}
                <code class="sn-key">${esc(shortKey(m.key))}</code>
              </div>
            </li>`).join("")}
          </ol>
          ${c.at_risk.length ? `<p class="sn-risk">${plural(c.at_risk.length, "more memory", "more memories")} downstream not yet flagged; CARE will test them.</p>` : ""}
          <div class="sn-plan">
            <div><span class="sn-plan-kicker">Agent plan</span>
              <p>${esc(c.plan.why.charAt(0).toUpperCase() + c.plan.why.slice(1))}.</p></div>
            <button class="btn" type="button" data-contain="${esc(c.case_id)}">Approve containment <span>→</span></button>
          </div>
        </div>` : ""}
      </article>`;
    }).join("");
  }

  function evidence(ev) {
    if (!ev) return "";
    const rows = [];
    if (ev.query) rows.push(["Alias query", ev.query]);
    if (ev.stored) rows.push(["Memory says", ev.stored]);
    if (ev.fhir_returns) rows.push(["FHIR says", ev.fhir_returns.join(", ")]);
    if (ev.expected) rows.push(["Task is about", ev.expected.join(", ")]);
    if (ev.names) rows.push(["Memory names", ev.names]);
    if (ev.parent_patient) rows.push(["Parent patient", `${ev.parent_patient} → ${ev.this_patient}`]);
    if (ev.parent_state) rows.push(["Parent state", ev.parent_state]);
    if (ev.foreign) rows.push(["Foreign records", ev.foreign.join(", ")]);
    if (ev.stale?.length) ev.stale.slice(0, 2).forEach((s) =>
      rows.push([`Code ${s.code}`, `memory ${s.asserted} · FHIR now ${s.current.join(", ")}`]));
    if (ev.restricted) rows.push(["Restricted", `${ev.restricted.length} field(s) in ${typeLabel(ev.role)}`]);
    if (!rows.length) return "";
    return `<dl class="sn-ev">${rows.map(([k, v]) =>
      `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl>`;
  }

  function renderSource(data) {
    const items = data.source_findings || [];
    $("sn-source-count").textContent = items.length;
    const box = $("sn-source");
    if (!items.length) {
      box.innerHTML = `<div class="sn-empty"><b>Source registry is clean.</b><span>No chart mismatches, blocked handovers or open reports.</span></div>`;
      return;
    }
    box.innerHTML = `<ul class="sn-src-list">${items.slice(0, 14).map((f) => {
      const fix = f.action && f.action.kind === "correct_source";
      const target = (f.evidence?.fhir_subject || "").replace("Patient/", "");
      return `<li class="sev-${f.severity}">
        <span class="sn-sev sev-${f.severity}">${SEV[f.severity]}</span>
        <div class="sn-src-body">
          <strong>${esc(f.rule_name)}</strong>
          <p>${esc(f.summary)}</p>
          <small>${who(f.patient_id)}${fix ? ` → ${who(target)}` : ""} · <code>${esc(f.subject)}</code></small>
        </div>
        ${fix ? `<button class="btn ghost small" type="button" data-refile="${esc(f.subject)}" data-target="${esc(target)}">Approve refile</button>` : ""}
      </li>`;
    }).join("")}</ul>${items.length > 14 ? `<p class="hint">${items.length - 14} more in Assurance → Review queue.</p>` : ""}`;
  }

  function renderContained(data) {
    const items = data.contained || [];
    const box = $("sn-contained");
    if (!items.length) {
      box.innerHTML = `<div class="sn-empty"><b>Nothing contained yet.</b><span>Approve a case, or switch on autopilot.</span></div>`;
      return;
    }
    box.innerHTML = items.map((o) => `
      <div class="sn-done ${o.safe_resume ? "is-safe" : "is-review"}">
        <div class="sn-done-top">
          <strong>${esc(o.title)}</strong>
          <span class="sn-tag">${esc(o.incident_id)}</span>
          <span class="sn-tag">${o.actor === "sentinel-autopilot" ? "autopilot" : "approved"}</span>
          <span class="sn-time">${esc(ago(o.at))}</span>
        </div>
        <div class="sn-done-stats">
          <span><b>${o.repaired}</b> rebuilt from FHIR</span>
          <span><b>${o.withdrawn ?? o.roots.length}</b> withdrawn</span>
          <span><b>${o.quarantined}</b> held for review</span>
          <span><b>${(o.waves || []).length || 1}</b> wave${(o.waves || []).length > 1 ? "s" : ""}</span>
          <span class="${o.safe_resume ? "ok" : "warn"}">${o.safe_resume ? "Safe resume approved" : "Review required"}</span>
        </div>
        <button class="sn-link" type="button" data-cert="${esc(o.incident_id)}">Show certificate</button>
        <pre class="sn-cert" id="cert-${esc(o.incident_id)}" hidden>${esc(o.certificate_text)}</pre>
      </div>`).join("");
  }

  function renderDrills(data) {
    const drills = data.drills || [];
    const box = $("sn-drills");
    if (!drills.length) { box.innerHTML = ""; return; }
    box.innerHTML = `<ul class="sn-drill-list">${drills.map((d) => {
      if (d.status !== "detected") {
        return `<li class="is-hidden"><b>${esc(d.drill_id)}</b><span>hidden · hunting…</span></li>`;
      }
      const s = d.score;
      return `<li class="is-found"><b>${esc(d.drill_id)}</b>
        <span>${esc(d.family_name)} · ${esc(d.provenance)}</span>
        <span class="sn-score"><em>${Math.round(s.recall * 100)}%</em> found ·
          ${s.seed_found ? "seed hit" : "seed missed"} · ${s.clean_flagged}/${s.clean_total} clean flagged ·
          ${esc(Math.max(0, Math.round((new Date(d.detected_at) - new Date(d.planted_at)) / 1000)))}s</span></li>`;
    }).join("")}</ul>`;
  }

  function renderDetectors(data) {
    const list = S.status?.detectors;
    if (!list) return;
    const hits = data?.hits || {};
    $("sn-detectors").innerHTML = list.map((d) => {
      const n = hits[d.id] || 0;
      const lit = n > 0 && d.id !== "provenance_gap";
      return `<div class="sn-det${lit ? " is-lit" : ""}" title="${esc(d.what)}">
        <div class="sn-det-top"><b>${esc(d.name)}</b><span>${d.id === "provenance_gap" ? `${n} gap${n === 1 ? "" : "s"}` : n}</span></div>
        <small>${esc(d.grounding)}</small>
      </div>`;
    }).join("");
  }

  function renderModel(m) {
    if (!m) return;
    const chip = $("sn-model-chip");
    chip.className = `sn-model ${m.configured ? "is-on" : ""}`;
    chip.textContent = m.configured
      ? `Gemini · ${m.calls}/${m.budget} calls`
      : "Local reasoning · no Gemini key";
  }

  function renderExamples() {
    const ex = $("sn-examples");
    const sample = S.patients.find((p) => p.name === "Rania Chowdhury") || S.patients[0];
    if (!sample) return;
    ex.innerHTML = EXAMPLES.map((e, i) =>
      `<button type="button" class="sn-chip" data-ex="${i}">${esc(e.label)}</button>`).join("");
    ex.onclick = (evt) => {
      const b = evt.target.closest("[data-ex]");
      if (!b) return;
      $("sn-report-text").value = EXAMPLES[+b.dataset.ex].text(sample.name);
      $("sn-report-text").focus();
    };
  }

  /* ---------------- actions ---------------- */
  async function containCase(caseId, btn) {
    btn.disabled = true;
    btn.innerHTML = "Containing…";
    try {
      const o = await api(`/api/sentinel/cases/${encodeURIComponent(caseId)}/contain`, { method: "POST" });
      toast(`Contained ${caseId}`, {
        detail: `${o.repaired} rebuilt from FHIR, ${o.withdrawn ?? 1} withdrawn, ${o.quarantined} held for review. ${o.safe_resume ? "Safe resume approved." : "Review required."}`,
        kind: o.safe_resume ? "good" : "", timeout: 7000 });
      S.openCase = null;
      await patrol({ quiet: true });
    } catch (e) {
      toast("Containment failed", { detail: e.message, kind: "bad" });
      btn.disabled = false;
      btn.innerHTML = "Approve containment <span>→</span>";
    }
  }

  async function refile(recordKey, target, btn) {
    const ok = window.confirm(
      `Refile ${recordKey} to ${name(target)} (${target})?\n\nThe Sentinel verified the FHIR subject. ` +
      "This records your approval in the correction log.");
    if (!ok) return;
    btn.disabled = true;
    try {
      await api("/api/registry/corrections", {
        method: "POST",
        body: JSON.stringify({ record_key: recordKey,
          note: `Sentinel verified FHIR subject Patient/${target}; refile approved from the Sentinel console.` }),
      });
      toast("Chart corrected", { detail: `${recordKey} now sits in ${name(target)}'s chart.`, kind: "good" });
      await patrol({ quiet: true });
    } catch (e) {
      btn.disabled = false;
      toast("Refile refused", { detail: e.message, kind: "bad" });
    }
  }

  async function plantDrill() {
    const btn = $("sn-drill");
    btn.disabled = true;
    try {
      const d = await api("/api/sentinel/drill", {
        method: "POST", body: JSON.stringify({ provenance: $("sn-drill-prov").value }) });
      toast(`${d.drill_id} planted`, { detail: d.message, timeout: 6000 });
      // Give the reader a beat to see the hidden drill before the hunt.
      S.last && renderDrills({ drills: [{ drill_id: d.drill_id, status: "hidden" }, ...(S.last.drills || [])] });
      setTimeout(() => patrol({ quiet: true }), 900);
    } catch (e) {
      toast("Could not plant drill", { detail: e.message, kind: "bad" });
    } finally {
      btn.disabled = false;
    }
  }

  function patientFromInput() {
    const raw = $("sn-report-patient").value.trim();
    if (!raw) return null;
    const id = raw.match(/\bS1\d{3}\b/i);
    if (id) return id[0].toUpperCase();
    const hit = S.patients.find((p) => p.name.toLowerCase() === raw.toLowerCase());
    return hit ? hit.id : null;
  }

  async function submitReport(e) {
    e.preventDefault();
    const text = $("sn-report-text").value.trim();
    if (text.length < 10) {
      toast("Add a little more detail", { detail: "At least 10 characters.", kind: "bad" });
      return;
    }
    const btn = $("sn-report-submit");
    btn.disabled = true;
    btn.innerHTML = "Triaging…";
    const out = $("sn-report-result");
    out.innerHTML = `<div class="sn-triage is-busy"><span class="sn-spinner" aria-hidden="true"></span> Reading the report, finding the patient, checking the detectors…</div>`;
    try {
      const r = await api("/api/sentinel/report", {
        method: "POST",
        body: JSON.stringify({ text, patient_id: patientFromInput() }),
      });
      renderTriage(r);
      if (r.filed) {
        $("sn-report-text").value = "";
        toast(`Report #${r.filed.id} filed`, {
          detail: r.concern_type === "assistant_memory" ? "Routed to the safety officer." : "Routed to compliance review.",
          kind: "good" });
        patrol({ quiet: true });
      }
    } catch (err) {
      out.innerHTML = `<div class="notice bad">${esc(err.message)}</div>`;
    } finally {
      btn.disabled = false;
      btn.innerHTML = "Triage &amp; file <span>→</span>";
    }
  }

  function renderTriage(r) {
    const relevant = r.corroboration.filter((f) => f.relevant);
    const others = r.corroboration.filter((f) => !f.relevant);
    const pname = r.patient_name || r.patient_id;
    $("sn-report-result").innerHTML = `
      <div class="sn-triage sev-${r.severity}">
        <div class="sn-triage-top">
          <span class="sn-sev sev-${r.severity}">${SEV[r.severity] || r.severity}</span>
          <strong>${esc(r.category_label)}</strong>
          <span class="sn-src ${r.source === "gemini" ? "is-ai" : ""}">${r.source === "gemini" ? "Gemini triage" : "Local triage"}</span>
        </div>
        ${r.summary ? `<p class="sn-triage-sum">${esc(r.summary)}</p>` : ""}
        <ol class="sn-triage-steps">${r.steps.map((s) =>
          `<li><span>${esc(PHASE[s.phase] || s.phase)}</span>${esc(s.text)}</li>`).join("")}</ol>
        <div class="sn-triage-grid">
          <div><dt>Patient</dt><dd>${r.patient_id ? `${esc(pname)} <code>${esc(r.patient_id)}</code>` :
            `<span class="warn">Not identified</span> — pick one above and resubmit`}</dd></div>
          <div><dt>Routed to</dt><dd>${r.concern_type === "assistant_memory" ? "Safety officer (memory)" : "Compliance (source record)"}</dd></div>
          <div><dt>Filed</dt><dd>${r.filed ? `Report #${r.filed.id}` : "Not yet"}</dd></div>
        </div>
        ${relevant.length ? `<div class="sn-corr"><b>Evidence the detectors already hold</b>
          <ul>${relevant.map((f) => `<li><span class="sn-sev sev-${f.severity}">${SEV[f.severity]}</span>
            ${esc(f.rule_name)} — ${esc(f.summary)}</li>`).join("")}</ul></div>`
          : r.patient_id ? `<div class="sn-corr is-none"><b>No detector corroborates this yet.</b>
            <span>That is exactly why manual reports exist: a person will review it.</span></div>` : ""}
        ${others.length ? `<p class="hint">${plural(others.length, "other open item")} for this patient.</p>` : ""}
      </div>`;
  }
})();
