# Gmail / Drive / Sheets connector szerződés

Az élő connector egy körülhatárolt forrásból rekordokat vagy szöveget gyűjt, majd az alábbi végpontra küldi:

`POST /api/imports/push`

```json
{
  "source_key": "gmail_enterprise",
  "external_id": "gmail-message-id",
  "file_name": "szamla.pdf",
  "mime_type": "application/pdf",
  "source_url": "belső-forráslink",
  "domain_hint": "enterprise",
  "records": [{"Projektazonosító": "IMP-...", "Számlaszám": "..."}],
  "text": "opcionális kinyert szöveg",
  "metadata": {"thread_id": "...", "label": "Pénzügy"}
}
```

A connector feladata a hitelesített forrásolvasás és – szükség esetén – OCR/Document AI. Az Import Center feladata a normalizálás, osztályozás, validáció, deduplikáció, staging és kontrollált commit.
