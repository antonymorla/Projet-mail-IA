#!/usr/bin/env python3
"""
Test LIVE — Vérifie que la sélection de la pente 15% fonctionne
sur le configurateur pergola mapergolabois.fr.

Ce test navigue sur le vrai site avec Playwright et tente de :
1. Sélectionner une variation 5m×4m indépendante, ventelle largeur, carport
2. Sélectionner la pente 15% via le swatch WAPF field-e8cec8d
3. Vérifier que la sélection est bien prise en compte

Usage :
    python tests/test_pergola_pente_live.py                    # navigateur visible
    python tests/test_pergola_pente_live.py --headless         # sans navigateur
    python tests/test_pergola_pente_live.py --screenshot       # sauvegarde des captures
    python tests/test_pergola_pente_live.py --headless --screenshot
"""

import asyncio
import os
import sys

# Ajouter scripts/ au path pour importer les utilitaires
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from playwright.async_api import async_playwright

PERGOLA_URL = "https://mapergolabois.fr/produit/pergola-bois-en-kit/"
PENTE_FIELD_ID = "e8cec8d"
SCREENSHOT_DIR = os.path.join(os.path.dirname(__file__), "screenshots")


async def fermer_popups_simple(page):
    """Ferme les popups classiques."""
    for sel in [
        ".popmake-close", "#cookie-accept", ".close-popup",
        ".cc-dismiss", ".cookie-close", "button.accept-cookies",
        "[aria-label='Close']", ".modal .close",
    ]:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=800):
                await btn.click()
                await page.wait_for_timeout(300)
        except Exception:
            pass


