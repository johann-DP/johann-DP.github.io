import assert from "node:assert/strict";
import test from "node:test";

import worker, {
  normalizeCountry,
  normalizePage,
  monthlyWindow,
  retentionCutoff,
  shiftDays,
  shiftMonths,
} from "../src/worker.js";

class FakeStatement {
  constructor(database, sql) {
    this.database = database;
    this.sql = sql;
    this.parameters = [];
  }

  bind(...parameters) {
    this.parameters = parameters;
    return this;
  }

  async first() {
    if (this.sql.includes("SELECT 1 FROM daily_totals")) {
      if (this.database.healthError) {
        throw new Error("base indisponible");
      }
      return { 1: 1 };
    }
    return {
      total_page_views: 142,
      total_visits: 81,
      today_page_views: 7,
      today_visits: 4,
      last_30_page_views: 96,
      last_30_visits: 55,
      last_30_engaged_30s: 31,
      last_30_scroll_75: 24,
      previous_30_page_views: 72,
      last_90_page_views: 128,
    };
  }

  async all() {
    if (this.sql.includes("FROM daily_totals")) {
      return {
        results: [
          { day: "2026-07-23", page_views: 4, visits: 2 },
          { day: "2026-07-24", page_views: 7, visits: 4 },
        ],
      };
    }
    if (this.sql.includes("FROM daily_pages")) {
      if (this.sql.includes("AS month")) {
        return {
          results: [
            { month: "2026-07", page: "/", page_views: 8 },
            { month: "2026-07", page: "/offres.html", page_views: 3 },
          ],
        };
      }
      return {
        results: [{
          page: "/",
          page_views: 50,
          visits: 30,
          engaged_30s: 20,
          scroll_75: 15,
        }],
      };
    }
    if (this.sql.includes("FROM daily_dimensions")) {
      return {
        results: [
          { dimension: "source", value: "linkedin", count: 12 },
          { dimension: "source", value: "other-site", count: 4 },
          { dimension: "device", value: "desktop", count: 20 },
          { dimension: "country", value: "FR", count: 25 },
        ],
      };
    }
    return { results: [] };
  }
}

class FakeDatabase {
  constructor() {
    this.batches = [];
    this.healthError = false;
  }

  prepare(sql) {
    return new FakeStatement(this, sql);
  }

  async batch(statements) {
    this.batches.push(
      statements.map((statement) => ({
        sql: statement.sql,
        parameters: statement.parameters,
      })),
    );
    return statements.map(() => ({ success: true }));
  }
}

const environment = () => ({
  COUNTER_DB: new FakeDatabase(),
  ALLOWED_ORIGINS: "https://www.datapredict.org",
  ADMIN_USERNAME: "datapredict",
  ADMIN_PASSWORD: "test-password",
  COLLECTION_STARTED_ON: "2024-01-01",
});

const basicAuth = (user, password) => (
  `Basic ${Buffer.from(`${user}:${password}`).toString("base64")}`
);

const payload = (overrides = {}) => ({
  page: "/",
  event: "pageview",
  visit: true,
  source: "direct",
  device: "desktop",
  ...overrides,
});

function hitRequest(body, origin = "https://www.datapredict.org", country = "FR") {
  const request = new Request("https://counter.example/hit", {
    method: "POST",
    headers: {
      "Content-Type": "text/plain;charset=UTF-8",
      Origin: origin,
    },
    body: JSON.stringify(body),
  });
  Object.defineProperty(request, "cf", { value: { country } });
  return request;
}

function tableRow(html, month) {
  const row = html.match(
    new RegExp(`<tr data-month="${month}">([\\s\\S]*?)<\\/tr>`),
  );
  assert.ok(row, `ligne mensuelle ${month} absente`);
  return row[1];
}

test("normalise uniquement les sept pages publiques et les codes pays", () => {
  assert.equal(normalizePage("/index.html"), "/");
  assert.equal(normalizePage("/cas-clients.html"), "/cas-clients.html");
  assert.equal(normalizePage("/demonstrations.html"), "/demonstrations.html");
  assert.equal(
    normalizePage("/demonstrations/ormevia-batiment.html"),
    "/demonstrations/ormevia-batiment.html",
  );
  assert.equal(normalizePage("/inconnue.html"), null);
  assert.equal(normalizeCountry("fr"), "FR");
  assert.equal(normalizeCountry("France"), "XX");
  assert.equal(normalizeCountry(undefined), "XX");
});

