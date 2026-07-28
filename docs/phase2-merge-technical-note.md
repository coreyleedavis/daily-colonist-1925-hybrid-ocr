# Merging Two Readers: How the Phase 2 Hybrid Combines Tesseract and Vision-Language Model Output

**Technical note — *The Daily Colonist* 1925 search project, Phase 2**
**Subject:** `phase2lib.py` and `synthesize.py` (complete listings in Appendices A and B)
**Related document:** *Word Geometry Generation in the Phase 1 PaddleOCR-VL → MiniOCR Converter* (the Phase 1 converter note)

---

## Summary

This document describes the program that merges two independent OCR readings of the same newspaper page into one search index. The two readings come from engines with opposite strengths. Tesseract 5 reports an exact position and a confidence score for every word it reads, but it misreads degraded print often and silently skips entire regions. The vision-language model (PaddleOCR-VL) transcribes far more accurately, but it reports only one position per block — a paragraph or headline, not a word — and no confidence at all.

The merge takes the model's text and assigns each word Tesseract's measured position wherever the two transcriptions can be matched. For each page it: removes duplicate blocks the model emitted twice; assigns every Tesseract word to the model block that contains it; aligns the two transcriptions character by character within each block; decides, for every word where the two engines disagree, which reading to display — and, when the disagreement cannot be decided, indexes *both* readings at the same position so a search for either finds the page; recovers regions the model never transcribed by clustering Tesseract's leftover words and splicing them into the reading order; rejoins words split across line breaks when a dictionary confirms the join; and writes the result as MiniOCR (the index format) plus a sidecar file recording, for every word, exactly how it was produced.

Every word in the output therefore carries one of twelve provenance classes — from `agree` (both engines read it identically) to `interp` (model text in an estimated position) to `tess-only` (rescued from a region the model missed). Across the year's 26.9 million words: 35.7% `agree`, 39.1% `interp`, 6.6% `vlm-routed`, 4.6% rescued, the rest smaller classes. The design's governing rule, applied at every decision point below: when a choice must be made without evidence, prefer the failure that a user can recover from.

## 1. The problem and the design idea

A search index for page images needs three things per word: the text, a position (so a match can be highlighted on the image), and — ideally — some account of reliability. Neither engine supplies all three.

| | Tesseract 5 | PaddleOCR-VL |
|---|---|---|
| Text accuracy on this material | poor to fair | good to excellent |
| Position granularity | per word, measured | per block only |
| Confidence | per word, 0–100 | none |
| Characteristic failure | misreads; silently skips regions | rare misses at block level |

The design idea is that these failures are complementary, so the outputs can check and complete each other: use the model's text (the better reading), use Tesseract's geometry wherever the two texts can be aligned (the only measured word positions that exist), use Tesseract's confidence to help decide disagreements, and use Tesseract's coverage to fill the model's gaps. Nothing is averaged and nothing is silently overwritten: every decision leaves a record, and undecidable disagreements are preserved rather than resolved by guesswork.

## 2. Where this approach sits in prior work

Combining multiple recognizers' output is an established idea. The ROVER system did it for speech recognition in 1997, aligning several recognizers' transcripts and voting [5]. Lopresti and Zhou brought consensus voting to OCR the same year [4]. The closest relative of this work is Lund and Ringger's 2009 study, which aligned the output of multiple OCR engines into a *lattice of alternatives* — a structure holding every engine's reading at each position — and showed that the lattice's error rate ran roughly 55% below any single engine's, with a dictionary-based process selecting among the alternatives [3]. Later work extended the idea to progressive alignment across more engines [6] and to merging noisy OCR of different editions of the same book [7]; a survey article reviewing this category of methods, along with post-OCR processing generally, is available [8].

This pipeline is a descendant of that line with four differences. First, the two engines here are *complementary rather than similar*: prior systems combined several engines of the same kind, while this one pairs a geometric engine with a generative one, and the merge transfers geometry as much as text. Second, the lattice survives into the index: where Lund and Ringger's selection process chose one reading, this pipeline's final stage can index *both* readings of an undecidable word at one position, so the user's query — not the pipeline — resolves the ambiguity. Third, every word carries provenance, so the merge is auditable after the fact. Fourth, this pipeline never modifies what either engine read. A common alternative approach, called post-OCR correction, takes one engine's transcript and edits it — a spell-checker or a language model changes words it judges to be errors. Nothing like that happens here: both engines' readings pass through unaltered, and the pipeline's only decisions are which reading to display, which position to attach, and whether to record the other reading as an alternative. Every word in the index is a reading one of the two engines actually produced from the page image, with a single exception: words the typesetter split across a line break are rejoined when a dictionary confirms the joined form (§4.10).

## 3. The inputs, and two loading rules learned from failures

**Tesseract's side** is a TSV file per page: one row per recognized word carrying pixel position (left, top, width, height), confidence (0–100), and the text. The loader (`load_tess_words`, Appendix A) contains one rule that exists because of a specific failure:

```python
r = csv.reader(f, delimiter='\t', quoting=csv.QUOTE_NONE)
```

Python's CSV reader, by default, treats a quotation mark as the start of a quoted field. A 1925 newspaper is full of quotation marks — and with default quoting, rows containing them were silently swallowed. The source comment records the damage: default quoting "silently ate 1/3 of rows on 1925 quote-heavy text." `QUOTE_NONE` tells the reader that quotation marks are just characters. The general lesson: parsing defaults tuned for clean modern data can fail silently on historical text, and silent failures are costly because nothing signals that data has been lost.

**The model's side** is a JSON file per page: a list of blocks, each with a label (`text`, `title`, `table`, `image`, …), the block's transcribed text as one string, and one bounding rectangle in the model's own coordinate space (2,560 pixels wide). The text is first cleaned by the same sanitizer the Phase 1 converter established (HTML table tags removed, dashes to spaces, invalid characters dropped — the rationale is in the Phase 1 note and is not repeated here).

**Coordinate conversion** between the two spaces uses no constants. Both files declare their own page dimensions, so the ratios are computed per page from the files themselves:

```python
sx, sy = vlm['width']/tess_w, vlm['height']/tess_h
```

The conversion runs in both directions. To decide whether a Tesseract word falls inside a model block, the word's center point is multiplied by `sx` and `sy`, moving it into the model's coordinate system where the block rectangles live. At the end of the pipeline the direction reverses: the output must use full-resolution page coordinates (that is what the viewer draws highlights against), so model rectangles are converted into Tesseract's coordinate system by dividing by the same ratios.

The ratios are computed fresh for every page, from the dimensions each page's own two files declare, because page dimensions vary from scan to scan. This applies a lesson from Phase 1 directly: the Phase 1 converter shipped with a single fixed scale constant as its default, and that constant turned out to be correct for almost no actual page — page widths across the year vary by more than 200 pixels, and a scale that is even slightly wrong displaces every box on the page, most severely at the right edge. Reading each page's real dimensions from its own files makes that class of error impossible.

## 4. The pipeline, stage by stage

### 4.1 Removing duplicate blocks

The model occasionally emits a region twice — the same paragraph as two overlapping blocks, or a block plus a fragment of itself.

