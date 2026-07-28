#!/usr/bin/env python3
"""Phase 2: orphan clustering v3. Changes from v2:
  1. ADAPTIVE GAPS: pair joins if vgap <= 1.5x and hgap <= 2.0x the TALLER
     word's height (headline type gets headline-scaled gaps; body text keeps
     tight gaps). No page-global threshold.
  2. GATES RE-CUT (risk asymmetry): median conf >= 80 keep | 40-80 flag |
     < 40 discard. no-alnum-majority still discards at any conf (pipe rule).
Read-only."""
import json, csv, os, sys

issue, page = sys.argv[1], sys.argv[2]
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
                          'cx': l+w/2, 'cy': t+h/2})
sx, sy = vlm['width']/tess_w, vlm['height']/tess_h
blocks = vlm['parsing_res_list']

orphans = []
for w in words:
    cx, cy = w['cx']*sx, w['cy']*sy
    if not any(b['block_bbox'][0] <= cx <= b['block_bbox'][2]
               and b['block_bbox'][1] <= cy <= b['block_bbox'][3]
               for b in blocks):
        orphans.append(w)
print(f'{issue}_{page}: {len(orphans)} orphans of {len(words)}')
if not orphans: sys.exit()

def joinable(a, b):
    ref = max(a['h'], b['h'])
    if ref < 15: ref = 15
    vg = max(0, max(a['t'], b['t']) - min(a['t']+a['h'], b['t']+b['h']))
    hg = max(0, max(a['l'], b['l']) - min(a['l']+a['w'], b['l']+b['w']))
    return vg <= 1.5*ref and hg <= 2.0*ref

clusters = []
for w in sorted(orphans, key=lambda x: (x['cy'], x['cx'])):
    placed = False
    for c in clusters:
        if any(joinable(w, m) for m in c):
            c.append(w); placed = True; break
    if not placed:
        clusters.append([w])
merged = True
while merged:
    merged = False
    for i in range(len(clusters)):
        for k in range(i+1, len(clusters)):
            if any(joinable(a, b) for a in clusters[i] for b in clusters[k]):
                clusters[i].extend(clusters[k]); del clusters[k]
                merged = True; break
        if merged: break

def verdict(c):
    confs = sorted(w['conf'] for w in c)
    med = confs[len(confs)//2]
    alnum = sum(1 for w in c if any(ch.isalnum() for ch in w['text']))
    if alnum <= len(c)/2: return 'discard', med
    if med >= 80: return 'keep', med
    if med >= 40: return 'flag', med
    return 'discard', med

counts = {'keep': 0, 'flag': 0, 'discard': 0}
wcounts = {'keep': 0, 'flag': 0, 'discard': 0}
print(f'{len(clusters)} clusters:\n')
for c in sorted(clusters, key=len, reverse=True):
    v, med = verdict(c)
    counts[v] += 1; wcounts[v] += len(c)
    hs = sorted(w['h'] for w in c); mh = hs[len(hs)//2]
    c.sort(key=lambda w: (round(w['cy']/max(mh, 15)), w['cx']))
    txt = ' '.join(w['text'] for w in c)[:75]
    print(f'  [{v:7s}] {len(c):3d}w conf{med:3.0f} h{mh:3.0f}: {txt!r}')
print(f'\nverdicts:', {k: f'{counts[k]}c/{wcounts[k]}w' for k in counts})
