import assert from "node:assert/strict";
import test from "node:test";

import worker, {
  normalizeCountry,
  normalizePage,
  retentionCutoff,
  shiftDays,
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

test("normalise uniquement les cinq pages publiques et les codes pays", () => {
  assert.equal(normalizePage("/index.html"), "/");
  assert.equal(normalizePage("/cas-clients.html"), "/cas-clients.html");
  assert.equal(normalizePage("/inconnue.html"), null);
  assert.equal(normalizeCountry("fr"), "FR");
  assert.equal(normalizeCountry("France"), "XX");
  assert.equal(normalizeCountry(undefined), "XX");
});

test("calcule correctement les fenêtres calendaires", () => {
  assert.equal(shiftDays("2026-03-01", -1), "2026-02-28");
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

test("protège et rend le tableau de statistiques enrichi", async () => {
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
  assert.match(html, /142/);
  assert.match(html, /LinkedIn/);
  assert.match(html, /France/);
  assert.match(html, /30 s actives/);
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
