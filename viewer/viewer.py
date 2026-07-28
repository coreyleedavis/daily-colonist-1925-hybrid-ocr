#!/usr/bin/env python3
"""Phase 2 hybrid viewer — port 8889. Mirador 3 + IIIF v2 manifests +
Content Search API against colonist_phase2, modeled on Phase 1's dialect.
New vs Phase 1: /text/<page> (reading-order plain text) and /json/<page>
(full per-word record: text+box+provenance+alternative). Read-only."""
import glob, json, os, re, urllib.parse, urllib.request
from flask import Flask, jsonify, request

app = Flask(__name__)
BASE = 'http://localhost:8889'
IIIF_IMG = 'http://localhost:8182/iiif/2'
SOLR = 'http://localhost:8983/solr/colonist_phase2/select'
OCRD = os.path.expanduser('~/solr-bridge/ocr-data/phase2')
SIDED = os.path.expanduser('~/solr-bridge/phase2/out')
ALT = '\u21ff'

def _load_stats():
    out = {}
    try:
        p1 = json.load(open(os.path.expanduser('~/solr-bridge/corpus_stats.json')))
        out['tess'] = p1['tesseract']; out['vlm'] = p1['vlm']
    except Exception:
        pass
    try:
        h = json.load(open(os.path.expanduser('~/solr-bridge/phase2/corpus_stats_hybrid.json')))
        out['hybrid'] = h['hybrid']
    except Exception:
        pass
    return out
STATS = _load_stats()

def _abbyy_counts():
    try:
        return json.load(open(os.path.expanduser(
            '~/solr-bridge/phase2/ia_abbyy_counts.json')))
    except Exception:
        return {}

try:
    ISSUE_DATES = json.load(open(os.path.expanduser('~/solr-bridge/.issue_dates.json')))
except Exception:
    ISSUE_DATES = {}
MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June',
               'July', 'August', 'September', 'October', 'November', 'December']

def calendar_html():
    import calendar as _cal
    groups = {}
    for issue, e in ISSUE_DATES.items():
        d = e.get('date')
        key = d[:7] if d else 'zzz-unknown'
        groups.setdefault(key, []).append(issue)
    parts = ['<div style="display:flex;flex-wrap:wrap;gap:14px;margin-top:.5em">']
    for mk in sorted(k for k in groups if k != 'zzz-unknown'):
        y, mo = int(mk[:4]), int(mk[5:7])
        by_day = {}
        for i in groups[mk]:
            e = ISSUE_DATES.get(i, {})
            d = e.get('date')
            if d:
                by_day[int(d[8:10])] = (i, e)
        rows = [f'<table style="border-collapse:collapse;font-size:.78em">'
                f'<tr><th colspan=7 style="padding:2px">{MONTH_NAMES[mo-1]}</th></tr>'
                '<tr>' + ''.join(f'<th style="color:#999;font-weight:normal;padding:1px 3px">{w}</th>'
                                 for w in ('Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa')) + '</tr>']
        _cal.setfirstweekday(_cal.SUNDAY)
        for week in _cal.monthcalendar(y, mo):
            cells = []
            for day in week:
                if day == 0:
                    cells.append('<td></td>')
                elif day in by_day:
                    i, e = by_day[day]
                    n = len(issue_pages(i))
                    tip = f'{n} pages &middot; {i}'
                    if e.get('source') == 'inferred':
                        tip += ' &middot; date inferred'
                    cells.append(f'<td style="padding:1px 3px;text-align:center">'
                                 f'<a href="/view/{i}" title="{tip}">{day}</a></td>')
                else:
                    cells.append(f'<td style="padding:1px 3px;text-align:center;color:#ccc">{day}</td>')
            rows.append('<tr>' + ''.join(cells) + '</tr>')
        rows.append('</table>')
        parts.append(''.join(rows))
    parts.append('</div>')
    return ''.join(parts)
_CALENDAR = None
def get_calendar():
    global _CALENDAR
    if _CALENDAR is None:
        _CALENDAR = calendar_html()
    return _CALENDAR


def solr(params):
    url = SOLR + '?' + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)

SOLR1 = 'http://localhost:8983/solr/colonist/select'
SOLRA = 'http://localhost:8983/solr/colonist_abbyy/select'
def solra(params):
    url = SOLRA + '?' + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)
def solr1(params):
    url = SOLR1 + '?' + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)

def canvas_id(page):
    return f'{BASE}/canvas/{page}'

_dims_cache = {}
def page_dims(page):
    """Canvas dims MUST match the image service's reality (info.json), not
    our OCR files' idea of it — mismatch breaks OSD's tile handshake and
    skews annotation placement. Cached per page."""
    if page in _dims_cache:
        return _dims_cache[page]
    issue = page.rsplit('_p', 1)[0]
    try:
        url = f'{IIIF_IMG}/{urllib.parse.quote(f"{issue}/{page}.png", safe="")}/info.json'
        with urllib.request.urlopen(url, timeout=10) as r:
            d = json.load(r)
        dims = (d['width'], d['height'])
    except Exception:
        xml_path = f'{OCRD}/{page}.miniocr.xml'
        m = re.search(r'wh="(\d+) (\d+)"', open(xml_path).read(1000)) if os.path.exists(xml_path) else None
        dims = (int(m.group(1)), int(m.group(2))) if m else (7466, 9478)
    _dims_cache[page] = dims
    return dims

def issue_pages(issue):
    return sorted(os.path.basename(f).replace('.miniocr.xml', '')
                  for f in glob.glob(f'{OCRD}/{issue}_p*.miniocr.xml'))

@app.after_request
def cors(resp):
    resp.headers['Access-Control-Allow-Origin'] = '*'
    return resp

# ---------- IIIF manifest (v2, Phase 1 dialect) ----------
@app.route('/manifest/<issue>')
def manifest(issue):
    canvases = []
    for p in issue_pages(issue):
        w, h = page_dims(p)
        canvases.append({'@id': canvas_id(p), '@type': 'sc:Canvas',
            'label': p.split('_p')[-1], 'width': w, 'height': h,
            'images': [{'@type': 'oa:Annotation', 'motivation': 'sc:painting',
                'on': canvas_id(p),
                'resource': {'@id': f'{IIIF_IMG}/{issue}%2F{p}.png/full/full/0/default.jpg',
                    '@type': 'dctypes:Image', 'width': w, 'height': h,
                    'service': {'@context': 'http://iiif.io/api/image/2/context.json',
                        '@id': f'{IIIF_IMG}/{issue}%2F{p}.png',
                        'profile': 'http://iiif.io/api/image/2/level2.json'}}}]})
    return jsonify({'@context': 'http://iiif.io/api/presentation/2/context.json',
        '@id': f'{BASE}/manifest/{issue}', '@type': 'sc:Manifest',
        'label': f'{issue} [hybrid]',
        'service': {'@context': 'http://iiif.io/api/search/1/context.json',
                    '@id': f'{BASE}/search/{issue}',
                    'profile': 'http://iiif.io/api/search/1/search'},
        'sequences': [{'@type': 'sc:Sequence', 'canvases': canvases}]})

