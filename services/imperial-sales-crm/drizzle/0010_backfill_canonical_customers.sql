INSERT OR IGNORE INTO `crm_customers` (
  `id`,
  `customer_type`,
  `name`,
  `email`,
  `phone`,
  `billing_address`,
  `tax_number`,
  `company_registration_number`,
  `source_lead_id`,
  `status`,
  `created_by_email`,
  `created_at`,
  `updated_at`
)
SELECT
  'CUST-IMPORT-' || ci.`id`,
  CASE
    WHEN lower(l.`name`) LIKE '% kft%'
      OR lower(l.`name`) LIKE '% zrt%'
      OR lower(l.`name`) LIKE '% bt%'
      OR lower(l.`name`) LIKE '% egyéni vállalkoz%'
    THEN 'company'
    ELSE 'person'
  END,
  trim(l.`name`),
  lower(trim(l.`email`)),
  CASE WHEN trim(l.`phone`) IN ('', '—') THEN 'Adatpótlás szükséges' ELSE trim(l.`phone`) END,
  CASE
    WHEN trim(l.`location`) IN ('', 'Nincs megadva') THEN 'Adatpótlás szükséges'
    ELSE trim(l.`location`) || ' · pontos számlázási cím szükséges'
  END,
  NULL,
  NULL,
  l.`id`,
  'prospect',
  'migration@imperial.system',
  ci.`imported_at`,
  ci.`imported_at`
FROM `crm_customer_imports` ci
JOIN `leads` l ON l.`id` = ci.`lead_id`
WHERE instr(trim(l.`email`), '@') > 1
ORDER BY ci.`id`;
