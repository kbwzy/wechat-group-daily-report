#!/usr/bin/env python3
"""Deterministic, local-only renderer for a single WeChat group daily report."""
from __future__ import annotations
import argparse, datetime as dt, html, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

TECH_HOSTS = ("weixin.qq.com", "wx.qq.com", "weixin.com", "tenpay.com")
# Chinese prose is routinely pasted straight after a URL; stop the match at CJK so the
# link stays clickable and the sentence keeps its words.
URL_RE = re.compile(r"https?://[^\s<>\"'，。；、\u3000-\u303f\u4e00-\u9fff\uff00-\uffef]+", re.I)
XML_REPLY_RE = re.compile(r"<(?:refermsg|引用|quote)[^>]*>.*?</(?:refermsg|引用|quote)>", re.I | re.S)
APPMSG_RE = re.compile(r"<appmsg\b[^>]*>(.*?)</appmsg>", re.I | re.S)
XML_TITLE_RE = re.compile(r"<(?:title|标题)>(.*?)</(?:title|标题)>", re.I | re.S)
DROP_MEDIA_RE = re.compile(r"<(?:msg|appmsg|voipmsg|img|image|emoji|videomsg|recorditem|attach|media)[^>]*>.*?</(?:msg|appmsg|voipmsg|img|image|emoji|videomsg|recorditem|attach|media)>", re.I | re.S)
WXID_PREFIX_RE = re.compile(r"^\s*wxid_[\w-]+\s+\d+(?:\s+\d+)?\s+",re.I)
SYSTEM_SENDER_RE = re.compile(r"(?:@chatroom$|系统消息|群公告)$",re.I)

def timestamp(value, zone):
    if not value: return None
    s=str(value).strip().replace("Z","+00:00")
    try: parsed=dt.datetime.fromisoformat(s)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S","%Y/%m/%d %H:%M:%S","%Y-%m-%d %H:%M"):
            try: parsed=dt.datetime.strptime(s,fmt); break
            except ValueError: continue
        else: return None
    if parsed.tzinfo is None: parsed=parsed.replace(tzinfo=zone)
    return parsed.astimezone(zone)

def clean_content(raw):
    text=str(raw or "")
    # The appmsg title is current-message content; quoted titles are discarded with refermsg.
    text=XML_REPLY_RE.sub("",text)
    app=APPMSG_RE.search(text)
    if app:
        app_title=XML_TITLE_RE.search(app.group(1))
        replacement=app_title.group(1) if app_title else ""
        current_urls=re.findall(r"<url[^>]*>(.*?)</url>",app.group(1),re.I|re.S)
        text=" ".join([replacement]+current_urls)
        text=html.unescape(re.sub(r"<!\[CDATA\[(.*?)\]\]>",r"\1",text,flags=re.S))
    else:
        text=DROP_MEDIA_RE.sub("",text)
    text=WXID_PREFIX_RE.sub("",text)
    text=re.sub(r"<[^>]{1,500}>"," ",text)
    text=re.sub(r"\[[^\]]{0,24}(?:红包|图片|视频|语音|表情|文件|小程序)[^\]]*\]"," ",text)
    text=re.sub(r"\s+"," ",text).strip()
    links=[]
    for sep in ("：",":","，"):
        text=text.replace("https://"+sep,"https://").replace("http://"+sep,"http://")
    def sub(match):
        raw_url=match.group(0).rstrip(".,!?;:)")
        try: host=(urlsplit(raw_url).hostname or "").lower()
        except ValueError: host=""
        technical=any(host==h or host.endswith("."+h) for h in TECH_HOSTS)
        if host in ("wxapp.tc.qq.com","vweixinf.tc.qq.com","wx.gtimg.com"):
            technical=True
        if technical and host!="mp.weixin.qq.com": return " "
        links.append(raw_url)
        return f" {raw_url} "
    text=URL_RE.sub(sub,text)
    text=re.sub(r"\s+"," ",text).strip()
    if re.fullmatch(r"(?:\[?(?:红包|恭喜发财|图片|视频|语音|表情|文件|小程序|转账)\]?\s*)+",text,re.I): text=""
    return text,links

def is_human_sender(sender,chat):
    s=str(sender or "").strip()
    return bool(s and s not in (chat,"未知发言人") and not SYSTEM_SENDER_RE.search(s))

def dedupe_links(occurrences):
    grouped={}
    for item in occurrences:
        url=item["url"]
        try:
            parts=urlsplit(url); key=(parts.scheme.lower(),parts.netloc.lower(),parts.path,parts.query,parts.fragment)
        except ValueError: key=(url,)
        entry=grouped.setdefault(key,{"url":url,"evidence_ids":[],"contexts":[],"senders":[],"times":[]})
        for field,value in (("evidence_ids",item["evidence_id"]),("contexts",item.get("context","")),("senders",item.get("sender","")),("times",item.get("time",""))):
            if value and value not in entry[field]: entry[field].append(value)
    result=[]
    for entry in grouped.values():
        contexts=[c for c in entry["contexts"] if len(c)>2]
        title=(contexts[0][:72] if contexts else "相关页面："+(urlsplit(entry["url"]).hostname or "网页链接"))
        result.append({"url":entry["url"],"title":title,"evidence_ids":entry["evidence_ids"],"senders":entry["senders"],"times":entry["times"]})
    return result

