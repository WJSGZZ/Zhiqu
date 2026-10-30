# 报告工作流：从本人信息到可交付报告

<!-- 核实：2026-10-25；复核期限：2027-01-25 -->

操控者是交付报告前亲自核查关键信息的人。

约定三版共用的证据、数字、操控者核查与复核方法；业务阶段和各节内容只在下表的对应文件定义。

| 版本 | 阶段表 | 内容合同与写作指南 |
|---|---|---|
| 高考 | [现有九阶段](../../zhiqu/references/case-workflow.md) | [合同](../../zhiqu/references/report-contract.json)、[指南](../../zhiqu/references/report-guide.md)；原计算及阶段不改 |
| 读研 | [阶段表](../../zhiqu-grad/references/case-workflow.md) | [合同](../../zhiqu-grad/references/report-contract.json)、[指南](../../zhiqu-grad/references/report-guide.md) |
| 求职 | [阶段表](../../zhiqu-career/references/case-workflow.md) | [合同](../../zhiqu-career/references/report-contract.json)、[指南](../../zhiqu-career/references/report-guide.md) |


## 画像输入与存档

JSON 格式、旧文字兼容和本机版本库统一见 [画像输入与本机存档](profile-input.md)。

## 一、顺序、产物与通过条件

| 通用阶段 | 目的 | 读研、求职产物 | 通过条件 |
|---|---|---|---|
| 0 登记 | 确定这次替谁、在哪个阶段回答什么 | `case.json` | 编号、版本、准备日期、目标年份、当前业务阶段、截止及数据版本齐；真实案例仅本机留存 |
| 1 画像 | 分清事实、偏好、约束、本人的判断 | `profile.txt`、`profile_parse.json` | 关键字段逐个 given / inferred / unknown；推断未确认不算事实；未知列 missing |
| 2 问题与方向 | 收敛到需要做的选择 | `directions.json` | 决策问题和方向数量按本版合同，各有支持、反证和验证办法 |
| 3 规则复核 | 确认当届规则能用于本案 | `rules_check.json` | 每条规则有来源、日期、期限与 verified / unretrieved；会变规则在本版合同规定的时限内重核 |
| 4 候选 | 区分可进入、待调查和已剔除 | `candidates.json` | 每个硬条件 met / unknown / failed 并关联证据；剔除逐项解释；候选数量按本版合同 |
| 5 证据 | 建立说法与原件的对应 | `evidence.json` | ID 唯一、适用人群年份清楚；所有阶段引用存在；取得原文才支持肯定事实，缺口说明影响 |
| 6 计算 | 用明确输入算预算、收入与条件情景 | `calculations.json` | 输入可追溯、算法可复算；基准之外有合同规定的敏感性情景；不覆盖原有结果 |
| 7 判断 | 把支持、反对、成本及切换条件摊开 | `judgment.json` | 维度/权重有本人依据，未知不造分；主路径、保险路径、每候选改判条件和检查点完整 |
| 8 报告 | 从前述文件组装一致内容 | `narrative.json` → `<案例目录>/report.md` → `report.html`、`<报告号>-report.pdf`；自动产生 `report_trace.json` | 内容合同、数字溯源、渲染、版面、长网址/SVG 门禁全过，才发布新生成件 |
| 9 操控者核查 | 让操控者检查影响交付的事实 | 自动生成 `<案例目录>/operator_check.md` | 按同一来源文件合并，逐个值列明报告节次和表格位置；客户画像合并确认，情景另核，影响主结论的排在前面；核查人/日期/结果/依据可回读；未解决的主结论条件不标为已满足 |
| 10 复核 | 用新会话复查判断和表达 | `review.json` | 各项坑均 pass、按合同抽查原文、评分满足共用标准；独立复核与操控者核查均完成才可交付 |

高考仍用 0—8 阶段，目的映射进现有产物，只加操控者核查单和复核评分。生成器把 report.json 的 sources 只读适配为核查条目，不另存 evidence、不反写；缺等级/日期的列为待分类，不按域名猜成官方。复核快照绑定 report/result 与 PDF 哈希。

### 门槛与版本

