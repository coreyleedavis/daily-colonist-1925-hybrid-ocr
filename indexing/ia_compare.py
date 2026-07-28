#!/usr/bin/env python3
"""Batch ABBYY-layer (Internet Archive) match counts for the 1925 Colonist.
Per-item search-inside API, 1 req/sec politeness, response cache on disk.
Usage: ia_compare.py <query> [query ...]
Output: phase2/ia_abbyy_counts.json  {query: {pages, issues, ts}}"""
import json, os, sys, time, urllib.parse, urllib.request

CACHE = os.path.expanduser('~/solr-bridge/phase2/ia_cache')
OUT = os.path.expanduser('~/solr-bridge/phase2/ia_abbyy_counts.json')
os.makedirs(CACHE, exist_ok=True)

def fetch_json(url, timeout=60):
    req = urllib.request.Request(url, headers={'User-Agent':
        'UVicLibraries-hybrid-ocr-research/1.0 (contact: library systems)'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)

def issues_1925():
    cf = f'{CACHE}/issues.json'
    if os.path.exists(cf):
        return json.load(open(cf))
    d = fetch_json('https://archive.org/advancedsearch.php?q=' +
        urllib.parse.quote('collection:dailycolonist AND date:[1925-01-01 TO 1925-12-31]') +
        '&fl[]=identifier&rows=400&output=json')
    ids = sorted(x['identifier'] for x in d['response']['docs'])
    json.dump(ids, open(cf, 'w'))
    return ids

def item_loc(item):
    cf = f'{CACHE}/{item}.loc.json'
    if os.path.exists(cf):
        return json.load(open(cf))
    m = fetch_json(f'https://archive.org/metadata/{item}')
    loc = {'server': m['server'], 'dir': m['dir']}
    json.dump(loc, open(cf, 'w'))
    time.sleep(1)
    return loc

def search_item(item, q):
    cf = f'{CACHE}/{item}.q.{urllib.parse.quote(q, safe="")}.json'
    if os.path.exists(cf):
        return json.load(open(cf))
    loc = item_loc(item)
    url = (f"https://{loc['server']}/fulltext/inside.php?item_id={item}"
           f"&doc={item}&path={urllib.parse.quote(loc['dir'])}&q={urllib.parse.quote(q)}")
    try:
        d = fetch_json(url)
    except Exception as e:
        d = {'error': str(e)[:100], 'matches': []}
    json.dump(d, open(cf, 'w'))
    time.sleep(1)
    return d

def count(q, ids, workers=4):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    pages, issues, errors, done = set(), set(), [0], [0]
    lock = threading.Lock()
    def one(item):
        d = search_item(item, q)
        pp = {p.get('page') for m in d.get('matches', []) for p in m.get('par', [])}
        pp.discard(None)
        with lock:
            if 'error' in d:
                errors[0] += 1
            if pp:
                issues.add(item)
                for p in pp:
                    pages.add((item, p))
            done[0] += 1
            if done[0] % 50 == 0:
                print(f'  {done[0]}/{len(ids)} issues... ({len(pages)} pages so far)', flush=True)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, ids))
    return {'pages': len(pages), 'issues': len(issues), 'errors': errors[0],
            'ts': time.strftime('%Y-%m-%d %H:%M')}

ids = issues_1925()
print(f'{len(ids)} issues enumerated')
out = json.load(open(OUT)) if os.path.exists(OUT) else {}
for q in sys.argv[1:]:
    print(f'query: {q}')
    out[q] = count(q, ids)
    print(f'  -> {out[q]}')
    json.dump(out, open(OUT, 'w'), indent=1)
print(f'written: {OUT}')
