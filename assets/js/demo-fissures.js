(() => {
  "use strict";

  const SVG_NS = ["http:", "", "www.w3.org", "2000", "svg"].join("/");
  const replay = globalThis.STRUCTURAL_REPLAY_DATA;

  const text = (value, fallback = "UNKNOWN") => {
    if (value === null || value === undefined || value === "") {
      return fallback;
    }
    return String(value);
  };

  const yesNo = (value) => {
    if (value === true) {
      return "OUI";
    }
    if (value === false) {
      return "NON";
    }
    return text(value);
  };

  const element = (tagName, className, content) => {
    const node = document.createElement(tagName);
    if (className) {
      node.className = className;
    }
    if (content !== undefined) {
      node.textContent = text(content);
    }
    return node;
  };

  const svgElement = (tagName, attributes = {}) => {
    const node = document.createElementNS(SVG_NS, tagName);
    Object.entries(attributes).forEach(([name, value]) => {
      node.setAttribute(name, String(value));
    });
    return node;
  };

  const addDefinition = (list, label, value, valueClass = "") => {
    const row = document.createElement("div");
    const term = element("dt", "", label);
    const definition = element("dd", valueClass, value);
    row.append(term, definition);
    list.append(row);
  };

  const addListItems = (list, values) => {
    (Array.isArray(values) ? values : []).forEach((value) => {
      list.append(element("li", "", value));
    });
  };

  const sourceDateLabel = (value) => {
    const raw = text(value);
    return raw.length >= 10 ? raw.slice(0, 10) : raw;
  };

  const sourceCalendarScalar = (value, fallback) => {
    const match = text(value, "").match(
      /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?)?/
    );
    if (!match) {
      return fallback;
    }
    const [, year, month, day, hour = "00", minute = "00", second = "00"] = match;
    let civilYear = Number(year);
    const civilMonth = Number(month);
    const civilDay = Number(day);
    civilYear -= civilMonth <= 2 ? 1 : 0;
    const era = Math.floor(civilYear / 400);
    const yearOfEra = civilYear - era * 400;
    const shiftedMonth = civilMonth + (civilMonth > 2 ? -3 : 9);
    const dayOfYear = Math.floor((153 * shiftedMonth + 2) / 5) + civilDay - 1;
    const dayOfEra =
      yearOfEra * 365 +
      Math.floor(yearOfEra / 4) -
      Math.floor(yearOfEra / 100) +
      dayOfYear;
    const civilDayNumber = era * 146097 + dayOfEra;
    // Ordonnée civile du texte source : aucun fuseau n'est attribué ou converti.
    return (
      ((civilDayNumber * 24 + Number(hour)) * 60 + Number(minute)) * 60 +
      Number(second)
    );
  };

  const shortNumber = (value) => {
    if (!Number.isFinite(value)) {
      return "—";
    }
    const absolute = Math.abs(value);
    const digits = absolute >= 100 ? 0 : absolute >= 10 ? 1 : 2;
    return value.toFixed(digits).replace(/\.0+$/, "").replace(/(\.\d*?)0+$/, "$1");
  };

  const drawPlot = (container, series) => {
    const compact = window.matchMedia("(max-width: 620px)").matches;
    const width = compact ? 350 : 760;
    const height = compact ? 286 : 320;
    const margin = compact
      ? { top: 42, right: 12, bottom: 48, left: 50 }
      : { top: 44, right: 24, bottom: 50, left: 66 };
    const innerWidth = width - margin.left - margin.right;
    const innerHeight = height - margin.top - margin.bottom;
    const allPoints = Array.isArray(series.points) ? series.points : [];
    const plotted = allPoints
      .map((point, index) => ({
        point,
        index,
        xValue: sourceCalendarScalar(point.timestamp_source, index),
        yValue: Number(point.measurement_value),
      }))
      .filter((entry) => Number.isFinite(entry.yValue));

    const figure = element("figure", "plot-card");
    const graphic = svgElement("svg", {
      viewBox: `0 0 ${width} ${height}`,
      role: "img",
      "aria-labelledby": `plot-title-${series.id} plot-desc-${series.id}`,
    });
    const title = svgElement("title", { id: `plot-title-${series.id}` });
    title.textContent = `${text(series.label)} — observations ponctuelles en ${text(series.unit)}`;
    const description = svgElement("desc", { id: `plot-desc-${series.id}` });
    description.textContent =
      "Chaque symbole représente une observation source. Aucun segment ne relie les points.";
    graphic.append(title, description);

    if (plotted.length === 0) {
      const empty = svgElement("text", {
        x: width / 2,
        y: height / 2,
        "text-anchor": "middle",
        class: "plot-title",
      });
      empty.textContent = "Aucune valeur numérique publiée";
      graphic.append(empty);
    } else {
      const xValues = plotted.map((entry) => entry.xValue);
      const yValues = plotted.map((entry) => entry.yValue);
      let xMin = Math.min(...xValues);
      let xMax = Math.max(...xValues);
      let yMin = Math.min(...yValues);
      let yMax = Math.max(...yValues);

      if (xMin === xMax) {
        xMin -= 1;
        xMax += 1;
      }
      if (yMin === yMax) {
        const padding = Math.abs(yMin) > 0 ? Math.abs(yMin) * 0.05 : 1;
        yMin -= padding;
        yMax += padding;
      }

      const yPadding = (yMax - yMin) * 0.08;
      yMin -= yPadding;
      yMax += yPadding;

      const xPosition = (value) =>
        margin.left + ((value - xMin) / (xMax - xMin)) * innerWidth;
      const yPosition = (value) =>
        margin.top + (1 - (value - yMin) / (yMax - yMin)) * innerHeight;

      const yTitle = svgElement("text", {
        x: margin.left,
        y: 20,
        class: "plot-title",
      });
      yTitle.textContent = `Valeur source (${text(series.unit)})`;
      graphic.append(yTitle);

      for (let index = 0; index <= 4; index += 1) {
        const ratio = index / 4;
        const y = margin.top + ratio * innerHeight;
        const value = yMax - ratio * (yMax - yMin);
        graphic.append(
          svgElement("line", {
            x1: margin.left,
            y1: y,
            x2: width - margin.right,
            y2: y,
            class: "plot-grid",
          })
        );
        const label = svgElement("text", {
          x: margin.left - 8,
          y: y + 4,
          "text-anchor": "end",
          class: "plot-label",
        });
        label.textContent = shortNumber(value);
        graphic.append(label);
      }

      graphic.append(
        svgElement("line", {
          x1: margin.left,
          y1: margin.top,
          x2: margin.left,
          y2: height - margin.bottom,
          class: "plot-axis",
        }),
        svgElement("line", {
          x1: margin.left,
          y1: height - margin.bottom,
          x2: width - margin.right,
          y2: height - margin.bottom,
          class: "plot-axis",
        })
      );

      const candidates = [...plotted].sort((left, right) => left.xValue - right.xValue);
      const labelEntries = compact
        ? [candidates[0], candidates[candidates.length - 1]]
        : [
            candidates[0],
            candidates[Math.floor((candidates.length - 1) / 2)],
            candidates[candidates.length - 1],
          ];
      labelEntries.forEach((entry, index) => {
        const label = svgElement("text", {
          x: xPosition(entry.xValue),
          y: height - 18,
          "text-anchor":
            index === 0 ? "start" : index === labelEntries.length - 1 ? "end" : "middle",
          class: "plot-label",
        });
        label.textContent = sourceDateLabel(entry.point.timestamp_source);
        graphic.append(label);
      });

      plotted.forEach(({ point, xValue, yValue }) => {
        const x = xPosition(xValue);
        const y = yPosition(yValue);
        const marker = point.duplicate_timestamp
          ? svgElement("rect", {
              x: x - 4.5,
              y: y - 4.5,
              width: 9,
              height: 9,
              transform: `rotate(45 ${x} ${y})`,
              class: "plot-duplicate",
            })
          : svgElement("circle", {
              cx: x,
              cy: y,
              r: compact ? 3.3 : 3.7,
              class: "plot-point",
            });
        const pointTitle = svgElement("title");
        pointTitle.textContent = [
          text(point.timestamp_source),
          `${text(point.measurement_value)} ${text(series.unit)}`,
          `ligne source ${text(point.source_row_number)}`,
          point.duplicate_timestamp ? "timestamp dupliqué conservé" : "timestamp non dupliqué",
        ].join(" · ");
        marker.append(pointTitle);
        graphic.append(marker);
      });
    }

    const caption = document.createElement("figcaption");
    const pointLegend = element("span", "legend-item");
    pointLegend.append(element("span", "legend-dot"), document.createTextNode("Observation source"));
    const duplicateLegend = element("span", "legend-item");
    duplicateLegend.append(
      element("span", "legend-diamond"),
      document.createTextNode("Timestamp dupliqué conservé")
    );
    const calendarNote = element(
      "span",
      "legend-item",
      "Position horizontale : calendrier source, sans attribution de fuseau"
    );
    caption.append(pointLegend, duplicateLegend, calendarNote);
    figure.append(graphic, caption);
    container.append(figure);
  };

  const buildSourceTable = (series) => {
    const details = element("details", "source-table");
    const summary = element("summary", "", "Consulter les observations source");
    const scroll = element("div", "table-scroll");
    const table = document.createElement("table");
    const caption = element(
      "caption",
      "sr-only",
      `Observations publiques de la série ${text(series.label)}`
    );
    const head = document.createElement("thead");
    const headerRow = document.createElement("tr");
    ["Horodatage source", `Valeur source (${text(series.unit)})`, "Ligne source", "Doublon"].forEach(
      (label) => headerRow.append(element("th", "", label))
    );
    head.append(headerRow);

    const body = document.createElement("tbody");
    (Array.isArray(series.points) ? series.points : []).forEach((point) => {
      const row = document.createElement("tr");
      if (point.duplicate_timestamp) {
        row.className = "duplicate-row";
      }
      row.append(
        element("td", "status-value", point.timestamp_source),
        element("td", "", point.measurement_value),
        element("td", "", point.source_row_number),
        element("td", "", yesNo(point.duplicate_timestamp))
      );
      body.append(row);
    });

    table.append(caption, head, body);
    scroll.append(table);
    details.append(summary, scroll);
    return details;
  };

  const renderSeries = (seriesList) => {
    const tabs = document.querySelector("#series-tabs");
    const panels = document.querySelector("#series-panels");
    const series = Array.isArray(seriesList) ? seriesList : [];
    const tabNodes = [];
    const panelNodes = [];

    series.forEach((item, index) => {
      const safeId = text(item.id, `serie-${index}`).replace(/[^a-zA-Z0-9_-]/g, "-");
      const tabId = `series-tab-${safeId}`;
      const panelId = `series-panel-${safeId}`;
      const tab = element("button", "series-tab", item.label);
      tab.type = "button";
      tab.id = tabId;
      tab.setAttribute("role", "tab");
      tab.setAttribute("aria-controls", panelId);
      tab.setAttribute("aria-selected", index === 0 ? "true" : "false");
      tab.tabIndex = index === 0 ? 0 : -1;

      const panel = element("article", "series-panel");
      panel.id = panelId;
      panel.setAttribute("role", "tabpanel");
      panel.setAttribute("aria-labelledby", tabId);
      panel.dataset.seriesId = text(item.id);
      panel.hidden = index !== 0;

      const header = element("header", "series-panel__header");
      const headingBlock = document.createElement("div");
      headingBlock.append(
        element("h3", "", item.label),
        element("p", "", item.measurement_name)
      );
      const chips = element("div", "series-chips");
      chips.setAttribute("aria-label", "Contexte de la série");
      chips.append(
        element("span", "series-chip", item.segment),
        element("span", "series-chip", `Unité source : ${text(item.unit)}`)
      );
      header.append(headingBlock, chips);

      const layout = element("div", "series-layout");
      const plotSlot = document.createElement("div");
      plotSlot.dataset.plotFor = safeId;
      drawPlot(plotSlot, item);

      const metaCard = element("aside", "series-meta");
      metaCard.append(element("h4", "", "Contrat de la série"));
      const meta = element("dl", "provenance-list");
      addDefinition(meta, "Segment", item.segment, "status-value");
      addDefinition(meta, "Unité source", item.unit);
      addDefinition(meta, "Protocole", item.protocol_status, "status-value");
      addDefinition(meta, "Fuseau", item.timezone_status, "status-value");
      addDefinition(meta, "Observations", item.observation_count);
      addDefinition(meta, "Début source", item.date_start, "status-value");
      addDefinition(meta, "Fin source", item.date_end, "status-value");
      metaCard.append(meta);

      layout.append(plotSlot, metaCard);
      panel.append(header, layout, buildSourceTable(item));
      tabs.append(tab);
      panels.append(panel);
      tabNodes.push(tab);
      panelNodes.push(panel);
    });

    const activate = (index, moveFocus) => {
      tabNodes.forEach((tab, tabIndex) => {
        const selected = tabIndex === index;
        tab.setAttribute("aria-selected", selected ? "true" : "false");
        tab.tabIndex = selected ? 0 : -1;
        panelNodes[tabIndex].hidden = !selected;
      });
      if (moveFocus && tabNodes[index]) {
        tabNodes[index].focus();
      }
    };

    tabNodes.forEach((tab, index) => {
      tab.addEventListener("click", () => activate(index, false));
      tab.addEventListener("keydown", (event) => {
        let target = null;
        if (event.key === "ArrowRight" || event.key === "ArrowDown") {
          target = (index + 1) % tabNodes.length;
        } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
          target = (index - 1 + tabNodes.length) % tabNodes.length;
        } else if (event.key === "Home") {
          target = 0;
        } else if (event.key === "End") {
          target = tabNodes.length - 1;
        }
        if (target !== null) {
          event.preventDefault();
          activate(target, true);
        }
      });
    });

    let compactMode = window.matchMedia("(max-width: 620px)").matches;
    window.addEventListener("resize", () => {
      const nextCompactMode = window.matchMedia("(max-width: 620px)").matches;
      if (nextCompactMode === compactMode) {
        return;
      }
      compactMode = nextCompactMode;
      series.forEach((item, index) => {
        const slot = panelNodes[index].querySelector("[data-plot-for]");
        slot.replaceChildren();
        drawPlot(slot, item);
      });
    });
  };

  const render = () => {
    if (!replay || typeof replay !== "object") {
      document.querySelector("#series-panels").append(
        element("p", "notice", "Données publiques du replay indisponibles.")
      );
      return;
    }

    const summary = replay.summary || {};
    const summaryList = document.querySelector("#summary");
    addDefinition(summaryList, "Observations", summary.observation_count);
    addDefinition(summaryList, "Séries distinctes", summary.series_count);
    addDefinition(summaryList, "Doublons conservés", yesNo(summary.duplicates_preserved));
    addDefinition(summaryList, "Jointure autorisée", yesNo(summary.join_ready));
    addDefinition(
      summaryList,
      "Interpolation masquée",
      yesNo(summary.hidden_interpolation_applied)
    );

    const geometry = replay.geometry || {};
    const geometryMeta = document.querySelector("#geometry-meta");
    addDefinition(geometryMeta, "Statut public", geometry.publication_status, "status-value");
    addDefinition(geometryMeta, "SHA-256 source", geometry.source_sha256, "status-value");
    addDefinition(
      geometryMeta,
      "Vue de face",
      geometry.front_view_status,
      "status-value"
    );
    addDefinition(
      geometryMeta,
      "Vue latérale",
      geometry.side_view_status,
      "status-value"
    );
    addDefinition(
      geometryMeta,
      "Fissure schématique",
      geometry.schematic_crack_status,
      "status-value"
    );
    addListItems(document.querySelector("#geometry-limits"), geometry.limits);
    addListItems(
      document.querySelector("#geometry-limits"),
      geometry.schematic_crack_limits
    );

    renderSeries(replay.series);

    const source = replay.source || {};
    const sourceMeta = document.querySelector("#source-meta");
    addDefinition(sourceMeta, "Manifeste public", source.manifest_sha256, "status-value");
    addDefinition(sourceMeta, "Mesures de fissures", source.manual_cracks_sha256, "status-value");
    addDefinition(sourceMeta, "Rapport qualité", source.quality_report_sha256, "status-value");

    const qualityMeta = document.querySelector("#quality-meta");
    addDefinition(qualityMeta, "Segments publiés", summary.series_count);
    addDefinition(qualityMeta, "Doublons préservés", yesNo(summary.duplicates_preserved));
    addDefinition(qualityMeta, "Prêt pour jointure", yesNo(summary.join_ready));
    addDefinition(
      qualityMeta,
      "Interpolation cachée",
      yesNo(summary.hidden_interpolation_applied)
    );
    addDefinition(qualityMeta, "Valeurs manquantes", summary.missing_values);
    addDefinition(qualityMeta, "Valeurs invalides", summary.invalid_values);
    addDefinition(qualityMeta, "Timestamps manquants", summary.missing_timestamps);
    addDefinition(qualityMeta, "Timestamps invalides", summary.invalid_timestamps);

    addListItems(document.querySelector("#pipeline"), replay.pipeline);
    addListItems(document.querySelector("#limits"), replay.limits);
    document.documentElement.dataset.replayReady = "true";
  };

  document.querySelectorAll("[data-scroll-target]").forEach((control) => {
    control.addEventListener("click", () => {
      const target = document.getElementById(control.dataset.scrollTarget);
      if (!target) {
        return;
      }
      target.scrollIntoView({ block: "start" });
      if (target.id === "contenu") {
        target.focus({ preventScroll: true });
      }
    });
  });

  render();
})();