Why this happens follows from how the layout stage works. The model's first stage is an object detector: it proposes candidate rectangles for regions of the page, each with a label and a score, and a standard filtering step (non-maximum suppression) then removes proposals that overlap strongly with a higher-scoring one. That filter is imperfect in two situations that dense newspaper pages produce constantly. First, partial overlaps can survive it: a rectangle around a whole paragraph and a second rectangle around just its opening lines may both score well while overlapping too little to trigger suppression — the detector is genuinely uncertain whether it is looking at one region or two, and both hypotheses survive. Second, suppression is typically applied within a label class, so the same region proposed once as `text` and once as `title` can pass through as two blocks. A separate mechanism produces the fragment case: when two surviving rectangles overlap at their boundary, each is transcribed independently, so text in the shared strip appears in both transcriptions — and when the strip cuts through a word, the second block begins with the severed piece of it, which is the hyphen-stub pattern the rule below specifically matches. The detector was not instrumented to measure how much each mechanism contributes; the deduplication rule is written against the observed output patterns, not against a theory of their origin.

Indexed as-is, duplicated text doubles match counts and clutters snippets. The deduplication rule (Appendix B) is deliberately narrow. Block A is dropped only when *all three* of these hold: A's text is no longer than B's; their rectangles overlap by at least half of A's area; and either A's whitespace-squashed text appears verbatim inside B's (minimum eight characters, so trivial fragments cannot trigger a drop), or A is a *hyphen-stub* continuation of B — A ends with a hyphenated fragment whose surrounding text (at least twelve characters of it) appears in B at the position where B continues with that same fragment.

The rule is deliberately strict, and the strictness was a decision, not an accident. An earlier version of the deduplication used approximate text similarity: two blocks whose texts were merely close would be treated as duplicates and one dropped. Testing rejected that version, because a newspaper legitimately contains text that is nearly identical without being duplicated. A shipping table lists many arrivals in the same format; a classified column repeats the same phrasing ad after ad; the same advertisement runs in multiple issues. Under a similarity rule, one of two genuinely distinct rows would be deleted as a "duplicate" of the other.

The choice between the strict rule and the similarity rule comes down to comparing the errors each one makes. The strict rule sometimes fails to remove a real duplicate. The cost is a redundant search match — the same text appears twice — which a reader recognizes and ignores as soon as they look at the page. The similarity rule sometimes removes a block that was not a duplicate. The cost is that real content disappears from the index, and nothing tells anyone it is gone. The first error is visible and cheap; the second is invisible and permanent. Requiring exact containment keeps the second kind of error at zero and accepts a small number of leftover duplicates as the price.

### 4.2 Assigning Tesseract's words to the model's blocks

Every Tesseract word is assigned to the model block whose rectangle contains the word's *center point* (after coordinate conversion). Center-point containment, rather than area overlap, is used because it is a partition: a word straddling a block boundary has exactly one center, so it gets exactly one home, and no word is counted twice. Words assigned to a block are marked `claimed`; words claimed by no text block become candidates for the rescue stages (§4.8). Blocks the model labeled as images are excluded from this assignment — their handling is separate (§4.8) — so picture regions cannot capture body text that merely overlaps them.

Within each block, the claimed Tesseract words must be put into reading order — the order a person would read them, line by line, left to right — because the character alignment in the next stage compares the two texts as sequences, and a scrambled sequence cannot align.

The ordering (`order_into_lines`, Appendix A) works in two steps. First, words are grouped into lines. The words are sorted by vertical position, then walked top to bottom: each word joins the current line if its vertical center is close enough to the line's running average center, and otherwise starts a new line. Second, the words within each line are sorted left to right.

The important decision is what "close enough" means. It is not a fixed number of pixels. It is 0.6 times the median height of the words in the block — a threshold that scales with the size of the type actually present. The reason a fixed threshold cannot work is that this page contains type at very different sizes: six-point classified advertising, where lines sit perhaps 40 pixels apart, and display headlines, where a single line of type is over 100 pixels tall. A pixel threshold small enough to keep adjacent classified lines separate would split one headline's slightly uneven letters into several "lines"; a threshold large enough for headlines would merge classified lines together. Deriving the threshold from the block's own median word height gives each block a rule proportioned to its own type.

This was learned from a failure. The first version of the aligner used a fixed grouping interval, and the source comment records the result: it "scrambled body text" — words from adjacent lines were interleaved into a wrong order, which then poisoned the character alignment built on top of it.

### 4.3 Character-level alignment

This is the central step of the merge: within one block, the two engines' texts are aligned as *character sequences*, and the alignment tells each model word which Tesseract word (if any) corresponds to the same printed text.

Why characters rather than words? Because the disagreements that matter most are exactly the ones that break word-level matching: Tesseract fuses two words into one token, splits one word into fragments, or misreads letters so badly that the words no longer look equal. A character-level alignment sees through all three — the shared correct characters still line up even when the word boundaries or some letters differ.

The implementation (`char_align`, Appendix A) uses Python's `difflib.SequenceMatcher`, which implements the Ratcliff-Obershelp "gestalt pattern matching" algorithm [9]: it finds the longest contiguous matching block of characters, then recursively matches the regions to its left and right, producing a set of matching spans. Three deliberate settings:

- **The comparison is case-blind but offset-exact.** Both strings are uppercased before matching — the engines frequently disagree only in case — but with a length-preserving uppercase (`_upper1`) that leaves alone any character whose uppercase form expands to multiple characters. Ordinary `upper()` can change a string's length: the ﬁ and ﬂ ligatures — single characters that 1925 letterpress used routinely in words like "ﬁnd" and "ﬂour," and that model output can contain — become the two letters FI and FL when uppercased, and a length change would shift every character index after it, corrupting the map from alignment positions back to word positions.
- **`autojunk=False`.** SequenceMatcher's default behavior treats characters that appear very frequently as "junk" and ignores them — a heuristic that speeds up comparisons of source code but, on long stretches of ordinary English (where the space character and the letter *e* are everywhere), causes the matcher to skip exactly the characters that anchor the alignment. Python's own documentation notes the heuristic can misfire on long sequences; it is disabled here.
- **A size guard.** The comparison algorithm's running time grows with the *product* of the two text lengths: aligning two 100-character texts is fast, but two 10,000-character texts cost ten thousand times more work, not a hundred. Most blocks are short and align in milliseconds. A few are not: on dense table blocks, both engines produced thousands of characters, the two transcriptions barely agreed, and the alignment of one such block ran for minutes. The guard refuses to run the alignment when the length product exceeds four million characters-squared (the `ALIGN_GUARD` constant); the block's words then receive estimated positions instead (§4.6).

    The reason this costs nothing in practice: minutes of alignment on a low-agreement table block does not produce usable matches anyway. When two transcriptions barely agree, the alignment finds only scattered coincidental matches, the words end up with no clear Tesseract owner, and they take estimated positions — the same outcome the guard imposes directly, minus the minutes of computation. The source comment records the specific page whose table blocks demonstrated this, which is how the constant earned its place.

The alignment's output is a character-by-character map: for each character in the model's text, either the position of the matching character in Tesseract's text, or nothing if no match was found. This map is between characters, but the merge needs a relationship between *words* — the question to be answered is "which Tesseract word corresponds to this model word?"

