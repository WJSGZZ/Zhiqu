<p align="center"><img src="assets/logo.png" width="128" alt="知衢"></p>
<h1 align="center">知衢</h1>
<p align="center"><strong>把重要选择，想得更清楚。</strong></p>
<p align="center">高考志愿 · 读研规划 · 求职方向</p>
<p align="center"><a href="https://wjsgzz.github.io/Zhiqu/">填写问卷</a> · <a href="#先看看三个普通人的选择">看三个案例</a> · <a href="#安装与开始使用">安装使用</a> · <a href="ROADMAP.md">进展与待办</a></p>

选专业、读研、找工作时，最难的往往不是信息太少，而是不知道哪些信息与自己有关。

你可能喜欢一个方向，又担心工作；想换一个平台，却承担不起反复试错；希望听取家人的建议，也想保留自己的选择。知衢从这些具体处境开始：先了解你想要什么、能做什么、承担得起什么，再比较可走的路。

**它给你的，是有理由的选择、看得见的代价，以及走到哪个节点需要重新判断。** 不要求你先成为成绩拔尖、目标清晰的人。对还不知道的事，它会写明缺什么，帮你把下一步缩小到可以核实的问题。

## 从你正在面对的选择开始

| 你现在的处境 | 版本与问卷 | 你会拿到什么 |
|---|---|---|
| 不知道学什么；出分后要填志愿 | [高考版](skills/zhiqu/SKILL.md) · [问卷](https://wjsgzz.github.io/Zhiqu/gaokao.html) | 方向分析；出分后，在核实资格与候选后计算志愿组合、说明过线与调剂风险 |
| 犹豫读研还是工作；要择校或比较录取 | [读研版](skills/zhiqu-grad/SKILL.md) · [问卷](https://wjsgzz.github.io/Zhiqu/grad.html) | 先比较路径，再看院校与项目；费用、时间线、失败去向与更新检查点 |
| 不知道找什么工作；要比较offer或跳槽 | [求职版](skills/zhiqu-career/SKILL.md) · [问卷](https://wjsgzz.github.io/Zhiqu/career.html) | 工作内容与能力匹配、城市与生活成本、合同条件、进入路线与备选 |

三版都做发展规划与关键选择，也说明大致怎么走；不提供逐日备考、讲题、文书或简历代写、面试陪练、代投或代签。求职版适用于专科到博士。读研版暂不办理推免流程；推免同样涉及志愿与录取，暂不覆盖属于产品范围选择。

## 先看看三个普通人的选择

三个案例都以**2026年秋季的处境，面向2027年的目标**展开。人物、生日、经历和预算完全虚构；官方事实、计算和未决事项分别标注。它们展示的是做决定的过程，不是成功案例或统计有效性证明。

| 人物 | 正在犹豫什么 | 阅读案例 |
|---|---|---|
| **小禾，17岁，高三** | 喜欢文字与人文，选了物理，父母更希望师范；她想知道自己喜欢的是专业，还是专业的名字 | [网页](skills/zhiqu/examples/demo_2027_gaokao/report.html) · [PDF](skills/zhiqu/examples/demo_2027_gaokao/report.pdf) · [画像与复现](skills/zhiqu/examples/demo_2027_gaokao/README.md) |
| **小林，21岁，普通本科电气类** | 实践有兴趣，数学英语有短板；既想读研，又怕备考、秋招两头落空，家里支持也有上限 | [网页](skills/zhiqu-grad/examples/demo_2027/report.html) · [PDF](skills/zhiqu-grad/examples/demo_2027/report.pdf) · [画像与复现](skills/zhiqu-grad/examples/demo_2027/README.md) |
| **小宁，20岁，高职会计类** | 毕业后需要收入，又担心学历限制；第一份工作与专升本，怎样比较才不只听单位名气 | [网页](skills/zhiqu-career/examples/demo_2027/report.html) · [PDF](skills/zhiqu-career/examples/demo_2027/report.pdf) · [画像与复现](skills/zhiqu-career/examples/demo_2027/README.md) |

他们都有长处，也有一般人的迟疑、习惯和现实牵挂。报告不会把这些写成需要被纠正的人格标签。

**阶段决定报告能说到哪里。** 小禾尚未出分，报告先做方向与调研，不能给可直接录入的志愿表；小林尚未初试，不编个人上岸百分比；小宁尚无offer，不把期望工资写成实际待遇。等资料齐了，再更新判断。

想看出分后的表格与计算，可看[浙江案例B](skills/zhiqu/examples/case_b_zhejiang_2027/README.md)和[广东案例C](skills/zhiqu/examples/case_c_guangdong_e2e/README.md)；想实际运行候选→预测→优化→报告，见[纯虚构计算流程](skills/zhiqu/examples/pipeline_demo/README.md)。历史算例不构成当年的正式推荐，也不覆盖当前三个人的未知条件。

## 怎样使用

1. **选择问卷，填写与你有关的部分。** 不确定就写不确定；出生资料与传统视角自愿填写。
2. **复制生成的画像给支持本地文件与Python的AI Agent。** 说明目标年份、当前阶段，以及这次最想解决的选择。安装方法见下节。
3. **先确认关键资料与取舍。** AI追问真正影响结论的信息，找方向、查官方资料，并请你确认偏好和约束。
4. **阅读报告，纠正不符合自己的判断。** 可以说“这个专业我不愿意读”“预算需要降低”或“先按我和父母分别比较”。你不需要用专业术语。
5. **到检查点更新。** 出分、拿到录取或offer、费用或家庭条件变化后，重新生成画像与报告。

画像开头用于识别版本：`【高考志愿 · 自我盘点】`、`【读研 · 自我盘点】`、`【求职 · 自我盘点】`。

可以直接这样开始：

```text
这是我的知衢画像。我计划2027年入学，现在还在备考。
请先比较读研与工作的路径，写清预算、尚未核实的条件和下次检查点。
【读研 · 自我盘点】
……
```

```text
我是2027年广东考生，已出分。请按同科类位次和当年完整专业组核实，
先让我确认愿意读的专业与调剂态度，再计算志愿表。
```

你会拿到固定12节报告，以一句话结论和摘要开始，后面保留证据、取舍、行动路线与来源。不同版本的节名按场景变化；缺内容的节说明原因。HTML可直接打开，PDF适合分享和打印；只有少量问题时，不强行生成整份报告。

## 安装与开始使用

### 给AI Agent的入口

用户发来本仓库链接并要求安装使用时：先按本节检查环境与安装位置，再问使用哪一版，读取对应SKILL.md，邀请用户填写问卷。不要修改项目源代码，也不要把安装视为上传画像或发送消息的授权。

这是文件型技能，适合能读取SKILL.md、运行本地Python并按需访问官方网页的Agent。Claude Code、Codex可采用相应技能目录；普通网页版聊天可讨论画像，但不能据此承诺已安装技能或实际运行本地计算。

### 环境与技能依赖

- 建议Python **3.10或更高**；预测、优化、验证与报告核心使用标准库，历法引擎已随仓库固定版本提供。
- 生成PDF需要本机Chrome、Edge或Chromium；没有浏览器仍可生成HTML。
- 公务员职位表若为旧`.xls`，解析时另需可选`xlrd`；其他核心流程不需要它。原始附件只在临时目录处理。
- 当前共用资料在`zhiqu`中，求职版还引用读研版的方向资料。**最省心的安装方式是同层保留三个知衢技能及bazi**，按需加载；bazi用于复核出生资料或独立八字任务。只做高考且不使用传统视角时，可以仅安装zhiqu。
- `zhiqu-shared`仍是拟议迁移，当前不要安装不存在的目录。

```bash
git clone https://github.com/WJSGZZ/Zhiqu.git
cd Zhiqu
python3 --version
```

按Agent与使用范围选择目标目录，例如：

| 范围 | 目标目录（技能放在其下） |
|---|---|
| Claude Code个人安装 | `~/.claude/skills/` |
| Claude Code项目安装 | `<项目>/.claude/skills/` |
| Codex个人安装 | `~/.codex/skills/` |
| 共用母版管理 | `<项目>/.agents/skills/`，再按各Agent要求建立发现入口 |

在仓库根目录执行下面的复制脚本，把目标改成所需目录。**已有任一同名文件夹时会停下，先检查原版本，再选择更新方法，避免混入两套文件。** 本脚本不改变已有Agent配置。

```bash
python3 - <<'PY'
from pathlib import Path
import shutil
source = Path('skills')
target = Path('~/.claude/skills').expanduser()  # Codex可改为~/.codex/skills
names = ('zhiqu', 'zhiqu-grad', 'zhiqu-career', 'bazi')
for name in names:
    if not (source / name / 'SKILL.md').is_file():
        raise SystemExit(f'源技能不完整：{name}')
    if (target / name).exists() or (target / name).is_symlink():
        raise SystemExit(f'已有 {target / name}，先核对版本，不覆盖')
target.mkdir(parents=True, exist_ok=True)
for name in names:
    shutil.copytree(source / name, target / name,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
print(f'已安装到 {target}')
PY
```

安装后可在目标`zhiqu`目录运行：

```bash
python3 scripts/optimize.py examples/candidates_demo.csv --rank 30000 --slots 12 --u-fall -60
```

该命令只验证优化器入口，不证明数据覆盖或个性化报告有效。继续读取所需SKILL.md；维护示例的完整复核见下节。安装源码默认来自仓库main；分支中的新demo与README在合并前需从对应分支查看，本轮没有自动发布或合并。

## 哪些可以相信，哪些还需要核实

**关于事实。** 招生、院校、费用、岗位与政策使用官方公开资料，并注明年份和查询日期。遇到验证码、登录或人机验证不绕过，记为缺口。项目仓库存放整理后的CSV，原始xls、pdf与图片附件不入库；生成的示例报告另作成品保留。

**关于高考计算。** 各省、科类、批次分别分析。位次也会受人数、计划与制度变化影响，跨年可比性需要检查；不能把外省系数当作本省已校准参数。专业组号相同不代表组内专业相同，正式历史拼接需要可信对应。高考数据与覆盖情况见[data目录](skills/zhiqu/data/README.md)和[官方缺口](skills/zhiqu/references/public-data-gaps.md)。

模型模拟录取线的共同波动，使用贪心选择与局部交换寻找组合，**不保证全局最优**。单项过线概率、整张表落点概率与最终录取是不同的量；资格、组内专业分配与退档风险需要另核。零次滑档只是有限模拟未出现，不能写成风险为零。依据与失败的研究假设见[回测记录](skills/zhiqu/references/backtests.md)、[模型说明](skills/zhiqu/references/volunteer-game.md)与[年度研究](skills/zhiqu/data/calibration/README.md)。

**关于读研与求职。** 两版目前以按候选调研和情景比较为主，没有高考式完整候选数据库与统一录取优化器。群体录取率、工资分位数不能直接套成个人概率或个人薪资；未知的输入就保持未知。货币、时间与满意度分别陈述，再请本人确认取舍。

**关于八字。** 自愿选择的传统反思视角，与性格作答、现实经历并列核对；不参与资格、打分、推荐排序或排除选项，不预测录取与录用。出生日期与时间可用工具复算，命理解释的现实预测效度未经验证。[联动边界](skills/zhiqu/references/bazi-lens.md)与[独立八字技能](skills/bazi/SKILL.md)分别说明两种用途。

**关于你的资料。** 公开仓库不收真实个人信息。问卷生成画像后，由本人选择提供给哪个Agent；出生资料可留空。提供真实材料前检查其中的身份证、联系方式等是否必要，也确认所用Agent与服务的隐私规则。问卷使用外部资源时不把它宣传成完全离线，联网情况由实际页面实现决定。

## 开发、维护与复现

先读[DESIGN](DESIGN.md)了解目标与已定原则，再读[ROADMAP](ROADMAP.md)核对任务、分支、证据与交接状态。保留其他Agent的有效改动，在新分支实施；main的合并由作者决定。问卷题目与受保护案例不随文档维护顺手修改。

在仓库根目录运行：

```bash
python3 -m unittest discover -s skills/zhiqu/tests
python3 skills/zhiqu/scripts/check_family.py
python3 skills/zhiqu/scripts/validate_data.py
python3 skills/zhiqu/scripts/check_demos.py
```

前三份人物报告使用同一个Markdown渲染器，重现命令见各demo的README。出生输入、实际命盘输出、时间线与预算都保存在案例目录；`check_demos.py`会重新排盘并核对预算，不替代正文、官方资格或版面的人工审核。

其他可运行入口：

```bash
cd skills/zhiqu
python3 scripts/audit_skill.py --examples
python3 scripts/pipeline.py examples/pipeline_demo/config.json --out-dir /tmp/zhiqu-pipeline-new
```

pipeline的输出目录须为空。它使用纯虚构投档数据，用来核对可复现计算；[偏好核对示例](skills/zhiqu/examples/preference_demo/README.md)展示本人/家长两种场景，交互重算见[使用说明](skills/zhiqu/references/interactive-report.md)。数据变动运行validate_data与相关口径检查；模型变动须在该省合格留出年份证明误差下降，否则只保留定性提示。PDF交付前检查实际渲染、数字与来源。

## 仓库导航

| 入口 | 内容 |
|---|---|
| [index.html](index.html) · [gaokao.html](gaokao.html) · [grad.html](grad.html) · [career.html](career.html) | 三版问卷入口；在线站点对应部署版本，不一定等于当前分支 |
| [AGENTS.md](AGENTS.md) | Agent接手与安装入口 |
| [DESIGN.md](DESIGN.md) · [ROADMAP.md](ROADMAP.md) | 设计决定、完善清单与跨Agent交接 |
| [skills/zhiqu](skills/zhiqu/) | 高考技能、当前共用层、官方数据、预测/优化/报告、验证与示例 |
| [skills/zhiqu-grad](skills/zhiqu-grad/) | 读研路径、阶段与候选调研 |
| [skills/zhiqu-career](skills/zhiqu-career/) | 工作匹配、生活成本与offer比较 |
| [skills/bazi](skills/bazi/) | 固定历法引擎、独立命理方法与可选联动 |

知其所往，方行其衢。最终的选择仍属于你；知衢负责把理由、代价与未知讲清楚，让这一步走得更明白。
