"""Publication controls for the approved, self-contained Jardin du chaos."""

import hashlib
import json
import re
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parents[1]
PAGE = "le-jardin-du-chaos.html"
PUBLIC_URL = "https://www.datapredict.org/" + PAGE
NAMES = (
    "pendulums", "lorenz", "fractal", "duffing", "vanderpol", "logistic", "bz", "ecology"
)
NAV_PAGES = (
    "index.html", "offres.html", "methode.html", "cas-clients.html",
    "demonstrations.html", "contact.html", "demonstrations/fissures.html", PAGE,
)
# Approved prototype 70db1634...: publication must not alter its scientific/UI modules.
SCRIPT_HASHES = {
    "physics.js": "ea063e284444e137fb46675cd1fc655b79bb17aafd125c803c76c3e1b6b2bb90",
    "visuals.js": "f7af74848f3e05b1152e2a5fca5e16683d5db1500aff29baca875ff4b8617b5d",
    "phase.js": "09896169e7259d114b23e11c27d3864338769a8b2e6f0cfb5091ee426492a5f5",
    "app.js": "8b64e121fe55f12d666dba6139709f9afcc9bc28e6fc68f75039b0a400272662",
    "lorenz.js": "14896fd37b019a40eba4138556e394345ab64aa8afce9a198b2913224c4c6edc",
    "lorenz-view.js": "337400849060773a9af51e3ed88a7e773de12711ff442e2e85ed87242df67ee5",
    "lorenz-app.js": "242d0a4fc87e78709b13fcabe1f38717482fdd1f515f6d5d74163feceea852d1",
    "fractal.js": "51df49d2dcda33661e6a0c5b242597c3df846188568869daf3f2794d22c9cfdd",
    "fractal-app.js": "d6aae7f2c6943043aa6dbeac4e0886a3c1f86a6f50dc573ca21290c4a561f7eb",
    "oscillators.js": "89b88e69dced7fad4a76956f350267c59e4d096a9298ece16ecd440d1a5d24b2",
    "populations.js": "a3d9ceea2b114af559d67ab26ba922b7897def5d7aa69092e1d1c9d53ad638fa",
    "ecology-view.js": "1e2cdee7e4e72b0740709ee2c2a5e284ccb6c7ebdae11ee90e473c3c6ce4baee",
    "chemistry.js": "f4093e21f77cd8ecec2d11d37651e653f455f748f8e8951caec81c2e6ce9e4b2",
    "lab-app.js": "7085537e182a6442406442b809244c1ba275ae7ac06090e634e961670cfbf93b",
}
PRIVATE_TABS_HASH = "664c02ce4d4641896b20efd592bced43f09e971f78b0818420eec6b577fa4079"
PUBLIC_BOOTSTRAP = "    }, 'pendulums');"
PRIVATE_BOOTSTRAP = (
    "    }, NAMES.includes(root.location.hash.slice(1))"
    " ? root.location.hash.slice(1) : 'pendulums');"
)


class PageParser(HTMLParser):
    """Read executable sources and relevant accessibility/navigation markup."""

    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
            "meta", "param", "source", "track", "wbr"}

    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.nodes = []
        self.stack = []
        self.scripts = []
        self.styles = []
        self.navs = []
        self.views = {}
        self.current_script = None
        self.current_style = None
        self.current_nav = None
        self.current_link = None
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.nodes.append((tag, attrs))
        if tag == "script":
            self.current_script = {"attrs": attrs, "body": ""}
            self.scripts.append(self.current_script)
        if tag == "style":
            self.current_style = {"attrs": attrs, "body": ""}
            self.styles.append(self.current_style)
        if tag == "nav" and "site-nav" in attrs.get("class", "").split():
            self.current_nav = []
            self.navs.append(self.current_nav)
        if tag == "a" and self.current_nav is not None:
            self.current_link = {"href": attrs.get("href", ""), "text": ""}
            self.current_nav.append(self.current_link)
        if tag == "button" and "data-lab-view" in attrs:
            panel = next(a["id"] for _, a in reversed(self.stack)
                         if a.get("id", "").startswith("panel-"))
            self.views.setdefault(panel, []).append(attrs)
        if tag not in self.VOID:
            self.stack.append((tag, attrs))

    def handle_endtag(self, tag):
        if tag == "script":
            self.current_script = None
        if tag == "style":
            self.current_style = None
        if tag == "a":
            self.current_link = None
        if tag == "nav":
            self.current_nav = None
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        if self.current_script is not None:
            self.current_script["body"] += data
        if self.current_style is not None:
            self.current_style["body"] += data
        if self.current_link is not None:
            self.current_link["text"] += data


