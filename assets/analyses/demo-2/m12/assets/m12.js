(function () {
  "use strict";

  const HOUR_MS = 60 * 60 * 1000;
  const PAGES = new Set(["factors", "forecast", "pruning"]);
  const RESPONSIVE_BREAKPOINTS = { factors: 900, forecast: 720, pruning: 720 };
  const PRUNING_MODES = new Set(["both", "raw", "corrected"]);
  const FONT = 'ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
  const COLORS = {
    ink: "#304b5d",
    heading: "#2a4252",
    muted: "#526b7a",
    aqua: "#087f86",
    blue: "#416f9f",
    deep: "#153f68",
    orange: "#cf7800",
    red: "#a93636",
    line: "#ccdae1",
    plot: "#e5ecf6",
    paper: "#ffffff",
  };
  const FORMAT = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 4 });
  const PLOT_CONFIG = {
    responsive: true,
    displaylogo: false,
    displayModeBar: false,
    scrollZoom: false,
    doubleClick: false,
    showTips: false,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialise, { once: true });
  } else {
    initialise();
  }

  async function initialise() {
    const page = document.body && document.body.dataset.page;
    if (!PAGES.has(page)) return;

    const chart = document.getElementById("main-chart");
    const loading = document.getElementById("chart-loading");
    const error = document.getElementById("chart-error");
    const freshness = document.getElementById("freshness-status");
    const renderers = { factors: renderFactors, forecast: renderForecast, pruning: renderPruning };
    let loadingNow = false;
    let latestData = null;
    let responsiveRendering = false;
    let resizeTimer = null;
    let lastRenderedWidth = null;

    async function load(initial) {
      if (loadingNow || (!initial && document.hidden)) return;
      loadingNow = true;
      if (initial) setVisibility(loading, true);
      setVisibility(error, false);
      try {
        if (!chart) throw new Error("Le conteneur graphique principal est absent.");
        if (!window.Plotly || typeof window.Plotly.newPlot !== "function") {
          throw new Error("Le moteur graphique local n’a pas été chargé.");
        }

        const response = await fetch(`../data/${page}.json`, {
          cache: "no-store",
          credentials: "same-origin",
          headers: { Accept: "application/json" },
        });
        if (!response.ok) throw new Error(`Le fichier de données local répond avec le statut ${response.status}.`);
        let data = await response.json();
        if (!data || typeof data !== "object" || Array.isArray(data)) {
          throw new Error("Le fichier de données public ne contient pas un objet exploitable.");
        }

        if (window.M12Live && typeof window.M12Live.refresh === "function") {
          try {
            const refreshed = await window.M12Live.refresh(page, data);
            if (refreshed && typeof refreshed === "object" && !Array.isArray(refreshed)) data = refreshed;
          } catch (_refreshError) {
            if (freshness) {
              freshness.textContent = "Actualisation complémentaire indisponible ; paquet public conservé.";
              freshness.setAttribute("role", "status");
            }
          }
        }

        latestData = data;
        const status = await renderers[page](data, chart);
        lastRenderedWidth = chartViewportWidth(chart);
        updateStatus(status);
        setVisibility(loading, false);
      } catch (caught) {
        showError(caught, chart, loading, error);
      } finally {
        loadingNow = false;
      }
    }

    const scheduleResponsiveRender = () => {
      if (resizeTimer !== null) window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(async () => {
        resizeTimer = null;
        const width = chartViewportWidth(chart);
        if (!responsiveWidthChanged(lastRenderedWidth, width)) return;
        if (loadingNow || responsiveRendering || !latestData) return;
        responsiveRendering = true;
        try {
          const status = await renderers[page](latestData, chart);
          lastRenderedWidth = chartViewportWidth(chart);
          updateStatus(status);
        } catch (caught) {
          showError(caught, chart, null, error);
        } finally {
          responsiveRendering = false;
        }
      }, 120);
    };

    await load(true);
    installResponsiveObserver(chart, scheduleResponsiveRender);
    window.setInterval(() => { void load(false); }, 5 * 60 * 1000);
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) void load(false);
    });
  }

  function setVisibility(node, visible) {
    if (node) node.hidden = !visible;
  }

  function chartViewportWidth(chart) {
    if (chart && typeof chart.getBoundingClientRect === "function") {
      const width = Number(chart.getBoundingClientRect().width);
      if (Number.isFinite(width) && width > 0) return width;
    }
    const fallback = Number(window.innerWidth);
    return Number.isFinite(fallback) && fallback > 0 ? fallback : 1024;
  }

  function responsiveProfile(page, width) {
    const breakpoint = RESPONSIVE_BREAKPOINTS[page] || 720;
    return Number.isFinite(width) && width < breakpoint ? "compact" : "wide";
  }

  function responsiveWidthChanged(previousWidth, currentWidth) {
    if (!Number.isFinite(previousWidth)) return true;
    return Number.isFinite(currentWidth) && Math.abs(currentWidth - previousWidth) >= 2;
  }

  function factorPlotHeight(rowCount, compact) {
    const rows = Number.isFinite(rowCount) ? Math.max(0, rowCount) : 0;
    return Math.max(compact ? 500 : 560, rows * (compact ? 27 : 68) + 120);
  }

  function applyChartHeight(chart, height) {
    if (!chart || !chart.style || !Number.isFinite(height) || height <= 0) return;
    chart.style.height = `${Math.round(height)}px`;
  }

  function isCompactChart(chart, page) {
    return responsiveProfile(page, chartViewportWidth(chart)) === "compact";
  }

  function installResponsiveObserver(chart, callback) {
    if (!chart || typeof callback !== "function") return;
    const target = chart.parentElement || chart;
    if (typeof window.ResizeObserver === "function") {
      const observer = new window.ResizeObserver(callback);
      observer.observe(target);
      chart.__m12ResizeObserver = observer;
      return;
    }
    window.addEventListener("resize", callback, { passive: true });
    chart.__m12ResizeFallback = callback;
  }

  function updateStatus(message) {
    document.querySelectorAll(".chart-status").forEach((node) => {
      node.textContent = message || "Visualisation prête.";
      node.setAttribute("role", "status");
      node.setAttribute("aria-live", "polite");
    });
  }

  function showError(caught, chart, loading, error) {
    setVisibility(loading, false);
    const message = caught instanceof Error && caught.message
      ? caught.message
      : "Erreur non documentée.";
    if (error) {
      error.textContent = `Impossible d’afficher la visualisation. ${message}`;
      error.setAttribute("role", "alert");
      setVisibility(error, true);
    }
    if (chart) {
      chart.replaceChildren();
      const fallback = element("p", "chart-status", "Les données restent consultables dans la lecture technique lorsqu’elle est disponible.");
      fallback.setAttribute("role", "alert");
      chart.appendChild(fallback);
    }
  }

  async function renderFactors(data, chart) {
    if (typeof chart.__m12FactorsCleanup === "function") chart.__m12FactorsCleanup();
    const source = asArray(data.contrasts);
    const rows = source.map(normaliseContrast).filter(Boolean);
    if (!rows.length) throw new Error("Aucune comparaison publique exploitable n’est disponible.");

    appendFactorsTechnical(data, rows);
    ensureFactorLegend(chart);
    const previousFilter = document.getElementById("factor-question-filter")?.value;
    const toolbar = makeFactorsToolbar(chart, rows);
    let activeFilter = rows.some((row) => row.kind === previousFilter) ? previousFilter : "all";
    toolbar.select.value = activeFilter;
    let browser = null;

    const draw = async () => {
      const filtered = rows.filter((row) => activeFilter === "all" || row.kind === activeFilter);
      if (!filtered.length) throw new Error("Aucune comparaison ne correspond à cette lecture.");
      const mobile = isCompactChart(chart, "factors");
      const height = factorPlotHeight(filtered.length, mobile);
      const domain = factorDomain(filtered);
      if (mobile) {
        await renderMobileFactors(chart, filtered, domain);
        updateStatus(`${filtered.length} comparaison${filtered.length > 1 ? "s" : ""} affichée${filtered.length > 1 ? "s" : ""}; ${filtered.filter((row) => !row.estimable).length} avec plage non calculable.`);
        return;
      }
      leaveMobileFactors(chart);
      const traces = filtered.map((row, index) => factorTrace(row, index));
      const desktopLeftMargin = Math.min(300, Math.max(240, Math.round(chartViewportWidth(chart) * 0.28)));
      const layout = baseLayout({
        height,
        margin: { l: desktopLeftMargin, r: 30, t: 38, b: 76 },
      });
      layout.hovermode = "closest";
      layout.showlegend = false;
      layout.xaxis = {
        title: { text: "Réduction de l’erreur moyenne (mm)", standoff: 14 },
        range: domain,
        gridcolor: COLORS.paper,
        zeroline: true,
        zerolinecolor: COLORS.heading,
        zerolinewidth: 2,
        fixedrange: true,
      };
      layout.yaxis = {
        tickmode: "array",
        tickvals: filtered.map((_, index) => index),
        ticktext: filtered.map((row) => row.axisLabel),
        tickfont: { size: 13, color: COLORS.ink },
        automargin: false,
        autorange: "reversed",
        gridcolor: "rgba(0,0,0,0)",
        zeroline: false,
        fixedrange: true,
      };
      layout.annotations = [{
        x: 0,
        y: 1.045,
        xref: "x",
        yref: "paper",
        text: "zéro",
        showarrow: false,
        font: { size: 13, color: COLORS.heading },
      }];

      applyChartHeight(chart, height);
      await window.Plotly.react(chart, traces, layout, PLOT_CONFIG);
      chart.setAttribute("role", "img");
      chart.setAttribute("aria-label", `${filtered.length} comparaisons exploratoires. Le zéro est visible; les plages non calculables sont explicitement signalées par un losange vide.`);

      const items = filtered.map((row, curveNumber) => ({
        label: row.fullLabel,
        detail: factorDetail(row),
        curveNumber,
        pointNumber: 0,
      }));
      browser = createPointBrowser(chart, items, "Explorer les résultats");
      updateStatus(`${filtered.length} comparaison${filtered.length > 1 ? "s" : ""} affichée${filtered.length > 1 ? "s" : ""}; ${filtered.filter((row) => !row.estimable).length} avec plage non calculable.`);
    };

    toolbar.select.addEventListener("change", () => {
      activeFilter = toolbar.select.value;
      draw().catch((caught) => showError(caught, chart, null, document.getElementById("chart-error")));
    });
    chart.__m12FactorsCleanup = () => {};
    await draw();
    return `${rows.length} comparaisons publiques chargées; utilisez le sélecteur pour distinguer les deux questions prédictives.`;
  }

  async function renderMobileFactors(chart, rows, domain) {
    removePointBrowser(chart);
    const oldLabels = chart.parentNode.querySelector('.forest-labels[data-for="main-chart"]');
    if (oldLabels) oldLabels.remove();
    chart.querySelectorAll(".mobile-factor-plot").forEach((plot) => {
      try { window.Plotly.purge(plot); } catch (_ignored) { /* le nœud va être remplacé */ }
    });
    try { window.Plotly.purge(chart); } catch (_ignored) { /* première vue mobile */ }
    chart.replaceChildren();
    chart.classList.add("m12-mobile-forest");
    chart.style.height = "auto";
    chart.setAttribute("role", "group");
    chart.setAttribute("aria-label", `${rows.length} comparaisons, chacune présentée avec son libellé complet, une échelle commune et sa réduction moyenne de l’erreur.`);
    const list = element("div", "mobile-factor-list");
    chart.appendChild(list);

    const jobs = rows.map((row, index) => {
      const article = element("article", "mobile-factor-row");
      const label = element("button", "mobile-factor-label");
      label.type = "button";
      const result = row.estimable
        ? `Réduction ${format(row.gain)} mm · plage ${format(row.lower)} à ${format(row.upper)} mm · ${count(row.n)} mesures`
        : `Réduction ${format(row.gain)} mm · plage non calculable · ${count(row.n)} mesures`;
      label.replaceChildren(
        element("strong", "", `${row.family} — ${row.question}`),
        element("span", "", row.model),
        element("small", "", result),
      );
      const plot = element("div", "mobile-factor-plot");
      plot.id = `mobile-factor-plot-${index + 1}`;
      plot.setAttribute("role", "img");
      plot.setAttribute("aria-label", `${row.fullLabel}. ${factorDetail(row)}`);
      label.setAttribute("aria-controls", plot.id);
      article.append(label, plot);
      list.appendChild(article);
      const layout = baseLayout({ height: 108, margin: { l: 10, r: 10, t: 5, b: 30 } });
      layout.showlegend = false;
      layout.hovermode = "closest";
      layout.xaxis = {
        range: domain,
        tickmode: "array",
        tickvals: [domain[0], 0, domain[1]],
        ticktext: [format(domain[0]), "0", format(domain[1])],
        tickfont: { size: 13, color: COLORS.muted },
        gridcolor: COLORS.paper,
        zeroline: true,
        zerolinecolor: COLORS.heading,
        zerolinewidth: 2,
        fixedrange: true,
      };
      layout.yaxis = { range: [-0.8, 0.8], visible: false, fixedrange: true };
      const show = () => {
        try { window.Plotly.Fx.hover(plot, [{ curveNumber: 0, pointNumber: 0 }]); } catch (_ignored) { /* texte visible en repli */ }
      };
      const hide = () => {
        try { window.Plotly.Fx.unhover(plot); } catch (_ignored) { /* aucune action requise */ }
      };
      label.addEventListener("focus", show);
      label.addEventListener("pointerenter", show);
      label.addEventListener("click", show);
      label.addEventListener("blur", hide);
      label.addEventListener("pointerleave", hide);
      label.addEventListener("keydown", (event) => { if (event.key === "Escape") hide(); });
      return window.Plotly.newPlot(plot, [factorTrace(row, 0)], layout, PLOT_CONFIG);
    });
    await Promise.all(jobs);
  }

  function leaveMobileFactors(chart) {
    if (!chart.classList.contains("m12-mobile-forest")) return;
    chart.querySelectorAll(".mobile-factor-plot").forEach((plot) => {
      try { window.Plotly.purge(plot); } catch (_ignored) { /* le nœud va être remplacé */ }
    });
    chart.replaceChildren();
    chart.classList.remove("m12-mobile-forest");
    chart.style.removeProperty("height");
  }

  function removePointBrowser(chart) {
    const old = chart.parentNode.querySelector(`.point-browser[data-for="${chart.id}"]`);
    if (!old) return;
    if (typeof old.__m12Cleanup === "function") old.__m12Cleanup();
    old.remove();
  }

  function normaliseContrast(row, index) {
    if (!row || typeof row !== "object") return null;
    const gain = number(row.gain_mae_mm);
    if (gain === null) return null;
    const bounds = object(row.simultaneous_95_mm) || {};
    const lower = number(bounds.lower);
    const upper = number(bounds.upper);
    const status = text(bounds.status, "");
    const estimable = lower !== null && upper !== null && !/NON|ABSENT|UNESTIM/i.test(status);
    const estimand = text(row.estimand, "");
    const kind = /^CONDITIONAL/i.test(estimand) ? "conditional" : "marginal";
    const family = text(row.family_label, text(row.family, "Groupe de données non publié"));
    const question = text(row.estimand_label, kind === "conditional" ? "Ajout aux autres données" : "Ajout seul");
    const model = text(row.model_label, text(row.model, "Modèle non publié"));
    return {
      id: text(row.id, `comparaison-${index + 1}`),
      family,
      question,
      model,
      fullLabel: `${family} — ${question} — ${model}`,
      axisLabel: `${safe(family)}<br>${safe(question)}<br>${safe(model)}${estimable ? "" : " · ◇"}`,
      kind,
      n: number(row.n),
      gain,
      lower,
      upper,
      status,
      estimable,
      verdict: publicVerdict(row.verdict),
    };
  }

  function factorTrace(row, y) {
    const error = row.estimable ? {
      type: "data",
      symmetric: false,
      array: [Math.max(0, row.upper - row.gain)],
      arrayminus: [Math.max(0, row.gain - row.lower)],
      color: COLORS.muted,
      thickness: 1.5,
      width: 6,
    } : undefined;
    const bounds = row.estimable
      ? `${format(row.lower)} à ${format(row.upper)} mm`
      : "non estimables — aucune barre d’intervalle n’est dessinée";
    return {
      type: "scatter",
      mode: "markers",
      x: [row.gain],
      y: [y],
      name: row.fullLabel,
      customdata: [[safe(row.family), safe(row.question), safe(row.model), bounds, count(row.n), safe(row.verdict)]],
      marker: {
        size: row.estimable ? 10 : 12,
        color: row.kind === "conditional" ? COLORS.aqua : COLORS.blue,
        symbol: row.estimable ? "circle" : "diamond-open",
        line: { width: row.estimable ? 1 : 2, color: row.estimable ? COLORS.paper : COLORS.red },
      },
      error_x: error,
      hovertemplate: "<b>%{customdata[0]}</b><br>%{customdata[1]}<br>%{customdata[2]}<br>Réduction moyenne de l’erreur %{x:.4f} mm<br>Plage simultanée : %{customdata[3]}<br>Mesures évaluées : %{customdata[4]}<br>%{customdata[5]}<extra></extra>",
      showlegend: false,
      cliponaxis: false,
    };
  }

  function factorDomain(rows) {
    const values = [0];
    rows.forEach((row) => {
      values.push(row.gain);
      if (row.estimable) values.push(row.lower, row.upper);
    });
    return paddedRange(values, 0.1);
  }

  function factorDetail(row) {
    const bounds = row.estimable
      ? `plage simultanée ${format(row.lower)} à ${format(row.upper)} mm`
      : "plage simultanée non calculable";
    return `Réduction moyenne ${format(row.gain)} mm; ${bounds}; ${count(row.n)} mesures évaluées. ${row.verdict}`;
  }

  function makeFactorsToolbar(chart, rows) {
    const old = document.querySelector('[data-m12-toolbar="factors"]');
    if (old) old.remove();
    const toolbar = element("div", "chart-toolbar");
    toolbar.dataset.m12Toolbar = "factors";
    const field = element("div", "chart-filter");
    const label = element("label", "", "Type de comparaison");
    const select = document.createElement("select");
    select.id = "factor-question-filter";
    label.htmlFor = select.id;
    const choices = [
      ["all", `Toutes les comparaisons (${rows.length})`],
      ["marginal", `Ajout seul (${rows.filter((row) => row.kind === "marginal").length})`],
      ["conditional", `Ajout aux autres données (${rows.filter((row) => row.kind === "conditional").length})`],
    ];
    choices.forEach(([value, labelText]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = labelText;
      select.appendChild(option);
    });
    field.append(label, select);
    toolbar.appendChild(field);
    chart.parentNode.insertBefore(toolbar, chart);
    return { toolbar, select };
  }

  function makePruningToolbar(chart, selectedMode) {
    const old = document.querySelector('[data-m12-toolbar="pruning"]');
    if (old) old.remove();
    const toolbar = element("div", "chart-toolbar");
    toolbar.dataset.m12Toolbar = "pruning";
    const field = element("div", "chart-filter");
    const label = element("label", "", "Courbes affichées");
    const select = document.createElement("select");
    select.id = "pruning-series-filter";
    label.htmlFor = select.id;
    [
      ["both", "Les deux séries"],
      ["raw", "Mesure traitée, non corrigée"],
      ["corrected", "Correction thermique exploratoire"],
    ].forEach(([value, labelText]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = labelText;
      select.appendChild(option);
    });
    select.value = PRUNING_MODES.has(selectedMode) ? selectedMode : "both";
    field.append(label, select);
    toolbar.appendChild(field);
    chart.parentNode.insertBefore(toolbar, chart);
    return { toolbar, select };
  }

  function pruningTraceVisibility(mode) {
    if (mode === "raw") return [true, false];
    if (mode === "corrected") return [false, true];
    return [true, true];
  }

  function pruningModeLabel(mode) {
    if (mode === "raw") return "Mesure traitée, non corrigée";
    if (mode === "corrected") return "Correction thermique exploratoire";
    return "Mesure traitée, non corrigée et correction thermique exploratoire";
  }

  function ensureFactorLegend(chart) {
    const legend = chart.parentNode.querySelector(".chart-legend");
    if (!legend || legend.querySelector("[data-m12-nonestimable]")) return;
    const item = document.createElement("span");
    item.dataset.m12Nonestimable = "true";
    const symbol = element("i", "legend-nonestimable", "◇");
    symbol.setAttribute("aria-hidden", "true");
    item.append(symbol, document.createTextNode(" Losange vide : plage non calculable"));
    legend.appendChild(item);
  }

  function publicVerdict(value) {
    const source = text(value, "");
    if (/INCONCLUS/i.test(source)) return "Résultat inconclusif";
    if (/NON[_ -]?ESTIM/i.test(source)) return "Plage non calculable";
    if (/EXPLOR/i.test(source)) return "Résultat exploratoire";
    return source ? source.toLocaleLowerCase("fr-FR").replace(/^./, (letter) => letter.toLocaleUpperCase("fr-FR")) : "Résultat exploratoire";
  }

  function createForestLabels(chart, rows, browser) {
    const old = chart.parentNode.querySelector('.forest-labels[data-for="main-chart"]');
    if (old) old.remove();
    const block = element("section", "forest-labels");
    block.dataset.for = chart.id;
    block.setAttribute("aria-labelledby", `${chart.id}-labels-title`);
    const heading = element("h3", "", "Libellés complets des résultats affichés");
    heading.id = `${chart.id}-labels-title`;
    const list = document.createElement("ol");
    rows.forEach((row, index) => {
      const item = document.createElement("li");
      const button = element("button", "", row.fullLabel);
      button.type = "button";
      button.setAttribute("aria-label", `${row.fullLabel}. ${factorDetail(row)}`);
      button.setAttribute("aria-pressed", "false");
      const activate = () => {
        list.querySelectorAll("button").forEach((node) => node.setAttribute("aria-pressed", "false"));
        button.setAttribute("aria-pressed", "true");
        browser.select(index, true);
      };
      button.addEventListener("focus", activate);
      button.addEventListener("pointerenter", activate);
      button.addEventListener("click", activate);
      item.appendChild(button);
      list.appendChild(item);
    });
    block.append(heading, list);
    chart.insertAdjacentElement("afterend", block);
  }

  function appendFactorsTechnical(data, rows) {
    const target = technicalTarget();
    if (!target) return;
    const generated = generatedTechnical(target);
    generated.appendChild(element("h3", "", "Tableau exhaustif des 19 comparaisons"));
    generated.appendChild(makeTable(
      "Réductions moyennes de l’erreur et plages simultanées publiées",
      [
        ["Groupe de données", false], ["Question", false], ["Modèle", false], ["Mesures évaluées", true],
        ["Réduction moyenne (mm)", true], ["Borne basse (mm)", true], ["Borne haute (mm)", true],
        ["Statut de la plage", false], ["Résultat", false],
      ],
      rows.map((row) => [
        row.family, row.question, row.model, count(row.n), format(row.gain),
        row.estimable ? format(row.lower) : "Non calculable",
        row.estimable ? format(row.upper) : "Non calculable",
        row.estimable ? "Calculable" : "Non calculable", row.verdict,
      ]),
    ));

    const supports = asArray(data.supports);
    if (supports.length) {
      generated.appendChild(element("h3", "", "Disponibilité des données"));
      generated.appendChild(makeTable(
        "Disponibilité par groupe",
        [["Groupe de données", false], ["Mesures disponibles", true], ["Variables", false]],
        supports.map((support) => [
          text(support.family_label, text(support.family, "—")),
          count(number(support.n)),
          Array.isArray(support.variables)
            ? support.variables.map(publicVariableLabel).filter(Boolean).join(", ") || "—"
            : publicVariableLabel(support.variables),
        ]),
      ));
    }
    const global = object(data.global_test);
    const pValue = global && number(first(global.p_value, global.p, global.value));
    if (pValue !== null && pValue !== undefined) {
      const note = element("p", "takeaway");
      note.textContent = `Test global publié : p = ${format(pValue)}. Cette valeur ne démontre ni causalité ni absence d’effet.`;
      generated.appendChild(note);
    }
  }

  async function renderPruning(data, chart) {
    const source = asArray(data.comparator_series);
    const rows = source.map(normaliseComparatorRow).filter(Boolean).sort((a, b) => a.time - b.time);
    if (!rows.length) throw new Error("La série horaire publique du comparateur est absente ou inexploitable.");
    const comparator = object(data.comparator) || {};
    const unit = comparatorUnit(comparator);
    const raw = plotSeriesWithGaps(rows, "raw");
    const corrected = plotSeriesWithGaps(rows, "corrected");
    const previousMode = document.getElementById("pruning-series-filter")?.value;
    const selectedMode = PRUNING_MODES.has(previousMode) ? previousMode : "both";
    const toolbar = makePruningToolbar(chart, selectedMode);
    const mobile = isCompactChart(chart, "pruning");
    const traces = [
      {
        type: "scattergl", mode: "lines+markers", name: "Mesure traitée, non corrigée",
        x: raw.x, y: raw.y, customdata: raw.custom,
        line: { color: COLORS.blue, width: 1.4 }, marker: { color: COLORS.blue, size: mobile ? 4 : 3, opacity: 0.62 },
        hovertemplate: "<b>%{customdata[0]}</b><br>Mesure traitée, non corrigée %{y:.4f} mm<br>Température : %{customdata[1]}<br>%{customdata[2]}<extra></extra>",
        connectgaps: false,
      },
      {
        type: "scattergl", mode: "lines+markers", name: "Correction thermique exploratoire",
        x: corrected.x, y: corrected.y, customdata: corrected.custom,
        line: { color: COLORS.aqua, width: 2.4, dash: "dash" }, marker: { color: COLORS.aqua, size: mobile ? 5 : 4 },
        hovertemplate: "<b>%{customdata[0]}</b><br>Correction thermique exploratoire %{y:.4f} mm<br>Mesure traitée, non corrigée %{customdata[3]} mm<br>Température : %{customdata[1]}<br>%{customdata[2]}<extra></extra>",
        connectgaps: false,
      },
    ];
    const visibility = pruningTraceVisibility(selectedMode);
    traces.forEach((trace, index) => { trace.visible = visibility[index]; });
    const layout = baseLayout({
      height: mobile ? 500 : 555,
      margin: mobile ? { l: 56, r: 14, t: 34, b: 74 } : { l: 82, r: 30, t: 38, b: 76 },
    });
    layout.hovermode = "closest";
    layout.showlegend = false;
    layout.xaxis = {
      type: "date",
      title: { text: "Date · heure source (sans conversion)", standoff: 12 },
      tickformat: "%d/%m<br>%Y",
      nticks: mobile ? 4 : 6,
      gridcolor: COLORS.paper,
      zeroline: false,
      fixedrange: false,
      rangeslider: { visible: false },
    };
    layout.yaxis = {
      title: { text: "Déplacement relatif (mm)", standoff: mobile ? 3 : 12 },
      gridcolor: COLORS.paper,
      zerolinecolor: "#9fb2bf",
      fixedrange: false,
    };
    const intervention = object(data.intervention) || {};
    const interventionDate = text(intervention.date, "");
    if (interventionDate && parseTime(interventionDate) !== null) {
      layout.shapes = [{
        type: "line", x0: interventionDate, x1: interventionDate, xref: "x", y0: 0, y1: 1, yref: "paper",
        line: { color: COLORS.orange, width: 2, dash: "dash" },
      }];
      layout.annotations = [{
        x: interventionDate, y: 1, xref: "x", yref: "paper", text: "Intervention documentée",
        showarrow: true, arrowhead: 0, ax: 0, ay: -26, font: { color: COLORS.orange, size: 11 },
      }];
    }
    applyChartHeight(chart, layout.height);
    const browserItems = (mode) => rows.map((row) => {
      const correctedIndex = corrected.rowPointIndexes.get(row);
      const rawIndex = raw.rowPointIndexes.get(row);
      const correctedVisible = mode !== "raw";
      const rawVisible = mode !== "corrected";
      const useCorrected = correctedVisible && row.corrected !== null && correctedIndex !== undefined;
      const useRaw = rawVisible && row.raw !== null && rawIndex !== undefined;
      if (!useCorrected && !useRaw) return null;
      const correctionDetail = row.corrected === null
        ? `Correction thermique exploratoire absente (${text(row.missingReason, "motif non publié")}); `
        : `Correction thermique exploratoire ${format(row.corrected)} ${unit}; `;
      return {
        label: row.date,
        detail: `${mode === "raw" ? "" : correctionDetail}mesure traitée, non corrigée ${row.raw === null ? "non publiée" : `${format(row.raw)} ${unit}`}; température ${temperature(row.temperature)}.`,
        curveNumber: useCorrected ? 1 : 0,
        pointNumber: useCorrected ? correctedIndex : rawIndex,
      };
    }).filter(Boolean);

    const drawMode = async (mode, withBrowser) => {
      const modeVisibility = pruningTraceVisibility(mode);
      traces.forEach((trace, index) => { trace.visible = modeVisibility[index]; });
      await window.Plotly.react(chart, traces, layout, PLOT_CONFIG);
      chart.setAttribute("role", "img");
      chart.setAttribute("aria-label", `${rows.length} mesures horaires exactes du comparateur. ${pruningModeLabel(mode)}. Les valeurs corrigées absentes et les heures manquantes ne sont pas reliées.`);
      if (withBrowser) createPointBrowser(chart, browserItems(mode), "Explorer les mesures horaires au clavier");
    };

    await drawMode(selectedMode, false);
    renderInterventionStatus(chart, intervention);
    appendPruningTechnical(data, rows, comparator, unit);
    createPointBrowser(chart, browserItems(selectedMode), "Explorer les mesures horaires au clavier");
    toolbar.select.addEventListener("change", () => {
      const mode = PRUNING_MODES.has(toolbar.select.value) ? toolbar.select.value : "both";
      drawMode(mode, true)
        .then(() => updateStatus(`${pruningModeLabel(mode)} · ${rows.length} mesures horaires exactes; aucune agrégation journalière.`))
        .catch((caught) => showError(caught, chart, null, document.getElementById("chart-error")));
    });
    return `${pruningModeLabel(selectedMode)} · ${rows.length} mesures horaires exactes; ${rows.filter((row) => row.corrected === null).length} correction(s) indisponible(s); aucune agrégation journalière.`;
  }

  function normaliseComparatorRow(row) {
    if (!row || typeof row !== "object") return null;
    const date = text(first(row.date, row.datetime, row.source_datetime, row.timestamp), "");
    const timestamp = number(row.timestamp_ms);
    const time = timestamp !== null ? timestamp : parseTime(date);
    const raw = number(first(row.raw_mm, row.raw, row.value_mm));
    const corrected = number(first(row.corrected_mm, row.corrected));
    if (time === null || (raw === null && corrected === null)) return null;
    return {
      date: date || String(timestamp),
      x: timestamp !== null ? timestamp : time,
      time,
      raw,
      corrected,
      temperature: number(first(row.temperature_c, row.temperature)),
      missingReason: text(row.missing_reason, ""),
    };
  }

  function plotSeriesWithGaps(rows, key) {
    const x = [];
    const y = [];
    const custom = [];
    const rowPointIndexes = new Map();
    let previous = null;
    rows.forEach((row) => {
      if (previous !== null && row.time - previous > HOUR_MS) {
        x.push(row.x); y.push(null); custom.push(["", "", "", ""]);
      }
      const value = row[key];
      const pointIndex = x.length;
      x.push(row.x);
      y.push(value);
      custom.push([
        safe(row.date), temperature(row.temperature),
        safe(value === null ? text(row.missingReason, "Valeur indisponible") : "Valeur disponible"),
        row.raw === null ? "non publiée" : format(row.raw),
      ]);
      if (value !== null) rowPointIndexes.set(row, pointIndex);
      previous = row.time;
    });
    return { x, y, custom, rowPointIndexes };
  }

  function comparatorUnit(comparator) {
    const units = object(comparator.units);
    return text(first(units && first(units.corrected, units.raw), comparator.unit), "mm");
  }

  function renderInterventionStatus(chart, intervention) {
    const old = chart.parentNode.querySelector(".intervention-status");
    if (old) old.remove();
    const date = text(intervention.date, "");
    if (!date || parseTime(date) === null) return;
    const block = element("aside", "intervention-status");
    block.appendChild(element("h3", "", "Repère d’intervention"));
    block.appendChild(element(
      "p",
      "",
      `Intervention documentée le ${date}. La zone postérieure n’est interprétée qu’avec les observations réellement acquises.`,
    ));
    chart.insertAdjacentElement("afterend", block);
  }

  function renderProtocol(data) {
    const steps = asArray(first(data.protocol_steps, data.protocol));
    if (!steps.length) return;
    const target = document.querySelector(".intervention-status") || document.querySelector(".chart-section");
    if (!target || target.querySelector(".protocol-steps")) return;
    const list = element("ol", "protocol-steps");
    steps.forEach((step) => {
      const label = typeof step === "object" && step
        ? text(first(step.label, step.title, step.description, step.step), "")
        : text(step, "");
      if (label) list.appendChild(element("li", "", label));
    });
    if (list.children.length) target.appendChild(list);
  }

  function appendPruningTechnical(data, rows, comparator, unit) {
    const target = technicalTarget();
    if (!target) return;
    const generated = generatedTechnical(target);
    generated.appendChild(element("h3", "", "Contrat de la série affichée"));
    const period = object(comparator.period) || {};
    const counts = object(comparator.counts) || {};
    const metadata = [
      ["Période", [text(period.start, "—"), text(period.end, "—")].join(" — ")],
      ["Horloge", text(comparator.clock_label, "Horloge source")],
      ["Unité", unit],
      ["Mesures affichables", String(rows.length)],
      ["Mesures traitées, non corrigées", count(number(first(counts.raw, rows.filter((row) => row.raw !== null).length)))],
      ["Corrections thermiques exploratoires disponibles", count(number(first(counts.corrected, rows.filter((row) => row.corrected !== null).length)))],
      ["Corrections absentes", String(rows.filter((row) => row.corrected === null).length)],
    ];
    generated.appendChild(makeTable("Métadonnées publiques du comparateur", [["Champ", false], ["Valeur", false]], metadata));
    const reasons = new Map();
    rows.filter((row) => row.corrected === null).forEach((row) => {
      const reason = text(row.missingReason, "Motif non publié");
      reasons.set(reason, (reasons.get(reason) || 0) + 1);
    });
    if (reasons.size) {
      generated.appendChild(makeTable(
        "Motifs d’absence de correction",
        [["Motif", false], ["Nombre", true]],
        Array.from(reasons, ([reason, total]) => [reason, String(total)]),
      ));
    }
  }

  async function renderForecast(data, chart) {
    const unit = text(first(data.unit, data.measurement_unit), "mm");
    const observations = asArray(first(data.measurements, data.observed_measurements, data.observed))
      .map(normaliseObservation).filter(Boolean).sort((a, b) => a.time - b.time);
    const simulation = object(data.simulation) || {};
    const targets = asArray(simulation.targets)
      .map(normaliseForecastTarget).filter(Boolean).sort((a, b) => a.time - b.time);
    if (!observations.length && !targets.length) throw new Error("Aucune mesure ni cible de prévision publique n’est disponible.");
    const cutoff = text(first(simulation.data_cutoff, data.cutoff_date), "").slice(0, 10);
    const displayedObservations = observations.slice(-40);
    const result = await drawProjectionPlot(chart, displayedObservations, targets, cutoff, unit);
    renderProjectionSummary(simulation, targets);
    appendForecastTechnical(data, observations, targets, unit);
    const secondary = document.getElementById("secondary-chart");
    if (secondary) await renderHistoricalComparison(data, secondary, unit);
    createPointBrowser(chart, result.items, "Explorer les mesures et cibles au clavier");
    return `${displayedObservations.length} des ${observations.length} mesures exactes et ${targets.length} cibles d’une simulation exploratoire non annoncée à l’avance sont affichées; aucun résultat n’est recalculé.`;
  }

  function normaliseObservation(row) {
    if (!row || typeof row !== "object") return null;
    const date = text(first(row.date, row.timestamp), "");
    const value = number(first(row.value_mm, row.value, row.observed_mm));
    const time = parseTime(date);
    return time === null || value === null ? null : { date, time, x: time, value };
  }

  function normaliseForecastTarget(row) {
    if (!row || typeof row !== "object") return null;
    const date = text(first(row.date, row.target_date, row.timestamp), "");
    const value = number(first(row.value_mm, row.predicted_mm, row.prediction_mm, row.value));
    const time = parseTime(date);
    if (time === null || value === null) return null;
    return {
      date, time, x: time, value,
      lower: number(first(row.lower95_mm, row.lower_95_mm, row.lower)),
      upper: number(first(row.upper95_mm, row.upper_95_mm, row.upper)),
      lower80: number(first(row.lower80_mm, row.lower_80_mm)),
      upper80: number(first(row.upper80_mm, row.upper_80_mm)),
      horizon: text(first(row.horizon_label, row.horizon), ""),
      observed: number(first(row.observed_mm, row.actual_mm, row.actual)),
      calibrationN: number(row.calibration_n),
      selectionN: number(row.selection_n),
      model: text(row.model, ""),
      modelLabel: text(row.model_label, text(row.model, "Modèle non publié")),
      selectionMae: number(row.selection_mae_mm),
      selectionWis: number(row.selection_wis_mm),
      selectionRmse: number(row.selection_rmse_mm),
      selectionBias: number(row.selection_bias_mm),
      referenceModel: text(row.selection_reference_model, "Persistance"),
      referenceMae: number(row.selection_reference_mae_mm),
      referenceWis: number(row.selection_reference_wis_mm),
      status: "Simulation exploratoire · non annoncée à l’avance",
      observationLabel: text(row.observation_label, "Observation non disponible à cette date"),
      residual: number(row.residual_mm),
    };
  }

  function projectionDateRange(observations, targets) {
    const times = [...observations, ...targets].map((row) => row.time).filter(Number.isFinite);
    if (!times.length) return undefined;
    const firstTime = Math.min(...times);
    const lastTime = Math.max(...times);
    const padding = Math.max((lastTime - firstTime) * 0.04, 86400000);
    return [firstTime - padding, lastTime + padding];
  }

  async function drawProjectionPlot(chart, observations, targets, cutoff, unit) {
    const mobile = isCompactChart(chart, "forecast");
    const complete = targets.filter((row) => row.lower !== null && row.upper !== null);
    const traces = [];
    if (complete.length) {
      traces.push({
        type: "scatter", mode: "lines", x: complete.map((row) => row.x), y: complete.map((row) => row.upper),
        line: { width: 0 }, hoverinfo: "skip", showlegend: false, connectgaps: false,
      });
      traces.push({
        type: "scatter", mode: "lines", x: complete.map((row) => row.x), y: complete.map((row) => row.lower),
        line: { width: 0 }, fill: "tonexty", fillcolor: "rgba(207,120,0,.18)",
        name: "Plage empirique descriptive à 95 %", hoverinfo: "skip", connectgaps: false,
      });
    }
    const observedCurve = traces.length;
    traces.push({
      type: "scatter", mode: "markers", name: "Mesures exactes — 40 derniers relevés",
      x: observations.map((row) => row.x), y: observations.map((row) => row.value),
      customdata: observations.map((row) => [safe(row.date)]),
      marker: { color: COLORS.deep, size: mobile ? 7 : 6 },
      hovertemplate: "<b>%{customdata[0]}</b><br>Mesure exacte %{y:.2f} mm<extra></extra>",
    });
    const targetCurve = traces.length;
    traces.push({
      type: "scatter", mode: "lines+markers", name: "Simulation exploratoire — liaison entre horizons = guide visuel",
      x: targets.map((row) => row.x), y: targets.map((row) => row.value),
      customdata: targets.map((row) => [
        safe(row.date), row.lower === null ? "non publiée" : format(row.lower),
        row.upper === null ? "non publiée" : format(row.upper), safe(row.horizon), safe(row.modelLabel),
        count(row.calibrationN), count(row.selectionN), format(row.selectionMae), format(row.selectionWis),
        safe(row.observationLabel), row.observed === null ? "non disponible" : `${format(row.observed)} mm`,
        row.residual === null ? "non calculable" : `${format(row.residual)} mm`,
      ]),
      line: { color: COLORS.orange, width: 2.5, dash: "dash" },
      marker: { color: COLORS.orange, size: mobile ? 8 : 7, symbol: "diamond" },
      hovertemplate: "<b>%{customdata[0]} · %{customdata[3]}</b><br>Simulation %{y:.4f} mm<br>Modèle sélectionné : %{customdata[4]}<br>Plage empirique 95 % : %{customdata[1]} à %{customdata[2]} mm<br>Calibration n = %{customdata[5]} · sélection n = %{customdata[6]}<br>MAE de sélection %{customdata[7]} mm · WIS %{customdata[8]} mm<br>%{customdata[9]}<br>Mesure exacte : %{customdata[10]} · écart : %{customdata[11]}<br><b>Simulation exploratoire · non annoncée à l’avance</b><extra></extra>",
      connectgaps: false,
    });
    const layout = baseLayout({
      height: mobile ? 500 : 555,
      margin: mobile ? { l: 55, r: 14, t: 42, b: 72 } : { l: 82, r: 30, t: 42, b: 74 },
    });
    layout.hovermode = "closest";
    layout.showlegend = false;
    layout.xaxis = { type: "date", range: projectionDateRange(observations, targets), title: { text: "Date", standoff: 12 }, tickformat: "%d/%m<br>%Y", nticks: mobile ? 4 : 6, gridcolor: COLORS.paper, zeroline: false };
    layout.yaxis = { title: { text: `Écartement (${unit})`, standoff: mobile ? 3 : 12 }, gridcolor: COLORS.paper, zeroline: false };
    if (cutoff && parseTime(cutoff) !== null) {
      const observedAfterCutoff = observations.some((row) => row.time > parseTime(cutoff));
      const lastTargetTime = targets.length ? targets[targets.length - 1].time : parseTime(cutoff);
      const lastObservationTime = observations.length ? observations[observations.length - 1].time : parseTime(cutoff);
      const endTime = Math.max(lastTargetTime, lastObservationTime);
      const end = endTime;
      layout.shapes = [
        { type: "rect", x0: cutoff, x1: end, xref: "x", y0: 0, y1: 1, yref: "paper", fillcolor: "rgba(207,120,0,.08)", line: { width: 0 }, layer: "below" },
        { type: "line", x0: cutoff, x1: cutoff, xref: "x", y0: 0, y1: 1, yref: "paper", line: { color: COLORS.red, width: 2, dash: "dot" } },
      ];
      layout.annotations = [
        { x: cutoff, y: 1, xref: "x", yref: "paper", xanchor: "right", text: mobile ? `Dernière mesure · ${shortDate(cutoff)}` : `Dernière mesure utilisée · ${shortDate(cutoff)}`, showarrow: true, arrowhead: 0, ax: 0, ay: -25, font: { color: COLORS.red, size: 13 } },
        { x: 1, y: 0.04, xref: "paper", yref: "paper", xanchor: "right", text: observedAfterCutoff ? (mobile ? "Nouvelles mesures<br>Simulation inchangée" : "Mesures reçues après la dernière donnée utilisée · simulation inchangée") : (mobile ? "Zone non observée" : "Non observé dans ce jeu de données"), showarrow: false, font: { color: COLORS.muted, size: 13 } },
      ];
    }
    applyChartHeight(chart, layout.height);
    await window.Plotly.react(chart, traces, layout, PLOT_CONFIG);
    chart.setAttribute("role", "img");
    chart.setAttribute("aria-label", "Quarante dernières mesures exactes, puis trois cibles d’une simulation exploratoire non annoncée à l’avance. Chaque horizon peut utiliser un modèle distinct; la ligne entre les points est seulement un guide visuel.");
    const items = observations.map((row, pointNumber) => ({
      label: row.date, detail: `Mesure exacte ${format(row.value)} ${unit}.`, curveNumber: observedCurve, pointNumber,
    })).concat(targets.map((row, pointNumber) => ({
      label: row.date,
      detail: `${row.horizon}; ${row.modelLabel}; simulation ${format(row.value)} ${unit}; plage 95 % ${row.lower === null ? "non publiée" : format(row.lower)} à ${row.upper === null ? "non publiée" : format(row.upper)} ${unit}; ${row.observationLabel}; calibration n ${count(row.calibrationN)}.`,
      curveNumber: targetCurve, pointNumber,
    })));
    return { items };
  }

  function renderProjectionSummary(simulation, targets) {
    const target = document.getElementById("projection-summary");
    if (!target) return;
    const ruleObject = object(simulation.selection_rule);
    const rule = typeof simulation.selection_rule === "string"
      ? simulation.selection_rule
      : text(first(ruleObject && ruleObject.label, ruleObject && ruleObject.description), "12 cas comparés par MAE et WIS");
    const caveat = text(simulation.robustness_caveat, "La simulation à 14 jours utilise des données élargies ; les tests de robustesse ultérieurs n’en soutiennent pas l’apport.");
    target.replaceChildren(
      element("h3", "", "Simulation exploratoire · non annoncée à l’avance"),
      element("p", "", `Trois sélections séparées par horizon ; la liaison est seulement un guide visuel. ${caveat}`),
      definitionGrid("projection-grid", [
        ["Calcul", readableDateTime(simulation.generated_at)],
        ["Mesures arrêtées au", longDate(simulation.data_cutoff)],
        ["Règle", /12/.test(rule) ? "12 cas communs · MAE et WIS à poids égal" : rule],
      ]),
    );
  }

  async function renderHistoricalComparison(data, chart, unit) {
    const comparison = object(data.historical_comparison) || {};
    const panels = asArray(comparison.panels).map(normaliseHistoricalPanel).filter(Boolean);
    if (!panels.length) {
      chart.hidden = true;
      return;
    }
    chart.hidden = false;
    const controls = document.getElementById("historical-controls");
    const previousIndex = Number(document.getElementById("historical-horizon")?.value);
    const selectedIndex = Number.isInteger(previousIndex) && previousIndex >= 0 && previousIndex < panels.length ? previousIndex : 0;
    const select = document.createElement("select");
    select.id = "historical-horizon";
    panels.forEach((panel, index) => {
      const option = document.createElement("option");
      option.value = String(index);
      option.textContent = `${panel.horizonLabel} · ${panel.modelLabel}`;
      select.appendChild(option);
    });
    if (controls) {
      const label = element("label", "", "Horizon historique affiché");
      label.htmlFor = select.id;
      controls.replaceChildren(label, select);
    }
    select.value = String(selectedIndex);
    const draw = async (index) => {
      const panel = panels[index] || panels[0];
      await drawHistoricalPanel(chart, panel, unit);
      renderHistoricalSummary(panel);
    };
    select.addEventListener("change", () => {
      draw(Number(select.value)).catch((caught) => {
        const summary = document.getElementById("historical-summary");
        if (summary) summary.textContent = caught instanceof Error ? caught.message : "Comparaison historique indisponible.";
      });
    });
    await draw(selectedIndex);
  }

  function normaliseHistoricalPanel(panel) {
    if (!panel || typeof panel !== "object") return null;
    const rows = asArray(panel.rows).map(normaliseHistoricalRow).filter(Boolean).sort((a, b) => a.time - b.time);
    if (!rows.length) return null;
    return {
      horizon: text(panel.horizon, ""),
      horizonLabel: text(panel.horizon_label, text(panel.horizon, "Horizon")),
      selectedModel: text(panel.selected_model, ""),
      modelLabel: text(panel.model_label, text(panel.selected_model, "Modèle non publié")),
      metrics: object(panel.metrics) || {},
      persistenceMetrics: object(panel.persistence_metrics) || {},
      rows,
    };
  }

  function normaliseHistoricalRow(row) {
    if (!row || typeof row !== "object") return null;
    const date = text(first(row.target_date, row.date), "");
    const time = parseTime(date);
    const observed = number(row.observed_mm);
    const predicted = number(row.predicted_mm);
    if (time === null || observed === null || predicted === null) return null;
    const bounds95 = object(row.bounds95) || object(row.bounds_95) || {};
    return {
      date, x: time, time,
      origin: text(row.origin_utc, "Origine non publiée"),
      evaluationAt: text(row.evaluation_at_utc, ""),
      observed, predicted,
      persistence: number(row.persistence_mm),
      lower: number(first(row.lower95_mm, row.lower_95_mm, bounds95.lower)),
      upper: number(first(row.upper95_mm, row.upper_95_mm, bounds95.upper)),
      calibrationN: number(row.calibration_n),
      trainingN: number(row.training_n),
    };
  }

  async function drawHistoricalPanel(chart, panel, unit) {
    const mobile = isCompactChart(chart, "forecast");
    const complete = panel.rows.filter((row) => row.lower !== null && row.upper !== null);
    const traces = [];
    if (complete.length) {
      traces.push({ type: "scatter", mode: "lines", x: complete.map((row) => row.x), y: complete.map((row) => row.upper), line: { width: 0 }, hoverinfo: "skip", showlegend: false });
      traces.push({ type: "scatter", mode: "lines", x: complete.map((row) => row.x), y: complete.map((row) => row.lower), line: { width: 0 }, fill: "tonexty", fillcolor: "rgba(8,127,134,.14)", name: "Plage 95 % (20 essais)", hoverinfo: "skip" });
    }
    traces.push({
      type: "scatter", mode: "markers", name: "Mesure observée", x: panel.rows.map((row) => row.x), y: panel.rows.map((row) => row.observed),
      customdata: panel.rows.map((row) => [safe(row.date), safe(row.origin)]),
      marker: { color: COLORS.deep, size: mobile ? 9 : 8, symbol: "circle", line: { color: COLORS.paper, width: 1 } },
      hovertemplate: "<b>Cible %{customdata[0]}</b><br>Origine %{customdata[1]}<br>Mesure %{y:.4f} mm<extra></extra>",
    });
    const predictedCurve = traces.length;
    traces.push({
      type: "scatter", mode: "markers", name: panel.modelLabel, x: panel.rows.map((row) => row.x), y: panel.rows.map((row) => row.predicted),
      customdata: panel.rows.map((row) => [safe(row.date), safe(row.origin), count(row.calibrationN), count(row.trainingN)]),
      marker: { color: COLORS.aqua, size: mobile ? 10 : 9, symbol: "diamond", line: { color: COLORS.heading, width: 1 } },
      hovertemplate: "<b>Cible %{customdata[0]}</b><br>Origine %{customdata[1]}<br>Prévision %{y:.4f} mm<br>Calibration n = %{customdata[2]} · entraînement n = %{customdata[3]}<extra></extra>",
    });
    traces.push({
      type: "scatter", mode: "markers", name: "Persistance — référence", x: panel.rows.map((row) => row.x), y: panel.rows.map((row) => row.persistence),
      marker: { color: COLORS.orange, size: mobile ? 7 : 6, symbol: "x", line: { color: COLORS.orange, width: 1.2 } },
      hovertemplate: "<b>%{x|%d/%m/%Y}</b><br>Persistance %{y:.4f} mm<extra></extra>",
    });
    const layout = baseLayout({ height: mobile ? 470 : 520, margin: mobile ? { l: 55, r: 14, t: 42, b: 72 } : { l: 82, r: 30, t: 42, b: 74 } });
    layout.hovermode = "closest";
    layout.legend = { orientation: "h", x: 0, y: 1.08, xanchor: "left", yanchor: "bottom", font: { size: 13 }, bgcolor: "rgba(255,255,255,.88)" };
    layout.xaxis = { type: "date", title: { text: "Date cible de l’essai historique" }, tickformat: "%d/%m<br>%Y", nticks: mobile ? 4 : 6, gridcolor: COLORS.paper, zeroline: false };
    layout.yaxis = { title: { text: `Écartement (${unit})` }, gridcolor: COLORS.paper, zeroline: false };
    applyChartHeight(chart, layout.height);
    await window.Plotly.react(chart, traces, layout, PLOT_CONFIG);
    chart.setAttribute("role", "img");
    chart.setAttribute("aria-label", `${panel.rows.length} essais historiques à l’horizon ${panel.horizonLabel}; mesures, modèle ${panel.modelLabel}, référence de persistance et ${complete.length} plages à 95 %.`);
    createPointBrowser(chart, panel.rows.map((row, pointNumber) => ({
      label: row.date,
      detail: `Origine ${row.origin}; prévision ${format(row.predicted)} ${unit}; mesure ${format(row.observed)} ${unit}; persistance ${format(row.persistence)} ${unit}.`,
      curveNumber: predictedCurve,
      pointNumber,
    })), `Explorer les essais historiques · ${panel.horizonLabel}`);
  }

  function renderHistoricalSummary(panel) {
    const target = document.getElementById("historical-summary");
    if (!target) return;
    const intervalCount = panel.rows.filter((row) => row.lower !== null && row.upper !== null).length;
    const coverage = number(panel.metrics.coverage_95);
    const covered = coverage === null ? null : Math.round(coverage * intervalCount);
    const entries = [
      ["Horizon · modèle", `${panel.horizonLabel} · ${panel.modelLabel}`],
      ["MAE · modèle / persistance", `${format(number(panel.metrics.mae_mm))} / ${format(number(panel.persistenceMetrics.mae_mm))} mm`],
      ["WIS · modèle / persistance", `${format(number(panel.metrics.wis_mm))} / ${format(number(panel.persistenceMetrics.wis_mm))} mm`],
      ["Couverture 95 % · support", `${coverage === null ? "Non publiée" : `${format(coverage * 100)} % (${covered}/${intervalCount})`} · ${panel.rows.length} cibles, ${intervalCount} plages`],
    ];
    target.replaceChildren(element("h3", "", "Résultats sur les mêmes dates"), definitionGrid("historical-metrics", entries));
  }

  function appendForecastTechnical(data, observations, targets, unit) {
    const target = technicalTarget();
    if (!target) return;
    const generated = generatedTechnical(target);
    generated.appendChild(element("h3", "", "Cibles de la simulation exploratoire"));
    generated.appendChild(makeTable(
      "Simulation, modèles par horizon et plages publiées",
      [["Horizon", false], ["Date cible", false], ["Modèle", false], ["Simulation", true], ["Borne basse 95 %", true], ["Borne haute 95 %", true], ["Calibration n", true], ["Sélection n", true], ["MAE sélection", true], ["WIS sélection", true]],
      targets.map((row) => [row.horizon, row.date, row.modelLabel, `${format(row.value)} ${unit}`, row.lower === null ? "Non publiée" : format(row.lower), row.upper === null ? "Non publiée" : format(row.upper), count(row.calibrationN), count(row.selectionN), format(row.selectionMae), format(row.selectionWis)]),
    ));
    const note = element("p", "takeaway");
    const simulation = object(data.simulation) || {};
    note.textContent = `Calcul : ${readableDateTime(simulation.generated_at)}; dernière mesure utilisée : ${longDate(first(simulation.data_cutoff, data.cutoff_date))}; simulation exploratoire non annoncée à l’avance. La série complète contient ${observations.length} mesures exactes.`;
    generated.appendChild(note);
    appendMetricsTable(generated, data.metrics);
  }

  function appendMetricsTable(target, metrics) {
    let rows = asArray(metrics);
    if (!rows.length) {
      const container = object(metrics);
      rows = container ? asArray(first(container.rows, container.results, container.models)) : [];
    }
    rows = rows.filter((row) => row && typeof row === "object" && !Array.isArray(row));
    if (!rows.length) return;
    const preferred = [
      "horizon_label", "model_label", "targets", "mae_mm", "wis_mm", "interval_targets",
      "coverage80", "coverage_80", "coverage80_pct", "coverage95", "coverage_95", "coverage95_pct",
      "mean_width_80_mm", "mean_width_95_mm", "interval_n", "interval_count",
    ];
    const available = new Set(rows.flatMap((row) => Object.keys(row)));
    let keys = preferred.filter((key) => available.has(key));
    if (!keys.length) {
      keys = Array.from(available).filter((key) => !/^m\d+/i.test(key) && !/qualification|acceptance|internal/i.test(key));
    }
    if (!keys.length) return;
    target.appendChild(element("h3", "", "Comparaison historique complète des méthodes"));
    target.appendChild(makeTable(
      "Métriques historiques publiées",
      keys.map((key) => [metricLabel(key), numericMetric(key)]),
      rows.map((row) => keys.map((key) => metricValue(row[key]))),
    ));
  }

  function definitionGrid(className, entries) {
    const list = element("dl", className);
    entries.forEach(([label, value]) => {
      const item = document.createElement("div");
      item.append(element("dt", "", label), element("dd", "", text(String(value), "—")));
      list.appendChild(item);
    });
    return list;
  }

  function metricEntries(metrics, prefix) {
    const order = ["targets", "mae_mm", "wis_mm", "interval_targets", "coverage_80", "coverage_95"];
    return order
      .filter((key) => metrics[key] !== null && metrics[key] !== undefined)
      .map((key) => [`${prefix} · ${metricLabel(key)}`, metricValue(metrics[key])]);
  }

  function metricLabel(key) {
    const labels = {
      horizon_label: "Horizon",
      model_label: "Modèle",
      n: "Effectif",
      evaluation_n: "Effectif évalué",
      targets: "Cibles physiques",
      mae_mm: "MAE (mm)",
      rmse_mm: "RMSE (mm)",
      bias_mm: "Biais (mm)",
      wis_mm: "WIS (mm)",
      coverage80: "Couverture 80 %",
      coverage_80: "Couverture 80 %",
      coverage80_pct: "Couverture 80 %",
      coverage95: "Couverture 95 %",
      coverage_95: "Couverture 95 %",
      coverage95_pct: "Couverture 95 %",
      interval_n: "Plages disponibles",
      interval_count: "Plages disponibles",
      interval_targets: "Plages disponibles",
      mean_width_80_mm: "Largeur moyenne 80 % (mm)",
      mean_width_95_mm: "Largeur moyenne 95 % (mm)",
    };
    return labels[key] || key.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
  }

  function numericMetric(key) {
    return !/label|model|horizon|status/i.test(key);
  }

  function metricValue(value) {
    if (typeof value === "number" && Number.isFinite(value)) return format(value);
    if (typeof value === "boolean") return value ? "Oui" : "Non";
    return text(String(value), "—");
  }

  function shortDate(value) {
    const parsed = parseTime(value);
    if (parsed === null) return text(value, "date non publiée");
    return new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short", timeZone: "UTC" }).format(new Date(parsed));
  }

  function longDate(value) {
    const parsed = parseTime(value);
    if (parsed === null) return text(value, "Date non publiée");
    return new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" }).format(new Date(parsed));
  }

  function readableDateTime(value) {
    const parsed = parseTime(value);
    if (parsed === null) return text(value, "Date non publiée");
    const instant = new Date(parsed);
    const date = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" }).format(instant);
    const utc = new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "UTC" }).format(instant).replace(":", " h ");
    const paris = new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Europe/Paris" }).format(instant).replace(":", " h ");
    return `${date} · ${utc} UTC (${paris} à Paris)`;
  }

  function baseLayout(options) {
    return {
      autosize: true,
      height: options.height,
      margin: options.margin,
      separators: ", ",
      paper_bgcolor: COLORS.paper,
      plot_bgcolor: COLORS.plot,
      font: { family: FONT, size: 13, color: COLORS.ink },
      hoverlabel: {
        bgcolor: COLORS.paper,
        bordercolor: "#8da4b3",
        font: { family: FONT, size: 13, color: COLORS.ink },
        align: "left",
        namelength: -1,
      },
    };
  }

  function createPointBrowser(chart, items, title) {
    const selector = `.point-browser[data-for="${chart.id}"]`;
    const old = chart.parentNode.querySelector(selector);
    if (old) {
      if (typeof old.__m12Cleanup === "function") old.__m12Cleanup();
      old.remove();
    }
    const block = element("section", "point-browser");
    block.dataset.for = chart.id;
    const heading = element("h3", "", title);
    const controls = element("div", "point-browser__controls");
    const previous = element("button", "point-browser__previous", "‹");
    const current = element("button", "point-browser__value");
    const next = element("button", "point-browser__next", "›");
    previous.type = current.type = next.type = "button";
    previous.setAttribute("aria-label", "Valeur précédente");
    next.setAttribute("aria-label", "Valeur suivante");
    current.setAttribute("aria-label", "Afficher la valeur sélectionnée sur le graphique");
    const tooltip = element("div", "chart-tooltip");
    tooltip.id = `${chart.id}-keyboard-tooltip`;
    tooltip.setAttribute("role", "tooltip");
    tooltip.hidden = true;
    current.setAttribute("aria-describedby", tooltip.id);
    controls.append(previous, current, next);
    block.append(heading, controls, tooltip);
    chart.insertAdjacentElement("afterend", block);
    let index = 0;
    let pinned = false;

    function hoverPlot(item) {
      try {
        window.Plotly.Fx.hover(chart, [{ curveNumber: item.curveNumber, pointNumber: item.pointNumber }]);
      } catch (_ignored) {
        // L’alternative textuelle reste utilisable si Plotly ne peut pas positionner le survol.
      }
    }

    function select(nextIndex, showTooltip) {
      if (!items.length) return;
      index = (nextIndex + items.length) % items.length;
      const item = items[index];
      current.replaceChildren(
        element("strong", "", `${index + 1}/${items.length} · ${item.label}`),
        element("span", "", item.detail),
      );
      tooltip.textContent = `${item.label}. ${item.detail}`;
      tooltip.hidden = !showTooltip;
      if (showTooltip) hoverPlot(item);
    }

    function close() {
      pinned = false;
      tooltip.hidden = true;
      try { window.Plotly.Fx.unhover(chart); } catch (_ignored) { /* aucune action requise */ }
    }

    previous.addEventListener("click", () => { pinned = true; select(index - 1, true); current.focus(); });
    next.addEventListener("click", () => { pinned = true; select(index + 1, true); current.focus(); });
    current.addEventListener("focus", () => select(index, true));
    current.addEventListener("pointerenter", () => select(index, true));
    current.addEventListener("pointerleave", () => { if (!pinned && document.activeElement !== current) close(); });
    current.addEventListener("blur", () => { if (!pinned) close(); });
    current.addEventListener("click", () => { pinned = !pinned; select(index, pinned || document.activeElement === current); });
    current.addEventListener("keydown", (event) => {
      if (event.key === "ArrowLeft" || event.key === "ArrowUp") { event.preventDefault(); select(index - 1, true); }
      if (event.key === "ArrowRight" || event.key === "ArrowDown") { event.preventDefault(); select(index + 1, true); }
      if (event.key === "Home") { event.preventDefault(); select(0, true); }
      if (event.key === "End") { event.preventDefault(); select(items.length - 1, true); }
      if (event.key === "Escape") { event.preventDefault(); close(); }
    });
    const controller = new AbortController();
    document.addEventListener("pointerdown", (event) => {
      if (pinned && !block.contains(event.target)) close();
    }, { signal: controller.signal });
    block.__m12Cleanup = () => controller.abort();
    select(0, false);
    return { select, close };
  }

  function technicalTarget() {
    return document.getElementById("technical-content");
  }

  function generatedTechnical(target) {
    const old = target.querySelector(".technical-generated");
    if (old) old.remove();
    const generated = element("section", "technical-generated");
    generated.setAttribute("aria-label", "Données détaillées générées depuis le fichier public");
    target.appendChild(generated);
    return generated;
  }

  function makeTable(captionText, headers, rows) {
    const wrap = element("div", "table-wrap");
    wrap.setAttribute("tabindex", "0");
    wrap.setAttribute("role", "region");
    wrap.setAttribute("aria-label", captionText);
    const table = element("table", "data-table");
    table.appendChild(element("caption", "", captionText));
    const head = document.createElement("thead");
    const headRow = document.createElement("tr");
    headers.forEach(([label, numeric]) => {
      const cell = element("th", "", label);
      cell.scope = "col";
      if (numeric) cell.dataset.numeric = "true";
      headRow.appendChild(cell);
    });
    head.appendChild(headRow);
    const body = document.createElement("tbody");
    rows.forEach((row) => {
      const tr = document.createElement("tr");
      row.forEach((value, index) => {
        const cell = element("td", "", text(value, "—"));
        if (headers[index] && headers[index][1]) cell.dataset.numeric = "true";
        tr.appendChild(cell);
      });
      body.appendChild(tr);
    });
    table.append(head, body);
    wrap.appendChild(table);
    return wrap;
  }

  function paddedRange(values, ratio) {
    const finiteValues = values.filter((value) => Number.isFinite(value));
    const minimum = Math.min(...finiteValues);
    const maximum = Math.max(...finiteValues);
    const span = maximum - minimum || Math.max(Math.abs(maximum), 1) * 0.2;
    return [minimum - span * ratio, maximum + span * ratio];
  }

  function parseTime(value) {
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (typeof value !== "string" || !value.trim()) return null;
    const source = value.trim();
    const naiveDate = /^\d{4}-\d{2}-\d{2}$/.test(source);
    const naiveDateTime = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/.test(source);
    const parsed = Date.parse(naiveDate ? `${source}T00:00:00Z` : naiveDateTime ? `${source}Z` : source);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function number(value) {
    if (value === null || value === undefined || value === "") return null;
    const converted = Number(value);
    return Number.isFinite(converted) ? converted : null;
  }

  function object(value) {
    return value && typeof value === "object" && !Array.isArray(value) ? value : null;
  }

  function asArray(value) {
    return Array.isArray(value) ? value : [];
  }

  function first(...values) {
    return values.find((value) => value !== null && value !== undefined);
  }

  function text(value, fallback) {
    return typeof value === "string" && value.trim() ? value.trim() : (fallback === undefined ? "" : fallback);
  }

  function publicVariableLabel(value) {
    return text(value, "—").replace(/invariantes? à l[’']offset/gi, "indépendantes du décalage de niveau");
  }

  function format(value) {
    return value === null || !Number.isFinite(value) ? "—" : FORMAT.format(value);
  }

  function count(value) {
    return value === null || !Number.isFinite(value) ? "Non publié" : FORMAT.format(value);
  }

  function temperature(value) {
    return value === null || !Number.isFinite(value) ? "non publiée" : `${format(value)} °C`;
  }

  function safe(value) {
    return String(value === null || value === undefined ? "" : value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function element(tag, className, content) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (content !== undefined && content !== null) node.textContent = String(content);
    return node;
  }
})();
