from __future__ import annotations

import re
import unicodedata

GENERIC_PHRASES = {
    "álmai otthona",
    "innovatív technológia",
    "kompromisszumok nélkül",
    "személyre szabott megoldás",
    "minden igényt kielégítő",
    "egyedülálló lehetőség",
    "professzionális megoldás",
    "magas minőség",
    "komplex szolgáltatás",
    "ügyfélközpontú szemlélet",
    "új dimenzió",
    "korszerű megoldások",
}

GENERIC_CTAS = {"kattints ide", "tovább", "küldés", "érdekel", "lépjen kapcsolatba"}

FORMAL_MARKERS = {"ön", "önnek", "önnel", "öné", "kérjen", "ismerje meg", "nézze meg"}
INFORMAL_MARKERS = {"te", "neked", "veled", "kérj", "ismerd meg", "nézd meg"}


def normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"\s+", " ", normalized).strip()


def contains_phrases(text: str, phrases: list[str] | set[str]) -> list[str]:
    value = normalize(text)
    return sorted(
        {
            phrase
            for phrase in phrases
            if re.search(
                rf"(?<!\w){re.escape(normalize(phrase))}(?!\w)",
                value,
            )
        }
    )


def sentence_lengths(text: str) -> list[int]:
    return [len(part.split()) for part in re.split(r"[.!?]+", text) if part.strip()]


def duplicate_values(values: list[str]) -> list[str]:
    normalized = [normalize(value) for value in values if normalize(value)]
    return sorted({value for value in normalized if normalized.count(value) > 1})


def tricolon_count(text: str) -> int:
    return len(
        re.findall(
            r"\b[^,.;]{2,40},\s*[^,.;]{2,40}\s+és\s+[^,.;]{2,40}[.;]",
            text,
            flags=re.IGNORECASE,
        )
    )


def numeric_signal_count(text: str) -> int:
    return len(re.findall(r"\b\d[\d\s.,%+/\-]*\b", text))
