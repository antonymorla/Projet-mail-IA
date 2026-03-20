#!/usr/bin/env python3
"""
Test complet du configurateur studio — teste chaque option une par une.

MODE 1 — Tests en ligne (sur machine avec accès au site) :
    python3 scripts/test_studio_configurator.py online [test|all|list]

MODE 2 — Tests unitaires de la logique Python (sans navigateur, sans réseau) :
    python3 scripts/test_studio_configurator.py unit

Tests en ligne disponibles :
    base           — Config minimale (4,4×3,5, bardage Gris, isolation 60mm)
    bardage-brun   — Bardage extérieur Brun
    bardage-noir   — Bardage extérieur Noir
    isolation-re   — Isolation RE2020
    rehausse       — Rehausse OUI
    bardage-int    — Bardage intérieur Panneaux bois massif
    plancher-std   — Plancher standard (isolation 60mm)
    plancher-re    — Plancher RE2020 (isolation RE2020)
    plancher-port  — Plancher porteur (isolation 60mm)
    finition       — Finition plancher OUI
    terrasse       — Terrasse 2m (11m2)
    pergola        — Pergola 4x2m (8m2)
    menu-pvc       — Menuiserie PORTE VITREE PVC
    menu-alu       — Menuiserie BAIE VITREE ALU
    menu-double    — 2 menuiseries sur murs différents
    full           — Config complète (toutes options)
"""

import asyncio
import sys
import os
import time
import traceback

# Ajouter le répertoire scripts au path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))

from generateur_devis_auto import GenerateurDevis, ConfigStudio, SITES


# ═══════════════════════════════════════════════════════════════
# TESTS UNITAIRES (sans navigateur, sans réseau)
# ═══════════════════════════════════════════════════════════════

