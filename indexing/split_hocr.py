#!/usr/bin/env python3
"""Split per-issue ABBYY hOCR into per-page .hocr files for the OCR plugin.
ppageno N -> pNNN (1-based). Verifies page count against our tess TSVs."""
import glob, os, re, sys

SRC = os.path.expanduser('~/colonist-abbyy-hocr')
DST = os.path.expanduser('~/solr-bridge/ocr-data/abbyy')
TESS = os.path.expanduser('~/tess5-1925-full')
os.makedirs(DST, exist_ok=True)

WRAP_HEAD = ("<?xml version='1.0' encoding='UTF-8'?>\n<html><head>"
             '<meta http-equiv="Content-Type" content="text/html;charset=utf-8"/>'
             '<meta name="ocr-system" content="LuraDocument XML Exporter for ABBYY FineReader"/>'
             '</head><body>\n')
WRAP_TAIL = '\n</body></html>\n'

total_pages, mismatches = 0, []
for path in sorted(glob.glob(f'{SRC}/*_hocr.html')):
    issue = os.path.basename(path).replace('_hocr.html', '')
    data = open(path, encoding='utf-8', errors='replace').read()
    # find page div start offsets
    starts = [m.start() for m in re.finditer(r'<div class="ocr_page"', data)]
    if not starts:
        mismatches.append((issue, 'no pages'))
        continue
    end_body = data.rfind('</body>')
    bounds = starts + [end_body if end_body > starts[-1] else len(data)]
    ours = len(glob.glob(f'{TESS}/{issue}/*.tsv'))
    if ours and ours != len(starts):
        mismatches.append((issue, f'ours={ours} hocr={len(starts)}'))
    for i in range(len(starts)):
        frag = data[bounds[i]:bounds[i+1]]
        # trim trailing junk after the page's closing (keep as-is; plugin tolerates)
        out = f'{DST}/{issue}_p{i+1:03d}.hocr'
        with open(out, 'w', encoding='utf-8') as f:
            f.write(WRAP_HEAD + frag + WRAP_TAIL)
        total_pages += 1
print(f'{total_pages} page files written to {DST}')
if mismatches:
    print(f'PAGE-COUNT MISMATCHES ({len(mismatches)}):')
    for m in mismatches[:10]:
        print(' ', m)
else:
    print('all issues match our page counts')