Getting from characters to words takes one bookkeeping step. When the block's Tesseract words were joined into a single text for alignment, a record was kept of which word each character came from. So for any model word, the pipeline can take its characters, follow the map to the matching Tesseract characters, and look up which Tesseract words those belong to. The result, for each model word, is its set of Tesseract "owners" — the Tesseract word or words that share its characters. A concrete example: if the model read `Railway` and Tesseract read `Rallway` at the same spot, six of the seven characters match, all six matches fall inside the one Tesseract word, and `Railway` gets exactly one owner. The number of owners — one, several, or none — is what the next stages act on.

### 4.4 The shrapnel rule

Before positions are assigned, one protective pass runs. When Tesseract shatters a region into garbage, its fragments can each attract alignments from several model words — many good words all claiming pieces of one bad token. Inheriting positions from such a token would place correct text at a garbage fragment's coordinates. The rule: if a single Tesseract word is claimed by **two or more** model words whose combined length exceeds **twice** the Tesseract word's length, that Tesseract word is declared shrapnel, and every model word claiming it takes an estimated position instead (`interp-shrapnel`). The principle: matching against garbage is worse than admitting no match exists.

### 4.5 Deciding disagreements: the routing cascade

For a model word with exactly one Tesseract owner, the two engines have each produced a reading of the same ink. The cascade decides what the index displays, in order, taking the first rule that applies. Each rule's class name is what appears in the word's provenance record.

1. **`agree`** — the readings are identical (case-blind). No decision needed. 35.7% of the corpus.
2. **`punct`** — identical once surrounding punctuation and typographic quote variants are normalized away. The engines transcribe quotation marks and word-edge punctuation inconsistently; these are not real disagreements.
3. **`vlm-routed`** — the model's reading is displayed, because either Tesseract's own confidence in its reading is **below 50**, or Tesseract's reading is a *truncation* — its normalized text appears inside the model's word (Tesseract read a fragment of what the model read whole). In both situations Tesseract's own output indicates its reading is unreliable: a low confidence score is the engine reporting uncertainty, and a truncated reading is visibly incomplete.
4. **`vlm-dict` / `tess-dict`** — the external dictionary votes. If exactly one engine's reading is a dictionary word and the other's is not, the dictionary word is displayed. This is symmetric, and `tess-dict` is the one place in the pipeline where **Tesseract's reading wins the display**: when Tesseract read a real word and the model produced a non-word, Tesseract's text is shown and the model's becomes the indexed alternative. The dictionary is the system's word list (American and British English combined — appropriate for a Canadian paper that uses both spellings), deliberately *not* the corpus-derived 1925 lexicon: that lexicon was built from Tesseract's own output and contains Tesseract's errors, so using it for routing would treat those errors as correct spellings.
5. **`residual-alt`** — none of the rules above applied. The two engines read the same printed word differently, and every available test failed to separate them: Tesseract's confidence in its reading is 50 or higher (the model, which reports no confidence, cannot be tested this way at all), Tesseract's reading is not a fragment of the model's, and the dictionary either recognizes both readings or recognizes neither. At that point the pipeline has no evidence left for choosing between them. Rather than choose anyway, it keeps both. The model's reading is displayed (consistent with the model being the more accurate engine overall), and the word is indexed under *both* readings at the same position. The index plugin supports this directly [2]: the emitted word contains the two readings joined by a separator character (⇿), and the plugin indexes each as a searchable term at that word's position. The practical effect is that a person searching for either spelling finds the page — if the model read *Cathcart* and Tesseract read *Catheart*, a search for either one lands on this word, and the page image settles which was printed. This is the lattice-of-alternatives idea from the prior work (§2) carried one step further: where Lund and Ringger's system used its lattice internally and then selected a single reading for output, here the unresolved part of the lattice survives into the live index, and the user's own query does the selecting. Across the year, approximately 498,000 word positions carry an alternative reading.

One constraint shapes what can carry an alternative. The emitter's `safe_alt` check permits ⇿ alternatives only when both readings are single, purely alphabetic tokens (apostrophes allowed): content the index's tokenizer would split — digits, internal punctuation, currency symbols — severs the joined alternative into pieces and corrupts the position arithmetic the highlighter depends on. The consequence is that *numeric* disagreements ("45¢" versus "45c" — prices, quantities, measurements, roughly 58,000 cases) cannot use the both-readings mechanism and must ship a single reading. Which reading to ship was investigated separately. Candidate judge models were evaluated for arbitrating the band, and the decisive step of that evaluation was checking a sample of the disputed readings by eye against the printed page: the model's reading was correct in every case a human could resolve. The band therefore ships with the model's reading.

Words with **multiple** Tesseract owners (the model read one word where Tesseract produced several tokens — spacing and hyphenation differences) take the class **`multi`**. Words with **no** owner take **`interp`**.

### 4.6 Geometry: measured, sliced, union, estimated

Each routing outcome has a geometric counterpart:

**One owner: a slice of the measured box.** Tesseract's box is a measured rectangle around *its* token. The model's word takes the horizontal portion of that rectangle corresponding to the characters it matched. When the two words matched end to end, that portion is the entire box, and the model word simply inherits it. The interesting case is a fused token. Suppose Tesseract read a masthead line as the single token `COLONISTTELEPHONES` — one token, one measured box 900 pixels wide — while the model correctly read two words, `COLONIST` and `TELEPHONES`. The alignment maps `COLONIST` onto the first 8 of the token's 18 characters and `TELEPHONES` onto the last 10. Each model word's box is the corresponding fraction of the measured box: `COLONIST` gets the left 8/18 (400 pixels), `TELEPHONES` the right 10/18 (500 pixels). Both words end up with positions derived from measurement, at the cost of assuming characters within the token are evenly wide.

**Several owners: the union of their boxes (`multi`).** The reverse situation: the model read one word where Tesseract produced several tokens — for example, Tesseract read `rail way` as two tokens and the model read `railway` as one. The model word's box is the smallest rectangle that contains all of its owners' boxes. The result is measured geometry, slightly generous: the union includes the space between the tokens.

**No owner: an estimated box (`interp`, `interp-shrapnel`).** These are words for which no matching Tesseract characters exist — the regions Tesseract dropped, plus words whose only match was disqualified by the shrapnel rule. Their boxes are estimated, and the estimation runs after every measured box on the line is in place, so that measurements can constrain it. The procedure, per output line: a cursor starts at the block's left edge and the line's words are walked left to right. When the walk reaches a word that already has a measured box, the cursor jumps to that box's right edge. When it reaches a word without a box, the word is placed at the cursor, given a width proportional to its share of the line's total characters, and the cursor advances past it. The effect is that estimated words fill the gaps *between* measured ones: an estimated word sitting between two measured neighbors cannot drift outside the space those neighbors leave for it. Vertically, an estimated word uses the line's measured words when the line has any — the topmost top edge and the tallest height among them — and otherwise the block's height divided evenly among its lines.

This estimation is the Phase 1 converter's character-proportional model with one improvement. In Phase 1, no measured word positions existed at all, so entire lines were estimated end to end, and estimation error could accumulate across a full line's width. Here, most lines contain at least some measured boxes, and every measured box is an anchor that resets the estimate: error can accumulate only across the gap between one measurement and the next, not across the line.