NODE_BOOTSTRAP_CHECK = r"""
const assert = require('node:assert/strict');
const vm = require('node:vm');
const input = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const names = input.names;
class Element {
  constructor(id) {
    this.id = id; this.hidden = false; this.tabIndex = 0;
    this.attributes = {}; this.handlers = new Map(); this.focusCount = 0;
    this.innerHTML = `Existing ${id}`;
  }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  addEventListener(type, cb) {
    if (!this.handlers.has(type)) this.handlers.set(type, []);
    this.handlers.get(type).push(cb);
  }
  focus() { this.focusCount++; }
  dispatch(type, properties = {}) {
    const event = {type, target: this, defaultPrevented: false,
      preventDefault() { this.defaultPrevented = true; }, ...properties};
    for (const cb of this.handlers.get(type) || []) cb(event);
    return event;
  }
}
function fixture(hash) {
  const nodes = new Map(names.flatMap(n => ['tab-' + n, 'panel-' + n])
    .map(id => [id, new Element(id)]));
  const intro = new Element('intro'), skip = new Element('skip'), events = [];
  const document = {
    getElementById: id => nodes.get(id),
    querySelector(selector) {
      if (selector === '.intro-copy') return intro;
      if (selector === '.skip-link') return skip;
      throw Error(selector);
    },
    dispatchEvent: event => events.push(event),
  };
  const window = {document, location: {hash}, CustomEvent: class {
    constructor(type, options) { this.type = type; this.detail = options.detail; }
  }};
  vm.runInNewContext(input.source, {window}, {filename: 'public-tabs.js', timeout: 1000});
  return {window, nodes, events};
}
function checkSelection(f, expected) {
  assert.equal(f.window.ChaosTabs.selected, expected);
  for (const name of names) {
    const button = f.nodes.get('tab-' + name);
    assert.equal(button.attributes['aria-selected'], String(name === expected));
    assert.equal(button.tabIndex, name === expected ? 0 : -1);
    assert.equal(f.nodes.get('panel-' + name).hidden, name !== expected);
  }
  assert.equal(f.events.at(-1).type, 'chaos:tabchange');
  assert.equal(f.events.at(-1).detail.tab, expected);
}
let clicks = 0;
const hashes = ['', ...names.map(n => '#' + n), '#unknown'];
for (const hash of hashes) {
  const f = fixture(hash);
  checkSelection(f, 'pendulums');
  assert.equal(f.events.length, 1);
  const oldPanel = f.nodes.get('panel-pendulums');
  oldPanel.visitorState = {value: 17};
  for (const name of names) {
    f.nodes.get('tab-' + name).dispatch('click');
    checkSelection(f, name);
    assert.equal(f.window.location.hash, hash);
    clicks++;
  }
  const first = f.nodes.get('tab-pendulums');
  assert.equal(first.dispatch('keydown', {key: 'End'}).defaultPrevented, true);
  checkSelection(f, 'ecology');
  f.nodes.get('tab-ecology').dispatch('keydown', {key: 'ArrowRight'});
  checkSelection(f, 'pendulums');
  assert.equal(first.focusCount, 1);
  assert.equal(f.nodes.get('panel-pendulums'), oldPanel);
  assert.equal(oldPanel.visitorState.value, 17);
  // A fresh document (including reload with the same fragment) resets to tab 1.
  checkSelection(fixture(hash), 'pendulums');
}
console.log(JSON.stringify({fragments: hashes.length, clicks}));
"""


class ChaosPublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / PAGE).read_text(encoding="utf-8")
        cls.page = PageParser(cls.source)

    def run_node(self, code, payload):
        return subprocess.run(
            ["node", "-e", code], input=json.dumps(payload), text=True,
            capture_output=True, timeout=30, check=False,
        )

    def test_navigation_on_all_eight_pages(self):
        for filename in NAV_PAGES:
            with self.subTest(page=filename):
                page = PageParser((ROOT / filename).read_text(encoding="utf-8"))
                self.assertEqual(len(page.navs), 1)
                links = page.navs[0]
                urls = [urljoin("https://www.datapredict.org/" + filename, link["href"])
                        for link in links]
                self.assertEqual(urls.count(PUBLIC_URL), 1)
                position = urls.index(PUBLIC_URL)
                self.assertGreater(position, 0)
                self.assertLess(position, len(urls) - 1)
                self.assertEqual(urls[position - 1],
                                 "https://www.datapredict.org/demonstrations.html")
                self.assertEqual(urls[position + 1],
                                 "https://www.datapredict.org/contact.html")
                self.assertEqual(" ".join(links[position]["text"].split()),
                                 "Le jardin du chaos")

    def test_initial_tab_and_analysis_views(self):
        ids = [a["id"] for _, a in self.page.nodes if "id" in a]
        self.assertEqual(len(ids), len(set(ids)))
        tabs = [a for _, a in self.page.nodes if a.get("role") == "tab"]
        panels = [a for _, a in self.page.nodes if a.get("role") == "tabpanel"]
        self.assertEqual([a["id"] for a in tabs], ["tab-" + name for name in NAMES])
        self.assertEqual([a["id"] for a in panels], ["panel-" + name for name in NAMES])
        for index, (tab, panel) in enumerate(zip(tabs, panels, strict=True)):
            self.assertEqual(tab["aria-selected"], str(index == 0).lower())
            self.assertEqual(tab["tabindex"], "0" if index == 0 else "-1")
            self.assertEqual("hidden" in panel, index != 0)
        for model, expected in (("duffing", "section"), ("vanderpol", "section"),
                                ("ecology", "bifurcation")):
            selected = [b["data-lab-view"] for b in self.page.views["panel-" + model]
                        if b.get("aria-pressed") == "true"]
            self.assertEqual(selected, [expected], model)

    def test_approved_scripts_preserved_except_public_initial_tab(self):
        self.assertEqual(len(self.page.scripts), 15)
        for script, (name, expected) in zip(
                self.page.scripts[:-1], SCRIPT_HASHES.items(), strict=True):
            self.assertEqual(hashlib.sha256(script["body"].encode()).hexdigest(),
                             expected, name)
        tabs = self.page.scripts[-1]["body"]
        self.assertEqual(tabs.count(PUBLIC_BOOTSTRAP), 1)
        restored = tabs.replace(PUBLIC_BOOTSTRAP, PRIVATE_BOOTSTRAP, 1)
        self.assertEqual(hashlib.sha256(restored.encode()).hexdigest(), PRIVATE_TABS_HASH)

    def test_all_fifteen_inline_scripts_parse(self):
        code = (
            "const vm=require('node:vm');"
            "const sources=JSON.parse(require('node:fs').readFileSync(0,'utf8'));"
            "sources.forEach((source,i)=>new vm.Script(source,{filename:'inline-'+i}));"
            "console.log(sources.length);"
        )
        result = self.run_node(code, [s["body"] for s in self.page.scripts])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "15")

    def test_actual_public_bootstrap_ignores_fragment_and_tabs_still_work(self):
        result = self.run_node(NODE_BOOTSTRAP_CHECK, {
            "names": NAMES, "source": self.page.scripts[-1]["body"],
        })
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"fragments": 10, "clicks": 80})

    def test_fragment_regression_is_causally_rejected(self):
        tabs = self.page.scripts[-1]["body"]
        self.assertEqual(tabs.count(PUBLIC_BOOTSTRAP), 1)
        result = self.run_node(NODE_BOOTSTRAP_CHECK, {
            "names": NAMES, "source": tabs.replace(PUBLIC_BOOTSTRAP, PRIVATE_BOOTSTRAP, 1),
        })
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ERR_ASSERTION", result.stderr)
        self.assertIn("lorenz", result.stderr)
        self.assertIn("pendulums", result.stderr)

    def test_self_contained_assets_and_no_network_or_persistence(self):
        for tag, attrs in self.page.nodes:
            self.assertNotIn("srcset", attrs)
            resource = attrs.get("src")
            if tag == "link" and attrs.get("rel") != "canonical":
                resource = attrs.get("href")
            if tag == "object":
                resource = attrs.get("data")
            if resource is not None:
                self.assertTrue(resource.startswith("data:"), (tag, resource[:80]))
            if tag == "script":
                self.assertNotIn("src", attrs)
            self.assertNotIn(tag, {"iframe", "base", "form"})
        styles = "\n".join(s["body"] for s in self.page.styles)
        self.assertNotRegex(styles, r"(?i)@import\b")
        for url in re.findall(r"url\(\s*['\"]?([^)'\"]+)", styles, flags=re.I):
            self.assertTrue(url.startswith("data:"), url)
        scripts = "\n".join(s["body"] for s in self.page.scripts)
        self.assertNotRegex(scripts, r"\b(?:fetch|import|sendBeacon)\s*\(")
        self.assertNotRegex(scripts, r"\b(?:XMLHttpRequest|WebSocket|EventSource|Worker)\b")
        self.assertNotRegex(scripts, r"\b(?:localStorage|sessionStorage|indexedDB)\b")
        self.assertNotRegex(scripts, r"\bdocument\s*\.\s*cookie\b")

    def test_public_indexing_and_canonical(self):
        self.assertNotRegex(self.source, r"(?i)aperçu privé|prototype local|non publié")
        canonical = [a["href"] for tag, a in self.page.nodes
                     if tag == "link" and a.get("rel") == "canonical"]
        self.assertEqual(canonical, [PUBLIC_URL])
        for tag, attrs in self.page.nodes:
            if tag == "meta" and attrs.get("name", "").lower() in {"robots", "googlebot"}:
                self.assertNotRegex(attrs.get("content", ""), r"(?i)noindex|nofollow")


if __name__ == "__main__":
    unittest.main()