def rows_from(data):
    if isinstance(data,list): return data
    if not isinstance(data,dict): raise ValueError("JSON 顶层必须是对象或消息数组")
    rows=data.get("messages")
    if isinstance(rows,list): return rows
    # chat-history supports common Hub generic row wrappers.
    for key in ("data","rows","results","items","records"):
        value=data.get(key)
        if isinstance(value,list): return value
        if isinstance(value,dict) and isinstance(value.get("messages"),list): return value["messages"]
    raise ValueError("找不到 messages 数组（支持 Hub group_daily.json 与 chat-history messages/data/rows/results/items/records）")

def msg_field(row, names, default=""):
    for name in names:
        if row.get(name) is not None: return row[name]
    return default

def escape(s): return html.escape(str(s or ""), quote=True)

def atomic_json(path, data): path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
def atomic_text(path, text): path.write_text(text,encoding="utf-8")
def ensure_safe_paths(src,out):
    src=src.resolve(); out=out.resolve()
    if src==out: raise ValueError("输入文件必须与输出目录分开")
    allowed_source=out/"source"
    if out in src.parents and allowed_source in src.parents:
        pass  # run_daily keeps the input under out/source/; output names are disjoint.
    elif src in out.parents or out in src.parents:
        raise ValueError("输入文件与输出目录不能重叠（输入仅允许位于输出目录的 source/ 下）")
    if out.exists() and not out.is_dir(): raise FileExistsError(f"输出路径不是目录：{out}")
    protected={"material.json","material.md","editorial.template.json","editorial.json","group_daily_report.md","group_daily_report.html","group_daily_report.png","delivery.json","status.json"}
    collisions=sorted(name for name in protected if (out/name).exists())
    if collisions: raise FileExistsError("拒绝覆盖既有报告产物："+", ".join(collisions))
    out.mkdir(parents=True,exist_ok=True); os.chmod(out,0o700)

def reply_sender(raw):
    block=re.search(r'<refermsg\b[^>]*>(.*?)</refermsg>',str(raw or ''),re.I|re.S)
    if not block: return ''
    name=re.search(r'<displayname[^>]*>(.*?)</displayname>',block.group(1),re.I|re.S)
    return html.unescape(re.sub(r'<!\[CDATA\[(.*?)\]\]>',r'\1',name.group(1),flags=re.S)).strip() if name else ''


def directed_at_owner(message,owners):
    return bool(owners and message.get('sender') not in owners and
                (message.get('reply_to') in owners or any(re.search(r'@'+re.escape(name)+r'(?:\s|$|[，,。:：])',message.get('content','')) for name in owners)))


def skills_root():
    """Return the installed skills directory, honouring CLAUDE_HOME/CODEX_HOME."""
    for variable in ("CLAUDE_HOME", "CODEX_HOME"):
        base=str(os.environ.get(variable) or "").strip()
        if base:
            candidate=Path(base).expanduser()
            candidate=candidate if candidate.name=="skills" else candidate/"skills"
            if candidate.is_dir(): return candidate
    for root in (".claude/skills",".codex/skills"):
        candidate=Path.home()/root
        if candidate.is_dir(): return candidate
    return Path.home()/".claude/skills"


def default_reader():
    return skills_root()/"wechat-cli"/"scripts"/"reader.sh"


def name_mapping(args):
    """Resolve the sender-name mode into a {label: name} map plus its provenance."""
    mode=getattr(args,"name_mode","group-nick") or "group-nick"
    if mode not in ("group-nick","display"):
        raise ValueError("--name-mode 只能是 group-nick 或 display")
    if mode=="display": return {}, {"basis":"display","mode":"display","source":"联系人备注/昵称（原始 sender）","labels":0}
    path=str(getattr(args,"names",None) or "").strip()
    module=local_module("group_nicknames")
    if path=="auto":
        chat_id=str(getattr(args,"chat_id","") or "").strip()
        if not chat_id:
            raise ValueError("--names auto 需要 --chat-id（稳定群ID）；也可先用 names 子命令生成文件后传 --names FILE")
        reader=Path(getattr(args,"reader",None) or default_reader()).expanduser()
        payload=module.probe(reader,_probe_run,chat_id)
        payload["chat"]=getattr(args,"chat","")
        return _payload_mapping(payload),{"basis":"group-nick","mode":"group-nick","source":payload["source"],
            "labels":len(payload["mapping"]),"ambiguous_labels":payload.get("ambiguous_labels",[]),
            "member_count":payload.get("member_count",0),"members_with_group_nickname":payload.get("members_with_group_nickname",0),
            "chat_id":chat_id,"probed":"live"}
    if path:
        mapping,meta=module.load_mapping(Path(path).expanduser())
        meta=dict(meta); meta.update({"basis":"group-nick","mode":"group-nick","source":meta.get("source") or "names 文件","labels":len(mapping)})
        return mapping,meta
    print("WARNING: 未提供 --names 映射，本轮退回联系人备注/昵称；要按群昵称出报，请传 --names FILE 或 --names auto --chat-id ID。",file=sys.stderr)
    return {},{'basis':'display-fallback','mode':'group-nick','source':'缺少群昵称映射，退回原始联系人昵称','labels':0}


def _payload_mapping(payload):
    return {str(k):str(v) for k,v in (payload.get("mapping") or {}).items() if str(k).strip() and str(v).strip()}