# ---------- IIIF Content Search (Phase 1 dialect) ----------
@app.route('/search/<issue>')
def search(issue):
    q = request.args.get('q', '').strip()
    qq = build_q(q)
    r = solr({'q': qq, 'fq': f'id:hybrid_{issue}_p*', 'rows': 30,
              'fl': 'id', 'hl': 'true', 'hl.ocr.fl': 'ocr_text',
              'hl.snippets': 20, 'hl.ocr.absoluteHighlights': 'true'})
    resources, hits = [], []
    for doc_id, hl in r.get('ocrHighlighting', {}).items():
        page = doc_id.replace('hybrid_', '')
        for snip in hl.get('ocr_text', {}).get('snippets', []):
            raw = snip.get('text', '')
            ids_this = []
            for region in snip.get('highlights', [[]]):
                for h in region:
                    x, y = h['ulx'], h['uly']
                    w, hgt = h['lrx'] - x, h['lry'] - y
                    aid = f'{BASE}/anno/{doc_id}/{len(resources)}'
                    resources.append({'@id': aid, '@type': 'oa:Annotation',
                        'motivation': 'sc:painting',
                        'resource': {'@type': 'cnt:ContentAsText',
                                     'chars': h.get('text', q)},
                        'on': f'{canvas_id(page)}#xywh={x},{y},{w},{hgt}'})
                    ids_this.append(aid)
            if ids_this:
                m = re.search('<em>(.*?)</em>', raw)
                hits.append({'@type': 'search:Hit', 'annotations': ids_this,
                    'match': m.group(1) if m else q,
                    'before': re.sub('</?em>', '', raw.split('<em>', 1)[0])[-120:],
                    'after': re.sub('</?em>', '', raw.rsplit('</em>', 1)[-1])[:120]})
    # image-description hits: outline the described image blocks
    try:
        ri = solr({'q': build_q(q, 'image_desc'), 'fq': f'id:hybrid_{issue}_p*',
                   'rows': 30, 'fl': 'id'})
        import glob as _glob
        for doc in ri['response']['docs']:
            page = doc['id'].replace('hybrid_', '')
            jpath = os.path.expanduser(f'~/paddle-year/{issue}/{page}_described.json')
            if not os.path.exists(jpath):
                continue
            pj = json.load(open(jpath))
            jw, jh = pj.get('width', 2560), pj.get('height', 2560)
            cw, ch = page_dims(page)
            fx, fy = cw / jw, ch / jh
            ql = q.lower()
            for b in pj['parsing_res_list']:
                if b['block_label'] not in ('image', 'footer_image'):
                    continue
                desc = (b.get('block_content') or '')
                if ql not in desc.lower():
                    continue
                x0, y0, x1, y1 = b['block_bbox']
                x, y = int(x0 * fx), int(y0 * fy)
                w, hgt = int((x1 - x0) * fx), int((y1 - y0) * fy)
                aid = f'{BASE}/anno/img/{page}/{b["block_id"]}'
                resources.append({'@id': aid, '@type': 'oa:Annotation',
                    'motivation': 'sc:painting',
                    'resource': {'@type': 'cnt:ContentAsText',
                                 'chars': '[image] ' + desc[:120]},
                    'on': f'{canvas_id(page)}#xywh={x},{y},{w},{hgt}'})
                i = desc.lower().index(ql)
                hits.append({'@type': 'search:Hit', 'annotations': [aid],
                    'match': desc[i:i+len(q)],
                    'before': '[image, AI-described] ' + desc[max(0, i-90):i],
                    'after': desc[i+len(q):i+len(q)+90]})
    except Exception:
        pass
    return jsonify({'@context': 'http://iiif.io/api/search/1/context.json',
        '@id': request.url, '@type': 'sc:AnnotationList',
        'resources': resources, 'hits': hits})

# ---------- word records: MiniOCR + sidecar joined (emit order) ----------
def build_q(q, field='ocr_text'):
    """Phase 1's query builder, field-parameterized: date-range rewriting,
    Lucene-syntax passthrough (quotes/wildcards/fuzzy/operators/parens),
    plain words as exact phrase."""
    import calendar as _cal
    def _daterange(m):
        a, b = m.group(1), m.group(2)
        def lo(d):
            if len(d) == 7: d += '-01'
            return d + 'T00:00:00Z'
        def hi(d):
            if len(d) == 7:
                y, mo = int(d[:4]), int(d[5:7])
                d += f'-{_cal.monthrange(y, mo)[1]:02d}'
            return d + 'T23:59:59Z'
        return f'issue_date:[{lo(a)} TO {hi(b)}]'
    q = re.sub(r'issue_date:\[(\d{4}-\d{2}(?:-\d{2})?) TO (\d{4}-\d{2}(?:-\d{2})?)\]',
               _daterange, q)
    q = re.sub(r'issue_date:(\d{4}-\d{2}-\d{2})(?![\dT-])',
               lambda m: f'issue_date:[{m.group(1)}T00:00:00Z TO {m.group(1)}T23:59:59Z]', q)
    if re.search(r'["*?~()\[:]|\b(AND|OR|NOT)\b', q):
        return f'{field}:({q})'
    return f'{field}:"{q}"'

def iiif_id(page):
    issue = page.rsplit('_p', 1)[0]
    return urllib.parse.quote(f'{issue}/{page}.png', safe='')

def image_descs(page):
    """[(description, crop_url, [x,y,w,h] canvas-space), ...] from the paddle
    JSON (desc + bbox from the same block — no cross-source joining)."""
    issue = page.rsplit('_p', 1)[0]
    jpath = os.path.expanduser(f'~/paddle-year/{issue}/{page}_described.json')
    if not os.path.exists(jpath):
        return []
    try:
        pj = json.load(open(jpath))
        jw, jh = pj.get('width', 2560), pj.get('height', 2560)
        cw, ch = page_dims(page)
        fx, fy = cw / jw, ch / jh
        out = []
        for b in pj['parsing_res_list']:
            if b['block_label'] not in ('image', 'footer_image'):
                continue
            desc = (b.get('block_content') or '').strip()
            if not desc:
                continue
            x0, y0, x1, y1 = b['block_bbox']
            x, y = max(0, int(x0 * fx)), max(0, int(y0 * fy))
            w, hgt = int((x1 - x0) * fx), int((y1 - y0) * fy)
            crop = (f'{IIIF_IMG}/{iiif_id(page)}/{x},{y},{w},{hgt}/'
                    f'!400,400/0/default.jpg')
            out.append((desc, crop, [x, y, w, hgt]))
        return out
    except Exception:
        return []

