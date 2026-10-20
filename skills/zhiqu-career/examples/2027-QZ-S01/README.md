# 小宁 · 20 岁 · 四川高职会计：第一份工作，不必替你决定一生

> 如果先去小公司做财务，是不是就比升本差？"国企"两个字到底意味着什么？

小宁是一位模拟用户。他在四川读三年制高职大数据与会计，实习做过凭证录入，初级会计还没考过；细致、慢热，喜欢把账对上，不想做推销。家里支持有限，毕业三个月内就要有收入；父母希望他考编或进国企。

知衢陪他走两个阶段：

1. **求职开始时（2026-09-30）**：找出能胜任又有收入的岗位方向，把专升本作为有条件的选项，算清时间和钱。
2. **模拟拿到两个 offer**：直签但要租房，和劳务派遣但离家近。按个税规则、四川 2026 年社保基数上下限和公积金，算到手收入、时薪和每月结余。

先读[报告正文](report.md)，或打开[网页版](report.html)与[PDF](2027-QZ-S01-report.pdf)。他的完整自述见[画像](profile.txt)。

示例只演示方法，不能直接拿去替真实的人填报、报名或签约。

## 文件

| 文件 | 作用 |
|---|---|
| profile.txt | 按问卷字段整理的人物画像（模拟用户） |
| case.json | 时间线、阶段、预算、证据状态，以及模拟后续阶段的全部输入 |
| case.json 中的 hypothetical_followup | 两个模拟 offer 的全部输入、四川工资价位与最低工资 |
| calculations.json | check_demos.py 算出的预算和 offer 数字 |
| birth_input.json / birth_chart.json | 出生资料（只到省份，按北京时间）与排盘工具的实际输出 |
| profile_parse.json / directions.json / rules_check.json / candidates.json | 画像字段、问题方向、规则与候选硬条件 |
| evidence.json / judgment.json / narrative.json | 唯一证据记录、结构化判断与受控文字 |
| operator_check.md / review.json / report_trace.json | 交付前核查、复核和输入与产物快照 |
| report.md / report.html / 2027-QZ-S01-report.pdf | 同一份 12 节报告的正文、网页与打印版 |

## 复现（仓库根目录）

```bash
python3 skills/zhiqu/scripts/case_check.py skills/zhiqu-career/examples/2027-QZ-S01 --stage 7
python3 skills/zhiqu/scripts/planning_report.py skills/zhiqu-career/examples/2027-QZ-S01
python3 skills/zhiqu/scripts/check_demos.py
python3 skills/zhiqu/scripts/case_check.py skills/zhiqu-career/examples/2027-QZ-S01 --stage 10
```

阶段文件逐项记录画像解析、问题方向、规则、候选、证据、计算输入及判断；`narrative.json`只放受控的分析文字。组装器按[内容合同](../../references/report-contract.json)生成报告，随后核版面、来源和数字。修改输入后须更新来源绑定并重算，再由组装器生成；不手改生成的正文。

[操控者核查单](operator_check.md)单独列出核什么、去哪里核、核完填什么；操控者是交付报告前亲自核查关键信息的人。本例全部勾选待实际核查。[复核记录](review.json)保留制作自评并等待独立审核，检查步骤通过不代表已获准真实交付；`--delivery`会继续检查本人核查与独立批准。

`check_demos.py`重新排盘、复算既有预算及条件情景，并检查工作流和生成快照。没有真实录取或offer，不把条件情景当成已经获得的选择。
