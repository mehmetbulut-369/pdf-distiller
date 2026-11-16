"""Çeviri dosyaları kontrolü: her dilde aynı anahtarlar, aynı yer tutucular; kodda kullanılan
her anahtar sözlükte var. Yeni metin eklerken üç dosyaya da eklemek yeterli, bu test unutulanı yakalar."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "app" / "static"
LANGS = ("en", "de", "tr")
DICTS = {lang: json.loads((STATIC / "i18n" / f"{lang}.json").read_text("utf-8")) for lang in LANGS}
EN = DICTS["en"]
PLACEHOLDER = re.compile(r"\{(\w+)\}")


@pytest.mark.parametrize("lang", LANGS[1:])
def test_same_keys_as_english(lang):
    d = DICTS[lang]
    assert sorted(set(EN) - set(d)) == [], f"{lang}.json'da eksik"
    assert sorted(set(d) - set(EN)) == [], f"{lang}.json'da fazla"


@pytest.mark.parametrize("lang", LANGS)
def test_values_non_empty_and_placeholders_match(lang):
    for k, v in DICTS[lang].items():
        assert isinstance(v, str) and v.strip(), f"{lang}:{k} boş"
        assert set(PLACEHOLDER.findall(v)) == set(PLACEHOLDER.findall(EN[k])), f"{lang}:{k} yer tutucu farklı"


def _used_keys() -> set[str]:
    html = (STATIC / "index.html").read_text("utf-8")
    js = (STATIC / "app.js").read_text("utf-8")
    server = (ROOT / "app" / "server.py").read_text("utf-8")
    keys = set(re.findall(r'data-i18n(?:-[a-z-]+)?="([^"]+)"', html))
    # app.js: anahtar biçimindeki her dizge (t("a.b"), üçlü ifadeler, şablonlar dahil; ${…} içerenler hariç)
    prefixes = {k.split(".")[0] for k in EN}
    for lit in re.findall(r'["`]([a-z_]+\.[a-z0-9_.-]+)["`]', js):
        if lit.split(".")[0] in prefixes:
            keys.add(lit)
    keys |= set(re.findall(r'HTTPException\(\d+, "([^"]+)"', server))
    # dinamik anahtarlar: t(`tier.${t}.name`), t(`cls.${c}`) …
    keys |= {f"tier.{i}.{p}" for i in range(4) for p in ("name", "desc")}
    keys |= {f"cap.{x}" for x in ("graphics", "text", "crop")}
    keys |= {f"sort.{x}" for x in ("desc", "asc", "alpha")}
    keys |= {f"kind.{x}" for x in ("image", "fill", "stroke", "shading", "text")}
    keys |= {f"cls.{x}" for x in ("white", "background", "repeated", "large", "other",
                                  "text", "text_repeated", "text_image")}
    keys |= {f"profile.{p.stem}" for p in (ROOT / "profiles").glob("*.json")}
    return keys


def test_every_used_key_exists():
    missing = sorted(k for k in _used_keys() if k not in EN)
    assert missing == []


def test_server_errors_are_keys():
    server = (ROOT / "app" / "server.py").read_text("utf-8")
    for detail in re.findall(r"HTTPException\(\d+, ([^)]+)\)", server):
        assert re.fullmatch(r'"error\.[a-z_]+"', detail.strip()), f"çevrilmemiş hata: {detail}"
