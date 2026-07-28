# Daily Colonist 1925 — Hybrid OCR Pipeline (Phase 2)

A word-level merge of two OCR engines' readings of the 1925 *Daily Colonist* (312 issues, 6,647 newspaper pages): the text of a vision-language model (PaddleOCR-VL) combined with the measured word positions and confidence scores of Tesseract 5, with every disagreement decided by explicit rules, undecidable disagreements indexed under both readings, regions the model missed rescued from Tesseract's output, and a provenance class recorded for every word. Indexed in Solr with word-level highlighting; served through a IIIF/Mirador viewer with a per-word provenance display; compared against the collection's existing ABBYY-era search layer, which was downloaded and indexed as a fourth arm.

**Institution:** University of Victoria Libraries
**Author:** [FILL]
**Phase 1 (the two source pipelines this phase merges):** https://github.com/coreyleedavis/daily-colonist-1925-dual-ocr
**License:** [FILL — MIT pending confirmation]

**In-depth documentation:** [How the merge works](docs/phase2-merge-technical-note.md) — the complete method, stage by stage, with the rationale for each decision, the full annotated sources, and the prior work this approach descends from.

> **AI-assistance disclosure:** substantial portions of this codebase were written in AI-pair-development sessions with Claude Fable (Anthropic), under a verify-before-acting protocol. All code was executed and verified by the human author.

---

## What this is

Phase 1 of this project (linked above) ran two independent OCR pipelines over the same 6,647 pages and compared them. This repository is Phase 2: the pipeline that merges those two outputs into one index that is better than either.

The two engines fail in complementary ways. Tesseract 5 reports an exact position and a confidence score for every word, but misreads degraded microfilm often and silently skips entire regions. The vision-language model transcribes far more accurately, but reports only one position per block and no confidence. The merge takes the model's text, attaches Tesseract's measured positions wherever the two transcriptions can be aligned character-by-character, uses Tesseract's confidence and an external dictionary to decide disagreements, indexes both readings when no rule can decide (≈498,000 word positions carry an alternative), and rescues regions the model never transcribed by clustering Tesseract's leftover words.

Every word in the output carries one of twelve **provenance classes**. Across the year's 26.9 million words: 35.7% `agree` (both engines identical), 39.1% `interp` (model text in an estimated position — a direct measurement of how much of the page Tesseract silently skipped), 6.6% `vlm-routed`, 4.6% rescued (`tess-only`), 3.5% `punct`, the rest smaller classes. The viewer paints any page's text by class, so a user can always see how any word was produced.

**Findability, measured on identical scans** (pages with ≥1 match):

