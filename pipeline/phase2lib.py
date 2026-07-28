#!/usr/bin/env python3
"""phase2lib — CANONICAL shared logic for the Phase 2 hybrid pipeline.
Process rule (state file, 2026-07-15): locked components get IMPORTED from
here, never re-typed. Consumers: synthesize.py, test scripts, smoke run."""
import csv, re, string, difflib

PUNCT = string.punctuation + '"\u201c\u201d\u2018\u2019\u2014\u2013'
ALT = '\u21ff'
ALIGN_GUARD = 4_000_000   # len(tstr)*len(vstr) above this: skip char alignment
                          # (quadratic difflib on garbage/table blocks; their
                          # alignments route to interp anyway — 0925uvic_17
                          # took minutes for nothing)

def norm(s):
    s = s.replace('\u2019', "'").replace('\u2018', "'")
    s = s.replace('\u201c', '"').replace('\u201d', '"')
    return s.strip(PUNCT).upper()

def core_l(s):
    return norm(s).lower()

def sanitize_content(text):
    """Phase 1 hard-won (paddle_to_miniocr.py): table HTML, em/en dashes,
    astral chars + U+FE0F (emoji incident)."""
    text = re.sub(r'</?(?:table|tr|td)[^>]*>', ' ', text or '')
    text = text.replace('\u2014', ' ').replace('\u2013', ' ')
    text = ''.join(c for c in text if ord(c) <= 0xFFFF and ord(c) != 0xFE0F)
    return text.strip()

def load_tess_words(tsv_path):
    """Tesseract TSV -> (page_w, page_h, words). csv.QUOTE_NONE is load-bearing
    (default quoting silently ate 1/3 of rows on 1925 quote-heavy text)."""
    tess_w = tess_h = None
    words = []
    with open(tsv_path) as f:
        r = csv.reader(f, delimiter='\t', quoting=csv.QUOTE_NONE)
        next(r)
        for row in r:
            if len(row) < 12:
                continue
            if row[0] == '1':
                tess_w, tess_h = int(row[8]), int(row[9])
            elif row[0] == '5' and row[11].strip():
                l, t, w, h = int(row[6]), int(row[7]), int(row[8]), int(row[9])
                words.append({'text': row[11], 'conf': float(row[10]),
                              'l': l, 't': t, 'w': w, 'h': h,
                              'cx': l + w/2, 'cy': t + h/2, 'claimed': False})
    assert tess_w and tess_h, f'no level-1 row in {tsv_path}'
    return tess_w, tess_h, words

