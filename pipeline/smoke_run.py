#!/usr/bin/env python3
"""Phase 2 smoke run: synthesize + index N random pages with tripwires.
Resumable (.done markers), failures -> quarantine.jsonl, per-page stats ->
smoke_stats.jsonl. Hard failures (exception, empty output, index error)
quarantine the page and continue. Soft anomalies logged, not fatal.
Usage: smoke_run.py <n_pages>"""
import json, glob, os, random, subprocess, sys, time
import urllib.request

N = int(sys.argv[1])
PADD = os.path.expanduser('~/paddle-year')
TESS = os.path.expanduser('~/tess5-1925-full')
OUTD = os.path.expanduser('~/solr-bridge/phase2/out')
SERVE = os.path.expanduser('~/solr-bridge/ocr-data/phase2')
MARKD = os.path.expanduser('~/solr-bridge/phase2/.smoke_done')
QUAR = os.path.expanduser('~/solr-bridge/phase2/smoke_quarantine.jsonl')
STATS = os.path.expanduser('~/solr-bridge/phase2/smoke_stats.jsonl')
os.makedirs(MARKD, exist_ok=True)

jsons = sorted(glob.glob(f'{PADD}/*/*_described.json'))
random.seed(42)   # different seed than diagnostics (1925) — fresh pages
sample = random.sample(jsons, N)

def post_doc(base):
    body = json.dumps([{'id': f'hybrid_{base}', 'source': 'hybrid',
                        'ocr_text': f'/ocr-data/phase2/{base}.miniocr.xml'}]).encode()
    req = urllib.request.Request(
        'http://localhost:8983/solr/colonist_phase2/update',
        data=body, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)['responseHeader']['status']

def quarantine(base, reason, detail=''):
    with open(QUAR, 'a') as f:
        f.write(json.dumps({'page': base, 'reason': reason,
                            'detail': str(detail)[:300]}) + '\n')
    print(f'QUARANTINE {base}: {reason}', flush=True)

done = skipped = 0
t_run = time.time()
for j in sample:
    base = os.path.basename(j).replace('_described.json', '')
    issue = os.path.dirname(j).split('/')[-1]
    page = base.replace(issue + '_', '')
    marker = f'{MARKD}/{base}'
    if os.path.exists(marker):
        skipped += 1
        continue
    tsv = f'{TESS}/{issue}/{issue}_{page}.tsv'
    if not os.path.exists(tsv):
        quarantine(base, 'no-tsv')
        continue
    t0 = time.time()
    r = subprocess.run(['python3', os.path.expanduser('~/solr-bridge/phase2/synthesize.py'),
                        issue, page], capture_output=True, text=True, timeout=300)
    dt = time.time() - t0
    if r.returncode != 0:
        quarantine(base, 'synthesize-error', r.stderr[-300:])
        continue
    xml = f'{OUTD}/{base}.miniocr.xml'
    side = f'{OUTD}/{base}.provenance.json'
    if not (os.path.exists(xml) and os.path.getsize(xml) > 500):
        quarantine(base, 'empty-output')
        continue
    # tripwires (soft): parse sidecar
    s = json.load(open(side))
    n = len(s)
    vlm_words = sum(len((b.get('block_content') or '').split())
                    for b in json.load(open(j))['parsing_res_list']
                    if b['block_label'] != 'image')
    provs = {}
    for w in s:
        provs[w['prov']] = provs.get(w['prov'], 0) + 1
    interp_frac = (provs.get('interp', 0) + provs.get('interp-shrapnel', 0)) / max(n, 1)
    anomalies = []
    if vlm_words and not (0.5 <= n / vlm_words <= 2.0):
        anomalies.append(f'word-ratio {n}/{vlm_words}')
    if interp_frac > 0.9:
        anomalies.append(f'interp {interp_frac:.2f}')
    if dt > 30:
        anomalies.append(f'slow {dt:.0f}s')
    # index
    try:
        subprocess.run(['cp', xml, SERVE + '/'], check=True)
        st = post_doc(base)
        if st != 0:
            quarantine(base, 'index-error', st)
            continue
    except Exception as e:
        quarantine(base, 'index-exception', e)
        continue
    with open(STATS, 'a') as f:
        f.write(json.dumps({'page': base, 'words': n, 'vlm_words': vlm_words,
                            'secs': round(dt, 1), 'interp_frac': round(interp_frac, 3),
                            'anomalies': anomalies}) + '\n')
    open(marker, 'w').close()
    done += 1
    if done % 25 == 0:
        el = time.time() - t_run
        print(f'{done}/{N} done ({skipped} skipped) {el:.0f}s elapsed '
              f'({el/max(done,1):.1f}s/page)', flush=True)

# final commit
req = urllib.request.Request(
    'http://localhost:8983/solr/colonist_phase2/update?commit=true',
    data=b'[]', headers={'Content-Type': 'application/json'})
urllib.request.urlopen(req, timeout=60)
print(f'DONE: {done} pages, {skipped} skipped, quarantine: '
      f'{sum(1 for _ in open(QUAR)) if os.path.exists(QUAR) else 0}', flush=True)
