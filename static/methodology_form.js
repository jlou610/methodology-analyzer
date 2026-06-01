// Spec builder: accordion + dynamic rows + live validation + JSON submit.
(function () {
  "use strict";
  const form = document.getElementById("specForm");
  const specId = form.dataset.specId || "";
  const $ = (id) => document.getElementById(id);

  const splitComma = (s) => (s || "").split(",").map((x) => x.trim()).filter(Boolean);
  const joinComma = (a) => (Array.isArray(a) ? a.join(", ") : "");
  const val = (el) => (el && el.value ? el.value.trim() : "");

  // ── Accordion ──────────────────────────────────────────────────────
  form.querySelectorAll(".acc-head").forEach((btn) => {
    btn.addEventListener("click", () => btn.parentElement.classList.toggle("open"));
  });

  // ── Grading type toggle ────────────────────────────────────────────
  function syncGrading() {
    const ordinal = form.querySelector('input[name="gradingType"]:checked').value === "ordinal";
    $("gradeOrdinal").hidden = !ordinal;
    $("gradeNumeric").hidden = ordinal;
  }
  form.querySelectorAll('input[name="gradingType"]').forEach((r) =>
    r.addEventListener("change", syncGrading)
  );

  // ── Confluence label propagation ───────────────────────────────────
  function syncConfLabel() {
    const label = val($("confLabel")) || "Confluence";
    form.querySelectorAll(".conf-label").forEach((s) => (s.textContent = label));
  }
  $("confLabel").addEventListener("input", syncConfLabel);

  // ── Row builders ───────────────────────────────────────────────────
  function addContext(data) {
    const node = $("tpl-context").content.firstElementChild.cloneNode(true);
    if (data) {
      node.querySelector('[data-f="name"]').value = data.name || "";
      node.querySelector('[data-f="what"]').value = data.what_it_tells_me || "";
    }
    $("contextInputs").appendChild(node);
  }

  function addListItem(container, text) {
    const node = $("tpl-listitem").content.firstElementChild.cloneNode(true);
    if (text) node.querySelector('[data-f="text"]').value = text;
    container.appendChild(node);
    return node;
  }

  function setupCount() {
    return $("setups").querySelectorAll(".setup-card").length;
  }
  function renumberSetups() {
    $("setups").querySelectorAll(".setup-card").forEach((c, i) => {
      c.querySelector(".setup-title").textContent = "Setup " + (i + 1);
    });
    form.querySelector('[data-action="add-setup"]').disabled = setupCount() >= 5;
  }

  function addSetup(data) {
    if (setupCount() >= 5) return null;
    const node = $("tpl-setup").content.firstElementChild.cloneNode(true);
    node.querySelector(".conf-label").textContent = val($("confLabel")) || "Confluence";
    if (data) {
      const set = (f, v) => { const el = node.querySelector(`[data-f="${f}"]`); if (el) el.value = v || ""; };
      set("name", data.name); set("direction", data.direction || "long");
      set("thesis", data.thesis); set("trigger", data.trigger);
      set("invalidation", data.invalidation); set("management", data.management);
      (data.confluence || []).forEach((c) => addListItem(node.querySelector(".confluence-list"), c));
      (data.red_flags || []).forEach((r) => addListItem(node.querySelector(".redflag-list"), r));
    }
    $("setups").appendChild(node);
    renumberSetups();
    return node;
  }

  // ── Delegated add/remove ───────────────────────────────────────────
  form.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-action]");
    if (!btn) return;
    const a = btn.dataset.action;
    if (a === "add-context") addContext();
    else if (a === "add-setup") addSetup();
    else if (a === "add-hardfilter") addListItem($("hardFilters"));
    else if (a === "add-confluence") addListItem(btn.closest(".setup-card").querySelector(".confluence-list"));
    else if (a === "add-redflag") addListItem(btn.closest(".setup-card").querySelector(".redflag-list"));
    else if (a === "remove-row") btn.closest(".row").remove();
    else if (a === "remove-setup") { btn.closest(".setup-card").remove(); renumberSetups(); }
    validate();
  });

  // ── Serialize ──────────────────────────────────────────────────────
  function collectSetups() {
    const out = [];
    $("setups").querySelectorAll(".setup-card").forEach((c) => {
      const g = (f) => val(c.querySelector(`[data-f="${f}"]`));
      const list = (sel) => Array.from(c.querySelectorAll(`${sel} [data-f="text"]`)).map((i) => i.value.trim()).filter(Boolean);
      const s = {
        name: g("name"), direction: g("direction"), thesis: g("thesis"),
        trigger: g("trigger"), invalidation: g("invalidation"), management: g("management"),
        confluence: list(".confluence-list"), red_flags: list(".redflag-list"),
      };
      if (s.name || s.trigger || s.invalidation || s.thesis) out.push(s);
    });
    return out;
  }

  function buildSpec() {
    const gradingType = form.querySelector('input[name="gradingType"]:checked').value;
    const contextInputs = [];
    $("contextInputs").querySelectorAll(".context-row").forEach((r) => {
      const name = val(r.querySelector('[data-f="name"]'));
      const what = val(r.querySelector('[data-f="what"]'));
      if (name || what) contextInputs.push({ name, what_it_tells_me: what });
    });
    const hardFilters = Array.from($("hardFilters").querySelectorAll('[data-f="text"]'))
      .map((i) => i.value.trim()).filter(Boolean);

    return {
      trader: {
        name: val($("traderName")),
        style_summary: val($("styleSummary")),
        edge_thesis: val($("edgeThesis")),
        markets: splitComma(val($("markets"))),
        instruments: splitComma(val($("instruments"))),
        timeframes: { context: splitComma(val($("tfContext"))), trigger: splitComma(val($("tfTrigger"))) },
        holding_style: val($("holdingStyle")),
        workflow: val($("workflow")),
      },
      terminology: { confluence_label: val($("confLabel")) || "Confluence" },
      context_inputs: contextInputs,
      setups: collectSetups(),
      conviction_rules: {
        grading_scale: {
          type: gradingType,
          tiers: gradingType === "ordinal" ? splitComma(val($("gradeTiers"))) : [],
          range: gradingType === "numeric" ? val($("gradeRange")) : "",
          notes: val($("gradeNotes")),
        },
        high_conviction: val($("highConviction")),
        low_or_skip: val($("lowSkip")),
        hard_filters: hardFilters,
      },
      risk: { per_trade: val($("riskPer")), max_concurrent: val($("riskMax")), notes: val($("riskNotes")) },
    };
  }

  // ── Live validation ────────────────────────────────────────────────
  function validate() {
    const spec = buildSpec();
    const checks = {
      name: !!val($("mName")),
      summary: !!spec.trader.style_summary,
      setup: spec.setups.some((s) => s.trigger && s.invalidation),
      filter: spec.conviction_rules.hard_filters.length > 0,
    };
    $("ck-name").classList.toggle("ok", checks.name);
    $("ck-summary").classList.toggle("ok", checks.summary);
    $("ck-setup").classList.toggle("ok", checks.setup);
    $("ck-filter").classList.toggle("ok", checks.filter);
    $("saveBtn").disabled = !(checks.name && checks.summary && checks.setup && checks.filter);
    return checks;
  }
  form.addEventListener("input", validate);

  // ── Submit ─────────────────────────────────────────────────────────
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const errBox = $("formErrors");
    errBox.hidden = true;
    $("saveBtn").disabled = true;
    const body = JSON.stringify({ name: val($("mName")), spec: buildSpec() });
    const url = specId ? `/api/methodology/${specId}` : "/api/methodology";
    const method = specId ? "PUT" : "POST";
    try {
      const res = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body });
      const data = await res.json();
      if (res.ok && data.ok) { window.location = "/methodology"; return; }
      errBox.innerHTML = "<strong>Couldn't save:</strong><ul>" +
        (data.errors || ["Unknown error."]).map((x) => `<li>${x}</li>`).join("") + "</ul>";
      errBox.hidden = false;
      errBox.scrollIntoView({ behavior: "smooth", block: "center" });
    } catch (err) {
      errBox.textContent = "Network error — please try again.";
      errBox.hidden = false;
    } finally {
      validate();
    }
  });

  // ── Hydrate ────────────────────────────────────────────────────────
  function hydrate() {
    const spec = JSON.parse($("initial-spec").textContent || "null");
    const name = JSON.parse($("initial-name").textContent || '""');
    if (name) $("mName").value = name;
    if (spec) {
      const t = spec.trader || {};
      $("styleSummary").value = t.style_summary || "";
      $("traderName").value = t.name || "";
      $("markets").value = joinComma(t.markets);
      $("instruments").value = joinComma(t.instruments);
      $("holdingStyle").value = t.holding_style || "";
      $("tfContext").value = joinComma((t.timeframes || {}).context);
      $("tfTrigger").value = joinComma((t.timeframes || {}).trigger);
      $("workflow").value = t.workflow || "";
      $("edgeThesis").value = t.edge_thesis || "";
      $("confLabel").value = (spec.terminology || {}).confluence_label || "Confluence";
      (spec.context_inputs || []).forEach(addContext);
      (spec.setups || []).forEach(addSetup);
      const cr = spec.conviction_rules || {};
      const gs = cr.grading_scale || {};
      if (gs.type === "numeric") {
        form.querySelector('input[name="gradingType"][value="numeric"]').checked = true;
        $("gradeRange").value = gs.range || "1-10";
      } else {
        $("gradeTiers").value = joinComma(gs.tiers) || "A, B, C";
      }
      $("gradeNotes").value = gs.notes || "";
      $("highConviction").value = cr.high_conviction || "";
      $("lowSkip").value = cr.low_or_skip || "";
      (cr.hard_filters || []).forEach((f) => addListItem($("hardFilters"), f));
      const rk = spec.risk || {};
      $("riskPer").value = rk.per_trade || "";
      $("riskMax").value = rk.max_concurrent || "";
      $("riskNotes").value = rk.notes || "";
    } else {
      addContext(); addSetup(); addListItem($("hardFilters"));  // start with one of each
    }
    syncGrading(); syncConfLabel(); renumberSetups(); validate();
  }
  hydrate();
})();
