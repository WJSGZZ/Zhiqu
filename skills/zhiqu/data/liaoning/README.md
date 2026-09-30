# 辽宁 · 普通类本科批物理学科类投档最低分（专业+院校，只公布分数）

| 年份 | 来源页面 |
|---|---|
| 2021 | <https://www.lnzsks.com/newsinfo/IMS_20210720_40207_h1JvM86IBU.htm> |
| 2022 | <https://www.lnzsks.com/newsinfo/IMS_20220720_41780_qHXx8p7S9E.htm> |
| 2023 | <https://www.lnzsks.com/newsinfo/IMS_20230720_42967_xuHWw7pSO3.htm> |
| 2024 | <https://www.lnzsks.com/newsinfo/IMS_20240720_44109_OymtAPK6ag.htm> |
| 2025 | <https://www.lnzsks.com/newsinfo/IMS_20250720_45051_8gfnOHDWBK.htm> |
| 2026 | <https://www.lnzsks.com/newsinfo/IMS_20260721_46231_UeWXLvA8x6.htm> |

下载日期：2026-09-28。列：`code, name, group, major, plan, admit, score, rank`（缺的留空）。

- 来源：辽宁省招生考试办公室（辽宁招生考试之窗），xls/xlsx；2025 年文件带默认只读保护，用标准默认密码解开。
- 官网未公开一分一段表（仅考生登录后可下载），因此只能用分数模式回测（`--metric score`）。
- 投档最低分为 0 表示无人投档，已视为缺失。

## 历史学科类（普通类本科批，2024—2026）

| 年份 | 官方发布页 | 历史学科类附件 | 投档行数（不含表头） | score 行数 | rank 行数 |
|---|---|---|---:|---:|---:|
| 2024 | <https://www.lnzsks.com/newsinfo/IMS_20240720_44109_OymtAPK6ag.htm> | <https://www.lnzsks.com/lnzkbfiles/2024/2024gkbkptdxosiexie01w.zip> | 3,674 | 3,674 | 0 |
| 2025 | <https://www.lnzsks.com/newsinfo/IMS_20250720_45051_8gfnOHDWBK.htm> | <https://www.lnzsks.com/lnzkbfiles/2025/2025gklqfsxbkdiedcpade0720w.xlsx> | 3,504 | 3,504 | 0 |
| 2026 | <https://www.lnzsks.com/newsinfo/IMS_20260721_46231_UeWXLvA8x6.htm> | <https://www.lnzsks.com/lnzkbfiles/2026/2026gklubkfsz0721w.xlsx> | 3,421 | 3,421 | 0 |

对应文件为 `history_2024.csv`、`history_2025.csv`、`history_2026.csv`。沿用投档数据主字段 `code, name, group, major, plan, admit, score, rank`，并增加 `major_code, score_bound, rank_bound` 保留原专业代号和边界/缺失解释。官方附件只公开专业投档最低分，`plan`、`admit` 留空。2024 ZIP 内含历史学科类 xlsx；2025 xlsx 为官方只读保护文件，使用本机 LibreOffice 读取转换到临时副本后抽取，未改写源数据。若源分值为0，则按本文件规则视为无人投档，`score` 留空、`score_bound` 留下原值及说明。

辽宁招生考试之窗未公开历史学科类一分一段/累计位次表（考生成绩统计需个人登录查询），因此三年 `rank` 均留空，并在每行 `rank_bound` 明确说明；不能把学校分数线换算成估算位次。按官方附件工作表中的院校编号+专业编号抽取完整行，院校编号+专业编号复合键无重复；数据校验器按“院校编号+专业名称”报告 2024/2025/2026 分别 17/22/32 条重复，是同校不同专业编号下同名专业，按原始行保留、不合并；同分行未合并。三年表都只覆盖普通类本科批的历史学科类，不包含提前批、艺术/体育、征集志愿、录取人数或计划数。
