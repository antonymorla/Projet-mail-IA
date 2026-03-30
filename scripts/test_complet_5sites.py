#!/usr/bin/env python3
"""
Test complet : 5 sites × configurations variées + multi-config panier.
Chaque test : configure → ajoute au panier → génère devis PDF.

Usage :
    python3 test_complet_5sites.py <test_id>
    python3 test_complet_5sites.py all
    python3 test_complet_5sites.py all-pergola
    python3 test_complet_5sites.py all-terrasse
    python3 test_complet_5sites.py all-cloture
    python3 test_complet_5sites.py all-studio
    python3 test_complet_5sites.py all-abri
"""
import asyncio
import sys
import os
import time
import json

sys.path.insert(0, os.path.dirname(__file__))

from generateur_devis_auto import (
    GenerateurDevis, ConfigStudio, ConfigAbri, Client,
    generer_devis_studio, generer_devis_abri,
)
from generateur_devis_3sites import (
    generer_devis_pergola,
    generer_devis_terrasse,
    generer_devis_terrasse_detail,
    generer_devis_cloture,
)

# Client de test
TEST_CLIENT = {
    "client_nom": "TestDevis",
    "client_prenom": "Auto",
    "client_email": "test@abri-francais.fr",
    "client_telephone": "0600000000",
    "client_adresse": "1 Rue du Test, 59000 Lille",
}


# ════════════════════════════════════════════════════════
# PERGOLA — 3 tests (options, pente, multi-config)
# ════════════════════════════════════════════════════════

PERGOLA_TESTS = {
    "pergola1": {
        "desc": "Pergola 5m×3m indépendante — ventelles largeur + pente 15%",
        "func": "pergola",
        "params": {
            "largeur": "5m", "profondeur": "3m",
            "fixation": "independante", "ventelle": "largeur",
            "option": "non",
            "pente": "15%",
            "poteau_lamelle_colle": True,
            "nb_poteaux_lamelle_colle": 4,
        },
    },
    "pergola2": {
        "desc": "Pergola 7m×4m adossée — platelage + claustra vertical×3 + sur-mesure",
        "func": "pergola",
        "params": {
            "largeur": "7m", "profondeur": "4m",
            "fixation": "adossee", "ventelle": "largeur",
            "option": "platelage",
            "claustra_type": "vertical", "nb_claustra": 3,
            "poteau_lamelle_colle": True,
            "nb_poteaux_lamelle_colle": 4,
            "sur_mesure": True,
            "largeur_hors_tout": "6.80",
            "profondeur_hors_tout": "3.50",
            "hauteur_hors_tout": "2.52",
        },
    },
    "pergola3_multi": {
        "desc": "Multi-config — 2 pergolas au même panier (5m×3m + 4m×2m)",
        "func": "pergola",
        "params": {
            "largeur": "5m", "profondeur": "3m",
            "fixation": "independante", "ventelle": "largeur",
            "option": "non",
            "pente": "5%",
            "poteau_lamelle_colle": True,
            "nb_poteaux_lamelle_colle": 4,
            "configurations_supplementaires": json.dumps([
                {
                    "largeur": "4m", "profondeur": "3m",
                    "fixation": "independante", "ventelle": "largeur",
                    "option": "non",
                    "pente": "",
                    "poteau_lamelle_colle": True,
                    "nb_poteaux_lamelle_colle": 4,
                }
            ]),
        },
    },
}


# ════════════════════════════════════════════════════════
# TERRASSE — 3 tests (WAPF, multi-config, au détail)
# ════════════════════════════════════════════════════════

TERRASSE_TESTS = {
    "terrasse1": {
        "desc": "Terrasse PIN 27mm Vert 4.2m — 10m² + lambourdes + plots + vis",
        "func": "terrasse",
        "params": {
            "essence": "PIN 27mm Autoclave Vert",
            "longueur": "4.2",
            "quantite": 10,
            "lambourdes": "Pin autoclave Vert 45x70",
            "lambourdes_longueur": "4.2",
            "plots": "4 à 6 cm",
            "visserie": "Vis Inox 5x60mm",
            "densite_lambourdes": "simple",
        },
    },
    "terrasse2_multi": {
        "desc": "Multi-config — 2 terrasses (10m² Vert + 20m² Marron) au même panier",
        "func": "terrasse",
        "params": {
            "essence": "PIN 27mm Autoclave Vert",
            "longueur": "3.6",
            "quantite": 10,
            "lambourdes": "Pin autoclave Vert 45x70",
            "lambourdes_longueur": "3.6",
            "plots": "2 à 4 cm",
            "visserie": "Vis Inox 5x60mm",
            "configurations_supplementaires": json.dumps([
                {
                    "essence": "PIN 27mm Autoclave Marron",
                    "longueur": "4.2",
                    "quantite": 20,
                    "lambourdes": "Pin autoclave Vert 45x70",
                    "lambourdes_longueur": "4.2",
                    "plots": "4 à 6 cm",
                    "visserie": "Vis Inox 5x60mm",
                }
            ]),
        },
    },
    "terrasse3_detail": {
        "desc": "Terrasse au détail — Cumaru lames + lambourdes Niove + plots",
        "func": "terrasse_detail",
        "params": {
            # ⚠ Ces IDs seront récupérés dynamiquement via rechercher_produits_detail
            # Pour le test, on utilise des valeurs connues — à adapter si les IDs changent
            "produits": "DYNAMIC",  # Sera remplacé dynamiquement
        },
    },
}


