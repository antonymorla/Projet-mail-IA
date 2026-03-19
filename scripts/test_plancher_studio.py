"""Test live : vérifie les 4 typologies de plancher studio.

Usage (choisir UN test à la fois) :

    # Test 1 — Plancher isolé simple (isolation 60mm)
    python scripts/test_plancher_studio.py isolé

    # Test 2 — Plancher RE2020 (isolation RE2020)
    python scripts/test_plancher_studio.py re2020

    # Test 3 — Plancher renforcé + isolation 60mm
    python scripts/test_plancher_studio.py renforcé-60

    # Test 4 — Plancher renforcé + isolation RE2020
    python scripts/test_plancher_studio.py renforcé-re2020

    # Test 5 — Sans plancher (contrôle)
    python scripts/test_plancher_studio.py sans

    # Test 6 — Ancien nom "Plancher standard" (alias → isolé simple)
    python scripts/test_plancher_studio.py alias-standard

    # Test 7 — Ancien nom "Plancher porteur" (alias → renforcé)
    python scripts/test_plancher_studio.py alias-porteur

    # Test 8 — Auto-correction : RE2020 demandé avec isolation 60mm → isolé simple
    python scripts/test_plancher_studio.py autocorrect-re2020

    # Test 9 — Auto-correction : isolé simple demandé avec isolation RE2020 → RE2020
    python scripts/test_plancher_studio.py autocorrect-isolé
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
    "isolé": {
        "desc": "Plancher isolé simple + isolation 60mm",
        "isolation": "60mm",
        "plancher": "Plancher isolé simple",
    },
    "re2020": {
        "desc": "Plancher RE2020 + isolation RE2020",
        "isolation": "100 mm (RE2020)",
        "plancher": "Plancher RE2020",
    },
    "renforcé-60": {
        "desc": "Plancher renforcé + isolation 60mm",
        "isolation": "60mm",
        "plancher": "Plancher renforcé",
    },
    "renforcé-re2020": {
        "desc": "Plancher renforcé + isolation RE2020",
        "isolation": "100 mm (RE2020)",
        "plancher": "Plancher renforcé",
    },
    "sans": {
        "desc": "Sans plancher (contrôle)",
        "isolation": "60mm",
        "plancher": "Sans plancher",
    },
    "alias-standard": {
        "desc": "Alias 'Plancher standard' → doit devenir 'Plancher isolé simple'",
        "isolation": "60mm",
        "plancher": "Plancher standard",
    },
    "alias-porteur": {
        "desc": "Alias 'Plancher porteur' → doit devenir 'Plancher renforcé'",
        "isolation": "60mm",
        "plancher": "Plancher porteur",
    },
    "autocorrect-re2020": {
        "desc": "Auto-correction : RE2020 demandé avec 60mm → isolé simple",
        "isolation": "60mm",
        "plancher": "Plancher RE2020",
    },
    "autocorrect-isolé": {
        "desc": "Auto-correction : isolé simple demandé avec RE2020 → RE2020",
        "isolation": "100 mm (RE2020)",
        "plancher": "Plancher isolé simple",
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
