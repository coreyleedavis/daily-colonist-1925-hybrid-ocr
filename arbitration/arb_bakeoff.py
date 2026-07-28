#!/usr/bin/env python3
"""Phase 2 judge bake-off: same 16 crops, N candidates, ¢-instrument scoring.
Candidates: ollama models (native /api/chat with images) + tesseract-whitelist
baseline. Usage: arb_bakeoff.py <issue> <page>"""
import base64, csv, json, os, re, subprocess, sys, tempfile
import requests
import cv2

issue, page = sys.argv[1], sys.argv[2]
items = [json.loads(l) for l in
         open(os.path.expanduser(f'~/solr-bridge/phase2/arb/{issue}_{page}.numeric.jsonl'))]
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

PROMPT = ("This is a small cropped region from a 1925 Canadian newspaper. "
          "Transcribe EXACTLY the printed characters you see — typically a "
          "number, price, or figure. Preserve every symbol as printed "
          "(¢, $, commas, periods). Respond with ONLY a JSON object, no other "
          "text: {\"transcription\": \"...\", \"legible\": true|false}")

def crop_png(it):
    x0, y0, x1, y1 = it['box_tess']
    c = img[max(0,int(y0*fy)):int(y1*fy), max(0,int(x0*fx)):int(x1*fx)]
    if c.shape[0] < 60:
        c = cv2.resize(c, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    ok, buf = cv2.imencode('.png', c)
    return bytes(buf)

def ask_ollama(model, png):
    r = requests.post('http://localhost:11434/api/chat', json={
        'model': model, 'stream': False,
        'think': False,
        'messages': [{'role': 'user', 'content': PROMPT,
                      'images': [base64.b64encode(png).decode()]}],
        'options': {'temperature': 0.0, 'num_predict': 200}}, timeout=600)
    r.raise_for_status()
    return r.json()['message']['content'].strip()

def ask_tess(png):
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
        f.write(png); path = f.name
    try:
        out = subprocess.run(
            ['tesseract', path, 'stdout', '--psm', '7',
             '-c', 'tessedit_char_whitelist=0123456789$.,;:¢-'],
            capture_output=True, text=True, timeout=60)
        return json.dumps({'transcription': out.stdout.strip(), 'legible': True})
    finally:
        os.unlink(path)

def canon(s): return str(s).strip('.,;: ').replace(' ', '')

def score(name, ask):
    print(f'=== {name}')
    verdicts = []
    for it in items:
        png = crop_png(it)
        try:
            raw = ask(png)
        except Exception as e:
            print(f"  vlm={it['vlm']!r:12s} tess={it['tess']!r:12s} CALL-FAILED {str(e)[:60]}")
            verdicts.append('fail'); continue
        m = re.search(r'\{.*\}', raw, re.S)
        t = ''
        if m:
            try: t = str(json.loads(m.group()).get('transcription', ''))
            except json.JSONDecodeError: pass
        if not t or not any(c.isdigit() for c in t):
            v = 'unreadable'
        elif canon(t) == canon(it['vlm']): v = 'vlm'
        elif canon(t) == canon(it['tess']): v = 'tess'
        else: v = 'C'
        cent = ' [¢-CASE]' if '¢' in it['vlm'] + it['tess'] and canon(it['vlm']).rstrip('¢c') == canon(it['tess']).rstrip('¢c') else ''
        print(f"  vlm={it['vlm']!r:12s} tess={it['tess']!r:12s} saw={t!r:14s} -> {v}{cent}")
        verdicts.append(v)
    from collections import Counter
    print(f'  summary: {dict(Counter(verdicts))}\n')

score('tesseract-whitelist-3x', ask_tess)
score('qwen3-vl:8b', lambda png: ask_ollama('qwen3-vl:8b', png))
score('deepseek-ocr', lambda png: ask_ollama('deepseek-ocr', png))
score('openbmb/minicpm-v4.5', lambda png: ask_ollama('openbmb/minicpm-v4.5', png))
score('qwen3-vl:32b', lambda png: ask_ollama('qwen3-vl:32b', png))
