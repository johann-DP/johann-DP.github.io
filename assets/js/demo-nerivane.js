"use strict";

(() => {
  const DATA_URL = "../assets/data/nerivane-governance-replay.json";
  const root = document.getElementById("nerivane-reader");
  const headerState = document.getElementById("nerivane-public-state");

  if (!root) return;

  const allowedStatuses = new Set(["MESURÉ", "PLANIFIÉ", "BLOQUÉ", "EXÉCUTÉ_NON_VALIDÉ"]);
  const state = {
    data: null,
    started: false,
    stepIndex: 0,
    locked: false,
  };

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function statusClass(status) {
    return String(status).toLowerCase().replaceAll("é", "e").replaceAll("_", "-");
  }

  function statusBadge(status, compact = false) {
    return `<span class="proof-status proof-status--${statusClass(status)}${compact ? " proof-status--compact" : ""}">${escapeHtml(status.replaceAll("_", " "))}</span>`;
  }

  function safeHref(value) {
    const href = String(value ?? "");
    return href.startsWith("../") || href.startsWith("./") || href.startsWith("#") ? href : DATA_URL;
  }

  function assertText(value, label) {
    if (typeof value !== "string" || value.trim() === "") throw new Error(`Champ invalide : ${label}`);
  }

  function validateClaim(claim, label) {
    assertText(claim.id, `${label}.id`);
    assertText(claim.label, `${label}.label`);
    assertText(claim.value, `${label}.value`);
    if (!allowedStatuses.has(claim.status)) throw new Error(`Statut invalide : ${label}`);
    assertText(claim.scope, `${label}.scope`);
    assertText(claim.limitation, `${label}.limitation`);
    assertText(claim.proof?.label, `${label}.proof.label`);
    assertText(claim.proof?.href, `${label}.proof.href`);
    assertText(claim.proof?.sha256, `${label}.proof.sha256`);
  }

  function validateData(data) {
    assertText(data.title, "title");
    assertText(data.subtitle, "subtitle");
    if (!Array.isArray(data.steps) || data.steps.length !== 7) throw new Error("Sept étapes sont requises");
    const claimIds = new Set();
    const allClaims = [...(data.introduction?.summaryClaims ?? [])];
    data.steps.forEach((step, index) => {
      if (step.order !== index + 1) throw new Error("Ordre des étapes invalide");
      if (!allowedStatuses.has(step.status)) throw new Error("Statut d’étape invalide");
      if (!Array.isArray(step.claims) || step.claims.length === 0) throw new Error("Une étape sans assertion est interdite");
      allClaims.push(...step.claims);
    });
    allClaims.forEach((claim, index) => {
      validateClaim(claim, `claim[${index}]`);
      if (claimIds.has(claim.id)) throw new Error(`Identifiant d’assertion dupliqué : ${claim.id}`);
      claimIds.add(claim.id);
    });

    const references = [];
    data.steps.forEach((step) => {
      const visual = step.visual ?? {};
      [visual.targetClaimId, visual.finalClaimId].filter(Boolean).forEach((id) => references.push(id));
      [visual.sources, visual.nodes, visual.events].filter(Array.isArray).flat().forEach((item) => references.push(item.claimId));
      [visual.input, visual.model, visual.controls].filter(Boolean).forEach((item) => references.push(item.claimId));
    });
    (data.conclusion?.gates ?? []).forEach((gate) => references.push(gate.claimId));
    references.filter(Boolean).forEach((id) => {
      if (!claimIds.has(id)) throw new Error(`Assertion référencée absente : ${id}`);
    });
    return data;
  }

  function allClaims() {
    return [
      ...state.data.introduction.summaryClaims,
      ...state.data.steps.flatMap((step) => step.claims),
    ];
  }

  function claimById(id) {
    return allClaims().find((claim) => claim.id === id);
  }

  function referencedBadge(claimId) {
    const claim = claimById(claimId);
    return claim ? statusBadge(claim.status, true) : "";
  }

  function renderClaim(claim) {
    const href = safeHref(claim.proof.href);
    return `
      <article class="proof-card" id="preuve-${escapeHtml(claim.id)}" tabindex="-1">
        <header>
          <div>
            <p>${escapeHtml(claim.label)}</p>
            <strong>${escapeHtml(claim.value)}</strong>
          </div>
          ${statusBadge(claim.status)}
        </header>
        <dl>
          <div><dt>Périmètre</dt><dd>${escapeHtml(claim.scope)}</dd></div>
          <div>
            <dt>Preuve / empreinte</dt>
            <dd><a href="${escapeHtml(href)}">${escapeHtml(claim.proof.label)}</a><code>${escapeHtml(claim.proof.sha256)}</code></dd>
          </div>
          <div class="proof-card__limit"><dt>Ce que cela ne prouve pas</dt><dd>${escapeHtml(claim.limitation)}</dd></div>
        </dl>
      </article>`;
  }

  function renderDefinitionVisual(visual) {
    return `
      <div class="definition-grid">
        ${visual.sources.map((source) => `
          <article>
            <div class="definition-grid__topline"><span>${escapeHtml(source.name)}</span>${referencedBadge(source.claimId)}</div>
            <strong>${escapeHtml(source.definition)}</strong>
            <small>Responsable : ${escapeHtml(source.owner)}</small>
          </article>`).join("")}
      </div>
      <div class="definition-blocker"><span aria-hidden="true">×</span><strong>Aucune agrégation tant que la définition commune n’est pas arbitrée</strong></div>`;
  }

  function renderH1Visual(visual) {
    return `
      <div class="h1-comparison">
        <section>
          <header><span>Cible contractuelle</span>${referencedBadge(visual.targetClaimId)}</header>
          <div class="h1-metrics">
            ${visual.target.map((metric) => `<div><strong>${escapeHtml(metric.value)}</strong><span>${escapeHtml(metric.label)}</span></div>`).join("")}
          </div>
          <p>Projection exacte : elle fixe le test, elle n’en constitue pas le résultat.</p>
        </section>
        <div class="h1-divider" aria-hidden="true"><span>≠</span></div>
        <section class="h1-comparison__final">
          <header><span>Bilan physique scellé</span>${referencedBadge(visual.finalClaimId)}</header>
          <div class="h1-metrics">
            ${visual.final.map((metric) => `<div><strong>${escapeHtml(metric.value)}</strong><span>${escapeHtml(metric.label)}</span></div>`).join("")}
          </div>
          <p>Les valeurs resteront vides jusqu’à la convergence des reçus et des empreintes.</p>
        </section>
      </div>`;
  }

  function renderTopologyVisual(visual) {
    return `<div class="topology-grid">
      ${visual.nodes.map((node) => `
        <article class="topology-node topology-node--${escapeHtml(node.name)}">
          <header><span>${escapeHtml(node.name)}</span>${statusBadge(node.status, true)}</header>
          <h3>${escapeHtml(node.role)}</h3>
          <strong>${escapeHtml(node.storage)}</strong>
          <p>${escapeHtml(node.detail)}</p>
          <a href="#preuve-${escapeHtml(node.claimId)}">Voir le périmètre de preuve</a>
        </article>`).join("")}
    </div>`;
  }

  function renderResourcesVisual(visual) {
    return `<div class="resource-grid">
      ${visual.nodes.map((node) => `
        <article>
          <header><span>${escapeHtml(node.name)}</span>${statusBadge(node.status, true)}</header>
          <h3>${escapeHtml(node.role)}</h3>
          <div class="resource-grid__metric"><span>Mesure</span><strong>${escapeHtml(node.metric)}</strong></div>
          <div class="resource-grid__gpu"><span aria-hidden="true">GPU</span><p>${escapeHtml(node.gpu)}</p></div>
          <a href="#preuve-${escapeHtml(node.claimId)}">Examiner la limite de preuve</a>
        </article>`).join("")}
    </div>`;
  }

  function renderRecoveryVisual(visual) {
    return `<ol class="recovery-flow">
      ${visual.events.map((event, index) => `
        <li>
          <div class="recovery-flow__index">${String(index + 1).padStart(2, "0")}</div>
          <div><header><strong>${escapeHtml(event.label)}</strong>${statusBadge(event.status, true)}</header><p>${escapeHtml(event.detail)}</p></div>
          <a href="#preuve-${escapeHtml(event.claimId)}" aria-label="Voir la preuve associée à ${escapeHtml(event.label)}">→</a>
        </li>`).join("")}
    </ol>`;
  }

  function renderLineageVisual(visual) {
    return `<ol class="lineage-flow">
      ${visual.nodes.map((node, index) => `
        <li>
          <div class="lineage-flow__number">${index + 1}</div>
          <div><strong>${escapeHtml(node.label)}</strong><span>${escapeHtml(node.detail)}</span></div>
          ${statusBadge(node.status, true)}
          <a href="#preuve-${escapeHtml(node.claimId)}" aria-label="Voir la preuve associée à ${escapeHtml(node.label)}">Preuve</a>
        </li>`).join("")}
    </ol>`;
  }

  function renderAiVisual(visual) {
    const blocks = [visual.input, visual.model, visual.controls];
    return `
      <div class="ai-chain">
        ${blocks.map((block, index) => `
          <article>
            <span>${String(index + 1).padStart(2, "0")}</span>
            <strong>${escapeHtml(block.label)}</strong>
            ${statusBadge(block.status, true)}
            <a href="#preuve-${escapeHtml(block.claimId)}">Preuve</a>
          </article>
          ${index < blocks.length - 1 ? '<div class="ai-chain__arrow" aria-hidden="true">→</div>' : ""}`).join("")}
      </div>
      <div class="ai-outcomes">
        ${visual.outcomes.map((outcome) => `<article class="ai-outcome ai-outcome--${escapeHtml(outcome.tone)}"><strong>${escapeHtml(outcome.label)}</strong><span>${escapeHtml(outcome.detail)}</span></article>`).join("")}
      </div>`;
  }

  function renderVisual(step) {
    switch (step.visual.type) {
      case "definitions": return renderDefinitionVisual(step.visual);
      case "h1": return renderH1Visual(step.visual);
      case "topology": return renderTopologyVisual(step.visual);
      case "resources": return renderResourcesVisual(step.visual);
      case "recovery": return renderRecoveryVisual(step.visual);
      case "lineage": return renderLineageVisual(step.visual);
      case "ai": return renderAiVisual(step.visual);
      default: return "";
    }
  }

  function renderProgress() {
    return `<ol class="nerivane-progress" aria-label="Progression des sept décisions">
      ${state.data.steps.map((step, index) => {
        const mode = index < state.stepIndex ? "done" : index === state.stepIndex ? "current" : "future";
        return `<li class="nerivane-progress__item nerivane-progress__item--${mode}"${mode === "current" ? ' aria-current="step"' : ""}>
          <button type="button" data-action="jump" data-step="${index}"${!state.started ? " disabled" : ""}>
            <span>${mode === "done" ? "✓" : step.order}</span><small>${escapeHtml(step.title)}</small>
          </button>
        </li>`;
      }).join("")}
    </ol>`;
  }

  function renderIntroduction() {
    const intro = state.data.introduction;
    return `
      <section class="nerivane-intro" aria-labelledby="nerivane-title">
        <div class="nerivane-intro__copy">
          <p class="nerivane-eyebrow">${escapeHtml(intro.kicker)}</p>
          <h1 id="nerivane-title">${escapeHtml(intro.headline)}</h1>
          <p class="nerivane-intro__lead">${escapeHtml(intro.lead)}</p>
          <div class="nerivane-intro__actions">
            <button type="button" class="nerivane-primary" data-action="start">Démarrer le replay <span aria-hidden="true">→</span></button>
            <a href="#registre-preuves">Examiner d’abord les statuts de preuve</a>
          </div>
          <p class="nerivane-offline"><span aria-hidden="true">●</span> Replay statique : aucun calcul, aucun cloud et aucune machine privée ne sont sollicités.</p>
        </div>
        <aside class="nerivane-intro__panel" aria-labelledby="watch-title">
          <header>
            <div><span>État public</span><strong>${escapeHtml(state.data.mode.label)}</strong></div>
            ${statusBadge(state.data.mode.status)}
          </header>
          <h2 id="watch-title">Ce qu’il faut regarder</h2>
          <ul>${intro.watch.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
          <div class="nerivane-intro__rule">
            <strong>Règle de lecture</strong>
            <p>${escapeHtml(state.data.mode.limitation)}</p>
          </div>
        </aside>
      </section>
      <section class="nerivane-summary" id="registre-preuves" aria-labelledby="summary-title">
        <header><p class="nerivane-eyebrow">Trois repères avant le départ</p><h2 id="summary-title">La page refuse de confondre intention et résultat</h2></header>
        <div>${intro.summaryClaims.map(renderClaim).join("")}</div>
      </section>`;
  }

  function renderStep() {
    const step = state.data.steps[state.stepIndex];
    return `
      <section class="nerivane-playback" aria-label="Replay de gouvernance Nérivane">
        <div class="nerivane-playback__topbar">
          <div><span>Replay Nérivane Distribution</span><strong>${escapeHtml(state.data.subtitle)}</strong></div>
          ${statusBadge(step.status)}
        </div>
        ${renderProgress()}
        <div class="nerivane-stage">
          <article class="story-panel">
            <header>
              <div class="story-panel__index">${String(step.order).padStart(2, "0")}</div>
              <div><p>${escapeHtml(step.kicker)}</p><h1 id="current-step-heading" tabindex="-1">${escapeHtml(step.title)}</h1></div>
            </header>
            <section class="story-panel__question"><span>Question de gouvernance</span><strong>${escapeHtml(step.businessQuestion)}</strong></section>
            <p class="story-panel__summary">${escapeHtml(step.summary)}</p>
            <div class="story-panel__visual">${renderVisual(step)}</div>
            <section class="story-panel__decision"><span>Décision appliquée</span><p>${escapeHtml(step.decision)}</p></section>
          </article>
          <aside class="evidence-panel" aria-labelledby="evidence-title">
            <header>
              <div><p>Registre de preuve</p><h2 id="evidence-title">Ce qui est affirmé — et seulement cela</h2></div>
              <span>${step.claims.length} assertion${step.claims.length > 1 ? "s" : ""}</span>
            </header>
            <div class="evidence-panel__legend">
              ${Object.entries(state.data.statusDefinitions).map(([status, definition]) => `<details><summary>${statusBadge(status, true)}</summary><p>${escapeHtml(definition)}</p></details>`).join("")}
            </div>
            <div class="evidence-panel__claims">${step.claims.map(renderClaim).join("")}</div>
          </aside>
        </div>
        <div class="nerivane-controls">
          <div><span>Étape ${step.order} sur 7</span><strong>${escapeHtml(step.title)}</strong></div>
          <div class="nerivane-controls__buttons">
            <button type="button" class="nerivane-secondary" data-action="previous"${state.stepIndex === 0 ? " disabled" : ""}>← Précédente</button>
            ${state.stepIndex < state.data.steps.length - 1
              ? '<button type="button" class="nerivane-primary" data-action="next">Décision suivante <span aria-hidden="true">→</span></button>'
              : '<button type="button" class="nerivane-primary" data-action="conclusion">Voir le bilan <span aria-hidden="true">→</span></button>'}
          </div>
        </div>
        <p class="sr-only" aria-live="polite">Étape ${step.order} sur 7 : ${escapeHtml(step.title)}</p>
      </section>`;
  }

  function renderConclusion() {
    const conclusion = state.data.conclusion;
    return `
      <section class="nerivane-conclusion" aria-labelledby="conclusion-title">
        <div class="nerivane-conclusion__mark" aria-hidden="true">!</div>
        <p class="nerivane-eyebrow">Bilan de préparation · Gate fail-closed</p>
        <h1 id="conclusion-title" tabindex="-1">${escapeHtml(conclusion.title)}</h1>
        <p class="nerivane-conclusion__lead">${escapeHtml(conclusion.lead)}</p>
        <div class="conclusion-gates">
          ${conclusion.gates.map((gate) => `
            <article>
              ${statusBadge(gate.status)}
              <strong>${escapeHtml(gate.label)}</strong>
              <button type="button" data-action="show-claim" data-claim="${escapeHtml(gate.claimId)}">Voir l’assertion source</button>
            </article>`).join("")}
        </div>
        <div class="nerivane-conclusion__next"><strong>Suite contrôlée</strong><p>${escapeHtml(conclusion.next)}</p></div>
        <div class="nerivane-conclusion__actions">
          <button type="button" class="nerivane-primary" data-action="restart">Recommencer le replay</button>
          <a class="nerivane-secondary" href="../contact.html">Échanger avec datapredict</a>
        </div>
      </section>`;
  }

  function render({ focus = false } = {}) {
    if (!state.started) root.innerHTML = renderIntroduction();
    else if (state.stepIndex >= state.data.steps.length) root.innerHTML = renderConclusion();
    else root.innerHTML = renderStep();
    root.setAttribute("aria-busy", "false");
    if (focus) document.querySelector("#current-step-heading, #conclusion-title")?.focus({ preventScroll: true });
  }

  function transition(callback) {
    if (state.locked) return;
    state.locked = true;
    callback();
    render({ focus: true });
    window.setTimeout(() => { state.locked = false; }, 250);
  }

  root.addEventListener("click", (event) => {
    const control = event.target.closest("[data-action]");
    if (!control) return;
    const action = control.dataset.action;
    if (action === "start") transition(() => { state.started = true; state.stepIndex = 0; });
    if (action === "previous") transition(() => { state.stepIndex = Math.max(0, state.stepIndex - 1); });
    if (action === "next") transition(() => { state.stepIndex = Math.min(6, state.stepIndex + 1); });
    if (action === "conclusion") transition(() => { state.stepIndex = 7; });
    if (action === "restart") transition(() => { state.started = false; state.stepIndex = 0; });
    if (action === "show-claim") {
      const claimId = control.dataset.claim;
      const index = state.data.steps.findIndex((step) => step.claims.some((claim) => claim.id === claimId));
      if (index >= 0) {
        transition(() => { state.stepIndex = index; });
        document.getElementById(`preuve-${claimId}`)?.focus({ preventScroll: false });
      }
    }
    if (action === "jump") {
      const index = Number(control.dataset.step);
      if (Number.isInteger(index) && index >= 0 && index < 7) transition(() => { state.stepIndex = index; });
    }
  });

  root.addEventListener("keydown", (event) => {
    if (!state.started || state.stepIndex >= 7 || event.altKey || event.ctrlKey || event.metaKey) return;
    if (event.key === "ArrowLeft" && state.stepIndex > 0) {
      event.preventDefault();
      transition(() => { state.stepIndex -= 1; });
    }
    if (event.key === "ArrowRight") {
      event.preventDefault();
      transition(() => { state.stepIndex += 1; });
    }
  });

  fetch(DATA_URL, { credentials: "same-origin" })
    .then((response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    })
    .then((data) => {
      state.data = validateData(data);
      if (headerState) {
        headerState.dataset.status = statusClass(state.data.mode.status);
        headerState.innerHTML = `<span aria-hidden="true">●</span> ${escapeHtml(state.data.mode.label)}`;
      }
      render();
    })
    .catch(() => {
      root.setAttribute("aria-busy", "false");
      root.innerHTML = `
        <section class="nerivane-error" role="alert">
          <p class="nerivane-eyebrow">Replay indisponible</p>
          <h1>Le registre public n’a pas pu être chargé.</h1>
          <p>Rechargez cette page depuis datapredict.org. Aucun système privé n’a été contacté.</p>
        </section>`;
    });
})();
