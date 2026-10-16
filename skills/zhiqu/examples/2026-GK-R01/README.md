# 对外样板（回溯版）：2026 年浙江，想进电网的电气方向（模拟考生小远）

同一位模拟考生“小远”（与 [2027-GK-S01](../2027-GK-S01/README.md) 同一画像、同一偏好），假设他是 2026 年考生、位次 33,000：**只用 2025 年及以前的官方数据**按出分后填报的情形做完整报告，再用 2026 年浙江省教育考试院的真实投档线填第 11 节“事后回看”。方案在运行前登记（省份、五档位次、参数、判定规则），结果不好也照实写。

结论：按 2026 年真实投档线，他会落在第 3 志愿中国计量大学·电气，正是报告预测最可能的落点（74.9%）；两个冲刺志愿没过。但 11 条可对照志愿的实际线全部比预测更紧（中位约 15%），5 条落到 80% 区间之外：2026 年电气类整体变热约 8.5%，模型的共同因子低估了这种方向性变化。这张表靠的是保底的余量，而不是冲刺概率算得准。

这是一位模拟考生、一年、一个方向的展示，不是模型有效性的证明（2026 年已揭盲）。2026 年适用的 2024 版选考要求与 2026 年招生计划没有入库，资格项全部待核（`simulation` 模式）。

| 阶段 | 文件 |
|---|---|
| 0 登记 | `case.json`（含 `retro`：目标年、所用数据年份、判定脚本、事前登记日期） |
| 1 画像 | `profile.txt`、`profile_parse.json` |
| 2 方向 | `directions.json` |
| 3 本省规则 | `rules_check.json`（省份层见 `data/zhejiang/rules.json`） |
| 4 筛选与候选池 | `screening.json`（2025 年表 17,890 → 117，逐步对账）、`excluded_campus.csv`、`pool.csv` |
| 5 打分 | `attributes.csv`（102 个沿用 S01，5 个按同校同专业套用，10 个按事前量表人工打分，逐条见 `basis`）、`preferences_config.json`、`preferences_review.json`、`reviewed.csv` |
| 6 计算 | `result.json`、`run.json`（全部命令）、`sensitivity/`（7 组，含前景悲观与电气类整体冷热） |
| 7 报告 | `report.json`、`report.pdf`、`report.html`、`entry_sheet.csv` |
| 事后对照 | `hindsight.json`（`scripts/retro_judge.py` 输出）、`retro_ranks.csv`（10,000 / 20,000 / 33,000 / 50,000 / 80,000 五档位次的回溯，全部报告） |
| 8 复核 | `review.json`：**尚未做**，须由没参与分析的新会话完成 |

在技能目录执行：

```bash
python3 scripts/case_check.py examples/2026-GK-R01 --stage 7
python3 scripts/retro_judge.py examples/2026-GK-R01/result.json --target data/zhejiang/general_2026.csv --rank 33000
```
