# 依赖生态

本 Skill 只做一件事：把一个群、一个时间窗的聊天编辑成图文日报。取数交给相邻的两个 Skill，它们不在本仓库里。

```text
wechat-cli                  只读证据读取器
   doctor                   检查能否真正读数据库（不只是通知预览）
   resolve-chat             群名 → 稳定群 ID
   members                  群成员表
   sql                      直接查询（读群昵称用）
        │
        ▼
wechat-intelligence-hub     项目目录 + 统一命令入口
   chat-history             按群 ID、时间窗、条数上限导出消息
        │
        ▼
wechat-group-daily-report   ← 本仓库
```

## 从哪里获取

两个依赖都由 Rion Wu 维护，**不在 PyPI**，需要单独安装：

```bash
git clone https://github.com/Rion-Wu-tech/wechat-intelligence-hub.git
cd wechat-intelligence-hub
./scripts/install.sh --with-sqlcipher --with-html
```

仓库地址：<https://github.com/Rion-Wu-tech/wechat-intelligence-hub>

### 许可证关系

上游 `wechat-intelligence-hub` 以 **AGPL-3.0-only** 发布，版权归 Rion Wu。本仓库与它是**两个独立项目**：

- 本仓库不复制、不修改上游的任何源码，也不 import 它的 Python 模块；
- 唯一的交互是子进程调用已安装的 `hub.sh` / `reader.sh`，等价于用户在终端自己敲命令；
- 因此在许可证层面这属于「使用一个独立程序」，本仓库可以独立以 MIT 发布。

如果你把两者一起分发，或修改了上游代码，请遵守上游的 AGPL 条款。本仓库不包含任何上游代码，也不提供上游的替代实现。

## 路径解析

`daily_report.py` 和 `run_daily.py` 都通过同一个规则找同级 Skill：

1. `$CLAUDE_HOME/skills` 或 `$CODEX_HOME/skills`（如果变量指向的目录存在）
2. `~/.claude/skills`
3. `~/.codex/skills`

找到 skills 根目录后，拼出 `wechat-cli/scripts/reader.sh` 与 `wechat-intelligence-hub/scripts/hub.sh`。两者都可用配置或命令行参数覆盖：

| 入口 | 覆盖方式 |
|---|---|
| Reader | 配置项 `reader`，或 `--reader PATH` |
| Hub 入口 | 配置项 `hub_entry` |
| Hub 项目目录 | 配置项 `hub_home`，或环境变量 `WECHAT_HUB_HOME` |
| Agent 可执行文件 | 配置项 `agent_bin`，默认取 `PATH` 上的 `claude` |

## 降级行为

缺依赖时不会假装成功：

| 缺失 | 行为 |
|---|---|
| Reader 或 Hub | 实时取数直接失败，素材保留，状态写 `failed` |
| 数据库不可读 | 拒绝用通知预览冒充历史记录，明确失败 |
| 群昵称映射 | 退回联系人昵称，stderr 告警，素材与报告都写明「非群昵称」 |
| Playwright / Pillow / Chrome | 仍交 Markdown 和 HTML，`png_status` 标 `missing-dependency`，进程返回 2 |
| Claude Code CLI | 定时桥接失败并保留素材，等之后手动补编辑；不会拿模板冒充成品 |

## 为什么分开

- **只读**是 `wechat-cli` 的职责，本仓库不碰密钥、不重启微信、不改权限。
- **多群/私聊/商机**是 Hub 的职责。本仓库刻意不实现跨群综合日报，避免和 Hub 的 Intent Router 抢路由。
- 两边共享同一份消息 JSON 格式，所以 `prepare` 也能直接吃 Hub 的 `group_daily.json` 或 `chat-history` 的 `messages.json`。
