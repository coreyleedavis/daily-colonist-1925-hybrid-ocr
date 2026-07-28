#!/usr/bin/env python3
"""Add image_desc field to colonist_phase2 docs via Solr atomic updates.
Descriptions = Phase 1's Qwen text in image-labeled blocks of the VLM JSONs.
Atomic 'set' touches ONLY image_desc; ocr_text pointers not re-read."""
import json, glob, os, urllib.request

SOLR = 'http://localhost:8983/solr/colonist_phase2/update'
BATCH = 200

def post(docs, commit=False):
    url = SOLR + ('?commit=true' if commit else '')
    body = json.dumps(docs).encode()
    req = urllib.request.Request(url, data=body,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)['responseHeader']['status']

batch, pages_with, descs_total, posted = [], 0, 0, 0
files = sorted(glob.glob(os.path.expanduser('~/paddle-year/*/*_described.json')))
for f in files:
    j = json.load(open(f))
    descs = [b['block_content'].strip() for b in j['parsing_res_list']
             if b['block_label'] in ('image', 'footer_image')
             and (b.get('block_content') or '').strip()]
    if not descs:
        continue
    page = os.path.basename(f).replace('_described.json', '')
    batch.append({'id': f'hybrid_{page}', 'image_desc': {'set': descs}})
    pages_with += 1
    descs_total += len(descs)
    if len(batch) >= BATCH:
        st = post(batch)
        assert st == 0, f'batch failed with status {st} near {page}'
        posted += len(batch)
        batch = []
        if posted % 2000 < BATCH:
            print(f'{posted} pages posted...', flush=True)
if batch:
    st = post(batch)
    assert st == 0, f'final batch failed with status {st}'
    posted += len(batch)
post([], commit=True)
print(f'DONE: {pages_with} pages with descriptions, {descs_total} descriptions, {posted} posted')