def _probe_run(command,env=None,timeout=120):
    result=subprocess.run(command,capture_output=True,text=True,env=env,timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"{Path(command[0]).name} {' '.join(command[1:3])} failed: {result.stderr[-600:]}")
    return result.stdout


def prepare(args):
    src=Path(args.input); out=Path(args.out); ensure_safe_paths(src,out)
    mapping,names_meta=name_mapping(args)
    rename=lambda value: mapping.get(str(value or "").strip()) or value
    zone=ZoneInfo(args.timezone); start=timestamp(args.since,zone); end=timestamp(args.until,zone)
    if not start or not end or start>=end: raise ValueError("--since/--until 必须是有效 ISO 时间且 since < until")
    raw=json.loads(src.read_text(encoding="utf-8")); selected=[]; link_occurrences=[]; dropped=0; matched_total=0; counts={}; renamed_messages=0
    for i,row in enumerate(rows_from(raw)):
        if not isinstance(row,dict): continue
        chat=str(msg_field(row,("chat","群聊","session","conversation")))
        if chat != args.chat: continue
        when=timestamp(msg_field(row,("time","timestamp","时间","datetime","created_at")),zone)
        if not when or when < start or when >= end: continue
        matched_total+=1
        sender=str(msg_field(row,("sender","发言人","speaker","from"),"未知发言人"))
        resolved=rename(sender)
        if resolved!=sender: renamed_messages+=1
        sender=resolved
        if is_human_sender(sender,chat): counts[sender]=counts.get(sender,0)+1
        content, urls=clean_content(msg_field(row,("content","内容","text","message")))
        if not content: dropped+=1; continue
        rec={"evidence_id":f"E{i+1:05d}","chat":chat,"sender":sender,"time":when.isoformat(timespec="seconds"),"content":content,"source_file":str(msg_field(row,("source_file","来源文件","file"),src.name))}
        rec["reply_to"]=rename(reply_sender(msg_field(row,("content","内容","text","message"))))
        selected.append(rec)
        for u in urls: link_occurrences.append({"url":u,"evidence_id":rec["evidence_id"],"sender":sender,"time":rec["time"],"context":re.sub(URL_RE,"",content).strip(" ：:，,。" )})
    selected.sort(key=lambda x:(x["time"],x["evidence_id"]))
    links=dedupe_links(link_occurrences)
    speakers=sorted(counts.items(),key=lambda p:(-p[1],p[0]))
    file_mtime=dt.datetime.fromtimestamp(src.stat().st_mtime,zone)
    age_hours=max(0.0,(dt.datetime.now(zone)-file_mtime).total_seconds()/3600)
    freshness="文件修改时间距今超过24小时（可能陈旧）" if age_hours>24 else "文件修改时间距今不超过24小时（不等于聊天已完整刷新）"
    source_meta={"input_file":src.name,"input_mtime":file_mtime.isoformat(timespec="seconds"),"file_age_hours":round(age_hours,1),"freshness_note":freshness,"source_type":"hub-group-daily" if isinstance(raw,dict) and isinstance(raw.get("groups"),list) else "chat-history-compatible-json"}
    input_coverage=raw.get("coverage") if isinstance(raw,dict) else None
    if input_coverage is None and isinstance(raw,dict) and isinstance(raw.get("payload"),dict):
        input_coverage=raw["payload"].get("coverage")
    collection_note="采集覆盖未在输入中提供，无法判定完整性。"
    if isinstance(input_coverage,dict):
        parts=[]
        for key,label in (("collected_at","采集时间"),("cap_reached","达到采集上限"),("read_limit","读取上限"),("record_cap","记录上限"),("live_database_read_ok","实时数据库读取成功"),("completeness","完整性")):
            if key in input_coverage: parts.append(f"{label}：{input_coverage[key]}")
        collection_note="；".join(parts) if parts else "输入包含采集覆盖信息，但未提供常见完整性字段。"
    coverage={"statement":"仅统计输入文件中指定群、半开时间窗口内可解析且保留的消息；输入可能是旧索引或部分采集，不代表全量微信记录。工具本身不触发刷新。发言榜按来源显示名计数，不进行账号身份消歧，同名可能合并。","collection_note":collection_note,"input_coverage":input_coverage,"input_message_rows":len(rows_from(raw)),"matched_chat_window_rows":matched_total,"effective_evidence_count":len(selected),"excluded_empty_or_media_rows":dropped,"source":source_meta}
    material={"schema_version":1,"chat":args.chat,"since":start.isoformat(timespec="seconds"),"until":end.isoformat(timespec="seconds"),"timezone":args.timezone,"coverage":coverage,"message_count":matched_total,"effective_evidence_count":len(selected),"speaker_count":len(counts),"speakers":[{"name":n,"count":c} for n,c in speakers],"messages":selected,"links":links}
    owner_aliases=[rename(a) for a in (getattr(args,'owner_alias',[]) or [])]
    used={m['sender'] for m in selected if m['sender'] in mapping.values()}
    names_meta=dict(names_meta); names_meta.update({"renamed_messages":renamed_messages,"names_used":sorted(used)})
    material['names']=names_meta
    material['audience']={'owner_aliases':owner_aliases,'owner_aliases_source':getattr(args,'owner_alias',[]) or [],'identity_basis':('group nicknames from the local group member list; still not account identity verification' if names_meta['basis']=='group-nick' else 'configured display names; not account identity verification')}
    atomic_json(out/"material.json",material)
    if names_meta['basis']=='group-nick':
        name_note="发言人按群昵称显示（本群映射 %d 个名称，改写 %d 条消息；未映射者保留联系人昵称）"%(names_meta['labels'],renamed_messages)
    elif names_meta['basis']=='display-fallback':
        name_note="未提供群昵称映射，本轮发言人使用联系人备注/昵称（非群昵称）"
    else: name_note="发言人使用联系人备注/昵称，未套用群昵称"
    if names_meta.get('ambiguous_labels'): name_note+="；同名多人未映射："+"、".join(names_meta['ambiguous_labels'][:8])
    md=[f"# {args.chat}｜群聊日报素材",f"\n时间范围（左闭右开）：{material['since']} 至 {material['until']}（{args.timezone}）",f"\n覆盖说明：{coverage['statement']}",f"\n采集覆盖：{collection_note}",f"\n命名：{name_note}",f"\n输入：{src.name}；文件修改时间：{source_meta['input_mtime']}（不代表采集截至）；{freshness}；原始消息 {matched_total} 条，有效证据 {len(selected)} 条，发言人 {len(counts)} 位。", "\n## 发言榜"]
    md += [f"- {n}：{c} 条" for n,c in speakers] or ["- 无消息"]
    md += ["\n## 链接"] + ([f"- [{x['title']}]({x['url']})（证据：{', '.join(x['evidence_ids'])}）" for x in links] or ["- 无"])
    md += ["\n## 全部消息"]
    md += [f"- `{m['evidence_id']}` {m['time']}｜{m['sender']}：{m['content']}（来源：{m['source_file']}）" for m in selected] or ["- 此窗口没有符合条件的消息。"]
    atomic_text(out/"material.md","\n".join(md)+"\n")
    atomic_json(out/"editorial.template.json",{"format_version":2,"lede":"","topics_note":"","topics":[],"angles":[],"attention":[],"links":[]})
    atomic_json(out/"status.json",{"prepare":"complete","validate":"pending","render":"pending","png":"not-requested"})
    print(f"准备完成：{out}（{len(selected)} 条证据）")

