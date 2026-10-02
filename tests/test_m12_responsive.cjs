const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

// Usage: node test_responsive.cjs [chemin/m12.js] [chemin/m12.css]
const sourcePath = process.argv[2] ? path.resolve(process.argv[2]) : path.join(__dirname, 'src/m12.js');
const cssPath = process.argv[3] ? path.resolve(process.argv[3]) : path.join(__dirname, 'src/m12.css');
const source = fs.readFileSync(sourcePath, 'utf8');
const css = fs.readFileSync(cssPath, 'utf8');
const insertionPoint = '  if (document.readyState === "loading") {';
assert.ok(source.includes(insertionPoint), 'point d’instrumentation responsive absent');

const instrumented = source.replace(
  insertionPoint,
  `  globalThis.__m12Responsive = {
    chartViewportWidth,
    responsiveProfile,
    responsiveWidthChanged,
    factorPlotHeight,
    projectionDateRange,
    applyChartHeight,
    isCompactChart,
    installResponsiveObserver,
    pruningTraceVisibility,
    pruningModeLabel,
  };\n${insertionPoint}`,
);
const context = {
  console,
  document: { readyState: 'loading', addEventListener() {} },
  window: { innerWidth: 1280 },
};
context.globalThis = context;
vm.runInNewContext(instrumented, context, { filename: sourcePath });
const responsive = context.__m12Responsive;

test('le profil dépend de la largeur actuelle du graphique, pas de sa largeur initiale', () => {
  let width = 1280;
  const chart = { getBoundingClientRect: () => ({ width }) };
  assert.equal(responsive.isCompactChart(chart, 'factors'), false);
  width = 453;
  assert.equal(responsive.isCompactChart(chart, 'factors'), true);
  width = 899;
  assert.equal(responsive.isCompactChart(chart, 'factors'), true);
  width = 900;
  assert.equal(responsive.isCompactChart(chart, 'factors'), false);
});

test('les seuils compacts sont explicites pour les trois pages', () => {
  assert.equal(responsive.responsiveProfile('factors', 899), 'compact');
  assert.equal(responsive.responsiveProfile('factors', 900), 'wide');
  assert.equal(responsive.responsiveProfile('forecast', 719), 'compact');
  assert.equal(responsive.responsiveProfile('forecast', 720), 'wide');
  assert.equal(responsive.responsiveProfile('pruning', 719), 'compact');
  assert.equal(responsive.responsiveProfile('pruning', 720), 'wide');
});

test('un changement de hauteur seul ne relance pas le redimensionnement Plotly', () => {
  assert.equal(responsive.responsiveWidthChanged(1264, 1264), false);
  assert.equal(responsive.responsiveWidthChanged(1264, 1265), false);
  assert.equal(responsive.responsiveWidthChanged(1264, 900), true);
  assert.doesNotMatch(source, /Plotly\.Plots\.resize/);
});

test('la forêt large réserve une hauteur causale aux 19 lignes', () => {
  assert.equal(responsive.factorPlotHeight(19, false), 1412);
  assert.equal(responsive.factorPlotHeight(10, false), 800);
  assert.equal(responsive.factorPlotHeight(19, true), 633);
  assert.ok((responsive.factorPlotHeight(19, false) - 120) / 19 >= 64);
  const chart = { style: {} };
  responsive.applyChartHeight(chart, responsive.factorPlotHeight(19, false));
  assert.equal(chart.style.height, '1412px');
});

test('l’observateur suit le conteneur stable du graphique', () => {
  let observed = null;
  let callbackSeen = null;
  context.window.ResizeObserver = class {
    constructor(callback) { callbackSeen = callback; }
    observe(node) { observed = node; }
  };
  const parentElement = { id: 'chart-section' };
  const chart = { parentElement };
  const callback = () => {};
  responsive.installResponsiveObserver(chart, callback);
  assert.equal(observed, parentElement);
  assert.equal(callbackSeen, callback);
  assert.ok(chart.__m12ResizeObserver);
});

test('les annotations ne prolongent pas artificiellement la projection jusqu’en 2027', () => {
  const observed = [{ time: Date.parse('2025-12-07') }, { time: Date.parse('2026-09-24') }];
  const targets = [{ time: Date.parse('2026-10-22') }];
  const range = responsive.projectionDateRange(observed, targets);
  assert.ok(range[0] < observed[0].time);
  assert.ok(range[1] > targets[0].time);
  assert.ok(range[1] < Date.parse('2026-11-05'));
  assert.match(source, /range: projectionDateRange\(observations, targets\)/);
  assert.equal(targets[0].time, Date.parse('2026-10-22'));
});

test('les trois choix du mur commandent exactement les deux traces', () => {
  assert.deepEqual(Array.from(responsive.pruningTraceVisibility('both')), [true, true]);
  assert.deepEqual(Array.from(responsive.pruningTraceVisibility('raw')), [true, false]);
  assert.deepEqual(Array.from(responsive.pruningTraceVisibility('corrected')), [false, true]);
  assert.match(responsive.pruningModeLabel('raw'), /non corrigée/);
  assert.match(responsive.pruningModeLabel('corrected'), /thermique exploratoire/);
});

test('tous les paragraphes utilisent la largeur disponible, avant et après les graphiques', () => {
  assert.match(css, /body\[data-page\]\s+p\s*\{\s*max-width:\s*none/);
  assert.doesNotMatch(css, /max-width:\s*\d+ch/);
  assert.match(css, /\.chart-section\s*>\s*#main-chart\s*~\s*p\s*,[\s\S]*?#secondary-chart\s*~\s*p\s*\{[\s\S]*?max-width:\s*none/);
});
