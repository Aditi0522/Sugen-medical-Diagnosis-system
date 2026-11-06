# ICD-11 consult-note coder

Maps a clinical consult note (typed, short, or ambient transcript; any language) to up to 3 ICD-11 MMS codes.

## Setup

Create a `.env` file in the project root:

```bash
cp .env.example .env
```

Add your API credentials and configuration to `.env`. The LLM providers are optional; without valid API credentials, the system uses its retrieval-only fallback.

Then run:

```bash
docker compose run coder /in/notes.jsonl /out/predictions.jsonl

```
## Approach
1. **Reader (LLM):** reads the note and writes the concluded diagnoses as English terms (ruled-out and past conditions ignored).
2. **Retrieval:** BM25 over the 15,912 leaf codes (title plus WHO synonyms, inclusions and short definition), several queries fused, then the siblings of the best hits added (`.Z` and `.Y` included), grouped by parent.
3. **Selection (LLM):** picks the best 3 from that candidate list only. Every code is checked against `mms-2026-01.json`, and the list is padded from retrieval order.
4. **Safety:** a no-key retrieval-only answer is written for every note first, then replaced atomically as LLM answers arrive, so the output is always complete. LLM work stops starting at 45 minutes. Rate limits wait and retry. Credit or key errors switch the provider off and the notes keep their fallback answers.

## Scores
- **Dev (`score.py`):** **72.5 / 75** (top-1 0.950, top-3 1.000), measured with Qwen3.8-27B on Groq as a stand-in, because my OpenAI and Anthropic keys had no credit.No-key path: 35.0 / 75.
- **Hidden estimate: about 70 / 100 (plausible range 55-80).** This is a judgement, not a measurement: roughly 60/75 on the core slice (dev is optimistic because I tuned on it and a stand-in model was used) and about 10/25 on the generalisation slice (non-English text and unseen chapters were not measured).

## Data added
WHO ICD-11 entity data (synonyms, index terms, inclusions, short definitions) fetched from the WHO ICD API with `tools/fetch_who.py` and stored as `data/kb.jsonl`. Source: WHO ICD API (icd.who.int). Used only to improve retrieval. [Licence: confirm the WHO ICD-11 terms before submitting.]

## Evaluation beyond the 60 dev notes
- **Stage metrics** (`tools/stage_metrics.py`): the gold code is in the 60-candidate pool for 100% of dev notes (recall@20 0.967, @40 0.983), so remaining errors are selection errors, not retrieval.
- **Error taxonomy and per-style scores** (`tools/errors.py`): most dev errors were over-specific picks (a specific child chosen when the note doesn't give the detail).
- **Ablations:** no-key 23.3 to 35.0 from note parsing; two prompt versions compared on the same model (70.8 vs 72.5, within noise).
- **Not done:** translated / style-swapped / synthetic-chapter sets and a locked holdout. dev is therefore treated as an optimistic number.

## Where AI tooling was wrong
I was using Claude as my AI assistant throughout this project there I encountered memory hallucination problems a lot of time, the context retention capacity of Sonnet 5.5 may be good but most often it just grazes the text without understanding it. You have to be very precise in ur prompt. The agent also overassumed undocumented stuff which we further accounted for in our pipeline too.Although it was quite accurate in code help, it was further cemented by tests and scores, the initial deep dive into various research papers on the same topic helped build context and direction.


Hours spent: [20+]
