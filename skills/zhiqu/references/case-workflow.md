# 个案流程：一份志愿报告怎样从取数做到复核

<!-- 核实：2026-10-07；复核期限：2027-07-01 -->

本文件定义一单报告的**中间产物和门槛**。思路是把规则从提示词搬到文件和脚本里：提示词写得再长，Agent 也可能跳过，脚本每次都会检查。命令都在技能目录执行：

```bash
python3 scripts/case_check.py <案例目录> --stage N    # 检查 0..N 阶段，上一步不全或对不上账就不能进下一步
```

脚本能保证"步骤做全、账对得上、数字有出处"，不能保证判断正确或来源真的这么写；这两件事靠阶段 8 的独立复核和人。**检查通过不等于分析正确。**

## 一、两层：省份层与个案层

按省份的数据大部分相同，所以分两层，避免每单重做：

- **省份层**（每省每年一次，多份报告共用）：放在 `data/<省>/`，核心是机器可读的 `rules.json`（样例：`data/zhejiang/rules.json`）加历年数据文件。取数时校对一次；用于某份报告时再校对一遍：历年数据已核过的不重查，当年会变的项（`volatile: true`）按核实日期判断，本单必须在阶段 3 逐项复核。
- **个案层**（每份报告做）：画像、方向、全量筛选、打分、计算、敏感性、院校调研、报告、复核。案例目录记下所用数据的仓库提交号，以后可复现。

### 省份层要提供的字段（给 T1 数据会话对齐）

`rules.json` 顶层：`province`、`mode`（专业+院校 / 院校专业组）、`category_system`、`rules_year`、`target_year_rules`（目标年规则未公布时怎么办）。

- `items.<键>`，每项 `{value, source(https), verified(日期), volatile(是否年年可能变)}`，键至少含：`slots`（志愿个数）、`parallel`（投档方式）、`ratio`（投档比例）、`tie_break`（同分规则）、`withdraw`（退档情形）、`subject_req`（选考/选科要求适用版本）、`fill_window`（填报时间）；有加分、专项、提前批的省另加对应键。
- `datasets`：`history`（年份、路径模板、口径、来源）、`yfyd`（一分一段，缺则 `status: 缺`）、`plan_current`（目标年计划，未公布写 `未公布` 和替代参照）、`subject_req_table`（选科要求表，未入库写 `未入库`）。
- `calibration`：`drift`、`sigma_floor`、`sigma_scale`、证据位置与核实日期。不借他省倍数。

数据缺项不是错误，但**必须显式写出**，个案在阶段 3 写明怎么处理。

## 二、案例目录与阶段门槛

案例目录 `cases/<报告编号>/`（本地，不提交，见 DESIGN）；样板放 `examples/` 下，编号用 `YYYY-GK-S01`；回溯样板（只用目标年以前的数据出稿，再用目标年真实投档线对照，判定用 `scripts/retro_judge.py`）用 `YYYY-GK-R01`。报告编号格式 `年份-GK-四位序号`。

