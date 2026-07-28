# Daily Colonist 1925 — Phase 2: Unified Hybrid Pipeline — state as of 2026-07-15

## GOAL
Combine Tesseract's measured word-level geometry with PaddleOCR-VL's superior
text/layout understanding into ONE hybrid OCR arm — pixel-accurate highlighting,
better recall/accuracy than either engine alone — indexed in Solr, viewed in a
single Mirador page. Route genuine disagreements between the two engines to an
LLM for arbitration (informed by the source image, not just the two competing
text strings).

## HARD RULE — ISOLATION FROM PHASE 1
Phase 1 (state: ~/PROJECT_STATE.md) is DEMO-READY for a committee/paper and MUST
NOT BE TOUCHED, MODIFIED, OR PLACED AT RISK by any Phase 2 work. Concretely:
- Read-only, never written to: ~/tess5-1925-full (ALTO), ~/paddle-year (raw VLM
  JSONs — described as immutable in Phase 1 notes too), ~/colonist-images,
  existing MiniOCR (~/solr-bridge/ocr-data/{vlm,corr}).
- Existing Solr core `colonist` (schema, synonyms file, analyzer chain) and its
  three existing `source` values (tesseract, paddleocr-vl, paddleocr-vl-corrected)
  are untouched. Phase 2 hybrid output goes into a NEW source value or, more
  safely, a SEPARATE Solr core, to make accidental cross-contamination structurally
  impossible rather than just a matter of care.
- Live shim (app.py on 8888) untouched until Phase 2 is validated. New viewer routes
  built/tested on a different port/script, merged in deliberately later, same
  diff-before-deploy discipline as Phase 1 (recall the Phase 1 near-miss where a
  parallel session had diverged app.py ahead of staging — blind copy would have
  destroyed work).
- All new code/data lives under ~/solr-bridge/phase2/, kept obviously separate,
  git-tracked distinctly.
This rule was stated explicitly by the user before any diagnostic commands were run
and applies to every future step in this project.

## RESEARCH FINDINGS THAT SHAPED THE ARCHITECTURE (2026-07-15 session)

### 1. The alignment problem has prior art, but the "ground truth" framing doesn't apply
Initial framing: align VLM text (no coordinates) onto Tesseract text (has
coordinates) using sequence alignment, treating Tesseract-with-boxes as the
positional anchor. Relevant technique: Needleman-Wunsch dynamic-programming
sequence alignment (from bioinformatics), used in:
  - Microsoft's `genalog` library (github: microsoft/genalog) — character-level
    NW alignment between clean ground-truth text and noisy OCR text.
  - DDMAL text_alignment project (github: DDMAL/text_alignment) — NW with affine
    gap penalties, aligns a "correct transcript" (no positions) to "messy OCR"
    (has positions), donating OCR bounding boxes to the correct transcript's
    characters. Structurally the closest published precedent to what we want to
    do with Tesseract-boxes + VLM-text.
CORRECTION MADE MID-SESSION: user pointed out we have no ground truth — both
Tesseract and PaddleOCR-VL are "OCR", neither is authoritative. Resolution: the
NW/dynamic-programming alignment ALGORITHM is agnostic to which side is "truth" —
it just finds the lowest-cost correspondence between two symbol sequences. The
"ground truth" framing in genalog/DDMAL is specific to THEIR application, not a
requirement of the algorithm. The correct analogy for two independently-
error-prone hypothesis streams is ROVER (Recognizer Output Voting Error
Reduction), from speech recognition: multiple ASR hypotheses (none of which is
truth) are aligned via dynamic programming into a word transition network, then
voted on per position. Ensemble-OCR literature (e.g. a dual-engine drug-label OCR
fusion paper, ScienceDirect) does the equivalent for two OCR engines.
CONCLUSION: alignment (step 1) produces agree/disagree correspondence regardless
of which engine is more accurate. Deciding WHICH reading to trust at each
disagreement is a separate, later step (not implied by alignment itself).
PRACTICAL NOTE: with two noisy streams (vs. one noisy + one clean), plain
equal-cost Levenshtein/NW may misalign more often on real OCR confusions
(rn<->m, l<->1<->I, O<->0). Worth using OCR-aware substitution costs (cheap cost
for known confusable pairs) rather than uniform cost, especially valuable here
since Tesseract's error profile (character-shape confusion) and PaddleOCR-VL's
error profile (semantic/plausible-word hallucination, per Phase 1 findings) are
DIFFERENT — meaning disagreements between them are more informative than
disagreements between two similarly-failing engines would be.

### 2. Image-only text is not an alignment problem
Qwen describer / VLM blocks that have NO corresponding Tesseract text at all
(ads, photos, illustrations Tesseract never recognized as text-bearing) cannot be
aligned — there is no second sequence to align against, not just a hard case.
DECISION: handle as a structurally separate class. Detect via zero block-overlap
with any Tesseract region on the page. Use PaddleOCR-VL's own native layout box
(no better coordinate source exists). Tag with distinct provenance (e.g.
"image-block"/"describer") so it is searchable but:
  (a) excluded from lexicon/word-frequency stats (this exact blending is what
      polluted Phase 1 corpus stats — describer vocabulary like "stylized" leaked
      into recognized-word counts),
  (b) never sent through disagreement arbitration against a Tesseract reading
      that structurally doesn't exist (this matches the known Phase 1 corrector
      bug: corrector must skip image blocks — top of the Phase 1 leftover queue,
      never fixed, now a hard requirement for Phase 2 too, not just an aspiration).

