/* Read the same approved public masters as Step 2. Never run a source script. */
(function (root) {
  'use strict';
  const BASE = '/assets/figures/demo-2/';
  const requireThat = (ok, message) => { if (!ok) throw new Error(message); };
  const finite = value => typeof value === 'number' && Number.isFinite(value);

  function arrayAssignment(html, name) {
    const match = new RegExp('\\bconst\\s+' + name + '\\s*=\\s*').exec(html);
    requireThat(match, 'Structure du maître de fissure non reconnue.');
    const start = match.index + match[0].length;
    requireThat(html[start] === '[', 'Tableau de mesures absent.');
    let depth = 0, quoted = false, escaped = false;
    for (let i = start; i < html.length; i += 1) {
      const char = html[i];
      if (quoted) {
        if (escaped) escaped = false;
        else if (char === '\\') escaped = true;
        else if (char === '"') quoted = false;
      } else if (char === '"') quoted = true;
      else if (char === '[' || char === '{') depth += 1;
      else if (char === ']' || char === '}') {
        depth -= 1;
        if (depth === 0) return JSON.parse(html.slice(start, i + 1));
      }
    }
    throw new Error('Tableau de mesures incomplet.');
  }

  function crackMeasurements(html) {
    const trace = arrayAssignment(html, 'data').find(t => t.name === 'Mesures récentes');
    requireThat(trace && Array.isArray(trace.x) && Array.isArray(trace.y), 'Mesures récentes absentes.');
    requireThat(trace.x.length === trace.y.length && trace.x.length > 0, 'Dates et valeurs incohérentes.');
    let previous = '';
    return trace.x.map((stamp, i) => {
      requireThat(typeof stamp === 'string' && /^\d{4}-\d{2}-\d{2}T00:00:00$/.test(stamp), 'Date de mesure non conforme.');
      const date = stamp.slice(0, 10);
      requireThat(date > previous && finite(trace.y[i]), 'Ordre ou valeur de mesure invalide.');
      previous = date;
      return {date, value_mm: trace.y[i]};
    });
  }

  function comparatorData(html, baseline) {
    const match = /<script id="processed-signal-payload" type="application\/json">([\s\S]*?)<\/script>/.exec(html);
    requireThat(match, 'Données traitées du mur absentes.');
    const payload = JSON.parse(match[1]);
    const meta = payload.metadata;
    requireThat(meta && Array.isArray(payload.origins) && Array.isArray(payload.thermal_extended), 'Structure du mur non reconnue.');
    requireThat(meta.conversion_factor_mm_per_inch === 25.4, 'Unité du maître non reconnue.');
    requireThat(meta.thermal_coefficient_mm_per_c === baseline.coefficient_mm_per_c, 'Méthode thermique modifiée : revue nécessaire.');
    requireThat(meta.global_reference_temperature_c === baseline.reference_c, 'Référence thermique modifiée : revue nécessaire.');
    const segment = Math.max(...payload.origins.map(o => o.id));
    const origin = payload.origins.find(o => o.id === segment);
    requireThat(origin && finite(origin.center_mm), 'Référence du segment absente.');
    const raw = payload.thermal_extended.filter(row => row[4] === segment);
    requireThat(raw.length > 0 && raw.length === origin.n, 'Support du segment incomplet.');
    let previous = -Infinity;
    const counts = {raw: raw.length, corrected: 0, missing_temperature: 0, out_of_domain: 0, other_missing: 0};
    const series = raw.map(row => {
      requireThat(row.length === 29 && finite(row[0]) && row[0] > previous && finite(row[5]), 'Valeurs horaires non conformes.');
      requireThat(typeof row[1] === 'string' && /^\d{4}-\d{2}-\d{2} \d{2}:00:00$/.test(row[1]), 'Heure source non conforme.');
      requireThat(new Date(row[0]).toISOString().slice(0,19).replace('T',' ') === row[1], 'Incohérence de l’axe et de l’heure source.');
      previous = row[0];
      const allowed = row[12] === true && row[11] === true;
      requireThat(!allowed || (finite(row[9]) && finite(row[8])), 'Correction sans composante ou température.');
      if (allowed) counts.corrected += 1;
      else if (row[14] === 'NO_EXACT_OUTDOOR_TEMPERATURE') counts.missing_temperature += 1;
      else if (row[14] === 'OUTSIDE_DOCUMENTED_TEMPERATURE_DOMAIN') counts.out_of_domain += 1;
      else counts.other_missing += 1;
      const reason = allowed ? null : row[14] === 'NO_EXACT_OUTDOOR_TEMPERATURE' ? 'Température exacte indisponible' : row[14] === 'OUTSIDE_DOCUMENTED_TEMPERATURE_DOMAIN' ? 'Température hors domaine documenté' : 'Correction indisponible selon les contrôles de la source';
      return {date: row[1].replace(' ','T'), timestamp_ms:row[0], raw_mm:row[5]-origin.center_mm, corrected_mm:allowed ? row[5]-row[9]-origin.center_mm : null, temperature_c:finite(row[8]) ? row[8] : null, missing_reason:reason};
    });
    return {series, segment, center_mm:origin.center_mm, counts, period:{start:series[0].date,end:series.at(-1).date}, continuity_changed:segment !== baseline.segment};
  }

  async function source(path) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch(BASE + path, {cache:'no-cache', credentials:'same-origin', signal:controller.signal});
      requireThat(response.ok, 'Source publiée momentanément indisponible.');
      const type = response.headers && response.headers.get('content-type');
      requireThat(!type || /text\/html/.test(type), 'Type de source publié non reconnu.');
      return await response.text();
    } finally { clearTimeout(timeout); }
  }

  function setText(selector, text) {
    const element = document.querySelector(selector);
    if (element) element.textContent = text;
  }
  const frDate = value => new Date(value.slice(0,10)+'T12:00:00').toLocaleDateString('fr-FR', {day:'numeric',month:'long',year:'numeric'});

  async function refresh(page, data) {
    const banner = document.getElementById('freshness-status');
    const checked = new Date().toLocaleTimeString('fr-FR', {hour:'2-digit',minute:'2-digit'});
    try {
      if (page === 'pruning') {
        const live = comparatorData(await source('retaining-wall-sensor-processed-v2.html'), data.comparator);
        data.comparator_series = live.series;
        Object.assign(data.comparator, {segment:live.segment,center_mm:live.center_mm,counts:live.counts,period:live.period,continuity_changed:live.continuity_changed});
        setText('.metrics .metric:nth-child(2) strong', live.counts.raw.toLocaleString('fr-FR'));
        setText('.metrics .metric:nth-child(3) strong', live.counts.corrected.toLocaleString('fr-FR'));
        setText('.metrics .metric:nth-child(3) small', `${live.counts.missing_temperature} températures absentes ; ${live.counts.out_of_domain} hors domaine ; ${live.counts.other_missing} autres indisponibilités`);
        setText('#thermal-support-copy', `${live.counts.raw.toLocaleString('fr-FR')} valeurs horaires, du ${frDate(live.period.start)} au ${frDate(live.period.end)}. Le graphique suit automatiquement le maître traité de l’étape 2. Un seul segment est montré, sans raccord de niveaux.`);
        setText('#thermal-missing-copy', `${live.counts.corrected.toLocaleString('fr-FR')} valeurs corrigées ; ${live.counts.raw-live.counts.corrected} corrections absentes selon les contrôles de la source. Le détail est disponible point par point. Les trous ne sont pas comblés.`);
        setText('#thermal-center-copy', `Les deux séries sont exprimées relativement au même centre de segment : ${live.center_mm.toLocaleString('fr-FR')} mm. Une actualisation de cette référence graphique ne représente pas un déplacement physique.`);
        if (banner) banner.textContent = `Dernières mesures du mur : ${frDate(live.period.end)} à ${live.period.end.slice(11,16)} (heure du capteur). Mise à jour vérifiée à ${checked}.` + (live.continuity_changed ? ' Nouvelle période de mesure : son niveau ne peut pas être comparé directement à celui de la période précédente.' : '');
      } else {
        const live = crackMeasurements(await source('fissure-recente-meme-format.html'));
        const last = live.at(-1);
        const analysisCutoff = data.cutoff_date || data.analysis_cutoff || '2026-09-24';
        if (page === 'forecast') {
          const original = data.measurements;
          const baseMap = new Map(live.map(r=>[r.date,r.value_mm]));
          const frozenHistory = original.filter(r=>r.date<=analysisCutoff);
          const currentHistory = live.filter(r=>r.date<=analysisCutoff);
          requireThat(currentHistory.length === frozenHistory.length && frozenHistory.every((r,i)=>currentHistory[i].date===r.date && currentHistory[i].value_mm===r.value_mm), 'Historique de mesure révisé : simulation à revoir.');
          data.measurements = live;
          data.latest_observation_date = last.date;
          data.simulation.outdated_by_new_measurements = last.date > data.simulation.data_cutoff.slice(0,10);
          const today = new Date().toLocaleDateString('en-CA', {timeZone:'Europe/Paris'});
          data.simulation.targets = data.simulation.targets.map(target => {
            const exact = baseMap.get(target.date);
            return {...target,
              observed_mm: exact === undefined ? null : exact,
              residual_mm: exact === undefined ? null : exact-target.predicted_mm,
              observation_status: exact !== undefined ? 'OBSERVÉE_EXACTE' : target.date < today ? 'OBSERVATION_EXACTE_ABSENTE' : 'NON_ÉCHUE',
              observation_label: exact !== undefined ? (data.simulation.issued_at ? 'Mesure exacte disponible — comparaison avec la prévision datée, sans conclusion de validation' : 'Mesure exacte disponible — simulation rétrospective, pas validation prospective') : target.date < today ? 'Échéance passée, mesure exacte non disponible' : 'Échéance à venir ; mesure non disponible',
            };
          });
          setText('.metrics .metric:first-child strong', frDate(last.date));
          setText('.metrics .metric:first-child small', `${last.value_mm.toLocaleString('fr-FR',{minimumFractionDigits:2})} mm ; source identique à l’étape 2`);
          setText('#measurement-support-copy', `${live.length} relevés, du ${frDate(live[0].date)} au ${frDate(last.date)}. Seul un extrait est affiché pour garder le contexte lisible ; dates et valeurs restent exactes.`);
        }
        if (banner) banner.textContent = `Dernier relevé de fissure : ${frDate(last.date)}. Analyse sur les mesures disponibles jusqu’au ${frDate(analysisCutoff)}. Mise à jour vérifiée à ${checked}.` + (last.date>analysisCutoff ? ' Des relevés plus récents sont disponibles ; l’analyse n’a pas encore été recalculée.' : '');
      }
      if (banner) banner.dataset.state = 'current';
      data.live_source_status = 'VERIFIED_PUBLISHED_SOURCE';
    } catch (error) {
      if (banner) {
        banner.dataset.state = 'unavailable';
        banner.textContent = `Actualisation non confirmée : ${error.message} Les données datées de cette page restent affichées ; leur actualité n’est pas garantie.`;
      }
      data.live_source_status = 'BASELINE_ONLY_REFRESH_UNCONFIRMED';
    }
    const download = document.querySelector('a[download]');
    if (download && typeof URL.createObjectURL === 'function') {
      if (download.dataset.liveUrl) URL.revokeObjectURL(download.dataset.liveUrl);
      const url = URL.createObjectURL(new Blob([JSON.stringify(data,null,2)], {type:'application/json'}));
      download.href = url;
      download.download = page+'-donnees-affichees.json';
      download.dataset.liveUrl = url;
    }
    return data;
  }
  root.M12Live = {refresh, crackMeasurements, comparatorData, arrayAssignment};
  if (typeof module !== 'undefined' && module.exports) module.exports = root.M12Live;
})(typeof window === 'undefined' ? globalThis : window);
