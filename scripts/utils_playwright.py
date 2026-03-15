#!/usr/bin/env python3
"""
utils_playwright.py — Utilitaires Playwright partagés
entre generateur_devis_auto.py et generateur_devis_3sites.py.

Fonctions exportées :
  fermer_popups(page)                    — supprime GDPR/cookie/modal overlays
  appliquer_code_promo(page, code_promo) — applique un code coupon WC (page déjà sur /panier/)
"""


async def fermer_popups(page) -> None:
    """Ferme les popups GDPR/cookies/modals WooCommerce.

    Stratégie multi-couche :
    1. Clic sur les boutons d'acceptation connus
    2. Suppression DOM des éléments bloquants
    3. Injection CSS persistant (survit aux rechargements AJAX)
    """
    for sel in ['.cmplz-accept', 'button:has-text("Accepter")',
                '#cn-accept-cookie', '.cookie-accept', '.gdpr-accept']:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=800):
                await btn.click()
                await page.wait_for_timeout(500)
                break
        except Exception:
            pass
    await page.evaluate("""
        () => {
            ['.cmplz-cookiebanner','#cookie-law-info-bar','.pum-overlay',
             '[class*="cookie-banner"]','[id*="cookie-consent"]','.gdpr-banner',
             '#popup-modal','.popup-modal','.modal.open','.popup-overlay',
             '.popup-backdrop','.backdrop','#cmplz-cookiebanner-container'].forEach(s =>
                document.querySelectorAll(s).forEach(el => {
                    el.classList.remove('open');
                    el.style.display = 'none';
                    el.style.pointerEvents = 'none';
                    if (el.parentNode) el.parentNode.removeChild(el);
                })
            );
            document.body.style.overflow = '';
            document.documentElement.style.overflow = '';
        }
    """)
    # CSS persistant — empêche tout overlay de bloquer les clics même s'il réapparaît
    try:
        await page.add_style_tag(content="""
            #popup-modal, .popup-modal, .modal.open,
            .cmplz-cookiebanner, #cmplz-cookiebanner-container,
            .pum-overlay, .pum-container,
            .popup-overlay, .popup-backdrop, .backdrop,
            [class*="cookie-banner"], [id*="cookie-consent"] {
                pointer-events: none !important;
                display: none !important;
            }
        """)
    except Exception:
        pass


async def appliquer_code_promo(page, code_promo: str) -> None:
    """Applique un code promo WooCommerce sur la page panier actuelle.

    La page doit déjà être sur /panier/ ou /votre-panier/.
    Stratégie double :
    1. AJAX via wc_cart_params.apply_coupon_nonce (rapide, sans rechargement)
    2. Fallback : formulaire HTML #coupon_code + bouton apply_coupon

    Continue silencieusement en cas d'erreur (le devis est généré même sans promo).
    """
    if not code_promo:
        return

    code_promo = code_promo.strip().upper()
    print(f"  ➜ Code promo : tentative d'application de {code_promo}...")

    # Stratégie 1 : AJAX avec nonce wc_cart_params
    try:
        result = await page.evaluate(
            """(code) => {
                const nonce = window.wc_cart_params?.apply_coupon_nonce;
                if (!nonce) return Promise.resolve({ok: false, msg: 'nonce_absent'});
                const fd = new FormData();
                fd.append('security', nonce);
                fd.append('coupon_code', code);
                return fetch('/?wc-ajax=apply_coupon', {method: 'POST', body: fd})
                    .then(r => r.text())
                    .then(text => ({
                        ok: text.includes('woocommerce-message'),
                        error: text.includes('woocommerce-error'),
                        msg: text.substring(0, 150),
                    }));
            }""",
            code_promo,
        )
        if result.get("ok"):
            print(f"    ✅ Code promo {code_promo} appliqué (AJAX)")
            return
        if result.get("error"):
            print(f"    ⚠ Code promo {code_promo} refusé par le site (invalide ou non applicable)")
            return
        print("    ⚠ nonce absent, tentative via formulaire...")
    except Exception as e:
        print(f"    ⚠ AJAX échoué ({e}), tentative via formulaire...")

    # Stratégie 2 : formulaire HTML (champ #coupon_code + bouton apply_coupon)
    try:
        coupon_input = page.locator("#coupon_code, input[name='coupon_code']").first
        apply_btn    = page.locator("button[name='apply_coupon'], .coupon button[type='submit']").first
        if await coupon_input.is_visible(timeout=3000):
            await coupon_input.fill(code_promo)
            await apply_btn.click(timeout=5000)
            await page.wait_for_timeout(2000)
            msg_ok  = await page.locator(".woocommerce-message").count()
            msg_err = await page.locator(".woocommerce-error").count()
            if msg_ok:
                print(f"    ✅ Code promo {code_promo} appliqué (formulaire)")
            elif msg_err:
                print(f"    ⚠ Code promo {code_promo} refusé (formulaire)")
            else:
                print(f"    ⚠ Code promo {code_promo} : résultat inconnu")
        else:
            print("    ⚠ Formulaire coupon introuvable")
    except Exception as e:
        print(f"    ⚠ Erreur application code promo {code_promo} (formulaire) : {e}")
