#!/usr/bin/env python3
"""Phase 2 test: spatially regroup Tesseract words into a VLM block's bbox.
Read-only against Phase 1 data. Test target: the RECEIVERS HERE / OF GREAT
LINE doc_title block on dailycolonist0525uvic_14_p005."""
import json, csv

TSV = '/home/coreyd@uvic.ca/tess5-1925-full/dailycolonist0525uvic_14/dailycolonist0525uvic_14_p005.tsv'
VLM = '/home/coreyd@uvic.ca/paddle-year/dailycolonist0525uvic_14/dailycolonist0525uvic_14_p005_described.json'

vlm = json.load(open(VLM))

# --- per-page scale from Tesseract level-1 row vs VLM page dims ---
tess_w = tess_h = None
words = []
with open(TSV) as f:
    r = csv.reader(f, delimiter='\t')
    header = next(r)
    for row in r:
        if len(row) < 12:
            continue
        if row[0] == '1':
            tess_w, tess_h = int(row[8]), int(row[9])
        elif row[0] == '5':
            left, top, w, h = int(row[6]), int(row[7]), int(row[8]), int(row[9])
            words.append({'text': row[11], 'conf': float(row[10]),
                          'cx': left + w / 2, 'cy': top + h / 2})
assert tess_w and tess_h, 'no level-1 row found in TSV'
sx = vlm['width'] / tess_w    # tesseract px -> vlm px
sy = vlm['height'] / tess_h
print(f'scale: x={sx:.6f} y={sy:.6f}  ({len(words)} tesseract words on page)')

# --- find the target VLM block ---
target = None
for b in vlm['parsing_res_list']:
    if b['block_label'] == 'doc_title' and 'RECEIVERS' in b['block_content']:
        target = b
        break
assert target, 'RECEIVERS doc_title block not found'
x0, y0, x1, y1 = target['block_bbox']
print(f"\ntarget block: {target['block_content']!r}")
print(f'bbox (vlm space): {x0},{y0} -> {x1},{y1}')

# --- which tesseract words' centers (scaled) fall inside? ---
print('\ntesseract words whose center falls inside the block:')
hits = 0
for w in words:
    cx, cy = w['cx'] * sx, w['cy'] * sy
    if x0 <= cx <= x1 and y0 <= cy <= y1:
        hits += 1
        print(f"  {w['text']!r:20s} conf={w['conf']:6.1f}  center=({cx:.0f},{cy:.0f})")
assert hits > 0, 'no words matched — scale or containment logic is wrong'
print(f'\n{hits} words matched')
