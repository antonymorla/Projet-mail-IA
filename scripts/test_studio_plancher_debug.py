#!/usr/bin/env python3
"""
Test complet : 4 studios + 4 abris avec configurations variées.
Chaque test : configure → ajoute au panier → génère devis PDF.
Lance les tests un par un via argument : studio1, studio2, studio3, studio4, abri1, abri2, abri3, abri4
Ou "all" pour tout lancer séquentiellement.
"""
import asyncio
import sys
import os
import time
sys.path.insert(0, os.path.dirname(__file__))

from generateur_devis_auto import (
    GenerateurDevis, ConfigStudio, ConfigAbri, Client,
    generer_devis_studio, generer_devis_abri,
)

# Client de test
TEST_CLIENT = {
    "client_nom": "TestDevis",
    "client_prenom": "Auto",
    "client_email": "test@abri-francais.fr",
    "client_telephone": "0600000000",
    "client_adresse": "1 Rue du Test, 59000 Lille",
}


# ════════════════════════════════════════════
# CONFIGURATIONS STUDIO (4 tests)
# ════════════════════════════════════════════

STUDIO_TESTS = {
    "studio1": {
        "desc": "Studio basique 3,3x2,4 — 1 porte PVC, config minimale",
        "params": {
            "largeur": "3,3", "profondeur": "2,4",
            "menuiseries": [
                {"type": "PORTE VITREE", "materiau": "PVC", "mur": "MUR DE FACE", "position": "auto"},
            ],
            # Tout le reste = valeurs par défaut (Gris, 60mm, OSB, Sans plancher)
        },
    },
    "studio2": {
        "desc": "Studio 5,5x3,5 — plancher standard, bardage Brun, 2 menuiseries PVC",
        "params": {
            "largeur": "5,5", "profondeur": "3,5",
            "menuiseries": [
                {"type": "PORTE VITREE", "materiau": "PVC", "mur": "MUR DE FACE", "position": "gauche"},
                {"type": "FENETRE SIMPLE", "materiau": "PVC", "mur": "MUR DE DROITE", "position": "centre"},
            ],
            "bardage_exterieur": "Brun",
            "plancher": "Plancher standard",
        },
    },
    "studio3": {
        "desc": "Studio 6,6x4,6 MAX — plancher porteur, finition, terrasse, pergola, multi-menuiseries ALU",
        "params": {
            "largeur": "6,6", "profondeur": "4,6",
            "menuiseries": [
                {"type": "PORTE VITREE", "materiau": "PVC", "mur": "MUR DE FACE", "position": "gauche"},
                {"type": "FENETRE DOUBLE", "materiau": "PVC", "mur": "MUR DE FACE", "position": "droite"},
                {"type": "BAIE VITREE", "materiau": "ALU", "mur": "MUR DE GAUCHE", "position": "centre"},
                {"type": "FENETRE SIMPLE", "materiau": "ALU", "mur": "MUR DU FOND", "position": "auto"},
            ],
            "bardage_exterieur": "Noir",
            "bardage_interieur": "Panneaux bois massif (3 plis épicéa)",
            "plancher": "Plancher porteur",
            "finition_plancher": True,
            "terrasse": "4m (32m2)",
            "pergola": "6x4m (24m2)",
        },
    },
    "studio4": {
        "desc": "Studio 8,8x5,7 — RE2020, rehausse, terrasse, 3 menuiseries mixtes",
        "params": {
            "largeur": "8,8", "profondeur": "5,7",
            "menuiseries": [
                {"type": "PORTE DOUBLE VITREE", "materiau": "ALU", "mur": "MUR DE FACE", "position": "centre"},
                {"type": "FENETRE SIMPLE", "materiau": "PVC", "mur": "MUR DE GAUCHE", "position": "auto"},
                {"type": "FENETRE SIMPLE", "materiau": "PVC", "mur": "MUR DE DROITE", "position": "auto"},
            ],
            "bardage_exterieur": "Gris",
            "isolation": "100 mm (RE2020)",
            "rehausse": True,
            "plancher": "Plancher porteur",
            "terrasse": "2 m (22 m2)",
        },
    },
}


# ════════════════════════════════════════════
# CONFIGURATIONS ABRI (4 tests)
# ════════════════════════════════════════════