The distinction between measured and estimated is not cosmetic: it is recorded per word (the `interp` classes), disclosed in the viewer's legend, and it is the accepted cost of indexing the 39.1% of words — Tesseract's dropout, made countable — that the geometric engine never saw.

### 4.7 Rescue one: Tesseract words inside image regions

Words the model's blocks never claimed are not discarded. The first rescue pass collects unclaimed Tesseract words whose centers fall inside blocks the model labeled *image*. Newspapers set real text inside illustrated advertisements, and the model's image label correctly identifies the region as pictorial without transcribing the text within it. Words here are kept when they contain at least one alphanumeric character and carry confidence ≥ 40, take the class **`tess-in-image`**, and are grouped into display lines. The class is kept distinct from the general rescue below because its evidentiary situation differs: the region *was* seen and classified by the model; only its text went unread.

### 4.8 Rescue two: orphan clusters

What remains after that are the true orphans: Tesseract words in regions the model did not transcribe at all — dropped headlines and skipped classified columns. They are grouped into blocks by adaptive two-dimensional clustering (`cluster_orphans`, locked as version 3 after two rejected predecessors):

- Two words are *joinable* when their vertical gap is at most 1.5× and their horizontal gap at most 2.0× the taller word's height (with a 15-pixel floor). Scaling the gaps to local type size means the same rule clusters agate classifieds and display headlines correctly.
- Words are agglomerated into clusters greedily, then clusters are merged while any pair remains joinable. (A bounding-box prefilter accelerates the pair tests; the source comment proves it skips only pairs that would test false, so performance work changed no decisions.)

Each cluster then receives a verdict (`orphan_verdict`) from its **median** Tesseract confidence and a content check:

- If half or more of the cluster's words contain no alphanumeric character at all: **discard**. Such clusters are noise: marks on the microfilm and printed ruling lines that Tesseract recognized as strings of punctuation.
- Median confidence ≥ 80: **keep**, class `tess-only`.
- Median 40–79: **keep but flag**, class `tess-only-lowconf` — indexed and searchable, visibly marked as lower-trust in the provenance record.
- Median < 40: **discard**.

The thresholds were set by comparing the two ways this verdict can go wrong.

The first error is keeping a cluster that is actually junk. Its cost is small and visible: the junk is indexed, someone's search occasionally matches it, and the person looks at the page image, sees there is nothing there, and moves on.

The second error is discarding a cluster that is actually real text. Its cost is large and invisible: the text is absent from the index, no search can ever find it, and nothing anywhere indicates that it existed. The source comment names this asymmetry in the project's own shorthand — "flagging junk ~free, discarding real text = Burridge" — where *Burridge* refers to the case that demonstrated the cost: an obituary whose subject, before this rescue stage existed, could be found on only one page across a decade of the collection's existing search, because the regions naming him had never been indexed.

Because the second error is so much worse than the first, the gates lean toward keeping: a genuinely bad cluster must fail clearly (median confidence below 40, or mostly non-alphanumeric content) before it is discarded, and the doubtful middle band is kept with a visible flag rather than thrown away.

One statistical choice serves the same goal. The verdict uses the cluster's *median* confidence, not its average. An average can be dragged down by a few words at zero confidence even when most of the cluster is read well; the median ignores those outliers and reflects the typical word. A cluster that is mostly readable therefore survives a few unreadable words in it.

### 4.9 Putting rescued blocks in reading order

Rescued blocks must be spliced into the model's block sequence at a sensible reading position — a rescued headline should precede the story under it, not trail the page. The placement rule (`insertion_index`) is geometric: a model block *precedes* a rescued block if it is in the same column (their horizontal overlap is at least 30% of the narrower one) and starts higher, or if it lies in a column strictly to the left. The rescued block is inserted after the last block that precedes it. Insertions are applied farthest-position-first so that each insertion cannot shift the target index of the next. This column-flow rule was verified at corpus scale: across roughly 926,000 adjacent block pairs in the year's output, 0.022% violate geometric reading order — the residue of genuinely ambiguous layouts.

### 4.10 Rejoining hyphenated words at seams

Line-break hyphenation was handled once already, inside the model's own blocks (the Phase 1 converter's conservative merge). Two kinds of seam remain: the boundary between one block and the next, and the line boundaries inside rescued clusters. The seam pass differs from Phase 1's rule in one deliberate way: here the hyphen is **removed** — but only when a dictionary confirms the join.

```python
joined = m.group(1) + _re.match(r'^([a-z]+)', w2['text']).group(1)
if joined.lower() not in DICT: return False
```

The two rules are opposite because their evidence differs. Phase 1's converter had no dictionary and could not distinguish a genuine compound (*six-room*) from a typesetter's split (*rail-way*), so it kept the hyphen — the non-destructive default. This pass *has* a dictionary: it removes the hyphen only when the joined form is a real word (*rail-* + *way* → *railway*, confirmed), and leaves everything else untouched — *six-* + *room* fails the dictionary test (*sixroom* is not a word) and correctly stays as printed. Same conservatism, better evidence, stronger repair.

### 4.11 Emission: the index file and the provenance sidecar

The output is two files per page. The first is MiniOCR for the index — page dimensions on the page element, blocks, lines, and words with integer pixel boxes, with undecided disagreements carrying their alternative:

```xml
<p xml:id="dailycolonist0325uvic_1_p012" wh="7487 9577">
  <b><l>
    <w x="2101 4180 312 64">Nazimova</w>
    <w x="2725 4180 210 62">portrayal⇿portrays</w>
  </l></b>
</p>
```

The second is the provenance sidecar: a JSON list, in emission order, of `{"t": word, "prov": class}` entries — one per emitted word. The sidecar is what makes the merge auditable: any consumer can reconstruct, for any word on any page, which engine said what and how the decision was made, with one array lookup. The viewer's per-page text view is built on it; so is the corpus-wide provenance distribution.

## 5. What the output claims, and what it does not

The twelve classes, with the year's distribution:

| class | share | meaning |
|---|---:|---|
| `interp` | 39.1% | model text; estimated box (Tesseract never saw this ink) |
| `agree` | 35.7% | both engines identical; measured box |
| `vlm-routed` | 6.6% | model text over low-confidence or truncated Tesseract; measured box |
| `tess-only` | 4.6% | rescued from model-missed regions; measured box |
| `punct` | 3.5% | punctuation-only difference; measured box |
| `multi`, `residual-alt`, `vlm-dict`, `tess-dict`, `interp-shrapnel`, `tess-in-image`, `tess-only-lowconf` | < 3% each | as described above |

The output does **not** claim correctness. It claims traceability: every word records how it was made, estimated boxes are labeled as estimates, lower-confidence rescues are flagged rather than presented as equal to the rest, and undecided readings are preserved as alternatives rather than settled by an arbitrary choice. The size of the `interp` class is itself a finding — a direct, per-word count of how much of the page the geometric engine skipped without reporting — and it is presented as such rather than hidden.

## 6. How the pipeline was verified

The basic difficulty is that no ground truth exists: nobody has a correct transcription of these pages to compare the output against. Verification therefore could not take the form "measure the error rate." It took three forms instead, each answering a different question.

