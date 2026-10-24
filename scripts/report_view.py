"""Reference-style, offline presentation for a single-group editorial report."""
from datetime import datetime
import html
import json
import os
from pathlib import Path
import re


def escape(value):
    return html.escape(str(value or ''), quote=True)


def inline_html(value):
    text = escape(value)
    text = re.sub(r'\*\*([^*\n]+)\*\*', r'<strong>\1</strong>', text)
    return re.sub(r'==([^=\n]+)==', r'<span class="hl">\1</span>', text)


def clock(value):
    try:
        return datetime.fromisoformat(str(value)).strftime('%H:%M')
    except ValueError:
        return str(value)


def signature_line():
    """页脚署名/联系方式：优先读私有配置 signature，其次读环境变量，都没有则不加。"""
    value = os.environ.get("WECHAT_DAILY_SIGNATURE", "").strip()
    if value:
        return value
    config = Path.home() / ".wechat-intelligence-hub" / "group-daily.json"
    try:
        data = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(data.get("signature") or "").strip()


def evidence_title(ids, index):
    return '；'.join(f"{key} {index[key].get('sender', '')} {clock(index[key].get('time', ''))}" for key in ids if key in index)


def period_label(material):
    try:
        start = datetime.fromisoformat(material['since'])
        end = datetime.fromisoformat(material['until'])
    except ValueError:
        return f"{material['since']} – {material['until']}"
    weekday = '一二三四五六日'[start.weekday()]
    if start.date() == end.date():
        period = f'{start:%H:%M} – {end:%H:%M}'
    elif end.hour == end.minute == end.second == 0 and (end.date() - start.date()).days == 1:
        period = f'{start:%H:%M} – 24:00'
    else:
        period = f'{start:%H:%M} – {end:%m-%d %H:%M}'
    return f'{start:%Y-%m-%d}（周{weekday}） · {period}'


