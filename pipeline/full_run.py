#!/usr/bin/env python3
"""Phase 2 FULL RUN: synthesize + index ALL pages into colonist_phase2.
Resumable (.full_done markers), quarantine + stats jsonl. Same harness as
smoke_run.py, no sampling. Usage: full_run.py"""
import json, glob, os, subprocess, sys, time
import urllib.request

PADD = os.path.expanduser('~/paddle-year')
TESS = os.path.expanduser('~/tess5-1925-full')
OUTD = os.path.expanduser('~/solr-bridge/phase2/out')
SERVE = os.path.expanduser('~/solr-bridge/ocr-data/phase2')
MARKD = os.path.expanduser('~/solr-bridge/phase2/.full_done')
QUAR = os.path.expanduser('~/solr-bridge/phase2/full_quarantine.jsonl')
STATS = os.path.expanduser('~/solr-bridge/phase2/full_stats.jsonl')
os.makedirs(MARKD, exist_ok=True)

jsons = sorted(glob.glob(f'{PADD}/*/*_described.json'))
print(f'{len(jsons)} pages total', flush=True)

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
for j in jsons:
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
    try:
        r = subprocess.run(['python3', os.path.expanduser('~/solr-bridge/phase2/synthesize.py'),
                            issue, page], capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        quarantine(base, 'synthesize-timeout')
        continue
    dt = time.time() - t0
    if r.returncode != 0:
        quarantine(base, 'synthesize-error', r.stderr[-300:])
        continue
    xml = f'{OUTD}/{base}.miniocr.xml'
    side = f'{OUTD}/{base}.provenance.json'
    if not (os.path.exists(xml) and os.path.getsize(xml) > 500):
        # degenerate-page check: is the INPUT also near-empty?
        tn = sum(1 for line in open(tsv) if line.split('\t')[0] == '5')
        if tn < 50:
            quarantine(base, 'degenerate-page', f'tess~{tn}w')
        else:
            quarantine(base, 'empty-output-RICH-INPUT', f'tess~{tn}w')
        continue
    s = json.load(open(side))
    n = len(s)
    provs = {}
    for w in s:
        provs[w['prov']] = provs.get(w['prov'], 0) + 1
    interp_frac = (provs.get('interp', 0) + provs.get('interp-shrapnel', 0)) / max(n, 1)
    anomalies = []
    if interp_frac > 0.9: anomalies.append(f'interp {interp_frac:.2f}')
    if dt > 30: anomalies.append(f'slow {dt:.0f}s')
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
        f.write(json.dumps({'page': base, 'words': n, 'secs': round(dt, 1),
                            'provs': provs, 'anomalies': anomalies}) + '\n')
    open(marker, 'w').close()
    done += 1
    if done % 200 == 0:
        el = time.time() - t_run
        rate = el / max(done, 1)
        eta = (len(jsons) - done - skipped) * rate / 60
        print(f'{done} done ({skipped} skipped) {el/60:.1f}min elapsed, '
              f'{rate:.1f}s/page, ~{eta:.0f}min left', flush=True)

req = urllib.request.Request(
    'http://localhost:8983/solr/colonist_phase2/update?commit=true',
    data=b'[]', headers={'Content-Type': 'application/json'})
urllib.request.urlopen(req, timeout=120)

# year-wide provenance summary
tot = {}
words = 0
for line in open(STATS):
    d = json.loads(line)
    words += d['words']
    for k, v in d['provs'].items():
        tot[k] = tot.get(k, 0) + v
nq = sum(1 for _ in open(QUAR)) if os.path.exists(QUAR) else 0
print(f'DONE: {done} pages ({skipped} skipped), {words} words, quarantine {nq}', flush=True)
for k in sorted(tot, key=lambda k: -tot[k]):
    print(f'  {k:18s} {tot[k]:9d} ({100*tot[k]/max(words,1):.1f}%)', flush=True)
