"""In-memory, two-parser HTML table geometry; no semantic mapping or persistence.

Only outermost tables are returned. Nested tables and their text are excluded.
Coordinates in ``anchors`` are 1-based physical tr/cell positions. A genuinely
absent slot in a ragged table has text ``''`` and anchor ``[0, 0]``. Rowspans may
continue across tbody sections, but never across separate tables or documents.
Encoding: explicit UTF-8/GBK/GB2312/GB18030, or strict UTF-8 then GB18030 when
undeclared. Conflicting declarations and undecodable input are rejected.
"""
from html.parser import HTMLParser
import re
import unicodedata
import warnings

from bs4 import (BeautifulSoup, NavigableString, MarkupResemblesLocatorWarning,
                 XMLParsedAsHTMLWarning)
from lxml import html, etree

_ERROR = 'HTML表格结构或双读核对失败'
_MAX_BYTES = 10 * 1024 * 1024
_MAX_ROWS = 20000
_MAX_SPAN = 1000
_MAX_COLUMNS = 2000
_MAX_SLOTS = 200000


def _norm(value):
    return ' '.join(unicodedata.normalize('NFKC', value).split())


def _decode(body):
    if not isinstance(body, bytes) or len(body) > _MAX_BYTES:
        raise ValueError(_ERROR)
    declarations = re.findall(rb'<meta\b[^>]*>', body, re.I)
    encodings = []
    aliases = {'utf8': 'utf-8', 'utf-8': 'utf-8', 'gbk': 'gb18030',
               'gb2312': 'gb18030', 'gb18030': 'gb18030'}
    for tag in declarations:
        for label in re.findall(rb'charset\s*=\s*[\"\x27]?\s*([a-zA-Z0-9_-]+)', tag, re.I):
            encoding = aliases.get(label.decode('ascii').lower())
            if encoding is None:
                raise ValueError(_ERROR)
            encodings.append(encoding)
    bom = body.startswith(b'\xef\xbb\xbf')
    if len(set(encodings)) > 1 or (bom and encodings and encodings[0] != 'utf-8'):
        raise ValueError(_ERROR)
    if encodings:
        result = body.decode('utf-8-sig' if bom else encodings[0], errors='strict')
    else:
        try:
            result = body.decode('utf-8-sig', errors='strict')
        except UnicodeDecodeError:
            result = body.decode('gb18030', errors='strict')
    if '\x00' in result or '\ufffd' in result:
        raise ValueError(_ERROR)
    return result


