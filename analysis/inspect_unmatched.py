#!/usr/bin/env python3
"""Phase 2: show the 3 blocks with most in-block-unmatched VLM words on p005 —
both word streams side by side, so we can see WHY alignment fails. Read-only."""
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
                          'cx': l+w/2, 'cy': t+h/2})
sx, sy = vlm['width']/tess_w, vlm['height']/tess_h

def order_into_lines(tw):
    if not tw: return []
    hs = sorted(w['h'] for w in tw); med_h = hs[len(hs)//2]
    tw = sorted(tw, key=lambda w: w['cy'])
    lines, cur, cur_cy = [], [tw[0]], tw[0]['cy']
    for w in tw[1:]:
        if w['cy'] - cur_cy <= 0.6*med_h:
            cur.append(w); cur_cy = sum(x['cy'] for x in cur)/len(cur)
        else:
            lines.append(cur); cur = [w]; cur_cy = w['cy']
    lines.append(cur)
    out = []
    for ln in lines:
        out.extend(sorted(ln, key=lambda w: w['cx']))
    return out

scored = []
for blk in vlm['parsing_res_list']:
    if blk['block_label'] in ('image', 'footer_image') or not blk['block_content'].strip():
        continue
    x0, y0, x1, y1 = blk['block_bbox']
    tw = [w for w in words if x0 <= w['cx']*sx <= x1 and y0 <= w['cy']*sy <= y1]
    if not tw: continue
    tw = order_into_lines(tw)
    tchars, towner = [], []
    for i, w in enumerate(tw):
        if tchars: tchars.append(' '); towner.append(None)
        for c in w['text']: tchars.append(c); towner.append(i)
    tstr = ''.join(tchars)
    vstr = blk['block_content'].replace('\n', ' ')
    sm = difflib.SequenceMatcher(None, tstr.upper(), vstr.upper(), autojunk=False)
    v2t = [None]*len(vstr)
    for a, b, n in sm.get_matching_blocks():
        for k in range(n): v2t[b+k] = a+k
    unmatched = 0; pos = 0
    for vw in vstr.split():
        s = vstr.index(vw, pos); e = s+len(vw); pos = e
        if not any(v2t[k] is not None for k in range(s, e)):
            unmatched += 1
    scored.append((unmatched, blk['block_label'], vstr, tstr))

scored.sort(reverse=True)
for unm, lbl, vstr, tstr in scored[:3]:
    print(f'=== [{lbl}] {unm} unmatched VLM words ===')
    print(f'VLM : {vstr[:400]}')
    print(f'TESS: {tstr[:400]}')
    print()
