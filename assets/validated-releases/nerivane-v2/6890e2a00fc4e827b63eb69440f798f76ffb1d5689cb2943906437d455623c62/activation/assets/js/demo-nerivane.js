"use strict";

(() => {
  const DATA_URL = "../assets/data/nerivane-governance-replay.json";
  const CONTRACT_ID = "DATAPREDICT-NERIVANE-ACTIVE-SITE-DATA-V2";
  const root = document.getElementById("nerivane-reader");
  const page = document.body;
  const headerState = document.getElementById("nerivane-public-state");

  if (!root || !page) return;

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = String(text);
    return node;
  }

  function setHeaderState(status, label, ariaLabel) {
    if (!headerState) return;
    const labelNode = headerState.querySelector("[data-state-label]");
    if (!labelNode) throw new Error("Libellé d’état public absent");
    headerState.dataset.status = status;
    headerState.setAttribute("aria-busy", "false");
    headerState.setAttribute("aria-label", ariaLabel);
    labelNode.textContent = label;
  }

  function requireText(value, label) {
    if (typeof value !== "string" || value.trim() === "") {
      throw new Error(`Champ public invalide : ${label}`);
    }
    return value;
  }

  function requireSha(value, label) {
    if (typeof value !== "string" || !/^[0-9a-f]{64}$/.test(value)) {
      throw new Error(`Empreinte publique invalide : ${label}`);
    }
    return value;
  }

  function validateData(data) {
    if (!data || typeof data !== "object" || Array.isArray(data)) {
      throw new Error("Registre public absent");
    }
    if (
      data.contract_id !== CONTRACT_ID ||
      data.format_version !== "2.0.0" ||
      data.fictional_scenario !== true ||
      data.status !== "ACTIVE_REPLAY_AVAILABLE"
    ) {
      throw new Error("Contrat public inattendu");
    }

    const releaseId = requireText(page.dataset.releaseId, "release_id");
    if (!/^[0-9a-f]{64}$/.test(releaseId)) {
      throw new Error("Identifiant de release invalide");
    }
    const releaseRoot = `../assets/validated-releases/nerivane-v2/${releaseId}`;
    if (data.release_reference !== releaseRoot) {
      throw new Error("Référence de release divergente");
    }

    requireText(data.title, "title");
    requireText(data.subtitle, "subtitle");
    if (!Array.isArray(data.metrics) || data.metrics.length !== 4) {
      throw new Error("Quatre métriques publiques sont requises");
    }
    data.metrics.forEach((metric, index) => {
      requireText(metric.label, `metrics[${index}].label`);
      requireText(metric.value, `metrics[${index}].value`);
      requireText(metric.scope, `metrics[${index}].scope`);
    });

    if (!Array.isArray(data.steps) || data.steps.length !== 7) {
      throw new Error("Sept étapes publiques sont requises");
    }
    const identifiers = new Set();
    data.steps.forEach((step, index) => {
      if (step.order !== index + 1) throw new Error("Ordre des étapes invalide");
      requireText(step.id, `steps[${index}].id`);
      if (identifiers.has(step.id)) throw new Error("Identifiant d’étape dupliqué");
      identifiers.add(step.id);
      requireText(step.title, `steps[${index}].title`);
      requireText(step.problem, `steps[${index}].problem`);
      requireText(step.action, `steps[${index}].action`);
      requireText(step.proof, `steps[${index}].proof`);
      requireText(step.limitation, `steps[${index}].limitation`);
      if (!new Set(["VALIDÉ", "VALIDÉ_FAIL_CLOSED"]).has(step.status)) {
        throw new Error("Statut d’étape invalide");
      }
      const expectedHref = `${releaseRoot}/steps/${String(index + 1).padStart(2, "0")}.html`;
      if (step.href !== expectedHref) throw new Error("Lien d’étape invalide");
    });

    if (!Array.isArray(data.evidence) || data.evidence.length !== 5) {
      throw new Error("Cinq preuves publiques sont requises");
    }
    const expectedEvidence = [
      ["replay-v2", "replay-manifest.json"],
      ["full-h1", "evidence/full-h1-final-public.json"],
      ["park-resources", "evidence/resource-windows/manifest.json"],
      ["sample-controls", "evidence/bigquery-h1-sample-public.json"],
      ["ai-fail-closed", "evidence/ai-local-fail-closed.json"],
    ];
    data.evidence.forEach((proof, index) => {
      const [expectedId, expectedPath] = expectedEvidence[index];
      if (proof.id !== expectedId) throw new Error("Identifiant de preuve invalide");
      requireText(proof.label, `evidence[${index}].label`);
      requireSha(proof.sha256, `evidence[${index}].sha256`);
      if (proof.href !== `${releaseRoot}/${expectedPath}`) {
        throw new Error("Lien de preuve hors release");
      }
    });

    if (!Array.isArray(data.boundaries) || data.boundaries.length !== 3) {
      throw new Error("Trois frontières de preuve sont requises");
    }
    data.boundaries.forEach((boundary, index) => {
      requireText(boundary.title, `boundaries[${index}].title`);
      requireText(boundary.text, `boundaries[${index}].text`);
    });
    return data;
  }

  function renderMetric(metric) {
    const card = element("article", "nerivane-metric");
    card.append(element("span", "", metric.label));
    card.append(element("strong", "", metric.value));
    card.append(element("span", "", metric.scope));
    return card;
  }

  function renderStep(step) {
    const item = element("li", "nerivane-step");
    item.id = `parcours-${step.id}`;

    item.append(element("span", "nerivane-step__number", String(step.order).padStart(2, "0")));

    const body = element("div", "nerivane-step__body");
    body.append(element("h3", "", step.title));
    body.append(element("p", "", step.problem));
    const proof = element("div", "nerivane-step__proof");
    proof.append(element("strong", "", `Action datapredict — ${step.action}`));
    proof.append(element("span", "", `Preuve — ${step.proof}`));
    proof.append(element("small", "", `Limite — ${step.limitation}`));
    body.append(proof);
    item.append(body);

    const side = element("div", "nerivane-step__link");
    const badgeClass = step.status === "VALIDÉ_FAIL_CLOSED"
      ? "nerivane-status nerivane-status--fail-closed"
      : "nerivane-status";
    side.append(element("span", badgeClass, step.status.replaceAll("_", " ")));
    const link = element("a", "nerivane-secondary", "Examiner la preuve");
    link.href = step.href;
    side.append(link);
    item.append(side);
    return item;
  }

  function renderBoundary(boundary) {
    const card = element("article", "nerivane-boundary");
    card.append(element("strong", "", boundary.title));
    card.append(element("p", "", boundary.text));
    return card;
  }

  function render(data) {
    const fragment = document.createDocumentFragment();
    const heading = element("header", "nerivane-section-heading");
    const headingCopy = element("div", "");
    headingCopy.append(element("p", "nerivane-eyebrow", "Résultats vérifiés"));
    headingCopy.append(element("h2", "", data.title));
    heading.append(headingCopy);
    heading.append(element("p", "", data.subtitle));
    fragment.append(heading);

    const metrics = element("section", "nerivane-metrics");
    metrics.setAttribute("aria-label", "Mesures vérifiées");
    data.metrics.forEach((metric) => metrics.append(renderMetric(metric)));
    fragment.append(metrics);

    const journeyHeading = element("header", "nerivane-section-heading");
    const journeyCopy = element("div", "");
    journeyCopy.append(element("p", "nerivane-eyebrow", "Pour aller plus loin"));
    journeyCopy.append(element("h2", "", "Sept décisions, chacune reliée à sa preuve"));
    journeyHeading.append(journeyCopy);
    fragment.append(journeyHeading);

    const journey = element("ol", "nerivane-journey");
    journey.id = "parcours";
    data.steps.forEach((step) => journey.append(renderStep(step)));
    fragment.append(journey);

    const boundaries = element("section", "nerivane-boundaries");
    boundaries.setAttribute("aria-label", "Frontières de la démonstration");
    data.boundaries.forEach((boundary) => boundaries.append(renderBoundary(boundary)));
    fragment.append(boundaries);

    root.replaceChildren(fragment);
    root.setAttribute("aria-busy", "false");
    setHeaderState("valide", "Replay scellé", "Replay authentifié et scellé");
  }

  function renderError() {
    const error = element("section", "nerivane-error");
    error.append(element("p", "nerivane-eyebrow", "Protection fail-closed"));
    error.append(element("h2", "", "Le registre public ne peut pas être authentifié"));
    error.append(element("p", "", "Le parcours reste fermé plutôt que d’afficher une conclusion non vérifiée. Le replay technique scellé demeure accessible depuis le lien d’introduction."));
    root.replaceChildren(error);
    root.setAttribute("aria-busy", "false");
    setHeaderState(
      "indisponible",
      "Indisponible / non authentifié",
      "Replay public indisponible ou non authentifié",
    );
  }

  fetch(DATA_URL, { credentials: "same-origin", cache: "no-cache" })
    .then((response) => {
      if (!response.ok) throw new Error("Registre public indisponible");
      return response.json();
    })
    .then(validateData)
    .then(render)
    .catch(renderError);
})();
