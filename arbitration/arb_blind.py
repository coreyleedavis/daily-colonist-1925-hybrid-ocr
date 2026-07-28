#!/usr/bin/env python3
"""Phase 2 arbitration v3: BLIND transcription protocol (position-bias fix —
the choice framing itself was biased; 14/16 verdicts followed the A slot under
label swap). No candidates in the prompt; verdict computed by comparing the
model's transcription to both candidates in code.
Usage: arb_blind.py <issue> <page> [jsonl]"""
import base64, csv, json, os, re, sys
import requests
import cv2

issue, page = sys.argv[1], sys.argv[2]
JSONL = (sys.argv[3] if len(sys.argv) > 3 else
         os.path.expanduser(f'~/solr-bridge/phase2/arb/{issue}_{page}.numeric.jsonl'))
items = [json.loads(l) for l in open(JSONL)]
IMG = os.path.expanduser(f'~/colonist-images/{issue}/{issue}_{page}.png')
img = cv2.imread(IMG)
assert img is not None
ih, iw = img.shape[:2]
with open(os.path.expanduser(f'~/tess5-1925-full/{issue}/{issue}_{page}.tsv')) as f:
    r = csv.reader(f, delimiter='\t', quoting=csv.QUOTE_NONE)
    next(r)
    for row in r:
        if row[0] == '1':
            tw_, th_ = int(row[8]), int(row[9]); break
fx, fy = iw/tw_, ih/th_

def edit_dist(a, b):
    dp = list(range(len(b)+1))
    for i, ca in enumerate(a, 1):
        prev, dp[0] = dp[0], i
        for j, cb in enumerate(b, 1):
            prev, dp[j] = dp[j], min(dp[j]+1, dp[j-1]+1, prev + (ca != cb))
    return dp[-1]

def canon(s):
    return s.strip('.,;: ').replace(' ', '')

PROMPT = ("This is a small cropped region from a 1925 Canadian newspaper (The "
          "Daily Colonist, Victoria BC). Transcribe EXACTLY the printed "
          "characters you see — typically a number, price, or figure. Preserve "
          "every symbol as printed (¢, $, commas, periods). Respond with ONLY "
          "a JSON object, no other text: {\"transcription\": \"...\", "
          "\"legible\": true|false}")

OUT = JSONL.replace('.numeric.jsonl', '.blind_verdicts.jsonl')
results = []
for it in items:
    x0, y0, x1, y1 = it['box_tess']
    crop = img[max(0,int(y0*fy)):int(y1*fy), max(0,int(x0*fx)):int(x1*fx)]
    if crop.shape[0] < 60:
        crop = cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    ok, buf = cv2.imencode('.png', crop)
    b64 = base64.b64encode(buf).decode()
    try:
        r = requests.post('http://localhost:8120/v1/chat/completions', json={
            'model': 'describer',
            'messages': [{'role': 'user', 'content': [
                {'type': 'image_url', 'image_url': {'url': f'data:image/png;base64,{b64}'}},
                {'type': 'text', 'text': PROMPT}]}],
            'max_tokens': 80, 'temperature': 0.0}, timeout=300)
        r.raise_for_status()
        raw = r.json()['choices'][0]['message']['content'].strip()
    except Exception as e:
        results.append({**it, 'status': 'call-failed', 'detail': str(e)[:120]})
        continue
    m = re.search(r'\{.*\}', raw, re.S)
    v = None
    if m:
        try: v = json.loads(m.group())
        except json.JSONDecodeError: pass
    if not v or 'transcription' not in v:
        results.append({**it, 'status': 'unparseable', 'raw': raw[:150]})
        continue
    t = str(v['transcription'])
    if not v.get('legible', True) or not any(c.isdigit() for c in t):
        verdict = 'unreadable'
    elif canon(t) == canon(it['vlm']):
        verdict = 'vlm'
    elif canon(t) == canon(it['tess']):
        verdict = 'tess'
    elif min(edit_dist(canon(t), canon(it['vlm'])),
             edit_dist(canon(t), canon(it['tess']))) <= 3:
        verdict = 'C'
    else:
        verdict = 'C-rejected-editcap'
    rec = {**it, 'status': 'ok', 'transcription': t, 'verdict': verdict}
    results.append(rec)
    print(f"vlm={it['vlm']!r:12s} tess={it['tess']!r:12s} saw={t!r:12s} -> {verdict}",
          flush=True)

with open(OUT, 'w') as f:
    for r_ in results:
        f.write(json.dumps(r_) + '\n')
from collections import Counter
print('\nverdicts:', dict(Counter(r_.get('verdict', r_['status']) for r_ in results)))
print(f'audit log: {OUT}')
