-- =============================================================================
-- Project SENTINEL - classroom schema for Supabase
-- Run once: Supabase dashboard -> SQL Editor -> New query -> paste -> Run.
-- (Or set DATABASE_URL in .env and run: python ingest.py create)
--
-- Tables live in the `public` schema so the Supabase REST API (PostgREST) can
-- reach them with the publishable key. CLASSROOM ONLY: the policies below let the
-- publishable key INSERT rows. After loading, run 02_lockdown.sql to make the
-- data read-only.
-- =============================================================================

-- ---------- 1. Reference tables ---------------------------------------------
CREATE TABLE IF NOT EXISTS public.customers (
  customer_id   text PRIMARY KEY,
  created_at    timestamptz NOT NULL,
  customer_age  integer NOT NULL,
  home_city     text NOT NULL,
  region        text NOT NULL,
  is_synthetic  boolean NOT NULL
);

CREATE TABLE IF NOT EXISTS public.merchants (
  merchant_id       text PRIMARY KEY,
  synthetic_name    text NOT NULL,
  merchant_category text NOT NULL,
  merchant_location jsonb NOT NULL,
  is_synthetic      boolean NOT NULL
);

CREATE TABLE IF NOT EXISTS public.devices (
  device_id    text PRIMARY KEY,
  device_kind  text NOT NULL,
  is_synthetic boolean NOT NULL
);

-- ---------- 2. Transactions and what happened to them -------------------------
-- The 14 CRD fields (section 7.1) minus fraud_label, which lives in `labels`
-- so that raw transactions never carry the answer.
CREATE TABLE IF NOT EXISTS public.transactions (
  transaction_id            text PRIMARY KEY,
  customer_id               text NOT NULL REFERENCES public.customers (customer_id),
  merchant_id               text NOT NULL REFERENCES public.merchants (merchant_id),
  device_id                 text REFERENCES public.devices (device_id),
  amount_paise              bigint NOT NULL CHECK (amount_paise > 0),
  transaction_amount        numeric(14,2) NOT NULL,
  payment_channel           text NOT NULL,
  merchant_category         text NOT NULL,
  transaction_time          timestamptz NOT NULL,
  customer_age              integer NOT NULL CHECK (customer_age BETWEEN 18 AND 120),
  customer_location         jsonb,
  merchant_location         jsonb NOT NULL,
  account_age               integer NOT NULL CHECK (account_age >= 0),
  previous_transactions     integer NOT NULL,
  average_transaction_value numeric(14,2),
  failed_transactions       integer NOT NULL,
  split                     text NOT NULL CHECK (split IN ('warmup','train','validation','holdout')),
  is_synthetic              boolean NOT NULL,
  CHECK (amount_paise = transaction_amount * 100)
);

CREATE TABLE IF NOT EXISTS public.payment_outcomes (
  transaction_id text PRIMARY KEY REFERENCES public.transactions (transaction_id),
  outcome_time   timestamptz NOT NULL,
  status         text NOT NULL,
  failure_code   text,
  is_synthetic   boolean NOT NULL
);

CREATE TABLE IF NOT EXISTS public.labels (
  transaction_id               text PRIMARY KEY REFERENCES public.transactions (transaction_id),
  fraud_label                  smallint NOT NULL CHECK (fraud_label IN (0,1)),
  label_source                 text NOT NULL,
  label_available_at           timestamptz NOT NULL,
  split                        text NOT NULL,
  eligible_at_next_split_start boolean NOT NULL,
  is_synthetic                 boolean NOT NULL
);

