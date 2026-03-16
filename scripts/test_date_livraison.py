#!/usr/bin/env python3
"""
Test diagnostic — vérifie la détection de date de livraison sur tous les sites.

Usage:
    python3 scripts/test_date_livraison.py              # teste les 5 sites
    python3 scripts/test_date_livraison.py terrasse      # teste un seul site

Ce script :
1. Ajoute un produit simple au panier de chaque site
2. Appelle _traiter_panier() pour scraper la date
3. Affiche le résultat + diagnostic si date non trouvée
"""

import asyncio
import sys
import os

# Ajouter le dossier scripts au path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from playwright.async_api import async_playwright
from utils_playwright import fermer_popups

# Config par site — URL produit simple + URL panier
SITES = {
    "terrasse": {
        "name": "Terrasse en Bois",
        "url": "https://terrasseenbois.fr",
        "add_to_cart_url": "https://www.terrasseenbois.fr/produit/plots-de-terrasse-reglables/?attribute_pa_hauteur-de-plots=2-a-4-cm",
    },
    "pergola": {
        "name": "Ma Pergola Bois",
        "url": "https://mapergolabois.fr",
        "add_to_cart_url": "https://www.mapergolabois.fr/produit/pied-de-poteau-reglable/?attribute_pa_type-de-pied-de-poteau=pied-de-poteau-reglable-12-a-18-cm",
    },
    "cloture": {
        "name": "Clôture Bois",
        "url": "https://cloturebois.fr",
        "add_to_cart_url": None,  # Pas de produit simple, on teste juste le panier
    },
    "abri": {
        "name": "Abri Français",
        "url": "https://www.xn--abri-franais-sdb.fr",
        "add_to_cart_url": None,  # Le panier est sur /votre-panier/
    },
    "studio": {
        "name": "Studio Français",
        "url": "https://xn--studio-franais-qjb.fr",
        "add_to_cart_url": None,
    },
}


async def test_site(site_key: str, site_info: dict, browser):
    """Teste la détection de date de livraison sur un site."""
    print(f"\n{'='*70}")
    print(f"  🔍 Test {site_info['name']} ({site_key})")
    print(f"{'='*70}")

    context = await browser.new_context(
        viewport={"width": 1400, "height": 900},
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    )
    page = await context.new_page()

    try:
        # Ajouter un produit au panier si disponible
        if site_info.get("add_to_cart_url"):
            print(f"  ➜ Ajout produit test...")
            try:
                await page.goto(site_info["add_to_cart_url"], wait_until="load", timeout=30000)
                await page.wait_for_timeout(2000)
                await fermer_popups(page)

                btn = page.locator('button.single_add_to_cart_button').first
                if await btn.count() > 0:
                    await btn.click()
                    await page.wait_for_timeout(3000)
                    print("  ✅ Produit ajouté au panier")
                else:
                    print("  ⚠ Bouton ajout panier non trouvé")
            except Exception as e:
                print(f"  ⚠ Erreur ajout produit : {e}")

        # Appeler _traiter_panier
        from generateur_devis_3sites import _traiter_panier

        print(f"  ➜ Appel _traiter_panier()...")
        date_livraison, diag_lines = await _traiter_panier(
            page=page,
            site_url=site_info["url"],
            code_promo="",
            mode_livraison="",
        )

        if date_livraison:
            print(f"\n  ✅ DATE TROUVÉE : {date_livraison}")
        else:
            print(f"\n  ❌ DATE NON TROUVÉE")
            if diag_lines:
                print(f"\n  📋 Diagnostic ({len(diag_lines)} lignes) :")
                for line in diag_lines[:25]:
                    print(f"    {line}")
            else:
                print("  (aucun diagnostic retourné)")

    except Exception as e:
        print(f"  ❌ Erreur : {e}")
        import traceback
        traceback.print_exc()
    finally:
        await context.close()


async def main():
    target = sys.argv[1] if len(sys.argv) > 1 else None

    async with async_playwright() as p:
        # headless=False pour voir le navigateur (debug)
        headless = "--headless" in sys.argv
        print(f"  Mode : {'headless' if headless else 'visible (navigateur affiché)'}")
        print(f"  Tip : ajouter --headless pour lancer sans navigateur\n")

        browser = await p.chromium.launch(headless=headless)

        if target and target in SITES:
            await test_site(target, SITES[target], browser)
        elif target and target not in SITES:
            print(f"  ❌ Site inconnu : {target}")
            print(f"  Sites disponibles : {', '.join(SITES.keys())}")
        else:
            for site_key, site_info in SITES.items():
                await test_site(site_key, site_info, browser)

        await browser.close()

    print(f"\n{'='*70}")
    print("  ✅ Test terminé")
    print(f"{'='*70}")


if __name__ == "__main__":
    asyncio.run(main())