def word_records(page):
    xml = open(f'{OCRD}/{page}.miniocr.xml').read()
    side = json.load(open(f'{SIDED}/{page}.provenance.json'))
    recs, blocks, wi = [], [], 0
    for b in re.finditer(r'<b>(.*?)</b>', xml, re.S):
        lines = []
        for l in re.finditer(r'<l>(.*?)</l>', b.group(1), re.S):
            words = []
            for wm in re.finditer(r'<w x="([\d\- ]+)">([^<]*)</w>', l.group(1)):
                x, y, w, h = (int(v) for v in wm.group(1).split())
                raw = wm.group(2)
                txt, alt = (raw.split(ALT, 1) + [None])[:2]
                prov = side[wi]['prov'] if wi < len(side) else '?'
                words.append({'text': txt, 'alt': alt, 'x': x, 'y': y,
                              'w': w, 'h': h, 'provenance': prov})
                wi += 1
            lines.append(words)
        blocks.append(lines)
    return blocks

@app.route('/json/<page>')
def page_json(page):
    if not re.match(r'^[A-Za-z0-9_]+$', page): return 'bad id', 400
    try:
        blocks = word_records(page)
    except FileNotFoundError:
        return 'no such page', 404
    W, H = page_dims(page)
    return jsonify({'page': page, 'width': W, 'height': H,
        'coordinate_space': 'full-resolution page pixels',
        'provenance_legend': {
            'agree': 'both engines read identically; Tesseract box',
            'punct': 'differ only in punctuation/quotes; VLM text, Tesseract box',
            'vlm-routed': 'Tesseract low-confidence or truncated; VLM text',
            'vlm-dict': 'dictionary vote for VLM reading',
            'tess-dict': 'dictionary vote for Tesseract reading; VLM as alternative',
            'residual-alt': 'unresolved; VLM primary, Tesseract as searchable alternative',
            'multi': 'VLM word spans several Tesseract words; union box',
            'interp': 'no Tesseract counterpart; box interpolated',
            'interp-shrapnel': 'Tesseract counterpart was fragment noise; box interpolated',
            'tess-only': 'Tesseract-only rescue (VLM missed region); measured box',
            'tess-only-lowconf': 'Tesseract-only rescue, low confidence',
            'tess-in-image': 'Tesseract text inside VLM image region'},
        'image_descriptions': {
            'note': 'AI-generated by Qwen2.5-VL; describes images on the page; not printed text; may contain errors',
            'descriptions': [{'text': d_, 'box_canvas': bx} for d_, _, bx in image_descs(page)]},
        'blocks': blocks})

