"""A statikus kapu typecheck runtime-jának determinisztikus, policy-kompatibilis
szerződése.

A mypyc-fordított mypy (és a mypy 1.19+ kötelező, csak bináris kerékként
létező ``librt``) natív moduljait egy Windows application-control házirend
letiltotta, így a typecheck kapu forráshiba nélkül bukott. A javítás nem a
kaput enyhíti -- a scope, a konfiguráció és az exit-kód szemantika
változatlan --, hanem a futtató runtime-ot teszi olyanná, amire a
házirendnek nincs mit kifogásolnia: a ``check_typecheck_runtime`` szkriptben
auditáltan deklarált, pontosan pinnelt, tiszta Python mypy, natív
kiterjesztés nélkül. Ez a modul a deklarált pin, a telepített disztribúció
és a tényleg betöltött modulok három szintjét bizonyítja.
"""

from __future__ import annotations

import subprocess
import sys
from importlib import metadata
from pathlib import Path
from types import SimpleNamespace

import pytest

PLATFORM_CORE = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PLATFORM_CORE / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import check_typecheck_runtime  # noqa: E402

REQUIREMENTS_TEXT = (PLATFORM_CORE / "requirements-dev.txt").read_text(encoding="utf-8")
CHECK_SCRIPT = SCRIPTS_DIR / "check_typecheck_runtime.py"
# A mypy 1.19+ kötelező ``librt`` függősége csak bináris kerékként
# létezik; a deklarált pin ezért az utolsó librt-mentes kiadás.
BINARY_ONLY_DEPENDENCY = "librt"


def _exercised_runtime_modules() -> dict[str, object]:
    """A tényleges, betöltött typecheck runtime modulhalmaza."""
    import mypy.build  # noqa: F401

    return dict(sys.modules)


def test_declared_pure_version_has_no_binary_only_mandatory_dependency() -> None:
    """A deklarált pin megválasztásának indoka: nincs csak bináris függőség."""
    declared = check_typecheck_runtime._PURE_MYPY_VERSION
    assert metadata.version("mypy") == declared
    mandatory = [
        requirement
        for requirement in (metadata.requires("mypy") or [])
        if "extra ==" not in requirement
    ]
    assert mandatory, "a mypy metaadatának kötelező függőségeket kell hirdetnie"
    assert not [
        requirement
        for requirement in mandatory
        if requirement.split(";")[0].strip().lower().startswith(BINARY_ONLY_DEPENDENCY)
    ]


def test_installed_mypy_distribution_ships_no_native_extension_file() -> None:
    """Disztribúció-szintű bizonyíték: egyetlen natív kiterjesztés sincs telepítve."""
    files = metadata.files("mypy") or []
    native = [
        str(entry)
        for entry in files
        if str(entry).endswith(check_typecheck_runtime._NATIVE_SUFFIXES)
    ]
    assert native == []


def test_loaded_typecheck_runtime_is_entirely_source_backed() -> None:
    """Modul-szintű bizonyíték: minden betöltött runtime modul ``.py`` alapú."""
    modules = _exercised_runtime_modules()
    assert check_typecheck_runtime._REQUIRED_RUNTIME_MODULE in modules
    assert check_typecheck_runtime.native_runtime_modules(modules) == []


def test_verification_passes_for_this_environment() -> None:
    summary = check_typecheck_runtime.verify_typecheck_runtime(
        REQUIREMENTS_TEXT, _exercised_runtime_modules(), metadata.version("mypy")
    )
    assert "pure-Python mypy" in summary
    assert metadata.version("mypy") in summary


def test_check_script_passes_end_to_end() -> None:
    """A parancs-szintű viselkedés: exit 0 és PASS üzenet, monkeypatch nélkül."""
    completed = subprocess.run(
        [sys.executable, str(CHECK_SCRIPT)],
        cwd=str(PLATFORM_CORE),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "Typecheck runtime PASS" in completed.stdout


def test_requirements_range_without_an_exact_pin_uses_the_declared_version() -> None:
    """A tartomány-pin a baseline állapot; a deklaráció akkor is a szerződés."""
    assert (
        check_typecheck_runtime.declared_pure_mypy_version("mypy>=1.17,<2.0\n")
        == check_typecheck_runtime._PURE_MYPY_VERSION
    )


def test_requirements_exact_pin_must_agree_with_the_declared_runtime() -> None:
    """Egy eltérő pontos pin nem bújhat meg a deklaráció mellett."""
    with pytest.raises(check_typecheck_runtime.TypecheckRuntimeError) as excinfo:
        check_typecheck_runtime.declared_pure_mypy_version("mypy==1.17.1\n")
    assert "disagrees" in str(excinfo.value)


def test_requirements_duplicate_pin_fails_closed() -> None:
    with pytest.raises(check_typecheck_runtime.TypecheckRuntimeError):
        check_typecheck_runtime.declared_pure_mypy_version(
            "mypy==1.18.2\nmypy==1.17.1\n"
        )


def test_installed_version_mismatch_fails_closed() -> None:
    with pytest.raises(check_typecheck_runtime.TypecheckRuntimeError) as excinfo:
        check_typecheck_runtime.verify_typecheck_runtime(
            "mypy>=1.17,<2.0\n",
            {"mypy.build": SimpleNamespace(__file__="/synthetic/mypy/build.py")},
            "1.20.2",
        )
    assert "is not the declared" in str(excinfo.value)


def test_unexercised_runtime_fails_closed() -> None:
    """Nem lehet vákuumban átmenni: a canary modult be kell tölteni."""
    with pytest.raises(check_typecheck_runtime.TypecheckRuntimeError) as excinfo:
        check_typecheck_runtime.verify_typecheck_runtime(
            "mypy>=1.17,<2.0\n",
            {"mypy": SimpleNamespace(__file__="/synthetic/mypy/__init__.py")},
            check_typecheck_runtime._PURE_MYPY_VERSION,
        )
    assert "was not exercised" in str(excinfo.value)


@pytest.mark.parametrize("suffix", [".pyd", ".so", ".dll"])
def test_native_runtime_module_fails_closed(suffix: str) -> None:
    """Egyetlen natív kiterjesztésmodul is fail-closed -- platformtól függetlenül."""
    modules = {
        "mypy.build": SimpleNamespace(__file__="/synthetic/mypy/build.py"),
        "librt.base64": SimpleNamespace(__file__=f"/synthetic/librt/base64{suffix}"),
    }
    assert check_typecheck_runtime.native_runtime_modules(modules) == ["librt.base64"]
    with pytest.raises(check_typecheck_runtime.TypecheckRuntimeError) as excinfo:
        check_typecheck_runtime.verify_typecheck_runtime(
            "mypy>=1.17,<2.0\n", modules, check_typecheck_runtime._PURE_MYPY_VERSION
        )
    assert "native extension module(s)" in str(excinfo.value)
    assert "librt.base64" in str(excinfo.value)


def test_unrelated_native_modules_are_out_of_scope() -> None:
    """A szerződés a typecheck runtime-ra szól, nem az egész folyamatra."""
    modules = {
        "mypy.build": SimpleNamespace(__file__="/synthetic/mypy/build.py"),
        "cryptography.hazmat": SimpleNamespace(__file__="/synthetic/cryptography/hazmat.pyd"),
        "namespace_pkg": SimpleNamespace(),
    }
    assert check_typecheck_runtime.native_runtime_modules(modules) == []
