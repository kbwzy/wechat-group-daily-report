# 示例数据

三个文件，一份合成群聊，跑通完整链路，不碰你的微信。

| 文件 | 说明 |
|---|---|
| `group-messages.json` | 10 条合成消息，含一个 `@你`、3 个链接、1 个红包占位 |
| `editorial.json` | 对应的 `format_version=2` 编辑稿，能通过 `validate --strict` |
| `preview.png` / `.html` / `.md` | 上面两个文件跑出来的产物 |

消息里有几处是刻意放进去的，用来展示这套流程在意的细节：

- **一次改口**：李四先劝退，王五给了实测数据，李四随后把结论从「功能没用」修正为「入口位置不对」。素材按时间完整保留，编辑必须把这段纠正写完整。
- **一条证据话题**：第二个话题只有一条消息，`editorial.json` 里就必须填 `boundary` 说明证据稀缺，否则严格校验会拦下。
- **一个 `@你`**：`E00008` 是张三直接 @ 示例读者，所以 `attention` 才能标 `scope: direct` + `status: 待回应`。没有这个证据就只能标 `reference`。
- **一个红包**：`[红包]` 会被清洗成空内容并计入 `excluded_empty_or_media_rows`，不进话题、不进发言榜。
- **一个技术链接**：如果消息里出现 `weixin.qq.com` 这类技术域名，会被识别为技术 URL 并从链接清单里剔除。

## 复现

```bash
SKILL="$PWD"
RUN=/tmp/wechat-daily-demo && rm -rf "$RUN"

python3 "$SKILL/scripts/daily_report.py" prepare "$SKILL/examples/group-messages.json" \
  --chat "示例·独立开发者交流群" \
  --since 2026-10-20T00:00:00+08:00 --until 2026-10-21T00:00:00+08:00 \
  --timezone Asia/Shanghai --name-mode display --owner-alias "示例读者" --out "$RUN"

cp "$SKILL/examples/editorial.json" "$RUN/editorial.json"
python3 "$SKILL/scripts/daily_report.py" validate --strict --out "$RUN"
python3 "$SKILL/scripts/daily_report.py" render --out "$RUN" --png
```

`status.json` 里 `png: complete` 才说明长图真的出来了；如果是 `missing-dependency`，装上 Playwright、Pillow 和 Chrome 再跑一次 `render`。

## 关于姓名

示例用 `--name-mode display`，因为群昵称保存在 `contact.db` 的 `chat_room.ext_buffer` 里，离线环境读不到。接了真实环境后建议用默认的 `--name-mode group-nick`。

## 改这份示例

`editorial.json` 里的每个 `evidence_ids` 都必须指向 `prepare` 生成的真实 ID（`E00001` 起），且链接要覆盖素材里的全部可读 URL。改完重新跑 `validate --strict` 和 `render --png`，`preview.*` 请一并更新。
