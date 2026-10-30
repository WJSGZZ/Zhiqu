"""图表几何：按科研插图标准检查位置与比例（数值→坐标严格线性、从 0 起、缺值不画成 0、字号不小于约 7pt）。"""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import report  # noqa: E402

NUM = r'(-?\d+(?:\.\d+)?)'


def rects(svg, fill=None):
    out = []
    for m in re.finditer(r'<rect ([^>]*)/>', svg):
        a = dict(re.findall(r'([\w-]+)="([^"]*)"', m[1]))
        if fill is None or a.get('fill') == fill:
            out.append({k: (float(v) if re.fullmatch(NUM, v) else v) for k, v in a.items()})
    return out


def font_sizes(svg):
    return [float(v) for v in re.findall(r'font-size="' + NUM + '"', svg)]


class BarGeometry(unittest.TestCase):
    def test_length_is_proportional_and_starts_at_zero(self):
        svg = report.bar_chart([['甲', 10, '主'], ['乙', 25, '主'], ['丙', 40, '主']], '元')
        bars = [r for r in rects(svg, '#21473E')]
        self.assertEqual(len(bars), 3)
        self.assertTrue(all(b['x'] == report.PLOT_L for b in bars))
        per_unit = [b['width'] / v for b, v in zip(bars, (10, 25, 40))]
        self.assertAlmostEqual(min(per_unit), max(per_unit), places=3)
        self.assertIn('>0</text>', svg)          # 轴从 0 起并标出
        self.assertIn('40 元</text>', svg)        # 最后一个刻度带单位

    def test_axis_maximum_is_a_tick_and_bars_never_exceed_plot(self):
        svg = report.bar_chart([['甲', 27600, '主']], '元', 30000)
        bar = rects(svg, '#21473E')[0]
        self.assertAlmostEqual(bar['width'], (report.PLOT_R - report.PLOT_L) * 27600 / 30000, places=1)
        self.assertIn('30,000 元</text>', svg)

    def test_missing_value_is_dashed_box_not_zero_bar(self):
        svg = report.bar_chart([['甲', 5, '主'], ['乙', None]])
        self.assertIn('未取到', svg)
        dashed = [r for r in rects(svg) if r.get('stroke-dasharray')]
        self.assertEqual(len(dashed), 1)
        self.assertEqual(dashed[0]['fill'], 'none')

    def test_legend_lists_only_tags_present_in_fixed_order(self):
        svg = report.bar_chart([['a', .2, '保'], ['b', .5, '冲']], maximum=1, palette=report.CERTAINTY,
                               legend={'冲': '冲', '稳': '稳', '保': '保'})
        labels = re.findall(r'font-size="9.5" fill="#6E776E">(冲|稳|保)</text>', svg)
        self.assertEqual(labels, ['冲', '保'])


class IntervalGeometry(unittest.TestCase):
    def test_positions_are_linear_in_score(self):
        svg = report.interval_chart([['甲', 360, 400, None], ['乙', 380, 390, None]])
        segs = [tuple(map(float, m)) for m in re.findall(r'<line x1="' + NUM + '" x2="' + NUM + '"[^>]*stroke-width="7"', svg)]
        (a1, a2), (b1, b2) = segs[:2]                # 之后是图例里的样例线
        per = (a2 - a1) / 40
        self.assertAlmostEqual((b1 - a1) / 20, per, places=2)
        self.assertAlmostEqual((b2 - b1) / 10, per, places=2)
        self.assertIn(' 分</text>', svg)            # 轴带单位

    def test_common_reference_point_is_drawn_once(self):
        svg = report.interval_chart([['甲', 360, 400, 380], ['乙', 370, 395, 380]])
        self.assertEqual(svg.count('对照 380 分'), 1)
        mixed = report.interval_chart([['甲', 360, 400, 380], ['乙', None, None, None]])
        self.assertNotIn('对照 380 分', mixed)       # 缺区间的一行不应被一条贯穿线暗示有对照点


