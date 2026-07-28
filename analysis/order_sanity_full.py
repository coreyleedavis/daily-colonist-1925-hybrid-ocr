#!/usr/bin/env python3
"""Corpus-wide VLM order sanity: geometric regressions per page + label-aware
continuity. Outputs worst-page list = candidate set for order repair /
LLM escalation. Read-only."""
import json, glob, os

PADD = os.path.expanduser('~/paddle-year')
TITLES = {'paragraph_title', 'doc_title', 'header', 'number', 'figure_title',
          'vision_footnote'}

results = []
tot_pairs = tot_geo = tot_ms = tot_ms_ok = 0
for j in sorted(glob.glob(f'{PADD}/*/*_described.json')):
    d = json.load(open(j))
    bl = [b for b in d['parsing_res_list']
          if b['block_label'] not in ('image', 'footer_image')
          and (b.get('block_content') or '').strip()]
    geo = ms = ms_ok = 0
    for a, b in zip(bl, bl[1:]):
        tot_pairs += 1
        ax0, ay0, ax1, ay1 = a['block_bbox']
        bx0, by0, bx1, by1 = b['block_bbox']
        if by1 < ay0 - 20 and bx1 < ax0 - 20:
            geo += 1
        if a['block_label'] in TITLES or b['block_label'] in TITLES:
            continue
        at = a['block_content'].rstrip()
        bt = b['block_content'].lstrip()
        if at and (at[-1].islower() or at.endswith(',')):
            ms += 1
            if bt and bt[0].islower():
                ms_ok += 1
    tot_geo += geo; tot_ms += ms; tot_ms_ok += ms_ok
    if geo:
        results.append((geo, os.path.basename(j).replace('_described.json', '')))

print(f'{tot_pairs} pairs across {len(glob.glob(f"{PADD}/*/*_described.json"))} pages')
print(f'geometric regressions: {tot_geo} ({100*tot_geo/max(tot_pairs,1):.3f}%) '
      f'on {len(results)} pages')
print(f'text-block mid-sentence ends (titles excluded): {tot_ms}; '
      f'lowercase continuation: {tot_ms_ok} ({100*tot_ms_ok/max(tot_ms,1):.0f}%)')
results.sort(reverse=True)
print('\nworst pages by regression count:')
for g, p in results[:15]:
    print(f'  {g:3d}  {p}')