def order_into_lines(tw):
    """Adaptive line clustering (0.6 x median word height per block).
    Fixed-quantum grouping scrambled body text — aligner v1 bug."""
    if not tw:
        return []
    hs = sorted(w['h'] for w in tw)
    med_h = hs[len(hs)//2]
    tw = sorted(tw, key=lambda w: w['cy'])
    lines, cur, ccy = [], [tw[0]], tw[0]['cy']
    for w in tw[1:]:
        if w['cy'] - ccy <= 0.6*med_h:
            cur.append(w); ccy = sum(x['cy'] for x in cur)/len(cur)
        else:
            lines.append(cur); cur = [w]; ccy = w['cy']
    lines.append(cur)
    out = []
    for ln in lines:
        out.extend(sorted(ln, key=lambda w: w['cx']))
    return out

def char_align(tstr, vstr):
    """Char-level map vlm-index -> tess-index, or None if the size guard
    fires (caller routes the block's words to interp)."""
    if not tstr:
        return None
    if len(tstr) * len(vstr) > ALIGN_GUARD:
        return None
    def _upper1(s):
        # length-preserving uppercase: keep chars whose upper() expands
        return ''.join(u if len(u := c.upper()) == 1 else c for c in s)
    sm = difflib.SequenceMatcher(None, _upper1(tstr), _upper1(vstr), autojunk=False)
    v2t = [None]*len(vstr)
    for a, b, n in sm.get_matching_blocks():
        for k in range(n):
            v2t[b+k] = a+k
    return v2t

def safe_alt(primary, alt):
    """True iff a ⇿ alternative is safe to emit: both sides single
    pure-alphabetic tokens (apostrophes allowed) after edge-strip, non-equal.
    Tokenizer-splittable content (digits, internal punct, currency) severs
    joiner-glued alternatives and crashes offset arithmetic at index time."""
    p = primary.strip(PUNCT)
    a = alt.strip(PUNCT)
    ok = lambda s: s and all(c.isalpha() or c == "'" for c in s)
    return ok(p) and ok(a) and p.upper() != a.upper()

def load_ext_dict():
    d = set()
    for p in ('/usr/share/dict/american-english', '/usr/share/dict/british-english'):
        with open(p, encoding='utf-8', errors='ignore') as f:
            for line in f:
                d.add(line.strip().lower())
    return d

# ---------- orphan clustering (LOCKED v3, from test_orphan_cluster3.py) ----------

def _joinable(a, b):
    ref = max(a['h'], b['h'], 15)
    vg = max(0, max(a['t'], b['t']) - min(a['t']+a['h'], b['t']+b['h']))
    hg = max(0, max(a['l'], b['l']) - min(a['l']+a['w'], b['l']+b['w']))
    return vg <= 1.5*ref and hg <= 2.0*ref

class _CBox:
    """Cluster with bbox prefilter (perf only; decisions unchanged)."""
    __slots__ = ('words', 'x0', 'y0', 'x1', 'y1', 'maxh')
    def __init__(self, w):
        self.words = [w]
        self.x0, self.y0 = w['l'], w['t']
        self.x1, self.y1 = w['l']+w['w'], w['t']+w['h']
        self.maxh = w['h']
    def add(self, w):
        self.words.append(w)
        self.x0 = min(self.x0, w['l']); self.y0 = min(self.y0, w['t'])
        self.x1 = max(self.x1, w['l']+w['w']); self.y1 = max(self.y1, w['t']+w['h'])
        self.maxh = max(self.maxh, w['h'])
    def absorb(self, o):
        self.words.extend(o.words)
        self.x0 = min(self.x0, o.x0); self.y0 = min(self.y0, o.y0)
        self.x1 = max(self.x1, o.x1); self.y1 = max(self.y1, o.y1)
        self.maxh = max(self.maxh, o.maxh)
    def near_word(self, w):
        ref = max(self.maxh, w['h'], 15)
        vg = max(0, max(self.y0, w['t']) - min(self.y1, w['t']+w['h']))
        hg = max(0, max(self.x0, w['l']) - min(self.x1, w['l']+w['w']))
        return vg <= 1.5*ref and hg <= 2.0*ref
    def near_cluster(self, o):
        ref = max(self.maxh, o.maxh, 15)
        vg = max(0, max(self.y0, o.y0) - min(self.y1, o.y1))
        hg = max(0, max(self.x0, o.x0) - min(self.x1, o.x1))
        return vg <= 1.5*ref and hg <= 2.0*ref

def cluster_orphans(orphans):
    """Adaptive 2D agglomeration + merge pass. v3, locked.
    bbox prefilter added (perf): bbox gap <= per-word gap for any member,
    and ref (taller height) <= max member height, so bbox-far implies all
    members test False. Prefilter skips only would-be-False pairs."""
    if not orphans:
        return []
    clusters = []
    for w in sorted(orphans, key=lambda x: (x['cy'], x['cx'])):
        for c in clusters:
            if c.near_word(w) and any(_joinable(w, m) for m in c.words):
                c.add(w); break
        else:
            clusters.append(_CBox(w))
    merged = True
    while merged:
        merged = False
        for i in range(len(clusters)):
            for k in range(i+1, len(clusters)):
                if clusters[i].near_cluster(clusters[k]) and any(
                        _joinable(a, b)
                        for a in clusters[i].words for b in clusters[k].words):
                    clusters[i].absorb(clusters[k]); del clusters[k]
                    merged = True; break
            if merged:
                break
    return [c.words for c in clusters]

def orphan_verdict(c):
    """('keep'|'flag'|'discard', median_conf). Gates 80/40 + no-alnum rule
    (risk asymmetry: flagging junk ~free, discarding real text = Burridge)."""
    confs = sorted(w['conf'] for w in c)
    med = confs[len(confs)//2]
    alnum = sum(1 for w in c if any(ch.isalnum() for ch in w['text']))
    if alnum <= len(c)/2:
        return 'discard', med
    if med >= 80:
        return 'keep', med
    if med >= 40:
        return 'flag', med
    return 'discard', med

def group_cluster_lines(c):
    """Split a kept cluster into display lines (0.75 x median height)."""
    hs = sorted(w['h'] for w in c)
    mh = max(hs[len(hs)//2], 15)
    c = sorted(c, key=lambda w: (round(w['cy']/mh), w['cx']))
    lines, cur, ccy = [], [c[0]], c[0]['cy']
    for w in c[1:]:
        if abs(w['cy'] - ccy) <= 0.75*mh:
            cur.append(w); ccy = sum(x['cy'] for x in cur)/len(cur)
        else:
            lines.append(cur); cur = [w]; ccy = w['cy']
    lines.append(cur)
    return lines


def _h_overlap(a, b):
    """Horizontal overlap as fraction of the narrower box. a,b = (x0,y0,x1,y1)."""
    ov = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    nar = max(1, min(a[2]-a[0], b[2]-b[0]))
    return ov / nar

def insertion_index(new_bbox, vlm_bboxes):
    """Index in vlm_bboxes AFTER which new_bbox belongs (0..len). A VLM block
    precedes the new block if: same column (h-overlap >= 0.3) and its TOP is
    above the new block's top, OR it lies in a column strictly left (its right
    edge <= new block's left edge + slack). Returns position after the LAST
    preceding block; 0 if none precede."""
    nx0, ny0, nx1, ny1 = new_bbox
    last = -1
    for i, bb in enumerate(vlm_bboxes):
        bx0, by0, bx1, by1 = bb
        same_col = _h_overlap(new_bbox, bb) >= 0.3
        if (same_col and by0 < ny0) or (bx1 <= nx0 + 10 and not same_col):
            last = i
    return last + 1