-- FE-01 .. FE-10 from the CRD, computed only from data available before the transaction.
CREATE TABLE IF NOT EXISTS public.features (
  transaction_id                    text PRIMARY KEY REFERENCES public.transactions (transaction_id),
  feature_as_of                     timestamptz NOT NULL,
  amount_to_avg_ratio               double precision,
  is_new_device                     boolean,
  customer_merchant_distance_km     double precision,
  is_new_city                       boolean,
  hour_of_day                       integer NOT NULL,
  is_night                          boolean NOT NULL,
  has_recent_failures               boolean NOT NULL,
  is_new_account                    boolean NOT NULL,
  txn_count_last_1h                 integer NOT NULL,
  txn_amount_last_24h_paise         bigint NOT NULL,
  distinct_customers_per_device_7d  integer,
  combined_risk_flags               integer NOT NULL,
  mcc_target_encoded_rate           double precision NOT NULL,
  mcc_encoding_as_of                timestamptz NOT NULL,
  mcc_encoding_count                integer NOT NULL,
  missing_customer_location         boolean NOT NULL,
  missing_device                    boolean NOT NULL,
  cold_start                        boolean NOT NULL,
  reason_codes                      jsonb NOT NULL,
  feature_version                   text NOT NULL
);

-- ---------- 3. Text corpus and LLM training targets ---------------------------
CREATE TABLE IF NOT EXISTS public.legacy_cases (
  legacy_case_id   text PRIMARY KEY,
  customer_id      text NOT NULL REFERENCES public.customers (customer_id),
  transaction_time timestamptz NOT NULL,
  closed_at        timestamptz NOT NULL,
  amount_paise     bigint NOT NULL,
  payment_channel  text NOT NULL,
  fraud_label      smallint NOT NULL,
  evidence         jsonb NOT NULL,
  is_synthetic     boolean NOT NULL
);

CREATE TABLE IF NOT EXISTS public.documents (
  document_id      text PRIMARY KEY,
  kind             text NOT NULL,
  title            text NOT NULL,
  transaction_id   text REFERENCES public.transactions (transaction_id),
  legacy_case_id   text REFERENCES public.legacy_cases (legacy_case_id),
  split            text NOT NULL,
  published_at     timestamptz NOT NULL,
  content          text NOT NULL,
  content_sha256   text NOT NULL,
  template_family  text NOT NULL,
  cpt_eligible     boolean NOT NULL,
  review_status    text NOT NULL,
  storage_path     text NOT NULL,
  record_in_shard  integer NOT NULL,
  metadata         jsonb NOT NULL,
  is_synthetic     boolean NOT NULL
);

CREATE TABLE IF NOT EXISTS public.gold_explanations (
  example_id     text PRIMARY KEY,
  transaction_id text NOT NULL REFERENCES public.transactions (transaction_id),
  split          text NOT NULL,
  prompt         text NOT NULL,
  target         jsonb NOT NULL,
  fraud_label    smallint NOT NULL,
  review_status  text NOT NULL,
  is_synthetic   boolean NOT NULL
);

CREATE TABLE IF NOT EXISTS public.preference_pairs (
  pair_id          text PRIMARY KEY,
  transaction_id   text NOT NULL REFERENCES public.transactions (transaction_id),
  split            text NOT NULL,
  prompt           text NOT NULL,
  chosen           jsonb NOT NULL,
  rejected         jsonb NOT NULL,
  rejection_reason text NOT NULL,
  review_status    text NOT NULL,
  is_synthetic     boolean NOT NULL
);

-- ---------- 4. Rules-engine configuration (CRD section 10) --------------------
CREATE TABLE IF NOT EXISTS public.threshold_sets (
  threshold_id  text PRIMARY KEY,
  version       integer NOT NULL,
  mcc_group     text,
  medium_from   numeric(4,3) NOT NULL,
  high_from     numeric(4,3) NOT NULL,
  critical_from numeric(4,3) NOT NULL,
  status        text NOT NULL,
  is_synthetic  boolean NOT NULL
);

CREATE TABLE IF NOT EXISTS public.hard_rules (
  rule_id      text PRIMARY KEY,
  code         text NOT NULL,
  expression   jsonb NOT NULL,
  action       text NOT NULL,
  priority     integer NOT NULL,
  enabled      boolean NOT NULL,
  is_synthetic boolean NOT NULL
);

