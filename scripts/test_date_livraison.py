#!/usr/bin/env python3
"""Test de récupération de la date de livraison estimée sur les 5 sites du groupe.

Ajoute un produit simple au panier de chaque site, puis scrape la date de livraison.
Usage : python3 scripts/test_date_livraison.py [site1 site2 ...]
        python3 scripts/test_date_livraison.py          # tous les sites
        python3 scripts/test_date_livraison.py abri pergola
"""

import asyncio
import sys
import os
import time

sys.path.insert(0, os.path.dirname(__file__))

from playwright.async_api import async_playwright
from generateur_devis_3sites import _traiter_panier, _fermer_popups

# ── Configuration par site ──────────────────────────────────────────────────

SITES = {
    "abri": {
        "name": "Abri Français",
        "url": "https://www.xn--abri-franais-sdb.fr",
        "panier_path": "/votre-panier/",
        # Produit simple à ajouter rapidement (abri basique)
        "add_to_cart_url": "https://www.xn--abri-franais-sdb.fr/panier/?add-to-cart=20575",
    },
    "studio": {
        "name": "Studio Français",
        "url": "https://xn--studio-franais-qjb.fr",
        "panier_path": "/panier/",
        "add_to_cart_url": "https://xn--studio-franais-qjb.fr/panier/?add-to-cart=5766",
    },
    "pergola": {
        "name": "Ma Pergola Bois",
        "url": "https://www.mapergolabois.fr",
        "panier_path": "/panier/",
        "add_to_cart_url": "https://www.mapergolabois.fr/panier/?add-to-cart=16046",
    },
    "terrasse": {
        "name": "Terrasse en Bois",
        "url": "https://www.terrasseenbois.fr",
        "panier_path": "/panier/",
        "add_to_cart_url": "https://www.terrasseenbois.fr/panier/?add-to-cart=57595",
    },
    "cloture": {
        "name": "Clôture Bois",
        "url": "https://cloturebois.fr",
        "panier_path": "/panier/",
        "add_to_cart_url": "https://cloturebois.fr/panier/?add-to-cart=18393",
    },
}


async def test_date_livraison(site_key: str) -> dict:
    """Teste la récupération de la date de livraison pour un site."""
    site = SITES[site_key]
    result = {"site": site_key, "name": site["name"], "date": "", "error": ""}

    print(f"\n{'─'*50}")
    print(f"  {site['name']} ({site_key})")
    print(f"{'─'*50}")

    start = time.time()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="fr-FR",
        )
        page = await context.new_page()

        try:
            # 1. Ajouter un produit au panier via URL directe
            print(f"  ➜ Ajout produit au panier...")
            await page.goto(site["add_to_cart_url"], wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)
            await _fermer_popups(page)

            # 2. Scraper la date via _traiter_panier
            print(f"  ➜ Scraping date de livraison...")
            date_livraison = await _traiter_panier(
                page, site["url"],
                code_promo="", mode_livraison="",
                panier_path=site["panier_path"],
            )

            elapsed = time.time() - start
            if date_livraison:
                print(f"  ✅ Date trouvée : {date_livraison} ({elapsed:.1f}s)")
                result["date"] = date_livraison
            else:
                print(f"  ⚠ Aucune date trouvée ({elapsed:.1f}s)")
                result["error"] = "Aucune date trouvée"

        except Exception as e:
            elapsed = time.time() - start
            print(f"  ❌ Erreur : {e} ({elapsed:.1f}s)")
            result["error"] = str(e)
        finally:
            await browser.close()

    return result


async def main():
    sites_to_test = sys.argv[1:] if len(sys.argv) > 1 else list(SITES.keys())

    # Valider les sites demandés
    for s in sites_to_test:
        if s not in SITES:
            print(f"❌ Site inconnu: {s}. Disponibles: {', '.join(SITES.keys())}")
            sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  TEST DATE DE LIVRAISON — {len(sites_to_test)} site(s)")
    print(f"{'='*60}")

    results = []
    for site_key in sites_to_test:
        result = await test_date_livraison(site_key)
        results.append(result)

    # Résumé
    print(f"\n{'='*60}")
    print(f"  RÉSUMÉ")
    print(f"{'='*60}")
    for r in results:
        if r["date"]:
            print(f"  ✅ {r['name']:25s} → {r['date']}")
        elif r["error"]:
            print(f"  ❌ {r['name']:25s} → {r['error']}")
        else:
            print(f"  ⚠ {r['name']:25s} → Pas de date")

    ok = sum(1 for r in results if r["date"])
    print(f"\n  {ok}/{len(results)} sites avec date de livraison")


if __name__ == "__main__":
    asyncio.run(main())
