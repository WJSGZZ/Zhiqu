# 大学排名快照

| 文件 | 内容 |
|---|---|
| `bcur_2025.csv` | 2025 软科中国大学排名主榜，589 所有具体名次，其余为 500+ |
| `arwu_2025.csv` | 2025 软科世界大学学术排名（ARWU）前 1000，101 名后为区间 |
| `sources.csv` | 两个快照的来源与指纹 |

用途只有一个：给没有软科名次的学校（中外合办、新校）按录取位次换算等效名次，见 `scripts/school_equivalence.py` 和 [school-research.md](../../references/school-research.md#没有排名的学校等效名次)。排名是第三方评价，换年时整体替换并更新 sources.csv；不在报告里把排名当学校质量的定论。