@app.route('/text/<page>')
def page_text(page):
    if not re.match(r'^[A-Za-z0-9_]+$', page): return 'bad id', 400
    plain = request.args.get('plain') == '1'
    try:
        blocks = word_records(page)
    except FileNotFoundError:
        return 'no such page', 404
    issue = page.rsplit('_p', 1)[0]
    STYLE = {
        'agree': '', 'punct': 'border-bottom:2px dotted #9ab',
        'vlm-routed': 'color:#1a4d8f',
        'vlm-dict': 'color:#1a4d8f;border-bottom:2px solid #1a4d8f',
        'tess-dict': 'color:#7a4d12;border-bottom:2px solid #7a4d12',
        'residual-alt': 'background:#ffe9b0',
        'multi': 'border-bottom:2px dashed #888',
        'interp': 'color:#8a8a8a',
        'interp-shrapnel': 'color:#8a8a8a;font-style:italic',
        'tess-only': 'background:#d9efd7',
        'tess-only-lowconf': 'background:#eef5ed;color:#567',
        'tess-in-image': 'background:#e7e0f2'}
    DESC = {
        'agree': 'Both OCR engines read this word identically, so there&#8217;s no doubt about the text. The highlight box is Tesseract&#8217;s measured position on the page. This is the highest-confidence class.',
        'punct': 'The two engines differ only in punctuation or quotation style &#8212; straight versus curly quotes, a comma versus a period. The displayed text follows the vision-language model; the box is Tesseract&#8217;s measured position. Effectively agreement.',
        'vlm-routed': 'The engines disagreed, but Tesseract admitted weakness: its own confidence score was below 50, or its reading was just a fragment of the VLM&#8217;s word (like &#8216;FR&#8217; against &#8216;FREE&#8217;). The VLM&#8217;s text is used; the box is still Tesseract&#8217;s measured position.',
        'vlm-dict': 'The engines disagreed and both seemed confident, so a dictionary was consulted: only the VLM&#8217;s reading is a real word (e.g. &#8216;railway&#8217; vs &#8216;rallway&#8217;). The VLM&#8217;s text is used; the box is Tesseract&#8217;s measured position.',
        'tess-dict': 'The engines disagreed and the dictionary sided with Tesseract: only its reading is a real word. Tesseract&#8217;s text is displayed &#8212; but the VLM&#8217;s reading is still indexed invisibly, so searching either spelling finds this page. The box is measured.',
        'residual-alt': 'A genuine coin-flip: the engines disagreed and nothing could break the tie &#8212; both readings are plausible (like &#8216;Rafters&#8217; vs &#8216;Ratters&#8217;). The VLM&#8217;s reading is displayed; Tesseract&#8217;s (marked \u21ff) is indexed at the same position, so searching either spelling finds this page.',
        'multi': 'One word in the VLM&#8217;s reading lines up with several of Tesseract&#8217;s words &#8212; usually a spacing or hyphenation difference. The VLM&#8217;s text is used; the box is the combined outline of the Tesseract words.',
        'interp': 'Tesseract, the classical OCR engine, produced nothing for this word &#8212; it skipped or failed on this part of the page. The text comes entirely from the vision-language model. Because Tesseract normally supplies each word&#8217;s pixel coordinates, this word has no measured position: its highlight box is an estimate, spread evenly along the line. A page with many interp words shows where Tesseract went blind.',
        'interp-shrapnel': 'Tesseract produced only garbled fragments here &#8212; shattered pieces of large display type, like &#8216;OFGREATLINE|&#8217;. Matching against garbage would be misleading, so its output was set aside. The text is the VLM&#8217;s; the box is an estimate; no alternative reading is indexed.',
        'tess-only': 'A rescue. The vision-language model missed this region entirely &#8212; it never transcribed it at all. Tesseract did read it, and its words passed confidence checks, so they&#8217;re kept. Text and box both come from Tesseract, and the block is placed into reading order by its physical position on the page. Without this class, this text &#8212; often a headline or an ad &#8212; would be unsearchable.',
        'tess-only-lowconf': 'A rescue like tess-only, but Tesseract&#8217;s confidence in these words was low. They&#8217;re kept so the region stays searchable at all, and flagged: treat the exact spellings with caution.',
        'tess-in-image': 'Words Tesseract read inside a region the VLM classified as a picture &#8212; typically text printed within an advertisement or illustration. Text and measured box both come from Tesseract.'}
    from collections import Counter
    counts = Counter(w['provenance'] for lines in blocks for ln in lines for w in ln)
    paras = []
    for lines in blocks:
        words_html = []
        for ln in lines:
            for w in ln:
                txt = w['text'].replace('<', '&lt;')
                if plain:
                    words_html.append(txt); continue
                k = w['provenance']
                tip = k + (' | alt: ' + w['alt'] if w['alt'] else '') + \
                      f" | box {w['x']},{w['y']} {w['w']}x{w['h']}"
                if w['alt']:
                    txt += '<sup>&#8703;' + w['alt'].replace('<', '&lt;') + '</sup>'
                words_html.append('<span class="w" data-k="' + k + '" style="' +
                                  STYLE.get(k, '') + '" title="' + tip + '">' + txt + '</span>')
        paras.append(' '.join(words_html))
    body = '\n'.join('<p>' + p + '</p>' for p in paras if p.strip())
    if plain:
        return ('<!doctype html><html><head><meta charset="utf-8"><title>' + page + '</title>'
                '<style>body{font-family:Georgia,serif;max-width:52em;margin:2em auto;'
                'padding:0 1em;line-height:1.6}</style></head><body>'
                '<div style="font-size:.85em"><a href="/text/' + page + '">provenance view</a></div>'
                '<h1 style="font-size:1.1em">' + page + '</h1>' + body + '</body></html>')
    chips = ''.join(
        '<button class="chip" data-k="' + k + '"><span style="' + STYLE.get(k, '') + '">' + k +
        '</span> <span class="n">' + str(n) + '</span></button>'
        for k, n in counts.most_common())
    descs = image_descs(page)
    if descs:
        items = ''.join(
            '<div style="display:flex;gap:12px;align-items:flex-start;margin:.8em 0">'
            '<a href="' + cu.replace('!400,400', '!1200,1200') + '" target="_blank">'
            '<img src="' + cu + '" style="max-width:150px;max-height:150px;'
            'border:1px solid #b9c4d4;border-radius:3px;flex-shrink:0"></a>'
            '<p style="margin:0">' + dd.replace('<', '&lt;') + '</p></div>'
            for dd, cu, _ in descs)
        imgdescs_html = ('<details style="margin:.8em 0 1.4em"><summary style="cursor:pointer;'
                         'font-family:-apple-system,Helvetica,sans-serif;font-size:.9em;color:#3b3bb3">'
                         f'Image descriptions on this page ({len(descs)}) '
                         '<span style="font-size:.85em;background:#dce6f5;border-radius:3px;padding:1px 6px;color:#444">'
                         'AI-generated &#8212; not printed text</span></summary>'
                         '<div style="margin-top:.6em;padding:1em;background:#eef2f7;'
                         'border:1px solid #c9d4e3;border-radius:6px;'
                         'font-family:-apple-system,Helvetica,sans-serif;font-size:.9em;line-height:1.55">'
                         + items + '</div></details>')
    else:
        imgdescs_html = ''
    desc_js = json.dumps({k: DESC.get(k, k) for k in counts})
    count_js = json.dumps(dict(counts))
    tpl = '''<!doctype html><html><head><meta charset="utf-8"><title>__PAGE__ — text</title>
<style>
body{font-family:Georgia,serif;max-width:52em;margin:0 auto;padding:0 1em 2em;line-height:1.7}
h1{font-size:1.05em;margin:.8em 0 .4em}
#bar{position:sticky;top:0;z-index:10;background:#fffdf7;border-bottom:1px solid #ddd;
padding:.45em 1em .4em;margin:0 -1em}
.chip{font:inherit;font-size:.78em;border:1px solid #ccc;border-radius:12px;
background:#fff;padding:1px 9px;margin:0 4px 4px 0;cursor:pointer}
.chip .n{color:#999;font-size:.9em}
.chip.on{border-color:#35619e;box-shadow:0 0 0 1px #35619e}
#exp{display:none;font-family:-apple-system,Helvetica,sans-serif;font-size:.8em;
color:#444;background:#f6f4ee;border-radius:4px;padding:.5em .7em;margin-top:.3em;line-height:1.5}
.w{transition:opacity .15s} .dim{opacity:.18}
sup{font-size:.65em;color:#a06f14}
.nav{font-size:.85em;margin:.1em 0 .35em}
</style></head><body>
<div id="bar">
<div class="nav"><a href="/view/__ISSUE__">&larr; viewer</a> ·
<a href="/text/__PAGE__?plain=1">plain text</a> · <a href="/json/__PAGE__">full JSON</a> &middot; <a href="__IMGURL__" target="_blank">full page image</a>
<span style="color:#999">— click a class to explain &amp; isolate</span></div>
__CHIPS__
<div id="exp"></div>
</div>
<h1>__PAGE__ — hybrid text, reading order</h1>
__IMGDESCS__
__BODY__
<script>
var DESC = __DESC__, N = __COUNTS__, active = null;
document.querySelectorAll('.chip').forEach(function(c){
  c.addEventListener('click', function(){
    var k = c.dataset.k, exp = document.getElementById('exp');
    if (active === k) { active = null; exp.style.display = 'none'; }
    else { active = k;
      exp.innerHTML = '<b>' + k + ' \u00b7 ' + N[k] + ' words</b> \u2014 ' + DESC[k];
      exp.style.display = 'block'; }
    document.querySelectorAll('.chip').forEach(function(o){
      o.classList.toggle('on', o.dataset.k === active); });
    document.querySelectorAll('.w').forEach(function(w){
      w.classList.toggle('dim', !!active && w.dataset.k !== active); });
  });
});
</script></body></html>'''
    return (tpl.replace('__PAGE__', page).replace('__ISSUE__', issue)
               .replace('__CHIPS__', chips).replace('__BODY__', body)
               .replace('__DESC__', desc_js).replace('__COUNTS__', count_js)
               .replace('__IMGDESCS__', imgdescs_html)
               .replace('__IMGURL__', f'{IIIF_IMG}/{iiif_id(page)}/full/full/0/default.jpg'))

# ---------- issue metadata for the header ----------
@app.route('/issue_meta/<issue>')
def issue_meta(issue):
    q = request.args.get('q', '').strip()
    n = 0
    if q:
        qq = build_q(q)
        n = solr({'q': qq, 'fq': f'id:hybrid_{issue}_p*', 'rows': 0})['response']['numFound']
    return jsonify({'label': issue, 'pages': len(issue_pages(issue)), 'hits': n})