CREATE TABLE IF NOT EXISTS public.list_entries (
  entry_id       text PRIMARY KEY,
  list_type      text NOT NULL,
  entity_id      text NOT NULL,
  effective_from timestamptz NOT NULL,
  reason         text NOT NULL,
  is_synthetic   boolean NOT NULL
);

-- ---------- 5. Indexes for the API's common filters ---------------------------
CREATE INDEX IF NOT EXISTS transactions_split_idx         ON public.transactions (split, transaction_id);
CREATE INDEX IF NOT EXISTS transactions_customer_time_idx ON public.transactions (customer_id, transaction_time);
CREATE INDEX IF NOT EXISTS labels_split_idx               ON public.labels (split, fraud_label);
CREATE INDEX IF NOT EXISTS documents_kind_split_idx       ON public.documents (kind, split);
CREATE INDEX IF NOT EXISTS gold_split_idx                 ON public.gold_explanations (split);

-- ---------- 6. One flat, model-ready view (raw fields + features + label) -----
-- security_invoker makes the view obey the caller's RLS policies.
CREATE OR REPLACE VIEW public.model_features WITH (security_invoker = true) AS
SELECT t.transaction_id, t.split, t.transaction_time, t.customer_id, t.device_id,
       t.transaction_amount, t.payment_channel, t.merchant_category,
       t.customer_age, c.region, t.account_age, t.previous_transactions,
       t.average_transaction_value, t.failed_transactions,
       f.amount_to_avg_ratio, f.is_new_device, f.customer_merchant_distance_km,
       f.is_new_city, f.hour_of_day, f.is_night, f.has_recent_failures,
       f.is_new_account, f.txn_count_last_1h, f.txn_amount_last_24h_paise,
       f.distinct_customers_per_device_7d, f.combined_risk_flags,
       f.mcc_target_encoded_rate, f.missing_customer_location, f.missing_device,
       f.cold_start, f.reason_codes,
       l.fraud_label, l.label_available_at
FROM public.transactions t
JOIN public.features  f USING (transaction_id)
JOIN public.labels    l USING (transaction_id)
JOIN public.customers c USING (customer_id);

-- ---------- 7. Row Level Security: read for everyone, insert for loading ------
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['customers','merchants','devices','transactions',
    'payment_outcomes','labels','features','legacy_cases','documents',
    'gold_explanations','preference_pairs','threshold_sets','hard_rules','list_entries']
  LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS classroom_read ON public.%I', t);
    EXECUTE format('CREATE POLICY classroom_read ON public.%I FOR SELECT TO anon, authenticated USING (true)', t);
    EXECUTE format('DROP POLICY IF EXISTS classroom_load ON public.%I', t);
    EXECUTE format('CREATE POLICY classroom_load ON public.%I FOR INSERT TO anon, authenticated WITH CHECK (true)', t);
    EXECUTE format('GRANT SELECT, INSERT ON public.%I TO anon, authenticated', t);
  END LOOP;
END $$;
GRANT SELECT ON public.model_features TO anon, authenticated;

-- ---------- 8. Private Storage bucket for training files ----------------------
INSERT INTO storage.buckets (id, name, public, file_size_limit)
VALUES ('sentinel-data', 'sentinel-data', false, 52428800)
ON CONFLICT (id) DO NOTHING;

DROP POLICY IF EXISTS sentinel_data_read ON storage.objects;
CREATE POLICY sentinel_data_read ON storage.objects
  FOR SELECT TO anon, authenticated USING (bucket_id = 'sentinel-data');
DROP POLICY IF EXISTS sentinel_data_load ON storage.objects;
CREATE POLICY sentinel_data_load ON storage.objects
  FOR INSERT TO anon, authenticated WITH CHECK (bucket_id = 'sentinel-data');

-- Tell the REST API about the new tables straight away.
NOTIFY pgrst, 'reload schema';
