"""Keep the shipped example runnable.

The example is the first thing a new user runs, so it must stay in sync with the
current contract: same evidence IDs, strict validation passes, rendering works.
"""
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts' / 'daily_report.py'
EXAMPLES = ROOT / 'examples'
CHAT = '示例·独立开发者交流群'

spec = importlib.util.spec_from_file_location('example_daily', SCRIPT)
daily = importlib.util.module_from_spec(spec)
spec.loader.exec_module(daily)


def prepare(out):
    subprocess.run(
        [sys.executable, str(SCRIPT), 'prepare', str(EXAMPLES / 'group-messages.json'),
         '--chat', CHAT, '--since', '2026-10-20T00:00:00+08:00', '--until', '2026-10-21T00:00:00+08:00',
         '--timezone', 'Asia/Shanghai', '--name-mode', 'display', '--owner-alias', '示例读者',
         '--out', str(out)],
        check=True, capture_output=True, text=True)


class ExampleTests(unittest.TestCase):
    def test_example_messages_are_synthetic_and_offline(self):
        payload = json.loads((EXAMPLES / 'group-messages.json').read_text(encoding='utf-8'))
        self.assertTrue(payload['messages'])
        for row in payload['messages']:
            self.assertEqual(row['source_file'], 'example')
            self.assertEqual(row['chat'], CHAT)
            # Synthetic data must never carry a real chat id.
            self.assertNotIn('@chatroom', json.dumps(row))

    def test_example_editorial_passes_strict_validation(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / 'run'
            prepare(out)
            editorial = json.loads((EXAMPLES / 'editorial.json').read_text(encoding='utf-8'))
            (out / 'editorial.json').write_text(json.dumps(editorial, ensure_ascii=False), encoding='utf-8')
            material = json.loads((out / 'material.json').read_text(encoding='utf-8'))
            self.assertEqual(daily.validate_data(material, editorial, strict=True), [])

    def test_example_editorial_covers_every_material_link(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / 'run'
            prepare(out)
            material = json.loads((out / 'material.json').read_text(encoding='utf-8'))
            editorial = json.loads((EXAMPLES / 'editorial.json').read_text(encoding='utf-8'))
            self.assertEqual({row['url'] for row in editorial['links']}, {row['url'] for row in material['links']})

    def test_example_renders_reference_layout(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / 'run'
            prepare(out)
            shutil.copyfile(EXAMPLES / 'editorial.json', out / 'editorial.json')
            material = json.loads((out / 'material.json').read_text(encoding='utf-8'))
            editorial = json.loads((out / 'editorial.json').read_text(encoding='utf-8'))
            page = daily.render_html(material, editorial)
            links = len(daily.report_links(material, editorial))
            self.assertEqual(daily.local_module('layout_check').check_html(page, material, editorial, links), [])
            self.assertIn('<h1>' + CHAT + '<br>今日内容总结</h1>', page)

    def test_reference_preview_matches_regenerated_output(self):
        """preview.md is committed; a contract change must not silently desync it."""
        # A maintainer's private config may carry a signature; the committed preview has none.
        view = daily.local_module('report_view')
        stubbed = types.SimpleNamespace(signature_line=lambda: '',
                                        period_label=view.period_label,
                                        render_html=view.render_html)
        with patch.object(daily, 'reference_view', return_value=stubbed):
            self._assert_preview_matches()

    def _assert_preview_matches(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / 'run'
            prepare(out)
            shutil.copyfile(EXAMPLES / 'editorial.json', out / 'editorial.json')
            material = json.loads((out / 'material.json').read_text(encoding='utf-8'))
            editorial = json.loads((out / 'editorial.json').read_text(encoding='utf-8'))
            # render runs validate first, which backfills topic start/end from evidence.
            self.assertEqual(daily.validate_data(material, editorial), [])
            expected = daily.md_report(material, editorial)
            self.assertEqual((EXAMPLES / 'preview.md').read_text(encoding='utf-8'), expected)


if __name__ == '__main__':
    unittest.main()
