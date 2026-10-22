#!/usr/bin/env python3
"""Check the approved, self-contained LLM page and its frozen public evidence."""
from __future__ import annotations

import argparse
import base64
from decimal import Decimal, InvalidOperation
import hashlib
from html.parser import HTMLParser
import io
import json
from pathlib import Path, PurePosixPath
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = 'https://www.datapredict.org/demonstrations/llm-local.html'
COUNTER = '../assets/js/audience-counter.js'
SOURCE_COMMIT = '99070d77cb426dafb5efc2435eefd6e2dabe2224'
FROZEN_DATA = '4f6f3e395c3862d21167d0d12adf28630c75e9f320c90d3e76f3985366dddf9b'
FROZEN_ZIP = 'bb7a234417875e54efddd27d87667683b4e0da35f7eb4637a9f2c42b2b0208cc'
BUNDLE_FILES = {'public-data.json', 'public-proofs.zip', 'method.json', 'budget-sources.json'}
DEFAULTS = {'cost-capex': 11000, 'cost-years': 4, 'cost-hours': 880,
            'cost-electricity': 0.16242, 'cost-overhead': 100, 'cost-fixed': 120,
            'cost-human-hours': 24, 'cost-human-rate': 90}


class ReplayError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ReplayError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate JSON key: ' + key)
            result[key] = value
        return result
    def constant(value):
        raise ReplayError('non-finite JSON number: ' + value)
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def checksum_manifest(raw):
    expected = {}
    for line in raw.splitlines():
        match = re.fullmatch(r'([a-f0-9]{64})  ([A-Za-z0-9_./-]+)', line)
        require(match is not None, 'invalid checksum manifest line')
        sha, name = match.groups()
        path = PurePosixPath(name)
        require(not path.is_absolute() and '..' not in path.parts
                and path.as_posix() == name and name not in expected,
                'unsafe or duplicate checksum path')
        expected[name] = sha
    require(list(expected) == sorted(expected), 'checksum manifest must be sorted')
    return expected


