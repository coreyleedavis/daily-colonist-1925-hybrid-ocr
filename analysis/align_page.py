#!/usr/bin/env python3
"""Phase 2: full-page alignment v2. Usage: align_page.py <issue> <page>
v2: proper line clustering (adaptive to word heights — v1's fixed 145px quantum
merged body-text lines, scrambling order and inflating unmatched); punct-aware
disagreement classes. Read-only."""
import json, csv, os, sys, difflib, string

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
                          'cx': l+w/2, 'cy': t+h/2, 'used': False})
sx, sy = vlm['width']/tess_w, vlm['height']/tess_h

def order_into_lines(tw):
    """Cluster words into text lines adaptively, return line-ordered flat list."""
    if not tw: return []
    hs = sorted(w['h'] for w in tw)
    med_h = hs[len(hs)//2]
    tw = sorted(tw, key=lambda w: w['cy'])
    lines, cur, cur_cy = [], [tw[0]], tw[0]['cy']
    for w in tw[1:]:
        if w['cy'] - cur_cy <= 0.6 * med_h:
            cur.append(w)
            cur_cy = sum(x['cy'] for x in cur) / len(cur)
        else:
            lines.append(cur); cur = [w]; cur_cy = w['cy']
    lines.append(cur)
    out = []
    for ln in lines:
        out.extend(sorted(ln, key=lambda w: w['cx']))
    return out

PUNCT = string.punctuation + '"\u201c\u201d\u2018\u2019'
def core(s): return s.strip(PUNCT).upper()

blocks = [b for b in vlm['parsing_res_list']
          if b['block_label'] not in ('image', 'footer_image')
          and b['block_content'].strip()]

stats = {'measured': 0, 'measured-split': 0, 'multi-owner': 0,
         'unmatched-dropout': 0, 'unmatched-inblock': 0}
dis = {'punct-only': 0, 'real': []}

for blk in blocks:
    x0, y0, x1, y1 = blk['block_bbox']
    tw = [w for w in words if x0 <= w['cx']*sx <= x1 and y0 <= w['cy']*sy <= y1]
    vstr = blk['block_content'].replace('\n', ' ')
    if not tw:
        stats['unmatched-dropout'] += len(vstr.split())
        continue
    tw = order_into_lines(tw)
    tchars, towner = [], []
    for i, w in enumerate(tw):
        if tchars:
            tchars.append(' '); towner.append(None)
        for c in w['text']:
            tchars.append(c); towner.append(i)
    tstr = ''.join(tchars)
    sm = difflib.SequenceMatcher(None, tstr.upper(), vstr.upper(), autojunk=False)
    v2t = [None]*len(vstr)
    for a, b, n in sm.get_matching_blocks():
        for k in range(n):
            v2t[b+k] = a+k
    pos = 0
    for vw in vstr.split():
        s = vstr.index(vw, pos); e = s + len(vw); pos = e
        tidx = [v2t[k] for k in range(s, e) if v2t[k] is not None]
        owners = sorted({towner[k] for k in tidx if towner[k] is not None})
        if not owners:
            stats['unmatched-inblock'] += 1
            continue
        for o in owners:
            tw[o]['used'] = True
        if len(owners) > 1:
            stats['multi-owner'] += 1
            continue
        w = tw[owners[0]]
        full = (len(tidx) == len(vw) == len(w['text']))
        stats['measured' if full else 'measured-split'] += 1
        if w['text'].upper() != vw.upper():
            if core(w['text']) == core(vw):
                dis['punct-only'] += 1
            elif core(vw) and core(w['text']):
                dis['real'].append((vw, w['text'], w['conf'], blk['block_label']))

n_v = sum(stats.values())
print(f'{issue}_{page}: {len(blocks)} text blocks, {n_v} VLM words')
for k, v in stats.items():
    print(f'  {k:18s} {v:5d} ({100*v/n_v:.1f}%)')
n_used = sum(1 for w in words if w['used'])
print(f'\ntess words consumed: {n_used}/{len(words)} ({100*n_used/len(words):.1f}%)')
print(f"\ndisagreements: {dis['punct-only']} punct-only (auto-normalizable), "
      f"{len(dis['real'])} real:")
for vw, tt, c, lbl in dis['real'][:30]:
    print(f'  vlm={vw!r:22s} tess={tt!r:22s} conf={c:5.1f}  [{lbl}]')
if len(dis['real']) > 30:
    print(f"  ... and {len(dis['real'])-30} more")