| query | Tesseract 5 | ABBYY ~2015 (the collection's existing layer) | Hybrid |
|---|---:|---:|---:|
| railway | 731 | 1,818 | **2,636** |
| esquimalt | 1,251 | 88 | **1,871** |
| burridge | 14 | 1 | **26** |
| telephone | 1,700 | 993 | **2,424** |

AI-generated image descriptions (produced in Phase 1) are indexed here in a **separate field**, searched only in an explicitly labeled mode, and never counted as page text — correcting a conflation Phase 1's index contained.

## What this is not

- **Not a turnkey package.** Working research scripts with machine-specific paths, published for transparency and reuse of the approach.
- **Not self-contained.** The pipeline's inputs are Phase 1's outputs: Tesseract TSVs and the model's per-page JSON (with image descriptions merged). Run Phase 1 first, or adapt the input loaders.
- **Not the corpus.** Page images are in the Internet Archive's [dailycolonist collection](https://archive.org/details/dailycolonist).

## Repository layout

```
pipeline/      the merge itself: shared library, per-page synthesis, year driver
indexing/      Solr loading; image-description field; the ABBYY fourth arm
analysis/      alignment/coverage/routing analysis and the comparative report builder
arbitration/   the model-judged arbitration study (a documented negative result)
tests/         the per-stage test scripts that locked each component
viewer/        the search viewer (Flask, port 8889) and its report/about pages
docs/          the merge technical note and the project state file (lab notebook)
solr-config/   the hybrid core's Solr configuration
sample_data/   word list, report data, issue dates, test fixtures
```

## The pipeline

| Script | What it does |
|---|---|
| `pipeline/phase2lib.py` | The canonical shared library: TSV loading (with the quoting rule that prevents silent row loss), line ordering, character alignment, orphan clustering, rescue verdicts, reading-order insertion. Components were locked here after passing their tests and are imported, never re-typed. |
| `pipeline/synthesize.py` | The per-page merge: deduplication → word-to-block assignment → character alignment → the routing cascade → geometry inheritance → rescues → seam dehyphenation → MiniOCR + provenance sidecar. The technical note in `docs/` documents every stage. |
| `pipeline/smoke_run.py` | Small-batch run for verification. |
| `pipeline/full_run.py` | The year driver: all 312 issues. |

Output per page: a MiniOCR file for the index and a `*.provenance.json` sidecar recording each word's class in emission order.

## Indexing and the fourth arm

`indexing/` loads the hybrid into Solr (`add_image_desc.py` populates the separate image-description field; `backfill_dates.py` sets issue dates for date-range search) and builds the comparison baseline: `ia_fetch_hocr.py` downloads the Internet Archive's hOCR derivatives for all 312 issues (~7 GB; these are format-converted ABBYY output from ~2015 — the provenance was verified from item metadata before labeling), `split_hocr.py` splits them per page, `index_abbyy.py` indexes them into their own core, and `ia_compare.py` is the earlier API-sampling comparator the local index superseded (kept for the record; its counts validated the local index within a few pages).

## The arbitration study (a negative result, kept)

Roughly 58,000 disagreements are numeric ("45¢" vs "45c") and cannot carry indexed alternatives (see the technical note, §4.5). The `arbitration/` harness evaluated whether a multimodal model judging word-image crops could arbitrate them. Findings: severe position bias in A/B protocols at the 7B scale (label order swapped the verdict in 14 of 16 instrumented crops); honest abstention but zero corrections from stronger models; and — decisive — human verification of the crops against the printed page showed the evaluation's own "ground truth" (built from Tesseract's high-confidence readings) was wrong: the model's disputed readings were correct in every humanly resolvable case, including a Tesseract glyph confabulation at confidence 58–88. The band ships model-primary, unarbitrated, by measurement rather than assumption. The harness is judge-agnostic and reusable; its acceptance protocol begins with verifying the instrument against the page.

## Tests

The twelve `tests/test_*.py` scripts are the development record: each pipeline stage was built against its test, and the passing version was locked into `phase2lib.py`. The dedup series (`test_dedup*.py`) documents the rejected fuzzy-matching versions as well as the shipped strict rule.

## The viewer

`viewer/viewer.py` (Flask, port 8889) serves: search over printed text, image descriptions (labeled mode), and a live five-arm comparison (Tesseract / VLM / ABBYY / hybrid / image descriptions) for any query; Mirador page view with zoom-to-hit highlighting; a per-page text view painted by provenance class with a plain-language legend; corpus statistics; a comparative report page (`report.html`) with charts and a live fuzzy-findability widget; and Lucene query syntax throughout (phrases, boolean, wildcards, fuzzy, date ranges). Requires the Solr cores, Cantaloupe, and the year's images in place.

## Honest caveats

1. **39.1% of word positions are estimates** (`interp`), disclosed per word in the provenance record and in the viewer's legend. Highlights in those regions land on the right line, not always the exact word.
2. **No ground truth exists.** Quality evidence is cross-engine agreement, dictionary rates, confidence distributions, and targeted human verification against the page image — correlates, not error rates. The technical note's §6 describes the verification practices.
3. **The corpus-derived 1925 lexicon is polluted by Tesseract's errors** and is used only as a comparable measuring stick, never for routing decisions (routing uses the system dictionary).
4. **Paths, ports, and endpoints are the project machine's.** Expect to edit constants.
5. `docs/PROJECT_STATE_PHASE2.md` is the project's working state file, published as-is as the development record — including failures and their repairs.

## Citation

If you use this code or approach, please cite: [FILL when published].

## Acknowledgements

[FILL]. Scans digitized by the University of Victoria Libraries; hosted by the Internet Archive. The solr-ocrhighlighting plugin is by dbmdz (Munich Digitization Centre, Bavarian State Library).
