#!/usr/bin/env python3
"""Phase 2: router simulation v2. New cascade:
  1 punct-normalize equal          -> auto
  2 tess conf < 50                 -> VLM
  3 tess truncation of VLM         -> VLM
  4 confusion-aware DICTIONARY vote -> dict side wins (external dict,
     american+british merged; pair must differ only by known confusions)
  5 plain dictionary vote           -> one side in dict, other not (no
     confusion constraint — catches bigger mangles like Tinh/Phantom)
  6 1925-lexicon proper-noun backstop -> conservative: one side freq>=20,
     other absent entirely, neither in ext dict (Esquimalt-class words)
  7 numeric                        -> image-arb band
  8 residual                       -> LLM-arb band
Read-only."""
import json, csv, os, difflib, string, re
from collections import Counter

PAGES = [('dailycolonist0525uvic_14', 'p005'),
         ('dailycolonist0525uvic_32', 'p030'),
         ('dailycolonist0725uvic_24', 'p015'),
         ('dailycolonist0525uvic_36', 'p011')]

# external dictionary (never touched by Tesseract)
DICT = set()
for p in ('/usr/share/dict/american-english', '/usr/share/dict/british-english'):
    with open(p, encoding='utf-8', errors='ignore') as f:
        for line in f:
            DICT.add(line.strip().lower())
print(f'external dict: {len(DICT)} entries')

# polluted 1925 lexicon, kept for proper-noun backstop only
LEX = {}
with open(os.path.expanduser('~/solr-bridge/lexicon_1925.tsv')) as f:
    for line in f:
        parts = line.split('\t')
        if len(parts) >= 2:
            try: LEX[parts[0].strip().lower()] = int(parts[1])
            except ValueError: pass
print(f'1925 lexicon: {len(LEX)} entries')

CONF_PAIRS = [('l','i'),('l','1'),('i','1'),('l','r'),('e','c'),('o','a'),
              ('o','0'),('h','b'),('n','u'),('m','w'),('t','f'),('s','5'),
              ('g','q'),('e','o'),('a','s')]
CONF = set()
for a, b in CONF_PAIRS:
    CONF.add((a,b)); CONF.add((b,a))
MULTI = [('rn','m'),('m','rn'),('vv','w'),('w','vv'),('cl','d'),('d','cl'),
         ('li','h'),('h','li')]

PUNCT = string.punctuation + '"\u201c\u201d\u2018\u2019\u2014\u2013'
def norm(s):
    s = s.replace('\u2019',"'").replace('\u2018',"'")
    s = s.replace('\u201c','"').replace('\u201d','"')
    return s.strip(PUNCT).upper()
def core_l(s): return norm(s).lower()
def is_num(s):
    c = norm(s)
    return bool(c) and bool(re.match(r'^[\d$.,¢%\-]+$', c)) and any(ch.isdigit() for ch in c)

def confusion_only(a, b):
    """True if a->b differs only via known confusion substitutions."""
    a, b = a.lower(), b.lower()
    if a == b: return False
    # try multi-char rewrites first (rn<->m etc.), greedy single pass
    for x, y in MULTI:
        a = a.replace(x, y) if a.replace(x, y) == b else a
    if a == b: return True
    if len(a) != len(b): return False
    return all(ca == cb or (ca, cb) in CONF for ca, cb in zip(a, b))

def get_disagreements(issue, page):
    TSV = os.path.expanduser(f'~/tess5-1925-full/{issue}/{issue}_{page}.tsv')
    VLMF = os.path.expanduser(f'~/paddle-year/{issue}/{issue}_{page}_described.json')
    vlm = json.load(open(VLMF))
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
                              'h': h, 'cx': l+w/2, 'cy': t+h/2})
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
        if blk['block_label'] in ('image','footer_image') or not blk['block_content'].strip():
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
    all_dis.extend(get_disagreements(issue, page))
print(f'{len(all_dis)} total disagreements\n')

bands = Counter(); residual = []
for vw, tt, conf in all_dis:
    nv, nt = norm(vw), norm(tt)
    cv, ct = core_l(vw), core_l(tt)
    if nv == nt:
        bands['1-punct-auto'] += 1; continue
    if conf < 50:
        bands['2-lowconf->vlm'] += 1; continue
    if nt and nv and nt != nv and nt in nv:
        bands['3-truncation->vlm'] += 1; continue
    v_dict, t_dict = cv in DICT, ct in DICT
    if confusion_only(ct, cv) and v_dict != t_dict:
        bands['4-confusion-dict->' + ('vlm' if v_dict else 'tess')] += 1; continue
    if v_dict != t_dict:
        bands['5-dict->' + ('vlm' if v_dict else 'tess')] += 1; continue
    if not v_dict and not t_dict:
        vf, tf = LEX.get(cv, 0), LEX.get(ct, 0)
        if vf >= 20 and tf == 0:
            bands['6-lex-backstop->vlm'] += 1; continue
        if tf >= 20 and vf == 0:
            bands['6-lex-backstop->tess'] += 1; continue
    if is_num(vw) or is_num(tt):
        bands['7-numeric->image-arb'] += 1; residual.append((vw, tt, conf, 'num')); continue
    bands['8-residual->llm-arb'] += 1; residual.append((vw, tt, conf, 'txt'))

n = len(all_dis)
print('cascade bands:')
for k in sorted(bands):
    print(f'  {k:26s} {bands[k]:5d} ({100*bands[k]/n:.1f}%)')
arb = sum(v for k, v in bands.items() if 'arb' in k)
print(f'\nARBITRATION WORKLOAD: {arb} of {n} ({100*arb/n:.1f}%) '
      f'-> extrapolated ~{arb//4*6647//1000}K corpus-wide')
print(f'\nresidual sample (first 30):')
for vw, tt, c, kind in residual[:30]:
    print(f'  [{kind}] vlm={vw!r:20s} tess={tt!r:20s} conf={c:5.1f}')