**Component testing answered: does each stage do what it claims?** Every stage was developed against its own test scripts (the repository's `test_*.py` files) — small, targeted programs that run one stage on known inputs and check the outputs. A stage that passed its tests was then moved into the shared module `phase2lib.py` and, from that point on, only ever *imported* by other code, never copied or re-typed. The rule exists to prevent drift: a verified behavior that lives in one place stays verified, while a behavior that gets re-typed into several scripts can silently diverge in one of them.

**Corpus-scale checks answered: do the claimed properties hold everywhere, not just on the pages that were looked at?** Two examples. The reading-order rule (§4.9) was checked mechanically across every pair of adjacent blocks in the year's entire output — roughly 926,000 pairs — rather than on a sample. And the provenance distribution was computed across the whole corpus, then compared against individual pages inspected by hand, to confirm the corpus-wide numbers describe what actually appears on pages.

**Checking against the printed page answered: is the output actually right where it matters?** For the decisions with real consequences — above all, which engine's reading to ship for the numeric disagreements — samples of the disputed cases were checked by eye against the page image itself, the only ground truth that exists. This step earned its place: one such check reversed a conclusion that the pipeline's own measurements had suggested, which is the strongest available argument for not skipping it.

The rule that summarizes all three: any number that decides something gets checked by eye before it gets trusted.

## 7. Design-decision summary

| Decision | Choice | Governing rationale |
|---|---|---|
| Text authority | model primary | measured: higher fidelity on this material |
| Geometry authority | Tesseract wherever alignable | the only measured word positions in existence |
| Dedup | exact containment + hyphen-stub only | false merges delete content; residual duplicates are visible and cheap |
| Word→block assignment | center-point containment | a partition: every word exactly one home |
| Alignment unit | characters, case-blind, offsets preserved | survives fusion, splitting, and misreads that break word matching |
| `autojunk` | disabled | the default heuristic skips the common characters that anchor English text |
| Alignment guard | length-product cap | quadratic cost on garbage blocks buys nothing |
| Shrapnel rule | ≥2 claimants at >2× length → no inheritance | matching against garbage places good text at bad coordinates |
| Routing dictionary | system wordlist (US+UK), not the corpus lexicon | the corpus lexicon contains Tesseract's own errors |
| Undecided disagreements | index both readings (⇿) | the user's query resolves what the pipeline cannot |
| Alternatives restricted to alphabetic tokens | `safe_alt` | tokenizer-splittable content corrupts index offsets |
| Rescue gates | median conf 80 / 40, alnum majority | flagging junk is nearly free; discarding real text is a Burridge |
| Cluster thresholds | 1.5× / 2.0× local height | one rule serves agate and headline type alike |
| Seam dehyphenation | remove hyphen, dictionary-gated | better evidence than Phase 1 permits a stronger repair |
| Provenance | one class per word, sidecar file | the merge must be auditable after the fact |

## References

[1] dbmdz (Munich Digitization Centre, Bavarian State Library). *solr-ocrhighlighting*. https://github.com/dbmdz/solr-ocrhighlighting

[2] *Solr OCR Highlighting Plugin — Supported Formats.* MiniOCR specification, including the alternatives mechanism (U+21FF-joined readings indexed at one position). https://dbmdz.github.io/solr-ocrhighlighting/

[3] Lund, W.B., Ringger, E.K. "Improving Optical Character Recognition through Efficient Multiple System Alignment." *JCDL* 2009, 231–240. https://doi.org/10.1145/1555400.1555437

[4] Lopresti, D., Zhou, J. "Using Consensus Sequence Voting to Correct OCR Errors." *Computer Vision and Image Understanding* 67(1), 1997, 39–47.

[5] Fiscus, J.G. "A Post-Processing System to Yield Reduced Word Error Rates: Recognizer Output Voting Error Reduction (ROVER)." *IEEE ASRU* 1997.

[6] Lund, W.B., Walker, D.D., Ringger, E.K. "Progressive Alignment and Discriminative Error Correction for Multiple OCR Engines." *ICDAR* 2011.

[7] Wemhoener, D., Yalniz, I.Z., Manmatha, R. "Creating an Improved Version Using Noisy OCR from Multiple Editions." *ICDAR* 2013.

[8] Nguyen, T.T.H., Jatowt, A., Coustaty, M., Doucet, A. "Survey of Post-OCR Processing Approaches." *ACM Computing Surveys* 54(6), 2021.

[9] Ratcliff, J.W., Metzener, D.E. "Pattern Matching: The Gestalt Approach." *Dr. Dobb's Journal*, July 1988. (The algorithm implemented by Python's `difflib.SequenceMatcher`; see also the Python standard library documentation for the `autojunk` heuristic and its caveats.)

[10] *Word Geometry Generation in the Phase 1 PaddleOCR-VL → MiniOCR Converter.* This project's Phase 1 note (Phase 1 repository, `docs/`): the sanitizer, the estimated-geometry model this pipeline inherits for `interp` words, and the keep-the-hyphen rule this pipeline's dictionary-gated seam pass supersedes.

---

## Appendix A: `phase2lib.py` (complete source)