class _StructureGuard(HTMLParser):
    """Reject missing/duplicate structural tags before either parser repairs them."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            if self.stack and not self.stack[-1][1]:
                raise ValueError(_ERROR)
            self.stack.append([False, False])
        elif tag == 'tr':
            if not self.stack or self.stack[-1][0]:
                raise ValueError(_ERROR)
            self.stack[-1][0] = True
        elif tag in ('td', 'th'):
            if not self.stack or not self.stack[-1][0] or self.stack[-1][1]:
                raise ValueError(_ERROR)
            keys = [k for k, _ in attrs if k in ('rowspan', 'colspan')]
            if len(keys) != len(set(keys)):
                raise ValueError(_ERROR)
            self.stack[-1][1] = tag

    def handle_endtag(self, tag):
        if tag == 'table':
            if not self.stack or self.stack[-1][0]:
                raise ValueError(_ERROR)
            self.stack.pop()
        elif tag == 'tr':
            if not self.stack or not self.stack[-1][0] or self.stack[-1][1]:
                raise ValueError(_ERROR)
            self.stack[-1][0] = False
        elif tag in ('td', 'th'):
            if not self.stack or self.stack[-1][1] != tag:
                raise ValueError(_ERROR)
            self.stack[-1][1] = False

    def handle_startendtag(self, tag, attrs):
        if tag in ('table', 'tr', 'td', 'th'):
            raise ValueError(_ERROR)


def _span(raw):
    if not isinstance(raw, str) or not re.fullmatch(r'[1-9][0-9]{0,3}', raw.strip()):
        raise ValueError(_ERROR)
    value = int(raw)
    if value > _MAX_SPAN:
        raise ValueError(_ERROR)
    return value


def _lxml_text(cell):
    parts = [cell.text or '']
    for child in cell:
        if isinstance(child.tag, str) and child.tag.lower() not in ('table', 'script', 'style'):
            parts.append(_lxml_text(child))
        parts.append(child.tail or '')
    return ''.join(parts)


def _lxml_tables(text):
    doc = html.fromstring(text, parser=html.HTMLParser(no_network=True))
    result = []
    for table in doc.xpath('descendant-or-self::table[not(ancestor::table)]'):
        trs = [tr for tr in table.xpath('.//tr') if tr.xpath('ancestor::table[1]')[0] is table]
        if len(trs) > _MAX_ROWS:
            raise ValueError(_ERROR)
        occupied = {}
        for ri, tr in enumerate(trs, 1):
            column = 1
            for ci, cell in enumerate(tr.xpath('./td|./th'), 1):
                while (ri, column) in occupied:
                    column += 1
                rs, cs = _span(cell.get('rowspan', '1')), _span(cell.get('colspan', '1'))
                if ri + rs - 1 > len(trs) or column + cs - 1 > _MAX_COLUMNS:
                    raise ValueError(_ERROR)
                value = _norm(_lxml_text(cell))
                for rr in range(ri, ri + rs):
                    for cc in range(column, column + cs):
                        if (rr, cc) in occupied or len(occupied) >= _MAX_SLOTS:
                            raise ValueError(_ERROR)
                        occupied[rr, cc] = (value, [ri, ci])
                column += cs
        width = max((cc for _, cc in occupied), default=0)
        if len(trs) * width > _MAX_SLOTS:
            raise ValueError(_ERROR)
        rows, anchors = [], []
        for ri in range(1, len(trs) + 1):
            rows.append([occupied.get((ri, col), ('', [0, 0]))[0] for col in range(1, width + 1)])
            anchors.append([occupied.get((ri, col), ('', [0, 0]))[1] for col in range(1, width + 1)])
        if len(trs) * width > _MAX_SLOTS:
            raise ValueError(_ERROR)
        result.append({'table': len(result) + 1, 'rows': rows, 'anchors': anchors, 'physical_rows': len(trs)})
    return result


def _bs4_tables(text):
    # These parser hints can echo source text; diagnostics are deliberately fixed.
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', MarkupResemblesLocatorWarning)
        warnings.simplefilter('ignore', XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(text, 'html.parser')
    result = []
    for table in soup.find_all('table'):
        if table.find_parent('table') is not None:
            continue
        trs = [tr for tr in table.find_all('tr') if tr.find_parent('table') is table]
        if len(trs) > _MAX_ROWS:
            raise ValueError(_ERROR)
        # Separate expansion: fixed-width arrays plus explicit occupied bitmap.
        values = [[] for _ in trs]
        origins = [[] for _ in trs]
        busy = [[] for _ in trs]
        filled = 0
        for r, tr in enumerate(trs):
            col = 0
            for physical_col, cell in enumerate(tr.find_all(['td', 'th'], recursive=False), 1):
                while col < len(busy[r]) and busy[r][col]:
                    col += 1
                down = _span(cell.get('rowspan', '1'))
                across = _span(cell.get('colspan', '1'))
                if r + down > len(trs) or col + across > _MAX_COLUMNS:
                    raise ValueError(_ERROR)
                strings = []
                for node in cell.descendants:
                    if (isinstance(node, NavigableString)
                            and node.find_parent('table') is table
                            and node.find_parent(['script', 'style']) is None
                            and node.__class__.__name__ not in ('Comment', 'Declaration', 'Doctype')):
                        strings.append(str(node))
                value = _norm(''.join(strings))
                for y in range(r, r + down):
                    needed = col + across - len(busy[y])
                    if needed > 0:
                        values[y].extend([''] * needed)
                        origins[y].extend([[0, 0] for _ in range(needed)])
                        busy[y].extend([False] * needed)
                    for x in range(col, col + across):
                        if busy[y][x] or filled >= _MAX_SLOTS:
                            raise ValueError(_ERROR)
                        busy[y][x] = True
                        values[y][x] = value
                        origins[y][x] = [r + 1, physical_col]
                        filled += 1
                col += across
        width = max(map(len, values), default=0)
        if width * len(trs) > _MAX_SLOTS:
            raise ValueError(_ERROR)
        for r in range(len(trs)):
            values[r].extend([''] * (width - len(values[r])))
            origins[r].extend([[0, 0] for _ in range(width - len(origins[r]))])
        result.append({'table': len(result) + 1, 'rows': values, 'anchors': origins, 'physical_rows': len(trs)})
    return result


def html_tables(body: bytes) -> list[dict]:
    """Return agreed table values in RAM; never filter, print, log or save them.

    Invalid input/geometry or any two-parser difference raises a fixed ValueError
    without including source values. Callers own privacy filtering and semantics.
    """
    try:
        text = _decode(body)
        guard = _StructureGuard()
        guard.feed(text)
        guard.close()
        if guard.stack:
            raise ValueError(_ERROR)
        if not text.strip():
            return []
        first = _lxml_tables(text)
        second = _bs4_tables(text)
        if first != second:
            raise ValueError(_ERROR)
        return first
    except (ValueError, UnicodeError, TypeError, OverflowError, RecursionError, IndexError, etree.ParserError):
        raise ValueError(_ERROR) from None
