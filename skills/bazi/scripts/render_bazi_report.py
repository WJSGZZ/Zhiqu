#!/usr/bin/env python3
"""Render a portable, interactive BaZi report from structured JSON."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any


SKILL_ROOT = Path(__file__).resolve().parents[1]
CSS_PATH = SKILL_ROOT / "assets" / "report.css"
JS_PATH = SKILL_ROOT / "assets" / "report.js"


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def paras(value: Any, css_class: str = "") -> str:
    if value is None or value == "":
        return ""
    parts = [part.strip() for part in str(value).splitlines() if part.strip()]
    cls = f' class="{css_class}"' if css_class else ""
    return "".join(f"<p{cls}>{esc(part)}</p>" for part in parts)


def list_html(items: Any) -> str:
    values = [item for item in (items or []) if str(item).strip()]
    if not values:
        return ""
    return "<ul>" + "".join(f"<li>{esc(item)}</li>" for item in values) + "</ul>"


def confidence(value: Any) -> str:
    return f'<span class="confidence">置信度 {esc(value)}</span>' if value not in (None, "") else ""


def status_badge(value: Any) -> str:
    labels = {
        "internally_coherent": "体系内成立",
        "textually_attested": "文献可证",
        "cross_text_consensus": "跨文本共识",
        "unresolved": "未决",
        "counterexample_found": "存在反例",
        "rejected_by_current_test": "当前测试否定",
    }
    shown = labels.get(str(value), value)
    return f'<span class="status-badge">{esc(shown)}</span>' if shown not in (None, "") else ""


def report_title(value: Any) -> str:
    parts = [part.strip() for part in str(value or "").split("·")]
    if len(parts) == 4 and all(parts):
        return "".join(
            '<span class="pillar-pair">'
            + "".join(f'<span class="pillar">{esc(part)}</span>' for part in pair)
            + "</span>"
            for pair in (parts[:2], parts[2:])
        )
    return esc(value)


def section(section_id: str, number: int, title: str, body: str) -> str:
    if not body.strip():
        return ""
    return (
        f'<section class="section" id="{esc(section_id)}" data-search-section data-search-title="{esc(title)}">'
        f'<div class="section-head"><span class="section-no">{number:02d}</span><h2>{esc(title)}</h2></div>'
        f"{body}</section>"
    )


def chart_table(chart: dict[str, Any]) -> str:
    columns = chart.get("columns") or []
    rows = chart.get("rows") or []
    if not columns or not rows:
        return ""
    head = "<tr><th>项目</th>" + "".join(f"<th>{esc(col)}</th>" for col in columns) + "</tr>"
    body = []
    for row in rows:
        values = list(row.get("values") or [])
        values += [""] * max(0, len(columns) - len(values))
        cells = []
        for value in values[: len(columns)]:
            normalized = "未知" if str(value).strip() in ("未知", "未选", "待补") else value
            cell_class = "unknown" if normalized == "未知" else ""
            cells.append(f'<td class="{cell_class}">{esc(normalized)}</td>')
        body.append(
            f"<tr><th>{esc(row.get('label', ''))}</th>"
            + "".join(cells)
            + "</tr>"
        )
    return f'<div class="table-wrap"><table><thead>{head}</thead><tbody>{"".join(body)}</tbody></table></div>'


def render_models(models: list[dict[str, Any]]) -> str:
    chunks = []
    for model in models:
        body = (
            paras(model.get("question"), "note")
            + paras(model.get("conclusion"))
            + labeled_list("命盘证据", model.get("evidence"))
            + labeled_list("成立条件", model.get("conditions"))
            + labeled_list("失败条件", model.get("failure_conditions"))
        )
        chunks.append(
            "<details>"
            f"<summary><span>{esc(model.get('name', '未命名模型'))}{confidence(model.get('confidence'))}</span></summary>"
            f'<div class="detail-body">{body}</div></details>'
        )
    return "".join(chunks)


def labeled_list(label: str, items: Any) -> str:
    rendered = list_html(items)
    return f'<div><span class="label">{esc(label)}</span>{rendered}</div>' if rendered else ""


def render_cards(items: list[dict[str, Any]], title_key: str = "title") -> str:
    cards = []
    for item in items:
        title = item.get(title_key) or item.get("name") or "未命名"
        details = item.get("details") or []
        cards.append(
            '<article class="card">'
            f"<h3>{esc(title)}{confidence(item.get('confidence'))}{status_badge(item.get('status'))}</h3>"
            f"{paras(item.get('summary') or item.get('text'))}{list_html(details)}"
            "</article>"
        )
    return f'<div class="grid-2">{"".join(cards)}</div>' if cards else ""


def render_factors(items: list[dict[str, Any]]) -> str:
    chunks = []
    for item in items:
        chunks.append(
            '<article class="card">'
            f'<h3>{esc(item.get("label", "未命名因素"))}<span class="confidence">优先级 {esc(item.get("priority", "未定"))}</span></h3>'
            f'<p><span class="label">功能</span><br>{esc(item.get("function", ""))}</p>'
            f'<p><span class="label">适用条件</span><br>{esc(item.get("conditions", ""))}</p>'
            f'<p><span class="label">失效条件</span><br>{esc(item.get("failure_conditions", ""))}</p>'
            f'<p><span class="label">副作用</span><br>{esc(item.get("side_effects", ""))}</p>'
            "</article>"
        )
    return f'<div class="grid-2">{"".join(chunks)}</div>' if chunks else ""


def render_domains(items: list[dict[str, Any]]) -> str:
    if not items:
        return ""
    ranked = sorted(items, key=lambda item: float(item.get("fit", 0)), reverse=True)
    bars = []
    details = []
    for item in ranked:
        fit = max(0, min(100, int(item.get("fit", 0))))
        name = item.get("name", "未命名领域")
        bars.append(
            f'<div class="fit-row"><span>{esc(name)}</span><div class="fit-track"><div class="fit-fill" style="width:{fit}%"></div></div><span class="fit-score">{fit}</span></div>'
        )
        detail = (
            paras(item.get("mechanism"))
            + labeled_list("适合的任务形态", item.get("suitable_roles"))
            + labeled_list("现实门槛", item.get("prerequisites"))
            + labeled_list("结构风险", item.get("risks"))
            + paras(item.get("evidence_needed"), "note")
        )
        details.append(
            "<details>"
            f'<summary><span>{esc(name)}{confidence(item.get("confidence"))}</span><span class="fit-score">{fit}/100</span></summary>'
            f'<div class="detail-body">{detail}</div></details>'
        )
    return (
        '<div class="callout"><span class="label">报告内相对匹配</span>'
        '<p class="note">以下数值只用于本报告内部排序，不是客观能力测量，也不是职业成功概率。</p>'
        + "".join(bars)
        + "</div>"
        + "".join(details)
    )


def render_cycles(items: list[dict[str, Any]]) -> str:
    chunks = []
    for cycle in items:
        year_cards = []
        for year in cycle.get("years_detail") or []:
            conditions = list_html(year.get("conditions"))
            year_cards.append(
                '<article class="year">'
                f"<strong>{esc(year.get('year', ''))} {esc(year.get('ganzhi', ''))}</strong>"
                f"{confidence(year.get('confidence') or year.get('rating'))}{paras(year.get('summary'))}{conditions}"
                "</article>"
            )
        body = (
            paras(cycle.get("summary"))
            + labeled_list("触发机制", cycle.get("mechanisms"))
            + labeled_list("可利用机会", cycle.get("opportunities"))
            + labeled_list("结构风险", cycle.get("risks"))
            + labeled_list("失败条件", cycle.get("failure_conditions"))
            + (f'<div class="year-grid">{"".join(year_cards)}</div>' if year_cards else "")
        )
        title = f"{cycle.get('name', '')} {cycle.get('ganzhi', '')}".strip()
        chunks.append(
            "<details>"
            '<summary><span class="cycle-head">'
            f'<span>{esc(title)}</span><span class="cycle-years">{esc(cycle.get("years", ""))}</span>{confidence(cycle.get("confidence"))}'
            "</span></summary>"
            f'<div class="detail-body">{body}</div></details>'
        )
    return "".join(chunks)


def render_actions(items: list[dict[str, Any]]) -> str:
    cards = []
    for item in items:
        cards.append(
            '<article class="card">'
            f"<h3>{esc(item.get('title', '建议'))}</h3>{paras(item.get('why'))}"
            f"{list_html(item.get('steps'))}{paras(item.get('tradeoff'), 'note')}</article>"
        )
    return f'<div class="grid-2">{"".join(cards)}</div>' if cards else ""


def validate(data: dict[str, Any]) -> None:
    if not isinstance(data, dict):
        raise ValueError("report root must be an object")
    meta = data.get("meta")
    summary = data.get("summary")
    if not isinstance(meta, dict):
        raise ValueError("meta must be an object")
    if not isinstance(summary, dict):
        raise ValueError("summary must be an object")
    for key in ("title", "analysis_date", "chart_label"):
        if not str(meta.get(key, "")).strip():
            raise ValueError(f"meta.{key} is required")
    for key in ("verdict", "confidence"):
        if not str(summary.get(key, "")).strip():
            raise ValueError(f"summary.{key} is required")


def render(data: dict[str, Any]) -> str:
    validate(data)
    meta = data["meta"]
    summary = data["summary"]
    nav_items: list[tuple[str, str]] = []
    sections: list[str] = []
    number = 1

    def add(section_id: str, title: str, body: str) -> None:
        nonlocal number
        if body.strip():
            nav_items.append((section_id, title))
            sections.append(section(section_id, number, title, body))
            number += 1

    summary_body = (
        f'<p class="lead">{esc(summary.get("verdict"))}</p>'
        f'<div class="callout"><h3>关键机制{confidence(summary.get("confidence"))}</h3>{paras(summary.get("key_mechanism"))}{paras(summary.get("confidence_note"), "note")}</div>'
        f'<div class="card"><h3>最强异议</h3>{paras(summary.get("strongest_objection"))}</div>'
    )
    add("summary", "结论先行", summary_body)

    facts = render_cards(data.get("structure_facts") or [])
    add("chart", "命盘与客观结构", chart_table(data.get("chart") or {}) + facts)
    add("models", "多轨分析与裁决", render_models(data.get("models") or []))
    add("factors", "综合优先因素", render_factors(data.get("priority_factors") or []))
    add("personality", "人格与行为机制", render_cards(data.get("personality") or []))
    add("domains", "学业、能力与职业领域", render_domains(data.get("domains") or []))
    add("themes", "人生主题", render_cards(data.get("themes") or [], title_key="name"))
    add("luck", "大运与重点流年", render_cycles(data.get("luck_cycles") or []))
    add("actions", "现实中的改善路径", render_actions(data.get("actions") or []))
    add("validation", "可验证问题", list_html(data.get("validation_questions") or []))
    add("sources", "来源与方法边界", list_html(data.get("sources") or []))

    nav = "".join(
        f'<a href="#{esc(key)}" data-nav-target="{esc(key)}">{esc(title)}</a>'
        for key, title in nav_items
    )
    meta_rows = [
        ("分析日期", meta.get("analysis_date")),
        ("采用四柱", meta.get("chart_label")),
        ("历法口径", meta.get("calendar_note")),
        ("模型版本", meta.get("model_version")),
    ]
    meta_html = "".join(
        f'<div class="meta-item"><span class="meta-label">{esc(label)}</span>{esc(value or "未提供")}</div>'
        for label, value in meta_rows
    )
    css = CSS_PATH.read_text(encoding="utf-8")
    js = JS_PATH.read_text(encoding="utf-8")
    title = meta.get("title")
    subtitle = meta.get("subtitle") or meta.get("chart_label")
    privacy = meta.get("privacy_note") or "传统命理结构分析；现实决定应结合实际信息。"
    status_tags = "".join(status_badge(item) for item in (meta.get("status_tags") or []))

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>{esc(title)}</title>
  <style>{css}</style>
</head>
<body>
  <div class="reading-progress no-print" aria-hidden="true"><span data-progress></span></div>
  <div class="shell">
    <aside class="sidebar no-print">
      <div class="sidebar-head">
        <p class="brand">BAZI · REPORT</p>
        <button class="menu-toggle" data-action="menu" aria-expanded="false" aria-controls="report-menu">目录</button>
      </div>
      <div class="sidebar-panel" id="report-menu">
        <label class="search-box">
          <span>报告内搜索</span>
          <input type="search" data-search placeholder="例如：调候、表达、职业" autocomplete="off">
          <small data-search-status>共 {len(nav_items)} 个章节</small>
        </label>
        <div class="nav-title">目录</div>
        <nav class="nav">{nav}</nav>
        <div class="tools">
          <button class="tool" data-action="expand">展开全部</button>
          <button class="tool" data-action="collapse">收起全部</button>
          <button class="tool" data-action="top">返回顶部</button>
          <button class="tool tool-primary" data-action="print">打印 / 存为 PDF</button>
        </div>
      </div>
    </aside>
    <main>
      <header class="cover">
        <div class="kicker">BAZI · COMPLETE READING</div>
        <h1>{report_title(title)}</h1>
        <p class="subtitle">{esc(subtitle)}</p>
        <div class="status-row">{status_tags}</div>
        <div class="meta-grid">{meta_html}</div>
      </header>
      <div class="search-empty" data-search-empty hidden>没有找到匹配内容。换一个更短的关键词试试。</div>
      {''.join(sections)}
      <footer class="footer"><p>{esc(privacy)}</p><p>生成日期 {esc(meta.get('analysis_date'))} · {esc(meta.get('model_version') or '未标版本')}</p></footer>
    </main>
  </div>
  <script>{js}</script>
</body>
</html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description="生成统一的交互式八字 HTML 报告")
    parser.add_argument("input", type=Path, help="报告 JSON")
    parser.add_argument("--output", "-o", type=Path, required=True, help="输出 HTML")
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    output = render(data)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(output, encoding="utf-8")
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
