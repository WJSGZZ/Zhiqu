# 付费样板：2027 年浙江，想进电网的电气方向（模拟考生小远）

用来演示一单报告从取数到出稿的完整个案流程。考生是模拟的，位次 33,000 是模拟出分；历年位次、志愿规则、院校章程与就业报告来自官方页面，每条带来源和查询日期。2027 年的招生计划、选考要求、一分一段表尚未公布，所以按 `simulation` 模式运行：所有资格项标为待核，**不能直接填报**。

目录按 [case-workflow.md](../../references/case-workflow.md) 的阶段排列，用 `python3 scripts/case_check.py examples/2027-GK-S01 --stage 7` 检查（在技能目录执行）。

| 阶段 | 文件 |
|---|---|
| 0 登记 | `case.json` |
| 1 画像 | `profile.txt`、`profile_parse.json` |
| 2 方向 | `directions.json` |
| 3 本省规则 | `rules_check.json`（省份层见 `data/zhejiang/rules.json`） |
| 4 筛选与候选池 | `screening.json`（18,543 → 143，逐步对账）、`excluded_campus.csv`、`pool.csv` |
| 5 打分 | `attributes.csv`、`preferences_config.json`、`preferences_review.json`、`reviewed.csv` |
| 6 计算 | `result.json`、`run.json`（全部命令）、`sensitivity/` |
| 7 报告 | `report.json`、`report.pdf`、`report.html`、`entry_sheet.csv` |
| 8 复核 | `review.json`：**尚未做**，须由没参与分析的新会话完成 |

这一单暴露并已处理的问题：

1. 候选池按校名匹配所在地时，“华北电力大学(保定)”被名单并入北京，实际在河北保定：`pool.py` 现在在 `note` 列提示“校区括号与名单所在地不符”，本案人工核对后剔除 12 个条目。
2. `pool.py --match` 连校名一起匹配（“信息工程”会命中南京信息工程大学的全部专业）：新增只看专业名的 `--match-major`、`--exclude-major`。
3. 报告里的“2026 年电气类整体变热约 8.5%”用 `scripts/category_shift.py` 可复算。
4. 中国计量大学官网对脚本访问设验证，不绕过：学费、校区、转专业写“未取到”，列入核对清单。