test("calcule correctement les fenêtres calendaires", () => {
  assert.equal(shiftDays("2026-03-01", -1), "2026-02-28");
  assert.equal(shiftMonths("2026-01", -1), "2025-12");
  assert.equal(shiftMonths("2026-12", 2), "2027-02");
  assert.deepEqual(monthlyWindow("2026-07-27"), {
    from: "2024-08-01",
    to: "2026-07-27",
  });
  assert.equal(retentionCutoff("2026-07-31"), "2024-07-31");
  assert.equal(retentionCutoff("2026-02-28"), "2024-02-28");
  assert.equal(retentionCutoff("2024-02-29"), "2022-02-28");
});

test("enregistre une page vue et une visite dans des agrégats séparés", async () => {
  const env = environment();
  const response = await worker.fetch(
    hitRequest(payload({ page: "/offres.html", source: "linkedin", device: "mobile" })),
    env,
  );

  assert.equal(response.status, 204);
  assert.equal(env.COUNTER_DB.batches.length, 1);
  const statements = env.COUNTER_DB.batches[0];
  assert.equal(statements.length, 5);
  assert.deepEqual(statements[0].parameters.slice(1), [1, 1, 0, 0]);
  assert.deepEqual(statements[1].parameters.slice(1), ["/offres.html", 1, 1, 0, 0]);
  assert.deepEqual(statements[2].parameters.slice(1), ["source", "linkedin"]);
  assert.deepEqual(statements[3].parameters.slice(1), ["device", "mobile"]);
  assert.deepEqual(statements[4].parameters.slice(1), ["country", "FR"]);
});

test("enregistre la démonstration Ormévia comme page publique", async () => {
  const env = environment();
  const response = await worker.fetch(
    hitRequest(payload({
      page: "/demonstrations/ormevia-batiment.html",
      visit: false,
      source: "internal",
    })),
    env,
  );

  assert.equal(response.status, 204);
  const statements = env.COUNTER_DB.batches[0];
  assert.equal(statements.length, 2);
  assert.deepEqual(
    statements[1].parameters.slice(1),
    ["/demonstrations/ormevia-batiment.html", 1, 0, 0, 0],
  );
});

test("n’ajoute aucune dimension sur les pages suivantes d’une visite", async () => {
  const env = environment();
  const response = await worker.fetch(
    hitRequest(payload({ page: "/methode.html", visit: false, source: "internal" })),
    env,
  );

  assert.equal(response.status, 204);
  assert.equal(env.COUNTER_DB.batches[0].length, 2);
  assert.deepEqual(env.COUNTER_DB.batches[0][0].parameters.slice(1), [1, 0, 0, 0]);
});

test("agrège les signaux de lecture sans recompter une page vue", async () => {
  const env = environment();
  const engaged = await worker.fetch(
    hitRequest(payload({ event: "engaged_30s", visit: false })),
    env,
  );
  const scrolled = await worker.fetch(
    hitRequest(payload({ event: "scroll_75", visit: false })),
    env,
  );

  assert.equal(engaged.status, 204);
  assert.equal(scrolled.status, 204);
  assert.deepEqual(env.COUNTER_DB.batches[0][0].parameters.slice(1), [0, 0, 1, 0]);
  assert.deepEqual(env.COUNTER_DB.batches[1][0].parameters.slice(1), [0, 0, 0, 1]);
});

test("refuse une origine étrangère et tout champ ou valeur non autorisé", async () => {
  const foreignEnv = environment();
  const foreign = await worker.fetch(
    hitRequest(payload(), "https://example.org"),
    foreignEnv,
  );
  assert.equal(foreign.status, 403);
  assert.equal(foreignEnv.COUNTER_DB.batches.length, 0);

  const extraEnv = environment();
  const extra = await worker.fetch(
    hitRequest({ ...payload(), userAgent: "interdit" }),
    extraEnv,
  );
  assert.equal(extra.status, 400);
  assert.equal(extraEnv.COUNTER_DB.batches.length, 0);

  const invalidEnv = environment();
  const invalid = await worker.fetch(
    hitRequest(payload({ source: "utm-campaign" })),
    invalidEnv,
  );
  assert.equal(invalid.status, 400);
  assert.equal(invalidEnv.COUNTER_DB.batches.length, 0);
});