```python
#!/usr/bin/env python3
"""phase2lib — CANONICAL shared logic for the Phase 2 hybrid pipeline.
Process rule (state file, 2026-07-15): locked components get IMPORTED from
here, never re-typed. Consumers: synthesize.py, test scripts, smoke run."""
import csv, re, string, difflib

PUNCT = string.punctuation + '"\u201c\u201d\u2018\u2019\u2014\u2013'
ALT = '\u21ff'
ALIGN_GUARD = 4_000_000   # len(tstr)*len(vstr) above this: skip char alignment
                          # (quadratic difflib on garbage/table blocks; their
                          # alignments route to interp anyway — 0925uvic_17
                          # took minutes for nothing)

def norm(s):
    s = s.replace('\u2019', "'").replace('\u2018', "'")
    s = s.replace('\u201c', '"').replace('\u201d', '"')
    return s.strip(PUNCT).upper()

def core_l(s):
    return norm(s).lower()

def sanitize_content(text):
    """Phase 1 hard-won (paddle_to_miniocr.py): table HTML, em/en dashes,
    astral chars + U+FE0F (emoji incident)."""
    text = re.sub(r'</?(?:table|tr|td)[^>]*>', ' ', text or '')
    text = text.replace('\u2014', ' ').replace('\u2013', ' ')
    text = ''.join(c for c in text if ord(c) <= 0xFFFF and ord(c) != 0xFE0F)
    return text.strip()

def load_tess_words(tsv_path):
    """Tesseract TSV -> (page_w, page_h, words). csv.QUOTE_NONE is load-bearing
    (default quoting silently ate 1/3 of rows on 1925 quote-heavy text)."""
    tess_w = tess_h = None
    words = []
    with open(tsv_path) as f:
        r = csv.reader(f, delimiter='\t', quoting=csv.QUOTE_NONE)
        next(r)
        for row in r:
            if len(row) < 12:
                continue
            if row[0] == '1':
                tess_w, tess_h = int(row[8]), int(row[9])
            elif row[0] == '5' and row[11].strip():
                l, t, w, h = int(row[6]), int(row[7]), int(row[8]), int(row[9])
                words.append({'text': row[11], 'conf': float(row[10]),
                              'l': l, 't': t, 'w': w, 'h': h,
                              'cx': l + w/2, 'cy': t + h/2, 'claimed': False})
    assert tess_w and tess_h, f'no level-1 row in {tsv_path}'
    return tess_w, tess_h, words

def order_into_lines(tw):
    """Adaptive line clustering (0.6 x median word height per block).
    Fixed-quantum grouping scrambled body text — aligner v1 bug."""
    if not tw:
        return []
    hs = sorted(w['h'] for w in tw)
    med_h = hs[len(hs)//2]
    tw = sorted(tw, key=lambda w: w['cy'])
    lines, cur, ccy = [], [tw[0]], tw[0]['cy']
    for w in tw[1:]:
        if w['cy'] - ccy <= 0.6*med_h:
            cur.append(w); ccy = sum(x['cy'] for x in cur)/len(cur)
        else:
            lines.append(cur); cur = [w]; ccy = w['cy']
    lines.append(cur)
    out = []
    for ln in lines:
        out.extend(sorted(ln, key=lambda w: w['cx']))
    return out

def char_align(tstr, vstr):
    """Char-level map vlm-index -> tess-index, or None if the size guard
    fires (caller routes the block's words to interp)."""
    if not tstr:
        return None
    if len(tstr) * len(vstr) > ALIGN_GUARD:
        return None
    def _upper1(s):
        # length-preserving uppercase: keep chars whose upper() expands
        return ''.join(u if len(u := c.upper()) == 1 else c for c in s)
    sm = difflib.SequenceMatcher(None, _upper1(tstr), _upper1(vstr), autojunk=False)
    v2t = [None]*len(vstr)
    for a, b, n in sm.get_matching_blocks():
        for k in range(n):
            v2t[b+k] = a+k
    return v2t

def safe_alt(primary, alt):
    """True iff a ⇿ alternative is safe to emit: both sides single
    pure-alphabetic tokens (apostrophes allowed) after edge-strip, non-equal.
    Tokenizer-splittable content (digits, internal punct, currency) severs
    joiner-glued alternatives and crashes offset arithmetic at index time."""
    p = primary.strip(PUNCT)
    a = alt.strip(PUNCT)
    ok = lambda s: s and all(c.isalpha() or c == "'" for c in s)
    return ok(p) and ok(a) and p.upper() != a.upper()

def load_ext_dict():
    d = set()
    for p in ('/usr/share/dict/american-english', '/usr/share/dict/british-english'):
        with open(p, encoding='utf-8', errors='ignore') as f:
            for line in f:
                d.add(line.strip().lower())
    return d

# ---------- orphan clustering (LOCKED v3, from test_orphan_cluster3.py) ----------

def _joinable(a, b):
    ref = max(a['h'], b['h'], 15)
    vg = max(0, max(a['t'], b['t']) - min(a['t']+a['h'], b['t']+b['h']))
    hg = max(0, max(a['l'], b['l']) - min(a['l']+a['w'], b['l']+b['w']))
    return vg <= 1.5*ref and hg <= 2.0*ref

class _CBox:
    """Cluster with bbox prefilter (perf only; decisions unchanged)."""
    __slots__ = ('words', 'x0', 'y0', 'x1', 'y1', 'maxh')
    def __init__(self, w):
        self.words = [w]
        self.x0, self.y0 = w['l'], w['t']
        self.x1, self.y1 = w['l']+w['w'], w['t']+w['h']
        self.maxh = w['h']
    def add(self, w):
        self.words.append(w)
        self.x0 = min(self.x0, w['l']); self.y0 = min(self.y0, w['t'])
        self.x1 = max(self.x1, w['l']+w['w']); self.y1 = max(self.y1, w['t']+w['h'])
        self.maxh = max(self.maxh, w['h'])
    def absorb(self, o):
        self.words.extend(o.words)
        self.x0 = min(self.x0, o.x0); self.y0 = min(self.y0, o.y0)
        self.x1 = max(self.x1, o.x1); self.y1 = max(self.y1, o.y1)
        self.maxh = max(self.maxh, o.maxh)
    def near_word(self, w):
        ref = max(self.maxh, w['h'], 15)
        vg = max(0, max(self.y0, w['t']) - min(self.y1, w['t']+w['h']))
        hg = max(0, max(self.x0, w['l']) - min(self.x1, w['l']+w['w']))
        return vg <= 1.5*ref and hg <= 2.0*ref
    def near_cluster(self, o):
        ref = max(self.maxh, o.maxh, 15)
        vg = max(0, max(self.y0, o.y0) - min(self.y1, o.y1))
        hg = max(0, max(self.x0, o.x0) - min(self.x1, o.x1))
        return vg <= 1.5*ref and hg <= 2.0*ref

def cluster_orphans(orphans):
    """Adaptive 2D agglomeration + merge pass. v3, locked.
    bbox prefilter added (perf): bbox gap <= per-word gap for any member,
    and ref (taller height) <= max member height, so bbox-far implies all
    members test False. Prefilter skips only would-be-False pairs."""
    if not orphans:
        return []
    clusters = []
    for w in sorted(orphans, key=lambda x: (x['cy'], x['cx'])):
        for c in clusters:
            if c.near_word(w) and any(_joinable(w, m) for m in c.words):
                c.add(w); break
        else:
            clusters.append(_CBox(w))
    merged = True
    while merged:
        merged = False
        for i in range(len(clusters)):
            for k in range(i+1, len(clusters)):
                if clusters[i].near_cluster(clusters[k]) and any(
                        _joinable(a, b)
                        for a in clusters[i].words for b in clusters[k].words):
                    clusters[i].absorb(clusters[k]); del clusters[k]
                    merged = True; break
            if merged:
                break
    return [c.words for c in clusters]

def orphan_verdict(c):
    """('keep'|'flag'|'discard', median_conf). Gates 80/40 + no-alnum rule
    (risk asymmetry: flagging junk ~free, discarding real text = Burridge)."""
    confs = sorted(w['conf'] for w in c)
    med = confs[len(confs)//2]
    alnum = sum(1 for w in c if any(ch.isalnum() for ch in w['text']))
    if alnum <= len(c)/2:
        return 'discard', med
    if med >= 80:
        return 'keep', med
    if med >= 40:
        return 'flag', med
    return 'discard', med

def group_cluster_lines(c):
    """Split a kept cluster into display lines (0.75 x median height)."""
    hs = sorted(w['h'] for w in c)
    mh = max(hs[len(hs)//2], 15)
    c = sorted(c, key=lambda w: (round(w['cy']/mh), w['cx']))
    lines, cur, ccy = [], [c[0]], c[0]['cy']
    for w in c[1:]:
        if abs(w['cy'] - ccy) <= 0.75*mh:
            cur.append(w); ccy = sum(x['cy'] for x in cur)/len(cur)
        else:
            lines.append(cur); cur = [w]; ccy = w['cy']
    lines.append(cur)
    return lines


def _h_overlap(a, b):
    """Horizontal overlap as fraction of the narrower box. a,b = (x0,y0,x1,y1)."""
    ov = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    nar = max(1, min(a[2]-a[0], b[2]-b[0]))
    return ov / nar

def insertion_index(new_bbox, vlm_bboxes):
    """Index in vlm_bboxes AFTER which new_bbox belongs (0..len). A VLM block
    precedes the new block if: same column (h-overlap >= 0.3) and its TOP is
    above the new block's top, OR it lies in a column strictly left (its right
    edge <= new block's left edge + slack). Returns position after the LAST
    preceding block; 0 if none precede."""
    nx0, ny0, nx1, ny1 = new_bbox
    last = -1
    for i, bb in enumerate(vlm_bboxes):
        bx0, by0, bx1, by1 = bb
        same_col = _h_overlap(new_bbox, bb) >= 0.3
        if (same_col and by0 < ny0) or (bx1 <= nx0 + 10 and not same_col):
            last = i
    return last + 1
```

