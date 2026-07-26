# ITEP v1.4 – Finance és CRM connectorok

Új kanonikus adapterek:

- BILLINGO: számlák, fizetési határidők, lejárt és fizetett számlák;
- BANK: PSD2-jellegű banki tranzakciók;
- CRM: leadek, ügyfélaktivitások, határidők és szerződéses aktivitások.

Az események a meglévő SourceIngestionService-en haladnak át, ezért a
fingerprint-alapú idempotencia, a deduplikáció, a Human Anne review queue és az
ITEP-feladatképzés automatikusan érvényesül.

Környezeti változók:
- BILLINGO_API_BASE_URL
- BANK_API_BASE_URL
- CRM_API_BASE_URL
- CONNECTOR_ACCESS_TOKEN_<CONNECTOR_ID>

Production kapu:
- valós Billingo contract teszt;
- választott bank/aggregátor PSD2-mezőtérkép;
- Imperial CRM konkrét endpoint- és mezőtérkép;
- ProjectID megfeleltetés;
- 100 számla, 500 tranzakció és 100 CRM-aktivitás staging UAT.
