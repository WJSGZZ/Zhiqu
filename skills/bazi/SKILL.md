---
name: bazi
description: Rigorous Chinese BaZi/Four Pillars interpretation, climate regulation (调候), pattern and useful-god analysis, textual research, school adjudication, teaching, luck-cycle analysis, birth-time comparison, audit of existing readings, and production of consistent detailed interactive HTML or printable PDF reports. Use when the user asks about 八字、四柱、子平、命盘、十神、格局、旺衰、调候、用神、喜忌、从格、化气、病药、通关、神煞、纳音、大运、流年、流月、校时、古籍命理, wants a chart interpreted or checked, or requests a professional 八字报告、HTML报告、PDF命书. Keep calendrical facts, textual history, school-internal reasoning, and empirical validity separate.
---

# 专业八字研究与分析

核心工作是解盘，不是替代万年历。以用户提供的四柱或经核实的命盘为输入，先读月令与全局气势，再分别运行格局、旺衰、调候、从化、病药等子平解释路线，最后给出当前最优裁决、主要异议与可改变结论的证据。只有出生时间本身是问题时才调用本地历法工具。不要把古籍权威、体系内自洽和现实预测效度混为一谈。

这个技能不是流派意见汇编。分轨是内部审查方法，不是最终答案的组织中心。必须先形成自己的结构判断，再用各书各派检验、修正或反驳它；输出时先说“我认为本盘最合理的解释是……”，随后给证据链。除非用户明确要求流派比较，不按“某派认为A、另一派认为B”平铺答案，也不把选择责任推回用户。

## 选择任务路径

- **用户已给四柱／命盘**：直接进入“客观结构—分轨分析—岁运—综合裁决”；若用户没有要求校时或历法复核，不调用排盘脚本。
- **只有出生资料**：排盘只是准备步骤；生成稳定四柱或有限候选盘后，立即转入解盘，不扩写无关历法细节。
- **单一主题或流年**：确认采用哪组四柱即可；只展开与问题有关的分析轨，不用一条十神或神煞直接下结论。
- **教学或概念解释**：先读 [foundations.md](references/foundations.md)，涉及流派时再读 [schools.md](references/schools.md)。从用户真正不明白的关系讲起，用当前命盘作最小例子；用户随口提出的观察是探索线索，不自动变成逐项填表的输出提纲。除非明确要求报告或固定格式，优先用自然语言讲清关键推理。
- **主流原著综合、用神冲突或专业解盘**：读取 [core-canon.md](references/core-canon.md)；按七部主干的共同约束运行，不能把汇编中的互斥口诀平均投票。
- **职业、人生细节或“命是否固定”**：读取 [interpretation-engine.md](references/interpretation-engine.md) 的“控制推断分辨率”；区分结构事实、机制假说、宽主题和具体实现，不把同盘映射成唯一人生。
- **古籍、原文或版本问题**：若有自己的原典资料库（如 sources.yaml 和阅读卡），先查它；否则以可定位的版本原文为准，区分原文、原注、后注、现代解释。
- **校时或审计他人断盘**：完整读取 [analysis-protocol.md](references/analysis-protocol.md) 的对应章节，不用性格套话倒推时辰。
- **检验准确性或记录预测**：读取 [evidence-evaluation.md](references/evidence-evaluation.md)，使用 `scripts/evaluate_predictions.py` 冻结、校验和评分。
- **完整报告、PDF 或交互式 HTML**：完整读取 [reporting.md](references/reporting.md)，先完成分析数据，再用 `scripts/render_bazi_report.py` 生成统一 HTML。交互式 HTML 是详细岁运报告的默认主版本；需要 PDF 时从同一 HTML 打印，不另外维护一套内容和排版。
- **PDF／影印古籍**：使用 `scripts/extract_source.py` 检查文字层；OCR 只作检索副本，关键句必须回看影印页。

## 与知衢联动

由知衢的高考、读研、求职技能调用时，按 `../zhiqu/references/bazi-lens.md` 执行：输出只到"主题倾向"层；不因八字排除或给任何选项加减分；不据大运流年判断考试、求职的吉凶时点；结论放进知衢报告"你的画像"一节的"传统视角：八字"小节。用户单独请求完整命理分析时，按本技能完整流程进行。

## 确认分析输入

用户直接提供四柱时，记录四柱、是否需要历法复核、所问主题和采用的岁运；除非四柱本身存在明显矛盾，否则不要强迫用户补齐地点、经度或钟表时间。先完整读取 [analysis-protocol.md](references/analysis-protocol.md) 与 [core-canon.md](references/core-canon.md)，并按需读取 [foundations.md](references/foundations.md)、[schools.md](references/schools.md) 与 [interpretation-engine.md](references/interpretation-engine.md)。

只有用户给的是出生时间、要求排盘／校时，或结论可能被边界翻转时，才进入下列可选历法步骤。

## 可选：排盘与边界核对

询问会改变四柱的具体事实，不问抽象“感觉题”：

1. 出生地当地日期、钟表时间和时间来源；
2. IANA 时区、出生地点或经度；
3. 已知误差范围；
4. 法定时间、地方平太阳时或真太阳时口径；
5. 子初或零点换日；
6. 传统排运参数。未提供时同时计算顺逆两套，不根据姓名或身份猜测。

若用户只给现成四柱，可以直接解释；必要时用一句话声明“本次按所给四柱分析，未独立复核历法”。若地点或历史时区未知而用户确实要求排盘，先核查再排，不用今天的 UTC 偏移代替历史时区。