| 阶段 | 文件 | 门槛（`case_check.py` 检查） |
|---|---|---|
| 0 登记 | `case.json` | 案例号与目录名一致；`mode`（formal / simulation）；准备日；`data_commit`；省份层文件存在；位次与志愿数 |
| 1 画像 | `profile.json`（旧版 `profile.txt`）、`profile_parse.json` | JSON 的 zhiqu=gaokao，或有效旧文字；九个关键字段都有状态（given / inferred / unknown）；推断值已向本人确认；未知项列入 `missing` |
| 2 方向 | `directions.json` | 2–4 个方向，各有支持、反证、怎么验证 |
| 3 本省规则 | `rules_check.json` | 所有 `volatile` 规则本次已复核（≤ 30 天内）；缺的数据项写明处理办法；历年数据文件齐全 |
| 4 筛选与候选池 | `screening.json`、`pool.csv`、可选 `excluded*.csv` | **账对得上**：起点 = 源表实际行数，每步 `after` = 下步 `before`，终点 = 候选池行数；人工剔除逐条有原因；池 ≥ 志愿位 2 倍，否则写原因；每行有资格证据和来源等级；formal 模式要求逐项 verified |
| 5 打分 | `attributes.csv`、`preferences_config.json`、`preferences_review.json`、`reviewed.csv` | 场景经本人确认；每条打分有 `basis`；已打分的 = 候选池 |
| 6 计算 | `result.json`、`run.json`、`sensitivity/*.json` | 参数与登记一致；记录实际命令；至少两组敏感性结果（`rho`、`u_fall`、`drift`、`sigma_scale` 或重新打分的候选表不同；重新打分的候选表放在 `sensitivity/` 下） |
| 7 报告 | `report.json`、`report.html` 或 `.pdf`、`entry_sheet.csv` | 编号与生成日期；各节必备内容（见 [report-guide.md](report-guide.md#付费报告的必备内容与篇幅由-check_reportpy-的-check_sections-检查)）；数字与 `result.json`、HTML 一致；概率评级不比本省体检评级更乐观、保底余量够、正文概率写法合规（见 [report-guide.md](report-guide.md#按本省评级写概率)）；填报单无空代码 |
| 8 复核 | `review.json` | 新会话（主模型级别）复核；`AGENTS.md` 第七节的坑逐条 pass/fail 并写说明；随机抽查 ≥ 5 条来源，报告数字与原文一致 |

阶段 4 的筛选链用 `pool.py` 的参数（位次段、方向匹配、排除词）逐步缩小，每一步记一行。门槛脚本自己数源表行数，所以起点不能随手写。

调用已有工具，不重写：`pool.py`、`rank.py`、`preferences.py`、`optimize.py`、`decision_evidence.py`（资格证据）、`check_report.py`、`report.py`。


### 登记与画像字段

关键字段仍是年份、省份、位次、选科、批次、体检、学费上限、调剂态度、优先级。问卷已直接记录高考年份；先分普通类与艺术、体育、分类考试等路径，分别记录出分/估分、单科与加分口径，不从特殊路径意向推定批次。户籍及专项条件只记录本人事实，敏感项拒答保留未知。费用分年度学费与全程预算；复读、最低可接受结果、学制和入学后机会分别保留。家长代填要注明孩子是否核对；最终偏好不能默认等同家长期望。

高考画像先按题号读取年份、选科与分数口径，再核批次和规则；不从题目收起推断已出分。 JSON 和旧文字兼容、存档与版本对比见 [画像输入与存档](../../zhiqu-shared/references/report-workflow.md#画像输入与存档)；新作答采用最新版本，登记其文件与题目指纹。

## 三、个案取数清单（现取现核）

一单开工后按需取数，核过的写回省份层供下一单复用：

1. 本省当年规则与一分一段：看 `rules.json` 的核实日期，会变的项重核；没出分或没公布就用上年并写明。
2. 没有官方投档表的省份（河南）：候选学校逐所到本校招生网取其公布的本省分组录取分数或位次，做法见 [backtests.md「数据薄的省份怎么做」](backtests.md#数据薄的省份怎么做山西河南2026-10-17-检验)。
3. 候选院校的当年计划、组内或专业级别的选科要求、章程限制（体检、单科、语种、性别）、调剂规则。选科要求用 `scripts/subject_check.py` 对着官方汇总表逐个核对，结果写进资格证据（表只适用于它标明的届次，届次不符时不用）；学校官网对脚本设验证时，招生章程先查阳光高考（教育部平台，gaokao.chsi.com.cn 的“招生章程”），不绕过验证。
4. 最终志愿表上的每个条目：逐项对官方原表（院校代码、专业代码、计划数、选科要求）。
5. 院校调研：对最可能去的几所，查培养方案、转专业政策、收费、校区、就业质量报告，**每条附官方来源**，查不到的写“未查到”，不写“不存在”。
6. 去向：考研、考公、就业各自的门槛与代价，沿用 [job-market.md](../../zhiqu-shared/references/job-market.md) 与 [outlook.md](../../zhiqu-shared/references/outlook.md)，不重复写。

## 四、不用子代理，复核另开会话

分析与报告全程由主 Agent 在本会话完成。阶段 8 复核由**没参与分析**的新会话做，用 `review.json` 记录：复核者、日期、坑的逐条结果、抽查来源。样板报告和最初几单一定复核，之后按实际耗时再定。最终判断由操控者（交付报告前亲自核查关键信息的人）把关。

`review.json` 格式：

```json
{"independent": true, "reviewer": "会话或模型", "date": "YYYY-MM-DD",
 "pitfalls": [{"item": "没查到写成不存在", "result": "pass", "note": "…"}],
 "sampled_sources": [{"claim": "报告中的说法与数字", "source": "https://…", "matches": true}]}
```

`pitfalls` 的 `item` 依次为：没查到写成不存在、群体数字当个人概率、经验帖数字做决定、按编号引用问卷、同一事实写两处、会过期的事实、八字越界、委派判断类任务、取页摘要当原文。

## 五、操控者核查与复核评分

现有九阶段、参数、计算与报告内容保持；共用规则只在[报告工作流总纲](../../zhiqu-shared/references/report-workflow.md)维护，各图清单见[内容合同](report-contract.json)。

- 报告阶段自动生成 `<案例目录>/operator_check.md`，只读适配 report.json 的 sources 来源条目，不修改 report.json / result.json。挑出非官方或等级未标、未取原文、临期/过期、影响主结论的条目，列“核什么、去哪里核、核完填什么”；缺个人信息请本人补充。它是给操控者的独立清单，不附进客户报告。
- 复核阶段在既有 review.json 新增 rubric 和 snapshot，保留原 independent、reviewer、date、pitfalls、sampled_sources。十项评分及门槛以总纲为准；制作会话的 self_assessment 不等于新会话复核，不假填操控者已核。
- 高考现有数值和评级规则优先；新增核查项不可借机调整概率、位次、志愿顺序或结论。任何依赖变更都使对应核查与复核失效，需对当前报告快照重核。
