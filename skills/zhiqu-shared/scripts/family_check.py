#!/usr/bin/env python3
"""知衢三个技能（zhiqu / zhiqu-grad / zhiqu-career）的一致性检查器。

只用标准库。用法（在 skills/zhiqu 目录下）：
    python3 scripts/check_family.py [--today YYYY-MM-DD]

每项检查是一个独立函数，返回 (level, file, line_no, message) 列表，
level 为 "错误" 或 "提醒"，file 是相对仓库根目录的路径。
"""
import argparse
import glob
import os
import re
import sys
from datetime import date, datetime

# 本文件路径：skills/zhiqu/scripts/check_family.py
# 仓库根目录 = 本文件所在目录（scripts）的父目录（skills/zhiqu）的
# 再上两级（skills/zhiqu -> skills -> 根目录）。
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
_ZHIQU_DIR = os.path.dirname(_SCRIPTS_DIR)  # skills/zhiqu
ROOT = os.path.dirname(os.path.dirname(_ZHIQU_DIR))  # 仓库根目录

ERROR = "错误"
WARN = "提醒"

# ---------------------------------------------------------------------------
# 公共工具
# ---------------------------------------------------------------------------

def skill_names(root):
    """列出 skills/ 下的技能目录名。"""
    skills_dir = os.path.join(root, "skills")
    if not os.path.isdir(skills_dir):
        return []
    return sorted(
        d for d in os.listdir(skills_dir)
        if os.path.isdir(os.path.join(skills_dir, d))
    )


def scanned_files(root):
    """返回本检查器扫描范围内的文件（相对仓库根目录的路径）。

    只扫描 skills/*/SKILL.md、skills/*/references/*.md、README.md；
    不扫描 skills/zhiqu/data/** 和 examples/**（它们本来就不在上面的范围内）。
    """
    files = []
    for name in ("README.md",):
        p = os.path.join(root, name)
        if os.path.isfile(p):
            files.append(name)
    for pattern in ("skills/*/SKILL.md", "skills/*/references/*.md"):
        for p in glob.glob(os.path.join(root, pattern)):
            files.append(os.path.relpath(p, root))
    return sorted(files)


def read_lines(root, relpath):
    with open(os.path.join(root, relpath), encoding="utf-8") as f:
        return f.readlines()


def count_cjk(text):
    """统计中日韩统一表意文字数量（粗略但够用）。"""
    return len(re.findall(r"[一-鿿]", text))


# ---------------------------------------------------------------------------
# 检查 1：引用的文件存在
# ---------------------------------------------------------------------------

_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
_CODE_RE = re.compile(r"`([^`]+)`")
_PATH_RE = re.compile(r"^(\.\./)*[\w\-./]+\.(md|py|html|csv|json)$")


def _is_placeholder(text):
    """明显是占位符的反引号内容，跳过不检查。"""
    if "<" in text or "*" in text:
        return True
    if "YYYY" in text:
        return True
    if re.search(r"(?<![A-Za-z])X(?![A-Za-z])", text):
        return True
    if "examples/" in text and "..." in text:
        return True
    return False


def _resolve_path(root, names, file_abspath, target):
    """按顺序尝试解析相对路径：本文件目录 -> 所属技能目录/references ->
    其余技能目录/references（三个技能互相引用参考文件）-> 仓库根目录 ->
    仓库根目录/skills/（兼容省略 skills/ 前缀的写法）。"""
    fdir = os.path.dirname(file_abspath)
    candidates = [os.path.join(fdir, target)]

    rel = os.path.relpath(file_abspath, root)
    parts = rel.split(os.sep)
    own_skill = parts[1] if parts[0] == "skills" and len(parts) > 1 else None

    # 技能内的文件只按本技能解析：引用别的技能必须写出 ../<技能>/ 路径，
    # 否则安装后会找不到。仓库根目录的 README 可以泛指任一技能的文件。
    order = [own_skill] if own_skill else list(names)
    for n in order:
        skill_dir = os.path.join(root, "skills", n)
        candidates.append(os.path.join(skill_dir, target))
        candidates.append(os.path.join(skill_dir, "references", target))

    candidates.append(os.path.join(root, target))
    candidates.append(os.path.join(root, "skills", target))

    return any(os.path.exists(os.path.normpath(c)) for c in candidates)


