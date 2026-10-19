# 读研个案流程：从画像到核查与复核

共用的证据字段、数字引用、时效、操控者单和评分只在[报告工作流总纲](../../zhiqu-shared/references/report-workflow.md)维护；本文件定义读研差异，各节数量在[内容合同](report-contract.json)，写法见[报告指南](report-guide.md)。

真实案例仅本机留存；公开样例放 examples，编号为 `YYYY-YJ-四位序号`，样例用 `YYYY-YJ-S01`、S02 等。新案例目录与编号一致；既有 `examples/demo_2027/` 保留，用 case.json 的 `legacy_directory: true` 记录迁移例外，不改它的原有计算和人物。介绍页说明人物为模拟，正文按真实交付标准写。

## 阶段表

| 阶段 | 文件 | 门槛 |
|---|---|---|
| 0 登记 | `case.json` | case_id、kind=grad、mode=formal/simulation、prepared_on、version、decision_stage、target_year、education、deadlines、data_commit 均有；日期和编号正确；mode 与人物说明一致 |
| 1 画像 | `profile.json`（旧版 `profile.txt`）、`profile_parse.json` | JSON 的 zhiqu=grad，旧文字保留原开头；11个关键字段逐个 given/inferred/unknown，按事实/偏好/约束/本人判断分类，unknown 与未确认推断列入 missing |
| 2 问题与方向 | `directions.json` | questions与directions数量按合同，各有 id/name/support/counter/verify，关联画像或已登记证据，不把“家里要求”直接当本人愿望 |
| 3 规则复核 | `rules_check.json` | items 逐条含 id、claim、evidence_refs、volatile、verified_on、review_due、status、scope；会变规则合同规定的有效窗口内核；规则未取到说明影响及替代调查，不能认证为满足 |
| 4 候选 | `candidates.json` | paths 与 school_programs 分开；走考研时 school_programs 中合同要求的调查候选，有同科目完整模考证据才要求个人条件分档；没有时只列调查对象并记录取得模考后的定档检查点；每个候选硬条件 met/unknown/failed 关联证据，剔除有原因；待核不能叫已合格 |
| 5 证据 | `evidence.json` | 按总纲全字段；与 rules、候选、画像、判断引用逐项对上；考试科目/普通专项/复试拟录取/学习方式/年份不混；个人名单只在内存处理，保留匿名统计 |
| 6 计算 | `calculations.json` | 基准预算、至少2个改关键假设的情景，输入/算法/输出及单位可复算；分数情景、机会成本有输入才算，无数据明确空缺，不给个人上岸率 |
| 7 判断 | `judgment.json` | 资格先行；偏好维度和权重有问卷「优先级排序」依据；每候选支持/反对/代价/失败去向/改判条件/检查点齐；主路径与保险路径可对应候选及证据 |
| 8 报告 | `narrative.json`、自动生成的 `<案例目录>/report.md`、HTML、PDF、`report_trace.json` | 12节角色完整、必备组件和数字引用过合同；引用解析后渲染，版面、长网址与图表门禁过才发布新生成件；禁止手改报告绕过阶段文件 |
| 9 操控者核查 | `<案例目录>/operator_check.md` | 按总纲自动挑条目，缺画像信息请本人补；操控者实际核查填写人/日期/结果/依据；未确认主要门槛不变成met，不进入客户报告 |
| 10 复核 | `review.json` | 新会话复核九项坑、按合同随机抽查原文；评分按合同达标；与报告快照一致，操控者核查完成；制作会话自评另存，不冒充独立通过 |

规则、候选与证据的处理顺序见总纲“门槛与版本”；阶段3可先登记证据，阶段5做全量一致性检查。simulation 同样查原文、计算和内容，不允许为样例捏造未来分数线或奖学金。

## 登记与画像字段

