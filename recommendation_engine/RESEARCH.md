# Offline challenger research

This environment is separate from Mariana's Python 3.12 runtime. RecBole 1.2.1
requires `ray<=2.6.3`, for which no Python 3.12 wheel is published. Run the
RecBole/Implicit temporal baselines in an isolated Python 3.10 or 3.11 virtual
environment created from `requirements-research.in`; never install them into
Mariana's core environment.

Candidate models are BPR, ALS, LightGCN, and SASRec. Export only aggregate
metrics and a model artifact. `recommendation_engine.research.should_promote`
accepts a challenger only when NDCG@10 improves by at least 2% and diversity
regresses by no more than 5%. The current champion remains available for
rollback in SQLite and on disk.
