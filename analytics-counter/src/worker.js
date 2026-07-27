const PAGE_LABELS = Object.freeze({
  "/": "Accueil",
  "/offres.html": "Offres",
  "/methode.html": "Méthode",
  "/cas-clients.html": "Réalisations",
  "/contact.html": "Contact",
});

const SOURCE_LABELS = Object.freeze({
  direct: "Accès direct",
  search: "Moteur de recherche",
  linkedin: "LinkedIn",
  "other-social": "Autre réseau social",
  "other-site": "Autre site",
  internal: "Interne / nouvel onglet",
});

const DEVICE_LABELS = Object.freeze({
  desktop: "Ordinateur",
  tablet: "Tablette",
  mobile: "Mobile",
});

const ALLOWED_EVENTS = new Set(["pageview", "engaged_30s", "scroll_75"]);
const ALLOWED_SOURCES = new Set(Object.keys(SOURCE_LABELS));
const ALLOWED_DEVICES = new Set(Object.keys(DEVICE_LABELS));
const PAYLOAD_KEYS = ["device", "event", "page", "source", "visit"];

const UPSERT_DAILY_TOTAL = `
  INSERT INTO daily_totals (day, page_views, visits, engaged_30s, scroll_75)
  VALUES (?1, ?2, ?3, ?4, ?5)
  ON CONFLICT (day)
  DO UPDATE SET
    page_views = page_views + excluded.page_views,
    visits = visits + excluded.visits,
    engaged_30s = engaged_30s + excluded.engaged_30s,
    scroll_75 = scroll_75 + excluded.scroll_75
`;

const UPSERT_DAILY_PAGE = `
  INSERT INTO daily_pages (day, page, page_views, visits, engaged_30s, scroll_75)
  VALUES (?1, ?2, ?3, ?4, ?5, ?6)
  ON CONFLICT (day, page)
  DO UPDATE SET
    page_views = page_views + excluded.page_views,
    visits = visits + excluded.visits,
    engaged_30s = engaged_30s + excluded.engaged_30s,
    scroll_75 = scroll_75 + excluded.scroll_75
`;

const UPSERT_DIMENSION = `
  INSERT INTO daily_dimensions (day, dimension, value, count)
  VALUES (?1, ?2, ?3, 1)
  ON CONFLICT (day, dimension, value)
  DO UPDATE SET count = count + 1
`;

const SUMMARY_QUERY = `
  SELECT
    COALESCE(SUM(page_views), 0) AS total_page_views,
    COALESCE(SUM(visits), 0) AS total_visits,
    COALESCE(SUM(CASE WHEN day = ?1 THEN page_views ELSE 0 END), 0) AS today_page_views,
    COALESCE(SUM(CASE WHEN day = ?1 THEN visits ELSE 0 END), 0) AS today_visits,
    COALESCE(SUM(CASE WHEN day >= ?2 THEN page_views ELSE 0 END), 0) AS last_30_page_views,
    COALESCE(SUM(CASE WHEN day >= ?2 THEN visits ELSE 0 END), 0) AS last_30_visits,
    COALESCE(SUM(CASE WHEN day >= ?2 THEN engaged_30s ELSE 0 END), 0) AS last_30_engaged_30s,
    COALESCE(SUM(CASE WHEN day >= ?2 THEN scroll_75 ELSE 0 END), 0) AS last_30_scroll_75,
    COALESCE(SUM(CASE WHEN day >= ?3 AND day < ?2 THEN page_views ELSE 0 END), 0) AS previous_30_page_views,
    COALESCE(SUM(CASE WHEN day >= ?4 THEN page_views ELSE 0 END), 0) AS last_90_page_views
  FROM daily_totals
`;

const DAILY_QUERY = `
  SELECT day, page_views, visits
  FROM daily_totals
  WHERE day >= ?1
  ORDER BY day ASC
`;

const PAGE_QUERY = `
  SELECT
    page,
    SUM(page_views) AS page_views,
    SUM(visits) AS visits,
    SUM(engaged_30s) AS engaged_30s,
    SUM(scroll_75) AS scroll_75
  FROM daily_pages
  WHERE day >= ?1
  GROUP BY page
  ORDER BY page_views DESC, page ASC
`;

const MONTHLY_PAGE_QUERY = `
  SELECT
    substr(day, 1, 7) AS month,
    page,
    SUM(page_views) AS page_views
  FROM daily_pages
  WHERE day BETWEEN ?1 AND ?2
  GROUP BY month, page
  ORDER BY month DESC, page ASC
`;

