# 广东 · 普通类（物理）本科批投档数据

| 文件 | 年份 | 来源 | 下载日期 |
|---|---|---|---|
| `physics_2022.csv` | 2022 | 广东省教育考试院《广东省2022年本科普通类（物理）投档情况》PDF，<https://eea.gd.gov.cn/zwgk/sjfb/tjsj/content/post_3975483.html> | 2026-09-28 |
| `physics_2023.csv` | 2023 | 广东省教育考试院《广东省2023年本科普通类（物理）投档情况》PDF（附件压缩包），<https://eea.gd.gov.cn/ptgk/content/post_4221648.html> | 2026-09-28 |

列：`code` 院校代码，`name` 院校名称，`group` 专业组代码，`plan` 计划数，`admit` 投档人数，`score` 投档最低分，`rank` 投档最低排位。

整理说明：
- 由 PDF 表格自动抽取，并清洗了"广东省教育考试院"水印字符。2022 年 2566 行，其中 3 个组投档人数为 0、无最低分与排位；2023 年 2666 行。
- 原表中少数顶尖院校写作"683以上""88以内"，CSV 只保留数字（683、88），实际含义是"不低于/不超过"。
- 表中**没有组内专业**；专业组组成需另查当年招生专业目录或各校招生计划。
- 参考：2023 年物理类 569 分对应位次 54261（官方分数段统计表附件 2，扫描件，人工读取）。

## 2024—2026 年补充（2026-09-28）

| 文件 | 来源 |
|---|---|
| `physics_2024.csv` | <https://eea.gd.gov.cn/zwgk/sjfb/tjsj/content/post_4458419.html>（附件压缩包内 PDF） |
| `physics_2025.csv` | <https://eea.gd.gov.cn/ptgk/content/post_4746781.html> |
| `physics_2026.csv` | <https://eea.gd.gov.cn/ptgk/content/post_4926622.html> |

## 普通类历史本科批投档（`history_2022.csv`—`history_2026.csv`）

五个年度文件采用同一列序：`code,name,group,major,plan,admit,score,rank,score_bound,rank_bound`。`major` 留空，因为官方表列出的是专业组整体投档，不含组内专业。普通最低分/排位写入 `score`、`rank`；无投档的 `-` 留空；官方以区间文字表示的值留在 bound 列，不能当作精确数值。2022 年北京大学、清华大学原表分别写“651以上”“28以内”，因此精确列留空、边界原文记入 `score_bound` 和 `rank_bound`。

