#!/usr/bin/env python3
"""
Test diagnostic — vérifie la détection de date de livraison sur tous les sites.

Usage:
    python3 scripts/test_date_livraison.py              # teste les 5 sites
    python3 scripts/test_date_livraison.py terrasse      # teste un seul site
    python3 scripts/test_date_livraison.py terrasse --headless
    python3 scripts/test_date_livraison.py --screenshot   # sauvegarde une capture du panier

Ce script :
1. Ajoute un produit au panier via API WooCommerce (add-to-cart) ou sélection variation
2. Appelle _traiter_panier() avec le bon chemin panier pour scraper la date
3. Affiche le résultat + diagnostic si date non trouvée
4. Optionnellement sauvegarde une capture d'écran du panier
"""

import asyncio
import sys
import os
import time

# Ajouter le dossier scripts au path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from playwright.async_api import async_playwright
from utils_playwright import fermer_popups

# Config par site — URL produit + méthode d'ajout au panier
SITES = {
    "abri": {
        "name": "Abri Français",
        "url": "https://www.xn--abri-franais-sdb.fr",
        "panier_path": "/votre-panier/",
        # Ajout via URL add-to-cart directe (planche 27x130 — produit simple avec variation)
        "add_to_cart_url": "https://www.xn--abri-franais-sdb.fr/?add-to-cart=46498&variation_id=53608&attribute_pa_longueur=4-2-m",
        "product_url": None,
        "select_variation": {},
    },
    "studio": {
        "name": "Studio Français",
        "url": "https://xn--studio-franais-qjb.fr",
        "panier_path": "/panier/",
        # Ajout via URL add-to-cart directe (cloison intérieure studio)
        "add_to_cart_url": "https://xn--studio-franais-qjb.fr/?add-to-cart=3227",
        "product_url": None,
        "select_variation": {},
    },
    "pergola": {
        "name": "Ma Pergola Bois",
        "url": "https://mapergolabois.fr",
        "panier_path": "/panier/",
        # Ajout via URL add-to-cart (bardage pergola)
        "add_to_cart_url": "https://www.mapergolabois.fr/?add-to-cart=1488",
        "product_url": None,
        "select_variation": {},
    },
    "terrasse": {
        "name": "Terrasse en Bois",
        "url": "https://terrasseenbois.fr",
        "panier_path": "/panier/",
        "add_to_cart_url": None,
        "product_url": "https://www.terrasseenbois.fr/produit/choisissez-vos-plots-plastiques-reglables/",
        "select_variation": {
            "#pa_hauteur-de-plots,#attribute_pa_hauteur_de_plots,#attribute_pa_hauteur-de-plots": "2-a-4-cm",
        },
    },
    "cloture": {
        "name": "Clôture Bois",
        "url": "https://cloturebois.fr",
        "panier_path": "/panier/",
        # Ajout via URL add-to-cart (pied galvanisé)
        "add_to_cart_url": "https://cloturebois.fr/?add-to-cart=879",
        "product_url": None,
        "select_variation": {},
    },
}


async def add_product_via_url(page, add_to_cart_url: str, site_url: str, panier_path: str) -> bool:
    """Ajoute un produit au panier via l'URL WooCommerce ?add-to-cart=ID."""
    print(f"  -> Ajout au panier via URL : {add_to_cart_url}")
    try:
        await page.goto(add_to_cart_url, wait_until="load", timeout=30000)
        await page.wait_for_timeout(3000)
        await fermer_popups(page)

        # Vérifier si on est redirigé vers le panier ou si un message de succès est affiché
        current_url = page.url
        if "/panier" in current_url or "/votre-panier" in current_url or "/cart" in current_url:
            print("  OK Redirigé vers le panier (produit ajouté)")
            return True

        # Vérifier message WooCommerce
        msg = page.locator('.woocommerce-message')
        if await msg.count() > 0:
            txt = await msg.first.text_content()
            print(f"  OK Message WC : {txt[:80]}")
            return True

        # Vérifier en navigant vers le panier
        panier_url = site_url.rstrip("/") + panier_path
        await page.goto(panier_url, wait_until="load", timeout=20000)
        await page.wait_for_timeout(2000)
        await fermer_popups(page)

        # Vérifier s'il y a des produits dans le panier
        has_items = await page.evaluate("""
            () => {
                const rows = document.querySelectorAll('.cart_item, .woocommerce-cart-form__cart-item, tr.cart-item');
                return rows.length > 0;
            }
        """)
        if has_items:
            print("  OK Produit trouvé dans le panier")
            return True

        print("  WARN Panier possiblement vide après ajout")
        return False
    except Exception as e:
        print(f"  ERREUR Ajout au panier : {e}")
        return False


