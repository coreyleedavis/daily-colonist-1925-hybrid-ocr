#!/usr/bin/env python3
"""Hybrid corpus stats, methodology copied verbatim from Phase 1's
_text_stats/_lex3 so the three-way table compares like with like."""
import glob, html, json, os, re, time

t0 = time.time()
LEX = set()
for line in open(os.path.expanduser('~/solr-bridge/lexicon_1925.tsv')):
    w, c = line.rstrip('\n').split('\t')
    if int(c) >= 3: LEX.add(w)

ALT = '\u21ff'
total = 0
from collections import Counter
suspects = Counter()
uniq = set()
checkable = 0
rec = 0
files = glob.glob(os.path.expanduser('~/solr-bridge/ocr-data/phase2/*.miniocr.xml'))
for i, f in enumerate(sorted(files)):
    xml = open(f).read()
    words = [m.split(ALT, 1)[0] for m in re.findall(r'<w x="[\d\- ]+">([^<]*)</w>', xml)]
    total += len(words)
    for w in words:
        a = re.sub(r"[^A-Za-z'-]", '', html.unescape(html.unescape(w))).lower()
        if len(a) >= 2:
            uniq.add(a)
            if len(a) >= 4:
                checkable += 1
                if a in LEX: rec += 1
                else: suspects[a] += 1
    if (i + 1) % 1000 == 0:
        print(f'{i+1}/{len(files)} files...', flush=True)

out = {
    'generated': time.strftime('%Y-%m-%d %H:%M'),
    'elapsed_s': round(time.time() - t0),
    'hybrid': {
        'total_words': total,
        'unique': len(uniq),
        'recognized_pct': round(100.0 * rec / checkable, 2) if checkable else 0,
        'suspect_tokens': checkable - rec,
        'pages': len(files),
        'words_per_page': round(total / len(files)) if files else 0,
        'suspect_distinct': len(suspects)},
    'top_suspects_hybrid': suspects.most_common(300)}
path = os.path.expanduser('~/solr-bridge/phase2/corpus_stats_hybrid.json')
json.dump(out, open(path, 'w'), indent=1)
print(json.dumps(out, indent=1))
