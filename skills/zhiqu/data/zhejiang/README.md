# 浙江 · 普通类第一段平行投档数据

浙江实行"专业 + 院校"平行志愿，每行是一个院校的一个专业，跨年按"院校代号 + 专业名称"匹配（去掉括号内注释）。

| 文件 | 年份 | 来源 | 下载日期 |
|---|---|---|---|
| `general_2022.csv` | 2022 | 浙江省教育考试院《浙江省2022年普通高校招生普通类第一段平行投档分数线表》（rar 内 xls），<https://www.zjzs.net/art/2022/7/19/art_155_7241.html> | 2026-09-28 |
| `general_2023.csv` | 2023 | 同名 2023 年表，<https://www.zjzs.net/art/2023/7/19/art_45_2052.html> | 2026-09-28 |
| `general_2024.csv` | 2024 | 同名 2024 年表，<https://www.zjzs.net/art/2024/7/21/art_45_9899.html> | 2026-09-28 |
| `general_2025.csv` | 2025 | 同名 2025 年表，<https://www.zjzs.net/art/2025/7/21/art_45_11467.html> | 2026-09-28 |
| `general_2026.csv` | 2026 | 同名 2026 年表，<https://www.zjzs.net/art/2026/7/21/art_45_12550.html> | 2026-09-28 |

列：`code` 学校代号，`name` 学校名称（已去掉"（一流大学建设高校）"等后缀），`major_code` 专业代号，`major` 专业名称，`plan` 计划数，`score` 分数线，`rank` 位次。

- 位次为空表示该专业本轮投档人数未满（官方表注），回测时排除。
- 2021 年官方页面（zjzs.net/moban/index/8a11f1547aa7a49c017abc8b5de900fc.html）已 404，暂缺。


## 提前录取（`early_general.csv`）

列：`year, code, name, loc, major, subjects, admit, years, avg, score, rank`。来源：浙江省教育考试院《浙江省普通高校招生投档及专业录取情况》2023—2025 年（<https://www.zjzs.net/art/2026/6/22/art_45_12416.html>）中"普通类提前录取各专业录取情况"一节，PDF 文本提取，下载日期 2026-09-29。按书中说明，有政审、面试、三位一体、综合评价、定向等特殊要求的提前录取不在其中；2026 年的书尚未出版。
