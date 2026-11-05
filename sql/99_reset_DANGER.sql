-- DESTRUCTIVE: deletes every SENTINEL table and its data so a class can start over.
-- Storage files are NOT removed here; use `python ingest.py reset --yes --storage`
-- or delete them from the Storage page.
DROP VIEW IF EXISTS public.model_features;
DROP TABLE IF EXISTS public.preference_pairs, public.gold_explanations, public.documents,
  public.legacy_cases, public.features, public.labels, public.payment_outcomes,
  public.transactions, public.devices, public.merchants, public.customers,
  public.threshold_sets, public.hard_rules, public.list_entries CASCADE;
NOTIFY pgrst, 'reload schema';