async def test_pente_selection(headless: bool = False, screenshot: bool = False):
    """Test principal : sélectionner pente 15% sur pergola 5×4m carport."""
    results = {"passed": [], "failed": [], "warnings": []}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        page = await browser.new_page(viewport={"width": 1400, "height": 900})

        # ── 1. Charger la page produit ────────────────────────────
        print("\n" + "=" * 70)
        print("  TEST PENTE PERGOLA — mapergolabois.fr")
        print("=" * 70)

        print("\n[1/6] Chargement de la page produit...")
        try:
            await page.goto(PERGOLA_URL, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)
            await fermer_popups_simple(page)
            results["passed"].append("Page chargée")
            print("  ✓ Page chargée")
        except Exception as e:
            results["failed"].append(f"Chargement page : {e}")
            print(f"  ✗ Échec chargement : {e}")
            await browser.close()
            return results

        # ── 2. Sélectionner la variation WC ───────────────────────
        print("\n[2/6] Sélection variation : 5m × 4m | indépendante | ventelle=largeur | carport")
        attrs = {
            "attribute_pa_largeur": "5m",
            "attribute_pa_profondeur": "4m",
            "attribute_pa_fixation": "independante",
            "attribute_pa_ventelle": "largeur",
            "attribute_pa_option": "carport",
        }

        try:
            await page.wait_for_selector("form.variations_form", timeout=15000)
            await page.wait_for_timeout(1500)

            # Essai via select jQuery
            log = await page.evaluate("""
                (attrs) => {
                    var log = [];
                    for (var key in attrs) {
                        var val = attrs[key];
                        var sel = document.querySelector('select[name="' + key + '"]');
                        if (sel && typeof jQuery !== 'undefined') {
                            jQuery(sel).val(val);
                            log.push(key + '=' + val);
                        }
                        var container = document.querySelector(
                            '.wcboost-variation-swatches[data-attribute_name="' + key + '"]'
                        );
                        if (container) {
                            container.querySelectorAll('.wcboost-variation-swatches-item').forEach(function(item) {
                                item.classList.toggle(
                                    'wcboost-variation-swatches-item--selected',
                                    item.getAttribute('data-value') === val
                                );
                            });
                        }
                    }
                    // Trigger change sur le dernier select
                    var keys = Object.keys(attrs);
                    var lastSel = document.querySelector('select[name="' + keys[keys.length - 1] + '"]');
                    if (lastSel && typeof jQuery !== 'undefined') jQuery(lastSel).trigger('change');
                    return log;
                }
            """, attrs)
            print(f"  ✓ Attributs sélectionnés : {log}")
            results["passed"].append("Variation WC sélectionnée")
        except Exception as e:
            results["failed"].append(f"Sélection variation : {e}")
            print(f"  ✗ Échec sélection variation : {e}")

        await page.wait_for_timeout(2000)

        # Vérifier le prix
        prix = await page.evaluate("""
            () => {
                var p = document.querySelector('.woocommerce-variation-price .woocommerce-Price-amount');
                return p ? p.textContent.trim() : null;
            }
        """)
        print(f"  Prix affiché : {prix or '(aucun)'}")

        if screenshot:
            os.makedirs(SCREENSHOT_DIR, exist_ok=True)
            await page.screenshot(path=os.path.join(SCREENSHOT_DIR, "01_variation_selected.png"))
            print(f"  📸 Screenshot sauvegardé")

        # ── 3. Inspecter le champ pente AVANT sélection ───────────
        print(f"\n[3/6] Inspection du champ pente (field-{PENTE_FIELD_ID})...")
        pente_state = await page.evaluate("""
            (fieldId) => {
                var container = document.querySelector('.wapf-field-container.field-' + fieldId);
                if (!container) return {exists: false, error: 'container_not_found'};

                var isHidden = container.classList.contains('wapf-hide');
                var classList = Array.from(container.classList);

                var label = container.querySelector('.wapf-field-label, label');
                var labelText = label ? label.textContent.trim() : '(pas de label)';

                // Lister tous les swatches disponibles
                var swatches = [];
                container.querySelectorAll('div.wapf-swatch label').forEach(function(l) {
                    var aria = l.getAttribute('aria-label') || '';
                    var text = l.textContent.trim();
                    var isSelected = l.classList.contains('selected') ||
                                     l.querySelector('input:checked') !== null;
                    var input = l.querySelector('input');
                    var inputValue = input ? input.value : '';
                    var inputChecked = input ? input.checked : false;
                    swatches.push({
                        aria_label: aria,
                        text: text,
                        is_selected: isSelected,
                        input_value: inputValue,
                        input_checked: inputChecked,
                        outer_html: l.outerHTML.substring(0, 200),
                    });
                });

                // Chercher aussi les inputs dans le container
                var inputs = [];
                container.querySelectorAll('input').forEach(function(inp) {
                    inputs.push({
                        type: inp.type,
                        name: inp.name,
                        value: inp.value,
                        checked: inp.checked,
                    });
                });

                return {
                    exists: true,
                    hidden: isHidden,
                    label: labelText,
                    classes: classList,
                    swatches: swatches,
                    inputs: inputs,
                    inner_html: container.innerHTML.substring(0, 1000),
                };
            }
        """, PENTE_FIELD_ID)

        if not pente_state.get("exists"):
            results["failed"].append(f"Champ pente non trouvé : {pente_state.get('error')}")
            print(f"  ✗ Champ pente NON TROUVÉ")
        else:
            hidden = pente_state.get("hidden", True)
            label = pente_state.get("label", "?")
            swatches = pente_state.get("swatches", [])
            print(f"  Label    : {label}")
            print(f"  Caché    : {hidden}")
            print(f"  Swatches : {len(swatches)}")
            for s in swatches:
                selected = " ← SÉLECTIONNÉ" if s["is_selected"] else ""
                print(f"    • aria-label=\"{s['aria_label']}\"  text=\"{s['text']}\"  "
                      f"input_value=\"{s['input_value']}\"  checked={s['input_checked']}{selected}")

            if hidden:
                results["warnings"].append("Champ pente caché (wapf-hide) — peut-être conditionnel")
                print("  ⚠ Le champ est caché (wapf-hide)")
            else:
                results["passed"].append("Champ pente visible")

            # Vérifier que "Pente 15%" existe dans les swatches
            pente_labels = [s["aria_label"] for s in swatches]
            if any("15%" in lbl for lbl in pente_labels):
                results["passed"].append("Option Pente 15% existe dans les swatches")
                print("  ✓ Option Pente 15% trouvée dans les swatches")
            else:
                results["failed"].append(f"Option Pente 15% absente. Disponibles : {pente_labels}")
                print(f"  ✗ Option Pente 15% ABSENTE. Disponibles : {pente_labels}")

        if screenshot:
            await page.screenshot(path=os.path.join(SCREENSHOT_DIR, "02_pente_before.png"))

        # ── 4. Attendre que le champ pente soit visible ──────────
        print(f"\n[4/6] Attente visibilité champ pente...")
        try:
            await page.wait_for_function(
                f"!document.querySelector('.wapf-field-container.field-{PENTE_FIELD_ID}')?.classList.contains('wapf-hide')",
                timeout=8000,
            )
            results["passed"].append("Champ pente devenu visible")
            print("  ✓ Champ pente visible (pas de wapf-hide)")
        except Exception as e:
            results["failed"].append(f"Champ pente reste caché après 8s : {e}")
            print(f"  ✗ Champ pente toujours caché après 8s")

            # Debug : ré-inspecter
            debug = await page.evaluate("""
                (fieldId) => {
                    var c = document.querySelector('.wapf-field-container.field-' + fieldId);
                    if (!c) return 'container not found';
                    return {
                        hidden: c.classList.contains('wapf-hide'),
                        display: getComputedStyle(c).display,
                        visibility: getComputedStyle(c).visibility,
                        opacity: getComputedStyle(c).opacity,
                        classes: Array.from(c.classList),
                    };
                }
            """, PENTE_FIELD_ID)
            print(f"  Debug état : {debug}")

        await page.wait_for_timeout(500)

        # ── 5. Cliquer sur le swatch Pente 15% ─────────────────────
        print("\n[5/6] Sélection pente 15%...")
        # aria-labels réels : "Pente 5%", "Pente 15%" (pas "5%" ni "15%")
        candidates_15 = ["Pente 15%", "15%", "15"]

        clic_ok = False
        for candidate in candidates_15:
            try:
                selector = f'.wapf-field-container.field-{PENTE_FIELD_ID} div.wapf-swatch label[aria-label="{candidate}"]'
                await page.click(selector, timeout=3000)
                results["passed"].append(f"Clic sur swatch \"{candidate}\" réussi")
                print(f'  ✓ Clic sur label aria-label="{candidate}" réussi')
                clic_ok = True
                break
            except Exception:
                print(f'  ✗ Clic aria-label="{candidate}" échoué')

        if not clic_ok:
            # Fallback JS : correspondance partielle
            try:
                js_result = await page.evaluate("""
                    (fieldId) => {
                        var c = document.querySelector('.wapf-field-container.field-' + fieldId);
                        if (!c) return {ok: false, error: 'container not found'};

                        var labels = c.querySelectorAll('div.wapf-swatch label');
                        for (var l of labels) {
                            var aria = (l.getAttribute('aria-label') || '').trim();
                            if (aria.indexOf('15') !== -1) {
                                l.click();
                                return {ok: true, method: 'js_partial', aria: aria};
                            }
                        }
                        return {ok: false, error: 'no matching label', count: labels.length};
                    }
                """, PENTE_FIELD_ID)
                print(f"  Fallback JS : {js_result}")
                if js_result.get("ok"):
                    results["passed"].append(f"Clic JS réussi ({js_result.get('method')})")
                else:
                    results["failed"].append(f"Tous les clics échoués : {js_result}")
            except Exception as e3:
                results["failed"].append(f"Pente 15% impossible à sélectionner : {e3}")

        await page.wait_for_timeout(1000)

        # ── 6. Vérifier que la pente est bien sélectionnée ────────
        print("\n[6/6] Vérification de la sélection...")
        post_state = await page.evaluate("""
            (fieldId) => {
                var c = document.querySelector('.wapf-field-container.field-' + fieldId);
                if (!c) return {exists: false};

                var swatches = [];
                c.querySelectorAll('div.wapf-swatch label').forEach(function(l) {
                    var aria = l.getAttribute('aria-label') || '';
                    var input = l.querySelector('input');
                    swatches.push({
                        aria_label: aria,
                        is_selected: l.classList.contains('selected'),
                        input_checked: input ? input.checked : false,
                        input_value: input ? input.value : '',
                    });
                });

                // Vérifier la valeur du champ WAPF dans le formulaire
                var wapfInput = c.querySelector('input[name*="wapf"]');
                var wapfValue = wapfInput ? wapfInput.value : '(no wapf input)';

                return {
                    exists: true,
                    hidden: c.classList.contains('wapf-hide'),
                    swatches: swatches,
                    wapf_value: wapfValue,
                };
            }
        """, PENTE_FIELD_ID)

        if post_state.get("exists"):
            swatches = post_state.get("swatches", [])
            for s in swatches:
                selected = " ← SÉLECTIONNÉ" if (s["is_selected"] or s["input_checked"]) else ""
                print(f"    • {s['aria_label']}: selected={s['is_selected']}, "
                      f"checked={s['input_checked']}, value={s['input_value']}{selected}")

            # Vérifier que 15% est checked
            pente_15_selected = any(
                (s["is_selected"] or s["input_checked"])
                and ("15" in s.get("aria_label", ""))
                for s in swatches
            )
            if pente_15_selected:
                results["passed"].append("Pente 15% confirmée comme sélectionnée")
                print("  ✓ PENTE 15% BIEN SÉLECTIONNÉE")
            else:
                results["failed"].append("Pente 15% non confirmée après clic")
                print("  ✗ PENTE 15% NON SÉLECTIONNÉE après clic")

        # Vérifier le prix total mis à jour
        prix_total = await page.evaluate("""
            () => {
                // WAPF prix total
                var wapfTotal = document.querySelector('.wapf-field-container.field-8a0aad9');
                if (wapfTotal) {
                    var inp = wapfTotal.querySelector('input');
                    return inp ? inp.value : 'input not found';
                }
                // Prix WC
                var p = document.querySelector('.woocommerce-variation-price .woocommerce-Price-amount');
                return p ? p.textContent.trim() : null;
            }
        """)
        print(f"\n  Prix total après sélection pente : {prix_total or '(non trouvé)'}")

        if screenshot:
            await page.screenshot(path=os.path.join(SCREENSHOT_DIR, "03_pente_after.png"))
            print(f"  📸 Screenshots sauvegardés dans {SCREENSHOT_DIR}/")

        await browser.close()

    # ── Rapport final ─────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  RÉSULTATS")
    print("=" * 70)
    for item in results["passed"]:
        print(f"  ✓ PASS : {item}")
    for item in results["warnings"]:
        print(f"  ⚠ WARN : {item}")
    for item in results["failed"]:
        print(f"  ✗ FAIL : {item}")
    print(f"\n  {len(results['passed'])} pass / {len(results['warnings'])} warn / {len(results['failed'])} fail")
    print("=" * 70)

    return results


