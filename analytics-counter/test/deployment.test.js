import assert from "node:assert/strict";
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
