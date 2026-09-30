# 小林 · 广东 · 读研：想读电气，怕备考和秋招两头落空

完全虚构的人物，官方事实另列来源。报告分两个阶段，演示"带你走一遍"的完整流程：

1. **初试前（2026-09-30）：比较考研、就业、合作办学等路径，核对预算和时间窗口。**
2. **假想初试成绩（330/355/380/400）：放进华南理工大学电气专硕 2025、2026 年官方录取者的初试分布里看位置，不换算成个人录取概率。**

先读[报告正文](report.md)，或打开[网页版](report.html)与[PDF](report.pdf)。人物背景见[画像](profile.txt)。示例只演示方法，不能直接拿去替真实的人填报、报名或签约。

## 文件

| 文件 | 作用 |
|---|---|
| profile.txt | 按问卷字段整理的人物画像（人物完全虚构） |
| case.json | 时间线、阶段、预算、证据状态，以及假想后续阶段的全部输入 |
| case.json 中的 hypothetical_followup | 华工官方拟录取初试成绩统计（按普通计划、基地计划分开），只保存统计值，不含考生个人信息 |
| birth_input.json / birth_chart.json | 出生资料（只到省份，按北京时间）与排盘工具的实际输出 |
| calculations.json | 周岁与费用情景 |
| report.md / report.html / report.pdf | 同一份 12 节报告的正文、网页与打印版 |

## 复现（仓库根目录）

```bash
python3 skills/zhiqu/scripts/check_demos.py
python3 skills/zhiqu/scripts/render_report.py skills/zhiqu-grad/examples/demo_2027/report.md --out /tmp/demo_2027.pdf
```

`check_demos.py` 会重新排盘、重算费用和 offer 数字，并按 case.json 记录的参数重跑高考优化器，结果必须和保存的一致。修改 case.json 里的假设后，用 `--write` 更新 calculations.json，再同步报告文字。