| 文件 | 行数 | PDF页数 | 无投档行 | 官方来源 | 查询日期 |
|---|---:|---:|---:|---|---|
| `history_2022.csv` | 1,288 | 41 | 0 | 广东省教育考试院《广东省2022年本科普通类（历史）投档情况》[PDF](https://eea.gd.gov.cn/attachment/0/494/494062/3975483.pdf)，[发布页](https://eea.gd.gov.cn/gkmlpt/content/3/3975/post_3975480.html) | 2026-09-30 |
| `history_2023.csv` | 1,381 | 33 | 0 | 广东省教育考试院[官方附件ZIP](https://eea.gd.gov.cn/attachment/0/526/526559/4221648.zip)（历史类PDF；[发布页](https://eea.gd.gov.cn/ptgk/content/post_4221648.html)） | 2026-09-30 |
| `history_2024.csv` | 1,448 | 29 | 5 | 广东省教育考试院[官方附件ZIP](https://eea.gd.gov.cn/attachment/0/554/554636/4458419.zip)（历史类PDF；[发布页](https://eea.gd.gov.cn/zwgk/sjfb/tjsj/content/post_4458419.html)） | 2026-09-30 |
| `history_2025.csv` | 1,637 | 35 | 3 | 广东省教育考试院《广东省2025年本科普通类（历史）投档情况》[PDF](https://eea.gd.gov.cn/attachment/0/585/585885/4746781.pdf)，[发布页](https://eea.gd.gov.cn/ptgk/content/post_4746781.html) | 2026-09-30 |
| `history_2026.csv` | 1,768 | 30 | 2 | 广东省教育考试院[历史类PDF](https://eea.gd.gov.cn/attachment/0/620/620024/4926622.pdf)（[发布页](https://eea.gd.gov.cn/ptgk/content/post_4926622.html)） | 2026-09-30 |

2022、2023、2024、2026 表格PDF由表格网格抽取（pdfplumber `extract_tables`），逐条保留官方代码、名称、组号、计划数、投档数、最低分和最低排位；按每页记录数汇总与文件行数相等，页脚总页数与PDF页数一致。2025 表为既有抽取，保留35页、1,637行的记录数。本轮复核名称时，2025 PDF第34页清晰列出`14001 | 聊城大学东昌学院 | 202 | 10 | 10 | 512 | 48720`，其前后行各字段也与表格列对齐；故按原表修正此前误用当前高校代码表造成的名称。2022、2023、2024、2026官方PDF中同一代码和名称也在表内逐年明确出现。扫描/文本抽取中的水印仅在出现独立前置字且同年官方物理类表能精确核实时清理；不得按当前院校名单覆盖官方原表名称。2026历史表代码10349的名称为“绍兴大学”，即使同年物理表名称不同，也保留历史表原文。

`score`、`rank` 均为空的记录数分别为：2022年2条边界档，2023年0条，2024年5条零投档，2025年3条零投档，2026年2条零投档。零投档行不提供精确最低分与位次，不推填数值。2022年另外两条边界档保留官方文字，不伪装为精确651分/28位。

## 一分一段表覆盖量（`../cohort_coverage.csv`）

2022、2025 普通类历史/物理分数段统计表均列有分数≥100的累计人数：

| 年份 | 科类 | 分数≥100累计人数 | 官方附件 |
|---|---|---:|---|
| 2022 | 历史 | 272,196 | <https://eea.gd.gov.cn/attachment/0/492/492287/3986282.pdf> |
| 2022 | 物理 | 399,216 | <https://eea.gd.gov.cn/attachment/0/492/492285/3986282.pdf> |
| 2025 | 历史 | 292,200 | <https://eea.gd.gov.cn/attachment/0/583/583759/4734449.zip>（第 1 项） |
| 2025 | 物理 | 440,208 | <https://eea.gd.gov.cn/attachment/0/583/583759/4734449.zip>（第 2 项） |

以上是分数段表在其公布下限（100 分）及以上的累计覆盖量。附件没有据此确认低于 100 分的人数或完整普通高考报考人数，因此 `is_all_exam_takers=false`，不能把这些值当作 `--cohort` 的总人数。2023、2024、2026 尚未补齐；附件查询日期为 2026-09-30。


## 提前批与专项（`early_physics.csv`）

列：`year, subject, type, code, name, group, plan, admit, score, rank`。含物理、历史两类，`type` 为官方分类（军检、面试院校 / 非军检、面试院校 / 教师专项 / 农村卫生专项 / 特殊类型招生（高校专项计划）/ 空军、海军招飞院校）。

| 年份 | 来源 |
|---|---|
| 2026 | <https://eea.gd.gov.cn/ptgk/content/post_4923339.html>、<https://eea.gd.gov.cn/ptgk/content/post_4923886.html>、<https://eea.gd.gov.cn/ptgk/content/post_4924250.html>（仅物理类） |
| 2025 | <https://eea.gd.gov.cn/ptgk/content/post_4742803.html>、<https://eea.gd.gov.cn/ptgk/content/post_4743597.html>、<https://eea.gd.gov.cn/ptgk/content/post_4746199.html>（仅物理类） |
| 2024 | <https://eea.gd.gov.cn/ptgk/content/post_4453920.html>、<https://eea.gd.gov.cn/ptgk/content/post_4455004.html>（压缩包；非军检表内含教师专项） |
| 2023 | <https://eea.gd.gov.cn/ptgk/content/post_4217777.html>（非军检）；军检院校投档页面没有附件，暂缺 |

下载日期 2026-09-29，均为官方 PDF 文本提取。2023—2025 年教师专项、农村卫生专项未单独找到附件。


## 专业组目录核查（2026-09-30）

广东工业大学的[2026 本科招生计划总表](https://zsb.gdut.edu.cn/info/2483/4821.htm)以图片发布，本轮页面可读但原图抓取失败；[2025 总表](https://zsb.gdut.edu.cn/info/2560/4573.htm)可读内容是全校专业计划，不能据此确认广东物理类本科普通批的逐组组成。[2026 招生章程](https://zsb.gdut.edu.cn/info/1144/4750.htm)第十六条明确分专业计划及要求以生源省招生目录为准。因此本轮没有新增逐组明细或跨年对应表：仍缺两年广东属地目录里的组号、选科、完整专业列表及校区/培养类型对应。此处记录的是本轮获取范围，不能解读为官方没有公开。学校代码或组线已有记录，也不能补出专业明细。

## 一分一段（`yfyd_{physics,history}_{2024,2025,2026}.csv`）

列：`score,count,cum,source`。来源是广东省教育考试院每年 6 月 25 日前后发布的《关于公布广东省 20XX 年普通高考成绩各分数段数据的通知》附件（文本 PDF，含"本科""专科"两套口径）：

| 年份 | 页面 |
|---|---|
| 2024 | <https://eea.gd.gov.cn/zwgk_tjxx/content/post_4445715.html> |
| 2025 | <https://eea.gd.gov.cn/ptgk/content/post_4734345.html> |
| 2026 | <https://eea.gd.gov.cn/ptgk/content/post_4916165.html> |

- 取"本科"列（分数段人数、累计人数均含本科层次加分），因为本科批投档最低排位按这一口径：2024—2026 年历史、物理本科批投档表里全部 12,000 余条（2024 年 4,563 条、2025 年 5,136 条、2026 年 6,014 条，分数在表内的）排位都落在该分数的累计区间 (cum(分+1), cum(分)] 内，0 条例外。
- 首行是合并档（"X 分及以上"，累计 = 该行人数）；每年物理类到 100 分、历史类到 100 分止。逐行核对"累计 = 上一行累计 + 本段人数"，并与 PDF 逐页文字的累计抽样点一致。
- 外购库里广东的一分一段是"专科"口径（含专科层次加分），累计比本科口径多 0—29 名；用外购库的广东累计当位次会略偏大，计算时用本目录的本科口径。
- 2022、2023 年的官方分数段表是体积很大的扫描件，未入库；2023 年物理 569 分的位次见上面的人工读取记录。
