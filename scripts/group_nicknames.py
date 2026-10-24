"""Resolve WeChat group nicknames (群昵称) for a single group, read-only.

The local message database only stores a contact's remark/nickname, never the
per-group nickname. Group nicknames live in `contact.db` table `chat_room`
column `ext_buffer`, a protobuf where each repeated member entry holds
`1: username`, `2: group nickname`, `3: flags`, `4: inviter`. This module
decodes that blob and builds a display-name -> group-nickname mapping so the
daily report can address people the way the group actually sees them.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict

SCHEMA_VERSION = 1
NAME_MODES = ("group-nick", "display")
IDENTITY_RE = re.compile(r"^[\w@.\-]{1,64}$", re.UNICODE)


class GroupNicknameError(RuntimeError):
    pass


def _varint(buffer, index):
    value = 0
    shift = 0
    while index < len(buffer):
        byte = buffer[index]
        index += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, index
        shift += 7
        if shift > 63:
            break
    raise ValueError("truncated varint")


def _fields(buffer):
    """Yield (field_number, wire_type, value) triples; stop on unknown framing."""
    index = 0
    while index < len(buffer):
        key, index = _varint(buffer, index)
        field, wire = key >> 3, key & 7
        if wire == 0:
            value, index = _varint(buffer, index)
        elif wire == 2:
            length, index = _varint(buffer, index)
            if length < 0 or index + length > len(buffer):
                raise ValueError("truncated length-delimited field")
            value = buffer[index:index + length]
            index += length
        elif wire == 5:
            value = buffer[index:index + 4]
            index += 4
        elif wire == 1:
            value = buffer[index:index + 8]
            index += 8
        else:
            raise ValueError(f"unsupported wire type {wire}")
        yield field, wire, value


def _text(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value or "")


def parse_group_nicknames(blob):
    """Return {member username: group nickname} from a chat_room.ext_buffer blob."""
    if not blob:
        return {}
    result = {}
    try:
        for field, wire, value in _fields(blob):
            if field != 1 or wire != 2:
                continue
            username = nickname = ""
            try:
                for sub_field, sub_wire, sub_value in _fields(value):
                    if sub_wire != 2:
                        continue
                    if sub_field == 1:
                        username = _text(sub_value)
                    elif sub_field == 2:
                        nickname = _text(sub_value)
            except ValueError:
                continue
            username, nickname = username.strip(), nickname.strip()
            if username and nickname:
                result[username] = nickname
    except ValueError:
        # A malformed tail must not discard the members already decoded.
        pass
    return result


def build_mapping(members, group_nicks):
    """Map every name the message database may print to the group nickname.

    `members` rows are wechat-cli `members` entries. A display name claimed by
    two members is ambiguous and is intentionally left unmapped; the caller
    reports those instead of guessing.
    """
    claims = defaultdict(set)
    for member in members:
        if not isinstance(member, dict):
            continue
        username = str(member.get("username") or "").strip()
        if not username:
            continue
        labels = [
            str(member.get("display_name") or "").strip(),
            str(member.get("nick_name") or "").strip(),
            str(member.get("remark") or "").strip(),
            username,
        ]
        for label in labels:
            if label:
                claims[label].add(username)
    mapping, ambiguous = {}, []
    for label, usernames in claims.items():
        if len(usernames) != 1:
            ambiguous.append(label)
            continue
        nickname = group_nicks.get(next(iter(usernames)))
        if nickname and nickname != label:
            mapping[label] = nickname
    return mapping, sorted(ambiguous)


def build_payload(chat_id, members, group_nicks, mapping, ambiguous):
    collisions = defaultdict(set)
    for username, nickname in group_nicks.items():
        collisions[nickname].add(username)
    return {
        "schema_version": SCHEMA_VERSION,
        "basis": "group-nick",
        "source": "wechat-cli members + contact.db chat_room.ext_buffer",
        "chat_id": chat_id,
        "member_count": len(members),
        "members_with_group_nickname": len(group_nicks),
        "mapped_label_count": len(mapping),
        "group_nicknames": dict(sorted(group_nicks.items())),
        "mapping": dict(sorted(mapping.items())),
        "ambiguous_labels": ambiguous,
        "shared_group_nicknames": sorted(name for name, users in collisions.items() if len(users) > 1),
    }


def load_mapping(path):
    """Read a names file: either this module's payload or a bare {label: name} map."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("mapping"), dict):
        meta = {key: data.get(key) for key in ("schema_version", "basis", "source", "chat_id", "member_count", "members_with_group_nickname", "mapped_label_count", "ambiguous_labels", "shared_group_nicknames")}
        mapping = data["mapping"]
    elif isinstance(data, dict) and all(isinstance(value, str) for value in data.values()):
        meta = {"basis": "group-nick", "source": "bare name map"}
        mapping = data
    else:
        raise GroupNicknameError("names 文件必须是 {label: name} 映射或含 mapping 的对象")
    clean = {}
    for label, name in mapping.items():
        label, name = str(label).strip(), str(name).strip()
        if label and name and label != name:
            clean[label] = name
    return clean, meta


def probe(reader, run, chat_id, env=None, limit=1000, timeout=120):
    """Read members and group nicknames through the read-only wechat-cli reader."""
    if not IDENTITY_RE.match(str(chat_id or "")):
        raise GroupNicknameError("群ID包含不支持的字符，拒绝拼入查询")
    members_payload = json.loads(run(["bash", str(reader), "members", "--chat", chat_id, "--limit", str(max(1, limit))], env=env, timeout=timeout))
    members = (members_payload.get("data") or {}).get("members") or []
    if not members:
        raise GroupNicknameError("members 未返回任何群成员，无法建立群昵称映射")
    query = f"SELECT hex(ext_buffer) AS h FROM chat_room WHERE username='{chat_id}'"
    blob_payload = json.loads(run(["bash", str(reader), "sql", "--subdir", "contact", "--limit", "1", query], env=env, timeout=timeout))
    rows = (blob_payload.get("data") or {}).get("rows") or []
    encoded = str((rows[0] if rows else {}).get("h") or "")
    try:
        blob = bytes.fromhex(encoded)
    except ValueError:
        blob = b""
    group_nicks = parse_group_nicknames(blob)
    mapping, ambiguous = build_mapping(members, group_nicks)
    return build_payload(chat_id, members, group_nicks, mapping, ambiguous)