async def add_product_via_form(page, product_url: str, select_variation: dict) -> bool:
    """Navigue vers un produit, sélectionne la variation, et clique Ajouter au panier."""
    print(f"  -> Navigation vers le produit : {product_url}")
    await page.goto(product_url, wait_until="load", timeout=30000)
    await page.wait_for_timeout(2000)
    await fermer_popups(page)

    # Sélectionner les variations (dropdowns)
    if select_variation:
        for selector_combo, value in select_variation.items():
            selectors = [s.strip() for s in selector_combo.split(",")]
            print(f"  -> Sélection variation {selectors} = {value}")
            found = False
            for selector in selectors:
                try:
                    select_el = page.locator(selector)
                    if await select_el.count() > 0:
                        await select_el.select_option(value=value)
                        await page.wait_for_timeout(1500)
                        print(f"    OK Variation sélectionnée via {selector}")
                        found = True
                        break
                except Exception:
                    pass
            if not found:
                print(f"    WARN Aucun sélecteur trouvé — dump des <select> disponibles :")
                selects = await page.evaluate("""
                    () => {
                        return Array.from(document.querySelectorAll('select')).map(s =>
                            '#' + s.id + ' / name=' + s.name + ' -> [' +
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
        is_disabled = await btn.is_disabled()
        if is_disabled:
            print("    WARN Bouton désactivé — attente 3s...")
            await page.wait_for_timeout(3000)
            is_disabled = await btn.is_disabled()

        if not is_disabled:
            await btn.scroll_into_view_if_needed()
            await btn.click()
            await page.wait_for_timeout(3000)

            try:
                await page.wait_for_selector(
                    '.woocommerce-message, .added_to_cart, .woocommerce-notices-wrapper a',
                    timeout=5000,
                )
                print("  OK Produit ajouté au panier")
                return True
            except Exception:
                if "/panier" in page.url or "/cart" in page.url:
                    print("  OK Redirigé vers le panier")
                    return True
                print("  WARN Pas de confirmation (on continue)")
                return True
        else:
            print("  ERREUR Bouton toujours désactivé")
            return False
    else:
        print("  ERREUR Bouton 'Ajouter au panier' non trouvé")
        return False


async def test_site(site_key: str, site_info: dict, browser, save_screenshot: bool = False):
    """Teste la détection de date de livraison sur un site."""
    print(f"\n{'='*70}")
    print(f"  TEST {site_info['name']} ({site_key})")
    print(f"  Panier : {site_info['panier_path']}")
    print(f"{'='*70}")

    context = await browser.new_context(
        viewport={"width": 1400, "height": 900},
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    )
    page = await context.new_page()

    try:
        # 1. Ajouter un produit au panier
        added = False
        if site_info.get("add_to_cart_url"):
            added = await add_product_via_url(
                page,
                site_info["add_to_cart_url"],
                site_info["url"],
                site_info["panier_path"],
            )
        elif site_info.get("product_url"):
            added = await add_product_via_form(
                page,
                site_info["product_url"],
                site_info.get("select_variation", {}),
            )
        else:
            print("  WARN Pas de produit de test pour ce site — panier vide")

        if not added:
            print("  WARN Impossible d'ajouter un produit — test avec panier vide")

        # 2. Appeler _traiter_panier avec le bon chemin
        from generateur_devis_3sites import _traiter_panier

        panier_path = site_info.get("panier_path", "/panier/")
        print(f"\n  -> Appel _traiter_panier(panier_path='{panier_path}')...")
        date_livraison, diag_lines = await _traiter_panier(
            page=page,
            site_url=site_info["url"],
            code_promo="",
            mode_livraison="",
            panier_path=panier_path,
        )

        # 3. Sauvegarder une capture d'écran du panier si demandé
        if save_screenshot:
            screenshot_dir = os.path.join(os.path.dirname(__file__), "..", "screenshots")
            os.makedirs(screenshot_dir, exist_ok=True)
            screenshot_path = os.path.join(screenshot_dir, f"panier_{site_key}_{int(time.time())}.png")
            await page.screenshot(path=screenshot_path, full_page=True)
            print(f"\n  SCREENSHOT : {screenshot_path}")

        # 4. Afficher le résultat
        if date_livraison:
            print(f"\n  >>> DATE TROUVEE : {date_livraison}")
        else:
            print(f"\n  >>> DATE NON TROUVEE")
            if diag_lines:
                print(f"\n  Diagnostic ({len(diag_lines)} lignes) :")
                for line in diag_lines[:30]:
                    print(f"    {line}")
            else:
                print("  (aucun diagnostic retourné)")

        return date_livraison

    except Exception as e:
        print(f"  ERREUR : {e}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        await context.close()


async def main():
    # Parser les arguments
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    target = args[0] if args else None
    headless = "--headless" in sys.argv
    save_screenshot = "--screenshot" in sys.argv

    print(f"  Mode : {'headless' if headless else 'visible (navigateur affiché)'}")
    print(f"  Screenshot : {'oui' if save_screenshot else 'non (ajouter --screenshot)'}")
    print(f"  Tip : --headless pour lancer sans navigateur\n")

    results = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)

        if target and target in SITES:
            result = await test_site(target, SITES[target], browser, save_screenshot)
            results[target] = result
        elif target and target not in SITES:
            print(f"  ERREUR Site inconnu : {target}")
            print(f"  Sites disponibles : {', '.join(SITES.keys())}")
            await browser.close()
            return
        else:
            for site_key, site_info in SITES.items():
                result = await test_site(site_key, site_info, browser, save_screenshot)
                results[site_key] = result

        await browser.close()

    # Résumé final
    print(f"\n{'='*70}")
    print("  RESUME")
    print(f"{'='*70}")
    for site_key, date in results.items():
        site_name = SITES[site_key]["name"]
        panier = SITES[site_key]["panier_path"]
        if date:
            print(f"  OK  {site_name:25s} ({panier:20s}) -> {date}")
        else:
            print(f"  FAIL {site_name:25s} ({panier:20s}) -> aucune date")
    print(f"{'='*70}")

    # Code de sortie : 0 si toutes les dates sont trouvées, 1 sinon
    all_found = all(d for d in results.values())
    if all_found:
        print("  SUCCES : toutes les dates de livraison ont été trouvées")
    else:
        missing = [k for k, v in results.items() if not v]
        print(f"  ECHEC : dates manquantes pour : {', '.join(missing)}")
    sys.exit(0 if all_found else 1)


if __name__ == "__main__":
    asyncio.run(main())
