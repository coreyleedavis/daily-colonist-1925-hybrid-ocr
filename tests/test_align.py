#!/usr/bin/env python3
"""Phase 2: alignment prototype on ONE block (RECEIVERS HERE / OF GREAT LINE,
p005). Char-level alignment tess<->VLM, donate/split measured tess boxes onto
VLM words. Read-only."""
import json, csv, os, difflib

issue, page = 'dailycolonist0525uvic_14', 'p005'
TSV = os.path.expanduser(f'~/tess5-1925-full/{issue}/{issue}_{page}.tsv')
VLM = os.path.expanduser(f'~/paddle-year/{issue}/{issue}_{page}_described.json')

vlm = json.load(open(VLM))
tess_w = tess_h = None
words = []
with open(TSV) as f:
    r = csv.reader(f, delimiter='\t', quoting=csv.QUOTE_NONE)
    next(r)
    for row in r:
        if len(row) < 12: continue
        if row[0] == '1':
            tess_w, tess_h = int(row[8]), int(row[9])
        elif row[0] == '5' and row[11].strip():
            l, t, w, h = int(row[6]), int(row[7]), int(row[8]), int(row[9])
            words.append({'text': row[11], 'conf': float(row[10]),
                          'l': l, 't': t, 'w': w, 'h': h,
                          'cx': l + w/2, 'cy': t + h/2})
sx, sy = vlm['width']/tess_w, vlm['height']/tess_h

target = next(b for b in vlm['parsing_res_list']
              if b['block_label'] == 'doc_title' and 'RECEIVERS' in b['block_content'])
x0, y0, x1, y1 = target['block_bbox']
tw = [w for w in words if x0 <= w['cx']*sx <= x1 and y0 <= w['cy']*sy <= y1]
tw.sort(key=lambda w: (round(w['cy']/50), w['cx']))  # crude line-then-x order

# Build char streams. tess: concatenated words, remember which char -> which word
tchars, towner = [], []
for i, w in enumerate(tw):
    if tchars:
        tchars.append(' '); towner.append(None)
    for c in w['text']:
        tchars.append(c); towner.append(i)
tstr = ''.join(tchars)
vstr = target['block_content'].replace('\n', ' ')
print(f'tess stream: {tstr!r}')
print(f'vlm  stream: {vstr!r}\n')

sm = difflib.SequenceMatcher(None, tstr.upper(), vstr.upper(), autojunk=False)
v2t = [None]*len(vstr)
for a, b, n in sm.get_matching_blocks():
    for k in range(n):
        v2t[b+k] = a+k

print(f'{"vlm word":15s} {"source tess word":18s} {"box (tess px)":28s} prov')
pos = 0
for vw in vstr.split():
    s = vstr.index(vw, pos); e = s + len(vw); pos = e
    tidx = [v2t[k] for k in range(s, e) if v2t[k] is not None]
    owners = sorted({towner[k] for k in tidx if towner[k] is not None})
    if not owners:
        print(f'{vw:15s} {"-":18s} {"-":28s} unmatched')
        continue
    o = owners[0]
    w = tw[o]
    inword = [k - sum(len(tw[j]["text"])+1 for j in range(o)) for k in tidx if towner[k] == o]
    n = len(w['text'])
    fx0, fx1 = min(inword)/n, (max(inword)+1)/n
    bx = w['l'] + w['w']*fx0
    bw = w['w']*(fx1-fx0)
    prov = 'measured' if (fx0, fx1) == (0.0, 1.0) else 'measured-split'
    print(f'{vw:15s} {w["text"]!r:18s} x={bx:6.0f} w={bw:5.0f} y={w["t"]:5d} h={w["h"]:3d}  {prov}')
