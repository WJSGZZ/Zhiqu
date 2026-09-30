# 湖南 · 本科批（普通类）第一次投档分数线（首选物理，院校专业组，只公布分数）

| 年份 | 来源页面 |
|---|---|
| 2023 | <http://jyt.hunan.gov.cn/jyt/sjyt/hnsjyksy/web/ksyzkzx/202307/t20230720_29406553.html> |
| 2024 | <https://jyt.hunan.gov.cn/jyt/sjyt/hnsjyksy/web/ksyzkzx/202407/t20240720_33360671.html> |
| 2025 | <https://jyt.hunan.gov.cn/jyt/sjyt/hnsjyksy/web/ksyzkzx/202507/t20250720_33744762.html> |
| 2026 | <https://jyt.hunan.gov.cn/jyt/sjyt/hnsjyksy/web/ksyzkzx/202607/t20260719_34029635.html> |

下载日期：2026-09-28。列：`code, name, group, major, plan, admit, score, rank`（缺的留空）。

- 来源：湖南省教育考试院（文件托管于 hneeb.cn），xls/xlsx；2026 年为 Strict OOXML 格式。
- 表中不含选科要求，只能按组号匹配，跨年可比性差。


## 位次（2026-09-30 补充）

`physics_<年份>.csv` 的原 `rank` 曾按同年官方《普通高考档分 1 分段统计表（物理科目组合）》累计人数换算。复核后发现，湖南地方性加分仅适用于向省属高校投档，2023、2024 一分段表分别列出“含全国性加分”与“含全国性和地方性加分”两套排名；先前统一取全国性加分列会与部分省属高校投档分不一致。因此本次已清空 `physics_2023.csv`、`physics_2024.csv` 的 `rank`。新增 `rank_bound` 只保留原换算累计数供追溯，不是可认证的精确位次，也不是数学上下界。官方规则与说明：[2023 招生实施办法](https://jyt.hunan.gov.cn/jyt/sjyt/xxgk/zcfg/gfxwj/202306/t20230627_1100994.html)明确地方性加分仅用于省属高校；[2024 招生实施办法](https://jyt.hunan.gov.cn/jyt/sjyt/xxgk/tzgg/202405/t20240531_33317217.html)同样作此区分；[2024 一分段表使用说明](https://jyt.hunan.gov.cn/jyt/sjyt/hnsjyksy/web/ksyzkzx/202406/t20240624_33335278.html)说明按加分适用范围分别统计。官方一分段网页表格整理为 `yfyd_physics_<年份>.csv`，原表累计递推仍可核验，但不能据此恢复上述两年的精确 `rank`。

| 年份 | 来源 |
|---|---|
| 2026 | <https://jyt.hunan.gov.cn/jyt/sjyt/hnsjyksy/web/ksyzkzx/202606/t20260625_34013125.html> |
| 2025 | <https://www.hneeb.cn/hnxxg/741/742/content_4434.html> |
| 2024 | <https://www.hneeb.cn/hnxxg/741/742/content_4207.html> |
| 2023 | <https://www.hneeb.cn/hnxxg/741/742/content_3941.html>（与湖南省教育厅网站同名页面核对一致） |


## 本科批普通类历史类第一次投档线（2026-09-30）

| 文件 | 年份 | 官方来源 | 筛选后完整数据行数 | 空投档线 |
|---|---:|---|---:|---:|
| `history_2024.csv` | 2024 | [湖南省教育考试院本科批第一次投档线](https://jyt.hunan.gov.cn/jyt/sjyt/hnsjyksy/web/ksyzkzx/202407/t20240720_33360671.html)（附件 XLSX） | 1666 | 82 |
| `history_2025.csv` | 2025 | [湖南省教育考试院本科批第一次投档线](https://jyt.hunan.gov.cn/jyt/sjyt/hnsjyksy/web/ksyzkzx/202507/t20250720_33744762.html)（附件 XLSX） | 1737 | 91 |
| `history_2026.csv` | 2026 | [湖南省教育考试院本科批第一次投档线](https://jyt.hunan.gov.cn/jyt/sjyt/hnsjyksy/web/ksyzkzx/202607/t20260719_34029635.html)（附件 ZIP 内 XLSX） | 1898 | 76 |

筛选条件为“本科批(普通) / 普通类 / 普通类(首选历史)”。统一列为 `code,name,group,major,plan,admit,score,rank`；原表没有计划数、投档人数及位次，故 `plan/admit` 留空。`rank` 仅在下节按同年同科类、同加分口径核验一分段表后填入；不满足精确匹配条件时留空。原表投档线空白表示该组线上生源不足，按说明保留空 `score`，不删除该记录。湖南表未提供选科组合，`major` 保留官方专业组名称，不自行补写选科要求。2026 附件为 Strict OOXML，按工作表 XML 与共享字符串读取。下载与整理日期：2026-09-30。

## 历史类位次（2026-09-30 补充）

仅 2025、2026 可按同科类精确档分换算。`rank` 记作相同档分的累计人数（并列位次上界）；不对表外分数、表内缺分记录或缺失分段插值。

| 年份 | 一分一段表官方来源 | 精确档分表范围 | 原表条目数 | 与投档线精确匹配 | 说明 |
|---|---|---:|---:|---:|---|
| 2026 | [湖南省教育考试院：历史科目组合档分1分段表](https://jyt.hunan.gov.cn/jyt/sjyt/hnsjyksy/web/ksyzkzx/202606/t20260625_34013108.html) | 100—656 | 548 个精确分段，另有“100分以下”汇总行 | 1818 / 1898 | 表头注明“含优惠加分”；表内本段人数与累计人数逐行递推一致。 |
| 2025 | [湖南招生考试信息港：历史科目组合档分1分段表](https://www.hneeb.cn/hnxxg/741/742/content_4433.html) | 100—657 | 549 个精确分段，另有“100分以下”汇总行 | 1642 / 1737 | 表头注明“含优惠加分”；表内本段人数与累计人数逐行递推一致。 |
| 2024 | [湖南招生考试信息港：历史科目组合档分1分段表](https://www.hneeb.cn/hnxxg/741/742/content_4206.html) | — | — | 0 | 官方表同时列出“含全国性加分”与“含全国性和地方性加分”两套累计人数；投档线文件对地方性加分的适用范围作区分，不能为整张投档表指定单一累计列，故不换算。 |

2025、2026 一分一段表表头均注明“含优惠加分”；当年湖南省教育考试院招生问答也明确普通类投档成绩为高考文化成绩（含政策性加分）：[2025 招生问答](https://jyt.hunan.gov.cn/jyt/sjyt/hnsjyksy/web/ksyzkzx/202506/t20250623_33718159.html)、[2026 招生问答](https://jyt.hunan.gov.cn/jyt/sjyt/hnsjyksy/web/ksyzkzx/202606/t20260616_34004507.html)。因此投档分与同年累计表的科类、分数加分口径相符。2025、2026 原表分别整理为 `yfyd_history_2025.csv`、`yfyd_history_2026.csv`，保留官方“100分以下”汇总行但不把它当作100分精确分段；原表存在未列出的分值，未插值。2025 年 95 条、2026 年 80 条投档记录没有 rank：其中分别有 91、76 条原表投档分为空，另各有 4 条非空分数超出对应公布范围（2025：658、659、660、665；2026：657、658、661、666）。查询、整理日期：2026-09-30。位次只是同年同科类档分累计人数，不能当作专业录取位次。
