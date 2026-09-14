# Operations Workspace v1.0 – UAT terv

## UAT cél

Bizonyítani, hogy a PM, helyszíni és beszerzési felületek ugyanazon ProjectID alatt konzisztensen működnek, miközben a forrásmodul-jogkörök és a pénzügyi jóváhagyási határok megmaradnak.

## Szerepkörök

- projektvezető;
- helyszíni munkatárs / FMV;
- műszaki validáló;
- beszerző;
- pénzügyi munkatárs;
- ügyvezető/tulajdonos;
- rendszeradminisztrátor.

## Kötelező forgatókönyvek

### 1. PM portfólió

- három valós ProjectID megjelenik;
- készültség, blokkolt munkacsomag, nyitott ügy és költségvetület egyezik a forrásmodullal;
- egy blokkolt projekt a beavatkozási lista elejére kerül.

### 2. Munkacsomag és kapu

- munkacsomag készültsége módosítható jogosult felhasználóval;
- minden módosítás auditálódik;
- sikertelen indulási kapu nem engedi a kapcsolódó munkacsomagot szabálytalanul elindítani;
- bizonyítéklink visszakereshető.

### 3. Helyszíni napi jelentés

- mobilról napi jelentés készül;
- offline módban a piszkozat megmarad;
- hálózat visszatérésekor a felhasználó beküldi;
- akadály megadása helyszíni ügyet, PM-feladatot és eseményt hoz létre;
- jelentés és bizonyíték a Projekt 360° idővonalán megjelenik.

### 4. Anyagátvétel

- rendeléshez szállítólevél rögzíthető;
- hiányzó aláírt dokumentum fizetési/dokumentumblokkot képez;
- eltérő átvett mennyiség mennyiségi riasztást képez;
- anyaglot létrejön, tárolási hellyel és felelőssel;
- teljesítménynyilatkozat és e-napló-bizonyíték státusza ellenőrizhető.

### 5. Anyagmozgás és túlhasználat

- lot készlete be- és kimenő mozgással változik;
- negatív készletet a rendszer blokkol;
- túlhasználás értéke kiszámolható;
- csak levonási javaslat készül;
- jóváhagyás nélkül nincs Finance-módosítás vagy automatikus levonás.

### 6. Rendszerközi parancs

- Operations parancs Outbox-rekordot képez;
- azonos DedupeKey ismétlése nem hoz létre többszörös üzleti műveletet;
- sikertelen adapter retry/dead-letter státuszba kerül;
- forrásmodul-visszaigazolás után frissül a vetület.

## Elfogadási kapu

Production státusz kizárólag akkor adható, ha mindhárom valós ProjectID forgatókönyve sikeres, nincs kritikus jogosultsági vagy adatvesztési hiba, a backup/restore bizonyított, és a tulajdonosi jóváhagyás auditrekordként rendelkezésre áll.