def check_links(root):
    issues = []
    names = skill_names(root)
    for relpath in scanned_files(root):
        fabs = os.path.join(root, relpath)
        for lineno, line in enumerate(read_lines(root, relpath), 1):
            # (a) markdown 链接
            for m in _LINK_RE.finditer(line):
                target = m.group(1).strip()
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                if target.startswith("#"):
                    continue
                target = target.split("#", 1)[0]
                target = re.sub(r":\d+$", "", target)
                if not target:
                    continue
                if not _resolve_path(root, names, fabs, target):
                    issues.append((ERROR, relpath, lineno,
                                    f"链接目标不存在：{target}"))
            # (b) 反引号里的路径
            for m in _CODE_RE.finditer(line):
                content = m.group(1)
                if not _PATH_RE.match(content):
                    continue
                if not ("/" in content or content.endswith(".md")):
                    continue
                if _is_placeholder(content):
                    continue
                if not _resolve_path(root, names, fabs, content):
                    issues.append((ERROR, relpath, lineno,
                                    f"引用的文件不存在：{content}"))
    return issues


# ---------------------------------------------------------------------------
# 检查 2：问卷节名引用
# ---------------------------------------------------------------------------

_DATA_TITLE_RE = re.compile(r'data-title="([^"]+)"')
_SECTION_NAME_RE = re.compile(r"「([^」]+)」(一节|节)")
_SECTION_NUM_RE = re.compile(r"第[一二三四五六七八九十]+节")


def _html_titles(root, name):
    p = os.path.join(root, name)
    if not os.path.isfile(p):
        return set()
    with open(p, encoding="utf-8") as f:
        text = f.read()
    titles = set()
    for t in _DATA_TITLE_RE.findall(text):
        t = t.strip()
        if t.endswith("（可选）"):
            t = t[: -len("（可选）")]
        titles.add(t)
    return titles


def check_section_names(root):
    issues = []
    grad_titles = _html_titles(root, "grad.html")
    career_titles = _html_titles(root, "career.html")

    targets = []
    for skill, files in (
        ("zhiqu-grad", ["skills/zhiqu-grad/SKILL.md"] +
         [os.path.relpath(p, root) for p in
          glob.glob(os.path.join(root, "skills/zhiqu-grad/references/*.md"))]),
        ("zhiqu-career", ["skills/zhiqu-career/SKILL.md"] +
         [os.path.relpath(p, root) for p in
          glob.glob(os.path.join(root, "skills/zhiqu-career/references/*.md"))]),
    ):
        for f in files:
            if os.path.isfile(os.path.join(root, f)):
                targets.append((skill, f))

    shared_file = "skills/zhiqu-grad/references/direction-and-state.md"

    for skill, relpath in targets:
        for lineno, line in enumerate(read_lines(root, relpath), 1):
            # 「节名」一节 / 节
            for m in _SECTION_NAME_RE.finditer(line):
                title = m.group(1)
                in_grad = title in grad_titles
                in_career = title in career_titles
                if relpath == shared_file:
                    if not in_grad and not in_career:
                        issues.append((ERROR, relpath, lineno,
                                        f"节名在 grad.html 和 career.html 中都不存在：「{title}」"))
                    elif in_grad != in_career and not (
                            ("读研版" in line and in_grad) or ("求职版" in line and in_career)):
                        only = "grad.html" if in_grad else "career.html"
                        issues.append((WARN, relpath, lineno,
                                        f"节名「{title}」仅见于 {only}，本文件为读研/求职共用，请确认"))
                elif skill == "zhiqu-grad":
                    if not in_grad:
                        issues.append((ERROR, relpath, lineno,
                                        f"节名在 grad.html 中不存在：「{title}」"))
                else:  # zhiqu-career
                    if not in_career:
                        issues.append((ERROR, relpath, lineno,
                                        f"节名在 career.html 中不存在：「{title}」"))

            # 第X节（编号引用，节次会变，除非明确说明是本文件的固定编号）
            for m in _SECTION_NUM_RE.finditer(line):
                before = line[max(0, m.start() - 12): m.start()]
                if "本文件" in before or ".md`" in before or ".md）" in before:
                    continue
                issues.append((ERROR, relpath, lineno,
                                f"用编号引用问卷节次，节次会变：{m.group(0)}"))
    # 报告模板与示例正文里同样不能写“问卷第X节”（2026-10 复核发现模板写死了“问卷第九节”）
    from pathlib import Path
    extra = [f for f in ("skills/zhiqu/scripts/report.py", "skills/zhiqu/scripts/render_report.py") if (Path(root) / f).exists()]
    extra += sorted(str(p.relative_to(root)) for p in Path(root).glob("skills/*/examples/*/report.json"))
    extra += sorted(str(p.relative_to(root)) for p in Path(root).glob("skills/*/examples/*/report.md"))
    for relpath in extra:
        for lineno, line in enumerate(read_lines(root, relpath), 1):
            for m in re.finditer(r"问卷第[一二三四五六七八九十0-9]+[节部分]", line):
                issues.append((ERROR, relpath, lineno, f"用编号引用问卷节次，节次会变，请写节名：{m.group(0)}"))
    return issues


