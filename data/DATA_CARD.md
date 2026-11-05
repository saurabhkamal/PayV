# SENTINEL synthetic dataset card

This dataset exercises the PayVista SENTINEL pipeline using fictional events and documents. It does not establish model accuracy, regulatory compliance, production throughput or investigator quality.

## Scope

The configured main transaction count is 100,000. Additional warmup events (10,000) cover October through December 2024. The main interval is January 2025 through February 2026. A separate legacy case archive supplies 2021 to 2024 narratives. All currency is INR; integer paise is authoritative. Timestamps are stored in UTC and interpreted in IST for calendar splits and night features. Authorisation histories include failed attempts; they are not a settlement ledger.

## Training boundaries

The benchmark is retrospective: train January to October 2025, validate November to December 2025, holdout January to February 2026. Labels mature after 60 days and the dataset snapshot is May 1, 2026. For a strict historical deployment simulation, filter `eligible_at_next_split_start=true` when fitting or calibrating. This removes late training/validation events whose labels were unavailable at the next split's start. A two-month validation window with a 60-day delay leaves very few prospectively mature validation examples; extend the calibration history for a real backtest. Do not mistake the retrospective split for a no-delay production experiment.

Every MCC encoding fold uses only earlier training labels already mature before that month's boundary. Validation and holdout use the November 1 frozen encoder. No validation or holdout labels fit that encoder. CPT excludes validation, holdout, late-published training notes and exact duplicate text. Histories are read before applying the current event. Outcomes are applied only once their timestamps are reached. Warmup events are not SFT targets.

## Prose and targets

Investigator and dispute notes are templated fiction. Regulatory exercises are RBI/NPCI-themed teaching scenarios, with source discovery URLs, and are not authentic circulars or summaries of individual official rules. RBA means risk based approach in the additional guide. Replace these exercises with verified licensed official text before real domain adaptation. Gold and DPO files are synthetic candidates with no human reviewer approval. The 500-case default holdout explanation pack remains evaluation-only.

All probabilities, decision latency and decisions in decision_audit are simulated. The model_version explicitly says SYNTHETIC-HEURISTIC-NOT-A-MODEL. This score is not calibrated and is never used as the fraud label. Fraud labels are sampled with noisy behavioural overlap at the requested prevalence. Scenario IDs live only in ground_truth, not in model inputs. Do not use predicted decisions, later verdicts, label availability flags, IDs or source documents as predictive features.

## Limits

One million events spread over 14 months intentionally do not reproduce PayVista's daily production volume. Uniform teaching variants do not recreate the original corpus diversity or 135 million tokens. Exact text duplicates are excluded from CPT; normalized template fingerprints are reported, but semantic near-deduplication is not certified. Token totals are estimates unless a local tokenizer is supplied. Run with --tokenizer /path/to/tokenizer.json to measure all prompts and enforce 1,024 tokens by removing oldest history entries as needed. Full 20-event histories remain separately available. PII scans check a deterministic document sample with limited patterns; they are not the client's human redaction acceptance audit.

No embeddings, teacher logits, trained weights, calibrated scores or production acceptance metrics are fabricated. document_chunks supports text search and later local embedding generation. Supabase implements this synthetic teaching environment; it does not recreate AWS residency, private networking or immutable Object Lock requirements.

## Label mode: learnable (classroom option)

Generated with --label-mode learnable. Fraud labels are concentrated on each campaign's final cash-out event and on events with more observable risk signals (new device, night hour, unusual city, shared ring device), with a random component retained. This makes models measurably learnable for teaching; it is a stronger assumption than the default noisy mode and is not evidence about real-world fraud separability.
