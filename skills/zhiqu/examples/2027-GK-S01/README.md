# 付费样板：2027 年浙江，想进电网的电气方向（模拟考生小远）

用来演示一单报告从取数到出稿的完整个案流程。考生是模拟的，位次 33,000 是模拟出分；历年位次、志愿规则、院校章程与就业报告来自官方页面，每条带来源和查询日期。选考要求已用浙江官方 2027 版表逐专业核对（`scripts/subject_check.py`：143 个候选中 131 个符合、0 个不符合、12 个未查到）；2027 年的招生计划、章程、一分一段表尚未公布，所以按 `simulation` 模式运行：资格总体仍为待核，**不能直接填报**。它是流程示范；对外样板用同一人物的回溯版 [2026-GK-R01](../2026-GK-R01/README.md)。

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
| 8 复核 | `review.json`：2026-10-16 第一次独立复核不通过（同分规则转述、参数口径不统一、变热情景幅度、100 分定义等），逐条修改后，2026-10-17 第二次独立复核**通过**（计算逐位重现，抽查 12 条来源全部一致；剩余低级别事项见记录） |

这一单暴露并已处理的问题：

1. 候选池按校名匹配所在地时，“华北电力大学(保定)”被名单并入北京，实际在河北保定：`pool.py` 现在在 `note` 列提示“校区括号与名单所在地不符”，本案人工核对后剔除 11 个条目。
2. `pool.py --match` 连校名一起匹配（“信息工程”会命中南京信息工程大学的全部专业）：新增只看专业名的 `--match-major`、`--exclude-major`。
3. 报告里的“2026 年电气类整体变热约 8%（对数中位数 −0.085）”用 `scripts/category_shift.py` 可复算。
4. 中国计量大学官网对脚本访问设验证，不绕过；2026 年章程后来在阳光高考（教育部平台）取得，学费、校区、体检限制已补，转专业细则仍未取到。
5. 本单的候选池是在 `pool.py` 统一全角、半角括号之前生成的（2026-10-17 修正）：浙江同一专业不同年份括号写法不一，当时有 11 个往年位次没拼上。用修正后的工具重跑，进入打分的 143 个候选里有 5 个往年位次补上，选出的 11 个志愿、顺序和概率都不变，所以本单文件不改。
