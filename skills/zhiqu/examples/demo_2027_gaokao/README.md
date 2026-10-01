# 小禾 · 17 岁 · 浙江高三：喜欢的，和稳妥的

> 喜欢哲学和历史，但大家都说不好就业，该不该坚持？师范是适合我，还是只是父母觉得稳？

小禾是一位模拟用户。她在浙江读普通公办高中，选考历史、政治、地理；作文和表达好，数学不稳；有截止日期会认真做，长期目标容易拖。家里每年能支持约 2.6 万元，父母希望她读师范、当老师，她不排斥，只是不想只因为"稳定"。

知衢陪她走两个阶段：

1. **出分前（2026-09-30）**：把"喜欢哲学"拆成能体验的日常，保留中文、哲学与历史、师范、法学四个方向，定好体验和检查点。
2. **模拟出分（位次 58000）**：用浙江 2022—2026 年官方投档位次预测 2027 年录取线，按她自己的排序、再按父母的排序各排一张志愿表，看分歧到底有多大。学费和住宿费用浙外 2026 年招生章程的标准估算。

先读[报告正文](report.md)，或打开[网页版](report.html)与[PDF](report.pdf)。她的完整自述见[画像](profile.txt)。

示例只演示方法，不能直接拿去替真实的人填报、报名或签约。

## 文件

| 文件 | 作用 |
|---|---|
| profile.txt | 按问卷字段整理的人物画像（模拟用户） |
| case.json | 时间线、阶段、预算、证据状态，以及模拟后续阶段的全部输入 |
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
