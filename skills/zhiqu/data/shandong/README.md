# 山东 · 普通类常规批第 1 次志愿投档（专业+院校，只公布位次）

| 年份 | 来源页面 |
|---|---|
| 2023 | <https://www.sdzk.cn/NewsInfo.aspx?NewsID=6279> |
| 2024 | <https://www.sdzk.cn/NewsInfo.aspx?NewsID=6656> |
| 2025 | <https://www.sdzk.cn/NewsInfo.aspx?NewsID=6996> |
| 2026 | <https://www.sdzk.cn/NewsInfo.aspx?NewsID=7312> |

下载日期：2026-09-28。列：`code, name, group, major, plan, admit, score, rank`（缺的留空）。

- 来源：山东省教育招生考试院，xls。
- 2026 年表不含计划数，改列选考科目要求。
- 跨年按院校名称 + 专业名称匹配（`--school name`）。


## 一分一段（`yfyd_YYYY.csv`，2023—2026）

来源：山东省教育招生考试院《YYYY 年夏季高考文化成绩一分一段表》（xls，无验证码，下载日期 2026-10-07）：[2026](https://www.sdzk.cn/NewsInfo.aspx?NewsID=7258)、[2025](https://www.sdzk.cn/NewsInfo.aspx?NewsID=6943)、[2024](https://www.sdzk.cn/NewsInfo.aspx?NewsID=6577)、[2023](https://www.sdzk.cn/NewsInfo.aspx?NewsID=6212)。官方表除“全体”外还分选考物理、化学、生物、思想政治、历史、地理各科的本段与累计人数，这里只取“全体”（山东按总成绩位次投档，不按单科排名）。列 `score,count,cum,source`；首行是合并档（累计含更高分），已标明。每年 543—548 行，最高档 2026 年 697、2025 年 692、2024 年 696、2023 年 697，最低到 150 分（线下没有位次）；校验：累计 = 上一行累计 + 本段人数逐行成立，分数无缺口，`check_yfyd.py` 无错误。山东 2022 及以前（2020 年起首届新高考）尚未收。