def run_unit_tests():
    """Teste la logique Python : dataclass, validation, mapping dimensions."""
    results = []

    def check(name, condition, detail=""):
        status = "OK" if condition else "FAIL"
        results.append((name, status, detail))
        icon = "✅" if condition else "❌"
        print(f"  {icon} {name}{' — ' + detail if detail else ''}")

    print("\n" + "="*70)
    print("  TESTS UNITAIRES — Logique Python (sans navigateur)")
    print("="*70)

    # --- Test 1: ConfigStudio defaults ---
    print("\n  [ConfigStudio — valeurs par défaut]")
    c = ConfigStudio(largeur="4,4", profondeur="3,5")
    check("bardage_exterieur default", c.bardage_exterieur == "Gris", f"got '{c.bardage_exterieur}'")
    check("isolation default", c.isolation == "60mm", f"got '{c.isolation}'")
    check("rehausse default", c.rehausse == False)
    check("bardage_interieur default", c.bardage_interieur == "OSB", f"got '{c.bardage_interieur}'")
    check("plancher default", c.plancher == "Sans plancher", f"got '{c.plancher}'")
    check("finition_plancher default", c.finition_plancher == False)
    check("terrasse default", c.terrasse == "")
    check("pergola default", c.pergola == "")
    check("menuiseries default", c.menuiseries == [])

    # --- Test 2: ConfigStudio custom values ---
    print("\n  [ConfigStudio — valeurs custom]")
    c2 = ConfigStudio(
        largeur="5,5", profondeur="4,6",
        bardage_exterieur="Brun",
        isolation="100 mm (RE2020)",
        rehausse=True,
        bardage_interieur="Panneaux bois massif (3 plis épicéa)",
        plancher="Plancher porteur",
        finition_plancher=True,
        terrasse="2m (11m2)",
        pergola="4x2m (8m2)",
        menuiseries=[{"type": "PORTE VITREE", "materiau": "PVC", "mur": "MUR DE FACE"}],
    )
    check("bardage custom", c2.bardage_exterieur == "Brun")
    check("isolation RE2020", c2.isolation == "100 mm (RE2020)")
    check("rehausse True", c2.rehausse == True)
    check("plancher porteur", c2.plancher == "Plancher porteur")
    check("finition True", c2.finition_plancher == True)
    check("terrasse", c2.terrasse == "2m (11m2)")
    check("pergola", c2.pergola == "4x2m (8m2)")
    check("menuiseries count", len(c2.menuiseries) == 1)

    # --- Test 3: Dimensions mapping ---
    print("\n  [Dimensions — mapping URL]")
    dim_map = SITES["studio"]["dimensions"]
    check("28 dimensions", len(dim_map) == 28, f"got {len(dim_map)}")
    check("4,4x3,5 exists", "4,4x3,5" in dim_map, f"url={dim_map.get('4,4x3,5')}")
    check("5,5x3,5 exists", "5,5x3,5" in dim_map, f"url={dim_map.get('5,5x3,5')}")
    check("8,8x5,7 exists", "8,8x5,7" in dim_map, f"url={dim_map.get('8,8x5,7')}")
    check("2,2x2,4 exists", "2,2x2,4" in dim_map, f"url={dim_map.get('2,2x2,4')}")
    check("invalid not exists", "9,9x9,9" not in dim_map)

    # --- Test 4: Plancher values ---
    print("\n  [Plancher — valeurs valides]")
    valid_planchers = ["Sans plancher", "Plancher standard", "Plancher RE2020", "Plancher porteur"]
    for p in valid_planchers:
        c = ConfigStudio(largeur="4,4", profondeur="3,5", plancher=p)
        check(f"plancher '{p}'", c.plancher == p)

    # --- Test 5: Plancher logic (skip if plancher == Sans plancher) ---
    print("\n  [Plancher — logique de skip]")
    c_sans = ConfigStudio(largeur="4,4", profondeur="3,5", plancher="Sans plancher")
    c_std = ConfigStudio(largeur="4,4", profondeur="3,5", plancher="Plancher standard")
    check("Sans plancher skips select", not (c_sans.plancher and c_sans.plancher != "Sans plancher"))
    check("Plancher standard triggers select", bool(c_std.plancher and c_std.plancher != "Sans plancher"))

    # --- Test 6: MCP normalisation (import and test if available) ---
    print("\n  [MCP — normalisation plancher]")
    try:
        from mcp_server_devis import _normaliser_plancher_studio
        # Test alias mapping
        check("alias 'Plancher isolé simple' → 'Plancher standard'",
              _normaliser_plancher_studio("Plancher isolé simple", "60mm") == "Plancher standard")
        check("alias 'Plancher renforcé' → 'Plancher porteur'",
              _normaliser_plancher_studio("Plancher renforcé", "60mm") == "Plancher porteur")
        # Test auto-correction
        check("RE2020 with 60mm → 'Plancher standard'",
              _normaliser_plancher_studio("Plancher RE2020", "60mm") == "Plancher standard")
        check("standard with RE2020 → 'Plancher RE2020'",
              _normaliser_plancher_studio("Plancher standard", "100 mm (RE2020)") == "Plancher RE2020")
        # Test pass-through
        check("'Plancher porteur' unchanged",
              _normaliser_plancher_studio("Plancher porteur", "60mm") == "Plancher porteur")
        check("'Sans plancher' unchanged",
              _normaliser_plancher_studio("Sans plancher", "60mm") == "Sans plancher")
        check("empty unchanged",
              _normaliser_plancher_studio("", "60mm") == "")
    except ImportError:
        print("  ⚠ mcp_server_devis non importable (dépendances MCP manquantes) — tests MCP skippés")
    except Exception as e:
        print(f"  ⚠ Erreur import MCP: {e}")

    # --- Test 7: Bardage values ---
    print("\n  [Bardage — valeurs]")
    for b in ["Gris", "Brun", "Noir"]:
        c = ConfigStudio(largeur="4,4", profondeur="3,5", bardage_exterieur=b)
        check(f"bardage '{b}'", c.bardage_exterieur == b)

    # --- Test 8: Menuiserie types ---
    print("\n  [Menuiseries — types et matériaux]")
    menu_types = ["PORTE VITREE", "FENETRE SIMPLE", "FENETRE DOUBLE", "BAIE VITREE", "PORTE DOUBLE VITREE"]
    for mt in menu_types:
        mat = "ALU" if mt in ("BAIE VITREE", "PORTE DOUBLE VITREE") else "PVC"
        c = ConfigStudio(largeur="4,4", profondeur="3,5",
                        menuiseries=[{"type": mt, "materiau": mat, "mur": "MUR DE FACE"}])
        check(f"menuiserie '{mt}' ({mat})", len(c.menuiseries) == 1)

    # --- Test 9: Terrasse/Pergola values ---
    print("\n  [Terrasse et Pergola — valeurs]")
    for t in ["", "2m (11m2)", "4m (22m2)"]:
        c = ConfigStudio(largeur="4,4", profondeur="3,5", terrasse=t)
        check(f"terrasse '{t or '(vide)'}'", c.terrasse == t)
    for p in ["", "4x2m (8m2)", "4x4m (16m2)"]:
        c = ConfigStudio(largeur="4,4", profondeur="3,5", pergola=p)
        check(f"pergola '{p or '(vide)'}'", c.pergola == p)

    # --- Résumé ---
    ok = sum(1 for _, s, _ in results if s == "OK")
    fail = sum(1 for _, s, _ in results if s == "FAIL")
    print(f"\n{'='*70}")
    print(f"  RÉSUMÉ: {ok} OK / {fail} FAIL sur {len(results)} tests")
    print(f"{'='*70}\n")

    return fail == 0


