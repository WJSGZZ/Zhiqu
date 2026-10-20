# 求职个案流程：从方向到核查与复核

共用的证据字段、数字引用、时效、操控者单和评分只在[报告工作流总纲](../../zhiqu-shared/references/report-workflow.md)维护；本文件定义求职差异，各节数量在[内容合同](report-contract.json)，写法见[报告指南](report-guide.md)。

真实案例仅本机留存；公开样例放 examples，编号为 `YYYY-QZ-四位序号`，样例用 `YYYY-QZ-S01`、S02等。新目录与编号一致；既有 `examples/demo_2027/` 以 `legacy_directory: true` 记录迁移例外，保留人物、原预算与 offer 情景。人物说明放介绍页，客户正文按真实标准。

## 阶段表

| 阶段 | 文件 | 门槛 |
|---|---|---|
| 0 登记 | `case.json` | case_id、kind=career、mode=formal/simulation、prepared_on、version、decision_stage、target_year、education、deadlines、data_commit完整；日期、编号、现实/情景阶段不混 |
| 1 画像 | `profile.json`（旧版 `profile.txt`）、`profile_parse.json` | JSON 的 zhiqu=career，旧文字保留原开头；关键字段 given/inferred/unknown，四类分开；缺项和未确认推断进missing，不反向编经历或收入底线 |
| 2 问题与方向 | `directions.json` | questions与directions数量按合同，每个支持/反证/怎么验证齐；用本人问题界定范围，不先按学历或行业名气排序 |
| 3 规则复核 | `rules_check.json` | 用到的招录/应届/劳动/社保/公积金/税等逐条有来源、核实日、期限、范围与verified/unretrieved；会变的规则合同规定的有效窗口内复核；全国规则不能替代本地缴费条件 |
| 4 候选 | `candidates.json` | 合同要求的不同岗位或职业方向；每个具体机会硬条件met/unknown/failed指证据，candidate.status为verified/pending/ineligible；不符者剔除有原因，不用品牌代替合同或资格 |
| 5 证据 | `evidence.json` | 按总纲字段齐且引用对上；逐岗区分公告/岗位表、学历专业、届别、户籍、政治面貌、合同主体及收入口径；按职位表筛“本人能报”时逐列逐条看全部资格（含性别、民族、证书或职称、年龄、备注），画像没写的记待核；名单只存匿名汇总 |
| 6 计算 | `calculations.json` | 基础收支、收入比较在有输入时算，合同要求的关键假设情景；含保证与非保证收入、缴费/税、实际月份/工时及住房支出；可复算，未知不填0 |
| 7 判断 | `judgment.json` | 维度/权重有本人问卷依据；矩阵有逐格依据；每候选支持/反对/代价/失败去向/改判条件/检查点齐，主路径和保险路径不承诺录用 |
| 8 报告 | `narrative.json`、自动生成的 `<案例目录>/report.md`、HTML、PDF、`report_trace.json` | 12节角色完整且按合同组装；数字引用、版面、长网址/SVG检查全过才发布新生成件；没有真实offer不能把情景变成实际选择 |
| 9 操控者核查 | `<案例目录>/operator_check.md` | 总纲四类必选条目、个人缺项与推断不漏；操控者核主体/条款/数字后填日期结果依据；未核不代勾，单子不进客户报告 |
| 10 复核 | `review.json` | 新会话九项坑逐条pass、按合同随机抽查原文、评分按合同达标、快照一致、操控者核查完成；自评不能冒充独立复核 |

阶段3可先登记证据，阶段5检查全量关系，见总纲。simulation同样核官方原文、真实计算和内容，不能为画像安排不存在的资格或工资。

## 登记与画像字段

