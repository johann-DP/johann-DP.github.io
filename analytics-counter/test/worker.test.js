import assert from "node:assert/strict";
import test from "node:test";

import worker, {
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

  async run() {
    if (this.sql.includes("INSERT INTO page_views")) {
      this.database.hits.push(this.parameters);
    }
    if (this.sql.includes("DELETE FROM page_views")) {
      this.database.cutoffs.push(this.parameters[0]);
    }
    return { success: true };
  }

  async first() {
    if (this.sql.includes("SELECT 1 FROM page_views")) {
      if (this.database.healthError) {
        throw new Error("base indisponible");
      }
      return { 1: 1 };
    }
    return { total: 42, today: 3, last_30_days: 19 };
  }

  async all() {
    if (this.sql.includes("GROUP BY page")) {
      return { results: [{ page: "/", count: 12 }] };
    }
    return { results: [{ day: "2026-07-24", count: 3 }] };
  }
}

class FakeDatabase {
  constructor() {
    this.hits = [];
    this.cutoffs = [];
    this.healthError = false;
  }

  prepare(sql) {
    return new FakeStatement(this, sql);
  }
}

const environment = () => ({
  COUNTER_DB: new FakeDatabase(),
  ALLOWED_ORIGINS: "https://www.datapredict.org",
  ADMIN_USERNAME: "datapredict",
  ADMIN_PASSWORD: "test-password",
});

const basicAuth = (user, password) => `Basic ${Buffer.from(`${user}:${password}`).toString("base64")}`;

test("normalise uniquement les cinq pages publiques", () => {
  assert.equal(normalizePage("/index.html"), "/");
  assert.equal(normalizePage("/cas-clients.html"), "/cas-clients.html");
  assert.equal(normalizePage("/inconnue.html"), null);
});

test("calcule correctement les fenêtres calendaires", () => {
  assert.equal(shiftDays("2026-03-01", -1), "2026-02-28");
  assert.equal(retentionCutoff("2026-07-31"), "2024-07-31");
  assert.equal(retentionCutoff("2026-02-28"), "2024-02-28");
  assert.equal(retentionCutoff("2024-02-29"), "2022-02-28");
});

test("incrémente une seule page autorisée", async () => {
  const env = environment();
  const response = await worker.fetch(
    new Request("https://counter.example/hit", {
      method: "POST",
      headers: {
        "Content-Type": "text/plain;charset=UTF-8",
        "Origin": "https://www.datapredict.org",
      },
      body: JSON.stringify({ page: "/offres.html" }),
    }),
    env,
  );

  assert.equal(response.status, 204);
  assert.equal(env.COUNTER_DB.hits.length, 1);
  assert.equal(env.COUNTER_DB.hits[0][1], "/offres.html");
});

test("refuse une origine étrangère et les champs supplémentaires", async () => {
  const foreignEnv = environment();
  const foreign = await worker.fetch(
    new Request("https://counter.example/hit", {
      method: "POST",
      headers: { "Origin": "https://example.org" },
      body: JSON.stringify({ page: "/" }),
    }),
    foreignEnv,
  );
  assert.equal(foreign.status, 403);
  assert.equal(foreignEnv.COUNTER_DB.hits.length, 0);

  const extraEnv = environment();
  const extra = await worker.fetch(
    new Request("https://counter.example/hit", {
      method: "POST",
      headers: { "Origin": "https://www.datapredict.org" },
      body: JSON.stringify({ page: "/", userAgent: "interdit" }),
    }),
    extraEnv,
  );
  assert.equal(extra.status, 400);
  assert.equal(extraEnv.COUNTER_DB.hits.length, 0);
});

test("protège la page de statistiques", async () => {
  const env = environment();
  const refused = await worker.fetch(new Request("https://counter.example/stats"), env);
  assert.equal(refused.status, 401);

  const accepted = await worker.fetch(
    new Request("https://counter.example/stats", {
      headers: { "Authorization": basicAuth("datapredict", "test-password") },
    }),
    env,
  );
  assert.equal(accepted.status, 200);
  assert.match(await accepted.text(), /42/);
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

test("purge les compteurs antérieurs à vingt-quatre mois", async () => {
  const env = environment();
  await worker.scheduled({}, env);
  assert.equal(env.COUNTER_DB.cutoffs.length, 1);
  assert.match(env.COUNTER_DB.cutoffs[0], /^\d{4}-\d{2}-\d{2}$/);
});