class StrategyGeometry(unittest.TestCase):
    def test_bars_use_fixed_zero_to_hundred_scale(self):
        svg = report.strategy_chart([('甲', 50, 0, True), ('乙', 25, 0, False)], fmt=lambda p: '0')
        widths = [r['width'] for r in rects(svg) if r.get('fill') in ('#21473E', '#CEC6B1')]
        self.assertAlmostEqual(widths[0], 2 * widths[1], places=2)   # 没有最小宽度，不按最大值拉满
        self.assertIn('100 分</text>', svg)
        with self.assertRaises(ValueError):
            report.strategy_chart([('甲', 120, 0, True)])


class StripGeometry(unittest.TestCase):
    def test_segment_widths_equal_probabilities(self):
        items = [('a', .5), ('b', .3), ('c', .0015), ('d', .1985)]
        svg = report.outcome_strip(items, 0.0, width=640)
        widths = [r['width'] for r in rects(svg) if r.get('y') == 0]
        self.assertEqual(len(widths), 4)
        for w, (_, p) in zip(widths, items):
            self.assertAlmostEqual(w, 638 * p, places=1)   # 画布 640，左右各留 1
        self.assertIn('太窄未标号：第 3 志愿', svg)

    def test_tiny_fall_risk_is_exact_and_annotated(self):
        svg = report.outcome_strip([('a', .9995)], .0005, fall_text='0.1%')
        red = rects(svg, '#9B3B2E')[0]
        self.assertAlmostEqual(red['width'], 638 * .0005, places=2)
        self.assertIn('红色：滑档 0.1%', svg)


class TimelineGeometry(unittest.TestCase):
    def test_nodes_are_linear_in_months_and_same_month_stays_in_band(self):
        rows = [['2026.10', '甲', '', ''], ['2026.10', '乙', '', ''], ['2027.01', '丙', '', ''], ['2027.07', '丁', '', '检查点']]
        svg = report.timeline(rows)
        xs = [float(v) for v in re.findall(r'<circle cx="' + NUM + '"', svg)]
        diamond = [float(v) for v in re.findall(r'<path d="M' + NUM + ' ', svg)]
        xs = xs[:3] + diamond[:1]                 # 图例里的标记在后，正文节点在前
        band = 600 / (2027 * 12 + 6 - (2026 * 12 + 9) + 1 + 1)
        center = (xs[0] + xs[1]) / 2
        self.assertLess(abs(xs[1] - xs[0]), band)                     # 同月两项都在这个月的格子里
        self.assertAlmostEqual((xs[2] - center) / 3, (xs[3] - xs[2]) / 6, places=3)  # 月份等比例
        self.assertIn('同月事项在该月内按先后错开', svg)

    def test_labels_on_same_level_do_not_overlap(self):
        rows = [[f'2026.{m:02d}', f'事项{m}', f'说明{m}', ''] for m in range(1, 13)]
        svg = report.timeline(rows)
        boxes = []
        for m in re.finditer(r'<text x="' + NUM + '" y="' + NUM + '"><tspan font-weight="600" fill="#21473E">([^<]*)</tspan><tspan[^>]*>([^<]*)</tspan>', svg):
            x, y, when, task = float(m[1]), float(m[2]), m[3], m[4]
            boxes.append((x, y, x + report._text_width(when + '  ' + task, 10)))
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                if a[1] == b[1]:
                    self.assertTrue(a[2] <= b[0] or b[2] <= a[0], (a, b))

    def test_fuzzy_dates_draw_one_line_per_item(self):
        svg = report.timeline([['2026 年底', '甲', '说明甲', ''], ['毕业后 3 个月内', '乙', '说明乙', '检查点']])
        self.assertIn('间距不代表时长', svg)
        self.assertEqual(len(re.findall(r'<text x="124"', svg)), 2)   # 事项与说明同一行，不出现一串短行