# ---------- search landing page ----------
@app.route('/')
def home():
    q = request.args.get('q', '').strip()
    mode = request.args.get('mode', 'ink')
    ink_c = 'checked' if mode != 'images' else ''
    img_c = 'checked' if mode == 'images' else ''
    cmp_c = 'checked' if mode == 'compare' else ''
    html = [f'''<!doctype html><html><head><meta charset="utf-8">
<title>Colonist 1925 — Hybrid</title><style>
body{{font-family:Georgia,serif;max-width:960px;margin:0 auto;padding:0 1.2em 3em;color:#191919;line-height:1.5}}
h1{{font-size:1.7em;margin:.9em 0 .1em;font-weight:normal}}
.sub{{color:#666;font-size:.95em;margin:0 0 1em}}
.rule{{border:none;border-top:2px solid #35619e;margin:.6em 0 1.2em}}
.searchrow{{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:.4em 0 .5em}}
input[type=text]{{font-family:Georgia,serif;font-size:1.05em;flex:1;min-width:280px;padding:7px 10px;border:1px solid #b9b6ae;border-radius:4px}}
button{{font-family:Georgia,serif;font-size:1em;padding:7px 16px;border:1px solid #35619e;background:#35619e;color:#fff;border-radius:4px;cursor:pointer}}
.modes{{display:flex;gap:18px;font-size:.92em;color:#444;margin:0 0 1.2em}}
.modes label{{cursor:pointer}}
.tag{{font-size:.72em;background:#dce6f5;border-radius:3px;padding:1px 6px;color:#333}}
.navrow{{font-size:.9em;margin:0 0 1.4em;color:#a09d95}}
.navrow a{{color:#3b3bb3;text-decoration:none}}
.navrow a:hover{{text-decoration:underline}}
details{{margin:.4em 0 1em;font-size:.9em}}
details summary{{cursor:pointer;color:#3b3bb3}}
.hit{{margin:1.1em 0;padding:.9em 1em;border:1px solid #ddd;border-radius:6px}}
.hit a.pg{{font-size:1.05em;color:#246;text-decoration:none}}
.hit a.pg:hover{{text-decoration:underline}}
.hit em{{background:#ffe28a;font-style:normal;font-weight:bold}}
.desc{{color:#345;font-size:.95em;margin:.35em 0;line-height:1.55}}
.links{{font-size:.82em;color:#a09d95;margin-top:.3em}}
.links a{{color:#3b3bb3}}
table.cmp{{border-collapse:collapse;font-size:.95em;margin:.6em 0}}
table.cmp th{{text-align:left;font-weight:normal;color:#666;border-bottom:1px solid #ccc;padding:4px 16px 4px 0}}
table.cmp th.num,table.cmp td.num{{text-align:right;padding:4px 20px 4px 16px}}
table.cmp td{{padding:5px 16px 5px 0;border-bottom:1px solid #eee}}
.note{{color:#a09d95;font-size:.85em}}
a{{color:#246}}
</style></head><body>
<h1>The Daily Colonist, 1925 &#8212; Hybrid Search</h1>
<p class="sub">One index from two readers: a vision-language model&#8217;s text wearing classical OCR&#8217;s word-level geometry &#8212; searchable, highlightable, provenance-tracked.</p>
<hr class="rule">
<form action="/">
<div class="searchrow"><input type="text" name="q" value="{q}" autofocus placeholder="Search all of 1925&#8230;"><button>Search</button></div>
<div class="modes">
<label><input type="radio" name="mode" value="ink" {ink_c}> printed text</label>
<label><input type="radio" name="mode" value="images" {img_c}> images <span class="tag">AI descriptions</span></label>
<label><input type="radio" name="mode" value="compare" {cmp_c}> compare arms</label>
</div></form>''']
    html.append('''<p class="navrow"><a href="/about">About this index</a> &nbsp;&middot;&nbsp; <a href="/corpus">Corpus statistics</a> &nbsp;&middot;&nbsp; <a href="/report">Comparative report</a></p>
<details style="margin:.6em 0 1em;font-size:.9em">
<summary style="cursor:pointer;color:#3b3bb3">Search tips &#8212; phrases, AND/OR/NOT, wildcards, fuzzy</summary>
<table style="font-size:.95em">
<tr><td style="padding:2px 12px 2px 0"><code>beecham pills</code></td><td>plain words search as an exact phrase, in order</td></tr>
<tr><td style="padding:2px 12px 2px 0"><code>beecham AND liver</code></td><td>both words anywhere on the page (operators must be UPPERCASE)</td></tr>
<tr><td style="padding:2px 12px 2px 0"><code>beecham NOT pills</code></td><td>pages with the first word but not the second</td></tr>
<tr><td style="padding:2px 12px 2px 0"><code>(logging OR lumber) AND strike</code></td><td>group alternatives with parentheses</td></tr>
<tr><td style="padding:2px 12px 2px 0"><code>"beecham pills"~5</code></td><td>the words within 5 words of each other &#8212; useful when OCR noise interrupts a phrase</td></tr>
<tr><td style="padding:2px 12px 2px 0"><code>esquimal*</code></td><td>wildcard: any ending &#8212; catches OCR-damaged word endings</td></tr>
<tr><td style="padding:2px 12px 2px 0"><code>beecham~1</code></td><td>fuzzy: within one character &#8212; finds OCR misreads like &#8220;Peecham&#8221;</td></tr>
<tr><td style="padding:2px 12px 2px 0"><code>regatta AND issue_date:[1925-06-01 TO 1925-08-31]</code></td><td>restrict to a date range; months work too: <code>[1925-06 TO 1925-08]</code></td></tr>
</table>
<p style="color:#777;font-size:.9em">Notes: printed-text mode searches the hybrid text only; AI image descriptions are the separate
&#8220;images&#8221; mode above, always labeled. Unresolved OCR disagreements are indexed under both readings, so either spelling finds
the page. Possessives and accents are normalized; modern spellings match 1925 forms (tomorrow = to-morrow). Wildcard and fuzzy
matches may highlight imperfectly on the page image.</p></details>''')
    if STATS.get('hybrid'):
        t, v, h_ = STATS.get('tess', {}), STATS.get('vlm', {}), STATS['hybrid']
        def _r(d, k): return f"{d[k]:,}" if k in d else '&#8212;'
        html.append(f'''<details style="margin:.4em 0 1em;font-size:.9em">
<summary style="cursor:pointer;color:#3b3bb3">Corpus statistics &#8212; Tesseract vs VLM vs Hybrid</summary>
<table style="font-size:.95em;border-collapse:collapse;margin:.5em 0">
<tr><th style="text-align:left;padding:2px 14px 2px 0"></th><th style="padding:2px 14px;text-align:right">Tesseract</th>
<th style="padding:2px 14px;text-align:right">VLM</th><th style="padding:2px 14px;text-align:right"><b>Hybrid</b></th></tr>
<tr><td>words</td><td style="text-align:right">{_r(t,"total_words")}</td><td style="text-align:right">{_r(v,"total_words")}</td><td style="text-align:right"><b>{_r(h_,"total_words")}</b></td></tr>
<tr><td>unique forms</td><td style="text-align:right">{_r(t,"unique")}</td><td style="text-align:right">{_r(v,"unique")}</td><td style="text-align:right"><b>{_r(h_,"unique")}</b></td></tr>
<tr><td>dictionary-recognized</td><td style="text-align:right">{t.get("recognized_pct","&#8212;")}%</td><td style="text-align:right">{v.get("recognized_pct","&#8212;")}%</td><td style="text-align:right"><b>{h_.get("recognized_pct","&#8212;")}%</b></td></tr>
<tr><td>pages</td><td style="text-align:right">{_r(t,"pages")}</td><td style="text-align:right">{_r(v,"pages")}</td><td style="text-align:right"><b>6,641</b></td></tr>
</table>
<p style="color:#777;font-size:.9em">Same methodology across all three columns (&#8805;4-char tokens vs the corpus-derived 1925
lexicon, frequency &#8805;3). Tesseract&#8217;s unique-forms figure is dominated by OCR damage (621,822 forms exclusive to it).
Phase 1 text-search counts for the VLM arm were inflated by AI image descriptions mixed into page text (e.g. railway: 2,717
conflated vs 2,636 ink-only); this index keeps them structurally separate. Full statistics (suspect-form lists, per-arm comparisons) on the <a href="/corpus">corpus page</a>; build details on the <a href="/about">about page</a>.</p>
</details>''')
    html = [h for h in html if h is not None]
    html.append('<details style="margin:.4em 0 1em;font-size:.9em">'
                '<summary style="cursor:pointer;color:#3b3bb3">Browse by date &#8212; 1925 publication calendar</summary>'
                + get_calendar() + '</details>')
    if q:
        if mode == 'compare':
            qq = build_q(q)
            qd = build_q(q, 'image_desc')
            rows = []
            try:
                n = solr1({'q': qq + ' AND source:tesseract', 'rows': 0})['response']['numFound']
                rows.append(('Tesseract (Phase 1)', n, '', f'http://localhost:8888/findall?q={urllib.parse.quote(q)}'))
            except Exception:
                rows.append(('Tesseract (Phase 1)', None, 'phase 1 core unreachable', ''))
            try:
                n = solr1({'q': qq + ' AND source:paddleocr-vl', 'rows': 0})['response']['numFound']
                rows.append(('VLM (Phase 1)', n,
                             'count includes AI image descriptions mixed into page text', 
                             f'http://localhost:8888/findall?q={urllib.parse.quote(q)}'))
            except Exception:
                rows.append(('VLM (Phase 1)', None, 'phase 1 core unreachable', ''))
            ia_url = ('https://archive.org/details/dailycolonist?query=' +
                      urllib.parse.quote(q) + '&sin=TXT&and%5B%5D=' +
                      urllib.parse.quote('year:"1925"'))
            try:
                n_a = solra({'q': qq, 'rows': 0})['response']['numFound']
                rows.append(('ABBYY (Internet Archive, ~2015)', n_a,
                             f'local index, 312/312 issues &middot; '
                             f'<a target=\"_blank\" href=\"{ia_url}\">view at archive.org</a>', ''))
            except Exception:
                rows.append(('ABBYY (Internet Archive, ~2015)', None, 'abbyy core unreachable', ''))
            n_h = solr({'q': qq, 'rows': 0})['response']['numFound']
            rows.append(('Hybrid', n_h, '', f'/?q={urllib.parse.quote(q)}&mode=ink'))
            n_i = solr({'q': qd, 'rows': 0})['response']['numFound']
            rows.append(('Image descriptions', n_i, 'AI-generated; separate field, never counted as page text',
                         f'/?q={urllib.parse.quote(q)}&mode=images'))
            html.append(f'<h2 style="font-size:1.05em">Pages matching &#8220;{q}&#8221; by arm</h2>')
            html.append('<table class="cmp">')
            html.append('<tr><th>arm</th><th class="num">pages</th><th></th></tr>')
            for name, n, note, link in rows:
                nn = f'{n:,}' if n is not None else '&#8212;'
                bold = ' style="font-weight:bold"' if name == 'Hybrid' else ''
                lk = f' <a style="font-size:.85em" href="{link}">view</a>' if link and n else ''
                nt = f' <span style="color:#a09d95;font-size:.85em">{note}</span>' if note else ''
                html.append(f'<tr><td{bold}>{name}{nt}</td>'
                            f'<td{bold} class="num">{nn}</td><td>{lk}</td></tr>')
            html.append('</table>')
            html.append('<p style="color:#777;font-size:.85em">Counts are pages with at least one match. '
                        'Phase 1 links open the comparison testbed on port 8888.</p>')
            html.append('''<script>
function abbyyGo() {
  var cell = document.getElementById('abbyy-cell');
  var q = new URLSearchParams(location.search).get('q');
  cell.innerHTML = 'starting&#8230;';
  fetch('/abbyy_compute', {method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'},
        body:'q=' + encodeURIComponent(q)})
    .then(function(r){ return r.json(); })
    .then(function(d){
      if (!d.ok && d.msg) { cell.innerHTML = d.msg; return; }
      cell.innerHTML = 'querying the Internet Archive (312 issues, 1 request/second)&#8230;';
      var t = setInterval(function(){
        fetch('/abbyy_status?q=' + encodeURIComponent(q))
          .then(function(r){ return r.json(); })
          .then(function(s){
            if (s.state === 'done') { clearInterval(t); location.reload(); }
            else if (s.state === 'running' && s.progress) { cell.innerHTML = 'computing&#8230; ' + s.progress; }
          });
      }, 3000);
    });
}
</script>''')
        elif mode == 'images':
            d = solr({'q': build_q(q, 'image_desc'), 'rows': 25, 'fl': 'id',
                      'hl': 'true', 'hl.fl': 'image_desc', 'hl.fragsize': 160})
            html.append(f"<p>{d['response']['numFound']} pages with matching image descriptions "
                        f"<span class='tag'>AI-generated by Qwen2.5-VL — may contain errors</span></p>")
            hls = d.get('highlighting', {})
            for doc in d['response']['docs']:
                pid = doc['id']; page = pid.replace('hybrid_', '')
                issue = page.rsplit('_p', 1)[0]
                html.append(f'<div class="hit"><a class="pg" href="/view/{issue}?canvas={page}&q={urllib.parse.quote(q)}">{page}</a>')
                for fr in hls.get(pid, {}).get('image_desc', [])[:3]:
                    html.append(f'<div class="desc">{fr}</div>')
                html.append(f'<div class="links"><a href="/text/{page}">text</a> · <a href="/json/{page}">json</a></div></div>')
        else:
            qq = build_q(q)
            d = solr({'q': qq, 'rows': 25, 'fl': 'id', 'hl': 'true',
                      'hl.ocr.fl': 'ocr_text', 'hl.snippets': 2})
            html.append(f"<p>{d['response']['numFound']} pages of printed text match</p>")
            ohl = d.get('ocrHighlighting', {})
            for doc in d['response']['docs']:
                pid = doc['id']; page = pid.replace('hybrid_', '')
                issue = page.rsplit('_p', 1)[0]
                html.append(f'<div class="hit"><a class="pg" href="/view/{issue}?q={urllib.parse.quote(q)}">{page}</a>')
                for s in ohl.get(pid, {}).get('ocr_text', {}).get('snippets', [])[:2]:
                    t = s['text'].replace('<em>', '§').replace('</em>', '¤')
                    t = t.replace('<', '&lt;').replace('§', '<em>').replace('¤', '</em>')
                    html.append(f'<div class="desc">…{t}…</div>')
                html.append(f'<div class="links"><a href="/text/{page}">text</a> · <a href="/json/{page}">json</a></div></div>')
    html.append('</body></html>')
    return ''.join(html)

