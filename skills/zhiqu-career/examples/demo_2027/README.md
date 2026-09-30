# 小宁：高职毕业前，收入与升本怎样取舍

这是一个完全虚构的普通人案例，决策时点为2026-09-30，目标年份2027。人物、经历、生日与费用情景均为设定，官方事实另列来源；不含真实个人资料，不声称具有统计代表性。

先读[报告正文](report.md)，或打开[HTML报告](report.html)与[PDF报告](report.pdf)。人物背景见[画像](profile.txt)。本例示范怎样在结果未知时做规划，不能直接拿去替本人填报、报名或签约。具体阶段、证据范围与不确定性写在报告中。

## 复现（仓库根目录）

```bash
python3 skills/bazi/scripts/calculate_bazi.py skills/zhiqu-career/examples/demo_2027/birth_input.json > /tmp/zhiqu-career-chart.json
python3 skills/zhiqu/scripts/check_demos.py
python3 skills/zhiqu/scripts/render_report.py skills/zhiqu-career/examples/demo_2027/report.md --out /tmp/zhiqu-career-report.html
python3 skills/zhiqu/scripts/render_report.py skills/zhiqu-career/examples/demo_2027/report.md --out /tmp/zhiqu-career-report.pdf
```

PDF需要本机Chrome、Edge或Chromium；没有浏览器时先生成HTML。工具只负责计算与排版，不能验证官方资料是否完整。修改case.json中的明确费用假设后，用check_demos.py --write更新calculations.json，并同步报告文字再重现。

## 文件与可信度

| 文件 | 作用 |
|---|---|
| profile.txt | 按问卷字段整理的人物画像，不声称为网页逐字导出 |
| case.json | 虚构标记、学籍时间线、阶段、预算与候选的证据状态；未知概率与结果留null |
| birth_input.json / birth_chart.json | 显式时间、时区、经度、误差与传统顺逆参数，以及工具实际输出 |
| calculations.json | 实际运行得到的周岁与预算情景，不是学费、工资或录取事实 |
| report.md / report.html / report.pdf | 同一份12节报告的可编辑正文、网页与打印版 |

出生日期先按学制选择，再实际排盘，不按性格倒选命盘。本次法定时间、平太阳时、真太阳时、换日口径与±10分钟产生同一候选。历法可以核算；命理主题不能证明现实能力、考试结果或工作适配，删掉八字不会改变正式建议。

本轮替换了旧claude/demo算例的叙事与证据处理，未沿用其未经核准的个人概率、专业组猜测或旧起运整数年龄。
