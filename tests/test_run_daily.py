import argparse
import importlib.util
from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'run_daily.py'
spec = importlib.util.spec_from_file_location('run_daily', SCRIPT)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class ScheduleTests(unittest.TestCase):
    def test_previous_natural_day_is_local_not_machine_day(self):
        now = datetime(2026, 3, 1, 9, 7, tzinfo=ZoneInfo('Asia/Shanghai'))
        start, end = runner.bounds({'timezone': 'Asia/Shanghai'}, now=now)
        self.assertEqual(start.isoformat(), '2026-02-28T00:00:00+08:00')
        self.assertEqual(end.isoformat(), '2026-03-01T00:00:00+08:00')

    def test_dst_natural_day(self):
        start, end = runner.bounds({'timezone': 'America/New_York'}, date='2026-03-08')
        self.assertEqual(end.timestamp() - start.timestamp(), 23 * 3600)

    def test_explicit_offset_bounds(self):
        start, end = runner.bounds({'timezone': 'Asia/Shanghai'}, since='2026-10-23T00:00:00Z', until='2026-10-23T06:00:00Z')
        self.assertEqual(start.hour, 8)
        self.assertEqual(end.hour, 14)
        with self.assertRaises(ValueError):
            runner.bounds({}, since='2026-01-01')
        with self.assertRaises(ValueError):
            runner.bounds({}, date='2026-01-01', since='2026-01-01', until='2026-01-02')

    def test_utc_bounds_parse_on_python_39(self):
        """datetime.fromisoformat rejects a trailing Z before 3.11; bounds() must not."""
        start, end = runner.bounds({'timezone': 'Asia/Shanghai'},
                                   since='2026-10-23T00:00:00Z', until='2026-10-23T06:00:00Z')
        self.assertEqual(start.isoformat(), '2026-10-23T08:00:00+08:00')
        self.assertEqual(end.isoformat(), '2026-10-23T14:00:00+08:00')
        # The lower-case form is just as common in the wild.
        start, end = runner.bounds({'timezone': 'UTC'},
                                   since='2026-10-23T00:00:00z', until='2026-10-23T06:00:00z')
        self.assertEqual(start.hour, 0)

    def test_exact_resolution_refuses_fuzzy_and_duplicate(self):
        self.assertEqual(runner.resolve_exact({'data': {'candidates': [{'display_name': '测试群', 'username': 'a@chatroom'}]}}, '测试群'), 'a@chatroom')
        for rows in ([{'display_name': '测试群二', 'username': 'a'}],
                     [{'display_name': '测试群', 'username': 'a'}, {'display_name': '测试群', 'username': 'b'}]):
            with self.assertRaises(ValueError):
                runner.resolve_exact({'data': {'candidates': rows}}, '测试群')

    def test_live_database_required(self):
        self.assertTrue(runner.live_ok({'data': {'checks': {'live_database_read_ok': True}}}))
        self.assertFalse(runner.live_ok({'notification_preview_ok': True, 'live_database_read_ok': False}))

    def test_editor_has_only_read_write_no_permission_bypass(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td)
            (output / 'editorial.json').write_text('{}')
            with patch.object(runner, 'run', return_value='done') as call:
                runner.invoke_editor({'agent_bin': '/bin/claude', 'owner_aliases': ['读者']}, output)
            command = call.call_args.args[0]
            self.assertIn('--restricted', command)
            self.assertIn('--strict-mcp-config', command)
            self.assertEqual(command[command.index('--tools') + 1], 'Read,Write')
            self.assertNotIn('--dangerously-skip-permissions', command)
            self.assertNotIn('--model', command)
            self.assertIn('读者', command[-1])

    def test_editor_cannot_change_evidence_and_still_publish(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td)
            (output / 'material.json').write_text('{"original":true}')
            (output / 'editorial.json').write_text('{}')
            def tamper(*args, **kwargs):
                (output / 'material.json').write_text('{"original":false}')
                return 'done'
            with patch.object(runner, 'run', side_effect=tamper):
                with self.assertRaisesRegex(RuntimeError, 'changed the evidence'):
                    runner.invoke_editor({'agent_bin': '/bin/claude'}, output)

    def test_local_only_never_launches_cloud_editor(self):
        with tempfile.TemporaryDirectory() as td, patch.object(runner, 'run') as call:
            with self.assertRaises(RuntimeError):
                runner.invoke_editor({'agent_bin': '/bin/claude', 'local_only': True}, Path(td))
            call.assert_not_called()

    def test_prepare_only_never_collects_or_launches_editor(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config = root / 'config.json'
            config.write_text(json.dumps({'chat': '测试群', 'output_root': str(root / 'reports')}))
            source = root / 'source.json'
            source.write_text('{"messages":[]}')
            args = argparse.Namespace(config=str(config), date='2026-10-23', since=None, until=None, input=str(source), prepare_only=True)
            with patch.object(runner, 'collect') as collector, patch.object(runner, 'invoke_editor') as editor, patch.object(runner, 'run', return_value=''):
                self.assertEqual(runner.execute(args), 0)
            collector.assert_not_called()
            editor.assert_not_called()
            state = json.loads(next((root / 'reports').rglob('run_status.json')).read_text())
            self.assertEqual(state['state'], 'prepared')
            self.assertFalse(state['sent'])

    def test_validator_failure_gets_only_one_editor_repair(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config = root / 'config.json'
            config.write_text(json.dumps({'chat': '测试群', 'output_root': str(root / 'reports')}))
            args = argparse.Namespace(config=str(config), date='2026-10-23', since=None, until=None, input=str(root / 'input.json'), prepare_only=False)
            def command_result(command, **kwargs):
                if 'validate' in command:
                    raise RuntimeError('Invalid editorial')
                return ''
            with patch.object(runner, 'invoke_editor') as editor, patch.object(runner, 'run', side_effect=command_result):
                self.assertEqual(runner.execute(args), 1)
                self.assertEqual(editor.call_count, 2)
            state = json.loads(next((root / 'reports').rglob('run_status.json')).read_text())
            self.assertEqual(state['state'], 'failed')

    def test_png_failure_preserves_partial_delivery_status(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config = root / 'config.json'
            config.write_text(json.dumps({'chat': '测试群', 'output_root': str(root / 'reports')}))
            args = argparse.Namespace(config=str(config), date='2026-10-23', since=None, until=None, input=str(root / 'input.json'), prepare_only=False)
            def command_result(command, **kwargs):
                if 'render' in command:
                    directory = Path(command[command.index('--out') + 1])
                    (directory / 'group_daily_report.md').write_text('done')
                    (directory / 'group_daily_report.html').write_text('done')
                    (directory / 'delivery.json').write_text('{"png_status":"missing-dependency"}')
                    raise RuntimeError('PNG dependency missing')
                return ''
            with patch.object(runner, 'invoke_editor'), patch.object(runner, 'run', side_effect=command_result):
                self.assertEqual(runner.execute(args), 3)
            state = json.loads(next((root / 'reports').rglob('run_status.json')).read_text())
            self.assertEqual(state['state'], 'partial')
            self.assertEqual(state['png_status'], 'missing-dependency')

    def test_editor_missing_output_is_failure(self):
        with tempfile.TemporaryDirectory() as td, patch.object(runner, 'run', return_value='done'):
            with self.assertRaisesRegex(RuntimeError, 'without editorial.json'):
                runner.invoke_editor({'agent_bin': '/bin/claude'}, Path(td))

    def test_names_default_to_group_nickname_and_are_cached(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cache = root / 'names.json'
            probes = []

            def probe(reader, run, identity, env=None):
                probes.append(identity)
                return {'schema_version': 1, 'basis': 'group-nick', 'source': 'test', 'chat_id': identity,
                        'member_count': 3, 'members_with_group_nickname': 1, 'mapped_label_count': 1,
                        'group_nicknames': {'u1': '群昵称一'}, 'mapping': {'显示名一': '群昵称一'},
                        'ambiguous_labels': ['同名'], 'shared_group_nicknames': []}

            import importlib.util
            spec = importlib.util.spec_from_file_location('wechat_daily_group_nicknames', runner.SKILL / 'scripts' / 'group_nicknames.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            from unittest.mock import patch as _patch
            with _patch.object(module, 'probe', side_effect=probe):
                with _patch.object(runner, 'load_names_module', return_value=module):
                    first, mode, note = runner.resolve_names({'chat': '群A', 'group_names_file': str(cache)},
                                                            lambda *a, **k: '', Path('/bin/true'), {}, '1@chatroom', root)
                    self.assertEqual((mode, first), ('group-nick', cache))
                    self.assertIn('可映射名称 1', note)
                    self.assertIn('同名', note)
                    self.assertTrue(cache.is_file())
                    self.assertEqual(json.loads(cache.read_text())['mapping'], {'显示名一': '群昵称一'})
                    # A live run refreshes by default so a changed group nickname follows.
                    runner.resolve_names({'chat': '群A', 'group_names_file': str(cache)},
                                         lambda *a, **k: '', Path('/bin/true'), {}, '1@chatroom', root)
                    self.assertEqual(len(probes), 2)
                    # With refresh off (or during replay) the cached file is reused untouched.
                    second, _, _ = runner.resolve_names({'chat': '群A', 'group_names_file': str(cache), 'group_names_refresh': False},
                                                        lambda *a, **k: '', Path('/bin/true'), {}, '1@chatroom', root)
                    self.assertEqual(second, cache)
                    self.assertEqual(len(probes), 2)

    def test_explicit_display_mode_never_reads_group_members(self):
        file, mode, note = runner.resolve_names({'chat': '群A', 'name_mode': 'display'},
                                               lambda *a, **k: (_ for _ in ()).throw(AssertionError('probe called')),
                                               Path('/bin/true'), {}, '', Path('/tmp'))
        self.assertEqual((file, mode), (None, 'display'))
        self.assertIn('display', note)
        with self.assertRaises(ValueError):
            runner.resolve_names({'chat': '群A', 'name_mode': 'guess'}, lambda *a, **k: '', Path('/bin/true'), {}, '1@chatroom', Path('/tmp'))

    def test_replay_without_cached_names_degrades_instead_of_probing(self):
        file, mode, note = runner.resolve_names({'chat': '群A'},
                                               lambda *a, **k: (_ for _ in ()).throw(AssertionError('probe called')),
                                               Path('/bin/true'), {}, '', Path('/tmp'))
        self.assertEqual((file, mode), (None, 'display'))
        self.assertIn('回放', note)

    def test_agents_root_is_canonical_and_dependencies_resolve_across_roots(self):
        """~/.agents/skills is the install location; siblings may live in other roots."""
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {'HOME': td}, clear=False):
            for var in ('AGENTS_HOME', 'CLAUDE_HOME', 'CODEX_HOME'):
                os.environ.pop(var, None)
            home = Path(td)
            (home / '.agents' / 'skills').mkdir(parents=True)
            (home / '.claude' / 'skills' / 'wechat-cli' / 'scripts').mkdir(parents=True)
            (home / '.claude' / 'skills' / 'wechat-cli' / 'scripts' / 'reader.sh').write_text('')
            (home / '.codex' / 'skills' / 'wechat-intelligence-hub' / 'scripts').mkdir(parents=True)
            (home / '.codex' / 'skills' / 'wechat-intelligence-hub' / 'scripts' / 'hub.sh').write_text('')

            roots = runner.skill_roots()
            self.assertEqual(roots[0], home / '.agents' / 'skills')
            # Reader and Hub sit in different roots and must still both resolve.
            self.assertEqual(runner.default_reader(), home / '.claude' / 'skills' / 'wechat-cli' / 'scripts' / 'reader.sh')
            self.assertEqual(runner.find_sibling('wechat-intelligence-hub/scripts/hub.sh'),
                             home / '.codex' / 'skills' / 'wechat-intelligence-hub' / 'scripts' / 'hub.sh')

    def test_home_override_beats_default_roots(self):
        """An explicit <X>_HOME/skills wins over the default ~/.agents root."""
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {'AGENTS_HOME': td}, clear=False):
            for var in ('CLAUDE_HOME', 'CODEX_HOME'):
                os.environ.pop(var, None)
            override = Path(td) / 'skills'
            override.mkdir()
            self.assertEqual(runner.skill_roots()[0], override)
            self.assertEqual(runner.skills_root(), override)

    def test_hub_home_is_discovered_for_symlinked_wrapper(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project = root / 'share' / 'wechat-intelligence-hub' / 'projects' / 'wechat-intelligence-hub'
            project.mkdir(parents=True)
            (project / 'wechat_intelligence_hub.py').write_text('')
            hub = root / 'skills' / 'wechat-intelligence-hub' / 'scripts' / 'hub.sh'
            hub.parent.mkdir(parents=True)
            hub.write_text('')
            self.assertEqual(runner.hub_home(hub), project)


if __name__ == '__main__':
    unittest.main()