- 检查阶段 N 须核 0…N 的字段、引用、数字、适用范围和依赖。文件存在不等于通过；错误须报文件、字段路径、实际值及期望条件。
- `case.json.prepared_on` 是开工日；出稿/交付用明确的 `as_of` 日期判断时效，不能靠早先准备日掩盖今天已过期的证据。核实日期不得晚于 as_of，复核期限不得早于核实日期；会变规则须满足 本版合同的 `workflow_limits.rule_fresh_days` 且未过复核期限。
- 证据登记是累积的：阶段 3、4 可先向 evidence.json 登记已使用的条目；阶段 5 再检查整个证据集合和全部引用，避免“规则先用、证据还没有”的断链。本人登记数值可直接引用画像，不必重复登记证据。
- 缺口可以带到后续调查，但必须附影响、负责人/查询入口与下一检查点。unknown 不算 met，unretrieved 不算原文已核；不能通过编数、冒充已确认或删除候选绕过门槛。 supports/counters和recommendation.conditions用非空文字或文字列表，单句算一项。
- 阶段文件变更后，后续结果视为过期，按依赖重算/重生成。`report_trace.json` 保存输入文件与合同的 SHA-256、数字引用、报告文件哈希；核查与复核均绑定这份快照。改后不能沿用旧勾选或旧评分。
- 真实案例存本机 `cases/`，不提交；公开样例用 simulation 且人物完全模拟。`mode` 不影响证据/算术/内容门槛，只影响是否在介绍页标示样例、是否还需要现实本人确认。

### 交付时效

出报告前，读研先跑[按需取数](kaoyan-on-demand.md)，求职跑[候选取证](career-on-demand.md)。先查库，缺项限时现取，旧数据须在复核期内；读研每校默认30分钟。常问规则和分数线入库复用，取证与无关写作并行；只取主结论所需，超时记“未取到：时间限制”，不编数字。

报告（含示例）直接生成为 `<报告号>-report.pdf`，不另存副本。

### 高考先查库再补官网

新报告先导出本省、科类和历史年，再把缺项列入官网补取清单。例如：

```bash
python3 skills/zhiqu-shared/scripts/zhiqu_db.py export-gaokao 河南 物理 --years 2025 --batch 本科批 --key group --out .cache/gk-export
python3 skills/zhiqu/scripts/pool.py --year 2025=.cache/gk-export/河南-物理-2025.csv --key group --out .cache/pool.csv
```

示例按河南2025新高考的院校专业组单位；不拼2024旧理科。先确认导出有候选，再跑pool；有一分一段不等于有组投档线，空表停在缺口，不能改成专业单位凑候选。

可用 `--schools` 限候选、`--batch`／`--plan-type` 限范围。专业分不充组线；有组号但旧major列未明确是专业名还是选科说明的，先核原表列语义，两种单位都不导出；组模式跨年仍须 `--group-map`。原学校/组/专业、批次、科类和计划口径须相同才覆盖：官方优先，缺的用第三方；冲突记 `conflicts.csv`，多个第三方不同值不任选。不能从投档分擅推位次。`export-metadata.json` 留未导出原因和一分一段缺口；换算继续用 `zhiqu_db.py yfyd` 或带完整性元数据的 `rank.Table`，不跨缺行或合并档插值。

CSV 的 `data_provenance` 按 rank/score/plan 记原值、来源、状态、范围与缺口，pool按年保留，优化与填报单继续传递。显示等级只用“官方／官方一致／第三方整理·内部未核”；“官方一致”须是该值同口径官方原表核对，不用分数位次自洽或文件抽样给整行升级。来源仍保原始等级；第三方须附本节要求的 `cross_check` 范围与不一致数，无核对如实记0。