求职画像先读取学历取得日期、本人意愿和家庭期待；户籍拒答不作资格否定。 JSON 和旧文字兼容、存档与版本对比见 [画像输入与存档](../../zhiqu-shared/references/report-workflow.md#画像输入与存档)；新作答采用最新版本，登记其文件与题目指纹。

毕业证与学位证的年月、专业全名/代码及辅修、学历取得方式、境外认证分别登记。三方、劳动关系、社保不混同；户籍与生源不混同；本人单位偏好与家里期待分开。收入底线、必要支出、最晚收入月、合同甲方和用工形式、可接受地点与服务期逐项保留；不从某一题直接判定应届资格。

case.json新增字段和旧stage并存，原budget、hypothetical_followup、出生输入和已有计算结果不删不改：

- `decision_stage`：还没开始 / 投递中 / 有 offer 在比较 / 在职想跳槽。应届毕业与有工作经历、劳务关系、是否参加某种招录分别核，不从阶段推定。
- `education`：degree、major、expected_graduation、qualification_date。未知可null并列missing；学历取得方式和学位另核，不能从“本科”二字补全。
- `deadlines`：每项id/label/date/kind（official / personal_checkpoint）/evidence_refs/unknown_reason，至少记录最晚需要收入的节点；日期未知保留问题，不能用旧招考日历冒充当届。
- `case_id`：`^\d{4}-QZ-(\d{4}|S\d{2})$`，formal不用S编号。version是本次报告版本；prepared_on为准备日，出稿另用as_of判断时效；data_commit固定数据版本。

profile_parse.fields每项 `{field, category, status, value, quote, locator, confirmed}`，category为fact/preference/constraint/self_judgment。quote用本人画像原话，locator用节名。inferred未确认须列missing，不作事实；unknown的value为null，missing写问题、影响和请谁补。只有问卷已有优先级时才谈排序；未给数值权重就不编分。

关键字段：**学历、专业、毕业时间、求职阶段、经历、证书、目标岗位、收入底线、城市、单位类型偏好、户籍、政治面貌、多快需要收入**。户籍与政治面貌按具体公职机会必要性核对，本人未提供就未知，不因省份或家庭情况推断。公开案例只到省，不记录真实姓名、联系方式或个人档案。

## 候选与具体机会

directions中questions格式 `{id, question, profile_refs}`，每方向id/name/support/counter/verify。支持与反证引用本人事实或证据；验证写动作、入口与检查点，不用“提升能力”代替可验证问题。

candidates顶层 `{schema_version, job_types, jobs, excluded}`：

- job_types数量按合同，各有direction_id关联directions.json中的分析方向；一个方向可对应多个岗位类型。多份同一岗位广告不算不同岗位类型；两类意向不足时增加有理由的调查方向或已排除对照，不编本人意愿。
- jobs按当前取得的信息登记，数量可为0；没有具体广告时明确“方向成立、具体可报岗位未核”。每项精确到雇主/发布机构、职位、届别、地点、主体、合同类型、发布日期/截止等，不能把单位类型当一份offer。
- hard_conditions逐项id/name/status/evidence_refs；明确不符的failed进入excluded并说明；unknown是待核，未取得岗位原文不能标verified。相关专业而目录不清、同页字段冲突都待确认，不自行采用更宽条款。
- 直接签约、劳务派遣、外包、事业编制、编外、实习分别核；国企不等于编制，实习不等于正式录用。收入数字只引用对应证据，平台薪资区间不当本人报价。
- 支持、反对、代价、失败去向、切换与检查点统一在judgment按候选ID保存，不能在另一文件重复一套条件。

判断必须分开**硬资格、能力差距、本人偏好与信息冲突**：硬不符不能靠技能补过，缺能力先查真实任务与带教，偏好冲突由本人取舍，信息冲突回招聘主体与原文确认。少数岗位样本不推行业比例、录用率或应届起薪。

## 计算、比较与切换

calculations给输入来源、算法、输出、单位和舍入方式。合同要求的关键情景可分别改变等待收入的时长、住房/必要支出、保证奖金、工时等；同参数重复运行不算新情景。没有offer时仍可核基础收支与等待成本；合同、当地缴费或可比工资不全就标缺口，不为了三张图捏造报价。

实际offer与条件情景用case上下文分开登记，不能靠报告一句小字混过：`context.offer_basis` 为 actual / scenario / none；actual需有本人提供的有效条件证据，scenario输入与假设齐全且正文显示“条件情景”。有offer或条件情景时，收入三图必须同口径：年到手现金、每小时到手、扣住房和必要支出后的月结余；公积金账户价值单列，不并成能花现金。none则说明暂不可比较，保留获取条件与下一节点，不假造两份offer。

judgment包含preferences、matrix、candidates、recommendation、actions、checkpoint、timeline、routes、risks、assumptions。维度与本人优先级相连；权重未确认用ordinal/unconfirmed，不算加权总分。单位身份、薪酬、城市与家庭期待分开，不能“综合得分”遮掉硬条件；未知矩阵占比的解释要求按总纲和合同。

在职转行同时比较在岗验证、边工作边找与离职再找的现金/时间约束，不默认先辞职；考公与秋招要标真实报名、考试和到岗冲突，官方窗口没发布不凭经验写具体日。主路径、保险路径和个人检查点以可观察反馈触发更新，不给录用概率，也不代投、代联系或签约。
