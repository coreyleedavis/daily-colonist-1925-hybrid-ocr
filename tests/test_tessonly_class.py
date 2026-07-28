#!/usr/bin/env python3
"""Phase 2: size and quality of the tess-only class.
Part A: orphan% and in-image% across the 25-page sample (+p005).
Part B: orphan detail on dailycolonist0925uvic_35_p005 — confidence
distribution and naive spatial clustering. Read-only."""
import json, csv, glob, os, random

TESS = os.path.expanduser('~/tess5-1925-full')
PADD = os.path.expanduser('~/paddle-year')

def load_page(issue, page):
    tsv = f'{TESS}/{issue}/{issue}_{page}.tsv'
    vj = f'{PADD}/{issue}/{issue}_{page}_described.json'
    if not (os.path.exists(tsv) and os.path.exists(vj)):
        return None
    vlm = json.load(open(vj))
    tess_w = tess_h = None
    words = []
    with open(tsv) as f:
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
    if not (tess_w and tess_h and words):
        return None
    sx, sy = vlm['width']/tess_w, vlm['height']/tess_h
    blocks = vlm['parsing_res_list']
    for w in words:
        cx, cy = w['cx']*sx, w['cy']*sy
        homes = [b for b in blocks
                 if b['block_bbox'][0] <= cx <= b['block_bbox'][2]
                 and b['block_bbox'][1] <= cy <= b['block_bbox'][3]]
        w['class'] = ('orphan' if not homes else
                      'image' if any(b['block_label'] == 'image' for b in homes)
                      else 'text')
    return words

# ---- Part A: sample-wide rates ----
jsons = glob.glob(f'{PADD}/*/*_described.json')
random.seed(1925)
sample = random.sample(jsons, 25)
sample.append(f'{PADD}/dailycolonist0525uvic_14/dailycolonist0525uvic_14_p005_described.json')

print(f'{"orph%":>6} {"img%":>6} {"n":>6}  page')
tot = {'orphan': 0, 'image': 0, 'text': 0}
rows = []
for j in sample:
    base = os.path.basename(j).replace('_described.json', '')
    issue = os.path.basename(os.path.dirname(j))
    page = base.replace(issue + '_', '')
    words = load_page(issue, page)
    if not words: continue
    n = len(words)
    o = sum(1 for w in words if w['class'] == 'orphan')
    i = sum(1 for w in words if w['class'] == 'image')
    for w in words: tot[w['class']] += 1
    rows.append((100*o/n, 100*i/n, n, base))
rows.sort(reverse=True)
for o, i, n, b in rows:
    print(f'{o:6.1f} {i:6.1f} {n:6d}  {b}')
N = sum(tot.values())
print(f'\nTOTALS across {len(rows)} pages, {N} words: '
      f'orphan {100*tot["orphan"]/N:.1f}%  in-image {100*tot["image"]/N:.1f}%  '
      f'in-text {100*tot["text"]/N:.1f}%')

# ---- Part B: orphan quality on the known high-tail page ----
print('\n---- Part B: orphans on dailycolonist0925uvic_35_p005 ----')
words = load_page('dailycolonist0925uvic_35', 'p005')
orph = [w for w in words if w['class'] == 'orphan']

def is_noise(t):
    return not any(c.isalnum() for c in t)
noise = [w for w in orph if is_noise(w['text'])]
real = [w for w in orph if not is_noise(w['text'])]
def cstats(ws):
    cs = sorted(w['conf'] for w in ws)
    return f'n={len(cs)} median={cs[len(cs)//2]:.0f} q1={cs[len(cs)//4]:.0f} q3={cs[3*len(cs)//4]:.0f}'
print(f'no-alnum noise tokens: {cstats(noise)}')
print(f'has-alnum tokens:      {cstats(real)}')

# naive clustering: sort by y, break cluster when y-gap > 150px (tess space)
real.sort(key=lambda w: (w['cy'], w['cx']))
clusters, cur = [], [real[0]]
for w in real[1:]:
    if w['cy'] - cur[-1]['cy'] > 150:
        clusters.append(cur); cur = [w]
    else:
        cur.append(w)
clusters.append(cur)
print(f'\n{len(clusters)} naive y-clusters (gap>150px):')
for c in clusters[:12]:
    c.sort(key=lambda w: (round(w['cy']/60), w['cx']))
    med = sorted(w['conf'] for w in c)[len(c)//2]
    txt = ' '.join(w['text'] for w in c)[:70]
    print(f'  [{len(c):3d} words, med conf {med:3.0f}] {txt!r}')
