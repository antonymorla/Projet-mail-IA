#!/usr/bin/env python3
"""
Test diagnostic — vérifie la détection de date de livraison sur tous les sites.

Usage:
    python3 scripts/test_date_livraison.py              # teste les 5 sites
    python3 scripts/test_date_livraison.py terrasse      # teste un seul site
    python3 scripts/test_date_livraison.py --headless     # sans navigateur
    python3 scripts/test_date_livraison.py --screenshot   # sauvegarde capture panier

Ce script :
1. Navigue vers la page boutique, clique sur le 1er produit, sélectionne la
   1ère variation disponible, et clique "Ajouter au panier"
2. Appelle _traiter_panier() avec le bon chemin panier pour scraper la date
3. Affiche le résultat + diagnostic si date non trouvée
"""

import asyncio
import sys
import os
import time

# Ajouter le dossier scripts au path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from playwright.async_api import async_playwright
from utils_playwright import fermer_popups

# Config par site
SITES = {
    "abri": {
        "name": "Abri Français",
        "url": "https://www.xn--abri-franais-sdb.fr",
        "panier_path": "/votre-panier/",
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


async def find_product_url(page, shop_url: str) -> str:
    """Navigue vers la boutique et retourne l'URL du 1er produit trouvé."""
    print(f"  -> Navigation boutique : {shop_url}")
    try:
        await page.goto(shop_url, wait_until="load", timeout=30000)
    except Exception as e:
        print(f"  ERREUR Navigation boutique : {e}")
        return ""
    await page.wait_for_timeout(2000)
    await fermer_popups(page)

    # Trouver le 1er lien vers un produit
    href = await page.evaluate("""
        () => {
            // Chercher les liens produits sur la page archive WooCommerce
            const links = document.querySelectorAll(
                'ul.products li.product a[href*="/produit/"], ' +
                '.products .product a.woocommerce-LoopProduct-link, ' +
                'a.woocommerce-loop-product__link'
            );
            for (const link of links) {
                const href = link.href || '';
                if (href.includes('/produit/') || href.includes('/product/')) {
                    return href;
                }
            }
            // Fallback : n'importe quel lien contenant /produit/
            const allLinks = document.querySelectorAll('a[href*="/produit/"]');
            if (allLinks.length > 0) return allLinks[0].href;
            return '';
        }
    """)
    if href:
        print(f"  -> Produit trouvé : {href}")
    else:
        print("  WARN Aucun lien produit trouvé sur la page boutique")
    return href


async def add_product_to_cart(page, product_url: str) -> bool:
    """Navigue vers la page produit, sélectionne les variations, ajoute au panier."""
    print(f"  -> Navigation produit : {product_url}")
    try:
        await page.goto(product_url, wait_until="load", timeout=30000)
    except Exception as e:
        print(f"  ERREUR Navigation produit : {e}")
        return False
    await page.wait_for_timeout(2000)
    await fermer_popups(page)

    # Sélectionner les variations (dropdowns WooCommerce)
    variation_selects = await page.evaluate("""
        () => {
            const selects = document.querySelectorAll(
                'table.variations select, .variations select, ' +
                'form.variations_form select'
            );
            const result = [];
            for (const sel of selects) {
                const options = [];
                for (const opt of sel.options) {
                    if (opt.value && opt.value !== '') {
                        options.push(opt.value);
                    }
                }
                if (options.length > 0) {
                    result.push({
                        id: sel.id || '',
                        name: sel.name || '',
                        first_value: options[0],
                        count: options.length
                    });
                }
            }
            return result;
        }
    """)

    if variation_selects:
        print(f"  -> {len(variation_selects)} variation(s) à sélectionner")
        for v in variation_selects:
            selector = f"#{v['id']}" if v['id'] else f"select[name='{v['name']}']"
            print(f"     {selector} -> {v['first_value']} ({v['count']} options)")
            try:
                sel = page.locator(selector).first
                if await sel.count() > 0:
                    await sel.select_option(value=v['first_value'])
                    await page.wait_for_timeout(1500)
                else:
                    # Fallback par name
                    sel2 = page.locator(f"select[name='{v['name']}']").first
                    if await sel2.count() > 0:
                        await sel2.select_option(value=v['first_value'])
                        await page.wait_for_timeout(1500)
            except Exception as e:
                print(f"     WARN Sélection variation échouée : {e}")
    else:
        print("  -> Pas de variation (produit simple ou configurateur)")

    # Attendre que le bouton soit actif (WooCommerce désactive le bouton
    # jusqu'à ce que toutes les variations soient sélectionnées)
    await page.wait_for_timeout(2000)

    # Cliquer sur "Ajouter au panier"
    btn = page.locator('button.single_add_to_cart_button').first
    if await btn.count() == 0:
        # Essayer d'autres sélecteurs
        btn = page.locator('input[type="submit"].single_add_to_cart_button, button[name="add-to-cart"]').first

    if await btn.count() > 0:
        btn_text = await btn.text_content() or ""
        is_disabled = await btn.is_disabled()
        print(f"  -> Bouton trouvé : '{btn_text.strip()[:40]}' (disabled={is_disabled})")

        if is_disabled:
            # Attendre encore un peu
            await page.wait_for_timeout(3000)
            is_disabled = await btn.is_disabled()
            if is_disabled:
                print("  WARN Bouton toujours désactivé après attente")
                return False

        await btn.scroll_into_view_if_needed()
        await btn.click()
        await page.wait_for_timeout(3000)

        # Vérifier l'ajout
        current_url = page.url
        if "/panier" in current_url or "/votre-panier" in current_url or "/cart" in current_url:
            print("  OK Redirigé vers le panier")
            return True

        msg = page.locator('.woocommerce-message')
        if await msg.count() > 0:
            txt = await msg.first.text_content()
            print(f"  OK Message : {txt.strip()[:80]}")
            return True

        # Parfois WC ne redirige pas et n'affiche pas de message mais l'ajout fonctionne
        print("  OK Clic effectué (vérification panier à suivre)")
        return True
    else:
        print("  WARN Pas de bouton 'Ajouter au panier' trouvé")
        # Dump des boutons présents pour debug
        buttons = await page.evaluate("""
            () => Array.from(document.querySelectorAll('button, input[type=submit]'))
                .map(b => (b.className || '').substring(0,60) + ' : ' +
                    (b.textContent || b.value || '').trim().substring(0,40))
                .filter(s => s.length > 5)
                .slice(0, 5)
        """)
        for b in buttons:
            print(f"     Bouton : {b}")
        return False


async def verify_cart(page, site_url: str, panier_path: str) -> int:
    """Navigue vers le panier et retourne le nombre d'articles."""
    panier_url = site_url.rstrip("/") + panier_path
    print(f"  -> Vérification panier : {panier_url}")
    await page.goto(panier_url, wait_until="load", timeout=20000)
    await page.wait_for_timeout(2000)
    await fermer_popups(page)

    nb_items = await page.evaluate("""
        () => {
            const items = document.querySelectorAll(
                'tr.cart_item, tr.woocommerce-cart-form__cart-item'
            );
            return items.length;
        }
    """)
    return nb_items


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
        # 1. Trouver un produit depuis la boutique
        product_url = await find_product_url(page, site_info["shop_url"])
        if not product_url:
            print("  WARN Aucun produit trouvé — test avec panier vide")
        else:
            # 2. Ajouter le produit au panier
            added = await add_product_to_cart(page, product_url)

            if added:
                nb = await verify_cart(page, site_info["url"], site_info["panier_path"])
                if nb > 0:
                    print(f"  OK Panier : {nb} article(s)")
                else:
                    print("  WARN Panier vide malgré l'ajout")
            else:
                print("  WARN Échec ajout produit")

        # 3. Scraper la date de livraison
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

        # 4. Screenshot si demandé
        if save_screenshot:
            screenshot_dir = os.path.join(os.path.dirname(__file__), "..", "screenshots")
            os.makedirs(screenshot_dir, exist_ok=True)
            screenshot_path = os.path.join(
                screenshot_dir, f"panier_{site_key}_{int(time.time())}.png"
            )
            await page.screenshot(path=screenshot_path, full_page=True)
            print(f"  SCREENSHOT : {screenshot_path}")

        # 5. Résultat
        if date_livraison:
            print(f"\n  >>> DATE TROUVEE : {date_livraison}")
        else:
            print(f"\n  >>> DATE NON TROUVEE")
            if diag_lines:
                print(f"\n  Diagnostic ({len(diag_lines)} lignes) :")
                for line in diag_lines[:30]:
                    print(f"    {line}")
            else:
                print("  (aucun diagnostic)")

        return date_livraison

    except Exception as e:
        print(f"  ERREUR : {e}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        await context.close()


async def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    target = args[0] if args else None
    headless = "--headless" in sys.argv
    save_screenshot = "--screenshot" in sys.argv

    print(f"  Mode : {'headless' if headless else 'visible'}")
    print(f"  Screenshot : {'oui' if save_screenshot else 'non (--screenshot)'}")
    print()

    results = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)

        if target and target in SITES:
            result = await test_site(target, SITES[target], browser, save_screenshot)
            results[target] = result
        elif target and target not in SITES:
            print(f"  ERREUR Site inconnu : {target}")
            print(f"  Sites : {', '.join(SITES.keys())}")
            await browser.close()
            return
        else:
            for site_key, site_info in SITES.items():
                result = await test_site(site_key, site_info, browser, save_screenshot)
                results[site_key] = result

        await browser.close()

    # Résumé
    print(f"\n{'='*70}")
    print("  RESUME")
    print(f"{'='*70}")
    for site_key, date in results.items():
        name = SITES[site_key]["name"]
        panier = SITES[site_key]["panier_path"]
        status = "OK  " if date else "FAIL"
        value = date if date else "aucune date"
        print(f"  {status} {name:25s} {panier:20s} -> {value}")
    print(f"{'='*70}")

    all_found = all(d for d in results.values())
    if all_found:
        print("  SUCCES")
    else:
        missing = [k for k, v in results.items() if not v]
        print(f"  ECHEC : {', '.join(missing)}")
    sys.exit(0 if all_found else 1)


if __name__ == "__main__":
    asyncio.run(main())
