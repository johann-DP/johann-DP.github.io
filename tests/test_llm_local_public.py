"""Causal controls for the approved page and its frozen downloadable evidence."""
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('llm_public', ROOT / 'scripts/validate_llm_local.py')
llm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(llm)


class PublicPageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(ROOT / 'assets/llm-local', self.root / 'assets/llm-local')
        (self.root / 'demonstrations').mkdir()
        self.page = self.root / 'demonstrations/llm-local.html'
        shutil.copyfile(ROOT / 'demonstrations/llm-local.html', self.page)
        self.bundle = self.root / 'assets/llm-local'

    def change_page(self, old, new):
        content = self.page.read_text()
        self.assertIn(old, content)
        self.page.write_text(content.replace(old, new, 1))

    def refresh_manifest(self):
        (self.bundle / 'SHA256SUMS').write_text(''.join(
            f'{llm.digest((self.bundle / name).read_bytes())}  {name}\n'
            for name in sorted(llm.BUNDLE_FILES)))

    def test_approved_page_and_sources(self):
        result = llm.validate(self.root)
        self.assertEqual((result['main_conform'], result['challenge_conform'], result['critical_responses']), (20, 6, 4))
        self.assertEqual(result['budget_defaults_valid'], 8)
        self.assertTrue(result['embedded_files_identical'])

    def test_embedded_data_tampering_is_rejected(self):
        self.change_page('<script id="public-data" type="application/json">',
                         '<script id="public-data" type="application/json">\n')
        with self.assertRaisesRegex(llm.ReplayError, 'embedded public data differs'):
            llm.validate(self.root)

    def test_coordinated_data_and_manifest_change_is_rejected(self):
        path = self.bundle / 'public-data.json'
        path.write_bytes(path.read_bytes() + b'\n')
        self.refresh_manifest()
        with self.assertRaisesRegex(llm.ReplayError, 'approved public data changed'):
            llm.validate(self.root)

    def test_budget_default_tampering_is_rejected(self):
        original = re.search(r'<input[^>]*id="cost-capex"[^>]*>', self.page.read_text()).group()
        self.change_page(original, original.replace('value="11000"', 'value="1"'))
        with self.assertRaisesRegex(llm.ReplayError, 'HTML budget default differs'):
            llm.validate(self.root)

    def test_electricity_step_must_accept_the_sourced_default(self):
        original = re.search(r'<input[^>]*id="cost-electricity"[^>]*>', self.page.read_text()).group()
        changed = re.sub(r'step="[^"]+"', 'step="0.01"', original)
        self.change_page(original, changed)
        with self.assertRaisesRegex(llm.ReplayError, 'invalid budget input constraint'):
            llm.validate(self.root)

    def test_manifest_tampering_is_rejected(self):
        path = self.bundle / 'SHA256SUMS'
        content = path.read_text()
        path.write_text(('1' if content[0] != '1' else '0') + content[1:])
        with self.assertRaisesRegex(llm.ReplayError, 'public bundle checksum mismatch'):
            llm.validate(self.root)

    def test_unlisted_file_is_rejected(self):
        (self.bundle / 'unexpected.txt').write_text('not part of the approved export')
        with self.assertRaisesRegex(llm.ReplayError, 'unexpected public bundle inventory'):
            llm.validate(self.root)

    def test_external_script_and_indexing_regressions_are_rejected(self):
        original = self.page.read_text()
        for insertion, message in [('<script src="https://example.invalid/run.js"></script>', 'only external script'),
                                   ('<meta name="robots" content="noindex,nofollow">', 'private indexing directive')]:
            with self.subTest(message=message):
                self.page.write_text(original.replace('</head>', insertion + '</head>'))
                with self.assertRaisesRegex(llm.ReplayError, message):
                    llm.validate(self.root)

    def test_missing_canonical_is_rejected(self):
        self.change_page('rel="canonical"', 'rel="alternate"')
        with self.assertRaisesRegex(llm.ReplayError, 'canonical URL'):
            llm.validate(self.root)

    def test_provenance_must_match_the_embedded_download(self):
        path = self.bundle / 'method.json'
        method = json.loads(path.read_text())
        method['purpose'] += ' changed'
        path.write_text(json.dumps(method))
        self.refresh_manifest()
        with self.assertRaisesRegex(llm.ReplayError, 'embedded provenance differs'):
            llm.validate(self.root)

    def test_cpu_reproduction_from_frozen_archive(self):
        llm.validate(self.root)
        with tempfile.TemporaryDirectory() as destination:
            with zipfile.ZipFile(self.bundle / 'public-proofs.zip') as archive:
                archive.extractall(destination)
            result = subprocess.run([sys.executable, '-B', str(Path(destination) / 'verify-public-data.py')],
                                    cwd=destination, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report['state'], 'VALIDÉ_CONTROLE_EXPORT')
            self.assertEqual((report['main_conform'], report['challenge_conform']), ('20/20', '6/10'))
            self.assertEqual(report['human_review_count'], 0)
            self.assertEqual(report['new_model_calls'], 0)
            self.assertEqual(report['public_files_verified'], 10)


if __name__ == '__main__':
    unittest.main()