def validate_data(mat,ed,strict=False):
    errors=[]; ids={m["evidence_id"]:m for m in mat.get("messages",[])}; chat=mat.get("chat")
    def refs(obj,where):
        refs=obj.get("evidence_ids")
        if not isinstance(refs,list) or not refs: errors.append(f"{where}: evidence_ids 必须是非空数组"); return []
        got=[]
        for ref in refs:
            m=ids.get(ref)
            if not m: errors.append(f"{where}: 不存在的证据ID {ref}")
            elif m.get("chat")!=chat: errors.append(f"{where}: 证据不属于指定群 {ref}")
            else: got.append(m)
        return got
    def norm(s): return re.sub(r"[\W_]+","",str(s or "").lower(),flags=re.UNICODE)
    if not isinstance(ed,dict): return ["editorial.json 顶层必须是对象"]
    reference=ed.get('format_version')==2
    if strict and not reference: errors.append('稳定日报须使用format_version=2，请按本轮模板修稿')
    if not isinstance(ed.get("lede"),str) or not ed["lede"].strip(): errors.append("lede 必须是非空结论标题/导语")
    topics=ed.get("topics",[])
    if not isinstance(topics,list): errors.append("topics 必须是数组"); topics=[]
    no_topic_note=str(ed.get("topics_note","")).strip()
    no_topic_phrases=("无实质信息","没有实质信息","尚未形成实质讨论","暂无实质讨论","无可归纳话题","未形成主题","不足以形成话题","有效证据不足","内容不足以归纳")
    if not topics and int(mat.get("effective_evidence_count",mat.get("message_count",0)) or 0)>0 and not any(phrase in no_topic_note for phrase in no_topic_phrases):
        errors.append("有有效证据却没有话题时，topics_note 必须明确说明无实质信息/讨论")
    broad={norm(x) for x in ("讨论","行业讨论","AI产品/模型","AI产品模型","工具分享","资源分享","经验交流","群内讨论","其他话题","日常交流","信息分享")}
    for i,t in enumerate(topics):
        p=f"topics[{i}]"
        if not isinstance(t,dict): errors.append(p+" 必须是对象"); continue
        title=str(t.get("title","")).strip()
        if len(title)<5 or norm(title) in broad: errors.append(p+" 标题为空、过短或过于宽泛")
        if t.get("kind","discussion") not in ("discussion","risk","verified"): errors.append(p+" kind 只能是 discussion/risk/verified")
        evidence=refs(t,p); times=[m["time"] for m in evidence]
        if not evidence: errors.append(p+" 没有可验证证据，不能形成话题")
        if times:
            derived_start=min(times); derived_end=max(times)
            if t.get("start") not in (None,derived_start): errors.append(p+" start 必须等于引用证据的最早时间")
            if t.get("end") not in (None,derived_end): errors.append(p+" end 必须等于引用证据的最晚时间")
            t["start"]=derived_start; t["end"]=derived_end
        bullets=t.get("bullets",[])
        if not isinstance(bullets,list): errors.append(p+" bullets 必须是数组"); continue
        if len(bullets)<1 or len(bullets)>4: errors.append(p+" bullets 需1-4条；仅1条须在 boundary 说明证据稀少")
        if len(bullets)==1 and "证据有限" not in str(t.get("boundary","")) and "仅一条" not in str(t.get("boundary","")): errors.append(p+" 仅1条bullet时 boundary 必须注明证据有限/仅一条")
        bullet_texts=[]
        for j,b in enumerate(bullets):
            if not isinstance(b,dict) or not str(b.get("text","")).strip(): errors.append(f"{p}.bullets[{j}] 缺少 text"); continue
            refs(b,f"{p}.bullets[{j}]"); bullet_texts.append(norm(b.get("text")))
            if not set(b.get("evidence_ids",[])).issubset(set(t.get("evidence_ids",[]))):
                errors.append(f"{p}.bullets[{j}]: 证据必须包含在话题 evidence_ids 中，以保证时间范围正确")
        insight=str(t.get("insight","")).strip(); insight_n=norm(insight)
        if not insight: errors.append(p+" 缺少 insight")
        if any(insight_n and (insight_n==bt or insight_n in bt or bt in insight_n) for bt in bullet_texts if bt): errors.append(p+" insight 不得照抄或复述 bullet")
        for claim in re.finditer(r'(?:绝对|一定|保证|必然|百分之百|100%|绝不会|肯定会)',insight):
            clause=re.split(r'[,，。；;!?！？]',insight[:claim.start()])[-1]
            if not re.search(r'不|未|勿|别|没有|并非',clause[-18:]):
                errors.append(p+' insight 含无条件保证用语，须改为有边界的判断'); break
    for group in ("angles","attention","links"):
        rows=ed.get(group,[])
        if not isinstance(rows,list): errors.append(group+" 必须是数组"); continue
        for i,item in enumerate(rows):
            if not isinstance(item,dict): errors.append(f"{group}[{i}] 必须是对象"); continue
            if group=="links":
                title=str(item.get("title","")).strip(); url=str(item.get("url","")).strip()
                if not title: errors.append(f"links[{i}] 缺少中文说明 title")
                elif not re.search(r"[㐀-鿿]",title): errors.append(f"links[{i}].title 必须包含中文说明")
                parts=urlsplit(url)
                if parts.scheme not in ("http","https") or not parts.hostname: errors.append(f"links[{i}] 仅允许有效 http/https URL")
                matching=[x for x in mat.get("links",[]) if x.get("url")==url]
                linked_ids={eid for x in matching for eid in x.get("evidence_ids",[x["evidence_id"]] if x.get("evidence_id") else [])}
                if not matching or not linked_ids.intersection(item.get("evidence_ids",[])):
                    errors.append(f"links[{i}] URL必须来自素材，且引用含该链接的原消息")
            else:
                text=item.get("text") or item.get("title")
                if not str(text or "").strip(): errors.append(f"{group}[{i}] 缺少文案")
            refs(item,f"{group}[{i}]")
            if group=="attention" and item.get("status") not in ("待回应","可跟进","待确认","可参考","可关注","无需处理"):
                errors.append(f"attention[{i}].status 必须为待回应/可跟进/待确认/可参考/可关注/无需处理")
    if reference and not errors:
        errors.extend(editorial_style_errors(mat,ed))
    return errors


