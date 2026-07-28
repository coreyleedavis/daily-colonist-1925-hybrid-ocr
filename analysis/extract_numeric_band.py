#!/usr/bin/env python3
"""Phase 2 arbitration, step 1: extract numeric-band disagreements for a page.
Reruns regroup+align+route (via phase2lib) and emits JSONL: one line per
numeric disagreement with vlm/tess readings, tess conf, and the tess-space
box (padded) for cropping. Usage: extract_numeric_band.py <issue> <page>
Read-only; writes only ~/solr-bridge/phase2/arb/<page>.numeric.jsonl"""
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from phase2lib import (norm, core_l, sanitize_content, load_tess_words,
                       order_into_lines, char_align, load_ext_dict)

issue, page = sys.argv[1], sys.argv[2]
TSV = os.path.expanduser(f'~/tess5-1925-full/{issue}/{issue}_{page}.tsv')
VLMF = os.path.expanduser(f'~/paddle-year/{issue}/{issue}_{page}_described.json')
ARBD = os.path.expanduser('~/solr-bridge/phase2/arb')
os.makedirs(ARBD, exist_ok=True)

DICT = load_ext_dict()
vlm = json.load(open(VLMF))
tess_w, tess_h, twords = load_tess_words(TSV)
sx, sy = vlm['width']/tess_w, vlm['height']/tess_h
for b in vlm['parsing_res_list']:
    b['block_content'] = sanitize_content(b.get('block_content', ''))

def is_num(s):
    c = norm(s)
    return bool(c) and bool(re.match(r'^[\d$.,¢%\-;:]+$', c)) and any(ch.isdigit() for ch in c)

out = []
for blk in vlm['parsing_res_list']:
    if blk['block_label'] in ('image', 'footer_image') or not blk['block_content'].strip():
        continue
    x0, y0, x1, y1 = blk['block_bbox']
    tw = [w for w in twords if x0 <= w['cx']*sx <= x1 and y0 <= w['cy']*sy <= y1]
    tw = order_into_lines(tw)
    tchars, towner = [], []
    for i, w in enumerate(tw):
        if tchars: tchars.append(' '); towner.append(None)
        for c in w['text']: tchars.append(c); towner.append(i)
    tstr = ''.join(tchars)
    vstr = blk['block_content'].replace('\n', ' ')
    v2t = char_align(tstr, vstr)
    if not v2t: continue
    pos = 0
    for vw in vstr.split():
        s = vstr.index(vw, pos); e = s+len(vw); pos = e
        tidx = [v2t[k] for k in range(s, e) if v2t[k] is not None]
        owners = sorted({towner[k] for k in tidx if towner[k] is not None})
        if len(owners) != 1: continue
        w = tw[owners[0]]
        if w['text'].upper() == vw.upper() or norm(w['text']) == norm(vw): continue
        # cascade prefix: skip what earlier bands resolve
        if w['conf'] < 50: continue
        if norm(w['text']) and norm(w['text']) != norm(vw) and norm(w['text']) in norm(vw): continue
        vd, td = core_l(vw) in DICT, core_l(w['text']) in DICT
        if vd != td: continue
        # numeric band only
        if not (is_num(vw) or is_num(w['text'])): continue
        pad = int(w['h'] * 0.6)
        out.append({'page': f'{issue}_{page}', 'vlm': vw, 'tess': w['text'],
                    'conf': round(w['conf'], 1),
                    'box_tess': [w['l']-pad, w['t']-pad,
                                 w['l']+w['w']+pad, w['t']+w['h']+pad]})

path = f'{ARBD}/{issue}_{page}.numeric.jsonl'
with open(path, 'w') as f:
    for o in out:
        f.write(json.dumps(o) + '\n')
print(f'{len(out)} numeric disagreements -> {path}')
for o in out[:10]:
    print(f"  vlm={o['vlm']!r:14s} tess={o['tess']!r:14s} conf={o['conf']}")
