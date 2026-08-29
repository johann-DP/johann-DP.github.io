(() => {
  "use strict";

  const figures = Object.freeze({
    "crack-history": {
      title: "Évolution historique de la fissure",
      description: "Mesures historiques, paliers, ajustements descriptifs et incertitudes.",
      path: "../assets/figures/demo-2/01-historical-crack-analysis-compacted-v2.html",
    },
    "crack-recent": {
      title: "Évolution récente de la fissure",
      description: "Suivi récent conservé séparément de la série historique.",
      path: "../assets/figures/demo-2/fissure-recente-meme-format.html",
    },
    "expansion-joint": {
      title: "Joint de dilatation du mur de soutènement",
      description: "Mesures observées, ajustement périodique et incertitude associée.",
      path: "../assets/figures/demo-2/joint-dilatation-rendu-site.html",
    },
    "retaining-wall-source-values": {
      title: "Signal brut du comparateur automatique — mur côté route",
      description: "Valeurs source brutes ; unité et fuseau des timestamps à confirmer.",
      path: "../assets/figures/demo-2/retaining-wall-sensor-source-values.html",
    },
    "weather-temperature": {
      title: "Températures intérieure et extérieure",
      description: "Séries temporelles et moyennes mobiles de température.",
      path: "../assets/figures/demo-2/weather/legacy/meteo_temperature.html",
    },
    "weather-temperature-range": {
      title: "Températures minimales et maximales",
      description: "Minima et maxima intérieurs et extérieurs.",
      path: "../assets/figures/demo-2/weather/legacy/meteo_temp_minmax.html",
    },
    "weather-humidity": {
      title: "Humidité et quantités d’eau dans l’air",
      description: "Humidité et contenus en eau intérieurs et extérieurs.",
      path: "../assets/figures/demo-2/weather/legacy/meteo_humidity.html",
    },
    "weather-light": {
      title: "Intensité lumineuse et indice UV",
      description: "Mesures de lumière, indice UV et différence de ratio.",
      path: "../assets/figures/demo-2/weather/legacy/meteo_light_uv.html",
    },
    "weather-rainfall": {
      title: "Précipitations hebdomadaires et journalières",
      description: "Moyennes hebdomadaires et mesures détaillées sur deux échelles.",
      path: "../assets/figures/demo-2/weather/legacy/meteo_precipitation.html",
    },
    "weather-wind-speed": {
      title: "Vitesses hebdomadaires et journalières du vent",
      description: "Moyennes hebdomadaires et série détaillée des vitesses.",
      path: "../assets/figures/demo-2/weather/legacy/meteo_wind_speed.html",
    },
    "weather-wind-direction": {
      title: "Direction et vitesse du vent",
      description: "Distribution radiale des directions et vitesses observées.",
      path: "../assets/figures/demo-2/weather/legacy/meteo_wind_dir.html",
    },
    "weather-pairplots": {
      title: "Scatterplots et distributions météo",
      description: "Distributions et relations croisées entre les variables affichées.",
      path: "../assets/figures/demo-2/weather/legacy/meteo_pairplots.html",
    },
    "weather-explorer": {
      title: "Explorateur des vingt mesures météo retenues",
      description: "Consultation directe des séries brutes, mesure par mesure.",
      path: "../assets/figures/demo-2/weather/complements/meteo_explorateur_toutes_mesures.html",
    },
    "weather-quality": {
      title: "Qualité et continuité de l’acquisition météo",
      description: "Complétude, trous temporels, doublons et constats de qualité.",
      path: "../assets/figures/demo-2/weather/complements/meteo_qualite_acquisition.html",
    },
  });

  const viewer = document.querySelector("#figure-viewer");
  const mount = document.querySelector("#viewer-mount");
  const title = document.querySelector("#viewer-title");
  const description = document.querySelector("#viewer-description");
  const fallback = document.querySelector("#viewer-fallback");
  const status = document.querySelector("#viewer-status");
  const buttons = [...document.querySelectorAll("[data-figure-id]")];
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  if (!viewer || !mount || !title || !description || !fallback || !status) {
    return;
  }

  const initialTitle = title.textContent;
  const initialDescription = description.textContent;
  const emptyState = mount.firstElementChild?.cloneNode(true);
  let activeButton = null;
  let frameObserver = null;

  const announce = (message) => {
    status.textContent = "";
    window.requestAnimationFrame(() => {
      status.textContent = message;
    });
  };

  const resetButtons = () => {
    buttons.forEach((button) => button.setAttribute("aria-pressed", "false"));
  };

  const closeFigure = ({ restoreFocus = true } = {}) => {
    frameObserver?.disconnect();
    frameObserver = null;
    mount.replaceChildren(emptyState?.cloneNode(true) || document.createElement("div"));
    title.textContent = initialTitle;
    description.textContent = initialDescription;
    fallback.hidden = true;
    fallback.removeAttribute("href");
    resetButtons();
    announce("La figure a été fermée.");
    if (restoreFocus && activeButton) {
      activeButton.focus();
    }
    activeButton = null;
  };

  const resizeFrame = (frame) => {
    try {
      const documentElement = frame.contentDocument?.documentElement;
      const body = frame.contentDocument?.body;
      const measured = Math.max(
        documentElement?.scrollHeight || 0,
        documentElement?.offsetHeight || 0,
        body?.scrollHeight || 0,
        body?.offsetHeight || 0,
      );
      if (measured > 0) {
        frame.style.height = `${Math.min(2800, Math.max(620, measured + 4))}px`;
      }
    } catch {
      frame.style.height = "900px";
    }
  };

  const loadFigure = (button) => {
    const identifier = button.dataset.figureId;
    const figure = figures[identifier];
    if (!figure) {
      announce("Cette restitution n’est pas disponible.");
      return;
    }

    frameObserver?.disconnect();
    resetButtons();
    button.setAttribute("aria-pressed", "true");
    activeButton = button;
    title.textContent = figure.title;
    description.textContent = figure.description;
    fallback.href = figure.path;
    fallback.hidden = false;

    const loading = document.createElement("div");
    loading.className = "fissures-demo__viewer-loading";
    const loadingText = document.createElement("p");
    loadingText.textContent = `Chargement de « ${figure.title} »…`;
    loading.append(loadingText);

    const frame = document.createElement("iframe");
    frame.className = "fissures-demo__viewer-frame";
    frame.title = figure.title;
    frame.src = figure.path;
    frame.loading = "eager";
    frame.hidden = true;
    frame.setAttribute("aria-describedby", "viewer-description");

    const actions = document.createElement("div");
    actions.className = "fissures-demo__viewer-actions";
    const close = document.createElement("button");
    close.className = "fissures-demo__viewer-return";
    close.type = "button";
    close.textContent = "Fermer la figure";
    close.addEventListener("click", () => closeFigure());
    const external = document.createElement("a");
    external.className = "fissures-demo__viewer-link";
    external.href = figure.path;
    external.target = "_blank";
    external.rel = "noopener noreferrer";
    external.textContent = "Ouvrir dans une nouvelle fenêtre";
    actions.append(close, external);

    frame.addEventListener("load", () => {
      loading.remove();
      frame.hidden = false;
      resizeFrame(frame);
      try {
        const observed = frame.contentDocument?.documentElement;
        if (observed && "ResizeObserver" in window) {
          frameObserver = new ResizeObserver(() => resizeFrame(frame));
          frameObserver.observe(observed);
        }
      } catch {
        frameObserver = null;
      }
      window.setTimeout(() => resizeFrame(frame), 500);
      window.setTimeout(() => resizeFrame(frame), 1800);
      announce(`La figure « ${figure.title} » est chargée.`);
    }, { once: true });

    mount.replaceChildren(loading, frame, actions);
    announce(`Chargement de la figure « ${figure.title} ».`);
    viewer.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "start" });
    title.focus({ preventScroll: true });
  };

  buttons.forEach((button) => {
    const identifier = button.dataset.figureId;
    if (!Object.hasOwn(figures, identifier)) {
      button.disabled = true;
      return;
    }
    button.addEventListener("click", () => loadFigure(button));
  });
})();