def editorial_style_errors(mat,ed):
    errors=[]
    plain=lambda text: re.sub(r'\*\*|==','',str(text or ''))
    if len(plain(ed.get('lede','')))>140: errors.append('导语超过140字，覆盖与核验说明请交给页脚')
    ids={m['evidence_id']:m for m in mat.get('messages',[])}
    owners=mat.get('audience',{}).get('owner_aliases',[])
    fragments=[('lede',ed.get('lede',''))]
    for i,topic in enumerate(ed.get('topics',[])):
        if isinstance(topic,dict): fragments += [(f'topics[{i}].insight',topic.get('insight','')),(f'topics[{i}].boundary',topic.get('boundary',''))]
    for section in ('angles','attention'):
        fragments += [(f'{section}[{i}].text',item.get('text','')) for i,item in enumerate(ed.get(section,[])) if isinstance(item,dict)]
    for label,value in fragments:
        if str(value).count('**')%2 or str(value).count('==')%2: errors.append(label+' 加粗或高亮未闭合')
    for i,topic in enumerate(ed.get('topics',[])):
        if not isinstance(topic,dict): continue
        prefix=f'topics[{i}]'
        if len(str(topic.get('title','')))>38: errors.append(prefix+' 标题超过38字，不能挤成大段说明')
        if topic.get('tone','neutral') not in ('neutral','insight','caution'): errors.append(prefix+' tone仅支持neutral/insight/caution，配色不表示事实已验证')
        text=' '.join(str(b.get('text','')) for b in topic.get('bullets',[]) if isinstance(b,dict))
        if not re.search(r'\*\*[^*]+\*\*',text): errors.append(prefix+' 正文至少加粗一位实际发言人')
        if not re.search(r'==[^=]+==',text): errors.append(prefix+' 正文须选择至少一句关键原话或准确归纳作==高亮==')
        for j,bullet in enumerate(topic.get('bullets',[])):
            if not isinstance(bullet,dict): continue
            value=str(bullet.get('text',''))
            if len(plain(value))>115: errors.append(f'{prefix}.bullets[{j}] 超过115字，请拆清主次')
            if value.count('**')%2 or value.count('==')%2: errors.append(f'{prefix}.bullets[{j}] 加粗或高亮未闭合')
            open_mark=None
            for mark in re.findall(r'\*\*|==',value):
                if mark==open_mark: open_mark=None
                elif open_mark:
                    errors.append(f'{prefix}.bullets[{j}] 加粗与高亮不要嵌套'); break
                else: open_mark=mark
        insight=plain(topic.get('insight',''))
        if not 15<=len(insight)<=130: errors.append(prefix+' 总结请收在15–130字，给一个读者带得走的认识')
        if len(plain(topic.get('boundary','')))>65: errors.append(prefix+' 边界说明超过65字，勿用审计说明淹没正文')
    stock=sum(str(topic.get('insight','')).startswith(('这轮讨论','这场讨论','讨论真正','现有材料')) for topic in ed.get('topics',[]) if isinstance(topic,dict))
    if stock>1: errors.append('多个总结使用同一类审计式开头，请按具体场景改写并拉开语气')
    for i,angle in enumerate(ed.get('angles',[])):
        if not isinstance(angle,dict): continue
        if len(plain(angle.get('title','')))>32 or len(plain(angle.get('text','')))>110: errors.append(f'angles[{i}] 选题请收成短标题加一句话')
        if not re.search(r'\*\*[^*]+\*\*',str(angle.get('text',''))): errors.append(f'angles[{i}] 说明须加粗实际相关人名，不能只有泛泛建议')
    for i,item in enumerate(ed.get('attention',[])):
        if not isinstance(item,dict): continue
        scope=item.get('scope')
        if scope not in ('direct','context','open','reference'): errors.append(f'attention[{i}] 须区分direct/context/open/reference')
        anchor=item.get('anchor_id')
        if anchor not in item.get('evidence_ids',[]) or anchor not in ids: errors.append(f'attention[{i}] anchor_id必须指向本条事项的真实消息')
        if scope=='direct' and not any(directed_at_owner(ids[e],owners) for e in item.get('evidence_ids',[]) if e in ids): errors.append(f'attention[{i}] 没有明确@本人或引用本人的证据，不能标direct')
        if item.get('status')=='待回应' and (not owners or scope not in ('direct','context')): errors.append(f'attention[{i}] 无本人指向证据不能标待回应')
        if item.get('status')=='待回应' and scope=='context':
            evidence=[ids[e] for e in item.get('evidence_ids',[]) if e in ids]
            if not any(message.get('sender') in owners for message in evidence) or ids.get(anchor,{}).get('sender') in owners:
                errors.append(f'attention[{i}] 上下文待回应必须保留本人先前发言，且事项锚点不是本人发出的消息')
        if len(plain(item.get('text','')))>95: errors.append(f'attention[{i}] 超过95字，表格内请只说具体事项')
    original={x['url'] for x in mat.get('links',[])}
    described={x.get('url') for x in ed.get('links',[]) if isinstance(x,dict)}
    if original-described: errors.append('今日链接须覆盖素材所有可读链接，不能静默漏项')
    return errors


