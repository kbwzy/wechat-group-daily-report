# 输入与编辑合同

## 本地CLI

```bash
# 1) 群昵称映射（只读：members + contact.db chat_room.ext_buffer）
python3 "$SKILL/scripts/daily_report.py" names --chat-id "$CHATROOM_ID" --chat "$EXACT_CHAT" --out "$NAMES_JSON"

# 2) 素材：默认按群昵称命名
python3 "$SKILL/scripts/daily_report.py" prepare "$INPUT_JSON" --chat "$EXACT_CHAT" \
  --since "$ISO_START" --until "$ISO_END" --timezone Asia/Shanghai \
  --names "$NAMES_JSON" --owner-alias "$OWNER_DISPLAY_NAME" --out "$RUN"
python3 "$SKILL/scripts/daily_report.py" validate --strict --out "$RUN"
python3 "$SKILL/scripts/daily_report.py" render --out "$RUN" --png
```

## 发言人命名（--name-mode）

`--name-mode group-nick` 是默认值：发言榜、话题正文、链接、提醒 anchor 里统一用**群昵称**（群成员在本群的昵称）。`--name-mode display` 保留微信联系人备注/昵称（旧行为）。

- 群昵称不在消息库里。它存在 `contact.db` 的 `chat_room.ext_buffer`（protobuf：每个成员条目 `1=username, 2=群昵称, 3=flags, 4=邀请人`），消息库只记录联系人备注/昵称，所以必须额外读一次群成员表才能映射。
- `names` 子命令只读，产出 `{group_nicknames, mapping, ambiguous_labels, ...}`；`prepare --names FILE` 用它改写 `sender`、`reply_to` 和 `owner_alias`。
- `--names auto --chat-id ID` 现场探测；`run_daily` 默认自动探测并把结果写到配置的 `group_names_file`（默认不配置则只写本轮 `source/group_names.json`）。
- 没有群昵称的成员保留联系人备注/昵称；**同名多人**无法判定是哪一个，宁可保留原名并记入 `ambiguous_labels`，也不猜。
- 缺少映射时 `prepare` 在 stderr 明确告警并记为 `names.basis=display-fallback`，素材与报告都写明“非群昵称”，不静默假装成功。
- 本人别名会自动改写（`audience.owner_aliases` 用群昵称，`audience.owner_aliases_source` 保留原配置值），提醒 `direct` 判定也随之用群昵称匹配 @ 与引用。
- 命名为显示层，不改变证据：`evidence_id`、时间、消息正文不动；`material.names` 记录依据与改写条数供核查。

没有本人身份时省略owner-alias，不猜个人待办；多个已确认显示名可重复传入。prepare处理已有数据，不刷新；run_daily负责定时获取最新源并传递私有配置中的别名。半开窗口`[since,until)`，每轮使用新目录。

输入：Hub `{since,until,messages:[{chat,sender,time,content,source_file}],coverage?}`（`sender` 默认被群昵称映射改写），或chat-history消息数组/常见嵌套messages。消息按精确群和时间过滤，长消息不截断。XML引用只保留本条正文，`reply_to`单独保存被引用者的显示名供提醒核对，不把引用正文重新算一次。发言人数按显示名统计，不能声称账号身份已核验。

material.json包含统计、消息evidence_id、链接、覆盖边界、`names`（命名依据/映射数/改写条数/歧义名）、audience.owner_aliases。素材和审计信息只在本机保留，不塞满成品页脚。

## editorial.json 必须使用format_version=2

```json
{
  "format_version": 2,
  "lede": "一句自然导读，指出今天真正值得读的主线。",
  "topics": [
    {
      "title": "具体对象与具体结论",
      "tone": "insight",
      "kind": "discussion",
      "evidence_ids": ["实际ID1", "实际ID2"],
      "bullets": [
        {"text": "**发言人甲**提出问题，==关键原话或准确归纳==。", "evidence_ids": ["实际ID1"]},
        {"text": "**发言人乙**给出方案或纠偏。", "evidence_ids": ["实际ID2"]}
      ],
      "insight": "用具体、轻快的语言收口，解释关系或适用条件，不再复述正文。"
    }
  ],
  "angles": [
    {"title": "由真实问题生出的选题", "text": "**相关人名**的什么经历，为什么值得展开。", "evidence_ids": ["实际ID1"]}
  ],
  "attention": [
    {"scope": "reference", "anchor_id": "实际ID1", "text": "**谁**的什么事需要留意。", "status": "待确认", "evidence_ids": ["实际ID1"]}
  ],
  "links": [
    {"url": "https://example.org/actual-source", "title": "有原消息依据的中文说明", "evidence_ids": ["实际含链接的ID"]}
  ]
}
```

此处是合同说明，ID和URL均为占位，不能作为报告运行。以当轮material和template为准。

- topics通常3–8，不强凑。每卡2–4条bullets，证据特别少允许1条并在boundary说明。无实质讨论可空topics，填写topics_note说明原因。
- 事实、提醒、选题和链接的证据ID必须存在于本轮指定群；bullet引用须包含在话题引用中，防止时间范围漏掉后续纠正。
- 省略start/end，由校验器从证据回填完整ISO时间。主动填写必须精确匹配，不能写估计时间或HH:MM。
- tone是insight/caution/neutral，只表示阅读类型；kind仍为discussion/risk/verified，不能为了绿色而伪称verified。
- 正文姓名用`**加粗**`，关键句用`==高亮==`，标记须闭合且不嵌套。每卡至少一处姓名加粗、一处高亮。总结15–130字，正文每条最多115字，导语最多140字；不是越短越好，限制用于稳定密度。
- attention.scope仅direct/context/open/reference；anchor_id须在本条evidence_ids中。direct必须能核对@本人或reply_to本人。无指向证据不标“待回应”，群内开放问题不是本人欠回复。
- attention.status固定：待回应/可跟进/待确认/可参考/可关注/无需处理。无事项保持空数组，不造提醒、不画空表。
- links须覆盖素材所有可读URL，不静默遗漏；每项至少引用实际含链接的消息，可附上下文证据。只写素材能证明的中文说明，不假装读过外部文章。

## 固定输出，不让模型自由设计

`report_view.py`掌握HTML，`layout_check.py`检查标题、栏目、四格、卡片/总结数量、提醒表头和实际URL是否可见。主标题固定“群名换行今日内容总结”；日期在上，导语在下。活跃度只有一份紧凑榜，不输出额外真实发言统计表。

topic是彩色细边卡＋浅色标题标签＋时间＋发言＋“总结：”灰块。选题、需要你留意的、今日链接三节遵循目标图顺序。今日链接是`时间 姓名｜说明｜实际URL`裸列表；提醒是`时间｜事项｜状态`三列。详细来源、文件mtime留素材，不做成大段页脚。

正式输出group_daily_report.md/html/png；quality_checks.json记录本轮版式合同。Markdown 使用 HTML 注释形式的区段标记（`<!-- group-report:* -->`），与 HTML 栏目一一对应，且在 Markdown 阅读器中不可见；证据ID以本机注释和editorial绑定保留。

PNG使用已安装Python Playwright＋Pillow＋Chrome，以430 CSS像素、3倍分段截图拼接。缺依赖不下载，交Markdown/HTML并明确PNG失败。status.json、delivery.json如实记录；计划路径不算成功文件。

严格检查固定的是格式、引用和密度，不是事实真假或每次都同样精彩。编辑必须按editorial.md再做内容复核。
