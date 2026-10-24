import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('group_nicknames', ROOT / 'scripts' / 'group_nicknames.py')
names = importlib.util.module_from_spec(spec)
spec.loader.exec_module(names)

DAILY = ROOT / 'scripts' / 'daily_report.py'


def varint(value):
    out = b''
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out += bytes([byte | 0x80])
        else:
            return out + bytes([byte])


def field_bytes(number, payload):
    return varint(number << 3 | 2) + varint(len(payload)) + payload


def field_varint(number, value):
    return varint(number << 3) + varint(value)


def member(username, nickname=None, flags=1, inviter='wxid_owner'):
    body = field_bytes(1, username.encode())
    if nickname is not None:
        body += field_bytes(2, nickname.encode())
    body += field_varint(3, flags) + field_bytes(4, inviter.encode())
    return field_bytes(1, body)


class ParseTests(unittest.TestCase):
    def test_group_nickname_is_field_two_of_each_member_entry(self):
        blob = member('wxid_owner', '本人群昵称', 16) + member('wxid_a', None, 17) + member('wxid_b', '设计群昵称')
        self.assertEqual(names.parse_group_nicknames(blob), {'wxid_owner': '本人群昵称', 'wxid_b': '设计群昵称'})

    def test_truncated_or_empty_blob_degrades_instead_of_crashing(self):
        good = member('wxid_owner', '本人群昵称')
        truncated = good + member('wxid_b', '设计群昵称')[:-4]
        self.assertEqual(names.parse_group_nicknames(truncated), {'wxid_owner': '本人群昵称'})
        self.assertEqual(names.parse_group_nicknames(good[:len(good) // 2]), {})
        self.assertEqual(names.parse_group_nicknames(b''), {})
        self.assertEqual(names.parse_group_nicknames(b'\xff\xff\xff\xff'), {})

    def test_mapping_uses_remark_nick_username_and_reports_ambiguity(self):
        members = [
            {'username': 'wxid_owner', 'nick_name': '本人', 'remark': '', 'display_name': '本人'},
            {'username': 'wxid_v0', 'nick_name': 'piano', 'remark': '渠道', 'display_name': '渠道'},
            {'username': 'wxid_1', 'nick_name': '同名', 'remark': '', 'display_name': '同名'},
            {'username': 'wxid_2', 'nick_name': '同名', 'remark': '', 'display_name': '同名'},
        ]
        group = {'wxid_owner': '本人群昵称', 'wxid_v0': '渠道群昵称'}
        mapping, ambiguous = names.build_mapping(members, group)
        self.assertEqual(mapping['本人'], '本人群昵称')
        self.assertEqual(mapping['wxid_owner'], '本人群昵称')
        self.assertEqual(mapping['piano'], '渠道群昵称')
        self.assertEqual(mapping['渠道'], '渠道群昵称')
        self.assertEqual(ambiguous, ['同名'])
        self.assertNotIn('同名', mapping)

    def test_payload_records_basis_and_shared_names(self):
        members = [
            {'username': 'a', 'nick_name': '甲', 'remark': '', 'display_name': '甲'},
            {'username': 'b', 'nick_name': '乙', 'remark': '', 'display_name': '乙'},
        ]
        payload = names.build_payload('1@chatroom', members, {'a': '值班', 'b': '值班'}, {}, [])
        self.assertEqual(payload['basis'], 'group-nick')
        self.assertEqual(payload['members_with_group_nickname'], 2)
        self.assertEqual(payload['shared_group_nicknames'], ['值班'])

    def test_load_mapping_accepts_payload_and_bare_map(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            full = root / 'full.json'
            full.write_text(json.dumps({'mapping': {'本人': '本人群昵称', 'same': 'same'}, 'source': 'x'}, ensure_ascii=False), encoding='utf-8')
            mapping, meta = names.load_mapping(full)
            self.assertEqual(mapping, {'本人': '本人群昵称'})
            self.assertEqual(meta['source'], 'x')
            bare = root / 'bare.json'
            bare.write_text(json.dumps({'设': '设计群昵称'}, ensure_ascii=False), encoding='utf-8')
            mapping, meta = names.load_mapping(bare)
            self.assertEqual(mapping, {'设': '设计群昵称'})
            self.assertEqual(meta['basis'], 'group-nick')

    def test_probe_refuses_identity_injection(self):
        with self.assertRaises(names.GroupNicknameError):
            names.probe(Path('/bin/false'), lambda *a, **k: '', "x'; DROP TABLE chat_room; --")


class PrepareNamingTests(unittest.TestCase):
    def rows(self):
        return {'messages': [
            {'chat': '群A', 'sender': '本人', 'time': '2026-10-01T10:00:00+08:00', 'content': '本人发言', 'source_file': 'a'},
            {'chat': '群A', 'sender': '渠道', 'time': '2026-10-01T10:01:00+08:00', 'content': '@张三 这里要怎么改', 'source_file': 'a'},
            {'chat': '群A', 'sender': '未映射', 'time': '2026-10-01T10:02:00+08:00', 'content': '普通消息', 'source_file': 'a'},
        ]}

    def run_prepare(self, root, extra):
        src = root / 'input.json'
        src.write_text(json.dumps(self.rows(), ensure_ascii=False), encoding='utf-8')
        out = root / 'out'
        command = [sys.executable, str(DAILY), 'prepare', str(src), '--chat', '群A',
                   '--since', '2026-10-01', '--until', '2026-10-02', '--owner-alias', '本人', '--out', str(out), *extra]
        result = subprocess.run(command, capture_output=True, text=True)
        return result, out

    def test_group_nick_mode_is_the_default_and_renames_owner_and_replies(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mapping = root / 'names.json'
            mapping.write_text(json.dumps({'mapping': {'本人': '本人群昵称', '渠道': '渠道群昵称'}}, ensure_ascii=False), encoding='utf-8')
            result, out = self.run_prepare(root, ['--names', str(mapping)])
            self.assertEqual(result.returncode, 0, result.stderr)
            material = json.loads((out / 'material.json').read_text(encoding='utf-8'))
            self.assertEqual(material['names']['basis'], 'group-nick')
            self.assertEqual(material['names']['renamed_messages'], 2)
            self.assertEqual(material['audience']['owner_aliases'], ['本人群昵称'])
            self.assertEqual(material['audience']['owner_aliases_source'], ['本人'])
            senders = {message['sender'] for message in material['messages']}
            self.assertEqual(senders, {'本人群昵称', '渠道群昵称', '未映射'})
            self.assertIn('群昵称', (out / 'material.md').read_text(encoding='utf-8'))

    def test_display_mode_keeps_contact_names(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            result, out = self.run_prepare(root, ['--name-mode', 'display'])
            self.assertEqual(result.returncode, 0, result.stderr)
            material = json.loads((out / 'material.json').read_text(encoding='utf-8'))
            self.assertEqual(material['names']['basis'], 'display')
            self.assertEqual(material['audience']['owner_aliases'], ['本人'])
            self.assertIn('本人', {message['sender'] for message in material['messages']})

    def test_missing_mapping_falls_back_loudly_instead_of_silently(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            result, out = self.run_prepare(root, [])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('WARNING', result.stderr)
            material = json.loads((out / 'material.json').read_text(encoding='utf-8'))
            self.assertEqual(material['names']['basis'], 'display-fallback')
            self.assertIn('非群昵称', (out / 'material.md').read_text(encoding='utf-8'))

    def test_unknown_name_mode_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            result, _ = self.run_prepare(root, ['--name-mode', 'guess'])
            self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