# ---------------------------------------------------------------------------
# 检查 3：报告目录完整
# ---------------------------------------------------------------------------

_ROW_NUM_RE = re.compile(r"^\|\s*(\d{2})\b")


GAOKAO_TITLES = ["摘要", "你的画像", "专业方向", "志愿表", "为什么这样排", "院校调研", "填报前核对清单", "填报单", "追问清单", "方法与假设", "事后回看", "数据来源与声明"]


def _check_gaokao_toc(root, relpath, lines):
    """高考报告 12 节的标题与顺序，须同时与 report-guide 内联目录、report.py、各示例 report.md 一致。
    出分前的规划阶段示例没有志愿表，其第 08 节可以是“行动路线”（见 report-guide）。"""
    out = []
    toc = [(n, l) for n, l in enumerate(lines, 1) if l.startswith("01 摘要")]
    if not toc:
        return [(ERROR, relpath, 1, "report-guide.md 缺少内联目录行（以“01 摘要”开头）")]
    lineno, line = toc[0]
    got = re.findall(r"(\d{2})\s*([^\s·]+)", line)
    if [t for _, t in got] != GAOKAO_TITLES or [n for n, _ in got] != [f"{i:02d}" for i in range(1, 13)]:
        out.append((ERROR, relpath, lineno, f"内联目录应为固定的 12 节：{GAOKAO_TITLES}，实际 {[t for _, t in got]}"))
    rp = os.path.join(root, "skills/zhiqu/scripts/report.py")
    if os.path.isfile(rp):
        titles = re.findall(r'sec\("([^"]+)"', open(rp, encoding="utf-8").read())
        titles = [t for i, t in enumerate(titles) if t not in titles[:i]]
        if titles != GAOKAO_TITLES:
            out.append((ERROR, "skills/zhiqu/scripts/report.py", 1, f"report.py 的章节顺序与固定目录不一致：{titles}"))
    exdir = os.path.join(root, "skills/zhiqu/examples")
    if os.path.isdir(exdir):
        for name in sorted(os.listdir(exdir)):
            md = os.path.join(exdir, name, "report.md")
            if not os.path.isfile(md):
                continue
            heads = re.findall(r"^## (\d{2}) (.+)$", open(md, encoding="utf-8").read(), re.M)
            expect = list(zip([f"{i:02d}" for i in range(1, 13)], GAOKAO_TITLES))
            ok = [h[0] for h in heads] == [e[0] for e in expect] and all(
                h[1].strip() == e[1] or (h[0] == "08" and h[1].strip() == "行动路线") for h, e in zip(heads, expect))
            if not ok:
                out.append((ERROR, f"skills/zhiqu/examples/{name}/report.md", 1, "报告章节应为固定 12 节（出分前规划阶段第 08 节可为“行动路线”）"))
    return out


