# 给 AI Agent

这份文件写给第一次接触知衢的 AI Agent（Claude Code、Codex 等）。读完它，你应该知道这个项目是什么、怎么安装使用、怎么在不破坏它的前提下改进它。给人看的介绍在 [README.md](README.md)。

## 一、先分清你是来做什么的

| 你的任务 | 读什么 | 不做什么 |
|---|---|---|
| **用知衢帮一个人做规划**（最常见：用户发来仓库链接，说"安装并使用"） | 本文件第二、三节，然后读对应技能的 `SKILL.md` | 不改项目源代码；安装不等于获准上传用户资料、代发消息或代为填报签约 |
| **改进这个项目本身** | 本文件第四到七节，再读 [DESIGN.md](DESIGN.md) 和 [ROADMAP.md](ROADMAP.md) | 不在 main 上直接改；不整份覆盖别人写的文件 |

## 二、知衢是什么

在高考、读研、求职这几个路口，帮一个人做**发展规划和关键选择**：走哪条路、选哪里、选哪个、失败了退到哪、什么时候再看一次，并给出大致怎么走的**路线图**。它**不陪跑执行**：不做逐日计划、讲题、文书或简历代写、面试陪练、代投代签。

流程固定为：问卷 → 画像 → 定阶段 → 分清事实、偏好、约束、本人判断 → 找方向 → 按候选收集官方数据 → 计算 → 12 节报告 → 检查点。

四个技能，同一个仓库，分开加载：

| 技能 | 用途 | 问卷 | 画像开头 |
|---|---|---|---|
| `skills/zhiqu` | 高考志愿，也是**三版共用的核心层** | `gaokao.html` | `【高考志愿 · 自我盘点】` |
| `skills/zhiqu-grad` | 读研规划（考研、境外、中外合作办学、先工作、考公） | `grad.html` | `【读研 · 自我盘点】` |
| `skills/zhiqu-career` | 求职方向（专科到博士） | `career.html` | `【求职 · 自我盘点】` |
| `skills/bazi` | 八字：独立使用，或作为前三者的"传统视角" | 三份问卷都有可选的出生信息 | — |

共用的规则和资料放在 `skills/zhiqu/references/`：
- `shared-rules.md`：骨架、原则、防误伤、交付前自查、纠错流程、写作纪律。**每次交付报告前都要按它自查。**
- `job-market.md`：全国就业形势；
- `outlook.md`：专业与行业前景；
- `bazi-lens.md`：八字怎么用、用到哪一层。

读研版和求职版共用 `skills/zhiqu-grad/references/direction-and-state.md`（迷茫与状态）。技能之间用相对路径互相引用，所以**四个技能要同层安装**。

## 三、安装与使用

需要：Python 3.10 或更高，核心脚本只用标准库；出 PDF 需要本机有 Chrome、Edge 或 Chromium，没有时输出 HTML。旧版 `.xls` 公务员职位表解析另需可选的 `xlrd`。

```bash
git clone --depth 1 https://github.com/WJSGZZ/Zhiqu.git
cd Zhiqu
```

把四个技能复制到你的技能目录。Claude Code 个人安装用 `~/.claude/skills/`，Codex 用 `~/.codex/skills/`，其他支持 `SKILL.md` 的 Agent 按其文档。已有同名文件夹时脚本会停下，先核对版本，不要覆盖：

```bash
python3 - <<'PY'
from pathlib import Path
import shutil
source = Path('skills')
target = Path('~/.claude/skills').expanduser()  # Codex 改为 ~/.codex/skills
names = ('zhiqu', 'zhiqu-grad', 'zhiqu-career', 'bazi')
for name in names:
    if not (source / name / 'SKILL.md').is_file():
        raise SystemExit(f'源技能不完整：{name}')
    if (target / name).exists() or (target / name).is_symlink():
        raise SystemExit(f'已有 {target / name}，先核对版本，不覆盖')
target.mkdir(parents=True, exist_ok=True)
for name in names:
    shutil.copytree(source / name, target / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
print(f'已安装到 {target}')
PY
```

验证安装：在安装后的 `zhiqu` 目录运行 `python3 scripts/optimize.py examples/candidates_demo.csv --rank 30000 --slots 12 --u-fall -60`，能输出一张志愿表即可。不支持技能目录的 Agent，每次对话先读对应的 `SKILL.md`。

然后：告诉用户装在哪里，问清是高考、读研还是求职，请用户填[在线问卷](https://wjsgzz.github.io/Zhiqu/)并把画像发来，按对应 `SKILL.md` 工作。三个完整示例在各技能的 `examples/demo_2027*/`，照着它们的结构写报告。

## 四、改进项目：开工前

1. 读 [DESIGN.md](DESIGN.md)（目标、原则、家族结构、扩展规则、已定决定、纠错记录）和 [ROADMAP.md](ROADMAP.md)（待办、验收标准、负责人与分支）。第十节是跨 Agent 交接状态。
2. `git fetch`，看 main 和其他分支、工作树上有没有别人正在改同一批文件。
3. 在 ROADMAP 对应条目上**写明负责人和分支**再动手；一项一个分支，从最新 main 开。

## 五、改完之后：必须通过的检查

在仓库根目录：

```bash
python3 -m unittest discover -s skills/zhiqu/tests     # 全部测试
python3 skills/zhiqu/scripts/check_family.py           # 引用、问卷节名、报告目录、复核期限、重复与体积；须 0 错误
python3 skills/zhiqu/scripts/check_demos.py            # 三个示例：重新排盘、重跑优化、重算 offer 与预算
python3 skills/zhiqu/scripts/validate_data.py          # 改了数据时
```

- 改了计算逻辑：重跑受影响的示例，核对报告数字，更新测试基准。
- 改了模型规则：必须在**该省**的留出年份上证明误差下降，否则只写成定性提示。
- 生成的 PDF 要实际打开看版面和数字。

## 六、协作与合并

- **记录只放一处**：状态、证据、提交号就地写在 ROADMAP 的条目里；重要决定追加到 DESIGN 的决定表；发现错误写进 DESIGN 的纠错记录。不另建台账。
- **互相审核**：一方完成的分支，由另一方审核，意见写在该条目下。
- **合并 main**：作者已授权（2026-09-30）：检查全部通过、ROADMAP 已记录，负责的 Agent 可以自行合并 main。以下改动先问作者：
  - 问卷题目；
  - 产品定位；
  - 删除已有功能；
  - 任何涉及真实个人信息的内容。
- **整合别人的分支**：逐处核对冲突，两边的新增都保留，不拿旧版整份覆盖。

## 七、容易踩的坑（都真实发生过）

- **把"没查到"写成"不存在"**：只核实了一所学校，就断言"物理类几乎读不了哲学"。只写证据支持的范围。
- **把群体数字当个人概率**：用"拟录取最低分 + 个人估分"推算个人上岸率；把在岗工资价位当应届起薪。
- **用经验帖数字做决定**：经验帖只当线索，官方原表才作依据。它常常和原表对不上。
- **按编号引用问卷节次**：节次会变，一律写「节名」一节。
- **同一事实写在两处**：会变的数字只放一个文件，别处链接。
- **会过期的事实**：加 `<!-- 核实：YYYY-MM-DD；复核期限：YYYY-MM-DD -->`，到期先更新再用。
- **八字越界**：只写到"主题倾向"层，不打分、不排除选项、不判断哪年考试或求职吉凶。
- **委派判断类任务给更小的模型**：规格清楚、能机械验证的活才适合交给子代理；需要判断来源和核对数字的活，交出去往往要反复返工，反而更费。
