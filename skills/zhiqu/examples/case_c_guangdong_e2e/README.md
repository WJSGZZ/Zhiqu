# 案例 C：用真实问卷从头到尾跑一次（虚构考生，广东 2027）

目的：检验整条流程，而不是给出完整志愿表。画像由 `index.html` 问卷实际生成（虚构作答：广东物理类、位次 30,500、想考公、在计算机和法学之间纠结、梦校广东工业大学）。候选只放了广工的 8 个专业组，用来演示组内专业分配模型；正式填报应补足其他学校。

| 文件 | 内容 |
|---|---|
| `candidates.csv` | 广工 8 个专业组：历年组线 + 组内各专业 2025 年最低排位（`majors`，来自广工招生网）+ 分配规则（`rule=score`，2026 招生章程第 25 条） |
| `result.json` | `optimize.py` 输出 |
| `report.json` / `report.pdf` | 决策报告 |

重现：

```bash
python3 scripts/optimize.py examples/case_c_guangdong_e2e/candidates.csv --rank 30500 --slots 45 \
  --u-fall -60 --max-fall 0.01 --drift 0.06 --target-year 2027 --sigma-scale 1.6 --sigma-rule legacy \
  --json examples/case_c_guangdong_e2e/result.json
python3 scripts/report.py examples/case_c_guangdong_e2e/report.json \
  --opt examples/case_c_guangdong_e2e/result.json --out examples/case_c_guangdong_e2e/report.pdf
```

这次跑通暴露并已修复的问题：

1. 问卷不记录高考年份 → 技能第 1 步改为推断后向考生确认。
2. 没有把本省数据变成候选表的工具，也没有院校所在地 → 新增 `scripts/pool.py` 和 `data/schools.csv`（教育部 2025 年全国普通高校名单），可按"留本省""只要公办"筛选。
3. 广东投档表没有组内专业和选科要求 → 技能写明要逐校查招生网（广工的表格是图片，由 AI 读图并与组线核对）。
4. 组内分配模型的缺陷：组内最松的专业线应等于组线，原实现让"进了组却哪个专业都不够"的情况被高估（计算机组调剂概率虚高到 16%）→ 已改为以同年最松专业为基准，并按组线整体平移。
5. 报告对专业组的"最可能去向"显示了整组名称 → 改为"学校·最可能的专业"，满意度指标按组内实际专业计算。

> 注：本例生成于 2026-09-29 引入"按条目区分波动"之前，重现命令加了 `--sigma-rule legacy`。新版默认波动规则（v2，广东倍数 1.7）下，本例期望效用约 93.7、各组落点相差不到 2 个百分点；报告按旧规则生成，待重新生成。