def check_report_guide(root):
    issues = []
    for relpath in ("skills/zhiqu-grad/references/report-guide.md",
                     "skills/zhiqu-career/references/report-guide.md",
                     "skills/zhiqu/references/report-guide.md"):
        fabs = os.path.join(root, relpath)
        if not os.path.isfile(fabs):
            continue
        lines = read_lines(root, relpath)
        nums = []
        for lineno, line in enumerate(lines, 1):
            m = _ROW_NUM_RE.match(line)
            if m:
                nums.append((lineno, m.group(1)))
        if relpath == "skills/zhiqu/references/report-guide.md" and not nums:
            # 高考指南用一行内联目录“01 摘要 · 02 你的画像 …”；逐节核对标题与 report.py 一致
            issues.extend(_check_gaokao_toc(root, relpath, lines))
            continue
        expected = [f"{i:02d}" for i in range(1, 13)]
        got = [n for _, n in nums]
        if got != expected:
            lineno = nums[0][0] if nums else 1
            issues.append((ERROR, relpath, lineno,
                            f"报告目录应为 01..12 依次出现一次，实际为：{got}"))
    return issues


# ---------------------------------------------------------------------------
# 检查 4：画像开头一致
# ---------------------------------------------------------------------------

_STORE_KEY_RE = re.compile(r"STORE_KEY\s*=\s*'([^']+)'")


def check_portrait_consistency(root):
    issues = []
    expect = {
        "grad.html": "【读研 · 自我盘点】",
        "career.html": "【求职 · 自我盘点】",
        "gaokao.html": "【高考志愿 · 自我盘点】",
    }
    readme = ""
    readme_path = os.path.join(root, "README.md")
    if os.path.isfile(readme_path):
        with open(readme_path, encoding="utf-8") as f:
            readme = f.read()

    store_keys = {}
    for html, marker in expect.items():
        p = os.path.join(root, html)
        if not os.path.isfile(p):
            issues.append((ERROR, html, 1, "文件不存在"))
            continue
        with open(p, encoding="utf-8") as f:
            text = f.read()
        if marker not in text:
            issues.append((ERROR, html, 1, f"未找到画像开头标记：{marker}"))
        if marker not in readme:
            issues.append((ERROR, "README.md", 1, f"未找到画像开头标记：{marker}"))
        m = _STORE_KEY_RE.search(text)
        if not m:
            issues.append((ERROR, html, 1, "未找到 STORE_KEY"))
        else:
            store_keys[html] = m.group(1)

    seen = {}
    for html, key in store_keys.items():
        if key in seen:
            issues.append((ERROR, html, 1,
                            f"STORE_KEY 与 {seen[key]} 重复：{key}"))
        else:
            seen[key] = html
    return issues


# ---------------------------------------------------------------------------
# 检查 5：复核期限
# ---------------------------------------------------------------------------

_MARKER_RE = re.compile(
    r"<!--\s*核实：(\d{4}-\d{2}-\d{2})；复核期限：(\d{4}-\d{2}-\d{2})\s*-->"
)
_EXPIRING_WORD_RE = re.compile(r"规定|快照|查询|发布")
_YEAR_RE = re.compile(r"\b(20[2-3]\d)\b")


def check_review_deadline(root, today=None):
    if today is None:
        today = date.today()
    issues = []
    for relpath in scanned_files(root):
        lines = read_lines(root, relpath)
        text = "".join(lines)
        markers = []
        for lineno, line in enumerate(lines, 1):
            m = _MARKER_RE.search(line)
            if m:
                markers.append((lineno, m.group(1), m.group(2)))
        for lineno, verified, deadline in markers:
            try:
                d = datetime.strptime(deadline, "%Y-%m-%d").date()
            except ValueError:
                issues.append((ERROR, relpath, lineno, f"复核期限日期格式错误：{deadline}"))
                continue
            if today > d:
                issues.append((ERROR, relpath, lineno, "已过复核期限，先按来源更新再使用"))
            elif (d - today).days <= 30:
                issues.append((WARN, relpath, lineno, f"复核期限临近：{deadline}"))

        if not markers and relpath.startswith("skills/") and "/references/" in relpath:
            if _YEAR_RE.search(text) and _EXPIRING_WORD_RE.search(text):
                issues.append((WARN, relpath, 1, "含有会过期的事实，建议加复核期限标记"))
    return issues


