#!/usr/bin/env python3
"""Phase 2 SYNTHESIS (refactored). Usage: synthesize.py <issue> <page>
Driver over phase2lib (canonical locked components — import, never re-type).
dedup(v4-lite) -> regroup -> align(guarded) -> route(cascade) ->
tess-in-image -> orphan clusters(v3) -> hybrid MiniOCR + provenance sidecar.
Writes ONLY to ~/solr-bridge/phase2/out/. Reads Phase 1 data read-only."""
import json, os, sys, re
from xml.sax.saxutils import escape
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from phase2lib import (PUNCT, ALT, norm, core_l, sanitize_content, safe_alt,
                       load_tess_words, order_into_lines, char_align,
                       load_ext_dict, cluster_orphans, orphan_verdict,
                       group_cluster_lines, insertion_index)

issue, page = sys.argv[1], sys.argv[2]
TSV = os.path.expanduser(f'~/tess5-1925-full/{issue}/{issue}_{page}.tsv')
VLMF = os.path.expanduser(f'~/paddle-year/{issue}/{issue}_{page}_described.json')
OUTD = os.path.expanduser('~/solr-bridge/phase2/out')
os.makedirs(OUTD, exist_ok=True)

vlm = json.load(open(VLMF))
tess_w, tess_h, twords = load_tess_words(TSV)
sx, sy = vlm['width']/tess_w, vlm['height']/tess_h
S = 1/sx
DICT = load_ext_dict()

for _b in vlm['parsing_res_list']:
    _b['block_content'] = sanitize_content(_b.get('block_content', ''))

# ---------- dedup (v4-lite: exact containment + hyphen-stub) ----------
blocks = [b for b in vlm['parsing_res_list']
          if b['block_label'] not in ('image', 'footer_image')
          and b['block_content'].strip()]
def squash(s): return ' '.join(s.split()).upper()
def area(bb): return max(0, bb[2]-bb[0])*max(0, bb[3]-bb[1])
def inter(a, b):
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    return max(0, x1-x0)*max(0, y1-y0)
def hyphen_stub(sm, bg):
    s, g = squash(sm), squash(bg)
    m = re.search(r'([A-Z]+)-$', s)
    if not m: return False
    stub, pre = m.group(1), s[:m.start()].strip()
    if len(pre) < 12 or pre not in g: return False
    return g[g.index(pre)+len(pre):].lstrip().startswith(stub)
dropped = set()
for A in blocks:
    for B in blocks:
        if A is B or A['block_id'] in dropped or B['block_id'] in dropped: continue
        if len(A['block_content']) > len(B['block_content']): continue
        ov = inter(A['block_bbox'], B['block_bbox'])
        if ov == 0 or ov/max(area(A['block_bbox']), 1) < 0.5: continue
        s, g = squash(A['block_content']), squash(B['block_content'])
        if (s in g and len(s) >= 8) or hyphen_stub(A['block_content'], B['block_content']):
            dropped.add(A['block_id'])
blocks = [b for b in blocks if b['block_id'] not in dropped]

# ---------- per-block regroup + align + route ----------
out_blocks = []
prov_counts = {}
def bump(p): prov_counts[p] = prov_counts.get(p, 0) + 1