const DIMENSION_QUERY = `
  SELECT dimension, value, SUM(count) AS count
  FROM daily_dimensions
  WHERE day >= ?1
  GROUP BY dimension, value
  ORDER BY dimension ASC, count DESC, value ASC
`;

const SECURITY_HEADERS = Object.freeze({
  "Cache-Control": "no-store",
  "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
});

export function normalizePage(value) {
  if (value === "/index.html") {
    return "/";
  }
  return Object.hasOwn(PAGE_LABELS, value) ? value : null;
}

export function normalizeCountry(value) {
  const country = String(value || "").toUpperCase();
  return /^[A-Z]{2}$/.test(country) ? country : "XX";
}

export function parisDay(date = new Date()) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Paris",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(date);
  const part = (type) => parts.find((item) => item.type === type)?.value;
  return `${part("year")}-${part("month")}-${part("day")}`;
}

export function shiftDays(day, offset) {
  const [year, month, date] = day.split("-").map(Number);
  const shifted = new Date(Date.UTC(year, month - 1, date + offset));
  return shifted.toISOString().slice(0, 10);
}

export function shiftMonths(month, offset) {
  const [year, monthNumber] = month.split("-").map(Number);
  const shifted = new Date(Date.UTC(year, monthNumber - 1 + offset, 1));
  return shifted.toISOString().slice(0, 7);
}

export function monthlyWindow(day) {
  return {
    from: `${shiftMonths(day.slice(0, 7), -23)}-01`,
    to: day,
  };
}

export function retentionCutoff(day) {
  const [year, month, date] = day.split("-").map(Number);
  const monthIndex = month - 1 - 24;
  const targetYear = year + Math.floor(monthIndex / 12);
  const targetMonth = ((monthIndex % 12) + 12) % 12;
  const lastDay = new Date(Date.UTC(targetYear, targetMonth + 1, 0)).getUTCDate();
  return new Date(Date.UTC(targetYear, targetMonth, Math.min(date, lastDay)))
    .toISOString()
    .slice(0, 10);
}

function allowedOrigins(env) {
  return new Set(
    String(env.ALLOWED_ORIGINS || "")
      .split(",")
      .map((origin) => origin.trim())
      .filter(Boolean),
  );
}

function corsHeaders(request, env) {
  const origin = request.headers.get("Origin");
  if (!origin || !allowedOrigins(env).has(origin)) {
    return null;
  }
  return {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
    "Vary": "Origin",
  };
}

function constantTimeEqual(left, right) {
  const leftBytes = new TextEncoder().encode(left);
  const rightBytes = new TextEncoder().encode(right);
  let difference = leftBytes.length ^ rightBytes.length;
  const length = Math.max(leftBytes.length, rightBytes.length);

  for (let index = 0; index < length; index += 1) {
    difference |= (leftBytes[index] || 0) ^ (rightBytes[index] || 0);
  }
  return difference === 0;
}

