## D-01 2026-11-05 15:42 IST
Commit: 5f4547c
Decision: Since this is a clinical NLP + information retrieveal + classification system, I am moving ahead with "Retrieve and re rank with an LLM system with diagnostic extraction step".
Options: I have worked in similar area matching (resume and job description) and I found TF-IDF and cosine similarity to be relevant but not that good, so I first and foremost looked for other research papers and read them using claude's help in this area. Fine tuning a classfier from scratch would be too time taking and compute heavy so I am avoiding that right now, I came across LLM tree search which was interest but it surely is expensive.
Evidence: The initial token overlap baseline achieved 15/75 score which proves simple lexical matching is obviously not sufficient, The available dataset has only 60 notes and ICD-MMS catalogue has 18,375 categories, hence training a classifier from scratch is impractical, also we have a budgest of $6 so unrestricted LLM inferencing or large fine tuned model is also not suitable.
Revisit: After building the basic system and getting the score, I will definitely want to look for further optimization in the system.

## D-02 2026-11-06 2:25 IST
Commit: 7de01c3
Decision:Build the knowledge base from the MMS file as 15,912 codable leaf categories only. The 2,463 non-leaf headings are kept as structure (parent, sibling and block lookups)
Options:
Evidence: all 61 gold codes in the dev set are leaves, so we are focusing on that and it has proved to be quite good on a 15 note slice with 70/75 score (top-1 and top-3 both 0.933).
Revisit: If the hidden set contains codes that are not leaves, offer the parent headings as candidates.

## D-03 2026-11-06 15:16 IST
Commit: <auto>
Decision: I opted for using free tier OpenAI compatible provider (Groq, Qwen) in development, this seems to be optimal right now.
Options: Openai and anthropic but my account wasn't credited for me to be able to utilize api key
Evidence: Multiple LLM out of credit test runs.
Revisit: If I test this system on a 600 note run myself, then maybe I will use multiple groq keys and do roundrobin btw them or buy paid tier if absolutely necessary.

## D-04 2026-11-06 16:15 IST
Commit: <auto>
Decisions: Built a condensed fallback retrieval [without api key/llm] scored 23/75 + analyze(llm) [reads clinical note and extracts 1-3 diagnostic terms], Then 60 icd candidates are extracted in Retrieval using bm25 + sibling expansion, before we re rank using LLM.
Options: (a) Pure BM25 retrieval; (b) use LLM to generate codes directly; (c) use LLM for analysis and reranking, with BM25 for retrieval.
Evidence: Fallback scored 23/75. First full run scored 65.4/75.
Revisit: If API is unavailable, fallback still works. Explore improving retrieval without increasing API dependency.

## D-05 2026-11-06 16:15 IST
Commit: <auto>
Decisions: I analyzed the errors in outcome that scored 65.4 and there were some errors I encountered, firstly icd database has Hypoglycaemia term but dev note has different spelling (american english) which categorizes two words as diff vectors, hence I added a function for normalization.
Options: need to explore more.
Evidence: dev-044 gold code moved from rank 82 to rank 3 after the change. Candidate pool recall reached 100% on 60 dev notes. No established improvement in final score.
Revisit: if this seems to be a hotfix in later runs, then maybe I need to change this another matching algo.

## D-06 2026-11-06 16:15 IST
Commit: <auto>
Decisions:Added errors.py and stage_metrics.py to inspect per-note errors and identify whether the issue is in Retrieval or RERANK.
Options:
Evidence: First full run scored 65.4/75. Errors included different conditions, wrong ordering and incorrect specificity. Performance was also lower on ambient transcripts than typed and short notes.

latest error report

=== error kinds (top-1 misses) ===
  3  different condition entirely (extraction/retrieval)
  3  right code in top-3 but not first (ordering)
  1  same 3-char block, different condition

=== by style (n, top1, top3) ===
typed_consult      n=29 top1=0.93 top3=0.97
short_consult      n=16 top1=0.81 top3=0.88
ambient_transcript n=15 top1=0.87 top3=0.93

Revisit: Test on translated and style-swapped notes to check generalisation.

## D-06 2026-11-06 16:15 IST
Commit: <auto>
Decision: Added specificity instructions in RERANK. Choose a specific child only if the note mentions the distinguishing detail; otherwise prefer .Z. Use .Y only when another specified type is mentioned.
Options:
Evidence: In the error results, I noticed that many misses were because the model picked a more specific code using undocumented info when the gold code was (.z), forcing .z specifically is not a solution because most notes require specific solution.
Revisit: will do a comparison on another set of notes and maybe check if prompt needs further verification

