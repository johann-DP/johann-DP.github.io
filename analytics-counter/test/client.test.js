import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

import worker, { normalizePage } from "../src/worker.js";

const script = readFileSync(new URL("../../assets/js/audience-counter.js", import.meta.url), "utf8");
const sitemap = readFileSync(new URL("../../sitemap.xml", import.meta.url), "utf8");

function visit(path, options = {}) {
  const location = new URL(path, "https://www.datapredict.org");
  const requests = [];
  const storage = options.storage || new Map();
  const documentListeners = new Map();
  const windowListeners = new Map();
  const timers = [];
  let now = 0;
  const document = {
    cookie: options.cookie || "",
    referrer: options.referrer || "",
    visibilityState: "visible",
    readyState: "complete",
    documentElement: { scrollHeight: 1000, offsetHeight: 1000 },
    body: { scrollHeight: 1000, offsetHeight: 1000 },
    querySelectorAll: () => [],
    addEventListener: (name, callback) => documentListeners.set(name, callback),
    removeEventListener: (name) => documentListeners.delete(name),
  };
  const window = {
    doNotTrack: options.windowDnt,
    scrollY: 0,
    innerHeight: 500,
    addEventListener: (name, callback) => windowListeners.set(name, callback),
    removeEventListener: (name) => windowListeners.delete(name),
  };
  vm.runInNewContext(script, {
    URL,
    document,
    window,
    location,
    history: { replaceState() {} },
    navigator: { userAgent: "Desktop", ...options.navigator },
    sessionStorage: {
      getItem(key) {
        if (options.storageUnavailable) throw new Error("storage unavailable");
        return storage.get(key) || null;
      },
      setItem(key, value) {
        if (options.storageUnavailable) throw new Error("storage unavailable");
        storage.set(key, value);
      },
    },
    fetch(url, init) {
      requests.push({ url, init, payload: JSON.parse(init.body) });
      return Promise.resolve();
    },
    performance: { now: () => now },
    setTimeout(callback) { timers.push(callback); return timers.length; },
    clearTimeout() {},
    requestAnimationFrame: (callback) => callback(),
  });
  return {
    requests,
    storage,
    document,
    engage() { now = 30_000; timers.shift()?.(); },
    scroll() { window.scrollY = 300; windowListeners.get("scroll")?.(); },
  };
}

test("chaque page du sitemap émet une page vue acceptée par le Worker", () => {
  const paths = [...sitemap.matchAll(/<loc>([^<]+)<\/loc>/g)].map((match) => new URL(match[1]).pathname);
  assert.equal(paths.length, 9);
  for (const path of paths) {
    const { requests } = visit(path);
    assert.equal(requests.length, 1, `page non comptée : ${path}`);
    assert.equal(requests[0].payload.event, "pageview");
    assert.equal(requests[0].payload.page, normalizePage(path));
  }
  assert.equal(visit("/inconnue.html").requests.length, 0);
  assert.equal(visit("/index.html").requests[0].payload.page, "/");
});

test("une campagne LinkedIn valide attribue une visite sans URL ni identifiant", () => {
  const { requests, storage } = visit("/?utm_source=LinkedIn&utm_medium=social&utm_campaign=dp-gouvernance-run&utm_content=ignored", {
    referrer: "",
  });
  assert.deepEqual(requests[0].payload, {
    page: "/", event: "pageview", visit: true, source: "linkedin", device: "desktop",
    campaign: { source: "linkedin", medium: "social", name: "dp-gouvernance-run" },
  });
  assert.deepEqual([...storage.values()], ["1"]);
  assert.equal(requests[0].init.credentials, "omit");
  assert.equal(requests[0].init.referrerPolicy, "no-referrer");
  assert.equal(requests[0].init.body.includes("utm_"), false);
});

