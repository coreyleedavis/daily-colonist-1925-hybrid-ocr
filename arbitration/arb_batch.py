#!/usr/bin/env python3
"""Phase 2 arbitration, step 3: batch-arbitrate one page's numeric band with
full guardrails. Verdicts + rejections -> arb/<page>.verdicts.jsonl (audit
log). Guardrails: strict JSON parse (strip fences/leakage), verdict whitelist,
C-verdict edit-distance cap vs BOTH inputs, tiny-crop upscale. Read-only
against sources. Usage: arb_batch.py <issue> <page>"""
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

OUT = JSONL.replace('.numeric.jsonl', '.verdicts.jsonl')
results = []
for it in items:
    x0, y0, x1, y1 = it['box_tess']
    crop = img[max(0,int(y0*fy)):int(y1*fy), max(0,int(x0*fx)):int(x1*fx)]
    if crop.shape[0] < 60:
        s = 3
        crop = cv2.resize(crop, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
    ok, buf = cv2.imencode('.png', crop)
    b64 = base64.b64encode(buf).decode()
    prompt = (f"This is a cropped region from a 1925 Canadian newspaper (The Daily "
              f"Colonist, Victoria BC). Two OCR systems disagree about a number "
              f"printed in this crop. Reading A: \"{it['vlm']}\"  Reading B: "
              f"\"{it['tess']}\". Look at the printed characters carefully. "
              f"Respond with ONLY a JSON object, no other text: "
              f"{{\"verdict\": \"A\"|\"B\"|\"C\"|\"unreadable\", \"text\": \"the correct "
              f"reading\", \"confidence\": \"high\"|\"low\"}} — use C with your own "
              f"transcription in \"text\" only if both A and B are wrong.")
    try:
        r = requests.post('http://localhost:8120/v1/chat/completions', json={
            'model': 'describer',
            'messages': [{'role': 'user', 'content': [
                {'type': 'image_url', 'image_url': {'url': f'data:image/png;base64,{b64}'}},
                {'type': 'text', 'text': prompt}]}],
            'max_tokens': 100, 'temperature': 0.0}, timeout=300)
        r.raise_for_status()
        raw = r.json()['choices'][0]['message']['content'].strip()
    except Exception as e:
        results.append({**it, 'status': 'call-failed', 'detail': str(e)[:120]})
        continue
    m = re.search(r'\{.*\}', raw, re.S)   # strip any leakage around the JSON
    v = None
    if m:
        try: v = json.loads(m.group())
        except json.JSONDecodeError: pass
    if not v or v.get('verdict') not in ('A', 'B', 'C', 'unreadable'):
        results.append({**it, 'status': 'unparseable', 'raw': raw[:150]})
        continue
    rec = {**it, 'status': 'ok', 'verdict': v['verdict'],
           'text': v.get('text', ''), 'llm_conf': v.get('confidence', '?')}
    if v['verdict'] == 'C':
        t = v.get('text', '')
        if not t or min(edit_dist(t, it['vlm']), edit_dist(t, it['tess'])) > 3:
            rec['status'] = 'C-rejected-editcap'
    results.append(rec)
    print(f"vlm={it['vlm']!r:12s} tess={it['tess']!r:12s} -> "
          f"{rec.get('verdict','-'):10s} {rec.get('text',''):12s} "
          f"[{rec['status']}]", flush=True)

with open(OUT, 'w') as f:
    for r_ in results:
        f.write(json.dumps(r_) + '\n')
from collections import Counter
print('\nsummary:', dict(Counter(r_['status'] for r_ in results)))
print('verdicts:', dict(Counter(r_.get('verdict', '-') for r_ in results)))
print(f'audit log: {OUT}')
