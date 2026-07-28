#!/usr/bin/env python3
"""Phase 2: dedup v2 — conservative. Suppress ONLY when confident:
  A. exact containment after whitespace/case normalization (any length >= 8), or
  B. fuzzy >= 0.85 AND len >= 25 AND mismatch is NOT a different-entity signal
     (concentrated alpha-token mismatch with edit distance > 2 -> VETO, keep both)
Middle band -> keep both + FLAG. Edit-distance<=2 concentrated mismatches are
logged as VLM SELF-DISAGREEMENTS (Hartz/Martz class) -> alternatives candidates.
Report-only. Read-only."""
import json, glob, os, random, difflib, re

PADD = os.path.expanduser('~/paddle-year')
jsons = glob.glob(f'{PADD}/*/*_described.json')
random.seed(1925)
sample = random.sample(jsons, 25)

def area(b): x0, y0, x1, y1 = b; return max(0, x1-x0)*max(0, y1-y0)
def inter(a, b):
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    return max(0, x1-x0)*max(0, y1-y0)
def squash(s): return ' '.join(s.split()).upper()

def edit_dist(a, b):
    if abs(len(a)-len(b)) > 4: return 99
    dp = list(range(len(b)+1))
    for i, ca in enumerate(a, 1):
        prev, dp[0] = dp[0], i
        for j, cb in enumerate(b, 1):
            prev, dp[j] = dp[j], min(dp[j]+1, dp[j-1]+1, prev + (ca != cb))
    return dp[-1]

def analyze(small, big):
    """Return (score, verdict, detail). Verdicts: suppress / veto-entity /
    flag / self-disagree(+suppress)."""
    s, g = squash(small), squash(big)
    if not s or len(s) > len(g): return 0, 'no', ''
    if s in g and len(s) >= 8:
        return 1.0, 'suppress', 'exact containment'
    sm = difflib.SequenceMatcher(None, g, s, autojunk=False)
    score = sum(n for _, _, n in sm.get_matching_blocks()) / len(s)
    if score < 0.85 or len(s) < 25:
        return score, 'no' if score < 0.7 else 'flag', 'below floor'
    # locate mismatched tokens of s
    matched = [False]*len(s)
    for _, b, n in sm.get_matching_blocks():
        for k in range(n): matched[b+k] = True
    bad_tokens = []
    for m in re.finditer(r'[A-Z]+', s):
        span = range(m.start(), m.end())
        if sum(not matched[k] for k in span) > len(m.group())/2:
            bad_tokens.append(m.group())
    if not bad_tokens:
        return score, 'suppress', 'fuzzy, no concentrated mismatch'
    if len(bad_tokens) == 1:
        # find nearest token in g to compare edit distance
        cands = re.findall(r'[A-Z]+', g)
        d = min((edit_dist(bad_tokens[0], c) for c in cands), default=99)
        if d <= 2:
            return score, 'self-disagree', f'{bad_tokens[0]} ed={d}'
        return score, 'veto-entity', f'{bad_tokens[0]} ed={d}'
    return score, 'veto-entity', f'{len(bad_tokens)} mismatched tokens'

verdicts = {'suppress': [], 'self-disagree': [], 'veto-entity': [], 'flag': []}
for j in sample:
    d = json.load(open(j))
    bl = [b for b in d['parsing_res_list']
          if b['block_label'] not in ('image', 'footer_image')
          and b['block_content'].strip()]
    for i in range(len(bl)):
        for k in range(len(bl)):
            if i == k: continue
            A, B = bl[i], bl[k]
            if len(A['block_content']) > len(B['block_content']): continue
            ov = inter(A['block_bbox'], B['block_bbox'])
            if ov == 0 or ov/max(area(A['block_bbox']), 1) < 0.5: continue
            score, verdict, detail = analyze(A['block_content'], B['block_content'])
            if verdict in verdicts:
                verdicts[verdict].append(
                    (os.path.basename(j)[:36], score, detail,
                     A['block_content'][:45], B['block_content'][:45]))

for v in ('suppress', 'self-disagree', 'veto-entity', 'flag'):
    print(f'=== {v}: {len(verdicts[v])} ===')
    for name, sc, det, a, b in verdicts[v]:
        print(f'  {name} {sc:.2f} ({det})')
        print(f'    A: {a!r}')
        print(f'    B: {b!r}')
    print()