报告逐值显示等级、出处编号及状态；第三方旁写“第三方整理，未经官方核对”。仅有第三方位次支撑的冲稳保，按现有[指南D级](../../zhiqu/references/report-guide.md#按本省评级写概率)处理，不给概率；`report.json.third_party_review` 以志愿名为键，`disclosure` 写明未核且“不单独支撑主结论”，`margin` 写具体余量、备选及核对办法。两项印在志愿表和核对清单，缺任一项报错；主结论仍须另核规则、本人条件等独立依据，不能用披露代替证据。缺来源或核对不过不编数。R01—R12继续原CSV，回顾案例不用事后数据重算。

导出空年、历史代码、模拟稿调研缺口与高考阶段8逐句回查的操作见[数据库报告补充](gaokao-database-report.md)。

## 二、证据只有一份

### 等级与取文方式是两回事

| evidence.grade | 能支持什么 | 不能支持什么 |
|---|---|---|
| 官方 | 官方原文明确的当年、学院、岗位、对象及规则 | 从一个学院外推全校，从旧年承诺未来，从原则推定个人资格 |
| 多人一致 | 可核对的多人独立体验在其范围内一致 | 招生、收费、录用或合同的法定事实；同一转载不算多人 |
| 第三方整理 | 补齐官方取不到的分数线、分布，作参照；须写 `cross_check`（抽样核对范围与不一致数） | 单独支撑主结论；与官方冲突时以官方为准 |
| 单人说法 | 本人偏好、预算、经历；一位受访者的体验 | 群体比例、其他人的条件、对未来录取录用的保证 |
| 推测 | 有明确前提的解释、条件判断 | 把假设当已发生事实，计算个人上岸或录用概率 |

| retrieval_method | 显示名称 | 记录要求 |
|---|---|---|
| curl | curl | 官方原页/附件 URL、原件定位、日期；使用脚本取文也归此类并记脚本方式 |
| browser | 浏览器 | 正常打开原页面的正文/附件、URL、日期；不以搜索摘要代替 |
| provided | 本人提供 | 画像节名/原话定位，或本机附件与原始官方 URL；不把私人文件路径放进客户报告 |
| operator_check | 操控者核查 | 操控者实际核查的日期、原件入口、结论与依据；不能由 Agent 代填“操控者已核” |

官方页面和附件取原文核对；遇到登录、验证码或人机验证不绕过，记为未取到并写明原因。找过没找到写已查页面，不写“没有”。取文方式不会抬高证据等级：操控者看过经验帖，仍不是官方规则。

### evidence.json 的最小结构

顶层为 `{schema_version: 1, items: [...]}`。每条必有：

| 字段 | 约束 |
|---|---|
| `id`、`claim` | 本案例内稳定唯一 ID（如 E001），一条原子说法；同一原文可关联多候选，不复制成矛盾事实 |
| `value`、`unit` | 单个原始数值、字符串、日期或专业代码；不得用字典或列表，原单位；纯定性或未取到用 null 并说明，不能填 0。`personal_input` 必须另有 `registration_ref`（如 `profile_parse.json#/fields/8/value`）精确指向本人 given 值；值和类型一致，且不得带官方网址或官方机构名 |
| `source.organization`、`source.url`、`source.locator` | 官方事实须有可定位的 http/https 官方 URL 与页码/表行/段落；个人输入的 URL 可为空，但须有画像节名或本机原件定位 |
| `availability` | available / not_published / not_found / blocked / not_requested；未请求用not_requested且status=unretrieved；已查未取到说明入口和失败，不把未知说成不存在 |
| `published_on`、`publication_status` | 有日期填 YYYY-MM-DD；原页未署日期填 null + undated，不从 URL 猜日期；未发布与未取到分别在 availability 中说明 |
| `retrieved_on`、`retrieval_method`、`verified_on`、`review_due` | 日期 YYYY-MM-DD，取文方式用上表枚举；未取到也记本次尝试日期及下次核对期限 |
| `grade`、`status`、`scope` | 上表等级；status 为 verified / unretrieved；scope 明确年份、学校/学院/岗位、计划和学习方式等适用边界 |
| `candidate_ids`、`rule_ids` | 关联候选/规则 ID 数组，无对应对象时空数组并说明公共用途 |
| `excerpt`、`original_locator` | 已取原文留不超过两行的关键原句或个人原话、原件定位；报告实际引用的官方单值必须包含在 excerpt 中，claim 只写原子标签，不复制报告原句；原始个人名单不落盘，只存匿名统计及加工范围 |
| `main_conclusion`、`gap` | 是否影响主结论；未取到时 gap 写原因、影响、查询入口、下一检查点 |

这里 verified 表示所列依据已取得并核对，不表示“推测已证明为真”。肯定某个硬条件还要联合官方适用规则与本人条件证据；经验或推测不能单独认证资格。原件可在本机缓存，仓库只留必要摘录/匿名汇总和来源，不复制付费知识库内容。

## 三、报告数字的追溯与计算

**事实性数字须能追溯；登记输入可直接引用，报告自己的计数无需另立证据。** 节号、尾注号、页码、报告编号、序数、列表编号及“三件事”“两条路”“第1个志愿”等报告计数豁免。目标年份、年级、毕业年份、本人填写的预算或分数可直接引用case.json或profile_parse.json，不必另建证据。其余计划数、学费、分数线、工资、比例、官方日期及规则中的数字，必须追到evidence.json条目或calculations.json键。

### 统一引用写法

占位符、格式与追踪要求见[数字引用](report-numbers.md#统一引用写法)。

### calculations.json

算法、输入、情景及隐私规则见[计算记录](report-numbers.md#calculationsjson)。

### 结构化判断与计算的字段约定

各阶段JSON顶层有schema_version=1；对象ID在本案稳定且唯一。引用用evidence_refs（E类ID）、candidate_refs（候选ID）、judgment_refs（J类ID）、calc_refs（计算JSON Pointer）分开记录，避免把证据ID和显示尾注混用。

judgment.json的字段固定如下，表格和组件直接取这些记录；数量由本版合同决定：

| 字段 | 项的最小结构 |
|---|---|
| preferences | questionnaire_section、quote、profile_refs、method（numeric/ordinal/unconfirmed）、dimensions、weights、confirmed；无确认数值权重时weights=null，不算综合分 |
| matrix | options、dimensions、cells；每格有 candidate_id、dimension_id、status、text 及引用；每对行列恰有一格 |
| candidates | id（J类）、candidate_id、supports、counters、costs、fallback、switch_conditions、checkpoint；支持、反对和改判条件分别登记 |
| recommendation | primary、backup、judgment_refs、evidence_refs、calc_refs、conditions仅列共同前提，单路径条件放对应候选；资格不明只作调查优先级 |
| checkpoint | date、trigger；全局与每个候选的检查点保持一致 |
| presentation | 按节号保存有序 `{slot, ref}` 数组；slot 来自本版合同，ref 是阶段文件名加 JSON Pointer，例如 `judgment.json#/report_blocks/01_1` |
| report_blocks | 以稳定键保存 `{type, content, evidence_refs}`；数字卡、行动、时间线、路线卡、风险、假设等组件放在合同指定的阶段文件 `report_blocks`，不另造同名顶层数组 |
| main_evidence_dependencies | 主结论所依赖的候选、证据和计算引用；用于继续追踪间接输入 |

连贯分析放 `narrative.json.sections` 对应的 lead、analysis、core_points 等登记位置；画像表放 `profile_parse.json.report_blocks`，候选表放 `candidates.json.report_blocks`，数据图与来源放 `evidence.json.report_blocks`。每个节点统一使用 type/content/evidence_refs；具体允许的位置与组件类型以合同的 from/node_types 为准。
这里的text是结构化短理由或动作；长分析只在narrative登记位置写。main_conclusion所需的证据要从recommendation及其引用继续追踪，不能漏掉间接影响结果的计算输入。

rules_check.json顶层用 `{schema_version, as_of, items}`，每项来源通过evidence_refs唯一定位，volatile布尔、status和日期必须齐。rules_check的as_of与本次出稿基准一致。候选中的每个硬条件要能联合定位适用规则和本人事实，而不是只挂一份学校首页。

## 四、内容合同与自动组装

各版 references/report-contract.json 唯一登记各节必备内容及数量；report-guide 只述写法，不复制数量。共用 CSS/组件只在 report.py；读研/求职组装后调用 render_report.py，不另建样式。

合同的 `sections` 按 01…12 排列，`role` 固定；`default_title` 沿用本版指南，读研/求职可围绕同一角色个人化标题，不能换名后省略内容，旧示例题名保持。高考保持现有节名。页数不作为内容达标证明。

每个 slot 规定 `component`、`min`、`max`（null 表示随候选数量）、`from`（文件和 JSON Pointer）、`source_required`、`condition` 与 `rules`。from 指定可引用的子树；min/max 按 count_by 指定的 items（条目）或 components（组件）计数，不按文字行数；矩阵的行列数另查 matrix_policy。条件为假时保留该节的暂无/不适用说明；不可把未知值画成零值。

合同条件按合同的阈值与阶段数据计算，不能手填开关绕过；case.context记出稿as_of；真实交付必须对应实际生成/交付日期，simulation历史快照须明示，不能借回填日期使用已过期规则。读研takes_kaoyan须与实际主/备路径一致，不能填false回避候选数量要求。

- narrative.json 顶层 `schema_version` 和 `sections`；每节只允许合同登记 `narrative_key` 的文字位置。禁止整章 Markdown、任意表格/:::组件或在叙述中重复填数字表；表格、图、路线卡与来源从阶段数据组装。
- 结构化阶段文件可有短标签、反证、理由与动作，供表格/卡片直接取用；连贯分析段落和摘要的表述只放在 narrative 对应位置。来源数据变更后从引用重出，不能人工改 report.md 修补数字。
- 摘要须有结论、数字卡、带小标题的核心结论、带日期的行动和检查点；各项上下限见本版内容合同。主路径与保险路径须能对应 judgment，不能用漂亮表述覆盖未满足条件。
- 比较矩阵的行列下限见本版合同；单元格分 supported / conditional / failed / unknown，对应 ✓ / △ / ✗ / △待查。unknown 格数占比超过合同阈值时，必须列出缺信息、去哪里补、拿到后怎样改判；“有条件”不能成为掩藏未知的标签。
- 每候选支持、反对、代价、失败去向均不空；每行动路线有固定四栏；风险情景数量按合同。无证据的项目明确说明未知，不能用套话填满。
- 每张图都有标题、一句读图说明、有效来源编号；全文来源编号由 evidence ID 确定性映射到第 12 节尾注。第 12 节以外不显示超过 40 字符的网址，也不显示私人缓存路径。

### 组件和叙述的字段

`judgment.json.presentation` 按节号列出 `{slot, ref}`；ref是 `文件名#/JSON/Pointer`，必须落在合同登记的文件和子树内，不能任意换文件。每个节点采用 `{type, content, evidence_refs, calc_refs, registration_refs}`，只允许该槽的组件类型。

- `narrative.json.sections` 按节号存受控的 `lead`、`analysis`、`core_points`、`unknown_explanation`、`disclaimer`。lead和disclaimer的content为`{text}`；analysis节点可为paragraph、heading、list或callout，内容分别为text、items或title+items；核心结论用items数组，每项title+text；未知说明的content有missing_information、retrieval_plan、decision_changes。禁止正文嵌入整章标题、表格和组件代码。
- 表格、图、路线卡、日期行动等是结构化节点，放在合同登记的对应阶段 `report_blocks` 内，不能放进叙述。表格content用columns+rows；图另含title、caption、unit及有效来源。行动节点content.items每项text+date；日期允许引用登记检查点或官方证据。时间线末列只接受空值、普通或检查点标记，不显示正文；后果写进说明。图名与读图说明随图节点保存，避免另一份文稿重复维护。
- presentation决定展示哪些节点，不会自动带入新加叙述；生成时提示未展示节点，须确认是否遗漏。阶段记录与展示不得资格或数值相反；组装器核类型、位置、数量和引用，语义由独立复核确认。
- 现有计算保留原键；`case.json.calculation_plan` 登记engine、inputs、dependencies与scenarios。旧案例使用已注册的legacy_demo算法，inputs逐个指向既有case字段的证据或本人输入，必须与实际计算值一致；dependencies记录计算键的证据依赖。通用算法仅支持已注册的sum/product/difference/ratio，operations写inputs引用和output键，不接受任意表达式。情景记录changed_inputs、why、output_ref及decision_effect，由已注册算法复算，不能以手填说明替代算术。

生成报告不等于批准交付，须过阶段10的`--delivery`。

## 五、操控者核查单

自动生成 operator_check.md，按 evidence ID 去重，**并集**选出：非官方等级；unretrieved；已过期或在本版合同的临期窗口内；影响主结论。影响主结论还要沿 judgment → calculations 输入 → evidence 反向追踪，不能只靠手填 main_conclusion；失效/缺日期的项也列出原因。

每项保留全部入选原因，写明“核什么、去哪里核、核完填什么”，至少含：

```text
- [ ] E001｜主结论 / 临近复核期限
  核什么：该收费是否适用于本人的年份、学院、学习方式。
  去哪里核：原公告链接与附件页码；缺原文则列已尝试入口。
  核完填：核查人___；日期___；结果（确认/不符/仍未知）___；原文依据与适用范围___；对建议的处理___。
```

生成器保存稳定 ID 与证据快照标记。重生成只保留相同 ID、相同原文/值/范围/期限快照的填写；变动项重新待核，不用原勾选。勾框本身不等于完成，须结果与依据齐全，且 trace 对应当前报告。操控者核了非官方体验后仍保留其原等级；核到官方规则时更新 evidence 再重生成，不在核查单里另立一份矛盾数值。

个人信息缺失按 profile_parse.missing 单独列“请本人补充”，不改问卷；推断未确认的也进入。核查由操控者亲自做，Agent 可以准备问题和入口，不能代勾或假称已经核查。simulation 也保留未核标记，不伪造现实操控者操作。

## 六、复核与评分

review.json 复用高考既有 `independent`、`reviewer`、`date`、`pitfalls`、`sampled_sources`，增加 `status`、`rubric` 与 `snapshot`。自评与独立复核分开保留：制作会话只填 `self_assessment`，不能把 independent 改成 true；新会话填写独立复核，快照绑定 report_trace/报告哈希。高考旧复核字段只补不覆盖。

### 十项评分表

评分结构 `rubric.items = [{id, score, reason, evidence_refs, report_location}]`；每项 0/1/2 的理由必须具体。总分由脚本相加，不靠手填总分过关。

| id | 项目 | 0 分 | 1 分 | 2 分 |
|---|---|---|---|---|
| clarity | 结论清楚 | 无主路径或前后冲突 | 有结论但条件难找 | 摘要说清主路径、保险路径及关键条件 |
| traceability | 证据可追溯 | 主要事实无原文或数字无引用 | 可追但少量定位/范围含糊 | 原件、条目、数字及适用范围逐一可查 |
| reasoning | 判断有反证和改判条件 | 只有支持理由 | 有反证，部分改判条件笼统 | 每候选反证、代价和可观察的改判条件齐 |
| consistency | 数字前后一致 | 冲突或复算失败 | 数字正确但单位/取整说明不清 | 数字复算且全篇口径一致 |
| timeliness | 时效 | 规则过期却按有效采用 | 已注明缺口但部分时间点待核 | 用到的有效规则均在期内，旧年仅作明示参照 |
| personalization | 个性化 | 可套给任何人 | 引用了画像但未影响取舍 | 有本人原话、矛盾与其对取舍的具体作用 |
| actionability | 可行动 | 无下一步或日期 | 有日期，部分动作/入口不清 | 行动事项及路线的日期、入口、检查点与切换明确 |
| boundaries | 不越界 | 编概率/保证结果/代决策 | 无硬越界，个别表述仍易误解 | 事实、假设、偏好与结果边界均清楚 |
| summary_access | 家长只读摘要也能看懂 | 术语或数字堆叠，无法知道做什么 | 大致懂，仍需翻正文找关键限制 | 摘要能理解理由、边界和行动事项，无须先学术语 |
| layout | 版式无问题 | 门禁失败或可见挤压/断图 | 门禁过但视觉仍有不影响阅读的瑕疵 | 机械门禁和逐页视觉检查均过 |

**评分通过：项目完整、各项无零分，总分下限按本版[内容合同](../../zhiqu-grad/references/report-contract.json)的 `workflow_limits.review_score_min`（[求职](../../zhiqu-career/references/report-contract.json)、[高考](../../zhiqu/references/report-contract.json)同字段）。** 任一硬门禁失败、九项坑有 fail、主结论引用未核的规则、操控者必核项未完成，都不能靠其他高分抵消。制作会话按事实自评，不给自己满分；独立复核不能靠复制自评分冒充审阅。

### review 的其余门槛

- 九项坑沿用 AGENTS 的名称：没查到写成不存在、群体数字当个人概率、经验帖数字做决定、按编号引用问卷、同一事实写两处、会过期的事实、八字越界、委派判断类任务、取页摘要当原文。逐条 pass / fail + 说明和报告位置。
- 从当前用于报告的官方原文证据 ID 集合中按合同抽查（数量不足不能声称完成该门槛），记录候选集合、种子、选中 ID、主张、URL、原文定位/关键句、取文方式、日期及 matches。必须真的打开/读取原文；本机已保存原件可凭哈希核对，过期规则需重新取文。
- 抽查之外发现的主要错误同样阻断；未取到的不能记 matches=true。随机抽查不能代替所有主结论来源核查。
- 复核员先与最近一份已批准的同版报告对照，再打分。改评分表后或每季度，同一份报告派两位复核员，记各项分差与是否同判；常有分差的项改写标准。
- `status` 区分 draft / self_assessed / awaiting_independent_review / approved / changes_required；自评可通过评分，但正式交付必须 independent=true 且 status=approved。机器只能查字段、算分和哈希，不能证明是新会话或本人真实操作，操控者确认身份与实际核查。

## 使用工具

在仓库根目录运行；四个技能及共用目录须同层安装：

```bash
python3 skills/zhiqu/scripts/case_check.py <案例目录> --stage 7
python3 skills/zhiqu/scripts/planning_report.py <案例目录> --profile-version <所用画像文件>
python3 skills/zhiqu/scripts/case_check.py <案例目录> --stage 9
# 操控者核查完成、新会话填写复核记录后才可检查真实交付
python3 skills/zhiqu/scripts/case_check.py <案例目录> --stage 10 --delivery
```

`case.json.report_input_usage` 逐条登记本次结论实际依赖的本人输入（`pointer` 指向 `profile_parse.json` 的本人值、`sections` 列使用节、`reason` 说明用途），不能把全问卷塞进附录。`case.json.report_profile` 保存明确选定版本的文件、填写时间、题目指纹与完整SHA256，生成时核对它与解析来源一致；旧文字原样封装为JSON，未知填写时间不补造。

`--profile-version` 必须明确选择分析所用的画像文件或 `profiles/` 中的某一版，不能只改标签来绑定另一份画像；有更新版本时附录会提示“报告基于旧画像”。PDF在12节后附可提取核对材料，并嵌入输入、证据、计算和追踪附件；生成成功后同步公开模拟登记或已有的本机总登记。仅凭PDF核对的方法见仓库 `AGENTS.md` 的「如何只凭一份报告核对」。

`planning_report.py` 检查前置阶段、内容合同及版面/来源；成功才替换产物，失败保留旧件。`--html-only` 仅供检查。阶段逐级累计；阶段9允许核查单待填，阶段10区分自评与独立批准。

核查单单独更新用 `operator_check.py <案例目录>`；高考用 `case_report.py` 生成并附单。旧报告可只读补单，不改原报告与结果；核查单变更后重新复核，旧批准不沿用。

### 用固定人物回归

[模拟人物库](sim-personas.md)集中维护问卷回答和覆盖边界；案例中的 `profile.txt` 由它提取，不能分别改写。人物只检验流程，不构成真实录取、录用或方法有效性的证据。

修改流程后运行 `python3 skills/zhiqu/scripts/check_personas.py`：完整案例检查至自评，前半程案例只检查画像、方向、规则和候选，并禁止出现报告产物；它同时检查 JSON 画像的稳定题号、题干、节名和缺项；问卷之外的口语材料另放补充文件。改作答后重新核对分析、计算与快照，不从人物库介绍反推答案。核查单只改措辞时，工具确认其余哈希未变后只更新核查单记录；其他变动照常重生成并复核。

图表没有可画的数据时，用同一内容槽的 `data_gap` 代替，内容只写 missing（缺什么）、source（去哪取，网址留来源节）、expected_by（预计补齐的日期引用），不生成空SVG。部分数据已取得时，可以画有依据的部分，但不得把缺值画成零或猜测点。

阶段9、10须独立会话逐句回查并绑定报告：不支持的删去或明示推测，部分支持的改写，无引用事实补证据。详见[逐句回查](claim-check.md)。写作模型、渲染器版本随报告记录；未知模型记“未记录”。
