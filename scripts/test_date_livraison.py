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
   1ère variation via JavaScript (les selects sont souvent cachés par les swatches),
   et clique "Ajouter au panier"
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

# Config par site — shop_url pointe vers une catégorie avec des produits ajoutables
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
        # Catégorie "accessoires" contient des produits simples ajoutables
        "shop_url": "https://xn--studio-franais-qjb.fr/product-category/accessoires/",
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
        # Catégorie plots — produits variables simples (1 seul attribut)
        "shop_url": "https://www.terrasseenbois.fr/product-category/plots-terrasse/",
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

    href = await page.evaluate("""
        () => {
            // Liens produits WooCommerce
            const selectors = [
                'ul.products li.product a[href*="/produit/"]',
                '.products .product a.woocommerce-LoopProduct-link',
                'a.woocommerce-loop-product__link',
                'a[href*="/produit/"]',
            ];
            for (const sel of selectors) {
                const links = document.querySelectorAll(sel);
                for (const link of links) {
                    const href = link.href || '';
                    if (href.includes('/produit/') || href.includes('/product/')) {
                        return href;
                    }
                }
            }
            return '';
        }
    """)
    if href:
        print(f"  -> Produit trouvé : {href}")
    else:
        print("  WARN Aucun lien produit trouvé sur la page boutique")
    return href


async def select_variations_js(page) -> int:
    """Sélectionne toutes les variations via JavaScript (contourne les selects cachés).

    Retourne le nombre de variations sélectionnées.
    """
    result = await page.evaluate("""
        () => {
            // Trouver tous les selects de variation WooCommerce
            const selects = document.querySelectorAll(
                'table.variations select, .variations select, form.variations_form select'
            );
            let selected = 0;
            for (const sel of selects) {
                // Trouver la 1ère option non-vide
                let firstValue = '';
                for (const opt of sel.options) {
                    if (opt.value && opt.value !== '') {
                        firstValue = opt.value;
                        break;
                    }
                }
                if (firstValue && sel.value !== firstValue) {
                    sel.value = firstValue;
                    sel.dispatchEvent(new Event('change', {bubbles: true}));
                    selected++;
                } else if (firstValue && sel.value === firstValue) {
                    selected++;  // déjà sélectionné
                }
            }
            return selected;
        }
    """)
    return result