# ---------- on-the-fly ABBYY computation ----------
import re as _re, subprocess as _sp

ABBYY_LOCK = os.path.expanduser('~/solr-bridge/phase2/ia_cache/.job.lock')

def _abbyy_job():
    try:
        j = json.load(open(ABBYY_LOCK))
        os.kill(j['pid'], 0)
        return j
    except Exception:
        try: os.remove(ABBYY_LOCK)
        except OSError: pass
        return None

@app.route('/abbyy_compute', methods=['POST'])
def abbyy_compute():
    q = (request.form.get('q') or '').strip().lower()
    if not _re.match(r"^[a-z0-9][a-z0-9'-]{1,30}$", q):
        return jsonify({'ok': False, 'msg': 'single words only'}), 400
    if q in _abbyy_counts():
        return jsonify({'ok': True, 'state': 'done'})
    job = _abbyy_job()
    if job:
        return jsonify({'ok': False,
                        'msg': "a computation is already running for '" + job['q'] + "'"}), 409
    log = os.path.expanduser('~/solr-bridge/phase2/ia_cache/.job.' + q + '.log')
    p = _sp.Popen(['python3', os.path.expanduser('~/solr-bridge/phase2/ia_compare.py'), q],
                  stdout=open(log, 'w'), stderr=_sp.STDOUT)
    json.dump({'q': q, 'pid': p.pid, 'log': log}, open(ABBYY_LOCK, 'w'))
    return jsonify({'ok': True, 'state': 'started'})

