#!/usr/bin/env python3
"""Download ONLY the *_hocr.html (ABBYY-converted) for the 312 1925 issues.
Resume-safe (skips complete files, size-verified vs metadata), 4 workers,
1s per-worker spacing. Output: ~/colonist-abbyy-hocr/<issue>_hocr.html"""
import json, os, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

OUT = os.path.expanduser('~/colonist-abbyy-hocr')
CACHE = os.path.expanduser('~/solr-bridge/phase2/ia_cache')
os.makedirs(OUT, exist_ok=True)
UA = {'User-Agent': 'UVicLibraries-hybrid-ocr-research/1.0 (contact: library systems)'}

ids = json.load(open(f'{CACHE}/issues.json'))
print(f'{len(ids)} issues')

def expected_size(item):
    with urllib.request.urlopen(urllib.request.Request(
            f'https://archive.org/metadata/{item}', headers=UA), timeout=30) as r:
        m = json.load(r)
    for f in m['files']:
        if f['name'] == f'{item}_hocr.html':
            return int(f['size'])
    return None

def fetch(item):
    dst = f'{OUT}/{item}_hocr.html'
    try:
        want = expected_size(item)
        if want is None:
            print(f'  {item}: NO HOCR FILE', flush=True)
            return 'missing'
        if os.path.exists(dst) and os.path.getsize(dst) == want:
            return 'cached'
        req = urllib.request.Request(
            f'https://archive.org/download/{item}/{item}_hocr.html', headers=UA)
        with urllib.request.urlopen(req, timeout=600) as r, open(dst + '.part', 'wb') as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
        got = os.path.getsize(dst + '.part')
        if got != want:
            print(f'  {item}: SIZE MISMATCH {got} vs {want}', flush=True)
            return 'mismatch'
        os.rename(dst + '.part', dst)
        time.sleep(1)
        return 'ok'
    except Exception as e:
        print(f'  {item}: ERROR {str(e)[:80]}', flush=True)
        return 'error'

from collections import Counter
results = Counter()
done = 0
with ThreadPoolExecutor(max_workers=4) as ex:
    for res in ex.map(fetch, ids):
        results[res] += 1
        done += 1
        if done % 25 == 0:
            print(f'{done}/{len(ids)}  {dict(results)}', flush=True)
print('FINAL:', dict(results))