class Typography(unittest.TestCase):
    def test_minimum_font_size_prints_at_least_7pt(self):
        svgs = [report.bar_chart([['甲', 3, '主']], '元', legend={'主': '甲'}),
                report.interval_chart([['甲', 1, 2, 1.5, 0, 3, 1.4, 1.2]]),
                report.strategy_chart([('甲', 50, 0, True)], fmt=lambda p: '0'),
                report.outcome_strip([('a', .5), ('b', .49)], .01),
                report.timeline([['2026.01', '甲', '说明', ''], ['2027.03', '乙', '说明', '检查点']])]
        pt_per_unit = 174 / 25.4 * 72 / 640
        for svg in svgs:
            self.assertGreaterEqual(min(font_sizes(svg) + [10]) * pt_per_unit, 7.0)

    def test_probability_never_prints_as_certain(self):
        self.assertEqual(report.pct(.9996), '&gt; 99%')
        self.assertEqual(report.pct(.99996, 1), '&gt; 99.9%')
        self.assertEqual(report.pct(.994), '99%')
        self.assertEqual(report.prob_formatter('B')(1.0), '&gt; 95%')

    def test_strategy_caption_does_not_rank_what_display_cannot_distinguish(self):
        shown = lambda p: f'{p:.1%}'
        cap = report.strategy_caption(50.34, .00075, (50.32, .001), (50.31, .00075), shown)
        self.assertNotIn('更高', cap)
        self.assertNotIn('浪费', cap)

    def test_matrix_rejects_cells_without_state(self):
        with self.assertRaises(ValueError):
            report.comparison_matrix(['资格'], [['考研', '待核']])


if __name__ == '__main__':
    unittest.main()


