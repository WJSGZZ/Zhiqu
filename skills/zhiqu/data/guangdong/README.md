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


## 提前批与专项（`early_physics.csv`）

列：`year, subject, type, code, name, group, plan, admit, score, rank`。含物理、历史两类，`type` 为官方分类（军检、面试院校 / 非军检、面试院校 / 教师专项 / 农村卫生专项 / 特殊类型招生（高校专项计划）/ 空军、海军招飞院校）。

| 年份 | 来源 |
|---|---|
| 2026 | <https://eea.gd.gov.cn/ptgk/content/post_4923339.html>、<https://eea.gd.gov.cn/ptgk/content/post_4923886.html>、<https://eea.gd.gov.cn/ptgk/content/post_4924250.html>（仅物理类） |
| 2025 | <https://eea.gd.gov.cn/ptgk/content/post_4742803.html>、<https://eea.gd.gov.cn/ptgk/content/post_4743597.html>、<https://eea.gd.gov.cn/ptgk/content/post_4746199.html>（仅物理类） |
| 2024 | <https://eea.gd.gov.cn/ptgk/content/post_4453920.html>、<https://eea.gd.gov.cn/ptgk/content/post_4455004.html>（压缩包；非军检表内含教师专项） |
| 2023 | <https://eea.gd.gov.cn/ptgk/content/post_4217777.html>（非军检）；军检院校投档页面没有附件，暂缺 |

下载日期 2026-09-29，均为官方 PDF 文本提取。2023—2025 年教师专项、农村卫生专项未单独找到附件。
