"""Lineáris, korlátos e-mail-cím validálás (ReDoS-mentes).

A korábbi ``[^@\\s]+@[^@\\s]+\\.[^@\\s]+`` minta átfedő karakterosztályai
polinomiális visszalépést tettek lehetővé (a CodeQL ``py/polynomial-redos``
szabálya szerint). Ez a validátor egyáltalán nem használ reguláris kifejezést:
minden részt karakterenként, fix bejárással ellenőriz, így a futásidő az input
hosszának lineáris függvénye.

Dokumentált bemeneti korlátok (RFC 5321/5322 pragmatikus részhalmaz):
- teljes cím: legfeljebb 254 karakter,
- local part: legfeljebb 64 karakter,
- domain: legfeljebb 255 karakter, legalább 2 label,
- domain-label: legfeljebb 63 karakter, nem kezdődhet/végződhet kötőjellel,
- az utolsó label (TLD) alfanumerikus (betű vagy számjegy), legalább 2 karakter
  hosszan.

Üzleti kompatibilitási döntések (repo-contracttal igazolt, 2026-08-23):
- Az idézőjeles local part (pl. ``"user"@example.com``) elfogadott: a korábbi,
  a tender_portal/tender_mail/partner_control/imperial_care folyamatokban
  érvényben lévő ``[^@\s]+@[^@\s]+\.[^@\s]+`` üzleti szerződés elfogadta.
- A numerikus TLD (pl. ``user@123.123``) elfogadott ugyanezen szerződés
  alapján; az egykarakteres TLD (``user@example.c``) továbbra is elutasított.
- A szóközt tartalmazó címek (``"john doe"@example.com``) és a single-label
  domainek (``user@localhost``) a régi szerződés szerint sem voltak érvényesek,
  ezért továbbra is elutasítottak.
- A biztonsági korlátok (hosszkorlátok, szóköz- és vezérlőkarakter-tiltás,
  pont- és kötőjelszabályok, label-szabályok) változatlanok; a ReDoS-mentes,
  lineáris szkennelés megmaradt.
"""

from __future__ import annotations

MAX_EMAIL_LENGTH = 254
MAX_LOCAL_LENGTH = 64
MAX_DOMAIN_LENGTH = 255
MAX_LABEL_LENGTH = 63

# A ``"`` karakter a korábbi üzleti szerződés szerint része volt a local
# partnak (idézett local part); szóköz és vezérlőkarakter továbbra is tiltott.
_LOCAL_EXTRA = frozenset("!#$%&'*+-/=?^_`{|}~.\"")


def is_valid_email(value: object) -> bool:
    if not isinstance(value, str) or not value or len(value) > MAX_EMAIL_LENGTH:
        return False
    local, separator, domain = value.partition("@")
    if (
        not separator
        or not local
        or not domain
        or len(local) > MAX_LOCAL_LENGTH
        or len(domain) > MAX_DOMAIN_LENGTH
    ):
        return False
    if local[0] == "." or local[-1] == "." or ".." in local:
        return False
    if any(not (char.isalnum() or char in _LOCAL_EXTRA) for char in local):
        return False
    labels = domain.rstrip(".").split(".")
    if len(labels) < 2 or any(not label or len(label) > MAX_LABEL_LENGTH for label in labels):
        return False
    for label in labels:
        if label[0] == "-" or label[-1] == "-":
            return False
        if any(not (char.isalnum() or char == "-") for char in label):
            return False
    if len(labels[-1]) < 2 or not labels[-1].isalnum():
        return False
    return True
