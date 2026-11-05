-- Data-quality checks to discuss in class. Every `violations` value must be 0.
SELECT 'money_mismatch' AS check_name, count(*) AS violations
  FROM public.transactions WHERE amount_paise <> transaction_amount * 100
UNION ALL SELECT 'label_delay_not_60_days', count(*)
  FROM public.transactions t JOIN public.labels l USING (transaction_id)
  WHERE l.label_available_at <> t.transaction_time + interval '60 days'
UNION ALL SELECT 'feature_from_the_future', count(*)
  FROM public.transactions t JOIN public.features f USING (transaction_id)
  WHERE f.feature_as_of <> t.transaction_time OR f.mcc_encoding_as_of > t.transaction_time
UNION ALL SELECT 'txn_before_account_created', count(*)
  FROM public.transactions t JOIN public.customers c USING (customer_id)
  WHERE t.transaction_time < c.created_at
UNION ALL SELECT 'holdout_doc_in_training_corpus', count(*)
  FROM public.documents WHERE cpt_eligible AND split <> 'train'
UNION ALL SELECT 'dpo_pair_outside_train', count(*)
  FROM public.preference_pairs WHERE split <> 'train';

-- Class-balance view of each time split (CRD 7.2: ~0.6% fraud).
SELECT split, count(*) AS rows, sum(fraud_label) AS fraud,
       round(avg(fraud_label)::numeric * 100, 3) AS fraud_pct
FROM public.labels GROUP BY split ORDER BY min(label_available_at);