# ════════════════════════════════════════════════════════
# CLÔTURE — 2 tests (classique + moderne multi-config)
# ════════════════════════════════════════════════════════

CLOTURE_TESTS = {
    "cloture1": {
        "desc": "Clôture classique 10m H=1,9m — bardage 27x130 + plots béton",
        "func": "cloture",
        "params": {
            "modele": "classique",
            "longeur": "10",
            "hauteur": "1-9",
            "bardage": "27x130",
            "fixation_sol": "plots-beton",
            "type_poteaux": "90x90-h",
            "longueur_lames": "2-m",
        },
    },
    "cloture2_multi": {
        "desc": "Multi-config — Clôture moderne 20m + classique 10m au même panier",
        "func": "cloture",
        "params": {
            "modele": "moderne",
            "longeur": "20",
            "hauteur": "1-9",
            "bardage": "21x145",
            "fixation_sol": "plots-beton",
            "sens_bardage": "vertical",
            "recto_verso": "non",
            "configurations_supplementaires": json.dumps([
                {
                    "modele": "classique",
                    "longeur": "10",
                    "hauteur": "1-9",
                    "bardage": "27x130",
                    "fixation_sol": "plots-beton",
                    "type_poteaux": "90x90-h",
                    "longueur_lames": "2-m",
                }
            ]),
        },
    },
}


# ════════════════════════════════════════════════════════
# STUDIO — 4 tests
# ════════════════════════════════════════════════════════

STUDIO_TESTS = {
    "studio1": {
        "desc": "Studio basique 3,3x2,4 — 1 porte PVC, config minimale",
        "func": "studio",
        "params": {
            "largeur": "3,3", "profondeur": "2,4",
            "menuiseries": [
                {"type": "PORTE VITREE", "materiau": "PVC", "mur": "MUR DE FACE", "position": "auto"},
            ],
        },
    },
    "studio2": {
        "desc": "Studio 5,5x3,5 — plancher standard, bardage Brun, 2 menuiseries PVC",
        "func": "studio",
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
        "func": "studio",
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
        "desc": "Studio 8,8x5,7 — RE2020, rehausse, bardage Vert, terrasse, 3 menuiseries mixtes",
        "func": "studio",
        "params": {
            "largeur": "8,8", "profondeur": "5,7",
            "menuiseries": [
                {"type": "PORTE DOUBLE VITREE", "materiau": "ALU", "mur": "MUR DE FACE", "position": "centre"},
                {"type": "FENETRE SIMPLE", "materiau": "PVC", "mur": "MUR DE GAUCHE", "position": "auto"},
                {"type": "FENETRE SIMPLE", "materiau": "PVC", "mur": "MUR DE DROITE", "position": "auto"},
            ],
            "bardage_exterieur": "Vert",
            "isolation": "100 mm (RE2020)",
            "rehausse": True,
            "plancher": "Plancher porteur",
            "terrasse": "2 m (22 m2)",
        },
    },
}


# ════════════════════════════════════════════════════════
# ABRI — 4 tests
# ════════════════════════════════════════════════════════