@app.route('/abbyy_status')
def abbyy_status():
    q = (request.args.get('q') or '').strip().lower()
    if q in _abbyy_counts():
        return jsonify({'state': 'done', 'result': _abbyy_counts()[q]})
    job = _abbyy_job()
    if job and job['q'] == q:
        prog = ''
        try:
            for line in open(job['log']):
                if 'issues...' in line:
                    prog = line.strip()
        except Exception:
            pass
        return jsonify({'state': 'running', 'progress': prog})
    return jsonify({'state': 'absent'})

# ---------- comprehensive report + live fuzzy counter ----------
@app.route('/fuzzy')
def fuzzy():
    q = (request.args.get('q') or '').strip().lower()
    if not re.match(r"^[a-z0-9][a-z0-9'-]{1,30}$", q):
        return jsonify({'error': 'single words only'}), 400
    out = {}
    pops = [
        ('tesseract', solr1, 'ocr_text:{} AND source:tesseract'),
        ('vlm', solr1, 'ocr_text:{} AND source:paddleocr-vl'),
        ('abbyy', solra, 'ocr_text:{}'),
        ('hybrid', solr, 'ocr_text:{}'),
        ('image_desc', solr, 'image_desc:({})'),
    ]
    for name, fn, tpl in pops:
        row = {}
        for label, term in (('exact', q), ('f1', q + '~1'), ('f2', q + '~2')):
            try:
                row[label] = fn({'q': tpl.format(term), 'rows': 0})['response']['numFound']
            except Exception:
                row[label] = None
        out[name] = row
    return jsonify({'q': q, 'counts': out})

@app.route('/report')
def report():
    try:
        tpl = open(os.path.expanduser('~/solr-bridge/phase2/report.html')).read()
        data = open(os.path.expanduser('~/solr-bridge/phase2/report_data.json')).read()
    except FileNotFoundError as e:
        return f'missing: {e}', 500
    return tpl.replace('__DATA__', data)

# ---------- corpus statistics page ----------
@app.route('/corpus')
def corpus():
    try:
        p1 = json.load(open(os.path.expanduser('~/solr-bridge/corpus_stats.json')))
        ph = json.load(open(os.path.expanduser('~/solr-bridge/phase2/corpus_stats_hybrid.json')))
    except FileNotFoundError as e:
        return f'stats file missing: {e}', 500
    t, v, h = p1['tesseract'], p1['vlm'], ph['hybrid']
    t['words_per_page'] = round(t['total_words'] / t['pages'])
    v['words_per_page'] = round(v['total_words'] / v['pages'])
    def row(label, key, fmt='{:,}', note=''):
        cells = ''.join(
            f'<td style="text-align:right;padding:3px 16px">{fmt.format(d[key]) if key in d else "&#8212;"}</td>'
            for d in (t, v, h))
        n = f' <span style="color:#a09d95;font-size:.85em">{note}</span>' if note else ''
        return (f'<tr><td style="padding:3px 16px 3px 0"><b>{label}</b>{n}</td>{cells}</tr>')
    def suspects_col(title, pairs):
        rows = ''.join(f'<div>{w} <span style="color:#999">{c:,}</span></div>' for w, c in pairs[:100])
        return (f'<div style="flex:1;min-width:220px"><h3 style="font-size:.95em">{title}</h3>'
                f'<div style="font-size:.85em;line-height:1.5;column-count:2">{rows}</div></div>')
    body = f'''
<p style="font-size:.85em"><a href="/">&larr; search</a> &middot; <a href="/about">about</a></p>
<h1>Daily Colonist 1925 &#8212; corpus statistics</h1>
<p style="color:#777;font-size:.9em">Phase 1 arms generated {p1["generated"]}; hybrid generated {ph["generated"]}.
&#8220;Recognized&#8221; = attested &#8805;3&times; in the year-corpus lexicon (built from Tesseract text, so the measure
slightly favors Tesseract; the other columns leading is despite that handicap). Phase 1&#8217;s VLM word counts include
AI image descriptions mixed into page text; the hybrid column counts printed-page text only &#8212; descriptions live in a
separate field. Cross-arm vocabulary overlap (Phase 1): shared {p1["shared_unique"]:,} &middot;
only Tesseract {p1["only_tesseract"]:,} &middot; only VLM {p1["only_vlm"]:,}.</p>
<table style="border-collapse:collapse;margin:1em 0;font-size:.95em">
<tr><th></th><th style="padding:3px 16px;text-align:right">Tesseract</th>
<th style="padding:3px 16px;text-align:right">VLM</th>
<th style="padding:3px 16px;text-align:right">Hybrid</th></tr>
{row('Pages', 'pages')}
{row('Total words', 'total_words')}
{row('Words per page', 'words_per_page')}
{row('Unique forms', 'unique', note='lower is better at corpus scale &#8212; OCR noise inflates uniques')}
{row('Recognized vocabulary', 'recognized_pct', fmt='{}%', note='higher is better')}
{row('Suspect forms (distinct)', 'suspect_distinct', note='lower is better')}
{row('Suspect tokens', 'suspect_tokens', note='lower is better')}
</table>
<h2 style="font-size:1.05em">Most frequent suspect forms by arm</h2>
<p style="color:#777;font-size:.9em">Tesseract&#8217;s list is dominated by damage signatures (i&#8217;he, lhe, vou);
the VLM&#8217;s and hybrid&#8217;s by real-but-unattested forms: hyphen-stub fragments from classified-ad typography
(shared with Tesseract), possessives, and modern compounds. The hybrid&#8217;s list resembling the VLM&#8217;s &#8212;
with no damage-class entries at the top &#8212; is evidence the rescue gating kept Tesseract&#8217;s noise out.</p>
<div style="display:flex;flex-wrap:wrap;gap:24px">
{suspects_col('Tesseract', p1['top_suspects_tesseract'])}
{suspects_col('VLM', p1['top_suspects_vlm'])}
{suspects_col('Hybrid', ph['top_suspects_hybrid'])}
</div>'''
    return ('<!doctype html><html><head><meta charset="utf-8"><title>Corpus statistics</title>'
            '<style>body{font-family:Georgia,serif;max-width:64em;margin:2em auto;'
            'padding:0 1em;line-height:1.5;color:#222}h1{font-size:1.3em}</style></head><body>'
            + body + '</body></html>')

