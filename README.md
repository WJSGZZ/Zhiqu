<p align="center"><img src="assets/logo.png" width="128" alt="知衢"></p>
<h1 align="center">知衢</h1>
<p align="center"><strong>知其所往，方行其衢。</strong></p>
<p align="center">高考志愿 · 读研规划 · 求职方向——在人生的几个路口，把选择想清楚</p>
<p align="center">
  <a href="https://wjsgzz.github.io/Zhiqu/">填写问卷</a> ·
  <a href="#看三个例子">看三个例子</a> ·
  <a href="#三步开始">三步开始</a> ·
  <a href="AGENTS.md">给 AI Agent</a> ·
  <a href="DESIGN.md">设计文档</a>
</p>

<details>
<summary><b>给 AI Agent：用户发来本仓库链接时，先读 <a href="AGENTS.md">AGENTS.md</a></b></summary>

AGENTS.md 里有安装脚本、项目地图、工作规则和验证命令。只安装、只读取，不修改项目源代码；安装不等于获准上传用户资料或代发消息。

</details>

<p align="center"><img src="assets/readme/entry.png" width="760" alt="知衢问卷入口：高考志愿、读研规划、求职方向"></p>

选专业、读研、找工作时，最难的往往不是信息太少，而是不知道哪些信息和自己有关。知衢先用一份 15 分钟左右的问卷了解你，再由你自己的 AI Agent（Claude Code、Codex 等）按知衢的方法查官方资料、做计算，交给你一份看得懂的报告：**有理由的选择、看得见的代价，以及走到哪一步需要重新判断。**

## 它能帮你做什么

- **高考**：按你的位次、选科和自己排的优先级，用各省官方历年投档数据，排出一张期望满意度最高、滑档风险可控的志愿表，并写清每一格为什么在这里。
- **读研**：先判断该走考研、境外读研、中外合作办学、先工作还是考公，再在路里挑学校；分清哪些可以算、哪些只能比较情景。
- **求职**：专科到博士都适用。找出工作内容、收入、城市、节奏都合适的方向；拿到 offer 时，算清到手收入、时薪和扣掉房租后每月剩多少。
- **传统视角（可选）**：填了出生信息，问卷当场排出八字，报告把它和你的性格自评、现实条件放在一起对照，只用来提问和反思，**不参与打分，不排除任何选项**。

知衢给路线图，不陪跑：不代写文书、不改简历、不做题目辅导，也不保证录取或录用。

## 看三个例子

三个完全虚构的普通人，分别在浙江、广东、四川，都面向 2027 年。每个例子分两步：**现在**，资料不全时只做方向和预算；**假想后续阶段**，演示资料齐了之后知衢会算出什么。人物是虚构的，用到的招生、工资、政策数据是真实官方数据。

### 小禾 · 浙江高三：喜欢哲学和历史，父母希望读师范

<img src="assets/readme/demo-gaokao.png" width="760" alt="小禾假想出分后的志愿表">

用浙江 2022—2026 年官方投档位次，按她的排序（专业 > 前景 > 城市 > 学校）排出 21 个志愿，最可能落在浙江外国语学院汉语言文学（师范），约 73%。换成父母的排序（前景优先）再算一次，**最可能的去向不变**，分歧只在第二去向，约占四分之一的概率。哲学在浙江可以报，但以这个位次只能冲。

[阅读报告](skills/zhiqu/examples/demo_2027_gaokao/report.md) · [PDF](skills/zhiqu/examples/demo_2027_gaokao/report.pdf) · [画像与复现](skills/zhiqu/examples/demo_2027_gaokao/README.md)

### 小林 · 广东普通本科电气类：想读研，又怕备考和秋招两头落空

<img src="assets/readme/demo-grad.png" width="760" alt="小林的初试分数情景对照">

华南理工大学电气专硕 2026 年统考录取约 120 人，比 2025 年多了一倍，多出来的主要是新增的"基地计划"。两年录取者的初试中位数都在 382 分左右，变的是最低分（365 → 330）。所以关键不是"华工难不难"，而是 **2027 年名额还在不在**，以及她的模考落在哪一段。报告不编个人上岸概率。