def load_ed(out):
    path=out/"editorial.json"
    if not path.exists(): raise FileNotFoundError("缺少 editorial.json；先复制 editorial.template.json 并填写")
    return json.loads(path.read_text(encoding="utf-8"))

def validate_cmd(args):
    out=Path(args.out).resolve(); mat=json.loads((out/"material.json").read_text(encoding="utf-8")); ed=load_ed(out)
    errors=validate_data(mat,ed,strict=getattr(args,'strict',False))
    if errors:
        atomic_json(out/"status.json",{"prepare":"complete","validate":"failed","render":"pending","png":"not-requested","errors":errors})
        print("\n".join("ERROR: "+e for e in errors),file=sys.stderr); return 1
    atomic_json(out/"editorial.json",ed)
    atomic_json(out/"status.json",{"prepare":"complete","validate":"complete","render":"pending","png":"not-requested","semantic_truth":"not-verified"})
    print("校验通过（仅结构与证据引用，不验证语义真实性）"); return 0

def md_escape(text):
    special="\\\\`*_{}[]()#+.!|>"
    return "".join("\\"+ch if ch in special else (" " if ch in "\r\n" else ch) for ch in str(text or ""))

def md_bold(text): return "**"+md_escape(text)+"**"

def inline_html(text):
    return re.sub(r"\*\*([^*\n]+)\*\*",r"<strong>\1</strong>",escape(text))

def inline_md(text):
    parts=re.split(r"(\*\*[^*\n]+\*\*)",str(text or ""))
    return "".join(md_bold(p[2:-2]) if p.startswith("**") and p.endswith("**") else md_escape(p) for p in parts)

def md_url(url):
    return str(url).replace("(","%28").replace(")","%29").replace("<","%3C").replace(">","%3E")

def short_time(value):
    try: return dt.datetime.fromisoformat(str(value)).strftime("%H:%M")
    except ValueError: return str(value)

def topic_time(t):
    start=str(t.get("start","")); end=str(t.get("end",""))
    try:
        a=dt.datetime.fromisoformat(start); b=dt.datetime.fromisoformat(end)
        return (a.strftime("%m-%d ") if a.date()!=b.date() else "")+a.strftime("%H:%M")+"–"+b.strftime("%H:%M")
    except ValueError: return start+"–"+end

def source_labels(evidence_ids,mat):
    idx={m["evidence_id"]:m for m in mat.get("messages",[])}
    return [f"{idx[e].get('sender','未知')} {short_time(idx[e].get('time',''))}" for e in evidence_ids if e in idx]

