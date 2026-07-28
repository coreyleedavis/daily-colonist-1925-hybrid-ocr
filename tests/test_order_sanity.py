#!/usr/bin/env python3
"""Phase 2: how trustworthy is the VLM's parsing_res_list order?
Mechanical checks over sampled pages: (a) geometric regressions — successor
block starts far ABOVE and LEFT of predecessor (against column-flow), and
(b) mid-sentence breaks — block ends lowercase/comma and successor doesn't
continue lowercase. Read-only."""
import json, glob, os, random

PADD = os.path.expanduser('~/paddle-year')
jsons = glob.glob(f'{PADD}/*/*_described.json')
random.seed(1925)
sample = random.sample(jsons, 25)

tot_pairs = geo_viol = midsent = midsent_ok = 0
examples = []
for j in sample:
    d = json.load(open(j))
    bl = [b for b in d['parsing_res_list']
          if b['block_label'] not in ('image', 'footer_image')
          and (b.get('block_content') or '').strip()]
    for a, b in zip(bl, bl[1:]):
        tot_pairs += 1
        ax0, ay0, ax1, ay1 = a['block_bbox']
        bx0, by0, bx1, by1 = b['block_bbox']
        # geometric regression: successor entirely above AND left of predecessor
        if by1 < ay0 - 20 and bx1 < ax0 - 20:
            geo_viol += 1
            if len(examples) < 6:
                examples.append(('GEO', a['block_content'][:40], b['block_content'][:40]))
        # continuity: a ends mid-sentence?
        at = a['block_content'].rstrip()
        bt = b['block_content'].lstrip()
        if at and at[-1].islower() or at.endswith(','):
            midsent += 1
            if bt and bt[0].islower():
                midsent_ok += 1
            elif len(examples) < 6:
                examples.append(('SENT', at[-40:], bt[:40]))

print(f'{tot_pairs} consecutive block pairs across 25 pages')
print(f'geometric regressions (up-and-left successor): {geo_viol} ({100*geo_viol/tot_pairs:.1f}%)')
print(f'mid-sentence block ends: {midsent}; successor continues lowercase: '
      f'{midsent_ok} ({100*midsent_ok/max(midsent,1):.0f}%)')
print('\nexamples of violations:')
for kind, a, b in examples:
    print(f'  [{kind}] ...{a!r} -> {b!r}')
