const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const assets = path.resolve(__dirname, '../assets/analyses/demo-2/m12/assets');
const live = require(path.join(assets, 'm12-live.js'));
const baseline = { coefficient_mm_per_c: -.1, reference_c: 15.1 };

function payload(day='2026-10-25', hours=[1,2,2,3]) {
  const rows = hours.map((hour, i) => {
    const row = Array(29).fill(null);
    row[1] = `${day} ${String(hour).padStart(2,'0')}:00:00`;
    row[0] = Date.parse(row[1].replace(' ','T')+'Z'); // Civil-axis coordinate only.
    row[4] = 36; row[5] = .1 + i/100;
    row[11] = false; row[12] = false;
    row[14] = hour===2 ? 'CLOCK_AMBIGUOUS_OR_NONEXISTENT' : 'NO_EXACT_OUTDOOR_TEMPERATURE';
    row[27] = 100 + i*236; row[28] = 335 + i*236;
    return row;
  });
  return { metadata: { conversion_factor_mm_per_inch:25.4, thermal_coefficient_mm_per_c:-.1,
      global_reference_temperature_c:15.1 }, origins:[{id:36,n:rows.length,center_mm:0}], thermal_extended:rows };
}
function document(value) {
  return '<script id="processed-signal-payload" type="application/json">'+JSON.stringify(value)+'</script>';
}

test('le lecteur réel conserve les deux heures civiles avec leurs identités distinctes', () => {
  const value = live.comparatorData(document(payload()), baseline);
  assert.equal(value.series.length, 4);
  assert.equal(value.series[1].timestamp_ms, value.series[2].timestamp_ms);
  assert.equal(value.series[1].date, value.series[2].date);
  assert.deepEqual(value.series.map(r=>r.source_hour_occurrence), [1,1,2,1]);
  assert.equal(value.series[2].source_line_min, 572);
  assert.equal(value.series[1].corrected_mm, null);
  assert.equal(value.series[2].corrected_mm, null);
});

test('le lecteur rejette doublon ordinaire, troisième occurrence et correction thermique ambiguë', () => {
  for (const value of [payload('2026-10-24'), payload('2026-10-25',[1,2,2,2,3])]) {
    assert.throws(()=>live.comparatorData(document(value),baseline), /Heure répétée/);
  }
  const value=payload(); value.thermal_extended[2][8]=12.5;
  assert.throws(()=>live.comparatorData(document(value),baseline), /Heure ambiguë/);
  const singleton=payload('2026-10-25',[1,2,3]);
  assert.equal(live.comparatorData(document(singleton),baseline).series.length,3);
  singleton.thermal_extended[1][8]=12.5;
  assert.throws(()=>live.comparatorData(document(singleton),baseline), /Heure ambiguë/);
  const forged=payload(); forged.thermal_extended[2][0]+=1;
  assert.throws(()=>live.comparatorData(document(forged),baseline), /Valeurs horaires/);
});

test('renderPruning garde les deux points, coupe la verticale et distingue survol et clavier', async () => {
  const source = fs.readFileSync(path.join(assets,'m12.js'),'utf8');
  const insertion='  if (document.readyState === "loading") {';
  assert.ok(source.includes(insertion));
  const instrumented=source.replace(insertion, `
    makePruningToolbar=()=>({select:{addEventListener(){}}});
    renderInterventionStatus=()=>{};
    appendPruningTechnical=()=>{};
    createPointBrowser=(_chart,items)=>{globalThis.clockItems=items;};
    globalThis.clockRender=renderPruning;
  ${insertion}`);
  let traces;
  const context={console, document:{readyState:'loading',addEventListener(){},getElementById(){return null;}},
    window:{innerWidth:1200,Plotly:{react:async(_chart,value)=>{traces=value;}}}};
  context.globalThis=context;
  vm.runInNewContext(instrumented,context);
  const chart={style:{},getBoundingClientRect:()=>({width:500}),setAttribute(){}};
  const value=live.comparatorData(document(payload()),baseline);
  await context.clockRender({comparator_series:value.series,comparator:baseline},chart);
  const raw=traces[0];
  assert.deepEqual(Array.from(raw.y), [.1,.11,null,.12000000000000001,.13]);
  assert.equal(raw.x[1],raw.x[3]);
  assert.match(raw.customdata[1][0], /1re occurrence/);
  assert.match(raw.customdata[3][0], /2e occurrence/);
  assert.match(context.clockItems[1].label, /1re occurrence/);
  assert.match(context.clockItems[2].label, /2e occurrence/);
  assert.equal(context.clockItems.length,4);
});