CSS = '''
/* A narrow editorial column: plain masthead, compact data, colored topic chips. */
:root{
 --bg:#f5f6f8;--card:#ffffff;--ink:#14171a;--ink2:#4a5158;--ink3:#66717d;
 --line:#e4e7eb;--brand:#1758a6;--brand-bg:#eaf1fd;--bar:#2878d0;
 --green:#247654;--green-bg:#e8f6ee;--green-line:#a0c6b3;
 --amber:#986317;--amber-bg:#fdf3e2;--amber-line:#cfb57c;
 --quote:#f8f9fa;--shadow:0 1px 2px #1018280f,0 6px 18px #1018280d;
 --body-font:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
 --title-font:"PingFang SC",-apple-system,BlinkMacSystemFont,sans-serif;
 color-scheme:light;
}
@media(prefers-color-scheme:dark){:root:not([data-theme="light"]){
 --bg:#0f1115;--card:#171a20;--ink:#e8eaed;--ink2:#b9c0c8;--ink3:#98a3b0;
 --line:#323943;--brand:#77aef0;--brand-bg:#16243c;--bar:#4c90d8;
 --green:#7bce9f;--green-bg:#172c22;--green-line:#46745d;
 --amber:#dfb568;--amber-bg:#30261a;--amber-line:#8b7049;
 --quote:#1e232b;--shadow:0 1px 2px #00000040,0 6px 18px #00000026;color-scheme:dark;
}}
:root[data-theme="dark"]{
 --bg:#0f1115;--card:#171a20;--ink:#e8eaed;--ink2:#b9c0c8;--ink3:#98a3b0;
 --line:#323943;--brand:#77aef0;--brand-bg:#16243c;--bar:#4c90d8;
 --green:#7bce9f;--green-bg:#172c22;--green-line:#46745d;
 --amber:#dfb568;--amber-bg:#30261a;--amber-line:#8b7049;
 --quote:#1e232b;--shadow:0 1px 2px #00000040,0 6px 18px #00000026;color-scheme:dark;
}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.7 var(--body-font);-webkit-text-size-adjust:100%}
.page{max-width:720px;margin-inline:auto;padding-block:20px 48px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));overflow-wrap:anywhere}
h1{font:700 22px/1.35 var(--title-font);letter-spacing:-.4px;margin:0 0 6px;text-wrap:balance}
h2{font:700 16px/1.5 var(--title-font);margin:32px 0 12px;padding-left:11px;border-left:3px solid var(--brand);letter-spacing:-.2px}
h3{font:600 15px/1.5 var(--title-font);display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:0 0 11px;padding-bottom:9px;border-bottom:1px solid var(--line)}
p{margin:8px 0}.meta{color:var(--ink3);font-size:12px;margin:0 0 3px}.lede{font-size:14px;color:var(--ink2);margin:10px 0 0}
a{color:var(--brand);text-decoration:none;word-break:break-all}a:focus-visible{outline:2px solid var(--brand);outline-offset:2px}
.stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:18px 0 6px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:13px 6px;text-align:center;box-shadow:var(--shadow)}
.stat b{display:block;font-size:21px;line-height:1.2;letter-spacing:-.5px;font-variant-numeric:tabular-nums}.stat span{font-size:11.5px;color:var(--ink3)}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;margin:12px 0;box-shadow:var(--shadow);min-width:0}
.card>:first-child{margin-top:0}.card>:last-child{margin-bottom:0}.topic.insight{border-color:var(--green-line)}.topic.caution{border-color:var(--amber-line)}
.tag{display:inline-block;font-size:11px;line-height:1.7;padding:2px 8px;border-radius:20px;background:var(--brand-bg);color:var(--brand);font-weight:650;max-width:100%}
.insight .tag{background:var(--green-bg);color:var(--green)}.caution .tag{background:var(--amber-bg);color:var(--amber)}
.time{font-size:11.5px;color:var(--ink3);font-weight:400;font-variant-numeric:tabular-nums;white-space:nowrap}
ul{padding-left:19px;margin:8px 0}li{margin:6px 0}li::marker{color:var(--ink2)}.hl{font-family:inherit;font-weight:700;color:var(--ink);background:linear-gradient(transparent 62%,color-mix(in srgb,var(--brand) 22%,transparent) 0)}
blockquote{margin:11px 0 0;padding:11px 14px;border-left:3px solid var(--line);background:var(--quote);border-radius:0 9px 9px 0;color:var(--ink2);font-size:14px}blockquote strong{color:var(--ink)}
.boundary{display:block;color:var(--ink3);font-size:12px;line-height:1.75;margin-top:10px;padding-top:8px;border-top:1px dashed var(--line)}.boundary::before{content:"注　";color:var(--ink3);font-weight:600;letter-spacing:.08em}
.rank{margin:0;padding:0;list-style:none}.rank li{display:grid;grid-template-columns:112px minmax(0,1fr);align-items:center;gap:10px;margin:7px 0;font-size:13.5px}
.rank .name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--ink2)}.bar-area{display:flex;align-items:center;gap:8px;min-width:0}.bar{height:7px;border-radius:0 4px 4px 0;background:var(--bar);opacity:.8;flex:none;min-width:2px}.count{color:var(--ink3);font-size:12px;white-space:nowrap;font-variant-numeric:tabular-nums}
.attention-wrap{overflow-x:auto}table{width:100%;table-layout:fixed;border-collapse:collapse;font-size:13.5px}th,td{text-align:left;padding:9px 8px;border-bottom:1px solid var(--line);vertical-align:top;overflow-wrap:anywhere}
th{font-size:11.5px;color:var(--ink3);font-weight:600}th:first-child,td:first-child{width:52px;white-space:nowrap;font-variant-numeric:tabular-nums}th:last-child,td:last-child{width:76px;white-space:nowrap}tr:last-child td{border-bottom:0}
.links{margin:8px 0}.links li{font-size:13px;line-height:1.7;margin:7px 0}.links a{font:12px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace}.note{font-size:11.5px;color:var(--ink3);margin-top:26px;border-top:1px solid var(--line);padding-top:14px}.note p{margin:4px 0}.sign{margin-top:14px;padding-top:12px;border-top:1px dashed var(--line);font:12.5px/1.9 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--ink2);letter-spacing:.02em;white-space:pre-line}
@media(max-width:360px){.stat b{font-size:18px}.stats{gap:7px}.card{padding:14px}.rank li{grid-template-columns:98px minmax(0,1fr)}}
@media print{.card{break-inside:avoid}}
'''