test("protège et rend les valeurs exactes et le tableau mensuel par page", async () => {
  const env = environment();
  const refused = await worker.fetch(new Request("https://counter.example/stats"), env);
  assert.equal(refused.status, 401);

  const accepted = await worker.fetch(
    new Request("https://counter.example/stats", {
      headers: { Authorization: basicAuth("datapredict", "test-password") },
    }),
    env,
  );
  const html = await accepted.text();
  assert.equal(accepted.status, 200);
  assert.match(html, />142</);
  assert.doesNotMatch(html, /dizaine la plus proche/);
  const sourceSection = html.match(
    /<h2>Origine technique des visites — 30 jours<\/h2>[\s\S]*?<\/section>/,
  );
  assert.ok(sourceSection, "section des provenances absente");
  assert.match(sourceSection[0], /LinkedIn/);
  assert.doesNotMatch(sourceSection[0], /Autre site/);
  assert.match(
    sourceSection[0],
    /Effectif inférieur à 5 — valeur masquée/,
  );
  assert.equal(
    (html.match(/Effectif inférieur à 5 — valeur masquée/g) || []).length,
    1,
  );
  assert.match(html, /France/);
  assert.match(html, /Visible 30 s/);
  assert.match(html, /Défilement 75 %/);
  assert.match(html, /Pages vues par mois et par page — 24 mois/);
  assert.match(html, /juillet 2026/);
  assert.match(html, /<th scope="col">Accueil<\/th>/);
  assert.match(html, /<th scope="col">Offres<\/th>/);
  assert.match(html, /<th scope="col">Démonstrations<\/th>/);
  assert.match(html, /<th scope="col">Démo Ormévia<\/th>/);
  assert.match(html, /<td>8<\/td>/);
  assert.match(html, /<td>3<\/td>/);
  assert.match(html, /<strong>11<\/strong>/);
  const june = tableRow(html, "2026-06");
  assert.match(june, /juin 2026/);
  assert.match(june, /<td>0<\/td>/);
  assert.doesNotMatch(june, /—/);

  const recentEnv = environment();
  recentEnv.COLLECTION_STARTED_ON = "2026-05-12";
  const recent = await worker.fetch(
    new Request("https://counter.example/stats", {
      headers: { Authorization: basicAuth("datapredict", "test-password") },
    }),
    recentEnv,
  );
  const recentHtml = await recent.text();
  assert.equal(recent.status, 200);
  const april = tableRow(recentHtml, "2026-04");
  assert.match(april, /avril 2026/);
  assert.match(april, /<td>—<\/td>/);
});

test("refuse un tableau dont la date de début de collecte est absente", async () => {
  const env = environment();
  delete env.COLLECTION_STARTED_ON;
  const response = await worker.fetch(
    new Request("https://counter.example/stats", {
      headers: { Authorization: basicAuth("datapredict", "test-password") },
    }),
    env,
  );
  assert.equal(response.status, 503);
});

test("contrôle réellement la disponibilité de la base", async () => {
  const env = environment();
  const available = await worker.fetch(
    new Request("https://counter.example/health"),
    env,
  );
  assert.equal(available.status, 200);

  env.COUNTER_DB.healthError = true;
  const unavailable = await worker.fetch(
    new Request("https://counter.example/health"),
    env,
  );
  assert.equal(unavailable.status, 503);
});

test("purge les trois agrégats antérieurs à vingt-quatre mois", async () => {
  const env = environment();
  await worker.scheduled({}, env);
  assert.equal(env.COUNTER_DB.batches.length, 1);
  assert.equal(env.COUNTER_DB.batches[0].length, 3);
  for (const statement of env.COUNTER_DB.batches[0]) {
    assert.match(statement.parameters[0], /^\d{4}-\d{2}-\d{2}$/);
  }
});