# ═══════════════════════════════════════════════════════════════
# TESTS EN LIGNE (avec navigateur)
# ═══════════════════════════════════════════════════════════════

ONLINE_TESTS = {
    "base": {
        "desc": "Config minimale (4,4×3,5, Gris, 60mm, OSB, sans plancher)",
        "config": ConfigStudio(
            largeur="4,4",
            profondeur="3,5",
        ),
    },
    "bardage-brun": {
        "desc": "Bardage extérieur Brun",
        "config": ConfigStudio(
            largeur="4,4",
            profondeur="3,5",
            bardage_exterieur="Brun",
        ),
    },
    "bardage-noir": {
        "desc": "Bardage extérieur Noir",
        "config": ConfigStudio(
            largeur="4,4",
            profondeur="3,5",
            bardage_exterieur="Noir",
        ),
    },
    "isolation-re": {
        "desc": "Isolation RE2020",
        "config": ConfigStudio(
            largeur="4,4",
            profondeur="3,5",
            isolation="100 mm (RE2020)",
        ),
    },
    "rehausse": {
        "desc": "Rehausse OUI (hauteur 3,20m)",
        "config": ConfigStudio(
            largeur="4,4",
            profondeur="3,5",
            rehausse=True,
        ),
    },
    "bardage-int": {
        "desc": "Bardage intérieur Panneaux bois massif (3 plis épicéa)",
        "config": ConfigStudio(
            largeur="4,4",
            profondeur="3,5",
            bardage_interieur="Panneaux bois massif (3 plis épicéa)",
        ),
    },
    "plancher-std": {
        "desc": "Plancher standard (isolation 60mm)",
        "config": ConfigStudio(
            largeur="4,4",
            profondeur="3,5",
            isolation="60mm",
            plancher="Plancher standard",
        ),
    },
    "plancher-re": {
        "desc": "Plancher RE2020 (isolation RE2020)",
        "config": ConfigStudio(
            largeur="4,4",
            profondeur="3,5",
            isolation="100 mm (RE2020)",
            plancher="Plancher RE2020",
        ),
    },
    "plancher-port": {
        "desc": "Plancher porteur (isolation 60mm)",
        "config": ConfigStudio(
            largeur="4,4",
            profondeur="3,5",
            isolation="60mm",
            plancher="Plancher porteur",
        ),
    },
    "finition": {
        "desc": "Finition plancher OUI",
        "config": ConfigStudio(
            largeur="4,4",
            profondeur="3,5",
            finition_plancher=True,
        ),
    },
    "terrasse": {
        "desc": "Terrasse 2m (11m2)",
        "config": ConfigStudio(
            largeur="4,4",
            profondeur="3,5",
            terrasse="2m (11m2)",
        ),
    },
    "pergola": {
        "desc": "Pergola 4x2m (8m2)",
        "config": ConfigStudio(
            largeur="4,4",
            profondeur="3,5",
            pergola="4x2m (8m2)",
        ),
    },
    "menu-pvc": {
        "desc": "Menuiserie PORTE VITREE PVC sur MUR DE FACE",
        "config": ConfigStudio(
            largeur="4,4",
            profondeur="3,5",
            menuiseries=[
                {"type": "PORTE VITREE", "materiau": "PVC", "mur": "MUR DE FACE", "position": "gauche"},
            ],
        ),
    },
    "menu-alu": {
        "desc": "Menuiserie BAIE VITREE ALU sur MUR DE FACE",
        "config": ConfigStudio(
            largeur="4,4",
            profondeur="3,5",
            menuiseries=[
                {"type": "BAIE VITREE", "materiau": "ALU", "mur": "MUR DE FACE", "position": "gauche"},
            ],
        ),
    },
    "menu-double": {
        "desc": "2 menuiseries : PORTE VITREE PVC face + FENETRE SIMPLE PVC droite",
        "config": ConfigStudio(
            largeur="5,5",
            profondeur="3,5",
            menuiseries=[
                {"type": "PORTE VITREE", "materiau": "PVC", "mur": "MUR DE FACE", "position": "gauche"},
                {"type": "FENETRE SIMPLE", "materiau": "PVC", "mur": "MUR DE DROITE", "position": "centre"},
            ],
        ),
    },
    "full": {
        "desc": "Config complète (Brun, RE2020, rehausse, bois massif, plancher porteur, finition, terrasse, pergola, 2 menuiseries)",
        "config": ConfigStudio(
            largeur="5,5",
            profondeur="3,5",
            bardage_exterieur="Brun",
            isolation="100 mm (RE2020)",
            rehausse=True,
            bardage_interieur="Panneaux bois massif (3 plis épicéa)",
            plancher="Plancher porteur",
            finition_plancher=True,
            terrasse="2m (11m2)",
            pergola="4x2m (8m2)",
            menuiseries=[
                {"type": "PORTE VITREE", "materiau": "PVC", "mur": "MUR DE FACE", "position": "gauche"},
                {"type": "FENETRE SIMPLE", "materiau": "PVC", "mur": "MUR DE DROITE", "position": "centre"},
            ],
        ),
    },
}