## Appendix B: `synthesize.py` (complete source)

```python
#!/usr/bin/env python3
"""Phase 2 SYNTHESIS (refactored). Usage: synthesize.py <issue> <page>
Driver over phase2lib (canonical locked components — import, never re-type).
dedup(v4-lite) -> regroup -> align(guarded) -> route(cascade) ->
tess-in-image -> orphan clusters(v3) -> hybrid MiniOCR + provenance sidecar.
Writes ONLY to ~/solr-bridge/phase2/out/. Reads Phase 1 data read-only."""
import json, os, sys, re
from xml.sax.saxutils import escape
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from phase2lib import (PUNCT, ALT, norm, core_l, sanitize_content, safe_alt,
                       load_tess_words, order_into_lines, char_align,
                       load_ext_dict, cluster_orphans, orphan_verdict,
                       group_cluster_lines, insertion_index)

issue, page = sys.argv[1], sys.argv[2]
TSV = os.path.expanduser(f'~/tess5-1925-full/{issue}/{issue}_{page}.tsv')
VLMF = os.path.expanduser(f'~/paddle-year/{issue}/{issue}_{page}_described.json')
OUTD = os.path.expanduser('~/solr-bridge/phase2/out')
os.makedirs(OUTD, exist_ok=True)

vlm = json.load(open(VLMF))
tess_w, tess_h, twords = load_tess_words(TSV)
sx, sy = vlm['width']/tess_w, vlm['height']/tess_h
S = 1/sx
DICT = load_ext_dict()

for _b in vlm['parsing_res_list']:
    _b['block_content'] = sanitize_content(_b.get('block_content', ''))

# ---------- dedup (v4-lite: exact containment + hyphen-stub) ----------
blocks = [b for b in vlm['parsing_res_list']
          if b['block_label'] not in ('image', 'footer_image')
          and b['block_content'].strip()]
def squash(s): return ' '.join(s.split()).upper()
def area(bb): return max(0, bb[2]-bb[0])*max(0, bb[3]-bb[1])
def inter(a, b):
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    return max(0, x1-x0)*max(0, y1-y0)
def hyphen_stub(sm, bg):
    s, g = squash(sm), squash(bg)
    m = re.search(r'([A-Z]+)-$', s)
    if not m: return False
    stub, pre = m.group(1), s[:m.start()].strip()
    if len(pre) < 12 or pre not in g: return False
    return g[g.index(pre)+len(pre):].lstrip().startswith(stub)
dropped = set()
for A in blocks:
    for B in blocks:
        if A is B or A['block_id'] in dropped or B['block_id'] in dropped: continue
        if len(A['block_content']) > len(B['block_content']): continue
        ov = inter(A['block_bbox'], B['block_bbox'])
        if ov == 0 or ov/max(area(A['block_bbox']), 1) < 0.5: continue
        s, g = squash(A['block_content']), squash(B['block_content'])
        if (s in g and len(s) >= 8) or hyphen_stub(A['block_content'], B['block_content']):
            dropped.add(A['block_id'])
blocks = [b for b in blocks if b['block_id'] not in dropped]

# ---------- per-block regroup + align + route ----------
out_blocks = []
prov_counts = {}
def bump(p): prov_counts[p] = prov_counts.get(p, 0) + 1

for blk in blocks:
    x0, y0, x1, y1 = blk['block_bbox']
    tw = [w for w in twords if x0 <= w['cx']*sx <= x1 and y0 <= w['cy']*sy <= y1]
    tw = order_into_lines(tw)
    for w in tw: w['claimed'] = True
    tchars, towner = [], []
    for i, w in enumerate(tw):
        if tchars: tchars.append(' '); towner.append(None)
        for c in w['text']: tchars.append(c); towner.append(i)
    tstr = ''.join(tchars)
    vstr = blk['block_content'].replace('\n', ' ')
    v2t = char_align(tstr, vstr)          # None if empty tess OR size guard
    lines_out = [ln.split() for ln in blk['block_content'].split('\n') if ln.strip()]

    # PASS 0 shrapnel rule (needs v2t)
    shrapnel_owners = set()
    if v2t:
        owner_claims = {}
        pos0 = 0
        for lw0 in lines_out:
            for vw0 in lw0:
                s0 = vstr.index(vw0, pos0); e0 = s0+len(vw0); pos0 = e0
                t0 = [v2t[k] for k in range(s0, e0) if v2t[k] is not None]
                ow0 = sorted({towner[k] for k in t0 if towner[k] is not None})
                if len(ow0) == 1:
                    owner_claims.setdefault(ow0[0], []).append(vw0)
        for o, claimants in owner_claims.items():
            if len(claimants) >= 2 and sum(len(v) for v in claimants) > 2*len(tw[o]['text']):
                shrapnel_owners.add(o)

    final_lines = []
    pos = 0
    for lw in lines_out:
        fl = []
        for vw in lw:
            s = vstr.index(vw, pos); e = s+len(vw); pos = e
            word = {'text': vw, 'alt': None}
            owners = []
            if v2t:
                tidx = [v2t[k] for k in range(s, e) if v2t[k] is not None]
                owners = sorted({towner[k] for k in tidx if towner[k] is not None})
            if len(owners) == 1 and owners[0] in shrapnel_owners:
                word['box'] = None; word['prov'] = 'interp-shrapnel'
                bump('interp-shrapnel'); fl.append(word); continue
            if len(owners) == 1:
                w = tw[owners[0]]
                inw = [k - sum(len(tw[j]['text'])+1 for j in range(owners[0]))
                       for k in tidx if towner[k] == owners[0]]
                n = len(w['text'])
                fx0, fx1 = min(inw)/n, (max(inw)+1)/n
                word['box'] = (w['l']+w['w']*fx0, w['t'], w['w']*(fx1-fx0), w['h'])
                if w['text'].upper() == vw.upper():
                    word['prov'] = 'agree'; bump('agree')
                elif norm(w['text']) == norm(vw):
                    word['prov'] = 'punct'; bump('punct')
                elif w['conf'] < 50 or (norm(w['text']) and norm(w['text']) in norm(vw)):
                    word['prov'] = 'vlm-routed'; bump('vlm-routed')
                elif core_l(vw) in DICT and core_l(w['text']) not in DICT:
                    word['prov'] = 'vlm-dict'; bump('vlm-dict')
                elif core_l(w['text']) in DICT and core_l(vw) not in DICT:
                    word['prov'] = 'tess-dict'; word['text'] = w['text']
                    word['alt'] = vw; bump('tess-dict')
                else:
                    word['prov'] = 'residual-alt'; word['alt'] = w['text']
                    bump('residual-alt')
            elif len(owners) > 1:
                ws = [tw[o] for o in owners]
                l = min(w['l'] for w in ws); t = min(w['t'] for w in ws)
                r_ = max(w['l']+w['w'] for w in ws); btm = max(w['t']+w['h'] for w in ws)
                word['box'] = (l, t, r_-l, btm-t)
                word['prov'] = 'multi'; bump('multi')
            else:
                word['box'] = None; word['prov'] = 'interp'; bump('interp')
            fl.append(word)
        final_lines.append(fl)
    bx0, bw_ = x0*S, (x1-x0)*S
    for fl in final_lines:
        known = [w for w in fl if w['box']]
        ln_t = min((w['box'][1] for w in known), default=y0*S)
        ln_h = max((w['box'][3] for w in known), default=(y1-y0)*S/max(len(final_lines), 1))
        total = sum(len(w['text']) for w in fl) + len(fl) - 1
        cx = bx0
        for w in fl:
            frac = len(w['text'])/max(total, 1)
            if not w['box']:
                w['box'] = (cx, ln_t, bw_*frac, ln_h)
            cx = w['box'][0] + w['box'][2] + bw_*(1/max(total, 1))
    out_blocks.append({'label': blk['block_label'], 'lines': final_lines})

rescued = []   # positioned via insertion_index before emit

# ---------- tess-in-image (own class, NOT orphans) ----------
img_blocks = [b for b in vlm['parsing_res_list']
              if b['block_label'] in ('image', 'footer_image')]
tess_in_image = []
for w in twords:
    if w['claimed']: continue
    cx, cy = w['cx']*sx, w['cy']*sy
    for b in img_blocks:
        bb = b['block_bbox']
        if bb[0] <= cx <= bb[2] and bb[1] <= cy <= bb[3]:
            w['claimed'] = True
            tess_in_image.append(w)
            break
if tess_in_image:
    keepers = [w for w in tess_in_image
               if any(ch.isalnum() for ch in w['text']) and w['conf'] >= 40]
    if keepers:
        fls = [[{'text': w['text'], 'box': (w['l'], w['t'], w['w'], w['h']),
                 'prov': 'tess-in-image', 'alt': None} for w in ln]
               for ln in group_cluster_lines(keepers)]
        for ln in fls:
            for _ in ln: bump('tess-in-image')
        _kw = keepers
        rescued.append({'label': 'tess-in-image', 'lines': fls,
                        'bbox_tess': (min(w['l'] for w in _kw), min(w['t'] for w in _kw),
                                      max(w['l']+w['w'] for w in _kw),
                                      max(w['t']+w['h'] for w in _kw))})

# ---------- orphan clusters (LOCKED v3 via lib) ----------
orph = [w for w in twords if not w['claimed']]
for c in cluster_orphans(orph):
    v, med = orphan_verdict(c)
    if v == 'discard': continue
    prov = 'tess-only' if v == 'keep' else 'tess-only-lowconf'
    fls = [[{'text': w['text'], 'box': (w['l'], w['t'], w['w'], w['h']),
             'prov': prov, 'alt': None} for w in ln]
           for ln in group_cluster_lines(c)]
    for ln in fls:
        for _ in ln: bump(prov)
    rescued.append({'label': 'tess-only', 'lines': fls,
                    'bbox_tess': (min(w['l'] for w in c), min(w['t'] for w in c),
                                  max(w['l']+w['w'] for w in c),
                                  max(w['t']+w['h'] for w in c))})

# ---------- position rescued blocks in VLM sequence ----------
# out_blocks currently holds only VLM-derived blocks, in VLM order.
# vlm_bboxes must be in the SAME coordinate space as the rescued bbox -> use
# tess space (convert VLM bboxes via S).
vlm_bboxes_tess = []
for blk in blocks:
    x0, y0, x1, y1 = blk['block_bbox']
    vlm_bboxes_tess.append((x0*S, y0*S, x1*S, y1*S))
# rescued blocks inserted far-first so earlier insertions don't shift later
# target indices computed against the pure-VLM list
placements = []
for rb in rescued:
    idx = insertion_index(rb['bbox_tess'], vlm_bboxes_tess)
    placements.append((idx, rb))
placements.sort(key=lambda t: t[0], reverse=True)
for idx, rb in placements:
    out_blocks.insert(idx, {'label': rb['label'], 'lines': rb['lines']})

# ---------- dehyph seam pass (cross-block + rescued-cluster line seams) ----------
import re as _re
def _try_join(w1, w2):
    m = _re.match(r'^([A-Za-z]+)-$', w1['text'])
    if not m: return False
    if not _re.match(r'^[a-z]+', w2['text']): return False
    joined = m.group(1) + _re.match(r'^([a-z]+)', w2['text']).group(1)
    if joined.lower() not in DICT: return False
    w1['text'] = m.group(1) + w2['text']   # keep w2's trailing punct
    return True

def _seam_join(prev_line, next_line):
    if prev_line and next_line and _try_join(prev_line[-1], next_line[0]):
        next_line.pop(0)
        return True
    return False

joins = 0
for bi, ob in enumerate(out_blocks):
    # (b) within rescued blocks: consecutive line seams
    if ob['label'] in ('tess-only', 'tess-in-image'):
        li = 0
        while li < len(ob['lines']) - 1:
            if _seam_join(ob['lines'][li], ob['lines'][li+1]):
                joins += 1
                if not ob['lines'][li+1]:
                    del ob['lines'][li+1]
                    continue
            li += 1
    # (a) block seam to next block
    if bi + 1 < len(out_blocks):
        nb = out_blocks[bi+1]
        if ob['lines'] and nb['lines'] and _seam_join(ob['lines'][-1], nb['lines'][0]):
            joins += 1
            if not nb['lines'][0]:
                del nb['lines'][0]
out_blocks = [ob for ob in out_blocks if any(ob['lines'])]
if joins:
    print(f'(dehyph seam pass: {joins} joins)')

# ---------- emit ----------
mini = [f'<p xml:id="{issue}_{page}" wh="{tess_w} {tess_h}">']
sidecar = []
for ob in out_blocks:
    mini.append('<b>')
    for ln in ob['lines']:
        parts = []
        for w in ln:
            x, y, ww, hh = (int(round(v)) for v in w['box'])
            txt = escape(w['text'])
            if w['alt'] and safe_alt(w['text'], w['alt']):
                txt = f'{txt}{ALT}{escape(w["alt"].strip(PUNCT))}'
            parts.append(f'<w x="{x} {y} {ww} {hh}">{txt}</w>')
            sidecar.append({'t': w['text'], 'prov': w['prov']})
        mini.append('<l>' + ' '.join(parts) + '</l>')
    mini.append('</b>')
mini.append('</p>')

open(f'{OUTD}/{issue}_{page}.miniocr.xml', 'w').write('\n'.join(mini))
json.dump(sidecar, open(f'{OUTD}/{issue}_{page}.provenance.json', 'w'))

total = sum(prov_counts.values())
print(f'{issue}_{page}: {len(out_blocks)} blocks ({len(dropped)} deduped), {total} words')
for k in sorted(prov_counts, key=lambda k: -prov_counts[k]):
    print(f'  {k:18s} {prov_counts[k]:5d} ({100*prov_counts[k]/total:.1f}%)')
```