function isAuthorized(request, env) {
  const expectedUser = String(env.ADMIN_USERNAME || "datapredict");
  const expectedPassword = String(env.ADMIN_PASSWORD || "");
  const header = request.headers.get("Authorization") || "";
  if (!expectedPassword || !header.startsWith("Basic ")) {
    return false;
  }

  try {
    const decoded = atob(header.slice(6));
    const separator = decoded.indexOf(":");
    if (separator < 0) {
      return false;
    }
    return constantTimeEqual(decoded.slice(0, separator), expectedUser)
      && constantTimeEqual(decoded.slice(separator + 1), expectedPassword);
  } catch {
    return false;
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function number(value, maximumFractionDigits = 0) {
  return new Intl.NumberFormat("fr-FR", { maximumFractionDigits })
    .format(Number(value) || 0);
}

function count(value) {
  return Math.max(0, Number(value) || 0);
}

function countNumber(value) {
  return number(count(value));
}

function roundedCount(value) {
  return Math.round(count(value) / 10) * 10;
}

function roundedNumber(value) {
  return number(roundedCount(value));
}

function ratio(numerator, denominator) {
  const safeDenominator = count(denominator);
  return safeDenominator ? count(numerator) / safeDenominator : null;
}

function percent(numerator, denominator) {
  const value = ratio(numerator, denominator);
  if (value === null) {
    return "—";
  }
  return `${number(value * 100, 1)} %`;
}

function changeLabel(current, previous) {
  const safeCurrent = count(current);
  const safePrevious = count(previous);
  if (!safePrevious) {
    return safeCurrent ? "nouvelle période" : "0 %";
  }
  const change = ((safeCurrent - safePrevious) / safePrevious) * 100;
  return `${change > 0 ? "+" : ""}${number(change, 1)} %`;
}

function countryLabel(code) {
  if (code === "XX") {
    return "Pays indéterminé";
  }
  try {
    return new Intl.DisplayNames(["fr"], { type: "region" }).of(code) || code;
  } catch {
    return code;
  }
}

function formatDay(day) {
  return new Intl.DateTimeFormat("fr-FR", {
    day: "2-digit",
    month: "short",
    timeZone: "Europe/Paris",
  }).format(new Date(`${day}T12:00:00Z`));
}

function formatMonth(month) {
  return new Intl.DateTimeFormat("fr-FR", {
    month: "long",
    year: "numeric",
    timeZone: "Europe/Paris",
  }).format(new Date(`${month}-15T12:00:00Z`));
}

function fillDaily(rows, today) {
  const values = new Map(rows.map((row) => [row.day, row]));
  return Array.from({ length: 30 }, (_, index) => {
    const day = shiftDays(today, index - 29);
    return values.get(day) || { day, page_views: 0, visits: 0 };
  });
}

function tableRows(rows, label, columns) {
  return rows
    .map((row) => `
      <tr>
        <th scope="row">${escapeHtml(label(row))}</th>
        ${columns.map((column) => `<td>${escapeHtml(column(row))}</td>`).join("")}
      </tr>`)
    .join("");
}

function monthlyTableRows(rows, today) {
  const counts = new Map(
    rows.map((row) => [`${row.month}|${row.page}`, count(row.page_views)]),
  );
  const observedMonths = [...new Set(rows.map((row) => row.month))].sort();
  const firstObservedMonth = observedMonths[0] || today.slice(0, 7);
  const months = Array.from(
    { length: 24 },
    (_, index) => shiftMonths(today.slice(0, 7), -index),
  );

  return months
    .map((month) => {
      const dataAvailable = month >= firstObservedMonth;
      const pageCounts = Object.keys(PAGE_LABELS)
        .map((page) => counts.get(`${month}|${page}`) || 0);
      const total = pageCounts.reduce((sum, value) => sum + value, 0);
      return `
        <tr>
          <th scope="row">${escapeHtml(formatMonth(month))}</th>
          ${pageCounts.map((value) => `<td>${dataAvailable ? escapeHtml(countNumber(value)) : "—"}</td>`).join("")}
          <td><strong>${dataAvailable ? escapeHtml(countNumber(total)) : "—"}</strong></td>
        </tr>`;
    })
    .join("");
}

function dashboard(summary, dailyRows, pages, monthlyPages, dimensions, today) {
  const daily = fillDaily(dailyRows, today);
  const maxDaily = Math.max(1, ...daily.map((row) => count(row.page_views)));
  const trendRows = daily
    .map((row) => {
      const pageViews = count(row.page_views);
      const width = Math.round((pageViews / maxDaily) * 1000) / 10;
      return `
        <div class="trend-row">
          <time datetime="${row.day}">${escapeHtml(formatDay(row.day))}</time>
          <div class="trend-bar"><span style="width:${width}%"></span></div>
          <strong>${countNumber(row.page_views)}</strong>
          <small>${countNumber(row.visits)} visite(s)</small>
        </div>`;
    })
    .join("");

  const pageRows = tableRows(
    pages,
    (row) => PAGE_LABELS[row.page] || row.page,
    [
      (row) => countNumber(row.page_views),
      (row) => countNumber(row.visits),
      (row) => percent(row.engaged_30s, row.page_views),
      (row) => percent(row.scroll_75, row.page_views),
    ],
  );
  const monthlyRows = monthlyTableRows(monthlyPages, today);

  const groupedDimensions = dimensions.reduce((groups, row) => {
    const group = groups[row.dimension] || [];
    group.push(row);
    groups[row.dimension] = group;
    return groups;
  }, {});
  const sourceRows = tableRows(
    (groupedDimensions.source || []).filter((row) => roundedCount(row.count) > 0),
    (row) => SOURCE_LABELS[row.value] || row.value,
    [(row) => roundedNumber(row.count)],
  );
  const countryRows = tableRows(
    (groupedDimensions.country || []).filter((row) => roundedCount(row.count) > 0),
    (row) => countryLabel(row.value),
    [(row) => roundedNumber(row.count)],
  );
  const deviceRows = tableRows(
    (groupedDimensions.device || []).filter((row) => roundedCount(row.count) > 0),
    (row) => DEVICE_LABELS[row.value] || row.value,
    [(row) => roundedNumber(row.count)],
  );

  const emptyRow = (columns = 2) => `<tr><td colspan="${columns}">Aucune donnée</td></tr>`;
  const dimensionEmptyRow = (rows) => (
    rows.length
      ? `<tr><td colspan="2">Effectif inférieur à 5 — valeur masquée</td></tr>`
      : emptyRow()
  );
  const pagesPerVisit = ratio(
    summary.last_30_page_views,
    summary.last_30_visits,
  );
  return `<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="only light">
  <title>Audience datapredict</title>
  <style>
    :root { color-scheme: only light; font-family: Inter, ui-sans-serif, system-ui, sans-serif; color: #1f3342; background: #f5fbfc; }
    * { box-sizing: border-box; }
    body { margin: 0; padding: 2rem 1rem 4rem; }
    main { width: min(72rem, 100%); margin: auto; }
    h1 { margin: 0 0 .4rem; color: #263f52; }
    .intro { margin: 0 0 2rem; color: #5b7284; }
    .cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1rem; margin-bottom: 2rem; }
    .card, section { border: 1px solid #c7dce4; border-radius: .75rem; background: #fff; box-shadow: 0 .4rem 1.2rem rgb(38 63 82 / 8%); }
    .card { padding: 1.2rem; }
    .card span { display: block; color: #5b7284; font-size: .85rem; }
    .card strong { display: block; margin-top: .25rem; color: #0c8790; font-size: 1.8rem; }
    .card small { display: block; margin-top: .25rem; color: #5b7284; }
    .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1rem; margin-top: 1rem; }
    section { overflow: hidden; margin-top: 1rem; }
    .grid section { margin-top: 0; }
    h2 { margin: 0; padding: 1rem 1.2rem; background: #e6edf2; color: #263f52; font-size: 1rem; }
    table { width: 100%; border-collapse: collapse; }
    th, td { padding: .7rem 1.2rem; border-top: 1px solid #e6edf2; text-align: left; }
    td { text-align: right; font-variant-numeric: tabular-nums; }
    .table-scroll { max-width: 100%; overflow-x: auto; -webkit-overflow-scrolling: touch; }
    .monthly-table { min-width: 48rem; }
    .monthly-table th:not(:first-child), .monthly-table td { text-align: right; font-variant-numeric: tabular-nums; }
    .monthly-table th:first-child { position: sticky; left: 0; z-index: 1; background: #fff; }
    .monthly-table thead th:first-child { z-index: 2; background: #e6edf2; }
    .trend { padding: 1rem 1.2rem; }
    .trend-row { display: grid; grid-template-columns: 4.5rem minmax(5rem, 1fr) 3rem 6.5rem; gap: .7rem; align-items: center; min-height: 1.65rem; }
    .trend-row time, .trend-row small { color: #5b7284; font-size: .78rem; }
    .trend-row strong { text-align: right; font-variant-numeric: tabular-nums; }
    .trend-bar { height: .55rem; border-radius: 999px; background: #e6edf2; overflow: hidden; }
    .trend-bar span { display: block; height: 100%; border-radius: inherit; background: linear-gradient(90deg, #11b3bf, #40647c); }
    .note { margin: 1.5rem 0 0; color: #5b7284; font-size: .85rem; }
    @media (max-width: 48rem) {
      .cards, .grid { grid-template-columns: 1fr; }
      .trend-row { grid-template-columns: 4rem minmax(4rem, 1fr) 2.5rem; }
      .trend-row small { display: none; }
      th, td { padding: .65rem .75rem; }
    }
  </style>
</head>
<body>
  <main>
    <h1>Audience datapredict</h1>
    <p class="intro">Statistiques agrégées, sans identifiant ni parcours individuel. Totaux et pages présentés à l’unité ; conservation : 24 mois.</p>
    <div class="cards">
      <div class="card"><span>Pages vues conservées</span><strong>${countNumber(summary.total_page_views)}</strong></div>
      <div class="card"><span>Aujourd’hui</span><strong>${countNumber(summary.today_page_views)}</strong><small>${countNumber(summary.today_visits)} visite(s) estimée(s)</small></div>
      <div class="card"><span>Pages vues — 30 jours</span><strong>${countNumber(summary.last_30_page_views)}</strong><small>${changeLabel(summary.last_30_page_views, summary.previous_30_page_views)} vs période précédente</small></div>
      <div class="card"><span>Visites estimées — 30 jours</span><strong>${countNumber(summary.last_30_visits)}</strong><small>une première page par session d’onglet</small></div>
      <div class="card"><span>Pages par visite — 30 jours</span><strong>${pagesPerVisit === null ? "—" : number(pagesPerVisit, 2)}</strong></div>
      <div class="card"><span>Pages vues — 90 jours</span><strong>${countNumber(summary.last_90_page_views)}</strong></div>
    </div>

    <section>
      <h2>Évolution quotidienne — 30 jours</h2>
      <div class="trend">${trendRows}</div>
    </section>

    <section>
      <h2>Contenus consultés — 30 jours</h2>
      <table>
        <thead><tr><th>Page</th><th>Vues</th><th>Entrées</th><th>Visible 30 s</th><th>Défilement 75 %</th></tr></thead>
        <tbody>${pageRows || emptyRow(5)}</tbody>
      </table>
    </section>

    <section>
      <h2>Pages vues par mois et par page — 24 mois</h2>
      <div class="table-scroll">
        <table class="monthly-table">
          <thead>
            <tr>
              <th scope="col">Mois</th>
              ${Object.values(PAGE_LABELS).map((label) => `<th scope="col">${escapeHtml(label)}</th>`).join("")}
              <th scope="col">Total</th>
            </tr>
          </thead>
          <tbody>${monthlyRows}</tbody>
        </table>
      </div>
    </section>

    <div class="grid">
      <section>
        <h2>Origine technique des visites — 30 jours</h2>
        <table><tbody>${sourceRows || dimensionEmptyRow(groupedDimensions.source || [])}</tbody></table>
      </section>
      <section>
        <h2>Type d’écran — 30 jours</h2>
        <table><tbody>${deviceRows || dimensionEmptyRow(groupedDimensions.device || [])}</tbody></table>
      </section>
    </div>

    <section>
      <h2>Pays approximatif — 30 jours</h2>
      <table><tbody>${countryRows || dimensionEmptyRow(groupedDimensions.country || [])}</tbody></table>
    </section>
    <p class="note">Les visites sont des estimations par session d’onglet. « — » indique un mois antérieur au début de la collecte. Les sources, pays et écrans sont arrondis à la dizaine et comptés séparément ; ils ne peuvent pas être croisés pour reconstituer un parcours.</p>
  </main>
</body>
</html>`;
}

function isValidPayload(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return false;
  }
  const keys = Object.keys(payload).sort();
  return keys.length === PAYLOAD_KEYS.length
    && keys.every((key, index) => key === PAYLOAD_KEYS[index])
    && ALLOWED_EVENTS.has(payload.event)
    && typeof payload.visit === "boolean"
    && ALLOWED_SOURCES.has(payload.source)
    && ALLOWED_DEVICES.has(payload.device);
}

function eventMetrics(event, visit) {
  return {
    pageViews: event === "pageview" ? 1 : 0,
    visits: event === "pageview" && visit ? 1 : 0,
    engaged30s: event === "engaged_30s" ? 1 : 0,
    scroll75: event === "scroll_75" ? 1 : 0,
  };
}

async function recordHit(request, env) {
  const cors = corsHeaders(request, env);
  if (!cors) {
    return new Response(null, { status: 403, headers: SECURITY_HEADERS });
  }

  const rawBody = await request.text();
  if (rawBody.length > 240) {
    return new Response(null, { status: 413, headers: { ...SECURITY_HEADERS, ...cors } });
  }

  let payload;
  try {
    payload = JSON.parse(rawBody);
  } catch {
    return new Response(null, { status: 400, headers: { ...SECURITY_HEADERS, ...cors } });
  }

  const page = normalizePage(payload?.page);
  if (!page || !isValidPayload(payload)) {
    return new Response(null, { status: 400, headers: { ...SECURITY_HEADERS, ...cors } });
  }

  const day = parisDay();
  const metrics = eventMetrics(payload.event, payload.visit);
  const statements = [
    env.COUNTER_DB.prepare(UPSERT_DAILY_TOTAL)
      .bind(day, metrics.pageViews, metrics.visits, metrics.engaged30s, metrics.scroll75),
    env.COUNTER_DB.prepare(UPSERT_DAILY_PAGE)
      .bind(day, page, metrics.pageViews, metrics.visits, metrics.engaged30s, metrics.scroll75),
  ];

  if (metrics.visits) {
    statements.push(
      env.COUNTER_DB.prepare(UPSERT_DIMENSION).bind(day, "source", payload.source),
      env.COUNTER_DB.prepare(UPSERT_DIMENSION).bind(day, "device", payload.device),
      env.COUNTER_DB.prepare(UPSERT_DIMENSION)
        .bind(day, "country", normalizeCountry(request.cf?.country)),
    );
  }

  await env.COUNTER_DB.batch(statements);
  return new Response(null, { status: 204, headers: { ...SECURITY_HEADERS, ...cors } });
}

async function showStats(request, env) {
  if (!isAuthorized(request, env)) {
    return new Response("Authentification requise.", {
      status: 401,
      headers: {
        ...SECURITY_HEADERS,
        "Content-Type": "text/plain;charset=UTF-8",
        "WWW-Authenticate": 'Basic realm="Audience datapredict", charset="UTF-8"',
      },
    });
  }

  const today = parisDay();
  const last30Days = shiftDays(today, -29);
  const previous30Days = shiftDays(today, -59);
  const last90Days = shiftDays(today, -89);
  const monthly = monthlyWindow(today);
  const [
    summary,
    dailyResult,
    pageResult,
    monthlyPageResult,
    dimensionResult,
  ] = await Promise.all([
    env.COUNTER_DB.prepare(SUMMARY_QUERY)
      .bind(today, last30Days, previous30Days, last90Days)
      .first(),
    env.COUNTER_DB.prepare(DAILY_QUERY).bind(last30Days).all(),
    env.COUNTER_DB.prepare(PAGE_QUERY).bind(last30Days).all(),
    env.COUNTER_DB.prepare(MONTHLY_PAGE_QUERY).bind(monthly.from, monthly.to).all(),
    env.COUNTER_DB.prepare(DIMENSION_QUERY).bind(last30Days).all(),
  ]);

  return new Response(
    dashboard(
      summary || {},
      dailyResult.results || [],
      pageResult.results || [],
      monthlyPageResult.results || [],
      dimensionResult.results || [],
      today,
    ),
    {
      headers: {
        ...SECURITY_HEADERS,
        "Content-Type": "text/html;charset=UTF-8",
      },
    },
  );
}

async function fetchHandler(request, env) {
  const url = new URL(request.url);

  if (url.pathname === "/health" && request.method === "GET") {
    try {
      await env.COUNTER_DB.prepare("SELECT 1 FROM daily_totals LIMIT 1").first();
      return Response.json({ status: "ok" }, { headers: SECURITY_HEADERS });
    } catch {
      return Response.json(
        { status: "unavailable" },
        { status: 503, headers: SECURITY_HEADERS },
      );
    }
  }

  if (url.pathname === "/hit" && request.method === "OPTIONS") {
    const cors = corsHeaders(request, env);
    return new Response(null, {
      status: cors ? 204 : 403,
      headers: cors ? { ...SECURITY_HEADERS, ...cors } : SECURITY_HEADERS,
    });
  }

  if (url.pathname === "/hit" && request.method === "POST") {
    try {
      return await recordHit(request, env);
    } catch {
      return new Response(null, { status: 503, headers: SECURITY_HEADERS });
    }
  }

  if (url.pathname === "/stats" && request.method === "GET") {
    try {
      return await showStats(request, env);
    } catch {
      return new Response("Statistiques temporairement indisponibles.", {
        status: 503,
        headers: { ...SECURITY_HEADERS, "Content-Type": "text/plain;charset=UTF-8" },
      });
    }
  }

  return new Response("Introuvable.", {
    status: 404,
    headers: { ...SECURITY_HEADERS, "Content-Type": "text/plain;charset=UTF-8" },
  });
}

async function scheduledHandler(_event, env) {
  const cutoff = retentionCutoff(parisDay());
  await env.COUNTER_DB.batch([
    env.COUNTER_DB.prepare("DELETE FROM daily_totals WHERE day < ?1").bind(cutoff),
    env.COUNTER_DB.prepare("DELETE FROM daily_pages WHERE day < ?1").bind(cutoff),
    env.COUNTER_DB.prepare("DELETE FROM daily_dimensions WHERE day < ?1").bind(cutoff),
  ]);
}

export default {
  fetch: fetchHandler,
  scheduled: scheduledHandler,
};
