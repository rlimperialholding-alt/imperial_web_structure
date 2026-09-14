# Imperial Checklist Engine v0.5.0

## Forrás és lefedettség

A kanonikus forrás a `CHK-000 – Operatív checklist katalógus és 99 folyamatsablon v1.0 – UAT` munkafüzet. A kiadási csomag ennek normalizált, gépi változatát tartalmazza:

- `config/operational-process-catalog-v1.0.json`;
- `docs/sources/CHK-000_operativ_checklist_katalogus_v1.0_UAT.xlsx`.

Lefedettség: 19 folyamatcsalád, 99 ProcessID és 99 egyedi ChecklistTemplateID.

## Sablon és példány

A sablon azt mondja meg, mit kell ellenőrizni. A példány egy konkrét üzleti objektum végrehajtási rekordja.

Kötelező példánymezők:

- ChecklistInstanceID;
- ProcessID és ChecklistTemplateID;
- GateID;
- RoleID az öt munkakör egyikéből;
- ObjectID és ObjectType;
- IGEN / NEM / N.A. válasz minden kötelező pontra;
- megjegyzés és bizonyíték;
- javítási felelős és határidő NEM válasznál;
- beküldő, jóváhagyó és időbélyegek;
- sablonverzió.

## Biztonsági szabályok

- blocking `NEM` válasz azonnal `HOLD` állapotot eredményez;
- kötelező pont nem maradhat válasz nélkül;
- kötelező evidence nélkül nincs beküldés;
- lezárt checklist nem módosítható;
- csak `CLOSED` státusz ad `can_proceed=true` eredményt;
- minden módosítás auditnaplóba és – konfigurált Directus esetén – a központi rekordba kerül.

## API

Minden végpont az `X-Imperial-Token` adminfejlécet kéri.

- `GET /api/v1/checklists/templates`
- `GET /api/v1/checklists/templates/process/{process_key}`
- `POST /api/v1/checklists/instances`
- `GET /api/v1/checklists/instances/{instance_id}`
- `PUT /api/v1/checklists/instances/{instance_id}/items/{item_id}`
- `POST /api/v1/checklists/instances/{instance_id}/evidence`
- `POST /api/v1/checklists/instances/{instance_id}/submit`
- `POST /api/v1/checklists/instances/{instance_id}/approve`
- `GET /api/v1/checklists/instances/{instance_id}/gate`

## UAT minimum

Minden folyamatcsaládból legalább egy valós példányt végig kell futtatni. Kötelező külön teszt:

- sikeres IGEN út;
- blocking NEM és HOLD;
- N.A. indoklás;
- hiányzó evidence blokkolása;
- új sablonverzió után régi és új példány elkülönítése;
- jogosultság és ügyvezetői jóváhagyás;
- workflow csak CLOSED kapu után lép tovább.
