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

## 普通类历史本科批投档（`history_2025.csv`）

| 年份 | 官方来源 | 查询日期 |
|---|---|---|
| 2025 | 广东省教育考试院《广东省2025年本科普通类（历史）投档情况》PDF，<https://eea.gd.gov.cn/attachment/0/585/585885/4746781.pdf>（发布页：<https://eea.gd.gov.cn/ptgk/content/post_4746781.html>） | 2026-09-30 |

列与同年 `physics_2025.csv` 一致：`code,name,group,plan,admit,score,rank`。PDF 共 35 页，整理为 1,637 行（前 34 页每页 47 行，末页 39 行）；保留 3 条无最低分/位次的零投档行。文本层混入了斜置“广东省教育考试院”水印字，清理时按院校代码与同年官方物理表及教育部高校名单规范校名；个别新名未在名单中出现时按 PDF 字样核对。表只含专业组投档数据，不含组内专业。当前仅补齐 2025，2024、2026 历史类表仍待获取；不据此声称广东各年已齐。

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