for blk in blocks:
    x0, y0, x1, y1 = blk['block_bbox']
    tw = [w for w in twords if x0 <= w['cx']*sx <= x1 and y0 <= w['cy']*sy <= y1]
    tw = order_into_lines(tw)
    for w in tw: w['claimed'] = True
    tchars, towner = [], []
    for i, w in enumerate(tw):
        if tchars: tchars.append(' '); towner.append(None)
        for c in w['text']: tchars.append(c); towner.append(i)
    tstr = ''.join(tchars)
    vstr = blk['block_content'].replace('\n', ' ')
    v2t = char_align(tstr, vstr)          # None if empty tess OR size guard
    lines_out = [ln.split() for ln in blk['block_content'].split('\n') if ln.strip()]

    # PASS 0 shrapnel rule (needs v2t)
    shrapnel_owners = set()
    if v2t:
        owner_claims = {}
        pos0 = 0
        for lw0 in lines_out:
            for vw0 in lw0:
                s0 = vstr.index(vw0, pos0); e0 = s0+len(vw0); pos0 = e0
                t0 = [v2t[k] for k in range(s0, e0) if v2t[k] is not None]
                ow0 = sorted({towner[k] for k in t0 if towner[k] is not None})
                if len(ow0) == 1:
                    owner_claims.setdefault(ow0[0], []).append(vw0)
        for o, claimants in owner_claims.items():
            if len(claimants) >= 2 and sum(len(v) for v in claimants) > 2*len(tw[o]['text']):
                shrapnel_owners.add(o)

    final_lines = []
    pos = 0
    for lw in lines_out:
        fl = []
        for vw in lw:
            s = vstr.index(vw, pos); e = s+len(vw); pos = e
            word = {'text': vw, 'alt': None}
            owners = []
            if v2t:
                tidx = [v2t[k] for k in range(s, e) if v2t[k] is not None]
                owners = sorted({towner[k] for k in tidx if towner[k] is not None})
            if len(owners) == 1 and owners[0] in shrapnel_owners:
                word['box'] = None; word['prov'] = 'interp-shrapnel'
                bump('interp-shrapnel'); fl.append(word); continue
            if len(owners) == 1:
                w = tw[owners[0]]
                inw = [k - sum(len(tw[j]['text'])+1 for j in range(owners[0]))
                       for k in tidx if towner[k] == owners[0]]
                n = len(w['text'])
                fx0, fx1 = min(inw)/n, (max(inw)+1)/n
                word['box'] = (w['l']+w['w']*fx0, w['t'], w['w']*(fx1-fx0), w['h'])
                if w['text'].upper() == vw.upper():
                    word['prov'] = 'agree'; bump('agree')
                elif norm(w['text']) == norm(vw):
                    word['prov'] = 'punct'; bump('punct')
                elif w['conf'] < 50 or (norm(w['text']) and norm(w['text']) in norm(vw)):
                    word['prov'] = 'vlm-routed'; bump('vlm-routed')
                elif core_l(vw) in DICT and core_l(w['text']) not in DICT:
                    word['prov'] = 'vlm-dict'; bump('vlm-dict')
                elif core_l(w['text']) in DICT and core_l(vw) not in DICT:
                    word['prov'] = 'tess-dict'; word['text'] = w['text']
                    word['alt'] = vw; bump('tess-dict')
                else:
                    word['prov'] = 'residual-alt'; word['alt'] = w['text']
                    bump('residual-alt')
            elif len(owners) > 1:
                ws = [tw[o] for o in owners]
                l = min(w['l'] for w in ws); t = min(w['t'] for w in ws)
                r_ = max(w['l']+w['w'] for w in ws); btm = max(w['t']+w['h'] for w in ws)
                word['box'] = (l, t, r_-l, btm-t)
                word['prov'] = 'multi'; bump('multi')
            else:
                word['box'] = None; word['prov'] = 'interp'; bump('interp')
            fl.append(word)
        final_lines.append(fl)
    bx0, bw_ = x0*S, (x1-x0)*S
    for fl in final_lines:
        known = [w for w in fl if w['box']]
        ln_t = min((w['box'][1] for w in known), default=y0*S)
        ln_h = max((w['box'][3] for w in known), default=(y1-y0)*S/max(len(final_lines), 1))
        total = sum(len(w['text']) for w in fl) + len(fl) - 1
        cx = bx0
        for w in fl:
            frac = len(w['text'])/max(total, 1)
            if not w['box']:
                w['box'] = (cx, ln_t, bw_*frac, ln_h)
            cx = w['box'][0] + w['box'][2] + bw_*(1/max(total, 1))
    out_blocks.append({'label': blk['block_label'], 'lines': final_lines})

rescued = []   # positioned via insertion_index before emit

# ---------- tess-in-image (own class, NOT orphans) ----------
img_blocks = [b for b in vlm['parsing_res_list']
              if b['block_label'] in ('image', 'footer_image')]
tess_in_image = []
for w in twords:
    if w['claimed']: continue
    cx, cy = w['cx']*sx, w['cy']*sy
    for b in img_blocks:
        bb = b['block_bbox']
        if bb[0] <= cx <= bb[2] and bb[1] <= cy <= bb[3]:
            w['claimed'] = True
            tess_in_image.append(w)
            break
if tess_in_image:
    keepers = [w for w in tess_in_image
               if any(ch.isalnum() for ch in w['text']) and w['conf'] >= 40]
    if keepers:
        fls = [[{'text': w['text'], 'box': (w['l'], w['t'], w['w'], w['h']),
                 'prov': 'tess-in-image', 'alt': None} for w in ln]
               for ln in group_cluster_lines(keepers)]
        for ln in fls:
            for _ in ln: bump('tess-in-image')
        _kw = keepers
        rescued.append({'label': 'tess-in-image', 'lines': fls,
                        'bbox_tess': (min(w['l'] for w in _kw), min(w['t'] for w in _kw),
                                      max(w['l']+w['w'] for w in _kw),
                                      max(w['t']+w['h'] for w in _kw))})

