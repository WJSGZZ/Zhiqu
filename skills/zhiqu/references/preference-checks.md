# 偏好核对与固定锚点

先由当事人确认属性评分、优先级、底线学校和梦校；工具不会根据候选池最大最小值移动锚点。底线记 0、梦校记 100，超出锚点不截断。学校、专业、城市、前景采用排序倒数和权重；safety 由优化器的滑档效用与风险约束另行处理。

`preferences.py` 的输入保留历年位次等原字段，只新增 utility 与 utility_scenario。config 的 scenarios 可包含 student 和 parent，各场景必须 confirmed=true，属性分为已调查且已确认的 0–10 分，未知不能默认补分。anchors.low/high 必须各含 name 和 school/major/city/outlook 四个 scores。checks 给出两个候选 id 与本人选择；不一致或循环只发出提醒，不改写选择。建议核对题是额外对话，不改原问卷。

在技能目录运行完全虚构的演示：

```bash
python3 scripts/preferences.py examples/preference_demo/attributes.csv --config examples/preference_demo/config.json --scenario student --out /tmp/zhiqu-student.csv --review /tmp/zhiqu-student-review.json
python3 scripts/preferences.py examples/preference_demo/attributes.csv --config examples/preference_demo/config.json --scenario parent --out /tmp/zhiqu-parent.csv --review /tmp/zhiqu-parent-review.json
python3 scripts/optimize.py /tmp/zhiqu-student.csv --rank 20000 --slots 1 --u-fall -60 --sims 2000 --json /tmp/zhiqu-student-result.json
python3 scripts/optimize.py /tmp/zhiqu-parent.csv --rank 20000 --slots 1 --u-fall -60 --sims 2000 --json /tmp/zhiqu-parent-result.json
```

报告并列展示两套已确认场景的权重、推荐表、滑档风险，以及发生交换的具体候选和原因。各场景效用只表示该人的取舍，不能比较“谁更满意”，不自动折中。实际双方案记录及重现说明见 [虚构偏好演示](../examples/preference_demo/README.md)。

## 可回头与前景的评分约定

可回头先拆成资格、名额、成绩门槛、考试/面试、时间窗口、转入失败后的可接受程度。任何不可转入的硬限制先排除。对剩余方案，考生可确认一份有序等级：0=没有可接受的回退路径，2=仅有名义机会且关键条件未知，5=路径公开但竞争/门槛较高，8=条件可核实且已有可接受的保留路径，10=当前路径本身可接受且无需转入才能达成主要目标。这个分数是个人偏好量尺，不是成功率；不得仅凭名额推算概率，不和风险上限重复计算。未知保留未知。大类分流同样记录规则、名额、成绩排序与未进入首选的后果。

前景分按目标定义证据与同口径基准，再由考生确认：考公看目标地区官方职位表中可报岗位数量、专业限制、基层与应届限制；考研看目标学科培养、推免资格与同届升学去向，不把全校平均当该专业保证；就业看同专业同届的就业口径、去向城市、岗位与雇主，并区分升学和签约。目标不同时不可混加岗位数与升学率。采用同一目标内确认的差/中/好锚点映射到 0/5/10，记录年份、分母和来源；缺数据不伪造标准全国分。多目标须先确认目标权重，悲观情景中单独降低证据薄弱的分项。