async def test_pente_5_percent(headless: bool = False, screenshot: bool = False):
    """Test supplémentaire : vérifier que la pente 5% (défaut) fonctionne aussi."""
    print("\n" + "=" * 70)
    print("  TEST PENTE 5% (défaut)")
    print("=" * 70)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        page = await browser.new_page(viewport={"width": 1400, "height": 900})

        await page.goto(PERGOLA_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)
        await fermer_popups_simple(page)

        # Sélectionner variation
        attrs = {
            "attribute_pa_largeur": "5m",
            "attribute_pa_profondeur": "4m",
            "attribute_pa_fixation": "independante",
            "attribute_pa_ventelle": "largeur",
            "attribute_pa_option": "carport",
        }
        await page.wait_for_selector("form.variations_form", timeout=15000)
        await page.wait_for_timeout(1500)
        await page.evaluate("""
            (attrs) => {
                for (var key in attrs) {
                    var sel = document.querySelector('select[name="' + key + '"]');
                    if (sel && typeof jQuery !== 'undefined') jQuery(sel).val(attrs[key]);
                }
                var keys = Object.keys(attrs);
                var lastSel = document.querySelector('select[name="' + keys[keys.length - 1] + '"]');
                if (lastSel && typeof jQuery !== 'undefined') jQuery(lastSel).trigger('change');
            }
        """, attrs)
        await page.wait_for_timeout(2000)

        # Essayer de sélectionner Pente 5%
        try:
            await page.wait_for_function(
                f"!document.querySelector('.wapf-field-container.field-{PENTE_FIELD_ID}')?.classList.contains('wapf-hide')",
                timeout=8000,
            )
            # aria-label réel : "Pente 5%" (pas "5%")
            clic_5_ok = False
            for candidate in ["Pente 5%", "5%", "5"]:
                try:
                    sel = f'.wapf-field-container.field-{PENTE_FIELD_ID} div.wapf-swatch label[aria-label="{candidate}"]'
                    await page.click(sel, timeout=3000)
                    print(f'  ✓ Pente 5% sélectionnée (aria-label="{candidate}")')
                    clic_5_ok = True
                    break
                except Exception:
                    continue
            if not clic_5_ok:
                print("  ✗ Pente 5% : aucun sélecteur n'a fonctionné")

            # Vérifier
            post = await page.evaluate("""
                (fieldId) => {
                    var c = document.querySelector('.wapf-field-container.field-' + fieldId);
                    var labels = c ? c.querySelectorAll('div.wapf-swatch label') : [];
                    var result = [];
                    labels.forEach(function(l) {
                        var inp = l.querySelector('input');
                        result.push({
                            aria: l.getAttribute('aria-label'),
                            checked: inp ? inp.checked : false,
                            selected: l.classList.contains('selected'),
                        });
                    });
                    return result;
                }
            """, PENTE_FIELD_ID)
            for s in post:
                sel = " ← SÉLECTIONNÉ" if (s["checked"] or s["selected"]) else ""
                print(f"    • {s['aria']}: checked={s['checked']}, selected={s['selected']}{sel}")
        except Exception as e:
            print(f"  ✗ Pente 5% échoué : {e}")

        if screenshot:
            os.makedirs(SCREENSHOT_DIR, exist_ok=True)
            await page.screenshot(path=os.path.join(SCREENSHOT_DIR, "04_pente_5pct.png"))

        await browser.close()


