"""Local macOS Vision only. OCR text and image bytes never leave memory.

``recognize_regions`` batches crops in one cached Swift process. Regions and
returned ``bbox`` use original-image, top-left pixel coordinates (x0,y0,x1,y1).
``region_text`` is a convenience for PDF's independent rendered-cell check.
``dual_read_cells`` compares a whole-image reading against fixed original-cell
crops; it never combines the best cells of inconsistent readings. Its returned
text is private working memory: callers must persist anonymous summaries only.
The injectable backend receives image bytes and normalized pixel regions, and
returns Vision-style normalized bottom-left boxes; it enables offline tests.
Vision confidence is not a calibrated accuracy probability. The fixed .25
minimum was locked using anonymous local calibration before real-school trials:
correct Chinese headings scored .3/.5 while digits scored 1.0. Exact complete
two-reading comparison and the separate sample comparison remain mandatory.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import tempfile
import time


class VisionUnavailable(ValueError):
    """Missing local capability; messages never include source contents."""


class VisionMismatch(ValueError):
    """A complete reading or its geometry could not be verified."""


SWIFT_SOURCE = r'''import Foundation
import Vision
import ImageIO
import CoreGraphics
func perform() throws {
 let input = FileHandle.standardInput.readDataToEndOfFile()
 guard let obj = try JSONSerialization.jsonObject(with: input) as? [String:Any],
       let encoded = obj["image"] as? String, let bytes = Data(base64Encoded: encoded),
       let source = CGImageSourceCreateWithData(bytes as CFData, nil),
       let image = CGImageSourceCreateImageAtIndex(source, 0, nil),
       let regions = obj["regions"] as? [[Double]] else { throw NSError(domain:"input",code:1) }
 var output: [[[String:Any]]] = []
 for a in regions {
  guard a.count == 4, let crop = image.cropping(to: CGRect(x:a[0],y:a[1],width:a[2]-a[0],height:a[3]-a[1])) else { throw NSError(domain:"region",code:1) }
  let request = VNRecognizeTextRequest()
  request.recognitionLevel = (obj["level"] as? String == "fast") ? .fast : .accurate
  request.recognitionLanguages = ["zh-Hans","en-US"]
  request.usesLanguageCorrection = obj["correction"] as? Bool ?? false
  try VNImageRequestHandler(cgImage:crop,orientation:.up,options:[:]).perform([request])
  var rows: [[String:Any]] = []
  for observation in request.results ?? [] {
   guard let candidate = observation.topCandidates(1).first else { continue }
   let b = observation.boundingBox
   var chars: [[String:Any]] = []
   let text = candidate.string
   var index = text.startIndex
   while index < text.endIndex {
    let next = text.index(after:index)
    if let rectangle = try? candidate.boundingBox(for:index..<next) {
     let r = rectangle.boundingBox
     chars.append(["text":String(text[index..<next]),"rect":[r.minX,r.minY,r.width,r.height]])
    }
    index = next
   }
   rows.append(["text":text,"confidence":Double(candidate.confidence),"rect":[b.minX,b.minY,b.width,b.height],"chars":chars])
  }
  output.append(rows)
 }
 let data = try JSONSerialization.data(withJSONObject:["regions":output],options:[.sortedKeys])
 FileHandle.standardOutput.write(data)
}
do { try perform() } catch {
 FileHandle.standardOutput.write(Data("{\"error\":\"vision_failed\"}".utf8))
 exit(2)
}
'''


def normalized(text):
    """Whitespace only; never repair OCR digits, punctuation, or programme codes."""
    return ''.join(str(text).split())


def _tick(deadline):
    if deadline is not None:
        deadline()


def _remaining(deadline, fallback=60):
    _tick(deadline)
    seconds = deadline.remaining() if hasattr(deadline, 'remaining') else fallback
    if seconds <= 0:
        raise TimeoutError('本机识别期限已到')
    return min(float(seconds), fallback)


def _run(args, data, deadline, maximum=60):
    """Capture private stdout/stderr in RAM and reap the whole child group."""
    _tick(deadline)
    try:
        process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True)
    except OSError:
        raise VisionUnavailable('本机识别进程不可用') from None
    try:
        stdout, _ = process.communicate(data, timeout=_remaining(deadline, maximum))
    except (subprocess.TimeoutExpired, TimeoutError):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()
        raise TimeoutError('本机识别超时，未保存识别正文') from None
    if process.returncode:
        raise VisionUnavailable('本机识别未完成，未保存进程诊断正文')
    _tick(deadline)
    return stdout


def _helper_binary(cache_dir=None, deadline=None):
    if platform.system() != 'Darwin' or not shutil.which('swiftc'):
        raise VisionUnavailable('需要macOS Vision与本机Swift编译器')
    import fcntl
    root = Path(cache_dir) if cache_dir else Path(__file__).resolve().parents[3] / '.cache/kaoyan-pdf-auto/vision'
    root.mkdir(parents=True, exist_ok=True)
    source_hash = hashlib.sha256(SWIFT_SOURCE.encode()).hexdigest()
    source = root / ('vision-'+source_hash+'.swift')
    binary = root / ('vision-'+source_hash)
    receipt = binary.with_suffix('.json')
    with (root/'compile.lock').open('a') as lock:
        # Nonblocking retry keeps a concurrent first-use compilation interruptible.
        while True:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                _tick(deadline)
                time.sleep(.05)
        for p in (source, binary, receipt):
            if p.is_symlink():
                raise VisionUnavailable('本机识别缓存不是普通文件')
        if source.exists() and hashlib.sha256(source.read_bytes()).hexdigest() != source_hash:
            raise VisionUnavailable('本机识别源码指纹不符')
        if binary.exists() and receipt.exists():
            try:
                metadata = json.loads(receipt.read_text())
            except (OSError, ValueError):
                raise VisionUnavailable('本机识别缓存证明不可用') from None
            if metadata.get('source_sha256') != source_hash or metadata.get('binary_sha256') != hashlib.sha256(binary.read_bytes()).hexdigest():
                raise VisionUnavailable('本机识别缓存指纹不符')
            return binary
        source.write_text(SWIFT_SOURCE)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(prefix='vision-build-', dir=root, delete=False) as f:
                temporary = Path(f.name)
            _run([shutil.which('swiftc'), '-O', str(source), '-o', str(temporary)], None, deadline, maximum=90)
            os.replace(temporary, binary)
            metadata = dict(source_sha256=source_hash, binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(), raw_images_written=False)
            receipt.write_text(json.dumps(metadata, sort_keys=True)+'\n')
            return binary
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def _image_info(image_bytes):
    from PIL import Image
    if not isinstance(image_bytes, bytes) or len(image_bytes) > 50_000_000:
        raise VisionMismatch('图像类型或大小不适合本机核验')
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            width, height = image.size
            if width < 1 or height < 1 or width*height > 80_000_000 or getattr(image, 'n_frames', 1) != 1:
                raise VisionMismatch('图像范围或帧数不适合自动核验')
            if image.getexif().get(274, 1) != 1:
                raise VisionMismatch('图像方向尚未独立确认')
            image.load()
    except VisionMismatch:
        raise
    except Exception:
        raise VisionMismatch('图像不可解码') from None
    return width, height


def _region(region, size):
    width, height = size
    if region is None:
        return (0, 0, width, height)
    if len(region) != 4 or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in region):
        raise VisionMismatch('图像区域坐标无效')
    x0, y0, x1, y1 = region
    if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
        raise VisionMismatch('图像区域超出原件')
    return (math.floor(x0), math.floor(y0), math.ceil(x1), math.ceil(y1))


def _pixel_box(rect, region):
    if len(rect) != 4 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in rect):
        raise VisionMismatch('识别文字坐标无效')
    x, y, width, height = rect
    if x < -.001 or y < -.001 or width < 0 or height < 0 or x+width > 1.001 or y+height > 1.001:
        raise VisionMismatch('识别文字超出原区域')
    x0, y0, x1, y1 = region
    return [x0+x*(x1-x0), y0+(1-y-height)*(y1-y0),
            x0+(x+width)*(x1-x0), y0+(1-y)*(y1-y0)]


def recognize_regions(image_bytes, regions, *, mode='accurate', correction=False,
                      deadline=None, backend=None, cache_dir=None, min_confidence=.25):
    """Return region/text/normalized/tokens in RAM, with absolute top-left boxes.

    ``backend`` is an offline-test callable accepting
    (image_bytes, regions=..., level=..., correction=..., deadline=...). It returns
    one raw-token list per region, using Vision's bottom-left normalized ``rect``.
    """
    _tick(deadline)
    if mode not in {'accurate', 'fast'} or not 0 <= min_confidence <= 1:
        raise ValueError('本机识别设置无效')
    size = _image_info(image_bytes)
    boxes = [_region(r, size) for r in regions]
    if not boxes:
        return []
    if backend is None:
        binary = _helper_binary(cache_dir, deadline)
        request = json.dumps(dict(image=base64.b64encode(image_bytes).decode(), regions=boxes,
                                  level=mode, correction=bool(correction))).encode()
        data = _run([str(binary)], request, deadline)
        try:
            raw = json.loads(data)['regions']
        except (KeyError, TypeError, ValueError):
            raise VisionUnavailable('本机识别返回格式未通过') from None
    else:
        raw = backend(image_bytes, regions=boxes, level=mode, correction=correction, deadline=deadline)
    if not isinstance(raw, list) or len(raw) != len(boxes):
        raise VisionMismatch('识别区域数量不一致')
    output = []
    for region, rows in zip(boxes, raw):
        _tick(deadline)
        tokens = []
        for token in rows:
            try:
                text, confidence = token['text'], float(token['confidence'])
                if not isinstance(text, str) or not math.isfinite(confidence) or not min_confidence <= confidence <= 1:
                    raise VisionMismatch('识别置信度未通过')
                chars = [dict(text=c['text'], bbox=_pixel_box(c['rect'], region)) for c in token.get('chars', [])]
                if chars and normalized(''.join(c['text'] for c in chars)) != normalized(text):
                    raise VisionMismatch('识别字符定位不完整')
                tokens.append(dict(text=text, confidence=confidence, bbox=_pixel_box(token['rect'], region), chars=chars))
            except VisionMismatch:
                raise
            except (KeyError, TypeError, OverflowError, ValueError):
                raise VisionMismatch('识别文字定位格式未通过') from None
        tokens.sort(key=lambda t: (round(t['bbox'][1]/3), t['bbox'][0]))
        text = '\n'.join(t['text'] for t in tokens)
        output.append(dict(region=list(region), text=text, normalized=normalized(text), tokens=tokens))
    return output


def recognize(image_bytes, *, region=None, **kwargs):
    return recognize_regions(image_bytes, [region], **kwargs)[0]['tokens']


def region_text(image_bytes, region=None, **kwargs):
    return recognize_regions(image_bytes, [region], **kwargs)[0]


def _contained(inner, outer, tolerance=1):
    return inner[0] >= outer[0]-tolerance and inner[1] >= outer[1]-tolerance and inner[2] <= outer[2]+tolerance and inner[3] <= outer[3]+tolerance


def dual_read_cells(image_bytes, cells, *, deadline=None, backend=None, cache_dir=None,
                    min_confidence=.25, table_region=None):
    """Whole-image character boxes vs every fixed cell crop; all cells must agree.

    ``cells``: [{cell_id: anonymous locator, bbox: [x0,y0,x1,y1]}, ...]. Caller
    obtains grid geometry independently of OCR. No relevant non-space character
    within table_region (default: cells' bounding rectangle) may go unassigned.
    The same Vision engine uses two fixed segmentations; this is not claimed to
    be independent model training. A third sample can use region_text with a
    separately rendered/cropped image or different mode/correction settings.
    """
    size = _image_info(image_bytes)
    if not cells or len({c['cell_id'] for c in cells}) != len(cells):
        raise VisionMismatch('原图格子定位不完整')
    boxes = [_region(c['bbox'], size) for c in cells]
    table = _region(table_region, size) if table_region is not None else (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
    for i, a in enumerate(boxes):
        for b in boxes[i+1:]:
            if min(a[2],b[2]) > max(a[0],b[0]) and min(a[3],b[3]) > max(a[1],b[1]):
                raise VisionMismatch('原图格子区域重叠')
    whole = region_text(image_bytes, deadline=deadline, backend=backend, cache_dir=cache_dir, min_confidence=min_confidence)
    first = [[] for _ in cells]
    for token in whole['tokens']:
        chars = token['chars']
        if not chars and normalized(token['text']):
            if len(token['text']) != 1:
                raise VisionMismatch('整图文字缺逐字符位置，不能可靠分格')
            chars = [dict(text=token['text'], bbox=token['bbox'])]
        for char in chars:
            if not normalized(char['text']):
                continue
            box = char['bbox'];cx, cy = (box[0]+box[2])/2, (box[1]+box[3])/2
            # A partially intersecting character at a table edge is relevant
            # too: dropping it in both readings could otherwise hide clipping.
            if min(box[2],table[2]) <= max(box[0],table[0]) or min(box[3],table[3]) <= max(box[1],table[1]):
                continue
            owners = [i for i,b in enumerate(boxes) if b[0] <= cx < b[2] and b[1] <= cy < b[3] and _contained(box,b)]
            if len(owners) != 1:
                raise VisionMismatch('整图文字跨格或有未覆盖原格，整份不入')
            first[owners[0]].append(char)
    second = recognize_regions(image_bytes, boxes, deadline=deadline, backend=backend,
                               cache_dir=cache_dir, min_confidence=min_confidence)
    readings = []
    for cell, chars, cropped in zip(cells, first, second):
        # Preserve the recognized sequence inside each line. Glyph ink tops
        # differ (e.g. 码 vs 专); sorting individual glyphs by minY reorders text.
        text = ''.join(c['text'] for c in chars)
        if normalized(text) != cropped['normalized']:
            raise VisionMismatch('图片完整双读有格不一致，整份不入')
        readings.append(dict(cell_id=cell['cell_id'], bbox=list(cell['bbox']), text=text, normalized=normalized(text), second_text=cropped['text']))
    if not any(r['normalized'] for r in readings):
        raise VisionMismatch('未识别到可核对文字')
    return dict(ok=True, cells=readings, checked_cells=len(readings), whole_tokens=whole['tokens'],
                methods=['macOS Vision accurate full-image character geometry', 'macOS Vision accurate fixed original-cell crops'],
                raw_images_written=False, raw_ocr_logged=False)