# ---------------------------------------------------------------------------
# 检查 6：重复段落
# ---------------------------------------------------------------------------

_LIST_MARKER_RE = re.compile(r"^\s*(?:[-*+]|\d+[.、])\s+")


def _normalize_line(line):
    line = line.strip()
    line = _LIST_MARKER_RE.sub("", line).strip()
    return line


def check_duplicate_paragraphs(root):
    issues = []
    seen = {}  # normalized text -> [(relpath, lineno), ...]
    for relpath in scanned_files(root):
        for lineno, raw in enumerate(read_lines(root, relpath), 1):
            stripped = raw.strip()
            if not stripped:
                continue
            if stripped.startswith("|") or stripped.startswith("#"):
                continue
            text = _normalize_line(raw)
            if not text:
                continue
            if count_cjk(text) < 40:
                continue
            seen.setdefault(text, []).append((relpath, lineno))

    reported = set()
    for text, locs in seen.items():
        files_involved = {f for f, _ in locs}
        if len(files_involved) < 2:
            continue
        if text in reported:
            continue
        reported.add(text)
        loc_desc = "；".join(f"{f}:{n}" for f, n in locs)
        first_file, first_line = locs[0]
        issues.append((WARN, first_file, first_line,
                        f"跨文件重复段落（{loc_desc}）：{text[:30]}…"))
    return issues


# ---------------------------------------------------------------------------
# 检查 7：体积
# ---------------------------------------------------------------------------

def check_file_size(root):
    issues = []
    for relpath in scanned_files(root):
        size = os.path.getsize(os.path.join(root, relpath))
        base = os.path.basename(relpath)
        if base == "SKILL.md" and size > 20000:
            issues.append((WARN, relpath, 1, f"SKILL.md 超过 20000 字节（{size}）"))
        elif "/references/" in relpath and size > 30000:
            issues.append((WARN, relpath, 1, f"参考文件超过 30000 字节（{size}）"))
    return issues


# ---------------------------------------------------------------------------
# 汇总与输出
# ---------------------------------------------------------------------------

CHECKS = [
    ("引用的文件存在", check_links),
    ("问卷节名引用", check_section_names),
    ("报告目录完整", check_report_guide),
    ("画像开头一致", check_portrait_consistency),
    ("复核期限", check_review_deadline),
    ("重复段落", check_duplicate_paragraphs),
    ("体积", check_file_size),
]


def run_all(root, today=None):
    """返回 {检查名: issues} 字典。"""
    result = {}
    for name, func in CHECKS:
        if func is check_review_deadline:
            result[name] = func(root, today)
        else:
            result[name] = func(root)
    return result


def format_report(result):
    lines = []
    total_error = 0
    total_warn = 0
    for name, issues in result.items():
        lines.append(f"【{name}】")
        if not issues:
            lines.append("  无问题")
            continue
        for level, relpath, lineno, msg in issues:
            if level == ERROR:
                total_error += 1
            else:
                total_warn += 1
            lines.append(f"  {level} {relpath}:{lineno} {msg}")
    lines.append("")
    lines.append(f"合计：{total_error} 个错误，{total_warn} 个提醒")
    return "\n".join(lines), total_error


def main():
    parser = argparse.ArgumentParser(description="知衢仓库一致性检查")
    parser.add_argument("--today", help="用于复核期限检查的日期，格式 YYYY-MM-DD，默认今天")
    args = parser.parse_args()

    today = None
    if args.today:
        try:
            today = datetime.strptime(args.today, "%Y-%m-%d").date()
        except ValueError:
            print(f"--today 格式错误：{args.today}", file=sys.stderr)
            return 2

    result = run_all(ROOT, today)
    report, total_error = format_report(result)
    print(report)
    return 1 if total_error else 0


if __name__ == "__main__":
    sys.exit(main())
