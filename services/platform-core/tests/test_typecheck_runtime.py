"""A statikus kapu typecheck runtime-jának determinisztikus, policy-kompatibilis
szerződése.

Task40: a Task39 statikus kapuja nem forráshiba miatt bukott meg, hanem mert a
mypyc-fordított mypy (és a mypy 1.19+ kötelező, csak bináris kerékként létező
``librt`` függőségének) natív kiterjesztésmoduljait egy Windows
application-control házirend letiltotta:
``ImportError: DLL load failed while importing base64``. A javítás nem a kaput
enyhíti -- a scope, a konfiguráció és az exit-kód szemantika változatlan --,
hanem a futtató runtime-ot teszi olyanná, amire a házirendnek nincs mit
kifogásolnia: pontosan pinnelt, tiszta Python mypy, natív kiterjesztés nélkül.

Ez a modul azt bizonyítja, hogy ez a tulajdonság kikényszerített és nem
véletlen: a deklarált pin (``--no-binary mypy`` + pontos ``mypy==``), a
telepített disztribúció és a tényleg betöltött modulok mindhárom szintjén, a
fail-closed irányokkal együtt.
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
# A mypy 1.19-ben jelent meg a kötelező, csak bináris kerékként publikált
# ``librt`` függőség; a pin ezért az utolsó librt-mentes kiadásra mutat.
BINARY_ONLY_DEPENDENCY = "librt"


def _exercised_runtime_modules() -> dict[str, object]:
    """A tényleges, betöltött typecheck runtime modulhalmaza."""
    import mypy.build  # noqa: F401

    return dict(sys.modules)


def test_requirements_declare_an_exact_pure_python_mypy_pin() -> None:
    """A deklaráció mindkét fele kötelező: pure-Python build és pontos verzió."""
    pinned = check_typecheck_runtime.pinned_mypy_requirement(REQUIREMENTS_TEXT)
    assert pinned == metadata.version("mypy")


def test_pinned_mypy_has_no_binary_only_mandatory_dependency() -> None:
    """A pin megválasztásának indoka: nincs csak bináris kötelező függőség.

    A ``librt`` kizárólag bináris kerékként létezik, tehát egy rá építő mypy
    soha nem lehet tisztán Python futtatású -- a pinnelt kiadás metaadatában
    ezért nem szerepelhet kötelező (extra nélküli) függőségként.
    """
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


def test_missing_no_binary_directive_fails_closed() -> None:
    """Pure-Python kényszerítés nélkül a pip a fordított kereket választaná."""
    with pytest.raises(check_typecheck_runtime.TypecheckRuntimeError) as excinfo:
        check_typecheck_runtime.pinned_mypy_requirement("mypy==1.18.2\n")
    assert "--no-binary mypy" in str(excinfo.value)


@pytest.mark.parametrize(
    "requirements",
    [
        "--no-binary mypy\nmypy>=1.17,<2.0\n",
        "--no-binary mypy\nmypy~=1.18\n",
        "--no-binary mypy\n",
    ],
)
def test_inexact_pin_fails_closed(requirements: str) -> None:
    """Tartomány-pin csendben előrelépne egy csak bináris függőségű kiadásra."""
    with pytest.raises(check_typecheck_runtime.TypecheckRuntimeError) as excinfo:
        check_typecheck_runtime.pinned_mypy_requirement(requirements)
    assert "exactly one version" in str(excinfo.value)


def test_duplicate_pin_fails_closed() -> None:
    with pytest.raises(check_typecheck_runtime.TypecheckRuntimeError):
        check_typecheck_runtime.pinned_mypy_requirement(
            "--no-binary mypy\nmypy==1.18.2\nmypy==1.17.1\n"
        )


def test_no_binary_equals_spelling_is_accepted() -> None:
    """A pip mindkét írásmódja ugyanaz a direktíva."""
    assert (
        check_typecheck_runtime.pinned_mypy_requirement("--no-binary=mypy\nmypy==1.18.2\n")
        == "1.18.2"
    )


def test_installed_version_mismatch_fails_closed() -> None:
    with pytest.raises(check_typecheck_runtime.TypecheckRuntimeError) as excinfo:
        check_typecheck_runtime.verify_typecheck_runtime(
            "--no-binary mypy\nmypy==1.18.2\n",
            {"mypy.build": SimpleNamespace(__file__="/synthetic/mypy/build.py")},
            "1.20.2",
        )
    assert "is not the pinned" in str(excinfo.value)


def test_unexercised_runtime_fails_closed() -> None:
    """Nem lehet vákuumban átmenni: a canary modult be kell tölteni."""
    with pytest.raises(check_typecheck_runtime.TypecheckRuntimeError) as excinfo:
        check_typecheck_runtime.verify_typecheck_runtime(
            "--no-binary mypy\nmypy==1.18.2\n",
            {"mypy": SimpleNamespace(__file__="/synthetic/mypy/__init__.py")},
            "1.18.2",
        )
    assert "was not exercised" in str(excinfo.value)


@pytest.mark.parametrize("suffix", [".pyd", ".so", ".dll"])
def test_native_runtime_module_fails_closed(suffix: str) -> None:
    """Egyetlen natív kiterjesztésmodul is fail-closed -- platformtól függetlenül.

    Ez pontosan az a betöltési út, amit az application-control házirend
    letilthat, ezért nem elég, hogy a jelenlegi hoston éppen működik.
    """
    modules = {
        "mypy.build": SimpleNamespace(__file__="/synthetic/mypy/build.py"),
        "librt.base64": SimpleNamespace(__file__=f"/synthetic/librt/base64{suffix}"),
    }
    assert check_typecheck_runtime.native_runtime_modules(modules) == ["librt.base64"]
    with pytest.raises(check_typecheck_runtime.TypecheckRuntimeError) as excinfo:
        check_typecheck_runtime.verify_typecheck_runtime(
            "--no-binary mypy\nmypy==1.18.2\n", modules, "1.18.2"
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
