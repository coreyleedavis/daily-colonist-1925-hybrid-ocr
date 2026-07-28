#!/usr/bin/env python3
"""Index all ABBYY hOCR pages into colonist_abbyy. One doc per page,
file pointers, batches of 200, single commit at end."""
import glob, json, os, urllib.request

SOLR = 'http://localhost:8983/solr/colonist_abbyy/update'
files = sorted(glob.glob(os.path.expanduser('~/solr-bridge/ocr-data/abbyy/*.hocr')))
print(f'{len(files)} page files')

def post(docs, commit=False):
    url = SOLR + ('?commit=true' if commit else '')
    req = urllib.request.Request(url, data=json.dumps(docs).encode(),
                                 headers={'Content-Type': 'application/json'})
    return json.load(urllib.request.urlopen(req, timeout=300))['responseHeader']['status']

batch, done = [], 0
for f in files:
    page = os.path.basename(f).replace('.hocr', '')
    batch.append({'id': f'abbyy_{page}', 'page_id': page, 'source': 'abbyy',
                  'ocr_text': f'/ocr-data/abbyy/{page}.hocr'})
    if len(batch) >= 200:
        st = post(batch)
        assert st == 0, f'batch failed near {page}'
        done += len(batch); batch = []
        if done % 1000 == 0:
            print(f'{done}/{len(files)}...', flush=True)
if batch:
    assert post(batch) == 0
    done += len(batch)
st = post([], commit=True)
print(f'DONE: {done} docs indexed, commit status {st}')
