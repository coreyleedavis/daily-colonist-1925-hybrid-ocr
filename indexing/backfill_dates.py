#!/usr/bin/env python3
"""Set issue_date on every doc in colonist_phase2 and colonist_abbyy from
.issue_dates.json via atomic updates. Idempotent."""
import json, os, urllib.request

DATES = json.load(open(os.path.expanduser('~/solr-bridge/.issue_dates.json')))

def post(core, docs):
    req = urllib.request.Request(
        f'http://localhost:8983/solr/{core}/update?commit=false',
        data=json.dumps(docs).encode(), headers={'Content-Type': 'application/json'})
    assert json.load(urllib.request.urlopen(req, timeout=120))['responseHeader']['status'] == 0

def ids(core, prefix):
    out, cursor = [], '*'
    while True:
        url = (f'http://localhost:8983/solr/{core}/select?q=*:*&rows=1000&fl=id'
               f'&sort=id+asc&cursorMark={urllib.parse.quote(cursor)}')
        d = json.load(urllib.request.urlopen(url, timeout=60))
        out += [x['id'] for x in d['response']['docs']]
        if d['nextCursorMark'] == cursor:
            return out
        cursor = d['nextCursorMark']

import urllib.parse
for core, prefix in (('colonist_phase2', 'hybrid_'), ('colonist_abbyy', 'abbyy_')):
    all_ids = ids(core, prefix)
    batch, done, skipped = [], 0, 0
    for i in all_ids:
        issue = i.replace(prefix, '').rsplit('_p', 1)[0]
        d = DATES.get(issue, {}).get('date')
        if not d:
            skipped += 1
            continue
        batch.append({'id': i, 'issue_date': {'set': d + 'T00:00:00Z'}})
        if len(batch) >= 500:
            post(core, batch); done += len(batch); batch = []
    if batch:
        post(core, batch); done += len(batch)
    urllib.request.urlopen(f'http://localhost:8983/solr/{core}/update?commit=true')
    print(f'{core}: {done} docs dated, {skipped} skipped (no date)')
