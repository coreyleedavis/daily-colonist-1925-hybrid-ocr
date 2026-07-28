#!/usr/bin/env python3
"""Build report_data.json: comprehensive no-ground-truth stats, 4 text arms
+ image descriptions. All arms ink-only, identical normalization/lexicon."""
import glob, html, json, os, re, time, urllib.parse, urllib.request
from collections import Counter, defaultdict

T0 = time.time()
OUT = os.path.expanduser('~/solr-bridge/phase2/report_data.json')
WORDS = [w.strip().lower() for w in open(os.path.expanduser(
    '~/solr-bridge/phase2/report_words.txt')) if w.strip()]
LEX = set()
for line in open(os.path.expanduser('~/solr-bridge/lexicon_1925.tsv')):
    w, c = line.rstrip('\n').split('\t')
    if int(c) >= 3: LEX.add(w)
DATES = json.load(open(os.path.expanduser('~/solr-bridge/.issue_dates.json')))
ALT = '\u21ff'

def norm(w):
    return re.sub(r"[^A-Za-z'-]", '', html.unescape(html.unescape(w))).lower()

def edit_le(a, b, k=3):
    if abs(len(a) - len(b)) > k: return False
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(cur[-1] + 1, prev[j] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > k: return False
        prev = cur
    return prev[-1] <= k

VARIANT_TARGETS = ['esquimalt', 'saanich', 'telephone', 'railway', 'victoria']

def analyze(name, stream):
    """stream yields (issue, page, word, conf_or_None). Returns metrics dict."""
    total = 0; vocab = Counter(); lens = Counter(); confs = Counter()
    rec = 0; checkable = 0
    wtok = Counter(); wpag = defaultdict(set); wmon = defaultdict(Counter)
    pages = set()
    for issue, page, w, conf in stream:
        total += 1
        pages.add((issue, page))
        a = norm(w)
        if len(a) >= 2:
            vocab[a] += 1
            lens[min(len(a), 20)] += 1
            if len(a) >= 4:
                checkable += 1
                if a in LEX: rec += 1
            if a in WSET:
                wtok[a] += 1
                wpag[a].add((issue, page))
                d = DATES.get(issue, {}).get('date')
                if d: wmon[a][d[:7]] += 1
        if conf is not None:
            confs[min(int(conf) // 10 * 10, 90)] += 1
    variants = {}
    for t in VARIANT_TARGETS:
        vs = [(v, c) for v, c in vocab.items()
              if v != t and abs(len(v) - len(t)) <= 3 and edit_le(v, t, 3) and c >= 3]
        variants[t] = sorted(vs, key=lambda x: -x[1])[:25]
    print(f'  {name}: {total:,} words, {len(pages):,} pages  [{time.time()-T0:.0f}s]', flush=True)
    return {'total_words': total, 'pages': len(pages), 'unique': len(vocab),
            'recognized_pct': round(100 * rec / checkable, 2) if checkable else 0,
            'hapax': sum(1 for c in vocab.values() if c == 1),
            'len_dist': dict(lens), 'conf_hist': dict(confs) or None,
            'word_tokens': dict(wtok),
            'word_pages': {k: len(v) for k, v in wpag.items()},
            'word_monthly': {k: dict(v) for k, v in wmon.items()},
            'variants': variants, 'vocab_keys_tmp': set(vocab)}

WSET = set(WORDS)

def stream_tess():
    for tsv in glob.glob(os.path.expanduser('~/tess5-1925-full/*/*.tsv')):
        issue = os.path.basename(os.path.dirname(tsv))
        page = os.path.basename(tsv).replace('.tsv', '').split('_')[-1]
        for line in open(tsv, errors='replace'):
            p = line.rstrip('\n').split('\t')
            if len(p) >= 12 and p[0] == '5' and p[11].strip():
                try: conf = float(p[10])
                except ValueError: conf = None
                yield issue, page, p[11], conf

def stream_vlm():
    for jf in glob.glob(os.path.expanduser('~/paddle-year/*/*_described.json')):
        base = os.path.basename(jf).replace('_described.json', '')
        issue, page = base.rsplit('_p', 1)[0], 'p' + base.rsplit('_p', 1)[1]
        j = json.load(open(jf))
        for b in j['parsing_res_list']:
            if b['block_label'] in ('image', 'footer_image'): continue
            for w in (b.get('block_content') or '').split():
                yield issue, page, w, None

def stream_abbyy():
    wre = re.compile(r'<span class="ocrx_word"[^>]*title="[^"]*x_wconf (\d+)[^"]*"[^>]*>(.*?)</span>', re.S)
    tagre = re.compile(r'<[^>]+>')
    for hf in glob.glob(os.path.expanduser('~/solr-bridge/ocr-data/abbyy/*.hocr')):
        base = os.path.basename(hf).replace('.hocr', '')
        issue, page = base.rsplit('_p', 1)[0], 'p' + base.rsplit('_p', 1)[1]
        data = open(hf, errors='replace').read()
        for m in wre.finditer(data):
            txt = tagre.sub('', m.group(2)).strip()
            if txt:
                yield issue, page, txt, float(m.group(1))

def stream_hybrid():
    for xf in glob.glob(os.path.expanduser('~/solr-bridge/ocr-data/phase2/*.miniocr.xml')):
        base = os.path.basename(xf).replace('.miniocr.xml', '')
        if '_p' not in base:
            continue
        issue, page = base.rsplit('_p', 1)[0], 'p' + base.rsplit('_p', 1)[1]
        for w in re.findall(r'<w x="[\d\- ]+">([^<]*)</w>', open(xf, errors='replace').read()):
            yield issue, page, w.split(ALT, 1)[0], None

out = {'generated': time.strftime('%Y-%m-%d %H:%M'), 'words': WORDS, 'arms': {}}
vocabs = {}
for name, s in (('tesseract', stream_tess), ('vlm', stream_vlm),
                ('abbyy', stream_abbyy), ('hybrid', stream_hybrid)):
    m = analyze(name, s())
    vocabs[name] = m.pop('vocab_keys_tmp')
    out['arms'][name] = m

# vocabulary overlap (pairwise + exclusives vs union)
names = list(vocabs)
union = set().union(*vocabs.values())
out['vocab_overlap'] = {
    'union': len(union),
    'sizes': {n: len(vocabs[n]) for n in names},
    'exclusive': {n: len(vocabs[n] - set().union(*(vocabs[m] for m in names if m != n)))
                  for n in names},
    'all_four': len(set.intersection(*vocabs.values()))}

# image descriptions: word table + monthly via Solr
def solrq(core, q):
    url = (f'http://localhost:8983/solr/{core}/select?q=' + urllib.parse.quote(q) + '&rows=0')
    return json.load(urllib.request.urlopen(url))['response']['numFound']
img = {'word_pages': {}, 'word_monthly': {}}
for w in WORDS:
    img['word_pages'][w] = solrq('colonist_phase2', f'image_desc:({w})')
out['image_desc'] = img
json.dump(out, open(OUT, 'w'))
print(f'written {OUT} ({os.path.getsize(OUT)/1e6:.1f}MB) in {time.time()-T0:.0f}s')