class NewComponents(unittest.TestCase):
    FLOW = [['A', '步骤', '先试方向', '>B'], ['B', '判断', '仍然喜欢？', '是>C', '否>F'],
            ['C', '结果', '国内考研主线', '>D'], ['F', '备选', '回本专业或工作'],
            ['D', '判断', '预算与英语都够？', '是>E', '否>G'], ['E', '结果', '并行港澳'], ['G', '备选', '只走国内']]

    def test_flow_main_path_goes_straight_down_and_side_ends_share_the_row(self):
        svg = report.flow(self.FLOW)
        boxes = {m[5]: (float(m[1]), float(m[2]), float(m[3]), float(m[4])) for m in re.finditer(
            r'<rect x="' + NUM + '" y="' + NUM + '" width="' + NUM + '" height="' + NUM + r'"[^>]*/><text[^>]*>([^<]*)</text>', svg)}
        a, c = boxes['先试方向'], boxes['国内考研主线']
        self.assertAlmostEqual(a[0] + a[2] / 2, c[0] + c[2] / 2, places=1)      # 主线同一列
        f = boxes['回本专业或工作']
        self.assertGreater(f[0], c[0] + c[2])                                       # 侧向终点在右侧
        for i, (n1, b1) in enumerate(boxes.items()):                               # 方框互不重叠
            for n2, b2 in list(boxes.items())[i + 1:]:
                self.assertFalse(b1[0] < b2[0] + b2[2] and b2[0] < b1[0] + b1[2] and b1[1] < b2[1] + b2[3] and b2[1] < b1[1] + b1[3], (n1, n2))
        self.assertIn('要核实的判断', svg)

    MERGE = [['A', '步骤', '报名', '>B'], ['B', '判断', '过院线？', '过了>D', '没过>E'],
             ['D', '步骤', '准备复试', '>H'], ['E', '判断', '过国家线？', '过了>F', '没过>G'],
             ['H', '判断', '复试通过？', '通过>I', '没通过>F'], ['I', '结果', '拟录取'],
             ['F', '备选', '调剂或春招'], ['G', '备选', '春招']]

    def test_flow_two_parents_enter_target_separately_with_arrows(self):
        svg = report.flow(self.MERGE)
        boxes = {m[5]: (float(m[1]), float(m[2]), float(m[3]), float(m[4])) for m in re.finditer(
            r'<rect x="' + NUM + '" y="' + NUM + '" width="' + NUM + '" height="' + NUM + r'"[^>]*/><text[^>]*>([^<]*)</text>', svg)}
        x, y, w, h = boxes['调剂或春招']
        tips = [(float(m[1]), float(m[2])) for m in re.finditer(r'L' + NUM + ' ' + NUM + r'Z" fill', svg)]
        on_top = [p for p in tips if abs(p[1] - y) < 0.6 and x - 0.6 <= p[0] <= x + w + 0.6]
        on_side = [p for p in tips if abs(p[0] - x) < 0.6 and y - 0.6 <= p[1] <= y + h + 0.6]
        self.assertEqual(len(on_top), 1)      # 正上方的父节点从顶边进入
        self.assertEqual(len(on_side), 1)     # 另一条从左侧边进入，各自带箭头
        # 两条入边的折线互不重合：侧入那条的竖段在方框左外侧，不与顶入竖线共线
        legs = [m for m in re.finditer(r'<path d="M([^"]+)" fill="none"', svg)]
        verticals = set()
        for m in legs:
            pts = [tuple(map(float, s.strip().split())) for s in m[1].split('L')]
            for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
                if abs(x1 - x2) < 0.01:
                    seg = (round(x1, 1), min(y1, y2), max(y1, y2))
                    for v in verticals:
                        if v[0] == seg[0]: self.assertFalse(v[1] < seg[2] - 0.5 and seg[1] < v[2] - 0.5, '两条连线在中途重合')
                    verticals.add(seg)

    def test_flow_rejects_cycles_and_unknown_targets(self):
        with self.assertRaises(ValueError):
            report.flow([['A', '步骤', '甲', '>B'], ['B', '步骤', '乙', '>A']])
        with self.assertRaises(ValueError):
            report.flow([['A', '步骤', '甲', '>Z']])

    def test_stack_segments_are_proportional_on_shared_axis(self):
        svg = report.stack([['三单元', [('政治', 100), ('外语', 100), ('专业课', 300)]],
                            ['四单元', [('政治', 100), ('外语', 100), ('课一', 150), ('课二', 150)]]], '分')
        segs = [r for r in rects(svg) if r.get('height') == 18]
        first = segs[:3]
        self.assertAlmostEqual(first[2]['width'], 3 * first[0]['width'], places=1)
        self.assertAlmostEqual(sum(s['width'] for s in first), sum(s['width'] for s in segs[3:]), places=1)
        self.assertEqual(svg.count('合计 500 分'), 2)

    def test_stack_names_every_narrow_segment(self):
        # 读研旗舰模考图曾在“英语一”段只写分数，读者对不上科目。
        svg = report.stack([['十月模考', [('政治', 63), ('英语一', 62), ('数学一', 105), ('专业课', 119)]],
                            ['单科最低要求', [('政治', 35), ('英语一', 35), ('数学一', 53), ('专业课', 53)]]], '分')
        texts = re.findall(r'>([^<>]*)</text>', svg)
        joined = ''.join(texts)
        for row, segs in (('十月模考', ('政治 63', '英语一 62', '数学一 105', '专业课 119')),
                          ('单科最低要求', ('政治 35', '英语一 35', '数学一 53', '专业课 53'))):
            for seg in segs:
                self.assertIn(seg, joined, (row, seg))
        self.assertIn('十月模考：左起第2段为 英语一 62', joined)
        self.assertIn('单科最低要求：从左到右依次为 政治 35、英语一 35、数学一 53、专业课 53', joined)
        # 写得下的段不重复写进图下说明
        self.assertNotIn('数学一 105；', joined.split('段内未写全的分项：')[-1])
        wide = report.stack([['三单元', [('政治', 100), ('外语', 100), ('专业课', 300)]]], '分')
        self.assertNotIn('段内未写全', wide)

    def test_facts_mark_unknown_as_unfilled(self):
        html_ = report.facts([['年级', '大二', '已知'], ['排名', '', '未知'], ['均分', '80', '待确认']])
        self.assertIn('class="fact unknown"><b>排名</b><span>未填</span>', html_)
        self.assertIn('class="fact pending"', html_)
        with self.assertRaises(ValueError):
            report.facts([['年级', '大二', '大概']])

    def test_cost_keeps_currencies_on_separate_axes_and_missing_not_zero(self):
        out = report.cost_chart([['港', 183960, '港币'], ['澳', 174000, '澳门元'], ['国内', None, '人民币']])
        self.assertEqual(out.count('<svg'), 3)
        self.assertIn('没有按汇率折算', out)
        self.assertIn('未取到', out)
        self.assertIn('200,000 港币', out)
        self.assertIn('200,000 澳门元', out)

    def test_cost_uses_one_axis_for_aliases_but_separates_period_and_scale(self):
        out = report.cost_chart([['现金', 9000, '元'], ['扣后', 1800, '人民币']])
        self.assertEqual(out.count('<svg'), 1)
        widths = [r['width'] for r in rects(out, '#21473E')]
        self.assertAlmostEqual(widths[0], 5 * widths[1], places=1)
        separate = report.cost_chart([['月租', 1200, '元/月'], ['年费', 1200, '元/年'], ['总额', 1.2, '万元']])
        self.assertEqual(separate.count('<svg'), 3)
        self.assertIn('计价周期各用自己的刻度', separate)
        aliases = report.cost_chart([['月租', 1200, '元每月'], ['房租', 900, '人民币/月'], ['学费', 8000, '元/生·年']])
        self.assertEqual(aliases.count('<svg'), 2)

    def test_cost_rejects_unsupported_units_and_rows_instead_of_autoscaling_them(self):
        for unit in ('预算', '结余', '', '月', '元/预算', '元/预算/月', '元/月每年', '元每月/年', '元每月每年', '元/年每月'):
            with self.subTest(unit=unit), self.assertRaisesRegex(ValueError, '第三列'):
                report.cost_chart([['现金', 9000, unit]])
        for row in (['现金', 9000], ['现金', 9000, '元', '9000元', '被忽略的第五列']):
            with self.subTest(row=row), self.assertRaisesRegex(ValueError, '每行'):
                report.cost_chart([row])
        for value in (True, -1, float('nan'), float('inf')):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, '有限非负'):
                report.cost_chart([['现金', value, '元']])

    def test_evidence_grid_uses_badge_levels_only(self):
        svg = report.evidence_grid([('甲大学', [('收费', '官方'), ('就业', '未取到')]), ('乙大学', [('收费', '推测')])])
        self.assertIn('未查', svg)          # 乙大学没有“就业”一项
        with self.assertRaises(ValueError):
            report.evidence_grid([('甲', [('收费', '很好')])])