async def test_generic_wapf_handler(headless: bool = False, screenshot: bool = False):
    """Test du handler générique _appliquer_options_wapf avec la pente."""
    print("\n" + "=" * 70)
    print("  TEST HANDLER GÉNÉRIQUE options_wapf")
    print("=" * 70)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        page = await browser.new_page(viewport={"width": 1400, "height": 900})

        await page.goto(PERGOLA_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)
        await fermer_popups_simple(page)

        # Sélectionner variation
        attrs = {
            "attribute_pa_largeur": "5m",
            "attribute_pa_profondeur": "4m",
            "attribute_pa_fixation": "independante",
            "attribute_pa_ventelle": "largeur",
            "attribute_pa_option": "carport",
        }
        await page.wait_for_selector("form.variations_form", timeout=15000)
        await page.wait_for_timeout(1500)
        await page.evaluate("""
            (attrs) => {
                for (var key in attrs) {
                    var sel = document.querySelector('select[name="' + key + '"]');
                    if (sel && typeof jQuery !== 'undefined') jQuery(sel).val(attrs[key]);
                }
                var keys = Object.keys(attrs);
                var lastSel = document.querySelector('select[name="' + keys[keys.length - 1] + '"]');
                if (lastSel && typeof jQuery !== 'undefined') jQuery(lastSel).trigger('change');
            }
        """, attrs)
        await page.wait_for_timeout(2000)

        # Importer et utiliser le handler générique
        from generateur_devis_3sites import _appliquer_options_wapf

        print("  Test 1 : options_wapf avec field_id nu")
        await _appliquer_options_wapf(page, {"e8cec8d": "15%"})

        # Vérifier
        post = await page.evaluate("""
            (fieldId) => {
                var c = document.querySelector('.wapf-field-container.field-' + fieldId);
                var labels = c ? c.querySelectorAll('div.wapf-swatch label') : [];
                var result = [];
                labels.forEach(function(l) {
                    var inp = l.querySelector('input');
                    result.push({
                        aria: l.getAttribute('aria-label'),
                        checked: inp ? inp.checked : false,
                    });
                });
                return result;
            }
        """, PENTE_FIELD_ID)
        for s in post:
            sel = " ← SÉLECTIONNÉ" if s["checked"] else ""
            print(f"    • {s['aria']}: checked={s['checked']}{sel}")

        pente_ok = any(s["checked"] and "15" in s.get("aria", "") for s in post)
        print(f"  {'✓' if pente_ok else '✗'} Handler générique {'OK' if pente_ok else 'ÉCHOUÉ'}")

        if screenshot:
            os.makedirs(SCREENSHOT_DIR, exist_ok=True)
            await page.screenshot(path=os.path.join(SCREENSHOT_DIR, "05_generic_handler.png"))

        await browser.close()


if __name__ == "__main__":
    headless = "--headless" in sys.argv
    screenshot = "--screenshot" in sys.argv

    print("Mode :", "headless" if headless else "navigateur visible")
    print("Screenshots :", "activés" if screenshot else "désactivés")

    asyncio.run(test_pente_selection(headless=headless, screenshot=screenshot))
    asyncio.run(test_pente_5_percent(headless=headless, screenshot=screenshot))
    asyncio.run(test_generic_wapf_handler(headless=headless, screenshot=screenshot))
