# 江苏 · 普通类本科批次平行志愿投档线（物理等科目类，院校专业组，只公布分数）

| 年份 | 来源页面 |
|---|---|
| 2023 | <https://www.jseea.cn/webfile/index/index_zkxx/2023-07-18/7086888854866628608.html> |
| 2024 | <https://www.jseea.cn/webfile/index/index_zkxx/2024-07-18/7219509116052443136.html> |
| 2025 | <https://www.jseea.cn/webfile/index/index_zkxx/2025-07-18/7351781448019349504.html> |
| 2026 | <https://www.jseea.cn/webfile/index/index_zkxx/2026-07-18/7484048378054053888.html> |

下载日期：2026-09-28。列：`code, name, group, major, plan, admit, score, rank`（缺的留空）。

- 来源：江苏省教育考试院，2023—2024 年 xls，2025—2026 年 PDF。
- 2025—2026 年 PDF 抽取时，页面水印"江苏省教育考试院"的单字混进了约 14% 行的校名开头（如"育南京大学""江东南大学"）；2026-09-30 按"同一院校代码的干净校名"去掉，共改 907 行，分数、组号等其他列未动。
- `group` 为专业组号，`major` 列存再选科目要求。组号每年重编，按"学校 + 选科要求"匹配（`--key major`）更可靠。


## 本科提前批次（`early_physics.csv`）

列：`year, type, code, name, group, subjects, region, score`（`region` 为定向地区）。物理等科目类，官方 xls，下载日期 2026-09-29：

| 年份 | 来源 |
|---|---|
| 2026 | <https://www.jseea.cn/webfile/index/index_zkxx/2026-07-08/7480462685813870592.html> |
| 2025 | <https://www.jseea.cn/webfile/index/index_zkxx/2025-07-08/7348163942021074944.html> |
| 2024 | <https://www.jseea.cn/webfile/index/index_zkxx/2024-07-08/7215906858794487808.html> |
| 2023 | <https://www.jseea.cn/webfile/index/index_zkxx/2023-07-08/7083248582249156608.html> |

2023 年"军事"已统一记为"军队"。2026 年分类改为"专项计划"（约 100 所院校），不再单列地方专项计划和乡村教师计划。


## 位次（2026-09-30 补充）

`physics_<年份>.csv` 的 `rank` 列由同年官方逐分段统计表换算：位次 = 该投档最低分对应的累计人数。统计表只以图片发布，整理为 `yfyd_physics_<年份>.csv`（`score,count,cum,source`）：

| 年份 | 来源 | 分数范围 | 双重确认的行 |
|---|---|---|---|
| 2026 | <https://www.jseea.cn/webfile/index/index_zkxx/2026-06-24/7475494421979467776.html> | 689—456 | 174 / 234 |
| 2025 | <https://www.jseea.cn/webfile/index/index_zkxx/2025-06-24/7343234265133355008.html> | 683—463 | 195 / 221 |
| 2024 | <https://www.jseea.cn/webfile/index/index_zkxx/2024-06-24/7210960924591525888.html> | 689—462 | 215 / 228 |
| 2023 | <https://www.jseea.cn/webfile/index/index_zkxx/2023-06-24/7078350479809318912.html> | 687—448 | 214 / 240 |

识别方法：分数按行位置推算（粗体分数常被误读），人数与累计由 OCR 读取；`source` 列标明每行的可信度——"确认"= 人数与累计互相吻合，"累计"= 累计与上下行单调一致，"人数"= 只读到人数、由上一行累计推出，"插值"= 该行未读到、在相邻两行之间线性插值。低于表内最低分的投档记录（共 15 条）不补位次。


## 普通类本科批历史类投档线（2026-09-30）

| 文件 | 年份 | 官方来源 | 完整表数据行数 | 空分数 |
|---|---:|---|---:|---:|
| `history_2024.csv` | 2024 | [江苏省教育考试院本科批投档线（附件：历史等科目类 XLS）](https://www.jseea.cn/webfile/index/index_zkxx/2024-07-18/7219509116052443136.html) | 1238 | 0 |
| `history_2025.csv` | 2025 | [江苏省教育考试院历史等科目类 PDF](https://www.jseea.cn/webfile/index/index_zkxx/2025-07-18/7351781284785426432.html) | 1290 | 0 |
| `history_2026.csv` | 2026 | [江苏省教育考试院历史等科目类 PDF](https://www.jseea.cn/webfile/index/index_zkxx/2026-07-18/7484047541940523008.html) | 1424 | 0 |

列与物理类文件相同：`code,name,group,major,plan,admit,score,rank`。代码、校名、专业组、选科要求和最低投档分来自官方表；PDF 的同分排序列不录入本 schema。原表没有计划数、投档人数及位次，故 `plan/admit/rank` 留空，未用一分一段表换算 rank。2025、2026 PDF 的长组名跨行文本已与后续分数字段拼接；逐页解析共计1290/1424条，与表内院校专业组记录数一致。下载与整理日期：2026-09-30。

## 历史类位次核查（2026-09-30）

本轮没有生成 `yfyd_history_<年份>.csv`，也没有填历史类 `rank`。江苏省教育考试院 2025、2026 年一分一段表在发布页以独立 JPG 发布：[2025 发布页](https://www.jseea.cn/webfile/index/index_zkxx/2025-06-24/7343234265133355008.html)，[2026 发布页](https://www.jseea.cn/webfile/index/index_zkxx/2026-06-24/7475494421979467776.html)。尚未完成历史类图片所有分数段的逐行转录、完整条目数核验和档分加分口径与历史投档表的一致性确认；2024两张、2025/2026各一张历史类原图已取得，但仍未完成上述认证。最高档为“651分及以上 / 658分及以上 / 657分及以上”等合并区间，不能当作精确分段位次。因此不以物理类一分一段表代用，也不填部分 OCR 或推测的位次。待上述原表完整复核后再考虑补录。