# ---------- about page ----------
@app.route('/about')
def about():
    try:
        body = open(os.path.expanduser('~/solr-bridge/phase2/about.html')).read()
    except FileNotFoundError:
        return 'about.html not found', 404
    return ('<!doctype html><html><head><meta charset="utf-8"><title>About this index</title>'
            '<style>body{font-family:Georgia,serif;max-width:46em;margin:2em auto;'
            'padding:0 1em;line-height:1.6;color:#222}h1{font-size:1.3em}h2{font-size:1.05em;margin-top:1.6em}'
            'code{background:#f4f4f2;padding:0 .3em}</style></head><body>'
            '<p style="font-size:.85em"><a href="/">&larr; search</a></p>' + body + '</body></html>')

# ---------- Mirador page (Phase 1 dialect, single window) ----------
@app.route('/view/<issue>')
def view(issue):
    return '''<!DOCTYPE html><html><head>
<script src="https://unpkg.com/mirador@3/dist/mirador.min.js"></script>
<style>body{margin:0}#m{position:absolute;top:44px;bottom:0;left:0;right:0}
#vhead{position:fixed;top:0;left:0;right:0;height:44px;z-index:9999;background:#fff;
border-bottom:2px solid #35619e;display:flex;align-items:center;gap:10px;padding:0 12px;
box-sizing:border-box;font-family:-apple-system,Helvetica,sans-serif;font-size:13px}
#vhead a{color:#3b3bb3;text-decoration:none}
#vhead .vt{font-family:Georgia,serif;font-size:15px}
#vq{font-family:Georgia,serif;font-size:13px;padding:4px 8px;border:1px solid #b9b6ae;border-radius:4px;width:170px}
.navb{border:1px solid #b9b6ae;background:#fff;border-radius:4px;padding:3px 9px;color:#333;cursor:pointer}
#tlinks{font-size:12px;color:#777}</style>
</head><body>
<div id="vhead">
 <a href="/">Home</a>
 <span class="vt" id="vtitle"></span>
 <form id="vform" style="margin-left:auto;display:flex;gap:6px">
  <input id="vq" type="text" placeholder="Search this issue…">
  <button class="navb" type="submit">Search</button>
 </form>
 <span id="tlinks"></span>
</div>
<div id="m"></div><script>
(function(){
  var issue = location.pathname.split('/').pop();
  var q = new URLSearchParams(location.search).get('q') || '';
  document.getElementById('vq').value = q;
  document.getElementById('vtitle').textContent = issue + ' [hybrid]';
  document.title = issue + ' — hybrid';
  document.getElementById('vform').addEventListener('submit', function(ev){
    ev.preventDefault();
    var nq = document.getElementById('vq').value.trim();
    location.href = '/view/' + issue + (nq ? '?q=' + encodeURIComponent(nq) : '');
  });
  var canvas = new URLSearchParams(location.search).get('canvas') || '';
  var cfg = {id:'m', workspaceControlPanel:{enabled:false},
    windows:[{manifestId:'/manifest/' + issue,
              allowClose:false, allowMaximize:false, sideBarOpenByDefault: !!q}]};
  if (q) cfg.windows[0].defaultSearchQuery = q;
  if (canvas) cfg.windows[0].canvasId = location.origin + '/canvas/' + canvas;
  var inst = Mirador.viewer(cfg);
  window.mirador = inst;
  var annoBox = {};
  if (q) {
    fetch('/search/' + issue + '?q=' + encodeURIComponent(q))
      .then(function(r){ return r.json(); })
      .then(function(d){
        (d.resources || []).forEach(function(a){
          var m = /xywh=(\d+),(\d+),(\d+),(\d+)/.exec(a.on || '');
          if (m) annoBox[a['@id']] = {x:+m[1], y:+m[2], w:+m[3], h:+m[4],
                                      canvas: (a.on || '').split('#')[0]};
        });
      });
  }
  var lastSel = null, pendingZoom = null;
  inst.store.subscribe(function(){
    try {
      var st = inst.store.getState();
      var wid = Object.keys(st.windows)[0];
      var sel = st.windows[wid].selectedAnnotationId;
      if (sel && sel !== lastSel && annoBox[sel]) {
        lastSel = sel;
        pendingZoom = annoBox[sel];
      }
      if (!pendingZoom) return;
      var cur = st.windows[wid].canvasId;
      if (cur !== pendingZoom.canvas) {
        // wrong page under the viewer: switch first, zoom on a later tick
        inst.store.dispatch(Mirador.actions.setCanvas(wid, pendingZoom.canvas));
        return;
      }
      if (!st.viewers || !st.viewers[wid]) return;  // OSD not ready on this canvas yet
      var b = pendingZoom; pendingZoom = null;
      var winW = Math.max(b.w * 6, 1200);
      inst.store.dispatch(Mirador.actions.updateViewport(wid,
        {x: Math.round(b.x + b.w/2), y: Math.round(b.y + b.h/2), zoom: 1/winW}));
    } catch(e) {}
  });
  // text/json links follow the currently shown canvas
  function updateLinks(){
    try{
      var st = inst.store.getState();
      var wid = Object.keys(st.windows)[0];
      var cid = st.windows[wid].canvasId || '';
      var page = cid.split('/').pop();
      if(page){document.getElementById('tlinks').innerHTML =
        '<a href="/text/'+page+'" target="_blank">text</a> · ' +
        '<a href="/json/'+page+'" target="_blank">json</a>';}
    }catch(e){}
  }
  inst.store.subscribe(updateLinks); setTimeout(updateLinks, 1500);
})();
</script></body></html>'''

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8889)
