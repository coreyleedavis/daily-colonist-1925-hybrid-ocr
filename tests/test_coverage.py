#!/usr/bin/env python3
"""Phase 2: full-page regrouping coverage stats for p005. Read-only.
v2: csv.QUOTE_NONE — Tesseract TSV is not quoted CSV; default quote
handling swallowed rows containing double-quote chars."""
import json, csv

TSV = '/home/coreyd@uvic.ca/tess5-1925-full/dailycolonist0525uvic_14/dailycolonist0525uvic_14_p005.tsv'
VLM = '/home/coreyd@uvic.ca/paddle-year/dailycolonist0525uvic_14/dailycolonist0525uvic_14_p005_described.json'

vlm = json.load(open(VLM))
tess_w = tess_h = None
words = []
with open(TSV) as f:
    r = csv.reader(f, delimiter='\t', quoting=csv.QUOTE_NONE)
    next(r)
    for row in r:
        if len(row) < 12:
            continue
        if row[0] == '1':
            tess_w, tess_h = int(row[8]), int(row[9])
        elif row[0] == '5' and row[11].strip():
            left, top, w, h = int(row[6]), int(row[7]), int(row[8]), int(row[9])
            words.append({'text': row[11], 'conf': float(row[10]),
                          'cx': left + w/2, 'cy': top + h/2})
assert tess_w and tess_h
sx, sy = vlm['width']/tess_w, vlm['height']/tess_h

blocks = vlm['parsing_res_list']
per_block = {b['block_id']: [] for b in blocks}
counts = {0: 0, 1: 0, 2: 0}
for w in words:
    cx, cy = w['cx']*sx, w['cy']*sy
    homes = [b['block_id'] for b in blocks
             if b['block_bbox'][0] <= cx <= b['block_bbox'][2]
             and b['block_bbox'][1] <= cy <= b['block_bbox'][3]]
    counts[min(len(homes), 2)] += 1
    for h in homes:
        per_block[h].append(w)

n = len(words)
print(f'{n} tesseract words (non-empty):')
print(f'  in exactly 1 block: {counts[1]:4d} ({100*counts[1]/n:.1f}%)')
print(f'  in 0 blocks:        {counts[0]:4d} ({100*counts[0]/n:.1f}%)')
print(f'  in 2+ blocks:       {counts[2]:4d} ({100*counts[2]/n:.1f}%)')

empty = [b for b in blocks if b['block_label'] != 'image' and not per_block[b['block_id']]]
n_text = sum(1 for b in blocks if b['block_label'] != 'image')
print(f'\nVLM text blocks with ZERO tesseract words: {len(empty)} of {n_text}')
for b in empty[:20]:
    preview = b['block_content'][:60].replace('\n', ' / ')
    print(f"  [{b['block_label']}] {preview!r}")
if len(empty) > 20:
    print(f'  ... and {len(empty)-20} more')

img_words = sum(len(per_block[b['block_id']]) for b in blocks if b['block_label'] == 'image')
print(f"\nimage-label blocks: {sum(1 for b in blocks if b['block_label']=='image')} blocks, "
      f'{img_words} tess words inside')
