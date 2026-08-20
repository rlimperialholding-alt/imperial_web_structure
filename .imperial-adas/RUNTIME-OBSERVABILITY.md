# Runtime / observability contract

A control plane helyben OpenTelemetry OTLP traces, metrics és logs jeleket fogad. A deployment gate csak akkor nyitható, ha az alkalmazás instrumentációja ténylegesen be van kötve, a `runtime-policy.json` `openTelemetry.enabled` értéke `true`, legalább egy projekt-specifikus health/business-smoke check működik, valamint a deploy és rollback parancsok konfiguráltak.

A kötelező üzleti számlálókat a projekt `runtime-policy.json` fájljának `requiredBusinessMetrics` mezője határozza meg. A generált lead/e-mail lista csak visszafelé kompatibilis alapérték, amelyet a projekt valós üzleti invariánsaira kell cserélni.

A reconciliation a beérkezett, feldolgozott és kimeneti darabszámokat veti össze. Ismeretlen, hiányzó vagy időtúllépő bizonyíték nem PASS, hanem blokkolás vagy warning a runtime policy production módja szerint.