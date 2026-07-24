const PAGE_LABELS = Object.freeze({
  "/": "Accueil",
  "/offres.html": "Offres",
  "/methode.html": "Méthode",
  "/cas-clients.html": "Réalisations",
  "/contact.html": "Contact",
});

const UPSERT_PAGE_VIEW = `
  INSERT INTO page_views (day, page, count)
  VALUES (?1, ?2, 1)
  ON CONFLICT (day, page)
  DO UPDATE SET count = count + 1
`;

const SUMMARY_QUERY = `
  SELECT
    COALESCE(SUM(count), 0) AS total,
    COALESCE(SUM(CASE WHEN day = ?1 THEN count ELSE 0 END), 0) AS today,
    COALESCE(SUM(CASE WHEN day >= ?2 THEN count ELSE 0 END), 0) AS last_30_days
  FROM page_views
`;

const PAGE_QUERY = `
  SELECT page, SUM(count) AS count
  FROM page_views
  WHERE day >= ?1
  GROUP BY page
  ORDER BY count DESC, page ASC
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

function number(value) {
  return new Intl.NumberFormat("fr-FR").format(Number(value) || 0);
}

function dashboard(summary, pages) {
  const pageRows = pages
    .map((row) => `
      <tr>
        <th scope="row">${escapeHtml(PAGE_LABELS[row.page] || row.page)}</th>
        <td>${number(row.count)}</td>
      </tr>`)
    .join("");
  return `<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Compteur datapredict</title>
  <style>
    :root { color-scheme: light; font-family: Inter, ui-sans-serif, system-ui, sans-serif; color: #1f3342; background: #f5fbfc; }
    body { margin: 0; padding: 2rem 1rem 4rem; }
    main { width: min(62rem, 100%); margin: auto; }
    h1 { margin: 0 0 .4rem; color: #263f52; }
    .intro { margin: 0 0 2rem; color: #5b7284; }
    .cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1rem; margin-bottom: 2rem; }
    .card, section { border: 1px solid #c7dce4; border-radius: .75rem; background: #fff; box-shadow: 0 .4rem 1.2rem rgb(38 63 82 / 8%); }
    .card { padding: 1.2rem; }
    .card span { display: block; color: #5b7284; font-size: .85rem; }
    .card strong { display: block; margin-top: .25rem; color: #0c8790; font-size: 2rem; }
    section { overflow: hidden; }
    h2 { margin: 0; padding: 1rem 1.2rem; background: #e6edf2; color: #263f52; font-size: 1rem; }
    table { width: 100%; border-collapse: collapse; }
    th, td { padding: .7rem 1.2rem; border-top: 1px solid #e6edf2; text-align: left; }
    td { text-align: right; font-variant-numeric: tabular-nums; }
    @media (max-width: 45rem) { .cards { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <main>
    <h1>Compteur datapredict</h1>
    <p class="intro">Pages vues indicatives et agrégées, sans suivi individuel. Conservation : 24 mois.</p>
    <div class="cards">
      <div class="card"><span>Total conservé</span><strong>${number(summary.total)}</strong></div>
      <div class="card"><span>Aujourd’hui</span><strong>${number(summary.today)}</strong></div>
      <div class="card"><span>30 derniers jours</span><strong>${number(summary.last_30_days)}</strong></div>
    </div>
    <section>
      <h2>Par page — 30 jours</h2>
      <table><tbody>${pageRows || "<tr><td>Aucune donnée</td></tr>"}</tbody></table>
    </section>
  </main>
</body>
</html>`;
}

async function recordHit(request, env) {
  const cors = corsHeaders(request, env);
  if (!cors) {
    return new Response(null, { status: 403, headers: SECURITY_HEADERS });
  }

  const rawBody = await request.text();
  if (rawBody.length > 120) {
    return new Response(null, { status: 413, headers: { ...SECURITY_HEADERS, ...cors } });
  }

  let payload;
  try {
    payload = JSON.parse(rawBody);
  } catch {
    return new Response(null, { status: 400, headers: { ...SECURITY_HEADERS, ...cors } });
  }

  if (
    !payload
    || typeof payload !== "object"
    || Array.isArray(payload)
    || Object.keys(payload).length !== 1
  ) {
    return new Response(null, { status: 400, headers: { ...SECURITY_HEADERS, ...cors } });
  }

  const page = normalizePage(payload.page);
  if (!page) {
    return new Response(null, { status: 400, headers: { ...SECURITY_HEADERS, ...cors } });
  }

  await env.COUNTER_DB.prepare(UPSERT_PAGE_VIEW)
    .bind(parisDay(), page)
    .run();
  return new Response(null, { status: 204, headers: { ...SECURITY_HEADERS, ...cors } });
}

async function showStats(request, env) {
  if (!isAuthorized(request, env)) {
    return new Response("Authentification requise.", {
      status: 401,
      headers: {
        ...SECURITY_HEADERS,
        "Content-Type": "text/plain;charset=UTF-8",
        "WWW-Authenticate": 'Basic realm="Compteur datapredict", charset="UTF-8"',
      },
    });
  }

  const today = parisDay();
  const last30Days = shiftDays(today, -29);
  const [summary, pageResult] = await Promise.all([
    env.COUNTER_DB.prepare(SUMMARY_QUERY).bind(today, last30Days).first(),
    env.COUNTER_DB.prepare(PAGE_QUERY).bind(last30Days).all(),
  ]);

  return new Response(
    dashboard(
      summary || { total: 0, today: 0, last_30_days: 0 },
      pageResult.results || [],
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
      await env.COUNTER_DB.prepare("SELECT 1 FROM page_views LIMIT 1").first();
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
  await env.COUNTER_DB.prepare("DELETE FROM page_views WHERE day < ?1")
    .bind(cutoff)
    .run();
}

export default {
  fetch: fetchHandler,
  scheduled: scheduledHandler,
};
