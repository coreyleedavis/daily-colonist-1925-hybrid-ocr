#!/usr/bin/env python3
"""Phase 2: regrouping coverage for any page. Usage: coverage.py <issue> <page>
e.g. coverage.py dailycolonist0925uvic_35 p005   Read-only."""
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
            words.append({'text': row[11], 'cx': l + w/2, 'cy': t + h/2})
assert tess_w and tess_h
sx, sy = vlm['width']/tess_w, vlm['height']/tess_h
blocks = vlm['parsing_res_list']

orphans = []   # tess words in no VLM block at all
in_img = 0
in_text = 0
for w in words:
    cx, cy = w['cx']*sx, w['cy']*sy
    homes = [b for b in blocks
             if b['block_bbox'][0] <= cx <= b['block_bbox'][2]
             and b['block_bbox'][1] <= cy <= b['block_bbox'][3]]
    if not homes:
        orphans.append(w)
    elif any(b['block_label'] == 'image' for b in homes):
        in_img += 1
    else:
        in_text += 1

vlm_text = sum(len(b['block_content'].split()) for b in blocks if b['block_label'] != 'image')
print(f'{issue}_{page}: tess={len(words)} vlm_text={vlm_text} ratio={len(words)/vlm_text:.2f}')
print(f'tess words: in text blocks {in_text}, in image blocks {in_img}, ORPHANS {len(orphans)} ({100*len(orphans)/len(words):.1f}%)')
print('\nfirst 40 orphan words (in tess stream order):')
print(' '.join(w['text'] for w in orphans[:40]))
