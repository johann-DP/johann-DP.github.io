"use strict";

(() => {
  const DATA_URL = "../assets/data/ormevia-scenarios.json";
  const LOGO_URL = "../assets/img/logo-datapredict.png";
  const root = document.getElementById("ormevia-reader");
  const main = document.getElementById("main");
  const footer = root?.querySelector(".site-footer");

  if (!root || !main || !footer) return;

  const state = {
    data: null,
    selectedId: null,
    phase: 0,
    mobileTab: "portal",
    transitionLocked: false,
    lastTransitionAt: Number.NEGATIVE_INFINITY,
  };

  const numberFormatter = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 1 });

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function formatBytes(value) {
    if (value === null || value === undefined) return "—";
    return `${numberFormatter.format(value / 1024 ** 3)} Go`;
  }

  function formatPercent(value) {
    if (value === null || value === undefined) return "—";
    return `${numberFormatter.format(value)} %`;
  }

  function formatDuration(value) {
    if (value === null || value === undefined) return "—";
    return value >= 1000
      ? `${numberFormatter.format(value / 1000)} s`
      : `${numberFormatter.format(value)} ms`;
  }

  function brandLogo(compact = false) {
    return `<img class="brand-logo${compact ? " brand-logo--compact" : ""}" src="${LOGO_URL}" alt="datapredict" width="966" height="159">`;
  }

  function selectedScenario() {
    return state.data.scenarios.find((scenario) => scenario.id === state.selectedId)
      ?? state.data.scenarios[0];
  }

  function scenarioChooser(selectedId) {
    return `
      <div class="scenario-chooser" role="radiogroup" aria-label="Choisir le scénario à rejouer">
        ${state.data.scenarios.map((scenario) => {
          const active = scenario.id === selectedId;
          return `
            <button
              type="button"
              role="radio"
              aria-checked="${active}"
              class="scenario-choice${active ? " scenario-choice--active" : ""}"
              data-action="select-scenario"
              data-scenario="${escapeHtml(scenario.id)}"
            >
              <span class="scenario-choice__check" aria-hidden="true">${active ? "✓" : ""}</span>
              <span>
                <strong>${escapeHtml(scenario.selectorLabel)}</strong>
                <small>${escapeHtml(scenario.selectorHint)}</small>
              </span>
            </button>`;
        }).join("")}
      </div>`;
  }

  function introduction(scenario) {
    return `
      <section class="intro-shell" aria-labelledby="intro-title">
        <div class="intro-copy">
          <p class="eyebrow">Choisissez l’un des deux parcours enregistrés</p>
          <h1 id="intro-title">IA locale et traçable : traitement d’un dossier de sinistre</h1>
          <p class="intro-lead">
            Vous allez rejouer une exécution locale enregistrée. La vue métier montre ce que voit la
            Direction d’Ormévia Bâtiment ; la vue technique explique les sept traitements parcourus
            sur quatre machines. Chaque clic avance d’une seule étape.
          </p>
          ${scenarioChooser(scenario.id)}
          <div class="question-card">
            <span>Question préparée</span>
            <p>${escapeHtml(scenario.question)}</p>
          </div>
          <button class="primary-action" type="button" data-action="start">
            Démarrer la démonstration <span aria-hidden="true">→</span>
          </button>
        </div>

        <aside class="intro-proof" aria-label="Repères du parcours">
          <div class="intro-proof__header">
            <span class="status-dot" aria-hidden="true"></span>
            <span>Replay prêt</span>
            <strong>7 étapes</strong>
          </div>
          <h2>${escapeHtml(scenario.introduction.title)}</h2>
          <p>${escapeHtml(scenario.introduction.description)}</p>
          <ul class="watch-list">
            ${scenario.introduction.watch.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
          </ul>
          <div class="machine-map">
            ${scenario.machines.map((machine) => `
              <article>
                <div class="machine-number">${escapeHtml(machine.name.replace("Machine ", ""))}</div>
                <div>
                  <strong>${escapeHtml(machine.name)}</strong>
                  <span>${escapeHtml(machine.role)}</span>
                </div>
                ${machine.gpu ? "<small>GPU</small>" : ""}
              </article>`).join("")}
          </div>
          <p class="offline-note"><span aria-hidden="true">●</span> Lecture autonome : aucun backend privé ni réseau local contacté.</p>
        </aside>
      </section>`;
  }

  function portalResult(result, final) {
    if (result.abstained) {
      return `
        <section class="portal-result portal-result--abstention" aria-labelledby="portal-result-title">
          <div class="result-kicker">Abstention explicite</div>
          <h3 id="portal-result-title">Aucune réponse non étayée</h3>
          <p>${escapeHtml(result.summary)}</p>
          <div class="abstention-reason">
            <strong>Pourquoi ?</strong>
            <span>${escapeHtml(result.abstentionReason)}</span>
          </div>
          <div class="rag-stats">
            <span><strong>${result.rag.passagesExamined}</strong> passages examinés</span>
            <span><strong>${result.rag.passagesRetained}</strong> retenu</span>
            <span><strong>${result.rag.citedSources}</strong> source citée</span>
          </div>
          ${final ? '<p class="no-transmission">Aucune publication · Aucune transmission</p>' : ""}
        </section>`;
    }

    return `
      <section class="portal-result" aria-labelledby="portal-result-title">
        <div class="result-kicker">${final ? "Décision validée" : "Proposition à valider"}</div>
        <h3 id="portal-result-title">Proposition préparée</h3>
        <p>${escapeHtml(result.summary)}</p>
        <ol class="action-list">
          ${result.actions.map((action) => `<li>${escapeHtml(action)}</li>`).join("")}
        </ol>
        <div class="responsible-card">
          <span>Responsable</span>
          <strong>${escapeHtml(result.responsible)}</strong>
        </div>
        <details class="citation-details">
          <summary>${result.citations.length} sources citées</summary>
          <div class="citation-list">
            ${result.citations.map((citation) => `
              <blockquote>
                <strong>${escapeHtml(citation.label)}</strong>
                <span>${escapeHtml(citation.excerpt)}</span>
              </blockquote>`).join("")}
          </div>
        </details>
      </section>`;
  }

  function portalPanel(portal, final = false) {
    return `
      <section class="view-panel portal-panel" aria-labelledby="portal-title">
        <header class="portal-header">
          <div class="ormevia-mark" aria-hidden="true">O</div>
          <div>
            <h2 id="portal-title">Ormévia Bâtiment</h2>
            <p>Portail métier · Direction</p>
          </div>
          <span class="business-status${portal.transmissionVisible ? " business-status--success" : ""}">${escapeHtml(portal.status)}</span>
        </header>

        <div class="portal-casebar">
          <div><span>Dossier suivi</span><strong>${escapeHtml(portal.caseReference)}</strong></div>
          <span class="case-kind">Sinistre bâtiment</span>
        </div>

        <div class="portal-body">
          <section class="portal-question" aria-label="Question adressée à l’assistant local">
            <span>Assistant local du dossier</span>
            <p>${escapeHtml(portal.question)}</p>
          </section>

          <section aria-labelledby="sources-title">
            <div class="section-heading">
              <h3 id="sources-title">Éléments du dossier</h3>
              <span>${portal.inputsTreated}/${portal.inputsTotal} traités</span>
            </div>
            <div class="source-grid">
              ${portal.sourceCards.map((source) => {
                const done = source.status === "Traité";
                return `
                  <article>
                    <span class="source-icon source-icon--${done ? "done" : "pending"}" aria-hidden="true">${done ? "✓" : "·"}</span>
                    <div><strong>${escapeHtml(source.label)}</strong><small>${escapeHtml(source.kind)}</small></div>
                    <em>${escapeHtml(source.status)}</em>
                  </article>`;
              }).join("")}
            </div>
          </section>

          ${portal.resultVisible && portal.result
            ? portalResult(portal.result, final)
            : `
              <section class="portal-pending" aria-label="État du résultat">
                <div class="pending-symbol" aria-hidden="true">⌁</div>
                <div>
                  <strong>${escapeHtml(portal.status)}</strong>
                  <p>Le résultat métier n’est pas encore présenté à la Direction.</p>
                </div>
              </section>`}

          ${portal.events.length > 0 ? `
            <details class="business-history"${final ? " open" : ""}>
              <summary>Historique métier · ${portal.events.length} événements</summary>
              <ol>
                ${portal.events.map((event) => `
                  <li>
                    <span>${event.order}</span>
                    <div>
                      <strong>${escapeHtml(event.label)}</strong>
                      ${event.detail ? `<p>${escapeHtml(event.detail)}</p>` : ""}
                    </div>
                  </li>`).join("")}
              </ol>
            </details>` : ""}

          ${portal.transmissionVisible ? `
            <section class="transmission-card">
              <span aria-hidden="true">✓</span>
              <div><strong>Dossier publié et transmis</strong><p>${escapeHtml(portal.transmission)}</p></div>
            </section>` : ""}

          ${portal.employeeViewVisible ? `
            <section class="employee-view">
              <div class="section-heading"><h3>Vue transmise au salarié</h3><span>Accès limité au dossier affecté</span></div>
              <p>Résumé validé, actions confiées et pièces du dossier.</p>
              <div class="attachment-list">
                ${portal.employeeAttachments.map((attachment) => `<span>▤ ${escapeHtml(attachment)}</span>`).join("")}
              </div>
            </section>` : ""}
        </div>

        <footer class="portal-footer">Solution réalisée par <strong>datapredict</strong></footer>
      </section>`;
  }

  function metricCard(name, role, active, metric) {
    const ramPercent = metric.ramUsedBytes && metric.ramTotalBytes
      ? (metric.ramUsedBytes / metric.ramTotalBytes) * 100
      : null;

    return `
      <article class="metric-card${active ? " metric-card--active" : ""}">
        <div class="metric-card__heading">
          <span>${escapeHtml(name)}</span>
          ${active ? "<strong>Étape active</strong>" : ""}
        </div>
        <p>${escapeHtml(role)}</p>
        ${metric.available ? `
          <dl>
            <div><dt>CPU</dt><dd>${formatPercent(metric.cpuPercent)}</dd></div>
            <div><dt>RAM</dt><dd>${formatPercent(ramPercent)}</dd></div>
            <div><dt>GPU</dt><dd>${formatPercent(metric.gpuPercent)}</dd></div>
            <div><dt>VRAM</dt><dd>${formatBytes(metric.vramUsedBytes)}</dd></div>
          </dl>
          <small>${metric.sampleCount} mesure${metric.sampleCount > 1 ? "s" : ""} · ${escapeHtml(metric.networkMedium ?? "réseau non qualifié")}</small>
          ${metric.calculation ? `<span class="calculation-proof">Calcul attribué · ${escapeHtml(metric.model ?? "modèle local")}</span>` : ""}
        ` : '<span class="metric-unavailable">Pas encore de mesure à cette pause</span>'}
      </article>`;
  }

  function technicalPanel(scenario, pause) {
    const gpuProof = pause.step.gpuProof;
    return `
      <section class="view-panel technical-panel" aria-labelledby="technical-title">
        <header class="technical-header">
          <div>${brandLogo(true)}<p id="technical-title">Démonstration technique</p></div>
          <span>Replay enregistré</span>
        </header>

        <div class="technical-body">
          <section class="current-step-card">
            <div class="step-index">${String(pause.order).padStart(2, "0")}</div>
            <div>
              <span>${escapeHtml(pause.step.machine)}</span>
              <h2>${escapeHtml(pause.step.label)}</h2>
              <p>${escapeHtml(pause.step.detail ?? pause.step.explanation)}</p>
            </div>
            <div class="step-tech">
              <strong>${escapeHtml(pause.step.technology)}</strong>
              <span>${formatDuration(pause.step.durationMs)}</span>
            </div>
          </section>

          ${gpuProof ? `
            <section class="gpu-proof" aria-label="Preuve GPU enregistrée">
              <div class="gpu-proof__icon" aria-hidden="true">GPU</div>
              <div>
                <span>Preuve GPU enregistrée</span>
                <strong>${escapeHtml(gpuProof.operation)} · ${escapeHtml(gpuProof.device)}</strong>
                <p>${escapeHtml(gpuProof.model)} · ${escapeHtml(gpuProof.framework)} · ${escapeHtml(gpuProof.cuda)}</p>
              </div>
              <dl>
                <div><dt>Calculs CUDA</dt><dd>${gpuProof.calculationCount}</dd></div>
                <div><dt>Durée GPU</dt><dd>${formatDuration(gpuProof.durationMs)}</dd></div>
                <div><dt>Pic VRAM</dt><dd>${formatBytes(gpuProof.vramPeakBytes)}</dd></div>
              </dl>
            </section>` : ""}

          <section aria-labelledby="sequence-title">
            <div class="technical-section-heading"><h3 id="sequence-title">Graphe réellement parcouru</h3><span>${pause.order}/7</span></div>
            <ol class="step-timeline">
              ${scenario.steps.map((step) => {
                const stepState = step.order < pause.order ? "done" : step.order === pause.order ? "current" : "future";
                return `
                  <li class="step-timeline__item step-timeline__item--${stepState}"${stepState === "current" ? ' aria-current="step"' : ""}>
                    <span class="step-timeline__number">${stepState === "done" ? "✓" : step.order}</span>
                    <div><strong>${escapeHtml(step.label)}</strong><small>${escapeHtml(step.machine)}</small></div>
                    <em>${stepState === "done" ? "Terminée" : stepState === "current" ? "Étape observée" : "À venir"}</em>
                  </li>`;
              }).join("")}
            </ol>
          </section>

          <section aria-labelledby="machines-title">
            <div class="technical-section-heading"><h3 id="machines-title">Mesures enregistrées</h3><span>Instant de la pause</span></div>
            <div class="metrics-grid">
              ${scenario.machines.map((machine) => metricCard(
                machine.name,
                machine.role,
                machine.name === pause.step.machine,
                pause.metrics[machine.name],
              )).join("")}
            </div>
            <p class="metrics-note">Les valeurs sont des mesures observées, sans interpolation. Une mesure GPU à 0 % après calcul n’annule pas la preuve d’exécution ci-dessus.</p>
          </section>

          <section class="communication-section" aria-labelledby="communications-title">
            <div class="technical-section-heading">
              <h3 id="communications-title">Communications de l’étape</h3>
              <span>${pause.communications.length} échange${pause.communications.length > 1 ? "s" : ""}</span>
            </div>
            ${pause.communications.length > 0 ? `
              <ul>
                ${pause.communications.map((exchange) => `
                  <li>
                    <div><strong>${escapeHtml(exchange.source)}</strong><span aria-hidden="true">→</span><strong>${escapeHtml(exchange.destination)}</strong></div>
                    <p>${escapeHtml(exchange.purpose)}</p>
                    <small>${escapeHtml(exchange.service)} · ${escapeHtml(exchange.protocol)} · ${formatDuration(exchange.durationMs)}</small>
                  </li>`).join("")}
              </ul>` : `<p class="no-communication">Traitement local sur ${escapeHtml(pause.step.machine)} : aucun échange intermachine supplémentaire à cette étape.</p>`}
          </section>

          ${pause.order >= 5 ? `
            <section class="model-contract" aria-labelledby="models-title">
              <div class="technical-section-heading"><h3 id="models-title">Contrat d’exécution des modèles</h3><span>État enregistré</span></div>
              <div class="model-grid">
                ${scenario.models.map((model) => `
                  <article>
                    <strong>${escapeHtml(model.name)}</strong>
                    <span>${escapeHtml(model.role)}</span>
                    <div>
                      <small>Résident : ${model.resident ? "oui" : "non"}</small>
                      <small>Exécuté : ${model.executed ? "oui" : "non"}</small>
                      ${model.role === "Génération locale" ? `<small>Appelé : ${model.generationCalled ? "oui" : "non"}</small>` : ""}
                    </div>
                  </article>`).join("")}
              </div>
            </section>` : ""}
        </div>
      </section>`;
  }

  function technicalConclusion(scenario) {
    const integrity = scenario.integrity;
    return `
      <section class="view-panel technical-panel" aria-labelledby="technical-conclusion-title">
        <header class="technical-header">
          <div>${brandLogo(true)}<p id="technical-conclusion-title">Bilan technique</p></div>
          <span class="technical-complete">Parcours complet</span>
        </header>
        <div class="technical-body conclusion-technical">
          <div class="completion-mark" aria-hidden="true">✓</div>
          <h2>Sept étapes rejouées sans accès au backend privé</h2>
          <p>${escapeHtml(scenario.conclusion.narration)}</p>
          <div class="proof-numbers">
            <article><strong>${integrity.eventCount}</strong><span>événements ordonnés</span></article>
            <article><strong>${integrity.viewFrameCount}</strong><span>frames synchronisées</span></article>
            <article><strong>${integrity.manualClickCount}</strong><span>reprises manuelles</span></article>
            <article><strong>${scenario.conclusion.citedSourceCount}</strong><span>sources citées</span></article>
          </div>
          <section aria-labelledby="final-steps-title">
            <div class="technical-section-heading"><h3 id="final-steps-title">Chaîne exécutée</h3><span>4 machines</span></div>
            <ol class="completed-steps">
              ${scenario.steps.map((step) => `
                <li><span>✓</span><div><strong>${escapeHtml(step.label)}</strong><small>${escapeHtml(step.machine)} · ${escapeHtml(step.technology)}</small></div></li>`).join("")}
            </ol>
          </section>
          <section class="final-models" aria-labelledby="final-models-title">
            <div class="technical-section-heading"><h3 id="final-models-title">Modèles locaux</h3><span>Contrat vérifiable</span></div>
            <div class="model-grid">
              ${scenario.models.map((model) => `
                <article>
                  <strong>${escapeHtml(model.name)}</strong><span>${escapeHtml(model.role)}</span>
                  <div>
                    <small>Chargé : ${model.loaded ? "oui" : "non"}</small>
                    <small>Exécuté : ${model.executed ? "oui" : "non"}</small>
                    <small>Appelé en génération : ${model.generationCalled ? "oui" : "non"}</small>
                  </div>
                </article>`).join("")}
            </div>
          </section>
          <div class="integrity-strip">
            <span>Intégrité : <strong>${escapeHtml(integrity.status)}</strong></span>
            <span>Confidentialité : <strong>${escapeHtml(integrity.privacy)}</strong></span>
            <span>Vues synchronisées : <strong>${integrity.synchronizedViews ? "oui" : "non"}</strong></span>
            <span>Séquences manquantes : <strong>${integrity.missingSequences.length}</strong></span>
          </div>
        </div>
      </section>`;
  }

  function viewTabs() {
    return `
      <div class="view-tabs" role="tablist" aria-label="Choisir la vue sur petit écran">
        <button type="button" role="tab" aria-selected="${state.mobileTab === "portal"}" aria-controls="portal-view" data-action="mobile-tab" data-tab="portal">Vue métier</button>
        <button type="button" role="tab" aria-selected="${state.mobileTab === "technical"}" aria-controls="technical-view" data-action="mobile-tab" data-tab="technical">Vue technique</button>
      </div>`;
  }

  function playback(scenario) {
    const conclusion = state.phase === 8;
    const pause = conclusion ? null : scenario.pauses[state.phase - 1];

    return `
      <section class="playback-shell" aria-label="Lecteur de la démonstration">
        <div class="playback-topbar">
          <div><span>${escapeHtml(scenario.selectorLabel)}</span><strong>${escapeHtml(scenario.question)}</strong></div>
          <ol class="progress-dots" aria-label="Progression des sept étapes">
            ${scenario.steps.map((step) => {
              const stepState = conclusion || step.order < state.phase ? "done" : step.order === state.phase ? "current" : "future";
              return `
                <li class="progress-dot progress-dot--${stepState}"${stepState === "current" ? ' aria-current="step"' : ""}>
                  <span>${step.order}</span><small>${escapeHtml(step.label)}</small>
                </li>`;
            }).join("")}
          </ol>
        </div>
        ${viewTabs()}
        <div class="dual-view">
          <div id="portal-view" class="${state.mobileTab === "portal" ? "mobile-view-active" : "mobile-view-inactive"}" role="tabpanel">
            ${portalPanel(conclusion ? scenario.conclusion.portal : pause.portal, conclusion)}
          </div>
          <div id="technical-view" class="${state.mobileTab === "technical" ? "mobile-view-active" : "mobile-view-inactive"}" role="tabpanel">
            ${conclusion ? technicalConclusion(scenario) : technicalPanel(scenario, pause)}
          </div>
        </div>
        <div class="reader-control${conclusion ? " reader-control--conclusion" : ""}">
          <div class="reader-control__index">
            <span>${conclusion ? "Bilan" : `Étape ${state.phase} sur 7`}</span>
            <strong>${conclusion ? "Parcours terminé" : escapeHtml(pause.step.label)}</strong>
          </div>
          <div class="reader-control__copy">
            <h2 id="reader-phase-heading" tabindex="-1">${conclusion ? "Ce que démontre cette exécution" : escapeHtml(pause.headline)}</h2>
            <p>${conclusion ? escapeHtml(scenario.conclusion.narration) : escapeHtml(pause.narration)}</p>
          </div>
          ${conclusion ? `
            <div class="conclusion-actions">
              <button class="primary-action" type="button" data-action="restart">Recommencer</button>
              <button class="secondary-action" type="button" data-action="change-scenario">Changer de scénario</button>
            </div>` : `
            <button class="primary-action" type="button" data-action="continue">Continuer <span aria-hidden="true">→</span></button>`}
        </div>
        <p class="sr-only" aria-live="polite">${conclusion ? "Parcours terminé" : `Étape ${state.phase} sur 7 : ${escapeHtml(pause.step.label)}`}</p>
      </section>`;
  }

  function provenance(scenario) {
    return `
      <details class="provenance-details">
        <summary>Détails de provenance</summary>
        <div>
          <p>${escapeHtml(state.data.publicProvenance)}</p>
          <dl>
            <div><dt>Scénario</dt><dd>${escapeHtml(scenario.selectorLabel)}</dd></div>
            <div><dt>Classification</dt><dd>${escapeHtml(scenario.provenance.classification)} · non canonique</dd></div>
            <div><dt>Paquet utilisé</dt><dd>${escapeHtml(scenario.provenance.sourceArtifact)}</dd></div>
            <div><dt>SHA-256</dt><dd>${escapeHtml(scenario.provenance.sourceSha256)}</dd></div>
            <div><dt>Capture brute</dt><dd>${escapeHtml(scenario.provenance.rawArtifact)}</dd></div>
            <div><dt>SHA-256 brut</dt><dd>${escapeHtml(scenario.provenance.rawSha256)}</dd></div>
            <div><dt>Commit déclaré</dt><dd>${escapeHtml(scenario.provenance.gitSha)}</dd></div>
            <div><dt>Événements</dt><dd>${scenario.integrity.eventCount}, sans trou de séquence</dd></div>
          </dl>
        </div>
      </details>`;
  }

  function render({ focusPhase = false } = {}) {
    const scenario = selectedScenario();
    main.innerHTML = state.phase === 0 ? introduction(scenario) : playback(scenario);
    footer.innerHTML = `
      <div>
        ${brandLogo(true)}
        <div class="footer-copy">
          <p>Replay TEST · Exécution enregistrée le 18 août 2026 · Corrections éditoriales postérieures à la capture</p>
          <nav class="demo-footer-links" aria-label="Liens de fin de démonstration">
            <a href="../demonstrations.html">Toutes les démonstrations</a>
            <a href="../offres.html">Offres</a>
            <a href="../contact.html">Contact</a>
          </nav>
        </div>
      </div>
      ${provenance(scenario)}`;
    root.setAttribute("aria-busy", "false");

    if (focusPhase) {
      document.getElementById("reader-phase-heading")?.focus({ preventScroll: true });
    }
  }

  function moveTo(nextPhase) {
    const now = performance.now();
    if (state.transitionLocked || now - state.lastTransitionAt < 500) return;

    state.transitionLocked = true;
    state.lastTransitionAt = now;
    state.phase = Math.max(0, Math.min(nextPhase, 8));
    state.mobileTab = "portal";
    render({ focusPhase: state.phase > 0 });
    window.setTimeout(() => {
      state.transitionLocked = false;
    }, 500);
  }

  main.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;

    switch (button.dataset.action) {
      case "select-scenario":
        if (button.dataset.scenario && button.dataset.scenario !== state.selectedId) {
          state.selectedId = button.dataset.scenario;
          state.phase = 0;
          state.mobileTab = "portal";
          render();
        }
        break;
      case "start":
        moveTo(1);
        break;
      case "continue":
        moveTo(state.phase + 1);
        break;
      case "restart":
      case "change-scenario":
        moveTo(0);
        break;
      case "mobile-tab":
        if (button.dataset.tab === "portal" || button.dataset.tab === "technical") {
          state.mobileTab = button.dataset.tab;
          render();
          document.querySelector(`button[data-tab="${state.mobileTab}"]`)?.focus();
        }
        break;
      default:
        break;
    }
  });

  main.addEventListener("dblclick", (event) => {
    if (event.target.closest("button[data-action]")) event.preventDefault();
  });

  fetch(DATA_URL, { credentials: "same-origin" })
    .then((response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    })
    .then((data) => {
      if (!Array.isArray(data.scenarios) || data.scenarios.length !== 2) {
        throw new Error("Projection publique invalide");
      }
      state.data = data;
      state.selectedId = data.scenarios[0].id;
      render();
    })
    .catch(() => {
      root.setAttribute("aria-busy", "false");
      main.innerHTML = `
        <section class="reader-error" role="alert">
          <h1>La démonstration n’a pas pu être chargée</h1>
          <p>Rechargez cette page depuis le site datapredict.org. Aucun système privé n’a été contacté.</p>
        </section>`;
    });
})();