class Structure(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.anchors, self.assets, self.scripts = [], [], [], []
        self.inputs, self.canonicals, self.robots = {}, [], []
        self.h1, self.titles, self.lang = 0, 0, None

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if 'id' in attrs:
            self.ids.append(attrs['id'])
        if tag == 'html':
            self.lang = attrs.get('lang')
        if tag == 'h1':
            self.h1 += 1
        if tag == 'title':
            self.titles += 1
        if tag == 'a' and attrs.get('href', '').startswith('#'):
            self.anchors.append(attrs['href'][1:])
        if 'src' in attrs:
            self.assets.append(attrs['src'])
        if tag == 'script' and 'src' in attrs:
            self.scripts.append(attrs['src'])
        if tag == 'link':
            if attrs.get('rel') == 'stylesheet':
                self.assets.append(attrs['href'])
            if attrs.get('rel') == 'canonical':
                self.canonicals.append(attrs.get('href'))
        if tag == 'meta' and attrs.get('name', '').lower() == 'robots':
            self.robots.append(attrs.get('content', '').lower())
        if tag == 'input':
            self.inputs[attrs['id']] = attrs

    handle_startendtag = handle_starttag


def validate(root=ROOT):
    root = Path(root)
    bundle = root / 'assets/llm-local'
    paths = list(bundle.rglob('*'))
    require(not any(p.is_symlink() for p in paths), 'symlink in public bundle')
    actual_names = {p.relative_to(bundle).as_posix() for p in paths if p.is_file()}
    require(actual_names == BUNDLE_FILES | {'SHA256SUMS'}, 'unexpected public bundle inventory')
    expected = checksum_manifest((bundle / 'SHA256SUMS').read_text())
    actual = {name: digest((bundle / name).read_bytes()) for name in BUNDLE_FILES}
    require(expected == actual, 'public bundle checksum mismatch')
    raw = (bundle / 'public-data.json').read_bytes()
    proof = (bundle / 'public-proofs.zip').read_bytes()
    require(digest(raw) == FROZEN_DATA, 'approved public data changed')
    require(digest(proof) == FROZEN_ZIP, 'approved proof archive changed')
    page = (root / 'demonstrations/llm-local.html').read_text()
    parsed = Structure()
    parsed.feed(page)
    require(parsed.lang == 'fr' and parsed.h1 == parsed.titles == 1, 'invalid page structure')
    require(len(parsed.ids) == len(set(parsed.ids)) and all(parsed.ids), 'duplicate or empty HTML id')
    require(set(parsed.anchors) <= set(parsed.ids), 'missing anchor target')
    require(parsed.canonicals == [CANONICAL], 'missing or incorrect canonical URL')
    require(not any('noindex' in item or 'nofollow' in item for item in parsed.robots), 'private indexing directive')
    require(parsed.scripts == [COUNTER], 'audience counter must be the only external script')
    require(all(item == COUNTER or item.startswith('data:') for item in parsed.assets), 'unexpected external asset')
    require(not re.search(r'__(BASE_CSS|PUBLIC_DATA|METHOD_DATA|APP_JS|PROOF_ZIP|LOGO)__', page), 'unexpanded template')
    def extract(identifier):
        match = re.search(r'<script id="' + identifier + r'"[^>]*>(.*?)</script>', page, re.S)
        require(match is not None, 'missing embedded evidence: ' + identifier)
        return match.group(1)
    require(extract('public-data').encode() == raw, 'embedded public data differs')
    require(base64.b64decode(extract('proof-zip'), validate=True) == proof, 'embedded archive differs')
    method = strict_json((bundle / 'method.json').read_bytes())
    require(strict_json(extract('method-data')) == method, 'embedded provenance differs')
    require(method['public_data_sha256'] == FROZEN_DATA and method['public_zip_sha256'] == FROZEN_ZIP,
            'provenance hashes differ')
    data = strict_json(raw)
    require(method['evidence_commit'] == data['provenance']['source_commit'] == SOURCE_COMMIT,
            'evidence commit differs')
    require(method['data_provenance'] == data['provenance'], 'source provenance differs')
    cases = data['cases']
    require(len(cases) == 30 and len({c['id'] for c in cases}) == 30, 'thirty unique cases required')
    for split, size, correct in [('assisted_main', 20, 20), ('assisted_challenge', 10, 6)]:
        cohort = [c for c in cases if c['split'] == split]
        require(len(cohort) == data['groups'][split]['planned'] == size, 'cohort denominator differs')
        require(sum(c['score']['conform'] for c in cohort) == data['groups'][split]['conform'] == correct,
                'cohort score differs')
    require([c['index'] for c in cases if not c['score']['conform']] == [22, 23, 26, 29], 'four failures differ')
    require(sum(bool(c['score']['critical_errors']) for c in cases) == data['summary']['critical_responses'] == 4,
            'critical response count differs')
    require(data['summary']['human_review_count'] == 0 and not data['summary']['independent_generalization'],
            'unproven human review or generalization')
    budget = strict_json((bundle / 'budget-sources.json').read_bytes())
    require(method['budget'] == budget, 'budget provenance differs')
    require({key: value['value'] for key, value in budget['defaults'].items()} == DEFAULTS, 'approved budget defaults differ')
    for identifier, value in DEFAULTS.items():
        attrs = parsed.inputs[identifier]
        amount = Decimal(attrs['value'])
        require(amount == Decimal(str(value)), 'HTML budget default differs: ' + identifier)
        lower, upper, step = map(Decimal, (attrs['min'], attrs['max'], attrs['step']))
        require(lower <= amount <= upper and step > 0 and (amount - lower) % step == 0,
                'invalid budget input constraint: ' + identifier)
    edf = next(source for source in budget['sources'] if source['id'] == 'edf')
    require(Decimal(str(DEFAULTS['cost-electricity'])) == Decimal(str(edf['base_eur_per_kwh_before_taxes']))
            + Decimal(str(edf['excise_eur_per_mwh_ex_vat'])) / 1000, 'electricity tax or unit mismatch')
    with zipfile.ZipFile(io.BytesIO(proof)) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)) == 11 and archive.testzip() is None, 'invalid proof archive')
        manifest = checksum_manifest(archive.read('SHA256SUMS-public.txt').decode())
        require(set(manifest) == set(names) - {'SHA256SUMS-public.txt'}, 'archive inventory differs')
        require(all(digest(archive.read(name)) == sha for name, sha in manifest.items()), 'archive checksum differs')
        require(archive.read('public-data.json') == raw, 'archive data differs')
    return {'status': 'VALIDÉ', 'cases': 30, 'main_conform': 20, 'challenge_conform': 6,
            'critical_responses': 4, 'budget_defaults_valid': 8, 'archive_files': 11,
            'files': len(actual_names), 'html_sha256': digest(page.encode()), 'embedded_files_identical': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        print('LLM_PUBLIC_CONTRACT_OK ' + json.dumps(validate(args.root), ensure_ascii=False))
    except (OSError, ValueError, TypeError, KeyError, StopIteration, InvalidOperation, zipfile.BadZipFile) as error:
        parser.exit(1, f'LLM_PUBLIC_CONTRACT_FAILED: {error}\n')
