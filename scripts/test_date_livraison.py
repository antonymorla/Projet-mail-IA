#!/usr/bin/env python3
"""
Test diagnostic — vérifie la détection de date de livraison sur tous les sites.

Usage:
    python3 scripts/test_date_livraison.py              # teste les 5 sites
    python3 scripts/test_date_livraison.py terrasse      # teste un seul site
    python3 scripts/test_date_livraison.py terrasse --headless
    python3 scripts/test_date_livraison.py --screenshot   # sauvegarde une capture du panier

Ce script :
1. Navigue vers la boutique du site, trouve un produit, l'ajoute au panier
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

# Config par site — page boutique + chemin panier
SITES = {
    "abri": {
        "name": "Abri Français",
        "url": "https://www.xn--abri-franais-sdb.fr",
        "panier_path": "/votre-panier/",
        # Page catégorie avec des produits simples (Gamme Essentiel)
        "shop_url": "https://www.xn--abri-franais-sdb.fr/product-category/nos-produits/modeles-preconcus/abris-de-jardin-essentiel/",
    },
    "studio": {
        "name": "Studio Français",
        "url": "https://xn--studio-franais-qjb.fr",
        "panier_path": "/panier/",
        "shop_url": "https://xn--studio-franais-qjb.fr/boutique/",
    },
    "pergola": {
        "name": "Ma Pergola Bois",
        "url": "https://mapergolabois.fr",
        "panier_path": "/panier/",
        "shop_url": "https://www.mapergolabois.fr/boutique/",
    },
    "terrasse": {
        "name": "Terrasse en Bois",
        "url": "https://terrasseenbois.fr",
        "panier_path": "/panier/",
        "shop_url": "https://www.terrasseenbois.fr/boutique/",
    },
    "cloture": {
        "name": "Clôture Bois",
        "url": "https://cloturebois.fr",
        "panier_path": "/panier/",
        "shop_url": "https://cloturebois.fr/boutique/",
    },
}


async def add_product_from_shop(page, site_url: str, shop_url: str, panier_path: str) -> bool:
    """Navigue vers la boutique, trouve un produit et l'ajoute au panier.

    Stratégie en 3 étapes :
    1. Chercher un bouton AJAX "Ajouter au panier" sur la page boutique (produits simples)
    2. Si pas de bouton AJAX, cliquer sur le 1er produit et ajouter depuis la page produit
    3. Vérifier que le panier contient au moins 1 article
    """
    print(f"  -> Navigation boutique : {shop_url}")
    try:
        await page.goto(shop_url, wait_until="load", timeout=30000)
    except Exception as e:
        print(f"  ERREUR Navigation boutique : {e}")
        return False
    await page.wait_for_timeout(2000)
    await fermer_popups(page)

    # ── Stratégie 1 : bouton AJAX "Ajouter au panier" sur la page archive ──
    # WooCommerce met data-product_id sur les boutons add_to_cart sur les pages archive
    ajax_btn = page.locator('a.add_to_cart_button[data-product_id]').first
    if await ajax_btn.count() > 0:
        product_id = await ajax_btn.get_attribute('data-product_id')
        print(f"  -> Clic AJAX ajout au panier (product_id={product_id})...")
        try:
            await ajax_btn.scroll_into_view_if_needed()
            await ajax_btn.click()
            await page.wait_for_timeout(3000)
            # WooCommerce ajoute la classe "added" après l'AJAX
            added_btn = page.locator(f'a.add_to_cart_button.added[data-product_id="{product_id}"]')
            if await added_btn.count() > 0:
                print(f"  OK Produit {product_id} ajouté via AJAX")
                return True
            # Vérifier aussi le badge panier
            print(f"  OK Clic effectué sur produit {product_id} (on continue)")
            return True
        except Exception as e:
            print(f"  WARN AJAX échoué : {e}")

    # ── Stratégie 2 : naviguer vers le 1er produit de la liste ──
    product_link = page.locator('a.woocommerce-LoopProduct-link, ul.products li.product a[href*="/produit/"]').first
    if await product_link.count() > 0:
        href = await product_link.get_attribute('href')
        print(f"  -> Navigation vers produit : {href}")
        try:
            await page.goto(href, wait_until="load", timeout=30000)
        except Exception as e:
            print(f"  ERREUR Navigation produit : {e}")
            return False
        await page.wait_for_timeout(2000)
        await fermer_popups(page)

        # Sur la page produit : si c'est un produit variable, sélectionner la 1ère variation
        selects = page.locator('table.variations select, .variations select')
        select_count = await selects.count()
        if select_count > 0:
            for i in range(select_count):
                sel = selects.nth(i)
                # Sélectionner la 1ère option non-vide
                first_option = await sel.evaluate("""
                    el => {
                        for (const opt of el.options) {
                            if (opt.value && opt.value !== '') return opt.value;
                        }
                        return '';
                    }
                """)
                if first_option:
                    sel_id = await sel.get_attribute('id') or '?'
                    print(f"  -> Variation #{sel_id} = {first_option}")
                    await sel.select_option(value=first_option)
                    await page.wait_for_timeout(1500)

        # Cliquer sur Ajouter au panier
        btn = page.locator('button.single_add_to_cart_button').first
        if await btn.count() > 0:
            is_disabled = await btn.is_disabled()
            if is_disabled:
                await page.wait_for_timeout(3000)
                is_disabled = await btn.is_disabled()

            if not is_disabled:
                await btn.scroll_into_view_if_needed()
                await btn.click()
                await page.wait_for_timeout(3000)
                print("  OK Clic 'Ajouter au panier' effectué")
                return True
            else:
                print("  WARN Bouton désactivé")
        else:
            print("  WARN Pas de bouton 'Ajouter au panier' sur la page produit")

    # ── Stratégie 3 (fallback) : essayer d'ajouter via wc-ajax ──
    # Chercher n'importe quel product_id dans le HTML de la page
    print("  -> Fallback : recherche product_id dans le HTML...")
    product_id = await page.evaluate("""
        () => {
            // Chercher dans les boutons add_to_cart
            const btn = document.querySelector('[data-product_id]');
            if (btn) return btn.getAttribute('data-product_id');
            // Chercher dans les formulaires
            const input = document.querySelector('input[name="add-to-cart"], input[name="product_id"]');
            if (input) return input.value;
            // Chercher dans le body class (WooCommerce met postid-XXXX)
            const m = document.body.className.match(/postid-(\\d+)/);
            if (m) return m[1];
            return '';
        }
    """)
    if product_id:
        print(f"  -> Ajout via wc-ajax (product_id={product_id})...")
        result = await page.evaluate("""
            async (pid) => {
                try {
                    const fd = new FormData();
                    fd.append('product_id', pid);
                    fd.append('quantity', '1');
                    const r = await fetch('/?wc-ajax=add_to_cart', {method: 'POST', body: fd});
                    const j = await r.json();
                    return JSON.stringify(j);
                } catch(e) {
                    return 'error:' + e.message;
                }
            }
        """, product_id)
        print(f"  -> Réponse wc-ajax : {str(result)[:150]}")
        if result and 'error' not in str(result).lower()[:20]:
            return True

    print("  WARN Aucun produit ajouté au panier")
    return False


async def verify_cart_has_items(page, site_url: str, panier_path: str) -> bool:
    """Vérifie que le panier contient au moins un article."""
    panier_url = site_url.rstrip("/") + panier_path
    await page.goto(panier_url, wait_until="load", timeout=20000)
    await page.wait_for_timeout(2000)
    await fermer_popups(page)

    has_items = await page.evaluate("""
        () => {
            const items = document.querySelectorAll(
                '.cart_item, .woocommerce-cart-form__cart-item, tr.cart-item, ' +
                '.woocommerce-cart-form .product-name'
            );
            return items.length;
        }
    """)
    return has_items > 0


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
        added = await add_product_from_shop(
            page,
            site_info["url"],
            site_info["shop_url"],
            site_info["panier_path"],
        )

        if added:
            # Vérifier que le panier contient réellement un article
            has_items = await verify_cart_has_items(page, site_info["url"], site_info["panier_path"])
            if has_items:
                print("  OK Panier vérifié : au moins 1 article")
            else:
                print("  WARN Panier semble vide malgré l'ajout")
        else:
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
            print(f"  OK   {site_name:25s} ({panier:20s}) -> {date}")
        else:
            print(f"  FAIL {site_name:25s} ({panier:20s}) -> aucune date")
    print(f"{'='*70}")

    all_found = all(d for d in results.values())
    if all_found:
        print("  SUCCES : toutes les dates de livraison ont ete trouvees")
    else:
        missing = [k for k, v in results.items() if not v]
        print(f"  ECHEC : dates manquantes pour : {', '.join(missing)}")
    sys.exit(0 if all_found else 1)


if __name__ == "__main__":
    asyncio.run(main())
