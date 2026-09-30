# 小禾 · 浙江 · 高考：喜欢哲学和历史，父母希望师范

完全虚构的人物，官方事实另列来源。报告分两个阶段，演示"带你走一遍"的完整流程：

1. **出分前（2026-09-30）：方向规划。不给正式志愿表，因为成绩、位次和当年招生计划都还没有。**
2. **假想出分后（虚构位次 58000）：用浙江 2022—2026 年官方投档位次，按她自己的排序、再按父母的排序，各跑一次志愿优化，比较两张表的差别。**

先读[报告正文](report.md)，或打开[网页版](report.html)与[PDF](report.pdf)。人物背景见[画像](profile.txt)。示例只演示方法，不能直接拿去替真实的人填报、报名或签约。

## 文件

| 文件 | 作用 |
|---|---|
| profile.txt | 按问卷字段整理的人物画像（人物完全虚构） |
| case.json | 时间线、阶段、预算、证据状态，以及假想后续阶段的全部输入 |
| candidates_after_score.csv | 候选池 79 个专业，备注列写明每项打分和理由；0/100 分锚定在本人确认的两个选项上 |
| candidates_after_score_parent_weights.csv | 同一候选池，按父母的排序（前景优先）打分 |
| result_after_score.json / result_after_score_parent_weights.json | optimize.py 的输出 |
| birth_input.json / birth_chart.json | 出生资料（只到省份，按北京时间）与排盘工具的实际输出 |
| calculations.json | 周岁与费用情景 |
| report.md / report.html / report.pdf | 同一份 12 节报告的正文、网页与打印版 |

## 复现（仓库根目录）

```bash
python3 skills/zhiqu/scripts/check_demos.py
python3 skills/zhiqu/scripts/render_report.py skills/zhiqu/examples/demo_2027_gaokao/report.md --out /tmp/demo_2027_gaokao.pdf
```

单独重跑志愿优化：

```bash
python3 skills/zhiqu/scripts/optimize.py skills/zhiqu/examples/demo_2027_gaokao/candidates_after_score.csv \
  --rank 58000 --slots 80 --u-fall -60 --max-fall 0.01 --drift 0.023 --sigma-scale 1.0 --target-year 2027 --seed 1
```

`check_demos.py` 会重新排盘、重算费用和 offer 数字，并按 case.json 记录的参数重跑高考优化器，结果必须和保存的一致。修改 case.json 里的假设后，用 `--write` 更新 calculations.json，再同步报告文字。