async def add_product_to_cart(page, product_url: str) -> bool:
    """Navigue vers la page produit, sélectionne les variations via JS, ajoute au panier."""
    print(f"  -> Navigation produit : {product_url}")
    try:
        await page.goto(product_url, wait_until="load", timeout=30000)
    except Exception as e:
        print(f"  ERREUR Navigation produit : {e}")
        return False
    await page.wait_for_timeout(2000)
    await fermer_popups(page)

    # Sélectionner les variations via JavaScript (les selects sont souvent cachés par swatches)
    nb_selected = await select_variations_js(page)
    if nb_selected > 0:
        print(f"  -> {nb_selected} variation(s) sélectionnée(s) via JS")
        # Attendre que WooCommerce mette à jour le prix et active le bouton
        await page.wait_for_timeout(3000)
        # Re-sélectionner au cas où WooCommerce a reset certains selects (cascade)
        nb2 = await select_variations_js(page)
        if nb2 > nb_selected:
            print(f"  -> +{nb2 - nb_selected} variation(s) supplémentaire(s) après cascade")
            await page.wait_for_timeout(2000)
    else:
        print("  -> Pas de variation (produit simple)")

    # Vérifier les variations sélectionnées pour debug
    variations_debug = await page.evaluate("""
        () => {
            const selects = document.querySelectorAll(
                'table.variations select, .variations select'
            );
            return Array.from(selects).map(s => ({
                id: s.id,
                value: s.value,
                visible: s.offsetParent !== null
            }));
        }
    """)
    for v in variations_debug:
        vis = "visible" if v["visible"] else "hidden"
        print(f"     #{v['id']} = '{v['value']}' ({vis})")

    # Cliquer sur "Ajouter au panier"
    btn = page.locator('button.single_add_to_cart_button').first
    if await btn.count() == 0:
        btn = page.locator(
            'input[type="submit"].single_add_to_cart_button, '
            'button[name="add-to-cart"]'
        ).first

    if await btn.count() > 0:
        btn_text = (await btn.text_content() or "").strip()[:40]
        is_disabled = await btn.is_disabled()
        print(f"  -> Bouton : '{btn_text}' (disabled={is_disabled})")

        if is_disabled:
            await page.wait_for_timeout(3000)
            is_disabled = await btn.is_disabled()
            if is_disabled:
                print("  WARN Bouton désactivé — variations probablement incomplètes")
                return False

        await btn.scroll_into_view_if_needed()
        await btn.click()
        await page.wait_for_timeout(3000)

        # Vérifier l'ajout
        url = page.url
        if "/panier" in url or "/votre-panier" in url or "/cart" in url:
            print("  OK Redirigé vers le panier")
            return True

        msg = page.locator('.woocommerce-message')
        if await msg.count() > 0:
            txt = (await msg.first.text_content() or "").strip()[:80]
            print(f"  OK Message : {txt}")
            return True

        # Vérifier erreur WooCommerce
        err = page.locator('.woocommerce-error')
        if await err.count() > 0:
            txt = (await err.first.text_content() or "").strip()[:80]
            print(f"  WARN Erreur WC : {txt}")
            return False

        print("  OK Clic effectué (vérification panier à suivre)")
        return True
    else:
        # Pas de bouton standard — essayer ajout via wc-ajax
        print("  WARN Pas de bouton standard — tentative wc-ajax")
        product_id = await page.evaluate("""
            () => {
                const input = document.querySelector(
                    'input[name="add-to-cart"], input[name="product_id"], ' +
                    'button[name="add-to-cart"]'
                );
                if (input) return input.value || input.getAttribute('value') || '';
                const m = document.body.className.match(/postid-(\\d+)/);
                return m ? m[1] : '';
            }
        """)
        if product_id:
            result = await page.evaluate("""
                async (pid) => {
                    try {
                        const fd = new FormData();
                        fd.append('product_id', pid);
                        fd.append('quantity', '1');
                        const r = await fetch('/?wc-ajax=add_to_cart', {
                            method: 'POST', body: fd
                        });
                        const j = await r.json();
                        return JSON.stringify(j);
                    } catch(e) {
                        return 'error:' + e.message;
                    }
                }
            """, product_id)
            print(f"  -> wc-ajax (pid={product_id}) : {str(result)[:100]}")
            if result and 'error' not in str(result).lower()[:20]:
                return True

        print("  WARN Échec ajout")
        return False


async def verify_cart(page, site_url: str, panier_path: str) -> int:
    """Navigue vers le panier et retourne le nombre d'articles."""
    panier_url = site_url.rstrip("/") + panier_path
    print(f"  -> Vérification panier : {panier_url}")
    await page.goto(panier_url, wait_until="load", timeout=20000)
    await page.wait_for_timeout(2000)
    await fermer_popups(page)

    nb = await page.evaluate("""
        () => document.querySelectorAll(
            'tr.cart_item, tr.woocommerce-cart-form__cart-item'
        ).length
    """)
    return nb


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
        # 1. Trouver un produit
        product_url = await find_product_url(page, site_info["shop_url"])
        if not product_url:
            print("  WARN Aucun produit trouvé — test avec panier vide")
        else:
            # 2. L'ajouter au panier
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

        # 4. Screenshot
        if save_screenshot:
            screenshot_dir = os.path.join(os.path.dirname(__file__), "..", "screenshots")
            os.makedirs(screenshot_dir, exist_ok=True)
            path = os.path.join(screenshot_dir, f"panier_{site_key}_{int(time.time())}.png")
            await page.screenshot(path=path, full_page=True)
            print(f"  SCREENSHOT : {path}")

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
        value = date or "aucune date"
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