def report_links(mat,ed):
    rows=ed.get("links") if ed.get("links") else [{"url":x["url"],"title":x.get("title") or "相关页面","evidence_ids":x.get("evidence_ids",[x["evidence_id"]] if x.get("evidence_id") else [])} for x in mat.get("links",[])]
    result=[]; index={}
    for row in rows:
        url=str(row.get("url",""))
        try:
            p=urlsplit(url); key=(p.scheme.lower(),p.netloc.lower(),p.path,p.query,p.fragment)
        except ValueError: key=(url,)
        if key not in index:
            index[key]=len(result); result.append({"url":url,"title":row.get("title") or "相关页面","evidence_ids":list(dict.fromkeys(row.get("evidence_ids",[])))})
        else:
            current=result[index[key]]
            current["evidence_ids"]=list(dict.fromkeys(current["evidence_ids"]+row.get("evidence_ids",[])))
    return result

def md_report(mat,ed):
    lines=['[meta]'+reference_view().period_label(mat),'# '+md_escape(mat['chat'])+'<br>今日内容总结','',
           '[lede]'+inline_md(ed['lede']),'',':::stats',f"{mat['message_count']} | 条消息",f"{mat['speaker_count']} | 人发言",
           f"{len(ed.get('topics',[]))} | 个话题",f"{len(report_links(mat,ed))} | 个链接",':::','','## 活跃度','',':::rank']
    lines += [f"{md_escape(item['name'])} | {item['count']}" for item in mat.get('speakers',[])[:12]]
    lines += [':::','','## 话题']
    if not ed.get('topics'): lines += ['',md_escape(ed.get('topics_note') or '本时段没有足够的讨论内容。')]
    for topic in ed.get('topics',[]):
        lines += ['',f"### {md_escape(topic['title'])} · {topic_time(topic)}",'']
        lines += ['- '+inline_md(item['text']) for item in topic.get('bullets',[])]
        lines += ['', '> **总结：**'+inline_md(topic['insight'])]
        if topic.get('boundary'): lines += ['> '+inline_md(topic['boundary'])]
        lines += ['<!-- evidence: '+', '.join(topic['evidence_ids'])+' -->']
    lines += ['','## 可做选题的线索','']
    lines += [f"- {md_bold('「'+item['title'].strip('「」')+'」')} {inline_md(item.get('text',''))}" for item in ed.get('angles',[])] or ['本时段没有值得单独展开的选题线索。']
    lines += ['','## 需要你留意的','']
    index={message['evidence_id']:message for message in mat.get('messages',[])}
    if ed.get('attention'):
        lines += ['| 时间 | 事项 | 状态 |','|---|---|---|']
        attention=sorted(ed['attention'],key=lambda item:index.get(item.get('anchor_id') or item['evidence_ids'][0],{}).get('time',''))
        for item in attention:
            anchor=item.get('anchor_id') or item['evidence_ids'][0]
            lines += [f"| {short_time(index.get(anchor,{}).get('time',''))} | {inline_md(item['text'])} | {item['status']} |"]
    else: lines += ['本时段未识别到需要你跟进的事项；未配置本人身份时不推断个人待办。']
    lines += ['','## 今日链接','']
    links=[]
    for row in report_links(mat,ed):
        sources=[index[eid] for eid in row['evidence_ids'] if eid in index and row['url'] in index[eid].get('content','')]
        first=min(sources,key=lambda message:message.get('time','')) if sources else {}
        links.append((first.get('time',''),f"- {short_time(first.get('time',''))} {md_bold(first.get('sender','分享者'))}｜{md_escape(row['title'])}｜[{md_escape(row['url'])}]({md_url(row['url'])})"))
    lines += [line for _,line in sorted(links)] or ['本时段群内没有可读链接分享。']
    lines += ['','[note]以上内容由「微信个人情报库」群聊日报 Skill 整理。仅覆盖本机已采集记录，附件与外链正文未核验；完整证据保留在本机素材。']
    sign = reference_view().signature_line()
    if sign: lines += ['', sign]
    return '\n'.join(lines)+'\n'

def local_module(name):
    import importlib.util
    spec=importlib.util.spec_from_file_location('wechat_daily_'+name,Path(__file__).with_name(name+'.py'))
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def reference_view():
    return local_module('report_view')


def render_html(mat,ed):
    links=[]
    for row in report_links(mat,ed):
        parts=urlsplit(row['url'])
        if parts.scheme in ('http','https') and parts.hostname:
            links.append(row)
    return reference_view().render_html(mat,ed,links)

def png_capture(out):
    target=out/"group_daily_report.png"; htmlfile=(out/"group_daily_report.html").resolve().as_uri()
    py=sys.executable
    probe=subprocess.run([py,"-I","-c","import playwright.sync_api; from PIL import Image"],capture_output=True)
    if probe.returncode==0:
        code="""import sys, io, math
from PIL import Image
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
 b=p.chromium.launch(headless=True,executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',args=['--disable-network'])
 page=b.new_page(viewport={'width':430,'height':900},device_scale_factor=3,color_scheme='light')
 page.route('**/*',lambda route: route.abort() if route.request.url.startswith(('http://','https://')) else route.continue_())
 page.goto(sys.argv[1],wait_until='load')
 page.evaluate('document.fonts.ready')
 height=page.evaluate('Math.ceil(document.documentElement.scrollHeight)')
 image=Image.new('RGB',(1290,height*3))
 for y in range(0,height,900):
  actual=page.evaluate('(y)=>{window.scrollTo(0,y);return window.scrollY}',y)
  page.evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
  tile=Image.open(io.BytesIO(page.screenshot(full_page=False))).convert('RGB')
  offset=round((y-actual)*3); length=min(900,height-y)*3
  image.paste(tile.crop((0,offset,1290,offset+length)),(0,y*3))
 image.save(sys.argv[2])
 b.close()
"""
        r=subprocess.run([py,"-I","-c",code,htmlfile,str(target)],capture_output=True,text=True)
        if r.returncode==0:return "complete",target.stat().st_size
        return "failed",r.stderr[-1500:]
    node=shutil.which("node")
    if node:
        return "missing-dependency","长图使用 Python Playwright + Pillow 分段截图拼接；未启用可能截断的整页 Node 截图，也未下载依赖。"
    return "missing-dependency","需要已安装的 Python Playwright、Pillow 与本机 Chrome；未下载或安装浏览器。"

