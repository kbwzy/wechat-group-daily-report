# 执行流程

## 定位与范围

1. 本技能路径以当前 `SKILL.md` 的真实目录为准，不硬编码维护者目录。Hub 入口按已安装的 skills 根目录解析（`$CLAUDE_HOME` 或 `$CODEX_HOME`，默认 `~/.claude/skills`、其次 `~/.codex/skills`）下的 `wechat-intelligence-hub/scripts/hub.sh`；项目由该包装器发现，`WECHAT_HUB_HOME` 可覆盖。
2. 精确群名、用户时区与起止时间先固定。单群调用不运行宽范围 `group-daily` 或全微信索引。Hub `group-daily --chat` 不存在，不要编参数。
3. 交互“今日”是当地 00:00 到当前时间的截止版；“昨天”是昨日自然日；未给时间沿用 Hub 的过去24小时。定时配置默认昨日自然日 `[00:00,次日00:00)`。均明确显示时区和范围。
4. 群名可从已有请求/私有配置获取；相近名、多精确同名候选必须停，不选最活跃的那个。没有配置且无人值守时写失败状态，不猜。

## 两种输入

### 复用本轮已采集数据

接受 Hub `group_daily.json`，或 Hub `chat-history` 输出的 `messages.json`。现有 `group_daily_topics.md` / `group_daily_groups.md` 只是编辑参考，不能拿它们计算发言榜、补齐全天话题或完整链接。

```bash
python3 "$SKILL/scripts/daily_report.py" prepare "$SOURCE_JSON" \
  --chat "$CHAT" --since "$SINCE" --until "$UNTIL" \
  --timezone "$TIMEZONE" --names "$NAMES_JSON" --out "$RUN"
```

`--names` 提供群昵称映射（`names` 子命令生成或 `auto` 现场探测）。默认命名口径是**群昵称**；没有映射时按联系人昵称并在 stderr 告警，需在报告中说明。

素材保留证据 ID、清洗后的消息、发言榜、可读链接和命名依据（`material.names`）。发言榜与正文统一用群昵称，未映射者保留联系人昵称。输入文件mtime不等于采集截止；旧文件明确称回放/截止版。读取范围缺失、页面上限、未读附件均需在导语或报告范围中说明。

### 获取最新单群消息

复用已有只读 Reader/Hub，`run_daily.py` 会：

- 检查 Reader `doctor` 的数据库读取能力，不以通知预览代替历史。
- 用 Reader `resolve-chat --type-filter group` 做元数据消歧，只允许一个精确群名命中。
- 用稳定群ID调用 Hub `chat-history --type-filter group --since ... --until ... --limit ... --out ...`。
- 用同一稳定群ID读群成员与 `chat_room.ext_buffer` 取得群昵称映射（`name_mode=group-nick` 默认；`display` 可退回联系人昵称）。
- 精确复核返回消息群名，传递到 prepare，不改写群身份。

只读查询会产生本机报告文件，但不改微信。新鲜度无法确认就失败或明确降级，不能回退到昨天却说今日成功。不重新获取key、不重启微信、不改系统权限；缺通道按 wechat-cli 接入流程另行处理。

## 编辑与验收

完整阅读 `references/editorial.md`，再阅读素材所有消息，按format_version=2模板在同一目录写 `editorial.json`。每个事实bullet、选题、提醒绑定证据ID；姓名加粗、关键句高亮、总结用自然口气收口。时间从证据回填，统计不让模型修改。有已确认本人显示名时，prepare增加`--owner-alias`（可重复）；没有则不推断个人待办。

依次执行 `validate --strict`、`render --png`；渲染时还会检查固定标题、栏目、四格、卡片/总结数量、提醒表头、实际URL是否可见。检查结果写入quality_checks.json。格式错误先修editorial，不能跳过校验或给模板补假证据。图片失败保留Markdown/HTML并如实说明。交付前打开实际PNG检查首尾与密度；未实际看过图不得声称视觉验收通过。

正式输出：`group_daily_report.md`、`group_daily_report.html`、`group_daily_report.png`（环境可用时）；`delivery.json` 为机器交付索引，`status.json` 为校验/渲染状态。素材、编辑JSON只保存在本机。

## 保留边界

不覆盖已有正式报告；每次创建唯一目录。重复执行不删除历史、不推进商机状态、不发微信、不公开托管网页。群里已有日报仅做索引，不让日报递归生成日报。程序验证证据ID与结构，不替代语义核查。当前Hub导出缺稳定发送者ID时按显示名计数并声明局限，不把同名合并当成身份核验。
