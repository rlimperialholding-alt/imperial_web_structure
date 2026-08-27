# Hozzáférési és élesítési ellenőrzőlista

## Google Cloud

- [ ] Külön Google Cloud projekt létrehozva az Imperial Intelligence részére.
- [ ] Analytics Data API engedélyezve.
- [ ] Search Console API engedélyezve.
- [ ] Service account létrehozva és kulcs biztonságosan eltárolva.
- [ ] A service account Viewer jogosultságot kapott minden GA4 propertyn.
- [ ] A service account felhasználóként hozzá lett adva minden Search Console propertyhez.
- [ ] OAuth consent screen és OAuth desktop/web kliens létrehozva a Business Profile részére.
- [ ] Business Profile API-hozzáférési kérelem jóváhagyva.
- [ ] Az Imperial irodai Business Profile-ok legalább 60 napja aktívak és ellenőrzöttek.
- [ ] Business Profile API-k és Performance API engedélyezve.
- [ ] Offline OAuth refresh token elkészült és secretként eltárolva.

## ingatlan.com

- [ ] Az ingatlan.com kapcsolattartó írásban visszaigazolta az Automata Betöltés jogosultságot.
- [ ] Tesztfelhasználónév és jelszó rendelkezésre áll.
- [ ] Az `apitest` környezetben legalább egy próbahirdetés teljes validációval átment.
- [ ] Saját `ownId` képzési szabály rögzítve, maximum 15 karakterrel.
- [ ] Referensek `agentId` megfeleltetése elkészült.
- [ ] Cím-, város- és városrész-kódok megfeleltetése elkészült.
- [ ] Képfolyamat megfelel a logó/vízjel szabályoknak.
- [ ] Új építésű projektek manuális kiegészítő folyamatát az iroda elfogadta.

## Weboldalak

- [ ] Minden engedélyezni kívánt oldal implementálta az aláírt `/api/internal/content-publish` végpontot.
- [ ] Oldalanként eltérő webhook secret beállítva.
- [ ] Staging környezetben publikálás, visszavonás és cache-frissítés tesztelve.
- [ ] Hibás aláírás és öt percnél régebbi kérés elutasítása tesztelve.
- [ ] Rollback és korábbi tartalomverzió visszaállítása tesztelve.

## Directus és üzemeltetés

- [ ] Directus admin jelszó, KEY és SECRET lecserélve.
- [ ] n8n encryption key lecserélve.
- [ ] MinIO/S3 hozzáférések lecserélve és mentés beállítva.
- [ ] PostgreSQL napi mentés és visszaállítási próba elkészült.
- [ ] Sentry/Grafana vagy más riasztás csatlakoztatva.
- [ ] API-admin token lecserélve.
- [ ] Éles környezet csak HTTPS-en érhető el.
