"""
wc_helpers — Fonctions utilitaires WooCommerce partagées entre les générateurs.

Contient les helpers d'interaction Playwright avec les sites WooCommerce :
- Sélection d'attributs (swatches wcboost / select caché)
- Match de variation depuis le JSON embarqué
- Ajout au panier (WAPF AJAX / clic natif)
- Vérification du panier
- Gestion des produits complémentaires
- Traitement du panier (code promo, livraison, date estimée)
- Génération du PDF via le formulaire WQG
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from generators.logging_config import get_logger
from utils_playwright import appliquer_code_promo, fermer_popups

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = get_logger(__name__)

DOWNLOAD_DIR: str = os.path.expanduser("~/Downloads")


async def select_wc_attribute(page: Page, attr_name: str, value: str) -> str | None:
    """Sélectionne un attribut WooCommerce (swatches wcboost ou select caché).

    Stratégie en 3 étapes :
    1. Clic sur le swatch ``wcboost li[data-value]``
    2. Fallback jQuery ``val() + trigger('change')``
    3. Fallback natif ``dispatchEvent``

    Args:
        page: Page Playwright active.
        attr_name: Nom de l'attribut WC (ex: ``attribute_pa_largeur``).
        value: Valeur à sélectionner (ex: ``"7m"``).

    Returns:
        Type de sélection utilisé (``"swatch_li"``, ``"jquery"``, etc.) ou ``None``.
    """
    swatch_clicked = await page.evaluate(f"""
        () => {{
            var item = document.querySelector('li.wcboost-variation-swatches__item[data-value="{value}"]');
            if (!item || item.classList.contains('disabled') || item.classList.contains('is-invalid')) {{
                var swatch = document.querySelector('[data-value="{value}"][class*="swatches"]');
                if (swatch) {{ swatch.click(); return 'swatch_legacy'; }}
                return false;
            }}
            if (item.classList.contains('selected')) return 'already_selected';
            item.click();
            return 'swatch_li';
        }}
    """)
    if swatch_clicked:
        if swatch_clicked != "already_selected":
            try:
                await page.wait_for_function(
                    "() => { var inp = document.querySelector('input.variation_id'); "
                    "return inp && inp.value && inp.value !== '0'; }",
                    timeout=3000,
                )
            except Exception:
                await page.wait_for_timeout(1500)
        return swatch_clicked

    set_ok = await page.evaluate(f"""
        () => {{
            var sel = document.querySelector('select[name="{attr_name}"]');
            if (!sel) return 'not_found';
            if (typeof jQuery !== 'undefined') {{
                jQuery(sel).val('{value}').trigger('change');
                return 'jquery';
            }}
            sel.value = '{value}';
            sel.dispatchEvent(new Event('change', {{bubbles: true}}));
            return 'native';
        }}
    """)
    await page.wait_for_timeout(800)
    return set_ok


async def match_wc_variation(page: Page, attrs: dict[str, str]) -> str | None:
    """Trouve et injecte la variation WC correspondant aux attributs.

    Lit ``data-product_variations`` de la page, trouve la variation matchante,
    et déclenche ``found_variation`` pour mettre à jour prix et bouton.

    Args:
        page: Page Playwright active.
        attrs: Dictionnaire d'attributs cibles
               (ex: ``{"attribute_pa_largeur": "7m", ...}``).

    Returns:
        Le ``variation_id`` (str) ou ``None`` si non trouvé.
    """
    attrs_js = str(attrs).replace("'", '"')
    result = await page.evaluate(f"""
        () => {{
            var form = document.querySelector('form.variations_form');
            if (!form) return 'no_form';
            var raw = form.getAttribute('data-product_variations');
            if (!raw || raw === 'false') return 'no_data';
            var variations;
            try {{ variations = JSON.parse(raw); }} catch(e) {{ return 'parse_error'; }}

            var target = {attrs_js};
            var found = null;
            for (var v of variations) {{
                var match = true;
                for (var key in target) {{
                    var va = v.attributes[key];
                    var ta = target[key];
                    if (va !== '' && ta !== '' && va !== ta) {{ match = false; break; }}
                }}
                if (match) {{ found = v; break; }}
            }}
            if (!found) return 'not_found';

            for (var key in target) {{
                var sel = document.querySelector('select[name="' + key + '"]');
                if (sel && typeof jQuery !== 'undefined') jQuery(sel).val(target[key]);
            }}

            var vidInp = document.querySelector('input.variation_id');
            if (vidInp) vidInp.value = found.variation_id;

            if (typeof jQuery !== 'undefined') {{
                jQuery(form).trigger('found_variation', [found]);
                jQuery('button.single_add_to_cart_button')
                    .removeAttr('disabled')
                    .removeClass('disabled wc-variation-selection-needed wc-no-matching-variations');
            }}
            return String(found.variation_id);
        }}
    """)
    return None if result in ("no_form", "no_data", "parse_error", "not_found") else result


async def ajouter_au_panier_wc(page: Page) -> bool:
    """Clique sur le bouton 'Ajouter au panier' via clic natif Playwright.

    Attend la stabilisation de l'image composite WAPF avant le clic,
    puis vérifie la confirmation d'ajout.

    Args:
        page: Page Playwright active sur une page produit WC.

    Returns:
        True si l'ajout a été confirmé, False si timeout.

    Raises:
        Exception: Si le bouton est désactivé (configuration incomplète).
    """
    btn = page.locator("button.single_add_to_cart_button").first

    is_disabled = await page.evaluate("""
        () => {
            const b = document.querySelector('button.single_add_to_cart_button');
            return !b || b.disabled || b.classList.contains('disabled')
                || b.classList.contains('wc-variation-is-unavailable');
        }
    """)
    if is_disabled:
        logger.warning("Bouton add-to-cart désactivé, attente 3s...")
        await page.wait_for_timeout(3000)
        is_disabled = await page.evaluate("""
            () => {
                const b = document.querySelector('button.single_add_to_cart_button');
                return !b || b.disabled || b.classList.contains('disabled')
                    || b.classList.contains('wc-variation-is-unavailable');
            }
        """)
        if is_disabled:
            raise Exception(
                "Bouton add-to-cart toujours désactivé — configuration WAPF incomplète"
            )

    _img_js = """
        () => {
            const img = document.querySelector('.woocommerce-product-gallery__image img');
            return img ? (img.getAttribute('data-large_image') || '') : '';
        }
    """
    prev_img = await page.evaluate(_img_js)
    if "wapf-layers" in prev_img:
        await page.wait_for_timeout(2000)
        prev_img = await page.evaluate(_img_js)
        for _ in range(6):
            await page.wait_for_timeout(500)
            cur_img = await page.evaluate(_img_js)
            if cur_img == prev_img:
                break
            prev_img = cur_img
        logger.info("Image composite WAPF stable : %s", prev_img.split("/")[-1])

    await btn.scroll_into_view_if_needed()
    await page.wait_for_timeout(300)
    await btn.click()

    added = False
    try:
        await page.wait_for_selector(
            ".woocommerce-message, .added_to_cart, .woocommerce-notices-wrapper a",
            timeout=8000,
        )
        added = True
    except Exception:
        await page.wait_for_timeout(3000)
    logger.info("Ajouté au panier")
    return added


async def ajouter_au_panier_wapf(page: Page, product_id: str) -> None:
    """Ajoute au panier via AJAX WC (``?wc-ajax=add_to_cart``).

    Contourne la validation JS de WAPF côté client.
    À utiliser sur les sites WAPF (terrasseenbois.fr).

    Args:
        page: Page Playwright active sur la page produit.
        product_id: ID du produit WooCommerce.

    Raises:
        RuntimeError: Si l'ajout AJAX échoue.
    """
    result = await page.evaluate(f"""
        async () => {{
            var form = document.querySelector('form.cart');
            if (!form) return {{error: 'no_form'}};
            var data = new URLSearchParams();
            form.querySelectorAll('input, select').forEach(function(el) {{
                if (el.disabled) return;
                if (el.type === 'radio' && !el.checked) return;
                if (el.type === 'checkbox' && !el.checked) return;
                if (el.name && el.value !== undefined) data.append(el.name, el.value);
            }});
            data.set('add-to-cart', '{product_id}');
            data.set('product_id', '{product_id}');
            try {{
                var resp = await fetch('/?wc-ajax=add_to_cart', {{
                    method: 'POST',
                    body: data,
                    credentials: 'same-origin',
                    headers: {{ 'Content-Type': 'application/x-www-form-urlencoded' }}
                }});
                var text = await resp.text();
                if (!text) return {{ok: true, note: 'empty_response'}};
                try {{
                    var json = JSON.parse(text);
                    return {{ok: !json.error, error: json.error || null}};
                }} catch(e) {{
                    return {{ok: true, note: 'non_json:' + text.substring(0, 50)}};
                }}
            }} catch(e) {{
                return {{error: e.message}};
            }}
        }}
    """)
    if result.get("error"):
        raise RuntimeError(f"AJAX add-to-cart failed: {result['error']}")
    logger.info("Ajouté au panier (AJAX WAPF)")
    await page.wait_for_timeout(2000)


async def verifier_panier(page: Page, site_url: str, nb_attendu: int) -> int:
    """Navigue vers le panier et vérifie le nombre d'items.

    Args:
        page: Page Playwright active.
        site_url: URL de base du site (ex: ``https://mapergolabois.fr``).
        nb_attendu: Nombre minimum d'items attendus.

    Returns:
        Nombre d'items réellement présents dans le panier.
    """
    cart_url = site_url.rstrip("/") + "/panier/"
    logger.info("Vérification panier (%s)", cart_url)
    await page.goto(cart_url, wait_until="domcontentloaded", timeout=20000)
    await page.wait_for_timeout(2000)

    nb_items = await page.evaluate("""
        () => {
            const rows = document.querySelectorAll(
                '.woocommerce-cart-form__cart-item, tr.cart_item'
            );
            return rows.length;
        }
    """)

    if nb_items >= nb_attendu:
        logger.info("Panier OK : %d ligne(s)", nb_items)
    else:
        logger.warning("Panier : %d ligne(s) au lieu de %d", nb_items, nb_attendu)
    return nb_items


async def traiter_panier(
    page: Page,
    site_url: str,
    code_promo: str = "",
    mode_livraison: str = "",
) -> str:
    """Traite le panier : code promo, livraison, date estimée.

    Args:
        page: Page Playwright active.
        site_url: URL de base du site.
        code_promo: Code promo à appliquer (vide = aucun).
        mode_livraison: ``""`` | ``"retrait"`` | ``"livraison"``.

    Returns:
        Date de livraison estimée (str), ou chaîne vide.
    """
    panier_url = site_url.rstrip("/") + "/panier/"
    try:
        await page.goto(panier_url, wait_until="load", timeout=25000)
        await page.wait_for_timeout(1500)
    except Exception as e:
        logger.warning("Impossible de charger le panier : %s", e)
        return ""

    # 1. Code promo
    await appliquer_code_promo(page, code_promo)

    # 2. Méthode de livraison
    if mode_livraison:
        mot_cle = "Retrait" if "retrait" in mode_livraison.lower() else "Livraison"
        logger.info("Sélection livraison '%s'...", mot_cle)
        try:
            result = await page.evaluate(
                """(motCle) => {
                    const radios = document.querySelectorAll('input[name^="shipping_method"]');
                    for (const r of radios) {
                        const lbl = document.querySelector(`label[for="${r.id}"]`);
                        const text = lbl ? lbl.textContent : (r.parentElement?.textContent || '');
                        if (text.includes(motCle)) {
                            if (!r.checked) { r.click(); return 'clicked:' + text.trim().substring(0, 80); }
                            return 'already:' + text.trim().substring(0, 80);
                        }
                    }
                    for (const r of radios) {
                        if ((r.value || '').toLowerCase().includes(motCle.toLowerCase()) ||
                            (r.id || '').toLowerCase().includes(motCle.toLowerCase())) {
                            if (!r.checked) r.click();
                            return 'clicked_by_id:' + (r.value || r.id);
                        }
                    }
                    return 'not_found';
                }""",
                mot_cle,
            )
            if result.startswith("clicked"):
                logger.info("Livraison sélectionnée : %s", result.split(":", 1)[1])
                await page.wait_for_timeout(3000)
            elif result.startswith("already"):
                logger.info("Livraison déjà sélectionnée : %s", result.split(":", 1)[1])
            else:
                logger.warning("Méthode '%s' introuvable dans le panier", mot_cle)
        except Exception as e:
            logger.warning("Erreur sélection livraison : %s", e)

    # 3. Date de livraison estimée
    date_livraison = ""
    try:
        date_livraison = await page.evaluate("""
            () => {
                const specific = [
                    '.delivery-date', '.estimated-delivery',
                    '[class*="delivery-date"]', '.order-delivery-date',
                ];
                for (const sel of specific) {
                    const el = document.querySelector(sel);
                    if (el && el.textContent.trim()) return el.textContent.trim();
                }
                const zones = document.querySelectorAll(
                    '.woocommerce-shipping-totals, #shipping_method, .cart_totals, .cart-collaterals'
                );
                for (const zone of zones) {
                    const text = zone.innerText || zone.textContent || '';
                    const m1 = text.match(/\\b(\\d{1,2}[\\/\\-]\\d{1,2}[\\/\\-]\\d{4})\\b/);
                    if (m1) return m1[0];
                    const m2 = text.match(/(?:avant le|livr[ée]|estimé)[^\\n]{0,30}(\\d{1,2}\\s+\\w{3,}\\s+\\d{4})/i);
                    if (m2) return m2[1];
                }
                const full = document.body ? (document.body.innerText || '') : '';
                const m3 = full.match(/(?:livr[ée][es]?|estimé[e]?s?|délai)[^\\n]{0,60}(\\d{1,2}[\\/\\-]\\d{1,2}[\\/\\-]\\d{4})/i);
                if (m3) return m3[1];
                return '';
            }
        """) or ""
        if date_livraison:
            m = re.search(r"\d{1,2}[\/\-]\d{1,2}[\/\-]\d{4}", date_livraison)
            if m:
                date_livraison = m.group(0)
            logger.info("Date de livraison estimée : %s", date_livraison)
    except Exception as e:
        logger.warning("Impossible de scraper la date de livraison : %s", e)

    return date_livraison


async def generer_devis_via_generateur(
    page: Page,
    site_url: str,
    client_nom: str,
    client_prenom: str,
    client_email: str,
    client_telephone: str,
    client_adresse: str,
    filepath: str,
    devis_path: str = "/generateur-de-devis/",
) -> str:
    """Génère le PDF via le formulaire WQG (#quote-form).

    Navigue vers la page du générateur de devis, remplit le formulaire client,
    soumet le formulaire et télécharge le PDF résultant.

    Args:
        page: Page Playwright active.
        site_url: URL de base du site.
        client_nom: Nom de famille du client.
        client_prenom: Prénom du client.
        client_email: Email du client.
        client_telephone: Téléphone du client.
        client_adresse: Adresse postale du client.
        filepath: Chemin de destination du PDF.
        devis_path: Chemin relatif de la page devis (défaut ``/generateur-de-devis/``).

    Returns:
        Chemin absolu du PDF généré.

    Raises:
        Exception: Si le PDF n'a pas pu être téléchargé.
    """
    devis_url = site_url.rstrip("/") + devis_path
    logger.info("Navigation vers %s", devis_url)
    try:
        await page.goto(devis_url, wait_until="domcontentloaded", timeout=30000)
    except Exception:
        pass
    await page.wait_for_timeout(2000)
    await fermer_popups(page)

    await page.wait_for_selector("#quote-form", timeout=10000)

    logger.info("Remplissage formulaire client")
    await page.locator("#quote-name").fill(client_nom)
    await page.locator("#quote-surname").fill(client_prenom)
    await page.locator("#quote-email").fill(client_email)
    await page.locator("#quote-phone").fill(client_telephone)
    await page.locator("#quote-address").fill(client_adresse)
    await page.wait_for_timeout(500)

    # Supprimer popups résiduels
    await page.evaluate("""
        () => {
            document.querySelectorAll(
                '.popup-modal, #popup-modal, .modal, .pum-overlay, .popup-backdrop, .backdrop'
            ).forEach(el => {
                el.classList.remove('open');
                el.style.display = 'none';
                if (el.parentNode) el.parentNode.removeChild(el);
            });
            document.body.style.overflow = '';
        }
    """)
    await page.wait_for_timeout(500)

    logger.info("Soumission du formulaire")
    Path(DOWNLOAD_DIR).mkdir(parents=True, exist_ok=True)

    _pdf_captured = asyncio.Event()
    _pdf_bytes: list[bytes] = []

    async def _on_response_pdf(response: Any) -> None:
        try:
            ct = response.headers.get("content-type", "")
            cd = response.headers.get("content-disposition", "")
            if "application/pdf" in ct or ("attachment" in cd and "pdf" in cd.lower()):
                data = await response.body()
                if len(data) > 1000:
                    _pdf_bytes.append(data)
                    _pdf_captured.set()
        except Exception:
            pass

    page.on("response", _on_response_pdf)
    try:
        async with page.expect_download(timeout=90000) as download_info:
            await page.evaluate(
                "() => document.querySelector('#quote-form').submit()"
            )
        download = await download_info.value
        await download.save_as(filepath)
    except Exception as e_dl:
        try:
            await asyncio.wait_for(_pdf_captured.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            pass
        if _pdf_bytes:
            with open(filepath, "wb") as f:
                f.write(_pdf_bytes[-1])
            logger.info(
                "PDF récupéré via intercepteur réseau (%d KB)",
                len(_pdf_bytes[-1]) // 1024,
            )
        else:
            raise Exception(f"PDF non téléchargé : {e_dl}") from e_dl
    finally:
        try:
            page.remove_listener("response", _on_response_pdf)
        except Exception:
            pass

    size_kb = os.path.getsize(filepath) / 1024
    logger.info("PDF généré : %s (%.0f KB)", filepath, size_kb)
    return filepath


async def generer_pdf_panier(
    page: Page,
    site_url: str,
    filepath: str,
    client_nom: str = "",
    client_prenom: str = "",
    client_email: str = "",
    client_telephone: str = "",
    client_adresse: str = "",
) -> str:
    """Fallback PDF : génère un PDF A4 depuis la page panier.

    Utilisé quand le générateur officiel WQG est indisponible (reCaptcha, etc.).

    Args:
        page: Page Playwright active.
        site_url: URL de base du site.
        filepath: Chemin de destination du PDF.
        client_*: Coordonnées client injectées en bandeau.

    Returns:
        Chemin absolu du PDF généré.
    """
    panier_url = site_url.rstrip("/") + "/panier/"
    logger.info("PDF fallback depuis %s", panier_url)
    try:
        await page.goto(panier_url, wait_until="domcontentloaded", timeout=20000)
    except Exception:
        pass
    await page.wait_for_timeout(2000)
    await fermer_popups(page)

    if client_nom or client_prenom:
        lines = []
        if client_prenom or client_nom:
            lines.append(
                f"<strong>Client :</strong> {client_prenom} {client_nom}".strip()
            )
        if client_email:
            lines.append(f"<strong>Email :</strong> {client_email}")
        if client_telephone:
            lines.append(f"<strong>Téléphone :</strong> {client_telephone}")
        if client_adresse:
            lines.append(f"<strong>Adresse :</strong> {client_adresse}")
        lines.append(
            f"<strong>Devis du :</strong> {time.strftime('%d/%m/%Y')}"
        )
        header_html = "<br>".join(lines)
        await page.evaluate(f"""
            () => {{
                var div = document.createElement('div');
                div.innerHTML = '<div style="border:2px solid #333;padding:12px 16px;'
                    + 'margin:10px 0;font-family:sans-serif;font-size:14px;'
                    + 'background:#f9f9f9;">{header_html}</div>';
                var body = document.querySelector('body');
                if (body) body.insertBefore(div, body.firstChild);
            }}
        """)

    Path(DOWNLOAD_DIR).mkdir(parents=True, exist_ok=True)
    await page.pdf(
        path=filepath,
        format="A4",
        print_background=True,
        margin={"top": "1cm", "bottom": "1cm", "left": "1.5cm", "right": "1.5cm"},
    )
    size_kb = os.path.getsize(filepath) / 1024
    logger.info("PDF panier : %s (%.0f KB)", filepath, size_kb)
    return filepath


async def ajouter_produits_complementaires(
    page: Page,
    produits_list: list[dict[str, Any]],
    site_url: str = "",
) -> int:
    """Ajoute des produits WC supplémentaires dans le panier courant.

    Args:
        page: Page Playwright active.
        produits_list: Liste de produits, chacun avec
            ``url``, ``variation_id``, ``quantite``, ``attribut_selects``, ``description``.
        site_url: URL de base du site (si fourni, vérifie le panier après chaque ajout).

    Returns:
        Nombre de produits effectivement ajoutés au panier.
    """
    confirmed_count = 0
    for i, prod in enumerate(produits_list):
        url = prod.get("url", "").strip()
        variation_id = int(prod.get("variation_id") or 0)
        quantite = int(prod.get("quantite") or 1)
        attribut_selects = prod.get("attribut_selects") or {}
        description = prod.get("description") or url.split("/produit/")[-1].strip("/")

        if not url:
            continue

        logger.info("Produit complémentaire : %s (x%d)", description, quantite)

        async def _configurer_page_et_ajouter() -> None:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(1500)
            await fermer_popups(page)

            if attribut_selects:
                for attr_name, attr_value in attribut_selects.items():
                    result = await select_wc_attribute(page, attr_name, attr_value)
                    logger.debug("Sélection %s=%s -> %s", attr_name, attr_value, result)

            # Autocontrôle swatches
            if attribut_selects:
                for _pass in range(2):
                    mismatches = await page.evaluate(
                        """
                        (attrs) => {
                            var missing = [];
                            for (var val of Object.values(attrs)) {
                                var item = document.querySelector(
                                    'li.wcboost-variation-swatches__item[data-value="' + val + '"]'
                                );
                                if (item && !item.classList.contains('selected')) missing.push(val);
                            }
                            return missing;
                        }
                    """,
                        list(attribut_selects.values()),
                    )
                    if not mismatches:
                        break
                    logger.warning("Swatches non sélectionnés %s — reclic...", mismatches)
                    for attr_name, attr_value in attribut_selects.items():
                        if attr_value in mismatches:
                            await select_wc_attribute(page, attr_name, attr_value)

            selected_var = await page.evaluate("""
                () => {
                    var inp = document.querySelector('input.variation_id, input[name="variation_id"]');
                    return inp ? inp.value : '0';
                }
            """)
            logger.debug("variation_id sélectionné : %s", selected_var)
            try:
                qty = page.locator('input.qty, input[name="quantity"]').first
                await qty.fill(str(quantite))
                await qty.dispatch_event("change")
            except Exception:
                pass
            await fermer_popups(page)
            await ajouter_au_panier_wc(page)

        confirmed = False
        for attempt in range(2):
            try:
                await _configurer_page_et_ajouter()
                if site_url:
                    nb = await verifier_panier(
                        page, site_url, nb_attendu=confirmed_count + 1
                    )
                    if nb >= confirmed_count + 1:
                        confirmed = True
                        break
                    if attempt == 0:
                        logger.warning("Produit absent du panier — nouvelle tentative...")
                else:
                    confirmed = True
                    break
            except Exception as e:
                logger.warning("Tentative %d/2 échouée : %s", attempt + 1, e)

        if confirmed:
            confirmed_count += 1
            logger.info("%s confirmé dans le panier (x%d)", description, quantite)
        else:
            logger.warning(
                "%s potentiellement absent du panier après 2 tentatives", description
            )

    return confirmed_count
