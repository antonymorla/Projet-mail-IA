"""Test live : vérifie les 4 typologies de plancher studio.

DOM WPC data-text : "Sans plancher", "Plancher standard", "Plancher RE2020", "Plancher porteur"
Alias acceptés : "Plancher isolé simple" → "Plancher standard", "Plancher renforcé" → "Plancher porteur"

Usage (choisir UN test à la fois) :

    # Test 1 — Plancher standard (isolation 60mm)
    python3 scripts/test_plancher_studio.py standard

    # Test 2 — Plancher RE2020 (isolation RE2020)
    python3 scripts/test_plancher_studio.py re2020

    # Test 3 — Plancher porteur + isolation 60mm
    python3 scripts/test_plancher_studio.py porteur-60

    # Test 4 — Plancher porteur + isolation RE2020
    python3 scripts/test_plancher_studio.py porteur-re2020

    # Test 5 — Sans plancher (contrôle)
    python3 scripts/test_plancher_studio.py sans

    # Test 6 — Alias "Plancher isolé simple" (→ Plancher standard)
    python3 scripts/test_plancher_studio.py alias-isolé

    # Test 7 — Alias "Plancher renforcé" (→ Plancher porteur)
    python3 scripts/test_plancher_studio.py alias-renforcé

    # Test 8 — Auto-correction : RE2020 demandé avec isolation 60mm → standard
    python3 scripts/test_plancher_studio.py autocorrect-re2020

    # Test 9 — Auto-correction : standard demandé avec isolation RE2020 → RE2020
    python3 scripts/test_plancher_studio.py autocorrect-standard
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from generateur_devis_auto import generer_devis_studio

# Config commune pour tous les tests
_COMMON = dict(
    largeur="4,4",
    profondeur="3,5",
    menuiseries=[
        {"type": "PORTE VITREE", "materiau": "PVC", "mur": "MUR DE FACE", "position": "centre"},
    ],
    bardage_exterieur="Gris",
    bardage_interieur="OSB",
    rehausse=False,
    finition_plancher=False,
    terrasse="",
    pergola="",
    client_nom="Test",
    client_prenom="Plancher",
    client_email="test@test.fr",
    client_telephone="0600000000",
    client_adresse="1 Rue Test, 75001 Paris",
    headless=False,
)

SCENARIOS = {
    # --- Tests principaux (noms DOM data-text) ---
    "standard": {
        "desc": "Plancher standard + isolation 60mm",
        "isolation": "60mm",
        "plancher": "Plancher standard",
    },
    "re2020": {
        "desc": "Plancher RE2020 + isolation RE2020",
        "isolation": "100 mm (RE2020)",
        "plancher": "Plancher RE2020",
    },
    "porteur-60": {
        "desc": "Plancher porteur + isolation 60mm",
        "isolation": "60mm",
        "plancher": "Plancher porteur",
    },
    "porteur-re2020": {
        "desc": "Plancher porteur + isolation RE2020",
        "isolation": "100 mm (RE2020)",
        "plancher": "Plancher porteur",
    },
    "sans": {
        "desc": "Sans plancher (contrôle)",
        "isolation": "60mm",
        "plancher": "Sans plancher",
    },
    # --- Tests alias (noms alternatifs → data-text DOM) ---
    "alias-isolé": {
        "desc": "Alias 'Plancher isolé simple' → résolu en 'Plancher standard'",
        "isolation": "60mm",
        "plancher": "Plancher isolé simple",
    },
    "alias-renforcé": {
        "desc": "Alias 'Plancher renforcé' → résolu en 'Plancher porteur'",
        "isolation": "60mm",
        "plancher": "Plancher renforcé",
    },
    # --- Tests auto-correction incohérence isolation/plancher ---
    "autocorrect-re2020": {
        "desc": "Auto-correction : RE2020 demandé avec 60mm → Plancher standard",
        "isolation": "60mm",
        "plancher": "Plancher RE2020",
    },
    "autocorrect-standard": {
        "desc": "Auto-correction : standard demandé avec RE2020 → Plancher RE2020",
        "isolation": "100 mm (RE2020)",
        "plancher": "Plancher standard",
    },
}


async def main():
    if len(sys.argv) < 2 or sys.argv[1] not in SCENARIOS:
        print("Usage : python scripts/test_plancher_studio.py <scenario>")
        print("\nScénarios disponibles :")
        for key, s in SCENARIOS.items():
            print(f"  {key:25s} → {s['desc']}")
        sys.exit(1)

    scenario = SCENARIOS[sys.argv[1]]
    print(f"\n{'='*60}")
    print(f"  TEST PLANCHER : {scenario['desc']}")
    print(f"  Isolation : {scenario['isolation']}")
    print(f"  Plancher demandé : {scenario['plancher']}")
    print(f"{'='*60}\n")

    params = {**_COMMON, "isolation": scenario["isolation"], "plancher": scenario["plancher"]}
    result = await generer_devis_studio(**params)
    print(f"\n✅ Devis généré : {result}")


if __name__ == "__main__":
    asyncio.run(main())