ABRI_TESTS = {
    "abri1": {
        "desc": "Abri basique 3,45M x 2,15m — 1 porte vitrée Face 1",
        "func": "abri",
        "params": {
            "largeur": "3,45M", "profondeur": "2,15m",
            "ouvertures": [
                {"type": "Porte Vitrée", "face": "Face 1", "position": "Centre"},
            ],
        },
    },
    "abri2": {
        "desc": "Abri 5,50M x 3,45m — 2 ouvertures + plancher",
        "func": "abri",
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
        "func": "abri",
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
        "func": "abri",
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


# ════════════════════════════════════════════════════════
# RUNNER
# ════════════════════════════════════════════════════════

ALL_TESTS = {}
ALL_TESTS.update(PERGOLA_TESTS)
ALL_TESTS.update(TERRASSE_TESTS)
ALL_TESTS.update(CLOTURE_TESTS)
ALL_TESTS.update(STUDIO_TESTS)
ALL_TESTS.update(ABRI_TESTS)


async def _resolve_terrasse_detail_products():
    """Récupère les IDs produits terrasse au détail via l'API WooCommerce."""
    import urllib.request
    base = "https://terrasseenbois.fr"
    endpoint = f"{base}/wp-json/wc/store/v1/products"

    def fetch(search):
        url = f"{endpoint}?per_page=5&search={urllib.parse.quote(search)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())

    import re
    def strip_html(s):
        return re.sub(r'<[^>]+>', '', s)

    lame = None
    for p in fetch("cumaru"):
        name = strip_html(p["name"]).lower()
        if "cumaru" in name and "lame" in name:
            lame = p
            break

    lamb = None
    for p in fetch("lambourde"):
        name = strip_html(p["name"]).lower()
        if "niove" in name or "lambourde" in name:
            lamb = p
            break

    plot = None
    for p in fetch("plot"):
        name = strip_html(p["name"]).lower()
        if "plot" in name:
            plot = p
            break

    if not lame or not lamb or not plot:
        print(f"  ⚠ Produits non trouvés : lame={lame is not None}, lamb={lamb is not None}, plot={plot is not None}")
        return None

    produits = []
    for prod, qty, desc in [(lame, 30, "30 lames Cumaru"), (lamb, 15, "15 lambourdes Niove"), (plot, 50, "50 plots")]:
        slug = prod.get("slug", "")
        url = f"{base}/produit/{slug}/"
        var_id = 0
        attr_selects = {}
        if prod.get("variations", []):
            var = prod["variations"][0]
            var_id = var.get("id", 0)
            for a in var.get("attributes", []):
                attr_selects[f"attribute_{a['name']}"] = a["value"]
        produits.append({
            "url": url,
            "variation_id": var_id,
            "quantite": qty,
            "attribut_selects": attr_selects,
            "description": desc,
        })

    return produits


async def run_test(test_id: str):
    """Lance un test complet (config → panier → PDF)."""
    test = ALL_TESTS[test_id]
    func_type = test["func"]
    params = {**test["params"], **TEST_CLIENT}

    print(f"\n{'='*70}")
    print(f"  TEST {test_id.upper()} — {test['desc']}")
    print(f"{'='*70}")

    start = time.time()
    try:
        if func_type == "studio":
            filepath = await generer_devis_studio(**params)
        elif func_type == "abri":
            filepath = await generer_devis_abri(**params)
        elif func_type == "pergola":
            filepath, *_ = await generer_devis_pergola(**params)
        elif func_type == "terrasse":
            filepath, *_ = await generer_devis_terrasse(**params)
        elif func_type == "terrasse_detail":
            # Résoudre les produits dynamiquement
            if params.get("produits") == "DYNAMIC":
                print("  ➜ Résolution dynamique des produits terrasse au détail...")
                produits = await _resolve_terrasse_detail_products()
                if not produits:
                    raise RuntimeError("Impossible de résoudre les produits terrasse au détail via API")
                params["produits"] = produits
            filepath, *_ = await generer_devis_terrasse_detail(**params)
        elif func_type == "cloture":
            filepath, *_ = await generer_devis_cloture(**params)
        else:
            raise ValueError(f"Type de test inconnu : {func_type}")

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
        print("Usage: python3 test_complet_5sites.py <test_id>")
        print()
        print("  Tests pergola:  pergola1, pergola2, pergola3_multi")
        print("  Tests terrasse: terrasse1, terrasse2_multi, terrasse3_detail")
        print("  Tests clôture:  cloture1, cloture2_multi")
        print("  Tests studio:   studio1, studio2, studio3, studio4")
        print("  Tests abri:     abri1, abri2, abri3, abri4")
        print()
        print("  Groupes:        all, all-pergola, all-terrasse, all-cloture, all-studio, all-abri")
        sys.exit(1)

    test_id = sys.argv[1].lower()

    group_map = {
        "all": list(ALL_TESTS.keys()),
        "all-pergola": [k for k in ALL_TESTS if k.startswith("pergola")],
        "all-terrasse": [k for k in ALL_TESTS if k.startswith("terrasse")],
        "all-cloture": [k for k in ALL_TESTS if k.startswith("cloture")],
        "all-studio": [k for k in ALL_TESTS if k.startswith("studio")],
        "all-abri": [k for k in ALL_TESTS if k.startswith("abri")],
    }
    tests = group_map.get(test_id, [test_id])

    results = {}
    for tid in tests:
        if tid not in ALL_TESTS:
            print(f"  ⚠ Test inconnu : {tid}")
            continue
        ok = await run_test(tid)
        results[tid] = ok

    # Résumé
    print(f"\n{'='*70}")
    print(f"  RÉSUMÉ DES TESTS")
    print(f"{'='*70}")
    for tid, ok in results.items():
        status = "✅" if ok else "❌"
        desc = ALL_TESTS[tid]["desc"]
        print(f"  {status} {tid:25s} — {desc}")
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    print(f"\n  {passed}/{total} réussis")


if __name__ == "__main__":
    asyncio.run(main())