# ---------- orphan clusters (LOCKED v3 via lib) ----------
orph = [w for w in twords if not w['claimed']]
for c in cluster_orphans(orph):
    v, med = orphan_verdict(c)
    if v == 'discard': continue
    prov = 'tess-only' if v == 'keep' else 'tess-only-lowconf'
    fls = [[{'text': w['text'], 'box': (w['l'], w['t'], w['w'], w['h']),
             'prov': prov, 'alt': None} for w in ln]
           for ln in group_cluster_lines(c)]
    for ln in fls:
        for _ in ln: bump(prov)
    rescued.append({'label': 'tess-only', 'lines': fls,
                    'bbox_tess': (min(w['l'] for w in c), min(w['t'] for w in c),
                                  max(w['l']+w['w'] for w in c),
                                  max(w['t']+w['h'] for w in c))})

# ---------- position rescued blocks in VLM sequence ----------
# out_blocks currently holds only VLM-derived blocks, in VLM order.
# vlm_bboxes must be in the SAME coordinate space as the rescued bbox -> use
# tess space (convert VLM bboxes via S).
vlm_bboxes_tess = []
for blk in blocks:
    x0, y0, x1, y1 = blk['block_bbox']
    vlm_bboxes_tess.append((x0*S, y0*S, x1*S, y1*S))
# rescued blocks inserted far-first so earlier insertions don't shift later
# target indices computed against the pure-VLM list
placements = []
for rb in rescued:
    idx = insertion_index(rb['bbox_tess'], vlm_bboxes_tess)
    placements.append((idx, rb))
placements.sort(key=lambda t: t[0], reverse=True)
for idx, rb in placements:
    out_blocks.insert(idx, {'label': rb['label'], 'lines': rb['lines']})

# ---------- dehyph seam pass (cross-block + rescued-cluster line seams) ----------
import re as _re
def _try_join(w1, w2):
    m = _re.match(r'^([A-Za-z]+)-$', w1['text'])
    if not m: return False
    if not _re.match(r'^[a-z]+', w2['text']): return False
    joined = m.group(1) + _re.match(r'^([a-z]+)', w2['text']).group(1)
    if joined.lower() not in DICT: return False
    w1['text'] = m.group(1) + w2['text']   # keep w2's trailing punct
    return True

def _seam_join(prev_line, next_line):
    if prev_line and next_line and _try_join(prev_line[-1], next_line[0]):
        next_line.pop(0)
        return True
    return False

joins = 0
for bi, ob in enumerate(out_blocks):
    # (b) within rescued blocks: consecutive line seams
    if ob['label'] in ('tess-only', 'tess-in-image'):
        li = 0
        while li < len(ob['lines']) - 1:
            if _seam_join(ob['lines'][li], ob['lines'][li+1]):
                joins += 1
                if not ob['lines'][li+1]:
                    del ob['lines'][li+1]
                    continue
            li += 1
    # (a) block seam to next block
    if bi + 1 < len(out_blocks):
        nb = out_blocks[bi+1]
        if ob['lines'] and nb['lines'] and _seam_join(ob['lines'][-1], nb['lines'][0]):
            joins += 1
            if not nb['lines'][0]:
                del nb['lines'][0]
out_blocks = [ob for ob in out_blocks if any(ob['lines'])]
if joins:
    print(f'(dehyph seam pass: {joins} joins)')

# ---------- emit ----------
mini = [f'<p xml:id="{issue}_{page}" wh="{tess_w} {tess_h}">']
sidecar = []
for ob in out_blocks:
    mini.append('<b>')
    for ln in ob['lines']:
        parts = []
        for w in ln:
            x, y, ww, hh = (int(round(v)) for v in w['box'])
            txt = escape(w['text'])
            if w['alt'] and safe_alt(w['text'], w['alt']):
                txt = f'{txt}{ALT}{escape(w["alt"].strip(PUNCT))}'
            parts.append(f'<w x="{x} {y} {ww} {hh}">{txt}</w>')
            sidecar.append({'t': w['text'], 'prov': w['prov']})
        mini.append('<l>' + ' '.join(parts) + '</l>')
    mini.append('</b>')
mini.append('</p>')

open(f'{OUTD}/{issue}_{page}.miniocr.xml', 'w').write('\n'.join(mini))
json.dump(sidecar, open(f'{OUTD}/{issue}_{page}.provenance.json', 'w'))

total = sum(prov_counts.values())
print(f'{issue}_{page}: {len(out_blocks)} blocks ({len(dropped)} deduped), {total} words')
for k in sorted(prov_counts, key=lambda k: -prov_counts[k]):
    print(f'  {k:18s} {prov_counts[k]:5d} ({100*prov_counts[k]/total:.1f}%)')