class Fences(unittest.TestCase):
    def test_cost_rejects_silently_ignored_options(self):
        import render_report as rr
        for option in ('max: 9000', 'unit: 元', 'percent: 是'):
            with self.subTest(option=option), self.assertRaisesRegex(ValueError, '费用图不支持选项'):
                rr.render_fence('cost', '现金', ['caption: 同口径对比', 'source: 1', option, '- 现金 | 9000 | 元'])


    def test_new_fences_render_through_shared_components(self):
        import render_report as rr
        md = '\n'.join(['::: stack 初试构成', 'caption: 说明', 'source: 1', 'unit: 分', '- 三单元 | 政治 100 | 外语 100 | 专业课 300', ':::',
                        '::: facts 现状', 'caption: 说明', 'source: 1', '- 年级 | 大二 | 已知', '- 排名 |  | 未知', ':::',
                        '::: cost 学费', 'caption: 说明', 'source: 1', '- 港 | 183,960 | 港币 | 183,960 港币', '- 国内 | 未取到 | 人民币', ':::',
                        '::: flow 分路', 'caption: 说明', 'source: 1', '- A | 步骤 | 先试 | >B', '- B | 判断 | 喜欢？ | 是>C | 否>D', '- C | 结果 | 考研', '- D | 备选 | 工作', ':::'])
        out, _ = rr.markdown_to_html(md)
        self.assertEqual(out.count('<figure class="fig">'), 4)
        self.assertIn('合计 500 分', out)
        self.assertIn('fact unknown', out)
        self.assertIn('未取到', out)
        self.assertIn('要核实的判断', out)


