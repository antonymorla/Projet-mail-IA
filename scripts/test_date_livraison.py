#!/usr/bin/env python3
"""
Test diagnostic — vérifie la détection de date de livraison sur tous les sites.

Usage:
    python3 scripts/test_date_livraison.py              # teste les 5 sites
    python3 scripts/test_date_livraison.py terrasse      # teste un seul site
    python3 scripts/test_date_livraison.py terrasse --headless

Ce script :
1. Ajoute un produit au panier via sélection variation + clic bouton
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

# Config par site — URL produit + sélection variation
SITES = {
    "terrasse": {
        "name": "Terrasse en Bois",
        "url": "https://terrasseenbois.fr",
        "product_url": "https://www.terrasseenbois.fr/produit/choisissez-vos-plots-plastiques-reglables/",
        "select_variation": {
            # Sélecteur CSS du <select> → valeur à choisir
            # Essayer les 2 formats WooCommerce : id="pa_xxx" ou id="attribute_pa_xxx"
            "#pa_hauteur-de-plots,#attribute_pa_hauteur_de_plots": "2-a-4-cm",
        },
    },
    "pergola": {
        "name": "Ma Pergola Bois",
        "url": "https://mapergolabois.fr",
        "product_url": "https://www.mapergolabois.fr/produit/pergola-bois-en-kit/",
        "select_variation": {},  # Configurateur WAPF, pas de variation simple
    },
    "cloture": {
        "name": "Clôture Bois",
        "url": "https://cloturebois.fr",
        "product_url": None,
    },
    "abri": {
        "name": "Abri Français",
        "url": "https://www.xn--abri-franais-sdb.fr",
        "product_url": None,  # Configurateur WPC, pas de produit simple pour test
    },
    "studio": {
        "name": "Studio Français",
        "url": "https://xn--studio-franais-qjb.fr",
        "product_url": None,
    },
}


async def add_product_to_cart(page, product_url: str, select_variation: dict) -> bool:
    """Navigue vers un produit, sélectionne la variation, et clique Ajouter au panier."""
    print(f"  ➜ Navigation vers le produit : {product_url}")
    await page.goto(product_url, wait_until="load", timeout=30000)
    await page.wait_for_timeout(2000)
    await fermer_popups(page)

    # Sélectionner les variations (dropdowns)
    if select_variation:
        for selector_combo, value in select_variation.items():
            # selector_combo peut contenir plusieurs sélecteurs séparés par virgule
            selectors = [s.strip() for s in selector_combo.split(",")]
            print(f"  ➜ Sélection variation {selectors} = {value}")
            found = False
            for selector in selectors:
                try:
                    select_el = page.locator(selector)
                    if await select_el.count() > 0:
                        await select_el.select_option(value=value)
                        await page.wait_for_timeout(1500)
                        print(f"    ✓ Variation sélectionnée via {selector}")
                        found = True
                        break
                except Exception:
                    pass
            if not found:
                print(f"    ⚠ Aucun sélecteur trouvé — dump des <select> disponibles :")
                selects = await page.evaluate("""
                    () => {
                        return Array.from(document.querySelectorAll('select')).map(s =>
                            '#' + s.id + ' / name=' + s.name + ' → [' +
                            Array.from(s.options).map(o => o.value).join(', ') + ']'
                        );
                    }
                """)
                for s in selects[:8]:
                    print(f"      {s}")

    # Cliquer sur Ajouter au panier
    await page.wait_for_timeout(1000)
    btn = page.locator('button.single_add_to_cart_button').first
    if await btn.count() > 0:
        # Vérifier que le bouton n'est pas désactivé
        is_disabled = await btn.is_disabled()
        if is_disabled:
            print("    ⚠ Bouton désactivé — attente 3s...")
            await page.wait_for_timeout(3000)
            is_disabled = await btn.is_disabled()

        if not is_disabled:
            await btn.scroll_into_view_if_needed()
            await btn.click()
            await page.wait_for_timeout(3000)

            # Vérifier l'ajout
            try:
                await page.wait_for_selector(
                    '.woocommerce-message, .added_to_cart, .woocommerce-notices-wrapper a',
                    timeout=5000,
                )
                print("  ✅ Produit ajouté au panier")
                return True
            except Exception:
                # Vérifier quand même si on est redirigé vers le panier
                if "/panier" in page.url or "/cart" in page.url:
                    print("  ✅ Redirigé vers le panier (produit probablement ajouté)")
                    return True
                print("  ⚠ Pas de confirmation d'ajout (peut-être ajouté quand même)")
                return True  # On continue quand même
        else:
            print("  ❌ Bouton toujours désactivé — variation non sélectionnée correctement")
            return False
    else:
        print("  ❌ Bouton 'Ajouter au panier' non trouvé")
        # Dump les boutons disponibles
        buttons = await page.evaluate("""
            () => Array.from(document.querySelectorAll('button, input[type=submit]'))
                .map(b => b.tagName + '.' + b.className.substring(0,60) + ' → ' + (b.textContent || b.value || '').trim().substring(0,50))
                .slice(0, 10)
        """)
        for b in buttons:
            print(f"    Trouvé : {b}")
        return False


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
        # Ajouter un produit au panier
        if site_info.get("product_url"):
            added = await add_product_to_cart(
                page,
                site_info["product_url"],
                site_info.get("select_variation", {}),
            )
            if not added:
                print("  ⚠ Impossible d'ajouter un produit — le panier sera vide")
        else:
            print("  ⚠ Pas de produit de test pour ce site — panier vide")

        # Appeler _traiter_panier
        from generateur_devis_3sites import _traiter_panier

        print(f"\n  ➜ Appel _traiter_panier()...")
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
                for line in diag_lines[:30]:
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
    # Filtrer les arguments (ignorer les flags --headless)
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    target = args[0] if args else None

    async with async_playwright() as p:
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