### 3. LLM-based correction/arbitration — real risk of making things worse
Literature is genuinely split, and the caution outweighs the optimism for
zero-shot use:
  - Sheffield (Thomas, Gaizauskas, Lu; ACL LT4HALA 2024) fine-tuned Llama 2 on
    BLN600 (19th c. British newspapers): 54.51% character-error-rate reduction,
    vs. 23.30% for fine-tuned BART. BUT this is a FINE-TUNED model on a matched
    historical-newspaper corpus, not a general-purpose zero-shot LLM call.
  - Multiple sources report the opposite for out-of-the-box general LLMs:
    unprompted Llama-3 8B "would almost always retain many errors, or insert
    unwanted new information" (Medium/Andornot writeup); a cited study found
    general LLMs "not good at correcting transcriptions of historical documents
    of any kind," sometimes DEGRADING accuracy rather than improving it.
  - A 2025 arXiv study ("OCR Error Post-Correction with LLMs in Historical
    Documents: No Free Lunches") specifically flags response-leakage as a
    concrete failure mode — preamble/postamble text ("Here is your corrected
    text:") polluting output if not stripped.
  - Prompting with socio-cultural/era context ("This is a newspaper from 1800s
    England...") measurably improves correction accuracy and named-entity
    fidelity (Bourne 2024, cited in a survey) — cheap, should be standard
    practice in the arbitration prompt.
This directly echoes Phase 1's own hard-won finding: "VLMs fail toward plausible
modern semantics, not noise" — an LLM correction/arbitration pass has the exact
same failure mode (wants text to "sound right," dangerous on 1925 orthography,
proper nouns, ad copy). This is the strongest argument for disagreement-ROUTING
(LLM only sees the small fraction of text where engines already disagree) over
whole-page LLM correction (which the literature says is actively risky).
GUARDRAILS TO BUILD (not yet implemented):
  - Era/genre context in every arbitration prompt.
  - Structured output only (pick engine A's reading / pick engine B's reading /
    supply C) — never freeform prose, both to prevent leakage into the index and
    to make edit-distance sanity-checking possible.
  - Include the image crop in the arbitration call (multimodal) so the LLM is
    judging against the actual page, not guessing between two text strings.
  - Edit-distance cap: if the LLM's answer diverges wildly from BOTH inputs,
    discard it and fall back to the higher-confidence/more-trusted engine rather
    than trusting a free invention.
  - Audit log of every arbitration decision (mirrors Phase 1's audit.jsonl
    pattern) for a human eyeball pass — Phase 1 found frequency-ranked QA is
    blind to pages that fail entirely, so spot-checking stays in the loop here too.
  - Corrector must SKIP image-only blocks (see #2 above) — known Phase 1 bug,
    now a load-bearing requirement, not just a fix to backport.

## DIAGNOSTIC FINDINGS (verified on-server, read-only checks, 2026-07-15)

### Tesseract TSV confidence — CONFIRMED PRESENT
File checked: dailycolonist0525uvic_14/dailycolonist0525uvic_14_p014.tsv
Standard Tesseract TSV columns: level, page_num, block_num, par_num, line_num,
word_num, left, top, width, height, conf, text.
Levels 1-4 (page/block/par/line) always show conf = -1 (not meaningful at those
levels). REAL per-word confidence is at level 5. Verified with awk -F'\t' '$1==5':
values are real and track real errors, e.g. "JHE" (masthead, should be "THE")
scored 60.5; a garbled fragment "Se" scored 32.5; correctly-read words like
"DAILY", "COLONIST.", "VICTORIA," scored 90-96. Confirms conf is a usable
per-word trust signal on the Tesseract side.

### PaddleOCR-VL JSON — NO per-word transcription confidence
File checked: dailycolonist0525uvic_14/dailycolonist0525uvic_14_p005_described.json
Top-level keys: input_path, page_index, page_count, width, height,
model_settings, parsing_res_list, layout_det_res.
- parsing_res_list[i]: block_label, block_content (text), block_bbox, block_id,
  block_order, group_id, block_polygon_points. NO confidence field.
- layout_det_res.boxes[i]: cls_id, label, score, coordinate, order,
  polygon_points. Has a "score" field (e.g. 0.719 for a "header" block) — but
  this is LAYOUT-DETECTION confidence ("how sure the model is this region is a
  text block of type X"), NOT transcription confidence ("how sure it is the
  words inside are correct"). Confirmed these are semantically different things,
  not a usable substitute.
Generative/VLM-style OCR generally doesn't expose per-token confidence the way
classic OCR does, short of requesting logprobs from the model-serving layer.
paddlevl container serves via vLLM, which CAN expose token-level logprobs via an
OpenAI-compatible logprobs request param — but this is NOT currently captured in
saved JSONs and would require re-running inference (new GPU time, changes how
the pipeline calls the existing paddlevl API). PARKED, not in scope now.

### DECISION — confidence signal is ASYMMETRIC, use as router not comparator
Because only Tesseract has real per-word confidence, the original "compare
confidence scores from both engines" design doesn't work as sketched — it's
"Tesseract confidence vs. nothing," not "confidence vs. confidence."
Simplified rule adopted for now:
  - Tesseract HIGH confidence + VLM disagrees -> lean Tesseract (it already told
    us it's probably right).
  - Tesseract LOW confidence + VLM disagrees -> route to LLM+image-crop
    arbitration. This is exactly the case where VLM's contextual understanding
    is expected to add value, and where Tesseract itself is uncertain.
This keeps the design simple and buildable now without new GPU inference runs.
PARKED explicitly for future revisit: vLLM logprobs on paddlevl for a genuine
two-sided confidence comparison, if arbitration volume or quality ends up
demanding it.

## PROPOSED PIPELINE (design only — NOT YET BUILT)
1. Segment: per page region, classify as (a) both engines have text here ->
   align, or (b) only VLM/describer has content here -> no alignment, tag as
   image-derived, use VLM's native box.
2. Align (a)-class regions at word/line level via NW-family dynamic-programming
   alignment, ideally with OCR-aware substitution costs.
3. Resolve agreements immediately — no LLM call needed, cheapest and most
   reliable path (this will be the majority of text).
4. Resolve disagreements via the confidence-router above: Tesseract-high ->
   trust Tesseract; Tesseract-low -> LLM+image arbitration with full guardrails
   (era context, structured output, edit-distance cap, audit log).
5. Merge into a single hybrid MiniOCR stream, every span provenance-tagged
   (agree / tesseract-trusted / llm-arbitrated / image-block).
6. Index into a NEW Solr source or separate core; build/verify a new viewer
   route in isolation; only merge into the live shim after explicit
   diff-and-verify, matching Phase 1's deployment discipline.

## COMPLETED SO FAR
- Isolation ground rule established and agreed (2026-07-15).
- Confirmed Tesseract TSV per-word confidence exists and is meaningful (level 5).
- Confirmed PaddleOCR-VL JSON has no usable per-word transcription confidence;
  layout_det_res.score is a different signal (layout, not transcription).
- Confidence-router design decision made and documented.
- All checks performed read-only; nothing written to Phase 1 data, config, core,
  or shim.

## NEXT
- Look at a real Tesseract vs. PaddleOCR-VL disagreement side by side on one
  page (not yet done) to see concretely what disagreement looks like before
  writing any alignment code.
- Then: prototype word/line alignment on a single known page, still entirely
  read-only against source data, output written only under
  ~/solr-bridge/phase2/.

## Session update 2026-07-15 — model review, scale check, regrouping proven, MAJOR Tesseract dropout found

### Plan review (Fable pass + literature sanity check) — refinements adopted
1. SCALE MISMATCH (latent bug caught pre-build): Tesseract TSV coords are full-res
   JP2 space; VLM bboxes are 2560px-downscale space. Regrouping must normalize
   PER PAGE (dims drift: p014=7466x9542, p005=7450x9526). Verified p005: factor
   2.9102 on width, 2.9105 on height — uniform scale, aspect ratios match.
2. GOLD SET (was missing from plan): hand-transcribe 20-30 blocks across 4-5 varied
   pages BEFORE pipeline output exists (contamination-proof), including reading-order
   judgments. Gives real WER/retrieval metrics vs tess-alone/vlm-alone/hybrid for
   committee + paper. Parallel track, not a blocker.
3. DEHYPHENATION SPLIT (was over-serialized): within-block dehyphenation (most cases)
   needs no reading order — runs right after alignment, Phase 1 gates + dictionary
   check on rejoined form. Only cross-block (column-spanning) cases wait for
   reading-order step.
4. ⇿ ALTERNATIVES (major de-risk, found in sanity check): solr-ocrhighlighting
   supports alternative readings at the same token position (MiniOCR marker U+21FF,
   index-time expansion, both forms searchable w/ full highlighting). Disagreements
   need NOT be destructive either/or: index BOTH readings, arbitration only picks
   primary/display form. Wrong LLM pick no longer costs recall. Connects to parked
   Phase 1 item (OcrAlternativesFilter / ALTO alternatives).
   TO CHECK: does MiniOCR have a hyphenation representation (one word, two boxes)?
   ALTO natively does (plugin de-hyphenates ALTO). May tip hybrid output format
   toward ALTO over MiniOCR. Desk-check before format freeze.
5. READING ORDER SIMPLIFIED: VLM's parsing_res_list sequence is already a
   semantically-informed order (p005 eyeball: stories flow correctly). Use it as
   the prior; cheap geometric/continuity sanity checks; LLM escalation only for
   flagged pages. Same hybrid philosophy as Armenian-newspaper paper, less code.
   Gold set must include order judgments to verify this trust corpus-wide.
6. block_label ROUTING: 'image' blocks = describer prose (never align/dehyphenate/
   text-flow). 'vision_footnote' = real caption text Tesseract may have read — DOES
   go through alignment. Route on label, not just geometry.

### Regrouping PROVEN on the motivating case (p005)
Center-point-in-bbox with per-page scaling: RECEIVERS (85.2), HERE (83.6), and
OFGREATLINE| (21.3) — scattered across Tesseract's own reading order — all landed
inside the one VLM doc_title block 'RECEIVERS HERE\nOF GREAT LINE'. Also note:
3 tess tokens vs 5 VLM words — OFGREATLINE| is a FUSED tess word (wide-spaced
display type). Coordinate donation there = split one measured box character-
proportionally across VLM words (still far tighter than Phase 1 whole-block
interpolation). Char-level NW handles fusions natively. Earlier guess that S<&/,
~, "SI; belonged to this headline was WRONG — they fall outside this bbox
("SI; is plausibly '51 from the Seattle headline). Coordinates beat stream-order
inference.
Scripts: ~/solr-bridge/phase2/test_regroup.py, test_coverage.py (read-only).

### HARD-WON: csv.QUOTE_NONE
Python csv.reader default quote handling SILENTLY ATE ~1/3 of TSV rows (1925
newspaper text is full of double quotes -> reader hunts for closing quote,
swallows tabs/newlines/rows). Output looked plausible (914 words, clean stats).
awk referee check exposed it. ALWAYS csv.QUOTE_NONE for Tesseract TSVs, and
sanity-check parsed counts vs awk. Also: final TSV row can be a whitespace
"word" with page-sized bbox at conf 95 — filter whitespace-only tokens.

### p005 coverage stats (fixed parser)
1,679 non-whitespace tess words: 91.4% in exactly 1 VLM block, 7.9% in 0 blocks,
0.7% in 2+ blocks. Clean-path fraction is high; edge cases tractable.

### MAJOR FINDING — Tesseract dropped ~40% of p005 text entirely
53 of 144 VLM text blocks contain ZERO tesseract words — including ORDINARY
EDITORIAL BODY TEXT: GOODALL/BROWN/BURRIDGE obituaries, Anderson story body
('aboriginal paddles...'), regimental continuations. grep across ALL FOUR
Tesseract output formats (hocr/tsv/txt/xml-ALTO, same run 2026-06-18): zero
occurrences of GOODALL|BURRIDGE|aboriginal. NOT a parser/file problem — Tesseract
layout analysis skipped whole mid-page regions (partial column swallows: CODY/
STROYAN captured, GOODALL/BROWN/BURRIDGE same column = absent). TSV ends
normally at page bottom (169 blocks), so run completed.
Word totals p005: VLM text blocks 3,039 words; Tesseract 1,773 (ratio 0.58).
Page's Phase 1 corpus avg would predict ~2,950 tess words — this page was already
an underperformer, invisibly.
CONSEQUENCES:
- Validates Phase 1 finding (7) at its sharpest: frequency-ranked QA is blind to
  whole-region failures. "Burridge" search silently misses this page in the tess
  arm. Concrete paper example.
- "VLM-only" class is NOT just ads/images — it includes editorial text. Bigger
  than designed for.
- Hybrid output mixes coordinate qualities: provenance must distinguish
  'measured' (aligned tess box) vs 'interpolated' (VLM-only regions, Phase 1
  method as fallback). Highlight precision visibly differs; be honest about it.
- 42->91 tess words sit inside 'image'-label blocks (e.g. Dr. Chase's ad):
  Tesseract read text where VLM classified image. Routing must handle this
  (likely: keep tess words, tag distinctly; do NOT align against describer prose).

### NEXT
- Word-level alignment prototype within regrouped blocks (char-level NW, OCR-aware
  costs) on p005: target OFGREATLINE| -> OF GREAT LINE with split measured box.
- Quantify 0-block tess words + tess-words-in-image-blocks handling.
- Check dropout rate on 2-3 more pages (is 0.58 an outlier or common?).
- Gold set start. MiniOCR hyphen-representation desk check.

## Session update 2026-07-15 (cont.) — tess-only class sized, orphan gates, block overlap

### Describer-leak check: CLEAN
Qwen description prose ("The image is/depicts...") appears ONLY in image-label
blocks — 0 leaks across 26 pages. VLM word counts (text-blocks-only) stand.
Full label census (26 pp): text 84644, image 8566 (describer), paragraph_title
1901, vision_footnote 1065, doc_title 942, table 296, header 287, number 26,
figure_title 12, footer_image 0. Router: everything except image/footer_image
is alignable page text; table needs special handling (Phase 1: HTML markup,
em-dash fusing); vision_footnote is REAL caption text, align it.

### High-tail explained: VLM has its own dropout mode
dailycolonist0925uvic_35_p005 (ratio 1.29): 214 orphan tess words (6.6%) in NO
VLM block — includes real headlines ('Prince Makes Stop to Plant Tree') and ad
copy (Maynard's Shoe Store + address). Plus 339 tess words (10.4%) inside
image-label blocks (VLM described regions Tesseract READ, e.g. ads). Each
engine drops what the other catches — cleanest one-line case for the hybrid.

### Tess-only class SIZED corpus-wide (26-page sample, 68,047 words)
orphan 8.0% + in-image 3.0% = ~11% of tess words have no VLM text home.
Structural, not garnish. NOTE: dailycolonist0925uvic_17_p014 = 39.6% orphans
despite "healthy" 0.93 word ratio — ratio metric masks two-sided dropout
(engines missing DIFFERENT regions). Orphan rate > ratio as a diagnostic.
That page goes in the gold set.

### Orphan quality gates (tested on 0925uvic_35_p005)
Word-level conf separates weakly (real median 87 vs noise 65, quartiles overlap
heavily). CLUSTER-level median conf separates strongly: coherent clusters 92-97,
junk clusters 14-49. GATE DESIGN: cluster first (2D gap clustering — naive
y-only fuses across columns, needs x-awareness), then filter clusters by median
conf + has-alnum; middle band (~70s) -> lexicon vote + 'low-confidence'
provenance flag. Some orphans are BOTH-engines-failed regions (weather table
fragments — same region class as the Phase 1 emoji incident); no pipeline
recovers text neither engine read. Gold set should include one such region to
quantify 'unrecoverable' honestly.

### Block overlap (25 pages): 816 touching pairs, 31 with >50% containment
TWO phenomena: (1) GENUINE DUPLICATION — VLM transcribed same text twice
(standalone headline block + same line repeated inside larger block; e.g.
'MR. J. S. McKINNON' twice; 'Hartz Speeds Up' vs 'Martz Speeds Up' — VLM
DISAGREES WITH ITSELF on re-reads, free confidence signal + tess box can
arbitrate spelling). Without dedup: doubled index text, doubled hit counts,
inflated VLM word totals (true dropout marginally worse than measured).
(2) LEGITIMATE NESTING — captions in photo regions, headline/subhead, table
columns. No dedup wanted there.
REGROUPER RULES (evidence-backed): dedup contained-duplicate blocks (prefix/
substring of overlapping block -> keep more complete); assign multi-home tess
words by text match then nearest-center; cluster-then-filter orphans.

### Design gap logged (for reading-order step)
Tess-only synthetic blocks have no position in parsing_res_list (= the
reading-order backbone). Need geometric insertion rule (after VLM block
above/left). Also: tess words in image-label regions get indexed alongside —
NOT aligned against — describer prose, distinct provenance.

### NEXT
- Alignment prototype (queued): OFGREATLINE| -> OF GREAT LINE, measured box
  split 3 ways. test_align.py written, not yet run.
- Then: dedup prototype; orphan 2D clustering; gold set (include 0925uvic_17_p014
  + a both-engines-failed weather region).

## Session update 2026-07-15 (cont.) — alignment prototype PASSES

### test_align.py result (RECEIVERS block, p005) — all success criteria hit
tess stream 'RECEIVERS HERE OFGREATLINE|' vs vlm 'RECEIVERS HERE OF GREAT LINE':
- RECEIVERS, HERE -> whole measured boxes inherited (prov=measured)
- OF/GREAT/LINE -> proportional slices of the ONE fused tess box
  (x=2718/2814/3055, w=96/240/192 tracking 2/5/4 chars, shared y/h;
  prov=measured-split)
- trailing '|' garbage auto-excluded: nothing in VLM stream aligned to it —
  ALIGNMENT ITSELF IS THE GARBAGE FILTER (no separate noise pass needed for
  aligned regions).
Core Phase 2 mechanism demonstrated: VLM text wearing Tesseract geometry.
What was OFGREATLINE| (conf 21, unsearchable) = 3 clean words w/ measured boxes.

### Prototype caveats (honest limits)
One short block; benign error pattern (fusion only, no substitutions);
difflib+casefold stands in for NW with OCR-aware costs; assumed single tess
owner per VLM word (real pages: chars aligning across two tess words, plus
genuine substitution disagreements — Hartz/Martz class — not present in this
block).

### NEXT
1. Full-page alignment on p005: every text block, stats (%measured/split/
   unmatched per VLM word) + dump actual disagreements found = first real look
   at what arbitration faces.
2. Dedup prototype (contained-duplicate blocks).
3. Orphan 2D clustering (x-aware, not y-only).
4. Gold set: include 0925uvic_17_p014 (39.6% orphans) + a both-engines-failed
   weather region.
5. Still parked: MiniOCR hyphen-representation desk check (before format freeze).

## Session update 2026-07-15 (cont.) — alignment prototype PASSES

### test_align.py result (RECEIVERS block, p005) — all success criteria hit
tess stream 'RECEIVERS HERE OFGREATLINE|' vs vlm 'RECEIVERS HERE OF GREAT LINE':
- RECEIVERS, HERE -> whole measured boxes inherited (prov=measured)
- OF/GREAT/LINE -> proportional slices of the ONE fused tess box
  (x=2718/2814/3055, w=96/240/192 tracking 2/5/4 chars, shared y/h;
  prov=measured-split)
- trailing '|' garbage auto-excluded: nothing in VLM stream aligned to it —
  ALIGNMENT ITSELF IS THE GARBAGE FILTER (no separate noise pass needed for
  aligned regions).
Core Phase 2 mechanism demonstrated: VLM text wearing Tesseract geometry.
What was OFGREATLINE| (conf 21, unsearchable) = 3 clean words w/ measured boxes.

### Prototype caveats (honest limits)
One short block; benign error pattern (fusion only, no substitutions);
difflib+casefold stands in for NW with OCR-aware costs; assumed single tess
owner per VLM word (real pages: chars aligning across two tess words, plus
genuine substitution disagreements — Hartz/Martz class — not present in this
block).

### NEXT
1. Full-page alignment on p005: every text block, stats (%measured/split/
   unmatched per VLM word) + dump actual disagreements found = first real look
   at what arbitration faces.
2. Dedup prototype (contained-duplicate blocks).
3. Orphan 2D clustering (x-aware, not y-only).
4. Gold set: include 0925uvic_17_p014 (39.6% orphans) + a both-engines-failed
   weather region.
5. Still parked: MiniOCR hyphen-representation desk check (before format freeze).

## Session update 2026-07-15 (cont.) — full-page alignment run + diagnosis

### align_page.py v1 -> v2: line-clustering bug found and fixed
v1 quantized cy into fixed ~145 tess-px buckets — merged 3-4 body-text lines
(~30-40px line heights), sorted merged lines by x, SCRAMBLED the tess stream.
Symptom in dump: 'Product'/'animals'/'Inventor' all "matching" tess 'past' —
nonsense pairings = scrambled-stream signature. difflib is order-sensitive.
v2: adaptive line clustering (0.6 x median word height per block). RULE: line
grouping must adapt to block's own type size, headlines != body text.

### p005 full-page results (v2)
3,039 VLM words: measured 23.8% + measured-split 11.5% + multi-owner 1.7%
= 37% wearing real tess geometry. Tess consumption 68.4% (was 43.7% in v1).
Unmatched split honestly: 37.2% dropout (blocks w/ ZERO tess words — known
holes, interpolated boxes, unfixable by alignment) + 25.8% in-block unmatched.
Disagreements: 71 punct-only (auto-normalize) + 273 real.

### In-block unmatched DIAGNOSED: not an aligner problem
Top-unmatched blocks inspected side-by-side: BLOOR obituary = ~120 VLM words vs
tess 'la Xr. 2 e 936 ull' (7 garbage fragments; '936 ull' = ghost of '936
Fullerton Street'). Crossword clues block: pure noise ('f at Ihe nose rkman').
DROPOUT HAS A GRADIENT: zero-word blocks, near-zero-garbage blocks, healthy
blocks. Aligner correctly refuses to match garbage. These blocks route to
interpolated class. No further matching work needed for this failure mode.
p005 honest accounting: ~37% measured, ~63% interpolated — but p005 is WORSE
than corpus median (0.58 ratio vs 0.90 median); don't quote it as typical.

### Router refinement from disagreement dump (for arbitration design)
HIGH TESS CONF ON TRUNCATED READS: 'FR'@97 vs VLM 'FREE'; 'ave'@95.7 vs 'save'.
Tesseract is confidently wrong about words it only partially read. Rule:
"high conf -> lean tess" needs a carve-out when tess word is a proper
substring/truncation of VLM word — length asymmetry counts AGAINST tess even
at high conf. Also seen: genuine coin-flips (Rafters@75 vs Ratters., Des@80 vs
Deist — VLM's own reading suspicious there) -> image-crop arbitration class.

### NEXT
1. Run align_page.py v2 on 2-3 median-quality pages (e.g. from the 0.90-1.06
   ratio band) — get the typical measured-geometry fraction, not p005's worst case.
2. Dedup prototype; orphan 2D clustering; gold set; MiniOCR hyphen desk check
   (all still queued).

## Session update 2026-07-15 (cont.) — median pages validate architecture

### align_page.py v2 on three median-band pages
p030 (ratio 0.90): 70.0% measured geometry, dropout 1.9%, in-block 28.1%
p015 (ratio 0.99): 54.8% measured, dropout 0.5%, in-block 44.8%
p011 (ratio 1.06): 70.6% measured, dropout 5.2%, in-block 24.2%
TYPICAL PAGE: ~55-70% of VLM words get real tess boxes (~2x p005's 37%).
p005 confirmed as stress tail. On median pages dropout nearly vanishes;
remaining unmatched is in-block = tess PRESENT BUT GARBLED (conf-0 shrapnel
like SERVICE<EFYVIOTIVE) — same gradient as p005, routes to interpolated.

### Disagreement VOLUME problem + router bands (from dumps)
257-566 real disagreements/page -> ~2-3M corpus-wide. LLM-per-disagreement
untenable; dumps show it's unnecessary:
- majority = low tess conf -> VLM wins, no LLM
- high-conf TRUNCATIONS (bu@96/but, ernment@95.6/Government) -> substring
  carve-out -> VLM, no LLM
- RECURRING PAIRS (Eight/Bight x3 on one page, their/thelr) -> arbitrate once,
  CACHE ruling, apply corpus-wide (1925-typeface confusions will dominate)
- NUMERIC disagreements ($3750/$3730, $5100/$3100, 1925/1025) -> no lexicon
  possible, image crop required, high search value (prices/dates) — small band
- punct-only runs 72-180/page -> normalization layer matters
- residual suspicious pairings (possess/Tires@96) = misalignment noise, watch
Substantial punct-only volume + Solr chain already normalizes curly/straight
apostrophes etc. — disagreement classifier must apply SAME normalizations as
the index (else we arbitrate distinctions the index doesn't even preserve).

### NEXT
1. ROUTER SIMULATION: classify all ~1,500 disagreements from the 4 aligned
   pages through rule cascade (punct-norm -> low-conf -> truncation ->
   lexicon-vote -> residual). The residual count sizes the real LLM workload.
2. Then: dedup prototype, orphan clustering, gold set, MiniOCR hyphen check.

## Session update 2026-07-15 (cont.) — lexicon pollution, dictionary cascade, arbitration reframed

### Frequency-vote hypothesis FALSIFIED — lexicon is majority-polluted for some patterns
lexicon_1925.tsv (Tesseract-built, 713,822 entries) frequencies: thelr 8,800 vs
their 14,978; rallway 1,687 vs railway 1,090 (!); ploneer 267 vs pioneer 245 (!).
Tesseract's l/i confusion on this typeface is SYSTEMATIC — misreads sometimes
OUTNUMBER correct forms. Frequency voting would pick the WRONG side. Corollary
for the demo/paper: searching "railway" in the tess arm misses ~60% of
occurrences. The lexicon indicts itself; never use it as a correctness oracle.

### Fix: external dictionary + confusion awareness (router_sim2.py)
/usr/share/dict american+british merged (104,305 entries, Tesseract never
touched them) splits all test pairs perfectly. New cascade on 2,026
disagreements (4 pages):
  punct-auto 23.9% | lowconf->vlm 31.6% | truncation->vlm 17.0%
  confusion-dict 3.9% | plain-dict 11.6% | lex-backstop 0.3%
  numeric->image-arb 1.7% | residual->llm-arb 9.9%
ARBITRATION: 11.6% (~385K extrapolated), down from 22.9%.
DICTIONARY VERDICT 12:1 — VLM wins 291, tess wins 24. The 24 = first
quantified VLM word-hallucination measure (real, small; the literature's
warning class, caught by tess letter-fidelity + dict).
1925 lexicon retained ONLY as conservative proper-noun backstop (freq>=20 one
side, absent other, neither in ext dict).

### Residual is mostly SHRAPNEL with a signature, not coin-flips
Repeats in residual: piano+Kent's both claiming tess 'at'; The+Part on 'ha';
held+Tuesday on 'hes'. Pattern: multiple consecutive VLM words mapping to ONE
short tess token = shrapnel charitably attached by aligner, not disagreement.
FREE RULE TO ADD (structural, safe): shared-owner + gross length mismatch ->
VLM wins. Would sweep ~1/3 of residual. Genuine coin-flips (Lang/Long@84.8,
Fall/Full@85.4) are the minority.

### STRATEGIC REFRAME — ⇿ alternatives makes arbitration non-blocking
Index BOTH readings at same position for residual band: full recall, zero LLM
calls, display form defaults to VLM (12:1 evidence). LLM+image arbitration
becomes optional QUALITY PASS, priority on numeric band (~58K corpus-wide;
prices/dates: vlm '$20,072' vs tess '248' — estates column) rather than a
pipeline dependency. "Index now, arbitrate at leisure."

### Overfitting caution
Cascade shaped by 4 pages / 2,026 disagreements. Shrapnel rule OK to add
(structural). NO more threshold tuning until gold set exists to validate
against. Scripts: router_sim.py, router_sim2.py.

### NEXT (back to queue, tuning paused)
1. Dedup prototype (contained-duplicate blocks — McKinnon/Hartz class)
2. Orphan 2D clustering (x-aware)
3. GOLD SET (now gating: cascade validation + reading-order trust + WER claims)
4. MiniOCR hyphen desk check (before format freeze)

## Session update 2026-07-15 (cont.) — dedup built and LOCKED (v4)

### Arc: test_dedup.py v1 -> v4 (all report-only, read-only)
v1 naive fuzzy-containment: caught true dups BUT false-positived on short
strings ('The Canadian' @0.83 into unrelated body text) and — worse — on
DIFFERENT-ENTITY template rows: 'Asuka Maru, from Orient' suppressed against
'Yokohama Maru, from Orient' (would DELETE SHIPS from a shipping index; the
Burridge-class invisible recall loss, self-inflicted). Risk asymmetry rule
adopted: wrong-suppress is catastrophic+invisible, missed-dedup is cosmetic ->
push all thresholds toward keep-both.
v2 added length floor + entity veto (concentrated mismatch, ed>2): killed the
dangerous errors, but floor ordering blinded the self-disagree detector
(Hartz/Martz died at the floor before analysis).
v3 reordered guards (analysis before floor at score>=0.9) + HYPHEN-STUB rule
(A ends mid-word, B completes it -> confident suppress). Still blind:
majority-of-token mismatch test can't see ed<=2 defects (1 char of HARTZ under
the half-token bar) AND can't see scattered spurious matches (LAWRENCE SCOTT
matching as confetti through long text — same 'clean' verdict, opposite
realities).
v4 FIX: CONTIGUITY metric (longest single matching run / len). contig>=0.75 ->
token-compare for ed<=2 defects -> self-disagree; contig<0.5 -> spurious
scatter, demote. RESULTS: Hartz/Martz -> self-disagree (HARTZ~MARTZ ed=1,
first confirmed alternatives-candidate specimen); LAWRENCE SCOTT -> demoted
(contig 0.43); suppress list clean (McKinnon, Victory, hyphen-stub, Yokohama
tail); Asuka veto holds.

### Findings encoded
- VLM emits OVERLAPPING FRAGMENTARY WINDOWS on tables (shipping schedules):
  not re-reads but partial transcriptions, sometimes mid-word. These need
  MERGING not dedup — consciously DEFERRED (0.05% volume, wrong cost/benefit);
  flag band keeps both, accepts occasional doubled hits.
- Leading-stub fragments ('ment of British Columbia.' = tail of hyphen-broken
  advertise-/ment): v4 keeps both (safe). Fourth micro-class; within-block
  dehyphenation will meet it from the other side. Logged, not chased.
- Volumes tiny: 4 suppress + 1 self-disagree + 9 flag across 25 pages.
  Dedup is a scalpel; the value is the SELF-DISAGREE INTAKE (purest same-
  region-two-readings signal, feeds ⇿ alternatives + arbitration cache).

### NEXT
1. Orphan 2D clustering (x-aware) — last unbuilt regrouping mechanism.
2. GOLD SET (gating: cascade validation, reading-order trust, WER claims).
3. MiniOCR hyphen desk check (before format freeze).

## Session update 2026-07-15 (cont.) — orphan clustering built and LOCKED (v3)

### test_orphan_cluster.py v2 -> v3
v2 (page-global gaps from median orphan word height 29px): column fusion FIXED
vs the naive y-only probe, gates worked (pipes discard at ANY conf via
no-alnum rule — Tesseract reads column rules as high-conf letters, the alnum
gate outworks the conf gate on noise). BUT: display type over-split ("Prince
Makes Stop" / "to Plant Tree" = 2 clusters; headline line-gaps exceed
body-text-scaled thresholds). SAME LESSON AS ALIGNER v1: geometry thresholds
must scale to LOCAL type size, never page-global medians. Also '3 PM.
Reports'@49 (real weather text) fell to discard at the 50 line.
v3: (1) ADAPTIVE PAIR GAPS — join if vgap<=1.5x / hgap<=2.0x the TALLER
word's height. (2) gates re-cut 80/40 (risk asymmetry: flagging junk ~free,
discarding real text = self-inflicted Burridge).
RESULTS (0925uvic_35_p005, 214 orphans): headline reunited (1 cluster, h112);
Maynard's ad reunited (17w keep); '3 PM. Reports' -> flag; pipes all discard;
NO cross-column re-fusion (gutters > 2x even headline heights).
Verdicts: keep 12c/83w, flag 7c/32w, discard 49c/99w.

### Accepted imperfections (cosmetic, logged not chased)
- Shrapnel from kept regions ('FERED'@23='OFFERED' fragment, 'INE'@0)
  discards correctly — parent content survives via kept cluster or VLM.
- Mixed flag clusters (Kent's piano ad @56) = honest half-reads, flag is right.
- High-conf singletons ('in'@96) keep alone — harmless; min-size rule would
  kill legit singletons ('Limited').
- Tiny-cluster median can drown one real word among junk ('| " B.C'@25) —
  ~1 word/page scale, accepted under risk asymmetry (it's flag/discard side).

### FOUNDATION COMPLETE
Regrouping layer fully built + tested read-only on real pages: block dedup
(v4), word->block assignment (center-in-bbox, per-page scale), within-block
alignment (v2, adaptive lines), orphan clustering (v3, adaptive 2D). All
scripts in ~/solr-bridge/phase2/, nothing in Phase 1 touched.

### NEXT (assembly phase begins)
1. GOLD SET — now the gating item for everything quantitative (cascade
   validation, reading-order trust, WER/retrieval claims). Pages nominated:
   0925uvic_17_p014 (39.6% orphans), a 0.32-ratio dropout page, a weather/
   both-failed region, 2 median pages. Human transcription work.
2. MiniOCR hyphen desk check (format freeze gate).
3. Then: synthesis prototype — one page end-to-end into hybrid output format.

## Session update 2026-07-15 (cont.) — gold set parked, format decision made

### Gold set: PARKED (user call — transcription time not realistically available)
Consequence accepted: no WER/retrieval numbers; claims stay qualitative backed
by structural corpus numbers (0.58 ratios, 8% orphans, 12:1 dict verdict,
railway/rallway lexicon evidence). Router cascade + reading-order trust stay
eyeball-validated -> stay conservative, NO further tuning. Replacements:
(a) RETRIEVAL SPOT-CHECKS — known-entity queries (Burridge, Asuka Maru,
railway) compared across tess/VLM/hybrid arms; minutes per query.
(b) OPPORTUNISTIC MICRO-GOLD — every block eyeball-verified during dev gets
logged (RECEIVERS headline, Hartz/Martz region, p005 chunks already qualify).

### MiniOCR hyphen desk check: RESOLVED — MiniOCR wins format decision
Plugin changelog: hyphenation resolved at indexing time FOR ALL SUPPORTED
FORMATS — word broken across lines indexed as dehyphenated form, both line-
parts highlighted at query time. MiniOCR included. ⇿ U+21FF alternatives
confirmed in MiniOCR too. DECISION: hybrid arm = MiniOCR (matches Phase 1 VLM
arm tooling: converter, reindex scripts, solr config; fastest to highlight).
CAVEAT: exact encoding mechanic (likely trailing hyphen at line-end) to be
verified empirically w/ 2-line test doc in scratch core BEFORE full synthesis
run — 5-min check when Phase 2 core stands up, not a blocker.

### NEXT — synthesis prototype
One page end-to-end: dedup -> regroup -> align -> route (cascade + ⇿ alts for
residual) -> orphan clusters -> hybrid MiniOCR file. Output under phase2/ only.
Then eyeball the MiniOCR, then scratch-core index test.

## Session update 2026-07-15 (cont.) — SYNTHESIS PROTOTYPE WORKING

### synthesize.py: first end-to-end hybrid MiniOCR produced (p005)
Chains: dedup(v4-lite: exact-containment + hyphen-stub only) -> regroup ->
align(v2) -> route(cascade) -> orphan clusters(v3) -> MiniOCR + provenance
sidecar JSON (MiniOCR has no per-word attrs; provenance lives in sidecar).
Output ONLY under ~/solr-bridge/phase2/out/. Design choices baked in:
- coords in FULL-RES TESS SPACE (matches Cantaloupe/ALTO-arm convention)
- residual disagreements: VLM primary + tess as ⇿ alternative (12:1 + recall-safe)
- tess-dict band: tess primary + VLM as ⇿ alternative
p005 v1 distribution: agree 23.5%, interp 62.2% (known dropout gradient),
routed/dict/punct/multi/residual bands as measured, 39 tess-only cluster-blocks
rescued, 50 ⇿ alt-carrying words. RECEIVERS block verified byte-level in
output: split measured boxes intact (OF 2718/96, GREAT 2814/240, LINE 3055/192).

### Shrapnel rule built (was named during router work, now demanded by output)
v1 emitted 'piano⇿at' w/ 8x10px box — piano's highlight the size of a comma,
garbage 'at' indexed as alternative. PATCH (assert-anchored, aborts loudly):
PASS 0 counts VLM claimants per tess owner; owner claimed by 2+ VLM words
whose combined length > 2x tess token = SHRAPNEL -> claimants route to interp,
no box inheritance, no alt. Result: piano⇿at gone, interp-shrapnel 43 words,
drawdown from exactly the right bands (routed -21, residual -11, dict -9/-2,
arithmetic exact), total unchanged 3078.

### Honest observations
- p005 tess-only clusters dirtier than the v3 test page (different page —
  p005 orphans skew garbage-gradient): 'Ma nard's Shoe Store' real, 'MORIZON'/
  'ig ol. 5 i ll' flag-band junk. Gates worked; risk-asymmetry accepts
  searchable junk over deleted text. Eye at scale later.
- Rafters⇿Ratters. = tess-dict routing (rafters IS a dict word, 'Ratters.'
  isn't) — dict-vote can favor tess on crossword oddities. Correct per rules.
- dedup found 0 on p005 (expected — McKinnon/Hartz were other pages).

### NEXT — scratch Solr core (SEPARATE from colonist, isolation rule)
Index the one hybrid file; verify: search hits, highlight boxes land on page
image, dehyphenation mechanic, ⇿ alternatives searchable both ways. Then
retrieval spot-checks vs existing arms.

## Session update 2026-07-15 (cont.) — SCRATCH CORE LIVE, ALL MECHANISMS VERIFIED

### colonist_phase2 core created (colonist untouched throughout, verified 13,310 docs)
- conf copied file-level from colonist (carries full Phase 1 analyzer chain:
  apostrophes, possessives, ASCII folding, 1925 synonyms)
- GOTCHA 1: plugin JAR loads from CORE-LOCAL lib/ (no <lib> directive) —
  conf copy alone -> ClassNotFoundException on CREATE. Fix: cp the JAR into
  colonist_phase2/lib/.
- GOTCHA 2: /var/solr/data is a HOST MOUNT (~/solr-bridge/solr-home/data),
  owned by container solr user — host-side edits get PermissionError; edit via
  docker exec (container lacks python3; sed with a\ works). All "in-container"
  conf edits are really host-filesystem operations through the mount.
- GOTCHA 3: ocr_text field = FILE POINTER read at index time by
  ExternalUtf8ContentFilterFactory. Container paths only: host
  ~/solr-bridge/ocr-data == container /ocr-data. Phase 2 output now goes to
  ~/solr-bridge/ocr-data/phase2/ (additive subdir in existing mount) and docs
  post /ocr-data/phase2/... paths. synthesize.py should write there directly
  for the full run.

### ⇿ alternatives: THREE-PART requirement (debugging arc, documented in plugin docs)
1. expandAlternatives="true" on OcrCharFilterFactory — encodes word+alt into
   ONE joiner-glued super-token (U+2060 WORD JOINER + offset number; watched
   it live via analysis endpoint: 'Rafters<U+2060><U+2060>72<U+2060><U+2060>Ratters').
2. solrocr.OcrAlternativesFilterFactory AFTER the tokenizer — DECODES the
   super-token into multiple tokens at one position. Without it the fused blob
   indexes as one unsearchable token (both readings -> 0 hits). Phase 1 never
   used alternatives so the copied schema lacked it. (Matches parked Phase 1
   queue item naming this exact class.)
3. PUNCTUATION-FREE alternatives — punctuated alts broke offset arithmetic at
   index time (startOffset>endOffset crash); synthesize.py patched to emit
   core-token alts only, skip if empty/same-core. DOCS CAVEAT: punctuation in
   the PRIMARY also severs alternatives silently (tokenizer splits the token,
   joiner-glued alt lost) — accepted for now: primary still indexes, only alt
   reading lost, punctuated-primary minority. Logged, not chased.
- Analysis endpoint can't take raw markup (first charFilter expects a file
  pointer) — probe with a tiny .miniocr.xml test file instead.

### VERIFIED LIVE (all six):
rafters=1 ratters=1 deist=1 des=1 (both readings, ⇿ working)
burridge=1 in hybrid vs 0 in tess arm same page (dropout rescue)
"great line" phrase -> snippet with SPLIT MEASURED BOXES (2814-3054, 3055-3247
@y1066) — the OFGREATLINE| word, searchable and pixel-highlighted.

### NEXT
1. Mirador/viewer route against colonist_phase2 (isolated port/script, live
   shim untouched) — see the highlights on the actual page image.
2. Small batch: synthesize + index the 4 aligned test pages + a couple more,
   retrieval spot-checks vs existing arms (the gold-set substitute).
3. Git commit phase2/ work.

## Session update 2026-07-15 (cont.) — batch run, TWO BUGS caught and fixed, 4th flagship result

### Small batch: 7 pages (4 aligned + 3 pathology) synthesized + indexed, no crashes
Per-page: median pages 62-64% measured geometry; pathology pages 23-27% w/
heavy interp/tess-only exactly as diagnosed (0925uvic_17: 1,328 tess-only
words). Spot-checks: all dropout rescues confirmed year-relevant
(burridge/goodall/stroyan/querulous/"great line": hybrid=1 tess=0), agreement
cases agree. NOTED: hybrid column initially mirrored vlm column — batch hadn't
yet demonstrated hybrid > VLM until the orphan page was added.

### BUG 1 (Phase 1 ghost): synthesize.py lacked block_content sanitization
Raw <table><tr><td> HTML from a weather table landed ESCAPED IN THE INDEX as
one 617px-tall <w>. This is Phase 1 hard-won finding #1, already solved in
paddle_to_miniocr.py lines 22-24 — synthesize.py was written from raw
block_content and never inherited it. FIX: same three sanitizations applied at
block load (table-tag strip, em/en-dash -> space, astral+U+FE0F strip).
LESSON REINFORCED: the handoff's hard-won findings list is a CHECKLIST for any
new consumer of raw VLM JSON, not history.

### BUG 2: synthesis orphan pool contaminated -> lost the Prince headline
Symptom: "prince makes stop"=0 in hybrid though locked v3 clustering keeps the
headline. ROOT CAUSE: v3 defines orphan = in NO block (image blocks count as
containment); synthesize only claimed words in TEXT blocks -> tess words
inside image-label regions flooded its orphan pool (Metchosin/Battensby
fragments), changing cluster neighborhoods/merges/medians -> Prince cluster
never survived. FIX: claim image-block words separately as designed —
new 'tess-in-image' provenance class (own blocks, conf>=40 + alnum gate).
Result: tess-only collapsed 312 -> 79 words (v3's neighborhood), tess-in-image
71 words, headline back in file with measured display-type boxes.
PROCESS RULE (paid for twice today): LOCKED COMPONENTS GET IMPORTED, NEVER
RE-TYPED. synthesize.py re-implemented v3 clustering inline and diverged on
the orphan DEFINITION. Refactor task queued: factor locked logic into a shared
module both test scripts and synthesize import.

### FOURTH FLAGSHIP RESULT (mirror of Burridge)
"makes stop to plant tree": hybrid=1, vlm-yearwide=0 — a headline the VLM
never saw anywhere in the year, phrase-searchable in the hybrid with measured
tess boxes (h112 display type, one line, internal order correct incl. 'to').
Hybrid now demonstrably exceeds BOTH parents. Footnotes (logged, cosmetic):
'—————' rule token breaks the full "Prince Makes..." phrase (accepted cluster
noise); two weather-table residue words carry ugly 14x617 interp boxes
(table-strip consequence, harmless text).

### NEXT
1. Refactor: shared phase2lib module (orphan clustering, sanitize, gates) —
   BEFORE smoke run, so the smoke run tests the code that will do the full run.
2. Re-run batch of 8 with refactored code, confirm identical output.
3. Smoke run (few hundred pages, nohup, tripwires: word-count ratios,
   provenance fractions, empty output, index failures).
4. Full run.

## Session update 2026-07-15 (cont.) — refactor to phase2lib, accepted on properties

### phase2lib.py created — canonical home for locked components
sanitize_content, load_tess_words (QUOTE_NONE), order_into_lines, char_align
(with ALIGN_GUARD), ext dict loader, cluster_orphans (v3), orphan_verdict,
group_cluster_lines, norm/core_l/PUNCT/ALT. synthesize.py rewritten as a
driver importing these. Backup: synthesize_pre_refactor.py.bak.

### Performance findings (from timed 8-page reruns)
1. difflib SequenceMatcher(autojunk=False) is quadratic; sanitize turned table
   blocks into huge single lines. ALIGN_GUARD added (len*len > 4M -> skip
   char alignment, words -> interp; honest trade: blocks that big are garbage-
   gradient/table cases whose alignment routes to interp anyway).
2. GUARD DID NOT CURE the slow pages — wrong diagnosis. Real hotspot #2:
   cluster_orphans merge pass is quadratic in orphan count (pairwise joinable
   across all cluster-member pairs, repeated to fixpoint). 0925uvic_17 (~1.6K
   orphans) takes ~100s alone. STILL OPEN: needs a cluster-bbox prefilter
   before pairwise member checks (pure perf, must reproduce v3 clusters on
   the 8-page set) BEFORE the full run; smoke run will tolerate it at few-
   hundred-page scale but 6,647 pages won't.

### Verification: md5 byte-equality FAILED honestly, properties PASSED
4 pages diverged old-vs-new. Investigated: NOT line-break cosmetics — real
word/box differences, all in the ORPHAN TAIL (garbage-gradient flag-band
tokens: 'h'/'ents', 'ny'/'y', degenerate 814x1 / 2x2 boxes).
ROOT CAUSE: greedy agglomerative clustering is ITERATION-ORDER SENSITIVE —
borderline words join whichever qualifying cluster is checked first; old
inline loop and lib loop differ subtly in construction/merge order. Two
"identical" implementations of an order-sensitive algorithm are only
identical if every loop is byte-equivalent. Old code was NOT a gold standard
(it lost the Prince headline); acceptance switched to PROPERTY TESTING:
word counts equal on all pages, divergent words are conf-gated junk, and the
full flagship battery passes 12/12 on refactored output (burridge, goodall,
stroyan, querulous, "great line", "makes stop to plant tree", rafters+ratters,
deist+des, receivers, maynard=3). ACCEPTED. Degenerate-box orphan junk (814x1,
2x2) noted as candidate for a min-box-sanity filter in the emit stage — queued,
not blocking.

### Sequencing hazard (self-inflicted, logged)
A "scratched" half-command left runnable lines in a message; user's terminal
executed them, poisoning an old-vs-new diff (diffed old against old, empty
diff looked like success). RULE: never leave runnable fragments in commands;
strict copy-aside-BEFORE-regenerate sequencing in comparison workflows.

### NEXT (pre-smoke-run gate)
1. Orphan clustering perf fix (bbox prefilter; acceptance = identical clusters
   on 8-page set — it's a prefilter, so true identity is achievable, unlike
   the ordering issue).
2. git commit refactor.
3. Smoke run: few hundred pages, nohup, tripwires (word-count ratio bounds,
   provenance fractions, empty output, index failures, per-page timing).
4. Full run + reading-order step still ahead (VLM-order prior + dehyphenation
   + LLM arbitration pass all remain design-complete but unbuilt).

## Session update 2026-07-15 (cont.) — safe_alt fix, SMOKE RUN PASSED

### Smoke run round 1: caught a real bug (4x index-exception, HTTP 400)
startOffset>endOffset again — punctuated/numeric PRIMARIES (price, / $300,000 /
(r25) / 75c) and dirty alts (sional—8300,000) sever joiner-glued alternatives
when StandardTokenizer splits mid-token. FIX: safe_alt() in phase2lib — attach
⇿ ONLY when both sides are single pure-alpha tokens (apostrophes ok) after
edge-strip. Rationale: alternatives exist for SPELLING disagreements
(Boils/Bolls, organization/organisation); numeric/punct disagreements are the
image-arbitration band anyway and half their alt readings were garbage.
Worst page: 64 alts -> 22, indexes clean.

### Smoke run round 2 (fresh markers, fixed code): 299/300 PASS
~0.7s/page, zero index failures, zero anomaly tripwires in stats.
1 quarantine = dailycolonist0725uvic_27_p001: GENUINELY DEGENERATE PAGE
(tess read 11 words, VLM 2 blocks/4 words, Phase 1 VLM arm equally empty at
244 bytes since July 8 — blank/plate-error/scan-failure class). Tripwire
worked as designed. TODO (nice-to-have): tripwire could distinguish
"empty output from rich input"=bug vs "both inputs empty"=degenerate by
checking tess word count.

### FULL RUN GATE: CLEARED
Projection: 6,647 pages @ ~0.7s = 75-80 min sequential. No parallelism needed.

## Session update 2026-07-15 (cont.) — FULL YEAR INDEXED

### Full run: 6,641/6,647 pages, 26.9M words, ~76 min @0.7s/page
Quarantine 12 = 6 degenerate pages (blank/plate-error class, correctly
flagged) + 6 char_align IndexError — FIXED: str.upper() length-expansion
(ss->SS/ligatures) made matcher indices invalid for original strings;
length-preserving per-char fold (_upper1) in phase2lib. Resume swept all 6.

### Year-wide provenance (final)
agree 35.7% | interp 39.1% | vlm-routed 6.6% | tess-only 4.6% | punct 3.5% |
tess-only-lowconf 2.7% | multi 2.4% | vlm-dict 2.2% | residual-alt 1.7% |
interp-shrapnel 1.0% | tess-in-image 0.5% | tess-dict 0.2%
RESCUE CLASSES = 2.08M words (7.8%) in neither parent's usable form.
~498K positions carry ⇿ alternatives.

### Year-wide retrieval report card (hybrid vs arms)
railway: hybrid 2,636 vs tess 731 (tess lost ~72% to l/i misreads) vs vlm 2,717
rallway (misspelling): 1,146 tess -> 116 hybrid (corruption nearly gone;
  remainder = honest tess alternatives, recall preserved both directions)
esquimalt: hybrid 1,871 BEATS BOTH (tess 1,251, vlm 1,746) — union effect
burridge: hybrid 26 = vlm 26, tess 14
NUANCES (logged): hybrid 81 pages under vlm on railway — investigate someday
(dedup suppressions? duplicate-block inflation in vlm counts? the gap may BE
dedup working). Prince-headline phrase: tess arm also =1 (words adjacent in
its stream on that page) — honest framing is "hybrid=1, vlm=0".

### REMAINING (design-complete, unbuilt): reading order + insertion rule +
cross-block dehyphenation; LLM arbitration quality pass (numeric band
priority). Both are re-emission passes over cached synthesis outputs.
Then viewer + demo polish.

## Session update 2026-07-15 (cont.) — reading order: trust verified, insertion rule built

### VLM order trust: CORPUS-WIDE CHECK (all 6,647 pages, 926,473 block pairs)
Geometric regressions: 206 (0.022%) spread thin across 171 pages, worst page
= 3. NO pathological cluster — the "scrambled page" class does not exist in
this corpus. Worst-list skews to high page numbers Sept/Nov (classified/
want-ad sections — layout density, not systemic failure). 171-page list =
escalation watchlist; at 1-3 stray pairs each, likely tolerable as-is.
Continuity (label-aware — first probe's 817 "violations" were headline-
blindness: titles naturally end unpunctuated): 81,540 text-block midsentence
ends, 4,516 (6%) lowercase continuations = the real cross-block story-flow
population that cross-block dehyphenation + phrase continuity care about.
CONCLUSION: VLM order trustworthy; minimal build confirmed (no repair
machinery by default; LLM escalation reserved for watchlist, may never fire).

### insertion_index() built (phase2lib) and validated on the motivating case
Column-flow rule: VLM block precedes a rescued block if same column
(h-overlap>=0.3 of narrower) and top above, OR strictly left column; insert
after LAST preceding. TEST: Prince headline cluster on 0925uvic_35_p005
inserts at index 55/98 — immediately before its own story's "Prince of Wales
made a brief stop..." caption, between adjacent items. Correct neighborhood
on the first try (with hand-reconstructed bbox).

### NEXT
1. Wire insertion_index into synthesize emit (rescued blocks positioned, not
   appended); track rescued-block bboxes in tess space, convert for comparison.
2. Re-synthesize familiar pages, verify neighborhoods; find a search-visible
   cross-block phrase test.
3. Then cross-block dehyphenation (the 4,516-continuation population).

## Session update 2026-07-15 (cont.) — ordering + dehyph wired, verified; YEAR REFRESH LAUNCHED

### MiniOCR hyphen desk-check resolved EMPIRICALLY (changelog was misleading)
Scratch doc test: plugin does NOT auto-join trailing-hyphen words in MiniOCR
('extraordinary'=0, both fragments=1). "All supported formats" evidently means
formats w/ explicit hyphen encoding (ALTO SUBS/HYP). LESSON: changelog
summaries are not format specs — test empirically.

### Cross-seam dehyphenation built (emit pass, post-ordering)
Seams: block->next-block + line seams INSIDE rescued blocks (their text never
went through VLM joining; within-VLM-block hyphens already joined upstream).
Gates: letters+hyphen / lowercase continuation / joined core in ext dict.
Join = fragments merged onto FIRST fragment's box (highlight slightly short —
honest), second <w> removed. Verified on p015: Au-/gust -> August, exactly
one multiset delta. Fire rate ~1/page-ish (conservative by design).

### Emit ordering: insertion_index wired (far-first splice), Prince headline
lands mid-file beside its story caption. Flagship battery 12/12 AT YEAR SCALE
(counts now year-wide: burridge 26, maynard 640, prince-phrase unique at 1).

### Year refresh: full_run rerun with ordering+dehyph (markers cleared)

## Session update 2026-07-15 (cont.) — STRUCTURAL BUILD COMPLETE (year refresh 2)
Refresh w/ ordering + dehyph: 6,641 pages, 26,891,614 words, quarantine = 6
degenerate only (casefold pages clean this time). Provenance distribution
stable vs run 1. Flagship battery holds exactly at year scale (railway 2,636,
esquimalt 1,871, burridge 26, prince-phrase 1).
BOOKKEEPING NOTES: (a) word total +20.8K vs run 1 = the 6 casefold-rescued
pages' words (~3.5K each), joins are in there but swamped — join volume
UNMEASURED because full_run captures synthesize stdout and discards on
success; join count should move to stats jsonl if we ever care. (b) 3 test
docs (hyph_test, alt_test, probe_*) deleted from core; docs now = pages.
REMAINING ROADMAP: LLM arbitration quality pass (numeric band ~58K priority);
railway-gap investigation (hybrid 2,636 vs vlm 2,717 — dedup suspected);
viewer route for demo. Structural pipeline is DONE.
CORRECTION to (b) above: post-delete audit found docs=6,643 not 6,641 — two
STALE hybrid docs from pre-tripwire debug sessions (0125uvic_27_p001,
0325uvic_26_p001 — degenerate front pages, old-emit content). Deleted.
INVARIANT NOW TRUE AND VERIFIED: docs == refresh done-markers == 6,641.
Audit method: indexed ids minus .full_done markers (worth keeping as a
standing consistency check before quoting counts).

## Session update 2026-07-15 (cont.) — LLM ARBITRATION: BUILT, TESTED, NOT DEPLOYED

### Machinery built (judge-agnostic, ready for a better model)
extract_numeric_band.py (re-derives numeric disagreements w/ crop boxes;
found a free pre-filter: ¢/c glyph-fold pairs are punct-band, not numeric),
arb_one.py, arb_batch.py (choice protocol), arb_blind.py (blind protocol).
PNG space == tess space (f=1.0000, verified) — no third coordinate system.
Truth instrument: ¢-sign pairs (1925 print uses ¢; letter-faithful tess read
it) — a knowable-answer test embedded in real data.

### Judge evaluation: Qwen2.5-VL-7B (describer, :8120) — FAILED, two ways
1. CHOICE PROTOCOL: 16/16 verdicts = A. Label-swap control: 14/16 STILL A —
   overwhelming POSITION BIAS. Same crop "definitely 338" then "definitely
   388" depending on slot order. Only gross-disparity cases (2) resisted.
2. BLIND PROTOCOL (no candidates in prompt; verdict computed in code): bias
   cured, verdicts vary — but transcription quality insufficient: ¢-truth-test
   2/4; hallucinated currency framing on hard crops ($1.00/$0.00/20¢ invented
   instead of admitting illegible; one invented minus sign). Editcap caught
   worst 4; subtler confabulations passed as C. ~5-6 trustworthy of 16,
   2 known-wrong on verifiable ground.
DECISION: numeric band stays VLM-primary/unarbitrated. Qwen-7B disqualified
as judge. Literature's warning (small models degrade historical OCR)
reproduced on own corpus with own guardrails. Machinery + acceptance test
(¢ instrument, 4/4 required) ready for any future stronger judge.
Residual band: unaffected — ⇿ alternatives already made arbitration optional.

## Session update 2026-07-15 (cont.) — ¢-INSTRUMENT INVERTED BY EYEBALL; VLM VINDICATED 5/5

### Judge bake-off round 2 (qwen3-vl:8b via Ollama, GPU after stopping paddlevl)
- THINKING MODE: reads hard crops (338, 3,91, Peter—39) but ruminates up to
  ~4min/crop on ambiguity (59¢ case) — accurate-but-unscalable.
- NO-THINK (+num_predict cap): fast, ZERO hallucinations, 6 verdicts /
  10 honest abstentions ('' -> unreadable instead of Qwen2.5's invented
  $1.00s). Trustworthy-but-timid profile.
- tesseract-whitelist-3x baseline: 16/16 empty (psm/whitelist bug — a
  baseline failure, not a verdict; no cheap classical rescue though).

### THE INSTRUMENT WAS WRONG — verified by human eyes on the ink (Cantaloupe
region URLs; NOTE: server forbids >100% scale, request /full/ and zoom)
All four "¢-cases": 1925 ink shows PLAIN c (1920s ad typography). Fifth crop
(59¢/50¢): ink shows genuine ¢ AND the digit is 9.
=> PaddleOCR-VL read 5/5 CORRECTLY, discriminating c vs ¢ in both directions.
=> My "VLM ASCII-folds ¢" claim from extraction: WRONG — it reads glyphs
   faithfully. => TESSERACT confabulated ¢ onto plain-c ink 4x at conf 58-88:
   new confirmed error mode, GLYPH CONFABULATION AT HIGH CONFIDENCE (error-
   character ledger updated; 12:1 gets this footnote).
=> Qwen2.5's ¢-portion of its indictment was my error (its disqualification
   stands independently on the label-swap position-bias result, 14/16).
=> VLM-PRIMARY INDEX POLICY VINDICATED on every verifiable case — the index
   already held the right reading, unarbitrated, all five times.

### Arbitration yield, measured: ZERO on verified cases
qwen3-vl's six verdicts confirmed the primary 6x, corrected 0x; its
abstentions were genuinely-hard crops that stay unarbitrated either way.
PARKED (second time, opposite reason): round 1 = "the judge lies";
round 2 = "the honest judge has nothing to fix." Machinery + harness remain
judge-agnostic; open option: deepseek-ocr as specialized last word on the
abstention crops (one pull + one harness line).
PROCESS RULE (paid in full tonight): AN ACCEPTANCE INSTRUMENT MUST ITSELF BE
VERIFIED AGAINST GROUND TRUTH BEFORE IT DISQUALIFIES ANYTHING. Eyeballs on
ink beat asserted typography.

## Session update 2026-07-15 (cont.) — DEEPSEEK-OCR TESTED FAIRLY, DISQUALIFIED; JUDGE QUESTION CLOSED

### deepseek-ocr (3B specialist, official Ollama build)
Round 1 (our JSON prompt): 16/16 blank — prompt-format mismatch, not a
verdict (model documented as prompt-fragile, expects native incantations).
Round 2 (native prompts 'Free OCR.' / 'Extract the text...', raw output):
READS BUT CONFABULATES WORSE THAN ALL PRIOR CANDIDATES —
  46c (human-verified) -> '16c' (both prompts)
  338/388 -> '238' in LaTeX \[..\] markup
  $6.50 price -> INVENTED DIVISION EQUATION '3.5 / 0.5 = 7.2' (and =7.0)
Page-parser architecture forces tiny crops into document idioms (headings,
formulas), fabricating structure. Most dangerous profile tested: wrong +
confident + plausible-shaped. DISQUALIFIED.

### JUDGE QUESTION CLOSED — 3 architecture classes + classical baseline:
  Qwen2.5-VL-7B: position-biased chooser / hallucinating transcriber
  qwen3-vl:8b: honest abstainer — 0 hallucinations, confirms-never-corrects,
    thinking mode accurate-but-unscalable (~4min on hard crops)
  deepseek-ocr: OOD confabulator on crops
  tesseract-whitelist: blank (baseline bug, unfixed — no cheap rescue)
Engine under judgment (PaddleOCR-VL): 5/5 vs human-verified ink.
STANDING CONCLUSION: numeric band remains VLM-primary, unarbitrated, with
measured justification. Machinery (extract/blind/bakeoff + corrected-
instrument protocol: verify against ink FIRST) archived judge-agnostic for
any future stronger local model.

## Session update 2026-07-15 (cont.) — BAKE-OFF COMPLETE: MiniCPM + qwen3-vl:32b

### MiniCPM-V 4.5 (8B, RLAIF-V hallucination-reduction training): DISQUALIFIED
High coverage (15/16 readings, 1 abstention) but the ONLY two verdicts all
night that would have CHANGED the index were both EYEBALL-VERIFIED WRONG:
  338/388 -> said 388; ink says 338 (VLM right)
  3,917/3.01 -> said 3.01; ink says 3,91[7] (VLM right, tess fragment wrong)
Plus digit error on the smudged ¢ crop (50¢ vs ink's 59¢) and noise-shaped
reads (10 25 / 9 n). Coverage = confabulation with better manners.

### qwen3-vl:32b (no-think, describer stopped per authorization): HONEST+
Same integrity profile as 8B, more reach: 9/16 readings, 7 abstentions,
ZERO verified errors. Converted 8B-abstentions into CORRECT reads (3,91 =
exact human reading; Peter—39). Abstained on 338 (which ink resolves) —
scale bought reach, never bluffing. Still zero arbitration yield: every
verdict confirms the primary.

### FINAL STANDINGS vs human-verified ink (7 crops eyeballed total):
PaddleOCR-VL: 7/7 — the engine under judgment out-read every judge.
qwen3-vl think: only judge to read hard crops correctly (~4min/crop).
qwen3-vl 8B/32B no-think: perfectly honest, confirms-only.
MiniCPM: bold-wrong. DeepSeek-OCR: OOD confabulator. Qwen2.5: position-biased.
CONVERGED CONCLUSION: the numeric band is not "disagreement needing a judge"
— it is overwhelmingly TESSERACT BEING WRONG ABOUT DIGITS/GLYPHS while the
VLM is right (12:1 extended to numerals, now 7-for-7 ink-verified). There was
almost nothing to arbitrate. VLM-primary policy stands, now with the
strongest evidence in the project. Bake-off harness + verify-by-URL protocol
archived for any future judge candidate.

## Session update 2026-07-15 (FINAL) — SELF-INFLICTED INCIDENT: Phase 1 inference containers DESTROYED

### What happened (Claude's error, full ownership)
During the judge bake-off, Claude directed `docker stop paddlevl` and later
`docker stop describer` to free VRAM, asserting BOTH times they were
"reversible with docker start" — WITHOUT VERIFYING how they were launched.
Both containers were evidently launched with --rm (auto-remove-on-stop):
stopping them DELETED them. `docker start` -> "No such container."
The check that was owed and skipped, five seconds each time:
  docker inspect <name> --format '{{.HostConfig.AutoRemove}}'

### Actual damage assessment (verified)
- Phase 1 DEMO: INTACT. solr-ocr (colonist core, 13,310 docs) Up, cantaloupe
  Up, shim app.py:8888 alive, all data products on disk (ALTO/TSV, paddle-year
  JSONs, MiniOCR, images, descriptions in index). Committee demo unaffected.
- LOST: the two INFERENCE containers only — paddlevl (:8110, PaddleOCR-VL-1.6
  via vLLM) and describer (:8120, Qwen2.5-VL-7B). Needed only for NEW
  inference (more issues, re-description). vllm/vllm-openai:v0.20.1 image
  (31.8GB) survives; Qwen2.5-VL-7B weights survive in ~/.cache/huggingface.
- NO recorded launch commands exist anywhere (state file documents names/
  ports/models only; bash history empty; no launch script found).

### Reconstruction status (for tomorrow)
- describer: fully specified — image + HF-cache weights present. Ready to
  relaunch with: -d, NO --rm, --restart unless-stopped, --gpus all,
  -p 8120:8000, HF cache mounted ro, --served-model-name describer,
  conservative --gpu-memory-utilization (~0.35).
- paddlevl: BLOCKED on locating PaddleOCR-VL-1.6 weights — NOT in
  ~/.cache/huggingface (only PP-LCNet doc-ori helper there). Next probes
  queued: ~/.paddle*, modelscope cache, ~/models, /opt/models,
  docker volume ls. Worst case: re-download from HF.
- Side-discoveries during the hunt: HF cache also holds olmOCR-2-7B,
  dots.ocr, surya, chandra (prior judge-landscape evaluation by user —
  dots.ocr locally present weakens the "not worth a container" dismissal;
  parked). Surviving containers have RestartPolicy=no — would NOT survive
  host reboot; fix queued: docker update --restart unless-stopped
  solr-ocr cantaloupe.

### PROCESS RULES minted (paid for in full)
1. NEVER call a container stop "reversible" without checking AutoRemove
   first. Verify, then assert — in that order.
2. Before ANY stop of long-lived infrastructure: capture its full config
   (docker inspect > file) so relaunch is copy-paste regardless of --rm.
3. Launch commands for infrastructure belong IN THE STATE FILE at creation
   time (Phase 1's state file had names/ports but not commands — half a
   record; tonight showed which half matters).

### Where the day actually ended (for perspective, not excuse)
Full-year hybrid index live and verified (6,641 pages, 26.9M words, battery
12/12); ordering + dehyph refreshed; judge question closed with 7/7
ink-verified vindication of VLM-primary; and one hole punched in Phase 1's
inference tier by Claude's unverified assumption. Tomorrow: locate paddle
weights, relaunch both containers with sane policies, verify with test
calls, then back to the menu (viewer / railway-gap).

## Session update 2026-07-16 — INCIDENT RESOLVED: both inference containers rebuilt

### Weights located
- PaddleOCR-VL-1.6: ~/.paddlex/official_models/PaddleOCR-VL-1.6 (2GB; the
  /opt/huggingface_cache entry is a 12K metadata stub, NOT weights)
- Qwen2.5-VL-7B-Instruct: ~/.cache/huggingface (16GB, confirmed working)
- NOTE: /opt/huggingface_cache holds a large OCR-model evaluation collection
  (GLM-OCR, HunyuanOCR, LightOnOCR, chandra, dots.ocr, olmOCR-2, surya,
  talkie-1930-13b) — possibly shared/other users; pre-staged candidates if
  the judge question ever reopens.

### CANONICAL LAUNCH COMMANDS (working, verified by real inference 2026-07-16)
docker run -d --name paddlevl --restart unless-stopped --gpus all \
  -p 8110:8000 --shm-size 8g \
  -v /home/coreyd@uvic.ca/.paddlex/official_models/PaddleOCR-VL-1.6:/model:ro \
  vllm/vllm-openai:v0.20.1 \
  --model /model --served-model-name paddleocr-vl \
  --trust-remote-code --gpu-memory-utilization 0.45 --max-model-len 32768

docker run -d --name describer --restart unless-stopped --gpus all \
  -p 8120:8000 --shm-size 8g \
  -v /home/coreyd@uvic.ca/.cache/huggingface:/root/.cache/huggingface \
  vllm/vllm-openai:v0.20.1 \
  --model Qwen/Qwen2.5-VL-7B-Instruct --served-model-name describer \
  --gpu-memory-utilization 0.48 --max-model-len 32768

### Tuning notes (differences from lost originals, learned the hard way)
- --max-model-len 32768 REQUIRED on both (defaults: paddle 131K -> impossible
  KV demand; single-newspaper-page workload never needs more than 32K)
- Memory split 0.45/0.48 (~44.5 of 47.3GB total): paddle weights only 1.8GB
  but big KV appetite; describer weights 15.6GB — 0.42 failed by exactly
  0.8GB, 0.48 clears with ~3GB cache
- SEQUENTIAL startup mattered: simultaneous launch races the memory
  accounting; restart policy retries eventually converge but cleanly
  launching one-at-a-time avoids the crash-loop phase entirely
- Boot-verify line: "Available KV cache memory:" must be POSITIVE;
  crash-loop signature = log restarting from the vLLM ASCII banner

### Hardening applied
All four containers (solr-ocr, cantaloupe, paddlevl, describer) now
--restart unless-stopped (old two were 'no' — would not have survived
reboot). Verified: real inference test on both models (the eyeball-verified
50c crop; both returned '50c').

## Session update 2026-07-16 — RAILWAY GAP SOLVED: description-text inflation, not a bug

Decomposition: net -81 = 87 missing / 6 gained / 0 quarantine-explained.
Autopsy (0125uvic_13_p019): the page's only 'railway' lives in an
image-labeled block — and corpus sampling (242 image-block contents / 40
pages) shows image block_content = PHASE 1's QWEN DESCRIPTIONS ("The image
is an advertisement...", "The illustration depicts..."), injected by the
describe step, NOT VLM transcription of ad text.
=> The VLM arm's railway count (2,717) mixes ink-matches with matches on
AI-generated descriptions. The hybrid's 2,636 is the honest ink-only count
(+6 pages gained via tess-only rescues). NOT a bug; dedup exonerated;
report card gets this footnote and the hybrid number is the defensible one.
DESIGN NOTE: excluding image-block text from the hybrid MiniOCR was the
right call for the right reason (it's 2025 English prose, not 1925 print).
ENHANCEMENT QUEUED (user decides when): index descriptions as a SEPARATE
Solr field (image_desc, plain text, no OCR highlighting) so picture-search
exists without conflating with text-search — the clean version of Phase 1's
describe feature. Additive: re-post docs w/ extra field from JSONs, no
re-synthesis.

## Session update 2026-07-16 — image_desc FIELD LIVE: picture-search without text-search pollution

### Built (option 1 from researched alternatives; research summary in convo,
### key precedents: LoC Newspaper Navigator 1.56M images; Emerald 2026
### academic-library MLLM-metadata case study; EyCon transparency norm)
- Schema: image_desc, text_general (NOT text_ocr — no highlighting/file-
  pointer semantics), stored, multiValued (one value per image), phase2
  core only (line 479), colonist untouched.
- add_image_desc.py: Solr ATOMIC updates ('set' on image_desc only —
  ocr_text pointers never re-read, no re-analysis). 5,963 pages, 39,458
  descriptions, minutes to run, zero failed batches.

### Verified
- SEPARATION HOLDS: ocr_text:railway unchanged at 2,636 (the design goal —
  Phase 1's arm conflated these; hybrid keeps ink and AI prose distinct).
- image_desc:railway=295, locomotive=126 ("steam locomotive pulling a train
  through a snowy landscape" — undiscoverable by any text search until now),
  advertisement=4,320.

### UI obligation (for the viewer): image_desc results MUST be labeled
AI-generated (transparency norm from the GLAM literature). Upgrade path
logged: free text now -> structured facets (people/place/event) ->
embedding/CLIP visual search (Solr 9 dense-vector) as research-grade
future work / grant line.

## Session update 2026-07-16 (cont.) — VIEWER: Mirador working baseline; zoom-to-hit PAUSED mid-investigation

### Working (verified in browser, uncommitted until now)
viewer.py on :8889 (nohup; NOT reboot-persistent — hardening queued):
search page (ink + images w/ AI label) -> /view/<issue> Mirador 3 (CDN),
IIIF v2 manifests + Content Search (Phase 1 dialect), native hit-centering,
header text/json links tracking current canvas; /text/<page> provenance-
painted reading-order text (+plain toggle, legend, ⇿ superscripts, hover
tooltips w/ box+alt); /json/<page> full per-word records w/ provenance
legend.
KEY FIX: canvas dims MUST come from Cantaloupe info.json (cached), not
MiniOCR wh — mismatch (7466x9478 vs real 7519x9467) broke OSD's tile
handshake (blank page). ALSO NOTED, UNRESOLVED: same mismatch means
TSV-space highlight boxes are ~0.7% off on canvas — needs per-page scaling
(canvas/TSV dims) in /search route; visually small, queued.

### Zoom-to-hit: two failed approaches, investigation designed, PAUSED
1. updateViewport w/ guessed units: zoom=1.2 -> yellow wall (units are
   ~1/visible-width); fixed formula -> viewport driven invalid BEFORE first
   tile request (blank page, zero image requests). Root problem: dispatching
   into Mirador internals on unverified assumptions (the --rm lesson, JS
   edition). Code REMOVED; baseline is native centering (works).
2. NEXT (designed, not run): window.mirador exposed in page script (patch
   applied to file; viewer process NOT restarted w/ it). Probe plan: console-
   inspect store slices ('viewers'?) to learn where/whether OSD instance or
   viewport numbers live, THEN write against observed reality. Possibility:
   updateViewport WAS the right API, only units wrong — probe 2 shows real
   zoom magnitudes.

## Session update 2026-07-16 (cont.) — IMAGE-SEARCH INTEGRATION + /text/ ENRICHMENT

### Image-mode click-through: fixed twice, landed on first-class design
Problem found by user: image hits linked /view/?q= -> Mirador fed the query
to the TEXT search service -> "No results found" + wrong page. Fix 1
(canvas param, no q) lost the search box + highlights. Fix 2 (option B,
chosen): /search/<issue> now ALSO matches image_desc — matching image
blocks returned as IIIF annotations (bbox from paddle JSON, scaled
json-space -> canvas-space via per-page dims; hits prefixed
"[image, AI-described]" as the in-panel transparency label). Home image
hits link ?canvas=<page>&q=<query>. Consequences: Mirador lists image hits
alongside text hits, OUTLINES the described advertisement/illustration on
the page, and zoom-to-hit works on them for free (same annotation map).
Substring-match caveat noted (Solr finds page; substring locates block;
stemmed matches can miss).

### /text/ page enrichment (user-directed, iterative)
- Image-descriptions section: thumbnail crops (Cantaloupe region requests,
  !400,400 fit-within — never upscale; click-through to !1200,1200) beside
  each description, desc+bbox read together from the paddle JSON (single
  source, no cross-source join). Placement iterated: bottom -> collapsed
  <details> directly under the title with count + AI label (visible,
  announced, zero reading cost until expanded).
- Nav: "full page image" link (Cantaloupe /full/full/ in new tab).
- /json/: image_descriptions key (text + box_canvas + provenance note).

### Bugs paid for and rules minted
- iiif_id() called but didn't exist — helper from the pre-Mirador viewer
  lost in the full-file rewrite; silent 'except: return []' converted the
  NameError into empty output and cost 4 diagnostic rounds. RULES:
  (1) silent exception handlers are banned in this codebase — log what is
  swallowed; (2) full-file rewrites must be checked for helpers that
  earlier code (or later patches) still reference.
- Flask test_client via importlib = the fast in-process way to corner
  route bugs without HTTP indirection (worked; keep in the toolkit).

## Session update 2026-07-16 (cont.) — CALENDAR, COMPARE-ARMS MODE, LAYOUT PASS

### Calendar browse (Phase 1 parity)
Date source: Phase 1's precomputed ~/solr-bridge/.issue_dates.json (312
issues, 293 ocr-read + 19 inferred, 0 missing) — issue-level truth, reused
not regenerated. Home page gains collapsed "Browse by date" details: 12
month grids, publication days linked to /view/<issue> w/ page-count +
date-inferred tooltips; Mondays grey year-round (no Monday paper).
BUG PAID: CALENDAR computed at import before issue_pages was defined ->
NameError crash-at-startup that ast.parse could not catch. Fixed lazy
(compute on first request, cached). RULE MINTED: patches touching module
level get a post-patch import smoke test (importlib exec_module), now part
of the restart ritual.

### Compare-arms mode (user-requested; design: counts not "confidence")
Third radio on home: same query vs four populations — Tesseract arm
(colonist, source:tesseract), VLM arm (source:paddleocr-vl, footnoted:
counts include mixed-in image descriptions), Hybrid (colonist_phase2
ocr_text, bolded), Image descriptions (image_desc, AI-labeled). Each row
links to its arm's results (Phase 1 rows -> :8888/findall?q= — front page
ignores ?q=, found by user; /findall is the year-search route). Solr
relevance deliberately NOT presented as confidence (cross-core scores
meaningless). Queued optional: sampled provenance breakdown under the
hybrid row (patch 2, designed not built).
DIAGNOSTIC LESSON: burned a round on a markup-grep verification pattern
that matched the wrong table — verify rendered pages by render-to-text,
not markup regex.

### Layout professionalization (home + results, one stylesheet)
Masthead header (title, subtitle, Phase 1's blue rule), full-width search
+ filled button, mode radios grouped, About/Corpus as quiet nav row,
compare table w/ hairline rules + right-aligned numerals, result cards
restyled. All logic untouched; CSS centralized for cheap iteration.

## Session update 2026-07-16 (cont.) — FOURTH ARM: ABBYY/Internet Archive, ground-truthed

### Machinery
ia_compare.py: enumerates the 312 1925 items (advancedsearch; identifiers
== our issue names exactly; IA date metadata unreliable but irrelevant),
walks per-item search-inside API (fulltext/inside.php via metadata-API
server/dir) at 1 req/s w/ disk cache; counts DISTINCT PAGES (our unit).
ia_cache/ + ia_abbyy_counts.json. Caveats built in: 0725uvic_50 permanently
"not yet indexed" at IA (311/312 coverage — IA's own index has holes);
error responses cached (clear cache file to retry).

### Report card (pages with >=1 match; tess/hybrid/img = our cores)
query        tess   ABBYY  hybrid  img_desc
railway       731   1,818   2,636    295
esquimalt   1,251      88   1,871      8
burridge       14       1      26      0
cathcarts       0       3       2      6
telephone   1,700     993   2,424    493
Headlines: hybrid beats decade-old commercial ABBYY +45% on railway;
BURRIDGE: ABBYY=1 vs hybrid 26 — the rescue content was never findable in
ANY prior system incl. commercial. cathcarts: ABBYY 3 > hybrid-ink 2 (ads
display type; our img_desc=6 wins the category its way). Honest note.

### Anomaly run down (esquimalt 88 vs tess 1,251): NOT case (Esquimalt/
ESQUIMALT identical), NOT engine caps, NOT region dropout (189K words in
test issue). GROUND TRUTH via raw _djvu.txt: ABBYY mangles the word's
FIRST LETTERS systematically — dhquimalt/kxquimalt/kaquimalt/kaqnimalt/
knquimaivr — display-capital E read as K/D pairs. Ink present, unfindable.
Explains telephone shortfall too (COLONIST TELEPHONES display caps).
NEW ERROR-MODE ENTRY: first-letter confabulation on display capitals —
Tesseract-class structural failure, commercial edition, 2015.
PROCESS NOTE: prefix-anchored variant censuses miss first-letter damage;
use shape-anchored patterns (\\w+imalt) — this almost produced a wrong
"region dropout" conclusion.

## Session update 2026-07-16 (cont.) — ON-THE-FLY ABBYY + IA CROSS-LINKS, feature complete

- /abbyy_compute (POST) + /abbyy_status: button on uncomputed ABBYY rows
  spawns ia_compare.py as background subprocess (stdlib-only — immune to
  the env trap); single-job lock (pid-checked, stale-cleared); status
  route tails the job log; page polls every 3s showing live progress
  ("150/312 issues..."), reloads on completion; result persists in
  ia_abbyy_counts.json for everyone after. Cost stated ON the button
  (~5-6 min); single-word guard (IA phrase semantics untested).
- "view at archive.org" on all ABBYY row states. LEARNED: IA's FTS engine
  REJECTS fielded constraints in the query string (collection:/date: are
  metadata-search features — caused "search engine encountered an error");
  the FTS-compatible scoping is the collection details page:
  /details/dailycolonist?query=<q>&sin=TXT&and[]=year:"1925" — verified
  in browser: text-contents mode + year slider clamped to 1925.
- ia_cache/ gitignored (1,900+ response files).

## Session update 2026-07-16 (FINAL) — 4-worker IA concurrency; night closed

- ia_compare.py: count() now ThreadPoolExecutor, 4 workers, per-call 1s
  sleep retained (aggregate ~4 req/s — deliberate middle ground: peer
  institution's free infra, UVic's name on the User-Agent; declined to go
  faster). Fresh query ~80-100s (was 5-6 min); button label updated.
  Thread-safe merge under lock; metadata locations fully pre-cached so
  worker contention on item_loc is theoretical.
- Progress watching (generic): tail -f phase2/ia_cache/.job.*.log — or
  exact current job via the .job.lock's log path.

## STATE AT CLOSE 2026-07-16
Viewer (:8889) feature-complete and demo-ready: search (ink/images/
compare) + tips + 3-way corpus stats + collapsed calendar + Mirador w/
zoom-to-hit + image-block outlining + provenance-painted /text/ (sticky
legend, plain-language classes, thumbnails, full-image link) + /json/ +
/about + /corpus + 5-arm compare w/ on-the-fly ABBYY + IA cross-links.
FOUR-GENERATION RESULT (ground-truthed): tess 731 / ABBYY 1,818 / hybrid
2,636 on railway; burridge ABBYY=1 vs hybrid 26; ABBYY first-letter
display-capital confabulation discovered (dhquimalt/kxquimalt).
QUEUED NEXT: 0.7% box-skew fix (/search route per-page scaling); viewer
hardening (start script w/ micromamba run, reboot persistence); compare
patch 2 (sampled provenance breakdown); suspect-word spot-checks (walia/
romania/fracpi — VLM modernization + notation-leakage hypotheses); THE
WRITE-UP (state file holds the complete story; compare table = Table 1,
provenance /text/ view = figure candidate).

## Session update 2026-07-17 — ABBYY LOCAL INDEX + COMPREHENSIVE REPORT

### ABBYY layer: downloaded, split, indexed (fourth first-class arm)
- Provenance VERIFIED before labeling: hOCR meta = "LuraDocument XML
  Exporter for ABBYY FineReader"; item meta ocr_converted=abbyy-to-hocr
  1.1.37; _abbyy.gz mtime 2015, hocr conversion 2023. IA switched to
  Tesseract-based OCR Dec 2020 — these items were CONVERTED not re-OCR'd,
  so the "ABBYY ~2015" label stands.
- ia_fetch_hocr.py: 312/312 hOCR downloaded (~7GB; 5 transient 500s
  cleared on resume-safe rerun; size-verified vs metadata).
- split_hocr.py: 6,647 per-page .hocr; page counts match our TSVs on ALL
  312 issues; ppageno N -> p(N+1). ABBYY coords full-res (scan_res 300).
- colonist_abbyy core: phase2 config copied; LESSON: plugin jar loads from
  <core>/lib/ (no <lib> directive — Solr auto-loads); plugin AUTO-DETECTS
  hOCR (zero config edits). Smoke-tested (1 page: index/match/box) before
  bulk. 6,647 docs indexed. VALIDATION vs IA API: railway 1,826 vs 1,818
  (+8 = the IA-unindexed issue now covered), esquimalt/burridge/cathcarts
  IDENTICAL — independent confirmation of the ground-truth findings.
- Compare table ABBYY row -> local core (instant, any query, 312/312);
  compute-button machinery retired (ia_compare.py archived, still works).

### Comprehensive report (/report) + live fuzzy widget
- report_build.py: all four arms from LOCAL TEXT LAYERS under one rule
  (tess TSVs w/ conf; VLM paddle JSONs INK-ONLY per user decision; abbyy
  hOCR w/ x_wconf; hybrid MiniOCR alt-stripped). 20-word list
  (report_words.txt), variant censuses (edit<=3, >=3 occurrences),
  monthly series, vocab overlaps w/ real sets, conf histograms.
  Cleanup: alt_test/hyph_test debris moved to phase2/test-fixtures.
- HEADLINE FINDINGS: totals 19.6M/24.1M/27.1M/26.9M (tess/vlm-ink/abbyy/
  hybrid) — ABBYY out-volumes everyone at lowest fidelity ("noisy
  abundance" vs Tesseract's silent gaps). ABBYY vocabulary 3.63M unique
  forms, 3.39M EXCLUSIVE (damage as vocabulary). Hybrid exclusives: 6,876
  — tightest discipline of any arm at 2nd-highest volume. VLM description
  contamination measured precisely: 26.8M indexed vs 24.1M ink-only =
  ~2.7M description words. Esquimalt census: esquimau 358 (LEGITIMATE
  period form — lexicon-aware footnote on page), then kaqulmalt 159,
  ksqulmalt 131, eaqulmalt 109, baqulmalt 102.
- /report: Chart.js page (headline bars, log-scale vocab, length curves,
  conf histograms, word table w/ 5th image-desc column, variant census
  selector, monthly series, overlaps). /fuzzy: live exact/~1/~2 across 5
  populations (Lucene caps fuzzy at 2 — documented; VLM live column
  includes descriptions, labeled — precomputed stats stay ink-only).
- Literature grounding: dictionary lookup + confidence + garbage
  detection = the established no-ground-truth trio (Springmann 2016,
  QuPipe/Cuper, Holley); page carries the estimates-not-accuracy caveat.

## Session update 2026-07-21 — ADVANCED SEARCH REPAIRED (user-found gap)

Bug (user report): boolean/phrase/wildcard/fuzzy worked on Phase 1 (:8888)
but not Phase 2 (:8889) — viewer's naive query builder phrase-wrapped
multi-word input ('railway AND victoria' -> 0 pages as a literal phrase).
FIX: Phase 1's build_q ported verbatim, field-parameterized (date-range
rewriting to Solr datetimes; Lucene-syntax passthrough on
quotes/wildcards/~/parens/UPPERCASE operators; plain words as phrase);
swapped at ALL 7 query sites (home ink, images, compare qq+qd, Mirador
content search, /json image lookup, image-annotation search). Verified:
railway AND victoria 2,632 / esquimal* 1,879 / beecham~1 79 /
"beecham pills"~5 46.
issue_date: field existed in schema (pdate, inherited) but NO doc carried
a value — backfill_dates.py set it on all 6,641 phase2 + 6,647 abbyy docs
from .issue_dates.json (atomic updates, idempotent). Date-range search now
real on both cores; every tips-table promise now true.