def _extent_errors(svg):
    """每个图形元素（含描边一半）和每段文字（按估算宽度）都在 viewBox 内。"""
    W, H = map(float, re.search(r'viewBox="0 0 ' + NUM + ' ' + NUM + '"', svg).groups())
    body = re.sub(r'<title>.*?</title>', '', svg)
    errs = []
    def check(x0, y0, x1, y1, what):
        if x0 < -0.01 or y0 < -0.01 or x1 > W + 0.01 or y1 > H + 0.01:
            errs.append(f'{what} 出界：({x0:.1f},{y0:.1f})—({x1:.1f},{y1:.1f})，画布 {W}×{H}')
    for tag, attrs in re.findall(r'<(rect|circle|line|path|text)\b([^>]*)>', body):
        a = dict(re.findall(r'([\w-]+)="([^"]*)"', attrs))
        sw = float(a.get('stroke-width', 1 if a.get('stroke') not in (None, 'none') else 0)) / 2
        f = lambda k: float(a[k])
        if tag == 'rect':
            check(f('x') - sw, f('y') - sw, f('x') + f('width') + sw, f('y') + f('height') + sw, 'rect')
        elif tag == 'circle':
            r = f('r') + sw; check(f('cx') - r, f('cy') - r, f('cx') + r, f('cy') + r, 'circle')
        elif tag == 'line':  # 平头线：描边只向线的两侧扩，不沿线方向伸长
            sx = sw if f('x1') == f('x2') else 0; sy = sw if f('y1') == f('y2') else 0
            check(min(f('x1'), f('x2')) - sx, min(f('y1'), f('y2')) - sy, max(f('x1'), f('x2')) + sx, max(f('y1'), f('y2')) + sy, 'line')
        elif tag == 'path':
            pts = [float(v) for v in re.findall(NUM, a.get('d', ''))]
            xs, ys = pts[0::2], pts[1::2]
            check(min(xs) - sw, min(ys) - sw, max(xs) + sw, max(ys) + sw, 'path')
        elif tag == 'text':
            size = float(a.get('font-size', 10))
            m = re.search(r'<text\b' + re.escape(attrs) + r'>(.*?)</text>', body)
            content = re.sub(r'<[^>]+>', '', m[1]) if m else ''
            w = report._text_width(content, size); x = f('x')
            x0 = {'start': x, 'middle': x - w / 2, 'end': x - w}[a.get('text-anchor', 'start')]
            check(x0, f('y') - size * .8, x0 + w, f('y') + size * .25, 'text「' + content[:8] + '」')
    return errs


class InsideViewBox(unittest.TestCase):
    def test_every_chart_keeps_marks_and_strokes_inside(self):
        charts = {
            'bar': report.bar_chart([['甲', 3, '冲'], ['乙', None], ['丙', 7, '保']], '元', legend={'冲': '冲', '保': '保'}, palette=report.CERTAINTY),
            'interval': report.interval_chart([['甲', 1, 2, 1.5, 0, 3, 1.4, 1.2], ['乙', 1, 2, 1.7]]),
            'interval_common': report.interval_chart([['甲', 360, 400, 380], ['乙', 370, 395, 380]]),
            'strategy': report.strategy_chart([('甲', 50, 0, True), ('乙', 100, .02, False)], fmt=lambda p: f'{p:.1%}'),
            'strip': report.outcome_strip([('a', .5), ('b', .3), ('c', .002), ('d', .197)], .001, fall_text='0.1%'),
            'timeline': report.timeline([['2026.10', '甲', '说明', '检查点'], ['2026.10', '乙', '说明', ''], ['2027.06', '丙', '说明', '']]),
            'sequence': report.timeline([['2026 年底', '甲', '说明', '检查点'], ['毕业后', '乙', '说明', '']]),
            'flow': report.flow(NewComponents.FLOW),
            'stack': report.stack([['三单元', [('政治', 100), ('外语', 100), ('专业课', 300)]]], '分'),
            'grid': report.evidence_grid([('甲大学', [('收费', '官方'), ('就业', '未取到')])]),
            'cost': report.bar_chart([['港', 183960, '主', '183,960 港币'], ['国内', None]], '港币'),
        }
        for name, svg in charts.items():
            self.assertEqual(_extent_errors(svg), [], name)