async def run_online_test(test_name: str, test_def: dict) -> dict:
    """Exécute un test unique : configure le studio et vérifie le WPC."""
    config = test_def["config"]
    desc = test_def["desc"]
    print(f"\n{'='*70}")
    print(f"  TEST: {test_name}")
    print(f"  {desc}")
    print(f"{'='*70}")

    gen = GenerateurDevis(site="studio", headless=True)
    result = {"name": test_name, "desc": desc, "status": "FAIL", "prix": None, "error": None, "uids": 0, "duration": 0}
    start = time.time()

    try:
        await gen.start()
        prix = await gen.configurer_studio(config)
        result["prix"] = prix

        # Vérifier la config WPC
        await gen._verifier_config_wpc(label=test_name)

        # Lire le wpc-encoded pour compter les UIDs
        wpc_data = await gen.page.evaluate("""
            () => {
                const form = document.querySelector('form.cart');
                const enc = form ? form.querySelector('[name="wpc-encoded"]') : null;
                if (!enc || !enc.value) return {uids: 0, raw: ''};
                const decoded = atob(enc.value);
                const uids = decoded.split(',').map(s => s.trim()).filter(Boolean);
                return {uids: uids.length, raw: decoded.substring(0, 200)};
            }
        """)
        result["uids"] = wpc_data.get("uids", 0)

        if result["uids"] > 0 and prix and "non trouvé" not in prix.lower():
            result["status"] = "OK"
        else:
            result["status"] = "WARN"
            if result["uids"] == 0:
                result["error"] = "wpc-encoded vide"

        print(f"\n  → Prix: {prix}")
        print(f"  → UIDs encodés: {result['uids']}")

    except Exception as e:
        result["error"] = str(e)
        result["status"] = "FAIL"
        print(f"\n  ❌ ERREUR: {e}")
        traceback.print_exc()
    finally:
        result["duration"] = time.time() - start
        try:
            await gen.stop()
        except Exception:
            pass

    return result


