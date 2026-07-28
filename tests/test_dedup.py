#!/usr/bin/env python3
"""Phase 2: dedup prototype. Find VLM block pairs where (a) bboxes overlap
>50% of the smaller, and (b) the smaller block's text fuzzy-matches into the
larger block's text. Report-only — shows what WOULD be suppressed. Read-only."""
import json, glob, os, random, difflib

PADD = os.path.expanduser('~/paddle-year')
jsons = glob.glob(f'{PADD}/*/*_described.json')
random.seed(1925)
sample = random.sample(jsons, 25)

def area(b): x0, y0, x1, y1 = b; return max(0, x1-x0) * max(0, y1-y0)
def inter(a, b):
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    return max(0, x1-x0) * max(0, y1-y0)

def fuzzy_contained(small, big, thresh=0.8):
    """Best-window similarity of small's text inside big's text."""
    s = ' '.join(small.split()).upper()
    g = ' '.join(big.split()).upper()
    if not s or not g or len(s) > len(g):
        return 0.0
    sm = difflib.SequenceMatcher(None, g, s, autojunk=False)
    matched = sum(n for _, _, n in sm.get_matching_blocks())
    return matched / len(s)

suppress_count = 0
pair_count = 0
examples = []
for j in sample:
    d = json.load(open(j))
    bl = [b for b in d['parsing_res_list']
          if b['block_label'] not in ('image', 'footer_image')
          and b['block_content'].strip()]
    suppressed = set()
    for i in range(len(bl)):
        for k in range(len(bl)):
            if i == k or bl[i]['block_id'] in suppressed:
                continue
            A, B = bl[i], bl[k]   # candidate duplicate A inside keeper B
            la, lb = len(A['block_content']), len(B['block_content'])
            if la > lb:
                continue
            ov = inter(A['block_bbox'], B['block_bbox'])
            if ov == 0 or ov / max(area(A['block_bbox']), 1) < 0.5:
                continue
            pair_count += 1
            score = fuzzy_contained(A['block_content'], B['block_content'])
            if score >= 0.8:
                suppressed.add(A['block_id'])
                suppress_count += 1
                if len(examples) < 12:
                    examples.append((os.path.basename(j)[:36], score,
                                     A['block_label'], A['block_content'][:50],
                                     B['block_content'][:50]))
    total_words = sum(len(b['block_content'].split()) for b in bl)
    dup_words = sum(len(b['block_content'].split()) for b in bl
                    if b['block_id'] in suppressed)
    if suppressed:
        print(f'{os.path.basename(j)[:44]}: suppress {len(suppressed)} blocks '
              f'({dup_words} of {total_words} words)')

print(f'\n25 pages: {pair_count} candidate pairs checked, '
      f'{suppress_count} blocks would be suppressed')
print('\nexamples (score, suppressed -> kept):')
for name, sc, lbl, a, b in examples:
    print(f'  {name} {sc:.2f} [{lbl}]')
    print(f'    SUPPRESS: {a!r}')
    print(f'    KEEP:     {b!r}')