def render_cmd(args):
    out=Path(args.out).resolve(); mat=json.loads((out/"material.json").read_text(encoding="utf-8")); ed=load_ed(out)
    errors=validate_data(mat,ed)
    if errors: raise ValueError("校验失败："+"；".join(errors))
    page=render_html(mat,ed)
    layout_errors=local_module('layout_check').check_html(page,mat,ed,len(report_links(mat,ed)))
    if layout_errors: raise ValueError('版式合同失败：'+'；'.join(layout_errors))
    atomic_json(out/'quality_checks.json',{'layout':'passed','format_version':ed.get('format_version',1),'topic_cards':len(ed.get('topics',[])),'links':len(report_links(mat,ed)),'semantic_truth':'not-verified'})
    atomic_json(out/"editorial.json",ed); atomic_text(out/"group_daily_report.md",md_report(mat,ed)); atomic_text(out/"group_daily_report.html",page)
    png="not-requested"; note=None
    if args.png: png,note=png_capture(out)
    atomic_json(out/"delivery.json",{"markdown":"group_daily_report.md","html":"group_daily_report.html","png":"group_daily_report.png" if png=="complete" else None,"png_status":png,"png_note":note,"output_scope":"local-files","model_processing":"handled by the invoking Agent; renderer does not call a model"})
    atomic_json(out/"status.json",{"prepare":"complete","validate":"complete","render":"complete","png":png,"semantic_truth":"not-verified","note":note})
    if args.png and png!="complete": print(f"Markdown/HTML 已生成；PNG 状态：{png}（{note}）",file=sys.stderr); return 2 if png=="missing-dependency" else 1
    print(f"渲染完成：{out}"); return 0

def names_cmd(args):
    out=Path(args.out).expanduser(); out.parent.mkdir(parents=True,exist_ok=True)
    module=local_module("group_nicknames")
    def run(command,env=None,timeout=120):
        result=subprocess.run(command,capture_output=True,text=True,env=env,timeout=timeout)
        if result.returncode: raise RuntimeError(f"{Path(command[0]).name} {command[1:3]} failed: {result.stderr[-800:]}")
        return result.stdout
    payload=module.probe(Path(args.reader).expanduser(),run,args.chat_id)
    payload['chat']=args.chat or ""
    payload['collected_at']=dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")
    atomic_json(out,payload)
    print(f"群昵称映射：{out}（成员 {payload['member_count']}，带群昵称 {payload['members_with_group_nickname']}，可映射名称 {payload['mapped_label_count']}）")
    if payload['ambiguous_labels']: print("同名多人未映射："+"、".join(payload['ambiguous_labels']),file=sys.stderr)
    return 0


def main():
    os.umask(0o077)
    p=argparse.ArgumentParser(description="Local deterministic single-group daily report")
    sub=p.add_subparsers(dest="cmd",required=True)
    a=sub.add_parser("prepare");a.add_argument("input");a.add_argument("--chat",required=True);a.add_argument("--since",required=True);a.add_argument("--until",required=True);a.add_argument("--timezone",default="Asia/Shanghai");a.add_argument("--owner-alias",action="append",default=[]);a.add_argument("--names",help="群昵称映射文件（names 子命令生成）；传 auto 则按 --chat-id 现场只读探测");a.add_argument("--name-mode",choices=list(local_module("group_nicknames").NAME_MODES),default="group-nick",help="group-nick（默认，用群昵称）或 display（联系人备注/昵称）");a.add_argument("--chat-id",help="稳定群ID，配合 --names auto 使用");a.add_argument("--reader",help="wechat-cli reader.sh 路径（--names auto 时使用）");a.add_argument("--out",required=True);a.set_defaults(func=prepare)
    a=sub.add_parser("names");a.add_argument("--chat-id",required=True,help="稳定群ID（如 44162461169@chatroom）");a.add_argument("--chat",help="群名，仅写入说明");a.add_argument("--reader",default=str(default_reader()));a.add_argument("--out",required=True);a.set_defaults(func=names_cmd)
    a=sub.add_parser("validate");a.add_argument("--out",required=True);a.add_argument("--strict",action="store_true");a.set_defaults(func=validate_cmd)
    a=sub.add_parser("render");a.add_argument("--out",required=True);a.add_argument("--png",action="store_true");a.set_defaults(func=render_cmd)
    args=p.parse_args()
    try:
        result=args.func(args); return result if isinstance(result,int) else 0
    except Exception as e:
        print(f"ERROR: {e}",file=sys.stderr); return 1
if __name__=="__main__": raise SystemExit(main())