ABRI_TESTS = {
    "abri1": {
        "desc": "Abri basique 3,45M x 2,15m — 1 porte vitrée Face 1",
        "params": {
            "largeur": "3,45M", "profondeur": "2,15m",
            "ouvertures": [
                {"type": "Porte Vitrée", "face": "Face 1", "position": "Centre"},
            ],
        },
    },
    "abri2": {
        "desc": "Abri 5,50M x 3,45m — 2 ouvertures + plancher",
        "params": {
            "largeur": "5,50M", "profondeur": "3,45m",
            "ouvertures": [
                {"type": "Porte double Vitrée", "face": "Face 1", "position": "Centre"},
                {"type": "Fenêtre Horizontale", "face": "Droite", "position": "Centre"},
            ],
            "plancher": True,
        },
    },
    "abri3": {
        "desc": "Abri 6,80M x 4,35m — extension toiture droite 2M + bac acier",
        "params": {
            "largeur": "6,80M", "profondeur": "4,35m",
            "ouvertures": [
                {"type": "Porte double Vitrée", "face": "Face 1", "position": "Gauche"},
                {"type": "Fenêtre Verticale", "face": "Face 1", "position": "Droite"},
            ],
            "extension_toiture": "Droite 2 M",
            "bac_acier": True,
        },
    },
    "abri4": {
        "desc": "Abri MAX 8,60M x 4,35m — 3 ouvertures + plancher + bac acier + extension",
        "params": {
            "largeur": "8,60M", "profondeur": "4,35m",
            "ouvertures": [
                {"type": "Porte double Vitrée", "face": "Face 1", "position": "Gauche"},
                {"type": "Porte double Pleine", "face": "Face 1", "position": "Droite"},
                {"type": "Fenêtre Horizontale", "face": "Gauche", "position": "Centre"},
            ],
            "plancher": True,
            "bac_acier": True,
            "extension_toiture": "Gauche 1 M",
        },
    },
}


async def run_studio_test(test_id: str):
    """Lance un test studio complet (config → panier → PDF)."""
    test = STUDIO_TESTS[test_id]
    print(f"\n{'='*60}")
    print(f"  TEST {test_id.upper()} — {test['desc']}")
    print(f"{'='*60}")

    params = {**test["params"], **TEST_CLIENT}
    start = time.time()
    try:
        filepath = await generer_devis_studio(**params)
        elapsed = time.time() - start
        print(f"\n  ✅ {test_id} RÉUSSI en {elapsed:.0f}s — {filepath}")
        return True
    except Exception as e:
        elapsed = time.time() - start
        print(f"\n  ❌ {test_id} ÉCHOUÉ en {elapsed:.0f}s — {e}")
        import traceback
        traceback.print_exc()
        return False


async def run_abri_test(test_id: str):
    """Lance un test abri complet (config → panier → PDF)."""
    test = ABRI_TESTS[test_id]
    print(f"\n{'='*60}")
    print(f"  TEST {test_id.upper()} — {test['desc']}")
    print(f"{'='*60}")

    params = {**test["params"], **TEST_CLIENT}
    start = time.time()
    try:
        filepath = await generer_devis_abri(**params)
        elapsed = time.time() - start
        print(f"\n  ✅ {test_id} RÉUSSI en {elapsed:.0f}s — {filepath}")
        return True
    except Exception as e:
        elapsed = time.time() - start
        print(f"\n  ❌ {test_id} ÉCHOUÉ en {elapsed:.0f}s — {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    if len(sys.argv) < 2:
        print("Usage: python3 test_studio_plancher_debug.py <test_id>")
        print("  Tests studio: studio1, studio2, studio3, studio4")
        print("  Tests abri:   abri1, abri2, abri3, abri4")
        print("  Tout:         all")
        print("  Studios:      all-studio")
        print("  Abris:        all-abri")
        sys.exit(1)

    test_id = sys.argv[1].lower()

    if test_id == "all":
        tests = list(STUDIO_TESTS.keys()) + list(ABRI_TESTS.keys())
    elif test_id == "all-studio":
        tests = list(STUDIO_TESTS.keys())
    elif test_id == "all-abri":
        tests = list(ABRI_TESTS.keys())
    else:
        tests = [test_id]

    results = {}
    for tid in tests:
        if tid in STUDIO_TESTS:
            ok = await run_studio_test(tid)
        elif tid in ABRI_TESTS:
            ok = await run_abri_test(tid)
        else:
            print(f"  ⚠ Test inconnu : {tid}")
            continue
        results[tid] = ok

    # Résumé
    print(f"\n{'='*60}")
    print(f"  RÉSUMÉ DES TESTS")
    print(f"{'='*60}")
    for tid, ok in results.items():
        status = "✅" if ok else "❌"
        print(f"  {status} {tid}")
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    print(f"\n  {passed}/{total} réussis")


if __name__ == "__main__":
    asyncio.run(main())
