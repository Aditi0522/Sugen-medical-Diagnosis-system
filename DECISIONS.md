
## 2026-11-05 15:42 IST
Commit: <auto>
Decision: Since this is a clinical NLP + information retrieveal + classification system, I am moving ahead with "Retrieve and re rank with an LLM system with diagnostic extraction step".
Options: I have worked in similar area matching (resume and job description) and I found TF-IDF and cosine similarity to be relevant but not that good, so I first and foremost looked for other research papers and read them using claude's help in this area. Fine tuning a classfier from scratch would be too time taking and compute heavy so I am avoiding that right now, I came across LLM tree search which was interest but it surely is expensive.
Evidence: The initial token overlap baseline achieved 15/75 score which proves simple lexical matching is obviously not sufficient, The available dataset has only 60 notes and ICD-MMS catalogue has 18,375 categories, hence training a classifier from scratch is impractical, also we have a budgest of $6 so unrestricted LLM inferencing or large fine tuned model is also not suitable.
Revisit: After building the basic system and getting the score, I will definitely want to look for further optimization in the system.