class AppendixReadability(unittest.TestCase):
    """第 12 节核对附录是给人和 AI 逐条核对的：不印 JSON、字段路径、英文键名和工具名。"""
    def test_leaks_are_detected_but_urls_and_attachments_are_not(self):
        bad = '<p>/education/expected_graduation；所在节 meta；挂科（fail_count）；gdut-retest：50%；方式：curl</p>'
        self.assertEqual(set(report.appendix_leaks(bad)), {'/education/expected_graduation', 'expected_graduation', 'meta', 'curl', 'fail_count', 'gdut-retest'})
        ok = '<p>https://yz.chsi.com.cn/zsml/a_b/c；附件 calculations.json；IELTS；CET-6；SHA256</p>'
        self.assertEqual(report.appendix_leaks(ok), [])

    def test_appendix_refuses_untranslated_labels(self):
        with self.assertRaises(ValueError):
            report.verification_appendix_html({'personal_inputs': [{'label': '/education/expected_graduation', 'value': '2029-06-30', 'sections': '02'}]})

    def test_compound_answers_read_as_chinese(self):
        import verify_report
        self.assertEqual(verify_report.readable_value({'fail': '有，尚未通过', 'fail_count': '1'}), '有，尚未通过；1 门')
        self.assertEqual(verify_report.section_names({'01', 'meta', '07'}), '01、07、封面')
        self.assertEqual(verify_report.readable_value({'四级': 518, '六级': 446}), '四级 518；六级 446')
        self.assertEqual(verify_report.readable_value({'unknown_english_key': 5}), '其他 5')

    def test_current_compound_career_fields_keep_specific_labels(self):
        import verify_report
        value={'major_name':'软件工程','major_code':{'专业代码或学科门类':'080902'}}
        self.assertEqual(verify_report.readable_value(value),'专业名称 软件工程；代码与辅修信息 专业代码或学科门类 080902')
        self.assertEqual(verify_report.readable_value({'job_stage':'还没开始','has_offer':'没有'}),'求职进度 还没开始；录用通知 没有')

    def test_current_grade_composite_keeps_marks_and_ranking_distinct(self):
        import verify_report
        self.assertEqual(verify_report.readable_value({'gpa':'82/100','rank_in_major':'未核实'}),'均分或绩点原答 82/100；专业排名原答 未核实')
        self.assertEqual(verify_report.readable_value({'gpa':'3.2/4','rank_in_major':None}),'均分或绩点原答 3.2/4')
        self.assertEqual(verify_report.readable_value({'gpa':'82','rank':'未知'}),'其他 82；其他 未知')
        from types import SimpleNamespace
        case=SimpleNamespace(data={'profile_parse.json':{'fields':[{'field':'均分或排名'}]}})
        self.assertEqual(verify_report.readable_path(case,'p','/fields/0/value/gpa'),'均分或排名（均分或绩点原答）')

    def test_shared_conditions_and_table_rows_print_once_each(self):
        html_ = report.verification_appendix_html({
            'shared_conditions': ['挂科先处理'],
            'limitations': [{'kind': 'candidate', 'name': '甲路', 'claim': '不利', 'reason': '支持', 'change_if': '改判'},
                            {'kind': 'candidate', 'name': '乙路', 'claim': '不利', 'reason': '支持', 'change_if': '改判'},
                            {'kind': 'table', 'section': '09', 'pairs': [('如果发生', '没过'), ('为什么改变判断', '影响毕业'), ('怎么应对', '先保毕业')]},
                            {'kind': 'table', 'section': '09', 'pairs': [('如果发生', '没钱'), ('为什么改变判断', '前提没了'), ('怎么应对', '退出')]}],
            'gaps': []})
        self.assertEqual(html_.count('挂科先处理'), 1)
        self.assertIn('第 09 节 · 如果发生：没过', html_)
        self.assertIn('第 09 节 · 如果发生：没钱', html_)
        self.assertIn('<p>怎么应对：先保毕业</p>', html_)

    def test_calculation_prints_only_registered_result(self):
        rows = [{'path': '/a', 'label': '合计', 'result': 500, 'formula': '100 + 400', 'sections': '11'},
                {'calculation_path': '/a', 'value': '500', 'label': '合计'},
                {'path': '/b', 'label': '占比', 'result': 0.6, 'formula': '300 ÷ 500', 'sections': '01'},
                {'calculation_path': '/b', 'value': '60%', 'label': '占比'}]
        html_ = report.verification_appendix_html({'numbers': rows, 'gaps': []})
        self.assertNotIn('正文显示 500', html_)
        self.assertNotIn('正文显示', html_)
        self.assertIn('<td>60%</td>', html_)
        self.assertNotIn('<td>0.6</td>', html_)


