#!/usr/bin/env python3
"""Phase 2: dedup v4. Change from v3: the score>=0.9 branch now measures
CONTIGUITY (longest single matching run / len(s)) instead of relying on the
majority-of-token mismatch test, which is blind to ed<=2 defects (Hartz) and
to scattered spurious matches (LAWRENCE SCOTT):
  contiguity >= 0.75 -> near-exact: token-compare for ed<=2 defect ->
      self-disagree if found; else suppress (len floor still guards shorts)
  contiguity < 0.5  -> spurious scatter -> demote to 'no'
  between           -> flag (uncertain)
Entity veto (concentrated big-ed mismatch) unchanged for 0.85-0.9 band.
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
    stub = m.group(1); prefix = s[:m.start()].strip()
    if len(prefix) < 12 or prefix not in g: return False
    tail = g[g.index(prefix)+len(prefix):].lstrip()
    return tail.startswith(stub)

def token_defects(s, g):
    """Compare s tokens to best-aligned g tokens; return list of (tok, ed<=2 partner)."""
    stoks = re.findall(r"[A-Z']+", s)
    gtoks = re.findall(r"[A-Z']+", g)
    defects = []
    for st in stoks:
        if st in gtoks: continue
        best = min(gtoks, key=lambda gt: edit_dist(st, gt), default=None)
        if best is None: return None
        d = edit_dist(st, best)
        if d == 0: continue
        if d <= 2: defects.append((st, best, d))
        else: return None          # big-ed token -> not a self-disagreement
    return defects

def analyze(small, big):
    s, g = squash(small), squash(big)
    if not s or len(s) > len(g): return 0, 'no', ''
    if s in g and len(s) >= 8:
        return 1.0, 'suppress', 'exact containment'
    if hyphen_stub(small, big):
        return 1.0, 'suppress', 'hyphen-stub completion'
    sm = difflib.SequenceMatcher(None, g, s, autojunk=False)
    blocks_m = sm.get_matching_blocks()
    score = sum(n for _, _, n in blocks_m) / len(s)
    contig = max((n for _, _, n in blocks_m), default=0) / len(s)
    if score >= 0.9:
        if contig < 0.5:
            return score, 'no', f'spurious scatter (contig {contig:.2f})'
        if contig >= 0.75:
            defects = token_defects(s, g)
            if defects:
                det = ', '.join(f'{a}~{b} ed={d}' for a, b, d in defects)
                return score, 'self-disagree', det
            if defects is not None and len(s) >= 8:
                return score, 'suppress', f'near-exact (contig {contig:.2f})'
        return score, 'flag', f'high score, mid contig {contig:.2f}'
    if score < 0.85 or len(s) < 25:
        return score, 'no' if score < 0.7 else 'flag', 'below floor'
    matched = [False]*len(s)
    for _, b, n in blocks_m:
        for k in range(n): matched[b+k] = True
    bad = [m.group() for m in re.finditer(r'[A-Z]+', s)
           if sum(not matched[k] for k in range(m.start(), m.end())) > len(m.group())/2]
    if len(bad) == 1:
        d = min((edit_dist(bad[0], c) for c in re.findall(r'[A-Z]+', g)), default=99)
        if d > 2: return score, 'veto-entity', f'{bad[0]} ed={d}'
        return score, 'self-disagree', f'{bad[0]} ed={d}'
    if bad: return score, 'veto-entity', f'{len(bad)} mismatched tokens'
    return score, 'suppress', 'fuzzy 0.85-0.9, clean'

verdicts = {'suppress': [], 'self-disagree': [], 'veto-entity': [], 'flag': [], 'no': []}
demoted = []
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
            rec = (os.path.basename(j)[:36], score, detail,
                   A['block_content'][:45], B['block_content'][:45])
            if verdict == 'no' and 'scatter' in detail:
                demoted.append(rec)
            elif verdict in ('suppress', 'self-disagree', 'veto-entity', 'flag'):
                verdicts[verdict].append(rec)

for v in ('suppress', 'self-disagree', 'veto-entity', 'flag'):
    print(f'=== {v}: {len(verdicts[v])} ===')
    for name, sc, det, a, b in verdicts[v]:
        print(f'  {name} {sc:.2f} ({det})')
        print(f'    A: {a!r}')
        print(f'    B: {b!r}')
    print()
print(f'=== demoted as spurious scatter: {len(demoted)} ===')
for name, sc, det, a, b in demoted:
    print(f'  {name} {sc:.2f} ({det})  A: {a!r}')