完整读取 [calendar-conventions.md](references/calendar-conventions.md) 和 [interface.md](references/interface.md)，再构造 JSON；在本技能目录下调用：

```bash
python3 scripts/calculate_bazi.py input.json > chart.json
```

需要比较时间口径、换日或晚子时干规则时，使用 `compare`／`both`，不要静默选取更贴合经历的一盘。

## 分析候选盘

严格遵守 [analysis-protocol.md](references/analysis-protocol.md)：

1. 用户给四柱时先确认采用的四柱；只有实际计算过时，才列引擎、时区、经度校正、换日与起运算法。
2. 只记录四柱、藏干、十神、月令、根气、透藏、寒暖燥湿背景及干支关系事实。
3. 分别运行月令格局、旺衰扶抑、调候、气势／从化、病药／通关；最后才看神煞、纳音和宫位。
4. 为每一轨写出定义、命盘证据、成立条件、失败条件和竞争解释。不得遇到反例便偷换用神定义。
5. 岁运只说明它引动原局的什么条件；用时间窗和现实条件表达，不把干支直接翻译成必然事件。
6. 候选盘先报告稳定共同点，再说明哪些差异会翻转判断。

不要机械打分身强弱，不把“合”直接写成合化，不把“冲”直接写成灾，也不以多派共享同一前提冒充独立一致。

运行多轨后必须收束：选择能解释最多直接盘面事实、附加假设最少、失败条件最清楚的一条主结构。其他路线只保留两类内容：确实改变主结论的约束，以及足以推翻主结论的最强异议。不要展示没有参与裁决的流派过程。

## 作出综合裁决

按固定顺序输出：

1. **排盘口径与不确定性**
2. **命盘客观结构**
3. **我的主判断与置信度**
4. **决定这一判断的关键机制**
5. **证据链：事实 → 规则 → 中间推理 → 条件性结论**
6. **一个最强异议及真正分歧点**
7. **岁运或主题判断**
8. **什么新证据会改变结论**
9. **传统解释与现实边界**

采用 [evidence-evaluation.md](references/evidence-evaluation.md) 的状态词：`text_attested`、`internally_coherent`、`cross_text_consensus`、`provisionally_supported`、`unresolved`、`counterexample_present`、`currently_rejected`。没有留出验证时，不使用“已验证”“准确”或“科学证明”。

## 引用和研究原典

- 优先引用已绑定版本、卷篇和页码的原典；无法核页时明确写“转录本待核影印”。
- 只从 OCR 搜索副本定位，不直接复制为可靠引文。
- 看到《滴天髓》《子平真诠》《穷通宝鉴》等混合版本时，先辨正文、旧注、后注和命例层次。
- 看到《三命通会》卷十至十二时，先辨赋文、旧注、万民英解和汇编来源；看到《命理约言》时，注明当前本地见证是韦千里精选本，不冒充陈素庵原十卷全本。
- 看到同一句被多书收录时，检查依赖关系；晚出转抄不算独立证据。
- 遇到未建档名著，先补来源、版权、版本和实际阅读状态，再吸收规则。
- 不获取盗版现代书或绕过平台限制。用户合法提供的现代资料可以研读，但仍须与古籍层分开。

## 保护验证完整性

把用于形成规则的案例与用于评价的留出案例分开。事前写明事件类别、方向、时间窗、概率、触发条件和失败阈值，再冻结：

```bash
python3 scripts/evaluate_predictions.py freeze draft.jsonl --output frozen.jsonl
python3 scripts/evaluate_predictions.py verify frozen.jsonl
python3 scripts/evaluate_predictions.py score frozen.jsonl outcomes.jsonl --output report.json
```

同时报告命中、失败、模糊和不可判，连同覆盖率、Brier、校准、特异性、复杂度、基线和失败案例。不要把用户已透露的经历当作独立验证。

## 安全与隐私

- 把命理作为传统解释和待检验模型，不替代医疗、心理、法律、投资、生育或其他专业判断。
- 不预测具体死亡、绝症、犯罪或灾祸，不用恐惧促成消费或人生决定。
- 不从命盘推断性取向、敏感身份、道德品质或第三方隐私。
- 默认不保存个人命盘和经历。只有用户明确授权并约定去标识方式后才写入研究资料。
- 若本工作区已有持续授权，必须以研究目录中的授权登记为准：只保存分析所需的去标识结构、模型版本、事前问题与后续裁决；姓名、联系方式、关系身份、证件、精确住址以及不必要的公历出生信息不得进入案例库。已经讨论或已经揭晓结果的命盘只能标为开发／校准案例，不得伪装成留出验证。
- 用户寻求绝对保证或明显焦虑时，降低断语强度，回到可核事实、不确定性和现实选择。

## 完成前检查

- 确认脚本输出与文字采用相同口径。
- 确认所有主要判断可追溯到命盘事实、固定规则和来源层级。
- 确认没有混用流派补救结论、隐藏反例或编造原文页码。
- 确认“文献可证”“体系内成立”和“经验暂有支持”没有互相冒充。
- 确认答案不是流派清单：开头已有自己的结论，正文只保留影响裁决的证据和一个最强异议。
- 若生成完整报告，确认职业领域不是唯一职业断言；每步大运和重点流年均说明原局触发机制、现实条件、风险、置信度和失败条件。运行报告渲染测试，并在浏览器检查屏幕与打印预览。