class ReaderFacingReportCorrections(unittest.TestCase):
    def test_diagram_text_is_at_least_body_small_size_when_printed(self):
        import xml.etree.ElementTree as ET
        drawings = [report.flow([['a', '步骤', '核实条件', '>b'], ['b', '结果', '保留主线']]),
                    report.timeline([['2027.01', '核实条件', '本人检查', '检查点'], ['2027.06', '再作比较', '核实费用']]),
                    report.timeline([['毕业前', '核实条件', '本人检查', '检查点']])]
        for svg in drawings:
            root = ET.fromstring(svg)
            def walk(node, inherited=report.FS):
                size = float(node.attrib.get('font-size', inherited))
                if node.tag.rsplit('}', 1)[-1] in ('text', 'tspan'):
                    # 174mm is the actual A4 content width; the diagrams use 640 SVG units.
                    self.assertGreaterEqual(size * 174 / 25.4 * 72 / 640, 8.5)
                for child in node:walk(child, size)
            walk(root)

    def test_nested_numeric_display_is_not_repeated_in_appendix(self):
        html_ = report.verification_appendix_html({'numbers': [
            {'path': '/years', 'result': 3, 'formula': '36 ÷ 12', 'label': '学制'},
            {'calculation_path': '/years', 'value': '3.0（正文另写作3）', 'label': '学制'}]})
        self.assertIn('<td>3.0</td>', html_)
        self.assertNotIn('正文显示', html_)
        self.assertNotIn('正文另写作', html_)
        self.assertNotIn('calculations.json', html_)
        self.assertIn('PDF 附带的计算明细', html_)

    def test_negative_budget_gap_keeps_sign_despite_absolute_body_format(self):
        rendered=report.verification_appendix_html({'numbers':[
            {'path':'/gap','result':-1600,'formula':'30000 - 31600','label':'预算余量'},
            {'calculation_path':'/gap','value':'1,600','label':'缺口大小'}]})
        self.assertIn('<td>-1600</td>',rendered)
        self.assertNotIn('<td>1,600</td>',rendered)

    def test_rounded_quartile_uses_single_registered_display(self):
        from verify_report import calculation_display_values
        rows=[{'path':'/q1','result':347.75,'value':347.75,'formula':'linear interpolation'},
              {'calculation_path':'/q1','value':'347.8'}]
        self.assertEqual(calculation_display_values(rows)['/q1'],'347.8')
        rendered=report.verification_appendix_html({'numbers':rows})
        self.assertEqual(rendered.count('<td>347.8</td>'),1)
        self.assertNotIn('<td>347.75</td>',rendered)

    def test_case_information_uses_reader_facing_version_label(self):
        import verify_report
        info = dict(verify_report.case_info({'case_id': 'fixture', 'data_commit': 'test-v1'}, {'sha256': '0' * 64}))
        self.assertEqual(info['所用资料版本'], 'test-v1')
        self.assertNotIn('数据快照版本', info)


class DiagramWrappingAtReaderFont(unittest.TestCase):
    def test_three_column_branch_reflows_without_smaller_type(self):
        rows=[['A','步骤','先找少量愿做的企业技术岗位，取招聘原文','>B'],
              ['B','判断','有愿做且符合条件的具体岗位？','是>C','否>D'],
              ['C','结果','比较工作内容与按期到手的现金'],
              ['D','判断','电网浙江单位或国考有具体可报职位？','是>E','否>F'],
              ['E','备选','按该职位准备，同时算好等待期现金'],
              ['F','备选','暂停新增投入，重核方向']]
        svg=report.flow(rows)
        self.assertIn('viewBox="0 0 640',svg)
        import xml.etree.ElementTree as ET
        text=''.join(ET.fromstring(svg).itertext())
        for row in rows:self.assertIn(row[2],text)
        self.assertTrue(all(value>=report.DIAGRAM_SMALL for value in font_sizes(svg)[1:]))
