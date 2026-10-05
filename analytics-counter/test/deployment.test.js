import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const workflow = readFileSync(new URL("../../.github/workflows/audience-counter-deploy.yml", import.meta.url), "utf8");
const steps = workflow.split(/^      - name:/m).slice(1);
const passwordWrites = steps.filter((step) => /\bwrangler secret (put|bulk|delete)\b/.test(step));

function writesEnabled(configureAdminPassword) {
  return passwordWrites.filter((step) => {
    const guard = step.match(/^        if: \$\{\{ (.+) \}\}$/m)?.[1];
    if (!guard) return true;
    return vm.runInNewContext(guard, { inputs: { configure_admin_password: configureAdminPassword } }) === true;
  });
}

test("la configuration explicite valide le mot de passe avant toute modification en production", () => {
  const firstProduction = steps.findIndex((step) => (
    /\bwrangler d1 migrations apply[^\n]*--remote|\bwrangler deploy\b/.test(step)
  ));
  assert.ok(firstProduction >= 0, "aucune étape de publication détectée");
  const preflightIndex = steps.findIndex((step) => (
    step.startsWith(" Vérifier le mot de passe avant publication\n")
  ));
  assert.ok(preflightIndex >= 0, "validation du mot de passe absente avant publication");
  assert.ok(preflightIndex < firstProduction, "validation du mot de passe trop tardive");
  const preflight = steps[preflightIndex];
  assert.match(preflight, /^        if: \$\{\{ inputs\.configure_admin_password == true \}\}$/m);
  assert.match(preflight, /^          COUNTER_ADMIN_PASSWORD: \$\{\{ secrets\.COUNTER_ADMIN_PASSWORD \}\}$/m);
  const guard = preflight.match(/^        if: \$\{\{ (.+) \}\}$/m)[1];
  for (const mode of [false, undefined]) {
    assert.equal(vm.runInNewContext(guard, { inputs: { configure_admin_password: mode } }), false);
    const passwordSteps = steps.slice(0, firstProduction).filter((step) => (
      /COUNTER_ADMIN_PASSWORD/.test(step)
    ));
    for (const step of passwordSteps) {
      const condition = step.match(/^        if: \$\{\{ (.+) \}\}$/m)?.[1];
      assert.ok(condition, "mot de passe chargé sans choix explicite");
      assert.equal(vm.runInNewContext(condition, { inputs: { configure_admin_password: mode } }), false);
    }
  }
  assert.equal(vm.runInNewContext(guard, { inputs: { configure_admin_password: true } }), true);
  const command = preflight.match(/^        run: (.+)$/m)?.[1];
  assert.ok(command, "contrôle du mot de passe absent");
  assert.match(command, /^test "\$\{#COUNTER_ADMIN_PASSWORD\}" -ge 32$/);
  for (const password of ["", "synthetic-too-short"]) {
    const result = spawnSync("bash", ["-c", command], {
      env: { COUNTER_ADMIN_PASSWORD: password }, encoding: "utf8",
    });
    assert.equal(result.status, 1, "mot de passe absent ou court accepté");
    assert.equal(result.stdout, "");
  }
  const valid = spawnSync("bash", ["-c", command], {
    env: { COUNTER_ADMIN_PASSWORD: "synthetic-password-for-workflow-test" }, encoding: "utf8",
  });
  assert.equal(valid.status, 0);
});

async function executeVerification(configureAdminPassword) {
  const verification = steps.find((step) => step.startsWith(" Vérifier le service déployé\n"));
  const code = verification.match(/          node - <<'NODE'\n([\s\S]+?)^          NODE$/m)[1].replace(/^ {10}/gm, "");
  const calls = [];
  await vm.runInNewContext(code, {
    Buffer,
    process: {
      env: {
        COUNTER_WORKER_URL: "https://counter.example.workers.dev",
        CONFIGURE_ADMIN_PASSWORD: String(configureAdminPassword),
        COUNTER_ADMIN_PASSWORD: "local-test-password",
      },
      exit(code) { throw new Error(`verification exit ${code}`); },
    },
    console: { warn() {}, error() {} },
    setTimeout(callback) { callback(); },
    async fetch(url, options) {
      calls.push({ url, options });
      if (url.endsWith("/health")) return Response.json({ status: "ok" });
      if (!options?.headers?.Authorization) return new Response(null, { status: 401 });
      if (!configureAdminPassword) return new Response(null, { status: 401 });
      assert.equal(options.headers.Authorization, `Basic ${Buffer.from("datapredict:local-test-password").toString("base64")}`);
      return new Response('Audience datapredict <section id="campaigns">');
    },
  });
  return calls;
}

test("un déploiement ordinaire ne peut pas réécrire le mot de passe existant", () => {
  const input = workflow.match(/^      configure_admin_password:\n((?:        [^\n]*\n)+)/m)?.[1];
  assert.ok(input, "le choix explicite de configuration est absent");
  assert.match(input, /^        type: boolean$/m);
  assert.match(input, /^        default: false$/m);
  assert.equal(writesEnabled(false).length, 0);
  assert.equal(writesEnabled(undefined).length, 0);
});

test("seul le choix explicite peut réappliquer le mot de passe GitHub", () => {
  assert.equal(passwordWrites.length, 1);
  assert.equal(writesEnabled(true).length, 1);
  assert.match(passwordWrites[0], /^        if: \$\{\{ inputs\.configure_admin_password == true \}\}$/m);
  assert.match(passwordWrites[0], /wrangler secret put ADMIN_PASSWORD/);
  assert.match(passwordWrites[0], /COUNTER_ADMIN_PASSWORD: \$\{\{ secrets\.COUNTER_ADMIN_PASSWORD \}\}/);
  assert.match(passwordWrites[0], /test "\$\{#COUNTER_ADMIN_PASSWORD\}" -ge 32/);
});

test("le contrôle normal ne tente pas le mot de passe GitHub, le choix explicite le vérifie", async () => {
  const normal = await executeVerification(false);
  assert.equal(normal.length, 2);
  assert.equal(normal.some((call) => call.options?.headers?.Authorization), false);
  const configured = await executeVerification(true);
  assert.equal(configured.length, 3);
  assert.equal(configured[2].url, "https://counter.example.workers.dev/stats");
  const verification = steps.find((step) => step.startsWith(" Vérifier le service déployé\n"));
  assert.match(verification, /COUNTER_ADMIN_PASSWORD: \$\{\{ inputs\.configure_admin_password && secrets\.COUNTER_ADMIN_PASSWORD \|\| '' \}\}/);
});
