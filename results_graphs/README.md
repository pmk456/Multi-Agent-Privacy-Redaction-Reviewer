# Results graphs

Every chart here is generated from `reports/*.json` by `backend/scripts/make_result_graphs.py`.
Each PNG has a CSV with the exact numbers behind it. Rebuild after any new evaluation run:

```bash
python backend/scripts/make_result_graphs.py
```

| Chart | What it shows |
| --- | --- |
| [00_dashboard.png](00_dashboard.png) ([data](00_dashboard.csv)) | **PS 247 at a glance: protected, verified, and honest about its limits.** Headline results from every evaluation run. |
| [01_detection_coverage.png](01_detection_coverage.png) ([data](01_detection_coverage.csv)) | **Agent 1 catches 92% of identifiers in-domain, 78% on an independent benchmark.** Coverage = gold identifier overlapped by any detection, raw text, ground truth hidden. Blue = held-out sets. |
| [02_detection_f1.png](02_detection_f1.png) ([data](02_detection_f1.csv)) | **Exact-label accuracy drops on unfamiliar data: strict F1 0.67 in-domain, 0.48 on PIIMB.** Micro-averaged F1. Strict needs exact span and type; relaxed accepts overlapping spans of the same type. |
| [03_coverage_by_entity_type.png](03_coverage_by_entity_type.png) ([data](03_coverage_by_entity_type.csv)) | **Contacts and IDs are near-perfect; occupations and demographics are the weak spots.** Share of gold identifiers caught, per category (sorted by how often it occurs). A missing bar = the category does not occur in that set. |
| [04_piimb_by_source.png](04_piimb_by_source.png) ([data](04_piimb_by_source.csv)) | **Structured SQL/JSON payloads are the hardest source: 54% caught.** PIIMB coverage per source, 100 examples each. |
| [05_annotation_validation.png](05_annotation_validation.png) ([data](05_annotation_validation.csv)) | **Corrupted annotations are caught: 100% of out-of-bounds, 88-100% of wrong types and shifted spans.** 30% of supplied annotations deliberately corrupted; rightmost pair is the false-alarm rate on correct annotations (lower is better). |
| [06_annotated_input_coverage.png](06_annotated_input_coverage.png) ([data](06_annotated_input_coverage.csv)) | **With annotations supplied, 96-98% of identifiers end up fully covered.** Gold spans fully inside a final entity after Agent 1 validates corrupted annotations. |
| [07_redaction_completeness.png](07_redaction_completeness.png) ([data](07_redaction_completeness.csv)) | **The full pipeline protects 92.8% of never-keep identifiers in-domain, 87.5% on PIIMB.** Protected = original text no longer appears in released output (a blocked document releases nothing). |
| [08_leak_causes.png](08_leak_causes.png) ([data](08_leak_causes.csv)) | **Most in-domain leaks are deliberate policy keeps; on PIIMB most are genuine detection misses.** Why each still-visible gold span survived. |
| [09_piimb_leak_rate_by_type.png](09_piimb_leak_rate_by_type.png) ([data](09_piimb_leak_rate_by_type.csv)) | **On PIIMB, occupations and dates leak most; emails and government IDs almost never.** Share of each category's gold spans still visible after the full pipeline (includes deliberate policy keeps). |
| [10_verification_fault_detection.png](10_verification_fault_detection.png) ([data](10_verification_fault_detection.csv)) | **Agent 4 caught all 361 injected faults, with 0% false alarms on 100 clean runs.** One fault injected per run on ai4privacy validation texts. Caveat: same detector family as Agent 1. |
| [11_agent5_confusion.png](11_agent5_confusion.png) ([data](11_agent5_confusion.csv)) | **Agent 5 flagged 4 of 4 re-identifiable people and 0 of 5 controls.** Synthetic cross-document set (28 documents, 40-person hidden registry). Green = correct. |
| [12_agent2_strategy_agreement.png](12_agent2_strategy_agreement.png) ([data](12_agent2_strategy_agreement.csv)) | **Agent 2 matches the expected redaction strategy for 88% of mentions.** Synthetic set, by category (mention count in brackets). Orange = below 85% agreement. |
| [13_claude_effect.png](13_claude_effect.png) ([data](13_claude_effect.csv)) | **Claude raises protection from 78% to 90%, at some cost in readability.** 30 validation documents; 66 Haiku calls, about $0.00859; 1.0 s vs 112.1 s. |
| [14_release_and_utility.png](14_release_and_utility.png) ([data](14_release_and_utility.csv)) | **Nearly every document is released, keeping about 80% of its text readable.** Readable = unchanged text 1.0, generalised text 0.5, blocked document 0. |
| [15_knowledge_base.png](15_knowledge_base.png) ([data](15_knowledge_base.csv)) | **The privacy knowledge base is complete and consistent.** Deterministic checks of policies.json against an independent, hand-written expected-results file. |
| [16_dataset_composition.png](16_dataset_composition.png) ([data](16_dataset_composition.csv)) | **Names and record or account numbers dominate both evaluation sets.** Gold spans per category after label mapping. ai4privacy 400 examples, PIIMB 300. |