test("les paramètres inconnus, personnels ou incomplets n’empêchent pas une page vue", () => {
  for (const query of [
    "utm_source=linkedin&utm_medium=social",
    "utm_source=unknown&utm_medium=social&utm_campaign=dp-test",
    "utm_source=linkedin&utm_medium=unknown&utm_campaign=dp-test",
    "utm_source=linkedin&utm_medium=social&utm_campaign=johann@example.com",
    "utm_source=linkedin&utm_medium=social&utm_campaign=dp--test",
    `utm_source=linkedin&utm_medium=social&utm_campaign=dp-${"a".repeat(62)}`,
    "utm_source=linkedin&utm_medium=social&utm_campaign=dp-%3Cscript%3E",
    "utm_source=linkedin&utm_source=google&utm_medium=social&utm_campaign=dp-test",
  ]) {
    const { requests } = visit(`/?${query}`);
    assert.equal(requests.length, 1);
    assert.equal(Object.hasOwn(requests[0].payload, "campaign"), false, query);
    assert.equal(requests[0].payload.source, "direct");
  }
});

test("les liens ordinaires gardent le contrat existant et leur provenance", () => {
  const { requests } = visit("/offres.html", { referrer: "https://www.linkedin.com/feed/" });
  assert.deepEqual(requests[0].payload, {
    page: "/offres.html", event: "pageview", visit: true, source: "linkedin", device: "desktop",
  });
});

test("une campagne n’est transmise que pour la première page vue de la visite", () => {
  const tracked = visit("/?utm_source=linkedin&utm_medium=social&utm_campaign=dp-pmo-data");
  tracked.engage();
  tracked.scroll();
  assert.deepEqual(tracked.requests.map(({ payload }) => payload.event), ["pageview", "engaged_30s", "scroll_75"]);
  assert.equal(Object.hasOwn(tracked.requests[0].payload, "campaign"), true);
  for (const { payload } of tracked.requests.slice(1)) assert.equal(Object.hasOwn(payload, "campaign"), false);
  const next = visit("/offres.html?utm_source=linkedin&utm_medium=social&utm_campaign=dp-pmo-data", { storage: tracked.storage });
  assert.equal(next.requests[0].payload.visit, false);
  assert.equal(Object.hasOwn(next.requests[0].payload, "campaign"), false);
});

test("l’opposition, GPC et Do Not Track bloquent aussi les campagnes", () => {
  for (const options of [
    { cookie: "datapredict_audience_optout=1" },
    { navigator: { globalPrivacyControl: true } },
    { navigator: { doNotTrack: "1" } },
    { windowDnt: "1" },
  ]) {
    const tracked = visit("/?utm_source=linkedin&utm_medium=social&utm_campaign=dp-test", options);
    assert.equal(tracked.requests.length, 0);
    assert.equal(tracked.storage.size, 0);
  }
  const tracked = visit("/?utm_source=linkedin&utm_medium=social&utm_campaign=dp-test");
  tracked.document.cookie = "datapredict_audience_optout=1";
  tracked.engage();
  assert.equal(tracked.requests.length, 1);
});

test("sans stockage de session, les pages vues restent mesurées sans visite ni campagne", () => {
  const { requests } = visit("/?utm_source=linkedin&utm_medium=social&utm_campaign=dp-test", { storageUnavailable: true });
  assert.equal(requests.length, 1);
  assert.equal(requests[0].payload.visit, false);
  assert.equal(Object.hasOwn(requests[0].payload, "campaign"), false);
});

test("le Worker accepte les campagnes produites par le navigateur", async () => {
  for (const [source, medium, category] of [
    ["linkedin", "social", "linkedin"],
    ["google", "cpc", "search"],
    ["bing", "organic", "search"],
    ["newsletter", "email", "other-site"],
    ["partner", "referral", "other-site"],
  ]) {
    const { requests } = visit(`/demonstrations/nerivane-distribution.html?utm_source=${source}&utm_medium=${medium}&utm_campaign=dp-${"a".repeat(61)}`);
    assert.equal(requests[0].payload.source, category);
    const database = {
      prepare(sql) { return { bind(...parameters) { return { sql, parameters }; } }; },
      async batch(statements) { return statements.map(() => ({ success: true })); },
    };
    const response = await worker.fetch(new Request(requests[0].url, {
      method: "POST",
      headers: { Origin: "https://www.datapredict.org", "Content-Type": "text/plain;charset=UTF-8" },
      body: requests[0].init.body,
    }), { COUNTER_DB: database, ALLOWED_ORIGINS: "https://www.datapredict.org" });
    assert.equal(response.status, 204, `${source} : ${await response.text()}`);
  }
});
