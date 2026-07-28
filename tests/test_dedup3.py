#!/usr/bin/env python3
"""Phase 2: dedup v3. Two surgical changes from v2:
  1. GUARD REORDER: when fuzzy score >= 0.9, run concentrated-mismatch /
     edit-distance analysis BEFORE the length floor — so short near-identical
     pairs (Hartz/Martz) reach the self-disagree detector instead of dying
     at the floor. Floor still applies to sub-0.9 scores (kills 'The
     Canadian' disease).
  2. HYPHEN-STUB rule: if A ends mid-word with a hyphen and B contains A's
     prefix plus a completion of the stub word -> suppress A confidently
     (VLM emitted a broken window + a complete line of the same table row).
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

def hyphen_stub(small, big):
    s, g = squash(small), squash(big)
    m = re.search(r'([A-Z]+)-$', s)
    if not m: return False
    stub = m.group(1)
    prefix = s[:m.start()].strip()
    if len(prefix) < 12 or prefix not in g: return False
    # does g continue the prefix with a word starting with the stub?
    tail = g[g.index(prefix)+len(prefix):].lstrip()
    return tail.startswith(stub)

def mismatch_analysis(s, g, sm):
    """Return ('self-disagree'|'veto-entity'|'clean', detail)."""
    matched = [False]*len(s)
    for _, b, n in sm.get_matching_blocks():
        for k in range(n): matched[b+k] = True
    bad = []
    for m in re.finditer(r'[A-Z]+', s):
        span = range(m.start(), m.end())
        if sum(not matched[k] for k in span) > len(m.group())/2:
            bad.append(m.group())
    if not bad: return 'clean', ''
    if len(bad) == 1:
        cands = re.findall(r'[A-Z]+', g)
        d = min((edit_dist(bad[0], c) for c in cands), default=99)
        return ('self-disagree' if d <= 2 else 'veto-entity'), f'{bad[0]} ed={d}'
    return 'veto-entity', f'{len(bad)} mismatched tokens'

def analyze(small, big):
    s, g = squash(small), squash(big)
    if not s or len(s) > len(g): return 0, 'no', ''
    if s in g and len(s) >= 8:
        return 1.0, 'suppress', 'exact containment'
    if hyphen_stub(small, big):
        return 1.0, 'suppress', 'hyphen-stub completion'
    sm = difflib.SequenceMatcher(None, g, s, autojunk=False)
    score = sum(n for _, _, n in sm.get_matching_blocks()) / len(s)
    if score >= 0.9:                        # CHANGE 1: analysis before floor
        kind, detail = mismatch_analysis(s, g, sm)
        if kind == 'self-disagree':
            return score, 'self-disagree', detail
        if kind == 'veto-entity':
            return score, 'veto-entity', detail
        if len(s) >= 25:
            return score, 'suppress', 'fuzzy>=0.9, clean'
        return score, 'flag', 'short but clean-high'
    if score < 0.85 or len(s) < 25:
        return score, 'no' if score < 0.7 else 'flag', 'below floor'
    kind, detail = mismatch_analysis(s, g, sm)
    if kind == 'veto-entity':
        return score, 'veto-entity', detail
    if kind == 'self-disagree':
        return score, 'self-disagree', detail
    return score, 'suppress', 'fuzzy 0.85-0.9, clean'

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
