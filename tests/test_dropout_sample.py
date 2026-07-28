#!/usr/bin/env python3
"""Phase 2: sample pages across the year, compare tess TSV word count vs
VLM text-block word count. Is p005's 0.58 ratio an outlier? Read-only."""
import json, csv, glob, os, random

TESS = os.path.expanduser('~/tess5-1925-full')
PADD = os.path.expanduser('~/paddle-year')

jsons = glob.glob(f'{PADD}/*/*_described.json')
random.seed(1925)
sample = random.sample(jsons, 25)

def tess_count(tsv):
    n = 0
    with open(tsv) as f:
        r = csv.reader(f, delimiter='\t', quoting=csv.QUOTE_NONE)
        next(r)
        for row in r:
            if len(row) >= 12 and row[0] == '5' and row[11].strip():
                n += 1
    return n

results = []
for j in sample:
    base = os.path.basename(j).replace('_described.json', '')
    issue = os.path.basename(os.path.dirname(j))
    tsv = f'{TESS}/{issue}/{base}.tsv'
    if not os.path.exists(tsv):
        print(f'SKIP (no tsv): {base}')
        continue
    d = json.load(open(j))
    vlm_words = sum(len(b['block_content'].split())
                    for b in d['parsing_res_list'] if b['block_label'] != 'image')
    if vlm_words == 0:
        continue
    t = tess_count(tsv)
    results.append((t / vlm_words, t, vlm_words, base))

results.sort()
print(f'{"ratio":>6} {"tess":>6} {"vlm":>6}  page')
for r, t, v, b in results:
    flag = '  <-- dropout?' if r < 0.75 else ''
    print(f'{r:6.2f} {t:6d} {v:6d}  {b}{flag}')

ratios = [r[0] for r in results]
n = len(ratios)
print(f'\n{n} pages: median={sorted(ratios)[n//2]:.2f}  '
      f'min={min(ratios):.2f}  max={max(ratios):.2f}  '
      f'pages<0.75: {sum(1 for r in ratios if r < 0.75)}')
