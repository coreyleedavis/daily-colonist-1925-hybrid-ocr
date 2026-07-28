#!/usr/bin/env python3
"""Phase 2 arbitration, step 2: ONE manual call. Crops the disputed region
from the decoded PNG, sends both readings + crop to the describer (Qwen), asks
for structured JSON verdict. Usage: arb_one.py <issue> <page> <index-in-jsonl>
Read-only against images; no outputs written."""
import base64, json, os, sys
import requests
import cv2

issue, page, idx = sys.argv[1], sys.argv[2], int(sys.argv[3])
item = [json.loads(l) for l in
        open(os.path.expanduser(f'~/solr-bridge/phase2/arb/{issue}_{page}.numeric.jsonl'))][idx]
IMG = os.path.expanduser(f'~/colonist-images/{issue}/{issue}_{page}.png')
img = cv2.imread(IMG)
assert img is not None, f'image not found/readable: {IMG}'
ih, iw = img.shape[:2]

# tess space -> png space: per-page factor from actual PNG dims vs tess page dims
# tess dims: read level-1 row
import csv
with open(os.path.expanduser(f'~/tess5-1925-full/{issue}/{issue}_{page}.tsv')) as f:
    r = csv.reader(f, delimiter='\t', quoting=csv.QUOTE_NONE)
    next(r)
    for row in r:
        if row[0] == '1':
            tw_, th_ = int(row[8]), int(row[9]); break
fx, fy = iw/tw_, ih/th_
x0, y0, x1, y1 = item['box_tess']
crop = img[max(0,int(y0*fy)):int(y1*fy), max(0,int(x0*fx)):int(x1*fx)]
print(f'crop: {crop.shape[1]}x{crop.shape[0]}px  (png {iw}x{ih}, tess {tw_}x{th_}, f={fx:.4f})')
ok, buf = cv2.imencode('.png', crop)
b64 = base64.b64encode(buf).decode()

prompt = (f"This is a cropped region from a 1925 Canadian newspaper (The Daily "
          f"Colonist, Victoria BC). Two OCR systems disagree about a number "
          f"printed in this crop. Reading A: \"{item['vlm']}\"  Reading B: "
          f"\"{item['tess']}\". Look at the printed characters carefully. "
          f"Respond with ONLY a JSON object, no other text: "
          f"{{\"verdict\": \"A\"|\"B\"|\"C\"|\"unreadable\", \"text\": \"the correct "
          f"reading\", \"confidence\": \"high\"|\"low\"}} — use C with your own "
          f"transcription in \"text\" only if both A and B are wrong.")

r = requests.post('http://localhost:8120/v1/chat/completions', json={
    'model': 'describer',
    'messages': [{'role': 'user', 'content': [
        {'type': 'image_url', 'image_url': {'url': f'data:image/png;base64,{b64}'}},
        {'type': 'text', 'text': prompt}]}],
    'max_tokens': 100, 'temperature': 0.0}, timeout=300)
r.raise_for_status()
raw = r.json()['choices'][0]['message']['content'].strip()
print(f"disagreement: vlm={item['vlm']!r} tess={item['tess']!r} conf={item['conf']}")
print(f'raw response: {raw!r}')
