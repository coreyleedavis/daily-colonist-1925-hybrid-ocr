#!/usr/bin/env python3
"""Phase 2: router simulation. Re-align the 4 test pages, classify every
disagreement through the cascade:
  1 punct/quote-normalize equal  -> auto (no arbitration)
  2 tess conf < 50               -> VLM wins (tess admits uncertainty)
  3 tess is truncation of VLM    -> VLM wins (substring carve-out, any conf)
  4 lexicon vote (1925 lexicon)  -> whichever side is a known word (other isn't)
  5 numeric                      -> image-arbitration band (no lexicon possible)
  6 residual                     -> LLM+image arbitration band
Also counts recurring-pair cache hits. Read-only."""
import json, csv, os, sys, difflib, string, re
from collections import Counter

PAGES = [('dailycolonist0525uvic_14', 'p005'),
         ('dailycolonist0525uvic_32', 'p030'),
         ('dailycolonist0725uvic_24', 'p015'),
         ('dailycolonist0525uvic_36', 'p011')]

LEX = os.path.expanduser('~/solr-bridge/lexicon_1925.tsv')
lexicon = set()
if os.path.exists(LEX):
    with open(LEX) as f:
        for line in f:
            t = line.split('\t')[0].strip().lower()
            if t: lexicon.add(t)
print(f'lexicon: {len(lexicon)} entries loaded')

PUNCT = string.punctuation + '"\u201c\u201d\u2018\u2019\u2014\u2013'
def norm(s):
    s = s.replace('\u2019', "'").replace('\u2018', "'")
    s = s.replace('\u201c', '"').replace('\u201d', '"')
    return s.strip(PUNCT).upper()
def core_l(s): return norm(s).lower()
def is_num(s):
    c = norm(s)
    return bool(c) and bool(re.match(r'^[\d$.,¢%\-]+$', c)) and any(ch.isdigit() for ch in c)

def get_disagreements(issue, page):
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
        for ln in lines: out.extend(sorted(ln, key=lambda w: w['cx']))
        return out
    out = []
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
        pos = 0
        for vw in vstr.split():
            s = vstr.index(vw, pos); e = s+len(vw); pos = e
            tidx = [v2t[k] for k in range(s, e) if v2t[k] is not None]
            owners = sorted({towner[k] for k in tidx if towner[k] is not None})
            if len(owners) != 1: continue
            w = tw[owners[0]]
            if w['text'].upper() != vw.upper():
                out.append((vw, w['text'], w['conf']))
    return out

all_dis = []
for issue, page in PAGES:
    d = get_disagreements(issue, page)
    all_dis.extend(d)
    print(f'{issue}_{page}: {len(d)} disagreements')

bands = Counter()
residual = []
pair_counter = Counter()
for vw, tt, conf in all_dis:
    if norm(vw) == norm(tt):
        bands['1-punct-auto'] += 1; continue
    pair_counter[(core_l(tt), core_l(vw))] += 1
    if conf < 50:
        bands['2-lowconf->vlm'] += 1; continue
    if norm(tt) and norm(vw) and norm(tt) != norm(vw) and norm(tt) in norm(vw):
        bands['3-truncation->vlm'] += 1; continue
    v_in = core_l(vw) in lexicon
    t_in = core_l(tt) in lexicon
    if v_in and not t_in:
        bands['4-lexicon->vlm'] += 1; continue
    if t_in and not v_in:
        bands['4-lexicon->tess'] += 1; continue
    if is_num(vw) or is_num(tt):
        bands['5-numeric->image-arb'] += 1; residual.append((vw, tt, conf, 'num')); continue
    bands['6-residual->llm-arb'] += 1
    residual.append((vw, tt, conf, 'txt'))

n = len(all_dis)
print(f'\n{n} total disagreements, cascade bands:')
for k in sorted(bands):
    print(f'  {k:22s} {bands[k]:5d} ({100*bands[k]/n:.1f}%)')

arb = bands['5-numeric->image-arb'] + bands['6-residual->llm-arb']
print(f'\nARBITRATION WORKLOAD: {arb} of {n} ({100*arb/n:.1f}%) '
      f'-> extrapolated ~{arb//4*6647//1000}K corpus-wide')

rep = {p: c for p, c in pair_counter.items() if c > 1}
rep_hits = sum(c for c in rep.values())
print(f'recurring pairs (pre-cascade, normalized): {len(rep)} pairs cover '
      f'{rep_hits} instances of {sum(pair_counter.values())}')
print('top repeats:', pair_counter.most_common(8))

print(f'\nsample of residual band (first 25):')
for vw, tt, c, kind in residual[:25]:
    print(f'  [{kind}] vlm={vw!r:20s} tess={tt!r:20s} conf={c:5.1f}')