async def run_online_tests(test_names: list):
    """Exécute une série de tests en ligne séquentiellement."""
    results = []
    total_start = time.time()

    for name in test_names:
        if name not in ONLINE_TESTS:
            print(f"\n⚠ Test '{name}' inconnu — ignoré")
            continue
        result = await run_online_test(name, ONLINE_TESTS[name])
        results.append(result)
        await asyncio.sleep(2)

    # Résumé
    total_time = time.time() - total_start
    print(f"\n\n{'='*70}")
    print(f"  RÉSUMÉ DES TESTS EN LIGNE — {len(results)} tests en {total_time:.1f}s")
    print(f"{'='*70}")
    print(f"  {'Test':<20} {'Status':<8} {'Prix':<15} {'UIDs':<6} {'Durée':<8} {'Erreur'}")
    print(f"  {'-'*20} {'-'*8} {'-'*15} {'-'*6} {'-'*8} {'-'*30}")
    for r in results:
        status_icon = "✅" if r["status"] == "OK" else ("⚠" if r["status"] == "WARN" else "❌")
        prix_short = (r["prix"] or "N/A")[:14]
        err = (r["error"] or "")[:30]
        print(f"  {r['name']:<20} {status_icon} {r['status']:<5} {prix_short:<15} {r['uids']:<6} {r['duration']:<7.1f}s {err}")

    ok_count = sum(1 for r in results if r["status"] == "OK")
    warn_count = sum(1 for r in results if r["status"] == "WARN")
    fail_count = sum(1 for r in results if r["status"] == "FAIL")
    print(f"\n  Total: {ok_count} OK / {warn_count} WARN / {fail_count} FAIL")
    return results


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 test_studio_configurator.py unit              — Tests unitaires (sans réseau)")
        print("  python3 test_studio_configurator.py online [test|all] — Tests en ligne (navigateur)")
        print("  python3 test_studio_configurator.py online list       — Lister les tests en ligne")
        print(f"\nTests en ligne: {', '.join(ONLINE_TESTS.keys())}")
        sys.exit(1)

    mode = sys.argv[1]

    if mode == "unit":
        success = run_unit_tests()
        sys.exit(0 if success else 1)

    elif mode == "online":
        if len(sys.argv) < 3:
            print(f"Tests en ligne: {', '.join(ONLINE_TESTS.keys())}")
            sys.exit(1)
        arg = sys.argv[2]
        if arg == "list":
            print("Tests en ligne disponibles:")
            for name, t in ONLINE_TESTS.items():
                print(f"  {name:<20} {t['desc']}")
            sys.exit(0)
        if arg == "all":
            test_names = list(ONLINE_TESTS.keys())
        else:
            test_names = arg.split(",")
        asyncio.run(run_online_tests(test_names))

    else:
        print(f"Mode inconnu: {mode}. Utiliser 'unit' ou 'online'.")
        sys.exit(1)
