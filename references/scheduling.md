# 每日定时调用

## 两种调用环境

- **已有 Agent 定时器**：任务中调用本技能，要求完整执行准备、编辑、校验、渲染，不停在素材层。Agent 已经在执行时不要再次调用 run_daily 的模型入口；直接依 workflow 调 daily_report.py。
- **系统 cron / launchd**：脚本本身没有语义编辑能力。用 `scripts/run_daily.py` 桥接：只读取数 → prepare → 调用已登录 Claude Code 写 editorial.json → validate → render。无需新 API key，但登录、配额及无人值守权限须有效；继承当前 Agent 的模型配置，不偷偷换模型。

定时器只负责唤起，不决定观点质量。编辑要求在 `references/editorial.md`；不能把一份机器摘要直接截图当最终报告。

## 私有配置

默认读取 `$HOME/.wechat-intelligence-hub/group-daily.json`，配置放技能目录之外。复制 `assets/config.example.json` 后填写准确群名；默认昨日自然日、Asia/Shanghai、PNG启用。可通过 `--config` 指定多个独立任务配置。

字段：`chat`、`timezone`、`window`（yesterday/rolling24/today）、`output_root`、`read_limit`、`png`、可选 `hub_entry`/`reader`/`agent_bin`、`local_only`。不存凭据。

可选 `name_mode`/`group_names_file`/`group_names_refresh`/`hub_home`，见下节。`hub_home` 用于 hub.sh 以符号链接安装、自身找不到项目目录时显式指定。默认 read_limit=20000，达到上限或来源覆盖不明时不能声称全量。

命名：默认 `name_mode=group-nick`（群昵称），run_daily 每轮用稳定群ID自动探测映射。设 `group_names_file`（如 `~/.wechat-intelligence-hub/group-names.json`）缓存映射；`group_names_refresh: false` 时只在缓存缺失才探测。`--input` 回放旧数据不访问微信，只有已有缓存才能用群昵称，否则降级为联系人昵称。要恢复旧口径设 `name_mode: "display"`。

```bash
python3 "$SKILL/scripts/run_daily.py" --config "$HOME/.wechat-intelligence-hub/group-daily.json"
```

安全试跑（不访问微信、不调用模型、不生成正式报告）：

```bash
python3 "$SKILL/scripts/run_daily.py" --config "$CONFIG" \
  --input "$EXISTING_GROUP_JSON" --date 2026-10-23 --prepare-only
```

指定截止版：`--since 2026-10-23T00:00:00+08:00 --until 2026-10-23T18:00:00+08:00`；不要同时传 `--date`。日期只为示例，不写入日常任务。

## 定时提示词模板

> 使用 wechat-group-daily-report，读取私有配置中的准确群名与时区，按群昵称称呼发言人，生成昨日自然日的单群图文日报。通过 wechat-intelligence-hub 限定单群获取最新已同步消息；完整读素材，按编辑准则写结论式标题、关键发言与不复述事实的编辑判断；绑定证据，校验后生成PNG长图、HTML、Markdown。覆盖不足、附件未读、身份未知如实说明。不发微信、不推进商机、不改调度，最后只交付实际成功的文件和最重要结论。

## 安全与费用

run_daily 仅给编辑子进程 Read/Write 工具，restricted模式，无Shell/浏览器/搜索和MCP；当前Agent只编辑本轮文件，不承担采集与运行脚本。不会传 `--dangerously-skip-permissions`。模型处理使用已授权Claude Code会话对应服务，可能消耗额度/费用；本机取数、存储、截图不代表模型在本机。`local_only=true` 时桥接拒绝启动云端Agent，需明确配置本地编辑方案，不能悄悄回退。

没有安装/登录Claude Code、版本不支持restricted参数或工具授权失败时，本轮失败并保留素材，不绕过权限。PNG分段截图需要本机已有Python Playwright、Pillow和Chrome。缺少依赖时Markdown/HTML仍可交，PNG标partial；不自动下载浏览器。正文校验首次失败时会根据status.json自动修稿一次，再失败就保留素材、明确失败，不无限重试。

## 本次安装不改系统调度

技能安装和定时器启用是两件事。本次不修改已有crontab、launchd、全局settings或微信。旧Hub `cron-daily-report.sh` 只跑数据脚本，不会因为安装新技能就自动调用它。应由使用者把上述入口或提示词接入已授权的定时器；不用在每次日报时再次解释格式。

## 失败恢复

每次目录唯一；看 `run_status.json` 判断 collecting/prepared/edited/complete/partial/failed，`status.json` 是正文校验与渲染的细分状态。失败不删除素材，不重用昨日成品冒充成功。若已生成 editorial.json，用 daily_report.py validate/render 完成该轮，避免再次花费模型额度。不存在的PNG不写成功交付。