读研画像先读取年级、排名口径和路径；未给的推免资格与模考保留未知。 JSON 和旧文字兼容、存档与版本对比见 [画像输入与存档](../../zhiqu-shared/references/report-workflow.md#画像输入与存档)；新作答采用最新版本，登记其文件与题目指纹。

排名含分母、学业/综测口径、首考/重修与覆盖学期；学历取得方式、毕业年月、在职经历、数学科目及可比模考分别登记。最坏退路、年度可落实预算和收入期限分开；拒答不作为不具资格。年级决定是否追问推免、初试、调剂或博士；问卷细分阶段需人工映射到登记的决策阶段，不能只按字面套用。


- `decision_stage`：还在考虑 / 备考中 / 初试已出分 / 已有录取；`target_year` 是计划入学年份，不混成考前报名年份。
- `education`：year_level、major、school_level、expected_graduation；未知填 null，并在 missing 指向对应字段。
- `deadlines`：数组项 id、label、date（官方未发布可null）、kind（official / personal_checkpoint）、evidence_refs、unknown_reason。官方日期必须有规则证据，个人检查点必须明示本人规划；未发布日期不能套上一年。
- `case_id`：`^\d{4}-YJ-(\d{4}|S\d{2})$`；formal 不使用S编号。version 标本次报告版本，data_commit 固定到使用的数据快照。prepared_on 不替代出稿 as_of。

profile_parse.fields 每项 `{field, category, status, value, quote, locator, confirmed}`；quote 是画像原话，locator 按节名定位。四类 category 用 fact / preference / constraint / self_judgment。inferred 未确认时须明确confirmed=false、保留推断依据并列missing；可继续调查，但不能作既定事实。unknown 的value为null；missing记录字段、问题、影响和请谁补。

关键字段：**年级、专业、院校层次、均分或排名、英语、数学基础、读研动机、目标方向、预算、能否二战、目标地区**。没有排名不强制编一个，只要均分/排名的已知与未知分别注明；保研案例必须额外核排名分母、口径、推免资格和名额规则。优先级排序按本人原话记录，没有权重不自己赋数。

## 问题、候选和条件分档

questions 每项 `{id, question, profile_refs}`；directions 每项有 support / counter / verify，支持和反证条目含 claim 与 profile_refs/evidence_refs，验证项有动作、入口和检查点。

candidates 顶层 `{schema_version, paths, school_programs, excluded}`。路径比较包括本人实际考虑的考研、推免、境外/合作、先工作等，不必为凑行编本人完全不接受的选项；合同要求的有意义选项，拒绝的可以保留为已排除比较项并解释。学校专业项包含：

- id、path_id、学校、学院、专业代码、学位类型、学习方式、计划类别、适用年份、考试科目、培养地点；不把同校不同学院合成一个候选。
- hard_conditions 每条 id/name/status/evidence_refs；candidate.status 沿用 verified / pending / ineligible。unknown 导致pending，failed 导致ineligible并登记excluded；已剔除项仍可在对照表说明原因，不作正式推荐。
- 有本人同科目完整模考证据时，tier 仅限相对稳妥/够一够/冒险，附依据、条件和未知项；它比较能力差距、规则与本人投入，不是个人上岸概率。没有模考时不填 tier；官方复试线或拟录取分布只能说明学校或项目之间的差异，不能写成本人的把握。
- `personal_difficulty.mock_exam` 没有资料时为 null；有资料时登记 complete、same_subjects、subjects、exam_date、evidence_refs、score_ref，成绩从已核证据或本人登记字段读取，条目须明确是本人模考，证据分值单位为“分”，不能拿学费或本科均分充当。操控者仍须核试卷、科目、单科和完成条件。`personal_difficulty.checkpoint` 写日期引用与动作：拿到同科目完整模考后在哪个个人检查点定档，届时仍无证据就继续不定档。
- 判断所需的 supports、counters、costs、fallback、switch_conditions 和 checkpoint 在 judgment 中按 candidate_id 保存，引用候选/证据，不再抄一套成绩数字。


## 计算与判断的读研重点

预算把学费事实、住宿收费或假设、生活假设、未确认奖助分开；合同要求的敏感性情景可分别改变生活费与支持金额/学费参照，但须说明改变依据，不能仅改情景名字。没取到当届收费时可用最近官方旧年参照，年份和条件写清，不能称当届已定价。未来就业工资未知，机会成本保留未知。

分数情景图由已核群体分布和明确的情景输入生成；本人实际模考与条件点分别标识。没有可比数据时用一行缺口说明代替图，写缺什么、去哪里取、预计何时补，不保留空图或假点；推免阶段也不能把排名直接当考研分数。均分、排名、竞赛加分都回本校规则与口径，不把培养方案当招生承诺。

judgment含 preferences（问卷原话/排序/确认状态）、matrix（选项、维度、逐格依据）、candidates（逐候选判断）、recommendation（primary/backup与理由依据）、actions（行动与日期）、checkpoint、timeline、routes、risks、assumptions。未确认数值权重则用ordinal或unconfirmed，不算加权总分。矩阵未知比例触发合同阈值时的说明、数字引用与图表细则统一按总纲和合同，不在本文件另设阈值。

初试已出分的候选要同时核总分、单科与当年复试规则；已有录取时核真实录取/收费条件与退出成本。未出分时以差距和节点判断，不写当前已经上岸。主路径受资格、费用、本人接受度约束；任一改变，按可观察触发条件重评。