def render_html(material, editorial, link_rows):
    index = {message['evidence_id']: message for message in material.get('messages', [])}
    statistics = [(material['message_count'], '条消息'), (material['speaker_count'], '人发言'),
                  (len(editorial.get('topics', [])), '个话题'), (len(link_rows), '个链接')]
    stats = ''.join(f'<div class="stat"><b>{value}</b><span>{label}</span></div>' for value, label in statistics)
    blocks = [f'<header><p class="meta">{escape(period_label(material))}</p><h1>{escape(material["chat"])}<br>今日内容总结</h1><p class="lede">{inline_html(editorial["lede"])}</p></header>',
              f'<section class="stats" aria-label="本时段概览">{stats}</section>']
    if material.get('speakers'):
        maximum = max(item['count'] for item in material['speakers']) or 1
        ranks = []
        for item in material['speakers'][:12]:
            width = item['count'] / maximum * 78
            label = f'{item["name"]}，{item["count"]}条消息'
            ranks.append(f'<li title="{escape(label)}"><span class="name">{escape(item["name"])}</span><span class="bar-area"><span class="bar" aria-hidden="true" style="width:{width:.3f}%"></span><span class="count">{item["count"]}</span></span></li>')
        blocks.append('<section aria-labelledby="activity-title"><h2 id="activity-title">活跃度</h2><div class="card"><ul class="rank">'+''.join(ranks)+'</ul></div></section>')
    blocks.append('<section aria-labelledby="topics-title"><h2 id="topics-title">话题</h2>')
    for topic in editorial.get('topics', []):
        tone = topic.get('tone', 'caution' if topic.get('kind') == 'risk' else 'neutral')
        if tone not in ('insight', 'caution', 'neutral'):
            tone = 'neutral'
        span = f'{clock(topic.get("start", ""))}–{clock(topic.get("end", ""))}'
        if str(topic.get('start', ''))[:10] != str(topic.get('end', ''))[:10]:
            span = f'{str(topic.get("start", ""))[:10]} {span} {str(topic.get("end", ""))[:10]}'
        rows = ''.join(f'<li title="{escape(evidence_title(item["evidence_ids"], index))}">{inline_html(item["text"])}</li>' for item in topic.get('bullets', []))
        boundary = f'<small class="boundary">{inline_html(topic["boundary"])}</small>' if topic.get('boundary') else ''
        blocks.append(f'<article class="card topic {tone}"><h3><span class="tag">{escape(topic["title"])}</span><span class="time">{escape(span)}</span></h3><ul>{rows}</ul><blockquote><strong>总结：</strong>{inline_html(topic["insight"])}{boundary}</blockquote></article>')
    if not editorial.get('topics'):
        blocks.append(f'<p class="meta">{escape(editorial.get("topics_note") or "本时段没有足够的讨论内容。")}</p>')
    blocks.append('</section><section aria-labelledby="angles-title"><h2 id="angles-title">可做选题的线索</h2>')
    angles = []
    for angle in editorial.get('angles', []):
        title = angle.get('title', '').strip('「」')
        angles.append(f'<li title="{escape(evidence_title(angle["evidence_ids"], index))}"><strong>「{escape(title)}」</strong>{inline_html(angle.get("text", ""))}</li>')
    blocks.append('<div class="card"><ul>'+''.join(angles)+'</ul></div>' if angles else '<p class="meta">本时段没有值得单独展开的选题线索。</p>')
    blocks.append('</section><section aria-labelledby="attention-title"><h2 id="attention-title">需要你留意的</h2>')
    attention = sorted(editorial.get('attention', []), key=lambda item: index.get(item.get('anchor_id') or item['evidence_ids'][0], {}).get('time', ''))
    owners = material.get('audience', {}).get('owner_aliases', [])
    direct = sum(item.get('scope') == 'direct' for item in attention)
    other = len(attention) - direct
    if direct:
        caption = f'本时段有 {direct} 条直接与你相关的消息'+(f'，另有 {other} 条可参考线索。' if other else '，已整理如下。')
    elif attention:
        caption = '没有确认到直接指向你的待办，以下是可参考的讨论与线索。'
    elif not owners:
        caption = '未配置本人身份，本版不推断个人待办。'
    else:
        caption = '本时段未识别到需要你跟进的事项。'
    blocks.append(f'<p class="meta">{escape(caption)}</p>')
    if attention:
        rows = []
        for item in attention:
            anchor = item.get('anchor_id') or item['evidence_ids'][0]
            when = clock(index.get(anchor, {}).get('time', ''))
            rows.append(f'<tr title="{escape(evidence_title(item["evidence_ids"], index))}"><td>{escape(when)}</td><td>{inline_html(item["text"])}</td><td>{escape(item["status"])}</td></tr>')
        blocks.append('<div class="card attention-wrap"><table><thead><tr><th scope="col">时间</th><th scope="col">事项</th><th scope="col">状态</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table></div>')
    blocks.append('</section><section aria-labelledby="links-title"><h2 id="links-title">今日链接</h2>')
    links = []
    for row in link_rows:
        candidates = [index[key] for key in row['evidence_ids'] if key in index and row['url'] in index[key].get('content', '')]
        first = min(candidates, key=lambda item: item.get('time', '')) if candidates else {}
        links.append((first.get('time', ''), f'<li title="{escape(evidence_title(row["evidence_ids"], index))}">{escape(clock(first.get("time", "")))} <strong>{escape(first.get("sender", "分享者"))}</strong>｜{escape(row.get("title", "相关页面"))}｜<a href="{escape(row["url"])}" rel="noreferrer noopener">{escape(row["url"])}</a></li>'))
    blocks.append('<ul class="links">'+''.join(row for _, row in sorted(links, key=lambda pair: pair[0]))+'</ul>' if links else '<p class="meta">本时段群内没有可读链接分享。</p>')
    source = material.get('coverage', {}).get('input_coverage') or {}
    if source.get('cap_reached'):
        coverage = '本轮已达到读取上限，不能视为全天完整记录。'
    elif source.get('live_database_read_ok'):
        coverage = '仅覆盖本机已同步记录，不代表全部历史；附件与外链正文未核验。'
    else:
        coverage = '基于已有导出整理，采集完整性未确认；附件与外链正文未核验。'
    sign = signature_line()
    sign_html = f'<p class="sign">{escape(sign)}</p>' if sign else ''
    blocks.append(f'</section><footer class="note"><p>以上内容由「微信个人情报助手」整理，未发送微信。</p><p>{escape(coverage)} 编辑判断供参考，详细证据保留在本机素材与 Markdown。</p>{sign_html}</footer>')
    title = escape(material['chat']+' 今日内容总结')
    return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; script-src \'none\'; connect-src \'none\'; img-src data:; base-uri \'none\'; form-action \'none\'"><title>'+title+'</title><style>'+CSS+'</style></head><body><main class="page" data-layout="editorial-v2">'+''.join(blocks)+'</main></body></html>'