[阅读报告](skills/zhiqu-grad/examples/demo_2027/report.md) · [PDF](skills/zhiqu-grad/examples/demo_2027/report.pdf) · [画像与复现](skills/zhiqu-grad/examples/demo_2027/README.md)

### 小宁 · 四川高职会计类：先工作，还是专升本

<img src="assets/readme/demo-career.png" width="760" alt="小宁的两个假想 offer 比较">

工资高的直签岗位在省会要租房，每月剩约 1780 元；工资低的劳务派遣岗位离家近，每月剩约 2363 元，另有公积金。**钱多不等于剩得多**；但派遣要问清能不能转直签，直签能学到完整的账务流程。收入参考用四川省人社厅公布的工资价位，并注明那不是应届起薪。

[阅读报告](skills/zhiqu-career/examples/demo_2027/report.md) · [PDF](skills/zhiqu-career/examples/demo_2027/report.pdf) · [画像与复现](skills/zhiqu-career/examples/demo_2027/README.md)

想看更多高考算例：[浙江案例 B](skills/zhiqu/examples/case_b_zhejiang_2027/README.md)、[广东案例 C](skills/zhiqu/examples/case_c_guangdong_e2e/README.md)。

## 三步开始

1. **填问卷**：打开[在线问卷](https://wjsgzz.github.io/Zhiqu/)，选高考、读研或求职。拿不准的可以留空，出生信息自愿填写。作答只存在你自己的浏览器里。
2. **交给 AI Agent**：把本仓库链接 `https://github.com/WJSGZZ/Zhiqu` 发给能运行本地程序的 AI Agent，说"安装并使用这个技能"；再把问卷生成的画像发给它（以 `【高考志愿 · 自我盘点】`、`【读研 · 自我盘点】` 或 `【求职 · 自我盘点】` 开头），说明你现在处在哪个阶段、最想解决什么。
3. **读报告，纠正它**：报告固定 12 节，第一页就是结论和下一步。不符合你的地方直接说，比如"这个专业我不愿意读""按我和父母分别算一次"。到了出分、拿到 offer 这些节点，回来更新问卷，重新算。

## 哪些可以相信，哪些还要核实

- **事实**：招生、院校、工资、政策只用官方公开资料，写明年份和查询日期；遇到验证码、登录不绕过，记为缺口。
- **计算**：高考志愿表的录取概率在有位次数据的省份做过校准检验（各省情况见[年度研究](skills/zhiqu/data/calibration/README.md)），但仍是估计；滑档概率为零只说明模拟里没出现，不等于没有风险。读研和求职以情景比较为主，群体数据不直接套成个人概率或个人工资。
- **八字**：传统视角，现实预测效度未经验证；删掉它，所有资格、打分和排序都不变。
- **你的资料**：公开仓库不收真实个人信息。画像发给哪个 AI、要不要填出生信息，都由你决定。

方法细节见[设计文档](DESIGN.md)、[模型说明](skills/zhiqu/references/volunteer-game.md)、[回测记录](skills/zhiqu/references/backtests.md)。

## 仓库导航

| 入口 | 内容 |
|---|---|
| [问卷](https://wjsgzz.github.io/Zhiqu/)（[index.html](index.html)、[gaokao](gaokao.html)、[grad](grad.html)、[career](career.html)） | 三版问卷，GitHub Pages 部署 |
| [skills/zhiqu](skills/zhiqu/) | 高考技能，也是三版共用的核心：官方数据、预测、优化、报告、检查脚本 |
| [skills/zhiqu-grad](skills/zhiqu-grad/) · [skills/zhiqu-career](skills/zhiqu-career/) | 读研版、求职版 |
| [skills/bazi](skills/bazi/) | 八字技能：排盘与解盘 |
| [AGENTS.md](AGENTS.md) | 给 AI Agent：安装、项目地图、规则与验证 |
| [DESIGN.md](DESIGN.md) · [ROADMAP.md](ROADMAP.md) | 设计与决定、完善清单与协作记录 |

> 知衢不是官方工具，不保证录取或录用。一切以考试院、教育部、各校和用人单位当年的正式文件为准；最终的选择属于你自己。
