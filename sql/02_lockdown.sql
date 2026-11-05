-- Run AFTER ingestion has finished. Removes the classroom INSERT permission so
-- the publishable key becomes read-only (tables and Storage).
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['customers','merchants','devices','transactions',
    'payment_outcomes','labels','features','legacy_cases','documents',
    'gold_explanations','preference_pairs','threshold_sets','hard_rules','list_entries']
  LOOP
    EXECUTE format('DROP POLICY IF EXISTS classroom_load ON public.%I', t);
    EXECUTE format('REVOKE INSERT, UPDATE, DELETE ON public.%I FROM anon, authenticated', t);
  END LOOP;
END $$;

DROP POLICY IF EXISTS sentinel_data_load ON storage.objects;
NOTIFY pgrst, 'reload schema';
