#!/usr/bin/env python3
"""
Générateur automatique de devis — 3 nouveaux sites
- mapergolabois.fr  (pergola bois en kit)
- terrasseenbois.fr (configurateur terrasse WAPF)
- cloturebois.fr    (kit clôture classique / moderne)

Ces sites utilisent WooCommerce standard (pas de WPC Booster).
Le devis est généré en PDF depuis le panier avec les infos client injectées.

Usage depuis le MCP server :
    from generateur_devis_3sites import generer_devis_pergola, ...
"""

import asyncio
import json
import math
import os
import time
from pathlib import Path

try:
    from playwright.async_api import async_playwright
except ImportError:
    import sys
    print("❌ Playwright non installé.")
    sys.exit(1)

from utils_playwright import fermer_popups, appliquer_code_promo

DOWNLOAD_DIR = os.path.expanduser("~/Downloads")


# ═══════════════════════════════════════════════════════════════
# MAPPING WAPF — TERRASSE
# ═══════════════════════════════════════════════════════════════
# Longueurs disponibles par essence (m) :
#   PIN 21mm Vert  : "3.3", "4.2", "5.1"
#   PIN 27mm Vert  : "2.4", "2.75", "3.3", "3.9", "4.2", "4.5", "4.8", "5.1"
#   PIN 27mm Marron: "3", "3.3", "3.6", "4.2", "4.8", "5.1", "5.4"
#   PIN 27mm Gris  : "3.6", "4.2", "4.8", "5.1", "5.4"
#   FRAKE          : "3.05"
#   JATOBA         : "1.85", "2.15", "2.45", "2.75", "3.35", "3.65", "4", "4.25", "4.55", "5.5", "6.4"
#   CUMARU         : "1.85", "2.15", "2.45", "2.75", "3.05", "3.35", "3.65", "4", "4.3", "4.55"
#   PADOUK         : "1.25", "1.55", "1.85", "2.15", "2.45", "2.75", "3.35", "3.65"
#   IPE            : "0.95", "1.25"

TERRASSE_ESSENCE_MAP = {
    "PIN 21mm Autoclave Vert":   ("e3l5p", "field_65c1ebe60b472"),
    "PIN 27mm Autoclave Vert":   ("stwhd", "field_65c1f585a5289"),
    "PIN 27mm Autoclave Marron": ("7zriy", "field_65c1f6b1e8f8e"),
    "PIN 27mm Autoclave Gris":   ("zf38s", "field_65c1f6e97c942"),
    "PIN 27mm Thermotraité":     ("jkbcy", "field_65c1f8a851cd3"),
    "FRAKE":  ("imw9v", "field_65c1f822125ec"),
    "JATOBA": ("vzvbh", "field_65c1f6e806c40"),
    "CUMARU": ("dvrbt", "field_65c1f80e4202c"),
    "PADOUK": ("q062n", "field_65c1f823a4def"),
    "IPE":    ("vyalq", "field_65c1f823984c6"),
}

# Lambourdes — type
TERRASSE_LAMBOURDES_MAP = {
    "Non":                       "h2t80",
    "Pin autoclave Vert 45x70":  "2p3bp",
    "Pin autoclave Vert 45x145": "izhh7",
    "Bois exotique Niove 40x60": "qiemc",
}

# Longueur lambourdes — champ dépend du type (Pin ou Niove)
# Pin : "3", "4.2", "4.8", "5.1"
# Niove : "1.55", "1.85", "2.15", "3.05", "3.65"
TERRASSE_LAMBOURDES_LON_PIN = {
    "3": "rsp2f", "4.2": "bywnd", "4.8": "yo0r1", "5.1": "fa3gc",
}
TERRASSE_LAMBOURDES_LON_NIOVE = {
    "1.55": "esjqv", "1.85": "v3x8w", "2.15": "6abob", "3.05": "nk52u", "3.65": "klx0s",
}

# Plots — 3 champs selon contexte (sans lambourdes / avec lambourdes pin / avec lambourdes niove)
TERRASSE_PLOTS_SANS_LAMB = {
    "2 à 4 cm": "0ua53", "4 à 6 cm": "dksd2", "6 à 9 cm": "btu51",
    "9 à 15 cm": "nvwv1", "15 à 26 cm": "6af38", "NON": "apusa",
}
TERRASSE_PLOTS_LAMB_PIN = {
    "2 à 4 cm": "wypcd", "4 à 6 cm": "0lt48", "6 à 9 cm": "rumiw",
    "9 à 15 cm": "kehag", "15 à 26 cm": "zcpu0", "NON": "mltmc",
}
TERRASSE_PLOTS_LAMB_NIOVE = {
    "2 à 4 cm": "ijy3u", "4 à 6 cm": "xpqfg", "6 à 9 cm": "q2sfn",
    "9 à 15 cm": "nvma6", "15 à 26 cm": "drutj", "NON": "vu2bq",
}

# Visserie
TERRASSE_VISSERIE_MAP = {
    "Vis Inox 5x50mm":           "mymdk",
    "Vis Inox 5x60mm":           "4mrt2",
    "Fixations invisible Hapax": "cmo63",
    "Non":                       "uz0h2",
}


# ═══════════════════════════════════════════════════════════════
# HELPERS COMMUNS
# ═══════════════════════════════════════════════════════════════

# Alias pour compatibilité descendante avec tous les appels internes
_fermer_popups = fermer_popups


async def _select_wc_attribute(page, attr_name: str, value: str):
    """Sélectionne un attribut WooCommerce (fonctionne même si le select est caché par wcboost).

    Stratégie :
    1. Clic sur le swatch wcboost li.wcboost-variation-swatches__item[data-value] (structure réelle)
    2. Fallback : jQuery val() + trigger('change') sur le select caché
    3. Fallback : dispatchEvent natif
    """
    # Essai 1 : clic direct sur le li avec data-value (structure réelle wcboost sur terrasseenbois.fr)
    swatch_clicked = await page.evaluate(f"""
        () => {{
            var item = document.querySelector('li.wcboost-variation-swatches__item[data-value="{value}"]');
            if (!item || item.classList.contains('disabled') || item.classList.contains('is-invalid')) {{
                // Fallback : ancienne structure
                var swatch = document.querySelector('[data-value="{value}"][class*="swatches"]');
                if (swatch) {{ swatch.click(); return 'swatch_legacy'; }}
                return false;
            }}
            // Si déjà sélectionné → ne pas cliquer (toggle = déselection)
            if (item.classList.contains('selected')) return 'already_selected';
            item.click();
            return 'swatch_li';
        }}
    """)
    if swatch_clicked:
        if swatch_clicked != 'already_selected':
            # Attendre que WC traite la variation (variation_id != 0) — plus fiable qu'un délai fixe
            try:
                await page.wait_for_function(
                    "() => { var inp = document.querySelector('input.variation_id'); return inp && inp.value && inp.value !== '0'; }",
                    timeout=3000,
                )
            except Exception:
                await page.wait_for_timeout(1500)  # fallback si pas de variation_id (produit simple)
        return swatch_clicked

    # Essai 2 : jQuery sur le select caché
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


async def _match_wc_variation(page, attrs: dict) -> str | None:
    """Trouve et injecte directement la variation WooCommerce qui correspond aux attributs donnés.

    Lit le JSON data-product_variations de la page, cherche la variation matchante,
    déclenche l'event found_variation pour mettre à jour prix/bouton.
    Retourne le variation_id (str) ou None si non trouvé.

    attrs : dict complet, ex:
        {'attribute_pa_largeur': '7m', 'attribute_pa_profondeur': '5m', ...}
    Seules les clés présentes dans attrs sont comparées (les autres doivent être '' pour "any").
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
                    // '' dans WooCommerce = "any" (match tout)
                    if (va !== '' && ta !== '' && va !== ta) {{ match = false; break; }}
                }}
                if (match) {{ found = v; break; }}
            }}
            if (!found) return 'not_found';

            // Mettre à jour les selects visuellement
            for (var key in target) {{
                var sel = document.querySelector('select[name="' + key + '"]');
                if (sel && typeof jQuery !== 'undefined') jQuery(sel).val(target[key]);
            }}

            // Injecter le variation_id
            var vidInp = document.querySelector('input.variation_id');
            if (vidInp) vidInp.value = found.variation_id;

            // Déclencher found_variation (WooCommerce met à jour prix + bouton)
            if (typeof jQuery !== 'undefined') {{
                jQuery(form).trigger('found_variation', [found]);
                // Activer le bouton
                jQuery('button.single_add_to_cart_button')
                    .removeAttr('disabled')
                    .removeClass('disabled wc-variation-selection-needed wc-no-matching-variations');
            }}
            return String(found.variation_id);
        }}
    """)
    return None if result in ('no_form', 'no_data', 'parse_error', 'not_found') else result


async def _generer_pdf_panier(
    page, site_url: str, filepath: str,
    client_nom: str = "", client_prenom: str = "",
    client_email: str = "", client_telephone: str = "", client_adresse: str = "",
) -> str:
    """
    Fallback PDF : navigue vers /panier/, injecte les coordonnées client,
    et génère un PDF via page.pdf() A4.
    Utilisé quand le générateur officiel est indisponible (reCaptcha, etc.).
    """
    panier_url = site_url.rstrip('/') + '/panier/'
    print(f"  ➜ {panier_url} (PDF fallback)")
    try:
        await page.goto(panier_url, wait_until="domcontentloaded", timeout=20000)
    except Exception:
        pass
    await page.wait_for_timeout(2000)
    await _fermer_popups(page)

    # Injecter un bandeau client en haut de la page
    if client_nom or client_prenom:
        lines = []
        if client_prenom or client_nom:
            lines.append(f"<strong>Client :</strong> {client_prenom} {client_nom}".strip())
        if client_email:
            lines.append(f"<strong>Email :</strong> {client_email}")
        if client_telephone:
            lines.append(f"<strong>Téléphone :</strong> {client_telephone}")
        if client_adresse:
            lines.append(f"<strong>Adresse :</strong> {client_adresse}")
        import time as _time
        lines.append(f"<strong>Devis du :</strong> {_time.strftime('%d/%m/%Y')}")
        header_html = "<br>".join(lines)
        await page.evaluate(f"""
            () => {{
                var div = document.createElement('div');
                div.innerHTML = '<div style="border:2px solid #333;padding:12px 16px;margin:10px 0;font-family:sans-serif;font-size:14px;background:#f9f9f9;">{header_html}</div>';
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
    print(f"  ✓ PDF panier : {filepath} ({size_kb:.0f} KB)")
    return filepath


async def _ajouter_au_panier_wapf(page, product_id: str):
    """
    Ajoute au panier via AJAX WooCommerce (?wc-ajax=add_to_cart).
    Contourne la validation JS de WAPF côté client qui bloque le bouton normal.
    À utiliser sur les sites WAPF (terrasseenbois.fr).
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
                    // Réponse non-JSON (HTML redirect) — considéré comme succès
                    return {{ok: true, note: 'non_json:' + text.substring(0, 50)}};
                }}
            }} catch(e) {{
                return {{error: e.message}};
            }}
        }}
    """)
    if result.get('error'):
        raise RuntimeError(f"AJAX add-to-cart failed: {result['error']}")
    print("    ✓ Ajouté au panier (AJAX WAPF)")
    await page.wait_for_timeout(2000)


async def _ajouter_au_panier_wc(page):
    """Clique sur le bouton 'Ajouter au panier' via Playwright (clic natif isTrusted=true).

    Playwright simule un vrai clic utilisateur : isTrusted=true, séquence
    mousedown/mouseup/click complète — identique à un humain sur le site.
    La galerie WC retourne toujours back.png (fixe) donc le scroll n'affecte pas WQG.
    """
    btn = page.locator('button.single_add_to_cart_button').first  # .first → évite strict mode si 2 boutons (ex: cloturebois.fr)

    # Vérifier que le bouton est activé (pas désactivé par WAPF champs manquants)
    is_disabled = await page.evaluate("""
        () => {
            const b = document.querySelector('button.single_add_to_cart_button');
            return !b || b.disabled || b.classList.contains('disabled') || b.classList.contains('wc-variation-is-unavailable');
        }
    """)
    if is_disabled:
        print("    ⚠ Bouton add-to-cart désactivé — attente 3s supplémentaires...")
        await page.wait_for_timeout(3000)
        is_disabled = await page.evaluate("""
            () => {
                const b = document.querySelector('button.single_add_to_cart_button');
                return !b || b.disabled || b.classList.contains('disabled') || b.classList.contains('wc-variation-is-unavailable');
            }
        """)
        if is_disabled:
            raise Exception("Bouton add-to-cart toujours désactivé — configuration WAPF incomplète")

    # Attendre que l'image composite WAPF (data-large_image) se stabilise avant le clic.
    # WAPF génère l'image composite via AJAX après chaque sélection.
    # WQG capture data-large_image au moment du clic add-to-cart.
    # Stratégie : attendre 2s (temps AJAX) puis confirmer la stabilité.
    _img_js = """
        () => {
            const img = document.querySelector('.woocommerce-product-gallery__image img');
            return img ? (img.getAttribute('data-large_image') || '') : '';
        }
    """
    prev_img = await page.evaluate(_img_js)
    if 'wapf-layers' in prev_img:
        await page.wait_for_timeout(2000)  # délai minimal AJAX WAPF
        prev_img = await page.evaluate(_img_js)
        for _ in range(6):  # confirmer stabilité (max +3s)
            await page.wait_for_timeout(500)
            cur_img = await page.evaluate(_img_js)
            if cur_img == prev_img:
                break
            prev_img = cur_img
        print(f"    ⚙ Image composite WAPF stable : {prev_img.split('/')[-1]}")

    # Clic natif Playwright : scroll + click (isTrusted=true, comme un humain)
    await btn.scroll_into_view_if_needed()
    await page.wait_for_timeout(300)
    await btn.click()

    added = False
    try:
        await page.wait_for_selector(
            '.woocommerce-message, .added_to_cart, .woocommerce-notices-wrapper a',
            timeout=8000,
        )
        added = True
    except Exception:
        await page.wait_for_timeout(3000)
    print("    ✓ Ajouté au panier")
    return added


async def _traiter_panier(
    page, site_url: str,
    code_promo: str = "",
    mode_livraison: str = "",
) -> str:
    """Traite le panier : code promo, méthode de livraison, date estimée.

    Navigue vers /panier/ pour appliquer le code promo, changer la méthode
    de livraison, et scraper la date de livraison estimée.

    mode_livraison : "" (ne pas changer) | "retrait" (local pickup)
                     | "livraison" (transport à domicile)

    Returns: date_livraison (str) — date estimée affichée dans le panier, ou ""
    """
    panier_url = site_url.rstrip("/") + "/panier/"
    try:
        await page.goto(panier_url, wait_until="load", timeout=25000)
        await page.wait_for_timeout(1500)
    except Exception as e:
        print(f"    ⚠ Impossible de charger le panier ({e})")
        return

    # ── 1. Code promo ────────────────────────────────────────────────────────
    await appliquer_code_promo(page, code_promo)

    # ── 2. Méthode de livraison ───────────────────────────────────────────────
    if mode_livraison:
        mot_cle = "Retrait" if "retrait" in mode_livraison.lower() else "Livraison"
        print(f"  ➜ Livraison : sélection '{mot_cle}'...")
        try:
            result = await page.evaluate(
                """(motCle) => {
                    const radios = document.querySelectorAll('input[name^="shipping_method"]');
                    for (const r of radios) {
                        const lbl = document.querySelector(`label[for="${r.id}"]`);
                        const text = lbl ? lbl.textContent : (r.parentElement?.textContent || '');
                        if (text.includes(motCle)) {
                            if (!r.checked) {
                                r.click();
                                return 'clicked:' + text.trim().substring(0, 80);
                            }
                            return 'already:' + text.trim().substring(0, 80);
                        }
                    }
                    // Fallback: chercher par value/id contenant le mot
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
                print(f"    ✅ Livraison sélectionnée : {result.split(':',1)[1]}")
                # Attendre la mise à jour AJAX du panier
                await page.wait_for_timeout(3000)
            elif result.startswith("already"):
                print(f"    ✓ Livraison déjà sélectionnée : {result.split(':',1)[1]}")
            else:
                print(f"    ⚠ Méthode de livraison '{mot_cle}' introuvable dans le panier")
        except Exception as e:
            print(f"    ⚠ Erreur sélection livraison : {e}")

    # ── 3. Date de livraison estimée ──────────────────────────────────────────
    date_livraison = ""
    try:
        date_livraison = await page.evaluate("""
            () => {
                // Sélecteurs spécifiques plugin date
                const specific = [
                    '.delivery-date', '.estimated-delivery',
                    '[class*="delivery-date"]', '.order-delivery-date',
                ];
                for (const sel of specific) {
                    const el = document.querySelector(sel);
                    if (el && el.textContent.trim()) return el.textContent.trim();
                }
                // Chercher pattern date dans la section livraison
                const zones = document.querySelectorAll(
                    '.woocommerce-shipping-totals, #shipping_method, .cart_totals, .cart-collaterals'
                );
                for (const zone of zones) {
                    const text = zone.innerText || zone.textContent || '';
                    // DD/MM/YYYY ou DD-MM-YYYY
                    const m1 = text.match(/\\b(\\d{1,2}[\\/\\-]\\d{1,2}[\\/\\-]\\d{4})\\b/);
                    if (m1) return m1[0];
                    // "avant le X mois YYYY" / "livré le X mois YYYY"
                    const m2 = text.match(/(?:avant le|livr[ée]|estimé)[^\\n]{0,30}(\\d{1,2}\\s+\\w{3,}\\s+\\d{4})/i);
                    if (m2) return m2[1];
                }
                // Chercher dans tout le corps (large filet)
                const full = document.body ? (document.body.innerText || '') : '';
                const m3 = full.match(/(?:livr[ée][es]?|estimé[e]?s?|délai)[^\\n]{0,60}(\\d{1,2}[\\/\\-]\\d{1,2}[\\/\\-]\\d{4})/i);
                if (m3) return m3[1];
                return '';
            }
        """) or ""
        if date_livraison:
            # Extraire uniquement la date DD/MM/YYYY si le sélecteur a retourné tout le texte de l'élément
            import re as _re
            _m = _re.search(r'\d{1,2}[\/\-]\d{1,2}[\/\-]\d{4}', date_livraison)
            if _m:
                date_livraison = _m.group(0)
            print(f"  ➜ Date de livraison estimée : {date_livraison}")
    except Exception as e:
        print(f"  ⚠ Impossible de scraper la date de livraison : {e}")

    return date_livraison


async def _generer_devis_via_generateur(
    page, site_url: str,
    client_nom: str, client_prenom: str,
    client_email: str, client_telephone: str, client_adresse: str,
    filepath: str,
    devis_path: str = '/generateur-de-devis/',
) -> str:
    """
    Helper commun — valable pour tous les sites disposant d'un formulaire WQG (#quote-form) :
      mapergolabois.fr, terrasseenbois.fr, cloturebois.fr, studio-francais.fr
      abri-francais.fr (/generer-un-devis/ — même formulaire WQG)

    Navigue vers devis_path (défaut /generateur-de-devis/), remplit le formulaire client (#quote-form)
    et télécharge le PDF officiel du site via form.submit().
    """
    devis_url = site_url.rstrip('/') + devis_path
    print(f"  ➜ {devis_url}")
    try:
        await page.goto(devis_url, wait_until="domcontentloaded", timeout=30000)
    except Exception:
        pass  # Timeout partiel OK, on continue si le DOM est chargé
    await page.wait_for_timeout(2000)
    await _fermer_popups(page)

    await page.wait_for_selector('#quote-form', timeout=10000)

    print("  ➜ Remplissage formulaire client")
    await page.locator('#quote-name').fill(client_nom)
    await page.locator('#quote-surname').fill(client_prenom)
    await page.locator('#quote-email').fill(client_email)
    await page.locator('#quote-phone').fill(client_telephone)
    await page.locator('#quote-address').fill(client_adresse)
    await page.wait_for_timeout(500)

    # Supprimer tout popup/modal résiduel pouvant bloquer le clic
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

    print("  ➜ Soumission du formulaire générateur de devis")
    Path(DOWNLOAD_DIR).mkdir(parents=True, exist_ok=True)

    # Intercepteur réseau — fallback headless : download event parfois absent en mode sans UI
    _pdf_captured = asyncio.Event()
    _pdf_bytes: list[bytes] = []

    async def _on_response_pdf(response):
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
            # form.submit() bypasse les handlers JS (reCaptcha) et déclenche le POST direct vers admin-post.php
            await page.evaluate("() => document.querySelector('#quote-form').submit()")
        download = await download_info.value
        await download.save_as(filepath)
        # Attendre que le fichier soit complètement écrit sur disque
        await page.wait_for_timeout(2000)
    except Exception as e_dl:
        # Headless mode : le download event peut ne pas se déclencher même si le PDF est reçu
        try:
            await asyncio.wait_for(_pdf_captured.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            pass
        if _pdf_bytes:
            with open(filepath, "wb") as f:
                f.write(_pdf_bytes[-1])
            print(f"  ℹ PDF récupéré via intercepteur réseau ({len(_pdf_bytes[-1]) // 1024} KB)")
        else:
            raise Exception(f"PDF non téléchargé : {e_dl}")
    finally:
        try:
            page.remove_listener("response", _on_response_pdf)
        except Exception:
            pass

    size_kb = os.path.getsize(filepath) / 1024
    print(f"  ✓ PDF : {filepath} ({size_kb:.0f} KB)")
    return filepath


async def _verifier_panier(page, site_url: str, nb_attendu: int) -> int:
    """Navigue vers le panier, attend que les produits soient chargés et retourne le nb d'items.

    Appelé après chaque ajout au panier pour s'assurer que l'item est bien enregistré
    côté serveur avant de passer au produit suivant.
    Affiche un récapitulatif détaillé de chaque ligne (nom + quantité + prix).
    """
    cart_url = site_url.rstrip("/") + "/panier/"
    print(f"    ➜ Vérification panier ({cart_url})")
    await page.goto(cart_url, wait_until="domcontentloaded", timeout=20000)
    await page.wait_for_timeout(2000)

    # Récupérer le détail de chaque ligne du panier
    cart_details = await page.evaluate("""
        () => {
            const rows = document.querySelectorAll(
                '.woocommerce-cart-form__cart-item, tr.cart_item'
            );
            const items = [];
            for (const row of rows) {
                const nameEl = row.querySelector('.product-name a, td.product-name a');
                const qtyEl = row.querySelector('input.qty, .product-quantity input');
                const priceEl = row.querySelector('.product-subtotal .amount, td.product-subtotal .amount');
                items.push({
                    name: nameEl ? nameEl.textContent.trim() : '?',
                    qty: qtyEl ? (qtyEl.value || '1') : '1',
                    subtotal: priceEl ? priceEl.textContent.trim() : '?',
                });
            }
            return items;
        }
    """)
    nb_items = len(cart_details)

    if nb_items >= nb_attendu:
        print(f"    ✓ Panier OK : {nb_items} ligne(s) présente(s)")
    else:
        print(f"    ⚠ Panier : {nb_items} ligne(s) au lieu de {nb_attendu} attendue(s)")

    # Récapitulatif détaillé
    if cart_details:
        print("    ┌── Récapitulatif panier ──")
        for i, item in enumerate(cart_details, 1):
            print(f"    │ {i}. {item['name']} × {item['qty']} → {item['subtotal']}")
        print(f"    └── {nb_items} ligne(s) total ──")

    return nb_items


async def _ajouter_produits_complementaires(page, produits_list: list, site_url: str = ""):
    """Ajoute des produits WooCommerce supplémentaires dans le panier courant.

    Chaque produit : {"url": str, "variation_id": int, "quantite": int,
                      "attribut_selects": dict, "description": str}

    Stratégie : navigation sur la page produit + clic bouton + vérification panier.
    Le clic bouton déclenche le hook AJAX du thème (ex: konte_ajax_add_to_cart)
    que les plugins de devis (WooQuote Generator) interceptent pour capturer les items.
    Si site_url est fourni, navigue vers /panier/ après chaque ajout pour confirmer
    que l'item est bien enregistré. En cas d'échec, réessaie une fois.
    """
    confirmed_count = 0  # Nombre d'items réellement ajoutés au panier
    for i, prod in enumerate(produits_list):
        url          = prod.get("url", "").strip()
        quantite     = int(prod.get("quantite") or 1)
        attribut_selects = prod.get("attribut_selects") or {}
        description  = prod.get("description") or url.split("/produit/")[-1].strip("/")

        if not url:
            continue

        print(f"  ➜ Produit complémentaire : {description} (×{quantite})")

        async def _configurer_page_et_ajouter():
            """Configure le produit sur sa page et clique Ajouter au panier."""
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(1500)
            await _fermer_popups(page)

            # ── Sélectionner les variations via clic sur les swatches wcboost ──────────
            # Les URL params WC ne fonctionnent pas sur ce thème → clic obligatoire
            if attribut_selects:
                for attr_name, attr_value in attribut_selects.items():
                    result = await _select_wc_attribute(page, attr_name, attr_value)
                    print(f"    ↳ Sélection {attr_name}={attr_value} → {result}")

            # ── AUTOCONTRÔLE OBLIGATOIRE avant ajout au panier ────────────────────────
            # Vérifie que tous les swatches attendus sont bien sélectionnés.
            # Si un swatch n'est pas sélectionné, le re-clique (max 2 passes).
            if attribut_selects:
                for _pass in range(2):
                    mismatches = await page.evaluate("""
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
                    """, list(attribut_selects.values()))
                    if not mismatches:
                        break
                    print(f"    ⚠ Autocontrôle : swatches non sélectionnés {mismatches} — reclic...")
                    for attr_name, attr_value in attribut_selects.items():
                        if attr_value in mismatches:
                            await _select_wc_attribute(page, attr_name, attr_value)

            # Vérifier variation_id final
            selected_var = await page.evaluate("""
                () => {
                    var inp = document.querySelector('input.variation_id, input[name="variation_id"]');
                    return inp ? inp.value : '0';
                }
            """)
            print(f"    ✓ variation_id sélectionné : {selected_var}")
            try:
                qty = page.locator('input.qty, input[name="quantity"]').first
                await qty.fill(str(quantite))
                await qty.dispatch_event("change")
            except Exception:
                pass
            await _fermer_popups(page)
            await _ajouter_au_panier_wc(page)

        confirmed = False
        for attempt in range(2):
            try:
                await _configurer_page_et_ajouter()
                if site_url:
                    # nb_attendu = items déjà confirmés + cet item (pas i+1 qui ignore les échecs précédents)
                    nb = await _verifier_panier(page, site_url, nb_attendu=confirmed_count + 1)
                    if nb >= confirmed_count + 1:
                        confirmed = True
                        break
                    if attempt == 0:
                        print("    ↺ Produit absent du panier — nouvelle tentative...")
                else:
                    confirmed = True
                    break
            except Exception as e:
                print(f"    ⚠ Tentative {attempt + 1}/2 échouée : {e}")

        if confirmed:
            confirmed_count += 1
            print(f"    ✓ {description} confirmé dans le panier (×{quantite})")
        else:
            print(f"    ⚠ {description} potentiellement absent du panier après 2 tentatives")


# ═══════════════════════════════════════════════════════════════
# PERGOLA — mapergolabois.fr
# ═══════════════════════════════════════════════════════════════
# WooCommerce variable product (productId=16046)
# URL : /produit/pergola-bois-en-kit
#
# Attributs :
#   largeur    : "2m","3m","4m","5m","6m","7m","8m","9m","10m"
#   profondeur : "2m","3m","4m","5m"
#   fixation   : "adossee","independante"
#   ventelle   : "largeur","profondeur","retro","sans"
#   option     : "non","platelage","voilage","bioclimatique","carport","lattage","polycarbonate"


async def _configurer_et_ajouter_pergola(
    page, product_url: str,
    largeur: str, profondeur: str, fixation: str, ventelle: str, option: str,
    poteau_lamelle_colle: bool, nb_poteaux_lamelle_colle: int,
    claustra_type: str, nb_claustra: int,
    sur_mesure: bool, largeur_hors_tout: str, profondeur_hors_tout: str, hauteur_hors_tout: str,
    nb_attendu: int,
    site_url: str = "https://mapergolabois.fr",
):
    """Configure une pergola sur la page produit et l'ajoute au panier.

    Encapsule toute la logique de configuration WAPF + ajout panier en une seule
    fonction réutilisable, pour supporter les configurations supplémentaires.
    """
    print(f"  ➜ {product_url}")
    try:
        await page.goto(product_url, wait_until="domcontentloaded", timeout=30000)
    except Exception:
        print("    ⚠ Timeout domcontentloaded, on attend...")
    await page.wait_for_timeout(3000)
    await _fermer_popups(page)

    # Attendre le formulaire WooCommerce + chargement du JSON des variations
    await page.wait_for_selector('form.variations_form', timeout=15000)
    await page.wait_for_timeout(1500)

    # Sélection directe via le JSON des variations embarqué dans la page
    attrs_target = {
        "attribute_pa_largeur":    largeur,
        "attribute_pa_profondeur": profondeur,
        "attribute_pa_fixation":   fixation,
        "attribute_pa_ventelle":   ventelle,
        "attribute_pa_option":     option,
    }
    print(f"  ➜ {largeur} × {profondeur} | {fixation} | ventelle={ventelle} | option={option}")
    variation_id = await _match_wc_variation(page, attrs_target)
    if variation_id:
        print(f"    ✓ Variation trouvée : ID={variation_id}")
    else:
        print("    ⚠ Variation non trouvée dans JSON, fallback jQuery tout-en-un")
        result = await page.evaluate("""
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
                var keys = Object.keys(attrs);
                var lastSel = document.querySelector('select[name="' + keys[keys.length - 1] + '"]');
                if (lastSel && typeof jQuery !== 'undefined') jQuery(lastSel).trigger('change');
                return log;
            }
        """, attrs_target)
        print(f"      ✓ {result}")

    await page.wait_for_timeout(1500)
    prix = await page.evaluate("""
        () => {
            var p = document.querySelector('.woocommerce-variation-price .woocommerce-Price-amount');
            return p ? p.textContent.trim() : null;
        }
    """)
    print(f"  ✓ Prix variation : {prix or '—'}")

    # ── Option Sur-mesure ─────────────────────────────────────────
    if sur_mesure and largeur_hors_tout:
        await _fermer_popups(page)
        await page.click(
            '.wapf-field-container.field-de3be54 div.wapf-swatch label[aria-label="Oui"]',
            timeout=5000,
        )
        print("    ✓ Pergola sur-mesure activée (+199,90€)")
        try:
            await page.wait_for_function(
                "!document.querySelector('.wapf-field-container.field-fe25811')?.classList.contains('wapf-hide')",
                timeout=6000,
            )
        except Exception:
            pass
        await page.wait_for_timeout(500)

        inp_l = page.locator('input[name="wapf[field_fe25811]"]').first
        await inp_l.fill(largeur_hors_tout.replace(",", "."))
        await inp_l.dispatch_event("change")
        await inp_l.dispatch_event("input")
        print(f"  ➜ Largeur HT : {largeur_hors_tout} m")

        if profondeur_hors_tout:
            inp_p = page.locator('input[name="wapf[field_eb3cd46]"]').first
            await inp_p.fill(profondeur_hors_tout.replace(",", "."))
            await inp_p.dispatch_event("change")
            await inp_p.dispatch_event("input")
            print(f"  ➜ Profondeur HT : {profondeur_hors_tout} m")

        if hauteur_hors_tout:
            inp_h = page.locator('input[name="wapf[field_c6c5dea]"]').first
            await inp_h.fill(hauteur_hors_tout.replace(",", "."))
            await inp_h.dispatch_event("change")
            await inp_h.dispatch_event("input")
            print(f"  ➜ Hauteur HT : {hauteur_hors_tout} m")

        await page.wait_for_timeout(800)

    # ── Option Poteau lamellé-collé ──────────────────────────────
    if poteau_lamelle_colle:
        import re as _re
        if nb_poteaux_lamelle_colle > 0:
            total_poteaux = nb_poteaux_lamelle_colle
            print(f"  ➜ Poteau lamellé-collé : {total_poteaux} poteaux (fourni explicitement)")
        else:
            try:
                await page.wait_for_selector(
                    '.woocommerce-variation-description, .woocommerce-variation__availability',
                    timeout=3000,
                )
            except Exception:
                pass
            desc = await page.evaluate("""
                () => {
                    var el = document.querySelector('.woocommerce-variation-description');
                    if (el && el.innerText) return el.innerText;
                    try {
                        var form = document.querySelector('form.variations_form');
                        var raw = form && form.getAttribute('data-product_variations');
                        if (raw && raw.length > 10) {
                            var vars = JSON.parse(raw);
                            var vid = document.querySelector('input.variation_id')?.value;
                            if (vid) {
                                var v = vars.find(v => String(v.variation_id) === String(vid));
                                if (v && v.variation_description) return v.variation_description;
                            }
                        }
                    } catch(e) {}
                    return '';
                }
            """)
            desc = _re.sub(r'<[^>]+>', ' ', desc)
            desc = desc.replace('&rsquo;', "'").replace('&#8217;', "'").replace('&nbsp;', ' ')
            desc = _re.sub(r'\s+', ' ', desc)

            m_angle = _re.search(r"Poteau d.{0,10}angle\s*:\s*(\d+)", desc)
            m_mur   = _re.search(r"Poteau mural\w*\s*:\s*(\d+)", desc)
            n_angle = int(m_angle.group(1)) if m_angle else 0
            n_mur   = int(m_mur.group(1)) if m_mur else 0
            total_poteaux = n_angle + n_mur
            print(f"  ➜ Poteau lamellé-collé : {n_angle} angle + {n_mur} muralière = {total_poteaux} poteaux")

            if total_poteaux == 0:
                print("    ⚠ Poteaux non trouvés dans la description (description vide ou absente)")

        await _fermer_popups(page)
        await page.click(
            '.wapf-field-container.field-60120c1 div.wapf-swatch label[aria-label="Oui"]',
            timeout=5000,
        )
        print("    ✓ Lamellé-collé sélectionné")

        try:
            await page.wait_for_function(
                "!document.querySelector('.wapf-field-container.field-a7fc76f')?.classList.contains('wapf-hide')",
                timeout=6000,
            )
        except Exception:
            pass

        await page.wait_for_timeout(500)

        qty_inp = page.locator('input[name="wapf[field_a7fc76f]"]').first
        await qty_inp.evaluate("el => el.removeAttribute('disabled')")
        await qty_inp.fill(str(total_poteaux))
        await qty_inp.dispatch_event("change")
        await qty_inp.dispatch_event("input")
        print(f"    ✓ Quantité poteaux = {total_poteaux}")
        await page.wait_for_timeout(800)

    # ── Option Claustra ─────────────────────────────────────────
    if claustra_type and nb_claustra > 0:
        await _fermer_popups(page)
        CLAUSTRA_LABEL_MAP = {
            "vertical": "Claustra vertical",
            "horizontal": "Claustra horizontal",
            "lattage": "Claustra lattage",
        }
        label = CLAUSTRA_LABEL_MAP.get(claustra_type, claustra_type)

        try:
            await page.click(
                f'.wapf-field-container.field-5219ffc div.wapf-swatch label[aria-label="{label}"]',
                timeout=5000,
            )
            print(f"    ✓ Claustra type sélectionné : {label}")
        except Exception as e:
            print(f"    ⚠ Claustra swatch non trouvé ({label}): {e}")

        try:
            await page.wait_for_function(
                "!document.querySelector('.wapf-field-container.field-6bf3105')?.classList.contains('wapf-hide')",
                timeout=6000,
            )
        except Exception:
            pass
        await page.wait_for_timeout(500)

        qty_inp = page.locator('input[name="wapf[field_6bf3105]"]').first
        await qty_inp.evaluate("el => el.removeAttribute('disabled')")
        await qty_inp.fill(str(nb_claustra))
        await qty_inp.dispatch_event("change")
        await qty_inp.dispatch_event("input")
        print(f"    ✓ Quantité claustra = {nb_claustra}")
        await page.wait_for_timeout(800)

    # ── Ajouter au panier ────────────────────────────────────────
    await _ajouter_au_panier_wc(page)
    await _verifier_panier(page, site_url, nb_attendu=nb_attendu)


async def generer_devis_pergola(
    largeur: str,
    profondeur: str,
    fixation: str,
    ventelle: str,
    option: str = "non",
    poteau_lamelle_colle: bool = False,
    nb_poteaux_lamelle_colle: int = 0,
    claustra_type: str = "",
    nb_claustra: int = 0,
    sur_mesure: bool = False,
    largeur_hors_tout: str = "",
    profondeur_hors_tout: str = "",
    hauteur_hors_tout: str = "",
    client_nom: str = "",
    client_prenom: str = "",
    client_email: str = "",
    client_telephone: str = "",
    client_adresse: str = "",
    code_promo: str = "",
    mode_livraison: str = "",
    produits_complementaires: str = "[]",
    configurations_supplementaires: str = "[]",
    headless: bool = False,
) -> tuple:
    """
    Génère un devis pergola sur mapergolabois.fr.

    Paramètres :
        largeur               : "2m", "3m", ..., "10m"  (variation standard, doit être >= dimension souhaitée)
        profondeur            : "2m", "3m", "4m", "5m"  (idem)
        fixation              : "adossee" | "independante"
        ventelle              : "largeur" | "profondeur" | "retro" | "sans"
        option                : "non" | "platelage" | ... | "polycarbonate"
        poteau_lamelle_colle  : True → ajoute les poteaux en bois lamellé-collé
        claustra_type         : "" | "vertical" | "horizontal" | "lattage" | "bardage"
        nb_claustra           : nombre de modules claustra/bardage (1 module = 1m)
        sur_mesure            : True → active l'option "Pergola sur mesure" (+199,90€)
        largeur_hors_tout     : ex. "7.60"  — dimension réelle souhaitée en largeur
        profondeur_hors_tout  : ex. "3.42"  — dimension réelle souhaitée en profondeur
        hauteur_hors_tout     : ex. "2.40"  — hauteur souhaitée (optionnel, max 3.07m)
        client_*              : coordonnées client pour le PDF
        configurations_supplementaires : JSON array de configs supplémentaires.
            Chaque élément est un dict avec les mêmes clés que la config principale :
            {"largeur": "5m", "profondeur": "3m", "fixation": "independante",
            "ventelle": "largeur", "option": "non", ...}
            Permet de mettre plusieurs pergolas sur le même devis PDF.

    Retourne : chemin vers le PDF
    """
    start_time = time.time()
    configs_sup = json.loads(configurations_supplementaires) if isinstance(configurations_supplementaires, str) and configurations_supplementaires != "[]" else []
    if isinstance(configurations_supplementaires, list):
        configs_sup = configurations_supplementaires
    print(f"\n{'='*60}")
    print("  DEVIS PERGOLA — mapergolabois.fr")
    print(f"  Client : {client_prenom} {client_nom}")
    extra = " | lamellé-collé" if poteau_lamelle_colle else ""
    if claustra_type:
        extra += f" | claustra={claustra_type}×{nb_claustra}"
    if sur_mesure and largeur_hors_tout:
        sm = f" | SUR-MESURE {largeur_hors_tout}m×{profondeur_hors_tout}m"
        if hauteur_hors_tout:
            sm += f" h={hauteur_hors_tout}m"
        extra += sm
    print(f"  {largeur} × {profondeur} | {fixation} | ventelle={ventelle} | option={option}{extra}")
    if configs_sup:
        print(f"  + {len(configs_sup)} configuration(s) supplémentaire(s)")
    print(f"{'='*60}\n")

    SITE_URL = "https://mapergolabois.fr"
    PRODUCT_URL = f"{SITE_URL}/produit/pergola-bois-en-kit"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            viewport={"width": 1400, "height": 900},
            locale="fr-FR",
            accept_downloads=True,
        )
        page = await context.new_page()
        try:
            nb_items_panier = 0

            # ── Configuration principale ───────────────────────────────
            await _configurer_et_ajouter_pergola(
                page, PRODUCT_URL,
                largeur=largeur, profondeur=profondeur, fixation=fixation,
                ventelle=ventelle, option=option,
                poteau_lamelle_colle=poteau_lamelle_colle,
                nb_poteaux_lamelle_colle=nb_poteaux_lamelle_colle,
                claustra_type=claustra_type, nb_claustra=nb_claustra,
                sur_mesure=sur_mesure, largeur_hors_tout=largeur_hors_tout,
                profondeur_hors_tout=profondeur_hors_tout, hauteur_hors_tout=hauteur_hors_tout,
                nb_attendu=1, site_url=SITE_URL,
            )
            nb_items_panier = 1

            # ── Configurations supplémentaires (multi-pergola) ─────────
            for idx, cfg in enumerate(configs_sup):
                print(f"\n  ─── Configuration supplémentaire {idx + 1}/{len(configs_sup)} ───")
                nb_items_panier += 1
                await _configurer_et_ajouter_pergola(
                    page, PRODUCT_URL,
                    largeur=cfg.get("largeur", ""),
                    profondeur=cfg.get("profondeur", ""),
                    fixation=cfg.get("fixation", "independante"),
                    ventelle=cfg.get("ventelle", "sans"),
                    option=cfg.get("option", "non"),
                    poteau_lamelle_colle=cfg.get("poteau_lamelle_colle", False),
                    nb_poteaux_lamelle_colle=cfg.get("nb_poteaux_lamelle_colle", 0),
                    claustra_type=cfg.get("claustra_type", ""),
                    nb_claustra=cfg.get("nb_claustra", 0),
                    sur_mesure=cfg.get("sur_mesure", False),
                    largeur_hors_tout=cfg.get("largeur_hors_tout", ""),
                    profondeur_hors_tout=cfg.get("profondeur_hors_tout", ""),
                    hauteur_hors_tout=cfg.get("hauteur_hors_tout", ""),
                    nb_attendu=nb_items_panier, site_url=SITE_URL,
                )

            # ── Produits complémentaires ─────────────────────────────────
            produits_list = json.loads(produits_complementaires) if produits_complementaires and produits_complementaires != "[]" else []
            if produits_list:
                await _ajouter_produits_complementaires(page, produits_list, site_url=SITE_URL)

            # ── Panier : code promo, livraison, date estimée ─────────────
            date_livraison = await _traiter_panier(page, SITE_URL, code_promo, mode_livraison)

            # ── Générer le devis via le générateur officiel ───────────────
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filepath = os.path.join(DOWNLOAD_DIR, f"devis_{client_nom}_{client_prenom}_{timestamp}.pdf")
            filepath = await _generer_devis_via_generateur(
                page, SITE_URL,
                client_nom, client_prenom, client_email, client_telephone, client_adresse,
                filepath,
            )

            elapsed = time.time() - start_time
            print(f"\n  ✅ DEVIS PERGOLA EN {elapsed:.1f}s — {filepath}")
            return filepath, date_livraison

        except Exception as e:
            print(f"\n  ❌ Erreur pergola : {e}")
            raise
        finally:
            await browser.close()


# ═══════════════════════════════════════════════════════════════
# TERRASSE — terrasseenbois.fr
# ═══════════════════════════════════════════════════════════════
# WooCommerce simple product + WAPF (productId=57595)
# URL : /produit/configurateur-terrasse/
#
# Champs WAPF principaux :
#   essence  : voir TERRASSE_ESSENCE_MAP (radio image swatch)
#   longueur : text visible du select, ex: "3.3", "4.2", "5.1"
#              (disponibles selon l'essence choisie)
#   lambourdes (optionnel) : voir TERRASSE_LAMBOURDES_MAP
#   quantite : nb de m² (défaut 1)

async def generer_devis_terrasse(
    essence: str,
    longueur: str,
    quantite: int = 1,
    lambourdes: str = "",
    lambourdes_longueur: str = "",
    plots: str = "NON",
    visserie: str = "",
    densite_lambourdes: str = "simple",
    nb_lames: int = 0,
    nb_lambourdes: int = 0,
    client_nom: str = "",
    client_prenom: str = "",
    client_email: str = "",
    client_telephone: str = "",
    client_adresse: str = "",
    code_promo: str = "",
    mode_livraison: str = "",
    produits_complementaires: str = "[]",
    configurations_supplementaires: str = "[]",
    headless: bool = False,
) -> tuple:
    """
    Génère un devis terrasse sur terrasseenbois.fr (WAPF).

    Paramètres :
        essence             : "PIN 21mm Autoclave Vert" | "PIN 27mm Autoclave Vert" |
                              "PIN 27mm Autoclave Marron" | "PIN 27mm Autoclave Gris" |
                              "FRAKE" | "JATOBA" | "CUMARU" | "PADOUK" | "IPE"
        longueur            : longueur de lame (voir TERRASSE_ESSENCE_MAP pour valeurs par essence)
                              ex: "0.95", "1.25" (IPE) | "3.3", "4.2" (PIN 21mm) | etc.
        quantite            : nombre de m² (commande par surface)
        lambourdes          : "" (aucune) | "Pin autoclave Vert 45x70" |
                              "Pin autoclave Vert 45x145" | "Bois exotique Niove 40x60"
        lambourdes_longueur : longueur des lambourdes (m)
                              Pin: "3", "4.2", "4.8", "5.1"
                              Niove: "1.55", "1.85", "2.15", "3.05", "3.65"
                              "" = première longueur disponible
        plots               : hauteur plots réglables. "NON" | "2 à 4 cm" | "4 à 6 cm" |
                              "6 à 9 cm" | "9 à 15 cm" | "15 à 26 cm"
        visserie            : "" (aucune) | "Vis Inox 5x50mm" | "Vis Inox 5x60mm" |
                              "Fixations invisible Hapax"
        densite_lambourdes  : "simple" (3ml/m²) | "double" (6ml/m²)
        configurations_supplementaires : JSON array de configs supplémentaires.
            Chaque élément est un dict avec les mêmes clés : {"essence": "...", "longueur": "...",
            "quantite": N, "lambourdes": "...", ...}
        client_*            : coordonnées client

    Retourne : chemin vers le PDF
    """
    if essence not in TERRASSE_ESSENCE_MAP:
        raise ValueError(
            f"Essence '{essence}' inconnue. "
            f"Disponibles : {', '.join(sorted(TERRASSE_ESSENCE_MAP.keys()))}"
        )

    # ── Calcul auto-split si nb_lames / nb_lambourdes fournis ────────────────
    # Formules terrasseenbois.fr (vérifiées sur devis réels) :
    #   Lame width = 0.145 m (145mm pour toutes les essences standard)
    #   m² par lame = lame_width × longueur_m
    #   Simple density = 3 ml lambourdes / m² → nb_lambourdes = m² * 3 / lamb_lon
    #
    # split_q2 = m² à ajouter en 2ème ligne panier (lames seulement, sans lambourdes)
    LAME_WIDTH_M = 0.145
    extra_lames_for_split = 0  # nombre de lames exactes pour item2 (mode nb_lames_direct)

    if nb_lambourdes > 0 and lambourdes:
        # m² pour obtenir exactement nb_lambourdes
        density_ml = 6.0 if densite_lambourdes == "double" else 3.0
        try:
            lamb_lon_f = float(lambourdes_longueur) if lambourdes_longueur else float(longueur)
        except ValueError:
            lamb_lon_f = float(longueur)
        quantite = math.ceil(nb_lambourdes * lamb_lon_f / density_ml)
        print(f"  [Split] nb_lambourdes={nb_lambourdes} → item1={quantite} m²")

        if nb_lames > 0:
            # Lames incluses dans item1
            try:
                lames_in_q1 = int(quantite / (LAME_WIDTH_M * float(longueur)))
            except (ValueError, ZeroDivisionError):
                lames_in_q1 = 0
            extra_lames = nb_lames - lames_in_q1
            if extra_lames > 0:
                extra_lames_for_split = extra_lames
                print(f"  [Split] {lames_in_q1} lames dans item1, {extra_lames} extra → item2={extra_lames} lames (mode direct)")

    elif nb_lames > 0:
        # Seulement nb_lames, sans lambourdes :
        # → utiliser le mode WAPF "nombre de lames" (quantité exacte, sans arrondi m²)
        # quantite n'est pas utilisé dans ce cas (nb_lames_direct prend le relais)
        print(f"  [Mode nb_lames direct] {nb_lames} lames {longueur}m — pas de calcul m²")
    # ─────────────────────────────────────────────────────────────────────────

    # Flag pour le mode "nombre de lames" WAPF
    use_nb_lames_direct = nb_lames > 0 and not lambourdes

    start_time = time.time()
    print(f"\n{'='*60}")
    print("  DEVIS TERRASSE — terrasseenbois.fr")
    print(f"  Client : {client_prenom} {client_nom}")
    print(f"  Essence: {essence} | Longueur: {longueur}m | Qté: {quantite} m²")
    if extra_lames_for_split:
        print(f"  + Item 2 : {extra_lames_for_split} lames seules (mode direct — quantité exacte)")
    extras = []
    if lambourdes:
        extras.append(f"lambourdes={lambourdes}")
    if plots and plots != "NON":
        extras.append(f"plots={plots}")
    if visserie:
        extras.append(f"visserie={visserie}")
    if extras:
        print(f"  Options: {' | '.join(extras)}")
    print(f"{'='*60}\n")

    SITE_URL = "https://terrasseenbois.fr"
    PRODUCT_URL = f"{SITE_URL}/produit/configurateur-terrasse/"
    ESSENCE_FIELD = "field_65c1e3eb8cfb0"

    essence_val, longueur_field = TERRASSE_ESSENCE_MAP[essence]

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            viewport={"width": 1400, "height": 900},
            locale="fr-FR",
            accept_downloads=True,
        )
        page = await context.new_page()

        # ── Helpers WAPF (closures sur page / variables du scope) ─────────
        async def wapf_wait_visible(field_id: str, timeout: int = 8000):
            fid = field_id.replace("field_", "")
            try:
                await page.wait_for_function(
                    f"!document.querySelector('.wapf-field-container.field-{fid}')?.classList.contains('wapf-hide')",
                    timeout=timeout,
                )
            except Exception:
                pass

        async def wapf_click_swatch(aria_label: str, desc: str = "", field_id: str = ""):
            """Clique sur un swatch WAPF.

            field_id : si fourni, scope le sélecteur au conteneur exact de ce champ.
                       Obligatoire quand aria_label est ambigu ("Non" peut être dans plusieurs
                       fields visibles simultanément — lambourdes, visserie…).
            """
            if field_id:
                fid = field_id.replace("field_", "")
                sel = f'.wapf-field-container.field-{fid}:not(.wapf-hide) div.wapf-swatch label[aria-label="{aria_label}"]'
            else:
                sel = f'.wapf-field-container:not(.wapf-hide) div.wapf-swatch label[aria-label="{aria_label}"]'
            try:
                await page.click(sel, timeout=5000)
                print(f"    ✓ {desc or aria_label}")
                await page.wait_for_timeout(400)
            except Exception as e:
                raise ValueError(f"Swatch '{aria_label}' introuvable (field={field_id or 'any'}): {e}")

        async def wapf_select_text(field_name: str, text: str, desc: str = ""):
            res = await page.evaluate(f"""
                () => {{
                    var sel = document.querySelector('select[name="{field_name}"]');
                    if (!sel) return 'not_found';
                    for (var opt of sel.options) {{
                        if (opt.text.trim() === '{text}' || opt.text.trim().startsWith('{text}')) {{
                            sel.value = opt.value;
                            sel.dispatchEvent(new Event('change', {{bubbles: true}}));
                            return 'ok:' + opt.value;
                        }}
                    }}
                    return 'not_found_option';
                }}
            """)
            if "not_found" in str(res):
                print(f"    ⚠ Select {desc} '{text}' : {res}")
            else:
                print(f"    ✓ {desc or text}")
            await page.wait_for_timeout(400)

        _wapf_cart_count = [0]  # compteur partagé entre les appels à _configurer_wapf_et_ajouter

        async def _configurer_wapf_et_ajouter(
            quantite_m2: int,
            avec_lambourdes: bool = True,
            avec_plots: bool = True,
            item_label: str = "",
            nb_lames_direct: int = 0,
            skip_goto: bool = False,
        ):
            """Navigue vers la page produit, configure les options WAPF et ajoute au panier.

            nb_lames_direct : si > 0, utilise le mode WAPF 'nombre de lames' (quantité exacte,
                              sans lambourdes/plots — ces champs sont cachés par le configurateur
                              dans ce mode).
            skip_goto : si True ET qu'on est déjà sur la page produit (AJAX add-to-cart),
                        évite le rechargement qui forcerait WQG à réinitialiser et écraser
                        l'image de l'item 1 avec l'image par défaut du produit.
            """
            label = f"[{item_label}] " if item_label else ""
            already_on_page = PRODUCT_URL.rstrip('/') in page.url

            if skip_goto and already_on_page:
                # Rester sur la page produit — WQG ne réinitialise pas l'image item 1
                if nb_lames_direct > 0:
                    print(f"\n  {label}➜ Reconfiguration WAPF ({nb_lames_direct} lames — mode direct)")
                else:
                    print(f"\n  {label}➜ Reconfiguration WAPF ({quantite_m2} m²) — sans rechargement")
                await page.wait_for_timeout(1500)
            else:
                if nb_lames_direct > 0:
                    print(f"\n  {label}➜ {PRODUCT_URL} ({nb_lames_direct} lames — mode direct)")
                else:
                    print(f"\n  {label}➜ {PRODUCT_URL} ({quantite_m2} m²)")
                try:
                    await page.goto(PRODUCT_URL, wait_until="domcontentloaded", timeout=30000)
                except Exception:
                    print("    ⚠ Timeout chargement page produit, on continue...")
                await page.wait_for_timeout(2000)
            await _fermer_popups(page)
            await page.wait_for_selector('div.wapf-swatch', timeout=15000)
            await page.wait_for_timeout(300)

            # 1. Essence
            already_checked = await page.evaluate(f"""
                () => !!document.querySelector(
                    'input[name="wapf[{ESSENCE_FIELD}]"][value="{essence_val}"]:checked')
            """)
            if already_checked:
                temp = next(e for e in ("FRAKE", "JATOBA", "CUMARU", "PADOUK") if e != essence)
                try:
                    await page.click(f'div.wapf-swatch label[aria-label="{temp}"]', timeout=3000)
                    await page.wait_for_timeout(400)
                except Exception:
                    pass
            print(f"  {label}➜ Essence : {essence}")
            await wapf_click_swatch(essence, f"Essence {essence}")

            # 2. Longueur
            await wapf_wait_visible(longueur_field)
            print(f"  {label}➜ Longueur : {longueur}m")
            await wapf_select_text(f"wapf[{longueur_field}]", longueur, f"Longueur {longueur}m")
            await page.wait_for_timeout(500)

            if nb_lames_direct > 0:
                # ── Mode "nombre de lames" : quantité exacte, sans lambourdes/plots ──
                # Le configurateur cache lambourdes/visserie/plots dans ce mode.
                await wapf_wait_visible("field_65c4b57273a3b")
                await wapf_select_text(
                    "wapf[field_65c4b57273a3b]",
                    "en indiquant le nombre de lames de terrasse souhaité",
                    "Mode nombre de lames",
                )
                await page.wait_for_timeout(800)
                # Quantité = nombre de lames exact
                print(f"  {label}➜ Quantité : {nb_lames_direct} lames")
                try:
                    qty_input = page.locator('input.qty, input[name="quantity"]').first
                    await qty_input.fill(str(nb_lames_direct))
                    await qty_input.dispatch_event("change")
                    await page.wait_for_timeout(800)
                except Exception as e:
                    print(f"    ⚠ Quantité: {e}")

            else:
                # ── Mode surface (m²) : lambourdes, visserie, plots, quantité ──

                # 3. Lambourdes
                await wapf_wait_visible("field_65c249d0a5359")
                if avec_lambourdes and lambourdes and lambourdes in TERRASSE_LAMBOURDES_MAP \
                        and lambourdes.lower() not in ("non", "aucune"):
                    lamb_label = lambourdes
                else:
                    lamb_label = "Non"
                lamb_val = TERRASSE_LAMBOURDES_MAP.get(lamb_label, "h2t80")
                print(f"  {label}➜ Lambourdes : {lamb_label}")
                await wapf_click_swatch(lamb_label, f"Lambourdes {lamb_label}",
                                        field_id="field_65c249d0a5359")

                if lamb_label != "Non":
                    is_niove  = "Niove" in lamb_label
                    lon_field = "field_65c24905394ba" if is_niove else "field_65c2481983a7c"
                    lon_map   = TERRASSE_LAMBOURDES_LON_NIOVE if is_niove else TERRASSE_LAMBOURDES_LON_PIN
                    await wapf_wait_visible(lon_field)
                    chosen_lon = lambourdes_longueur if lambourdes_longueur in lon_map else next(iter(lon_map))
                    if lambourdes_longueur and lambourdes_longueur not in lon_map:
                        print(f"    ⚠ Longueur lambourdes '{lambourdes_longueur}' inconnue → {chosen_lon}m")
                    print(f"  {label}➜ Longueur lambourdes : {chosen_lon}m")
                    await wapf_select_text(f"wapf[{lon_field}]", chosen_lon, "Longueur lambourdes")
                    densite_kw = "Double" if densite_lambourdes == "double" else "Simple"
                    print(f"  {label}➜ Densité : {densite_kw}")
                    await wapf_select_text("wapf[field_65c5fc624fea1]", densite_kw, f"Densité {densite_kw}")

                # 4. Visserie — toujours sélectionner (même "Non") pour débloquer les plots
                # ⚠ field_id obligatoire : "Non" existe aussi dans lambourdes (toujours visible)
                #    → sans scoping, le clic atterrit sur le "Non" lambourdes et déselectionne Niove
                viss_label = visserie if (avec_lambourdes and visserie and visserie in TERRASSE_VISSERIE_MAP) else "Non"
                await wapf_wait_visible("field_65c24ccdb0633")
                await _fermer_popups(page)
                print(f"  {label}➜ Visserie : {viss_label}")
                await wapf_click_swatch(viss_label, f"Visserie {viss_label}",
                                        field_id="field_65c24ccdb0633")

                # 5. Plots
                # ⚠ field_id obligatoire : 3 champs plots (sans lamb / Pin / Niove),
                #    un seul visible → scoper au bon container
                # ⚠ Pour Item 2 (avec_plots=False) : clic JS pour éviter auto-scroll
                #    Playwright qui changerait l'image produit avant capture WQG
                if lamb_val == "izhh7":
                    plots_field = "field_65c601bb8ddca"
                elif lamb_val in ("", "h2t80"):
                    plots_field = "field_65c251f1d2b79"
                else:
                    plots_field = "field_65c4a948e1b14"
                fid_plots = plots_field.replace("field_", "")

                if avec_plots and plots:
                    # Item 1 : hauteur réelle → clic Playwright normal (label visible)
                    plots_value = plots if plots != "NON" else "NON"
                    try:
                        await wapf_wait_visible(plots_field, timeout=8000)
                        await _fermer_popups(page)
                        print(f"  {label}➜ Plots : {plots_value}")
                        await wapf_click_swatch(plots_value, f"Plots {plots_value}", field_id=plots_field)
                    except Exception as e_plots:
                        print(f"  {label}⚠ Plots non sélectionnés ({plots_value}) : {e_plots}")
                else:
                    # Item 2 (lames seules) : sélectionner "NON" via JS sans scroll
                    # → WQG capte l'image de configuration correcte (pas de déplacement de page)
                    # Fallback sur clic Playwright si JS échoue (container caché)
                    try:
                        await wapf_wait_visible(plots_field, timeout=8000)
                        await _fermer_popups(page)
                        result = await page.evaluate(f"""
                            () => {{
                                var c = document.querySelector(
                                    '.wapf-field-container.field-{fid_plots}:not(.wapf-hide)');
                                if (!c) return 'no_container';
                                var lbl = c.querySelector('div.wapf-swatch label[aria-label="NON"]') ||
                                          c.querySelector('div.wapf-swatch label[aria-label="Non"]');
                                if (!lbl) return 'no_label';
                                lbl.click();
                                return 'ok';
                            }}
                        """)
                        print(f"  {label}➜ Plots NON (JS) : {result}")
                        if result in ('no_container', 'no_label'):
                            # Fallback : clic Playwright (implique un scroll mais c'est acceptable
                            # pour item 2 car il n'y a pas d'image spécifique à capturer)
                            print(f"  {label}⚠ Fallback → clic Playwright pour plots NON")
                            await wapf_click_swatch("NON", "Plots NON (fallback)", field_id=plots_field)
                        await page.wait_for_timeout(500)
                    except Exception as e_plots:
                        print(f"  {label}⚠ Plots NON : {e_plots}")

                # 6. Quantité en m²
                print(f"  {label}➜ Quantité : {quantite_m2} m²")
                try:
                    qty_input = page.locator('input.qty, input[name="quantity"]').first
                    await qty_input.fill(str(quantite_m2))
                    await qty_input.dispatch_event("change")
                    await page.wait_for_timeout(800)
                except Exception as e:
                    print(f"    ⚠ Quantité: {e}")

            prix = await page.evaluate("""
                () => {
                    var p = document.querySelector('.wapf-product-totals, .wapf-calc-text, .woocommerce-Price-amount');
                    return p ? p.textContent.trim() : null;
                }
            """)
            print(f"  {label}✓ Prix : {prix or '—'}")

            await _fermer_popups(page)
            # Pas de navigation intermédiaire vers /panier/ : cela perturberait WQG
            # qui recalcule les images de la quote cart à chaque navigation.
            # La vérification complète se fait en une seule fois, après tous les items.
            await _ajouter_au_panier_wc(page)
            _wapf_cart_count[0] += 1
        # ─────────────────────────────────────────────────────────────────

        try:
            if use_nb_lames_direct:
                # ── Mode "nombre de lames" WAPF : quantité exacte ────────────────
                await _configurer_wapf_et_ajouter(
                    quantite_m2=1,  # ignoré en mode direct
                    nb_lames_direct=nb_lames,
                    item_label="Lames directes",
                )
            else:
                # ── Mode surface (m²) ────────────────────────────────────────────
                # Item 1 : configuration principale (avec lambourdes + plots)
                await _configurer_wapf_et_ajouter(
                    quantite_m2=quantite,
                    avec_lambourdes=True,
                    avec_plots=True,
                    item_label="Item 1" if extra_lames_for_split else "",
                )

                # Item 2 : lames seules — mode nb_lames_direct (quantité exacte, sans arrondi m²)
                # skip_goto=True : évite le rechargement qui écrase l'image item 1 dans WQG
                if extra_lames_for_split > 0:
                    await _configurer_wapf_et_ajouter(
                        quantite_m2=1,  # ignoré en mode direct
                        nb_lames_direct=extra_lames_for_split,
                        item_label="Item 2 — lames seules",
                        skip_goto=True,
                    )

            # ── Configurations supplémentaires (multi-terrasse sur même devis) ──
            configs_sup = json.loads(configurations_supplementaires) if isinstance(configurations_supplementaires, str) and configurations_supplementaires != "[]" else []
            if isinstance(configurations_supplementaires, list):
                configs_sup = configurations_supplementaires
            for idx_sup, cfg_sup in enumerate(configs_sup):
                print(f"\n  ─── Configuration supplémentaire {idx_sup + 1}/{len(configs_sup)} ───")
                sup_essence = cfg_sup.get("essence", essence)
                if sup_essence not in TERRASSE_ESSENCE_MAP:
                    print(f"    ⚠ Essence '{sup_essence}' inconnue, ignorée")
                    continue
                # Réassigner les variables capturées par la closure _configurer_wapf_et_ajouter
                # Python closures capturent la référence de la variable, pas sa valeur,
                # donc les modifications sont visibles par la fonction interne.
                essence = cfg_sup.get("essence", essence)
                longueur = cfg_sup.get("longueur", longueur)
                lambourdes = cfg_sup.get("lambourdes", "")
                lambourdes_longueur = cfg_sup.get("lambourdes_longueur", "")
                plots = cfg_sup.get("plots", "NON")
                visserie = cfg_sup.get("visserie", "")
                densite_lambourdes = cfg_sup.get("densite_lambourdes", "simple")
                essence_val, longueur_field = TERRASSE_ESSENCE_MAP[essence]
                sup_quantite = cfg_sup.get("quantite", 1)
                await _configurer_wapf_et_ajouter(
                    quantite_m2=sup_quantite,
                    avec_lambourdes=True,
                    avec_plots=True,
                )

            # ── Produits complémentaires ───────────────────────────────────────
            produits_list = json.loads(produits_complementaires) if produits_complementaires and produits_complementaires != "[]" else []
            if produits_list:
                await _ajouter_produits_complementaires(page, produits_list, site_url=SITE_URL)

            # ── Vérification panier (une seule fois, après tous les items) ─────
            nb_attendu = _wapf_cart_count[0] + len(produits_list)
            await _verifier_panier(page, SITE_URL, nb_attendu=nb_attendu)

            # ── Panier : code promo, livraison, date estimée ──────────────────
            date_livraison = await _traiter_panier(page, SITE_URL, code_promo, mode_livraison)

            # ── Générer le devis ──────────────────────────────────────────────
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filepath = os.path.join(DOWNLOAD_DIR, f"devis_{client_nom}_{client_prenom}_{timestamp}.pdf")
            filepath = await _generer_devis_via_generateur(
                page, SITE_URL,
                client_nom, client_prenom, client_email, client_telephone, client_adresse,
                filepath,
            )

            elapsed = time.time() - start_time
            print(f"\n  ✅ DEVIS TERRASSE EN {elapsed:.1f}s — {filepath}")
            return filepath, date_livraison

        except Exception as e:
            print(f"\n  ❌ Erreur terrasse : {e}")
            raise
        finally:
            await browser.close()


# ═══════════════════════════════════════════════════════════════
# TERRASSE AU DÉTAIL — terrasseenbois.fr (sans configurateur WAPF)
# ═══════════════════════════════════════════════════════════════
# Ajoute des produits du catalogue au détail directement au panier
# (lames, lambourdes, plots, visserie…), sans passer par le WAPF.
# Le PDF est généré via WQG /generateur-de-devis/ — le test permet
# de vérifier si WQG capture les produits du catalogue.

async def generer_devis_terrasse_detail(
    produits: list,                  # [{url, variation_id, quantite, attribut_selects, description}]
    client_nom: str = "",
    client_prenom: str = "",
    client_email: str = "",
    client_telephone: str = "",
    client_adresse: str = "",
    code_promo: str = "",
    mode_livraison: str = "",
    headless: bool = False,
) -> tuple:
    """
    Génère un devis terrasse en ajoutant des produits au détail (sans configurateur WAPF).

    Chaque produit dans `produits` : {
        "url": "https://www.terrasseenbois.fr/produit/...",
        "variation_id": 89495,
        "quantite": 70,
        "attribut_selects": {"attribute_pa_longueur_de_lame": "3-05-m"},
        "description": "70 lames Cumaru 3,05m"
    }

    Retourne : (filepath, date_livraison)
    """
    SITE_URL = "https://terrasseenbois.fr"

    start_time = time.time()
    print(f"\n{'='*60}")
    print("  DEVIS TERRASSE AU DÉTAIL — terrasseenbois.fr")
    print(f"  Client : {client_prenom} {client_nom}")
    print(f"  Produits : {len(produits)}")
    for p in produits:
        print(f"    • {p.get('description', p.get('url', '?'))} ×{p.get('quantite', 1)}")
    print(f"{'='*60}\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            viewport={"width": 1400, "height": 900},
            locale="fr-FR",
            accept_downloads=True,
        )
        page = await context.new_page()

        try:
            # 1. Ajouter chaque produit via clic bouton (WQG hook)
            # site_url activé → vérifie le panier après chaque ajout avant de continuer
            await _ajouter_produits_complementaires(page, produits, site_url=SITE_URL)

            # 2. Panier : code promo, livraison, date estimée
            date_livraison = await _traiter_panier(page, SITE_URL, code_promo, mode_livraison)

            # 3. Générer le devis via WQG /generateur-de-devis/
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filepath = os.path.join(
                DOWNLOAD_DIR,
                f"devis_terrasse_detail_{client_nom}_{client_prenom}_{timestamp}.pdf",
            )
            filepath = await _generer_devis_via_generateur(
                page, SITE_URL,
                client_nom, client_prenom, client_email, client_telephone, client_adresse,
                filepath,
            )

            elapsed = time.time() - start_time
            print(f"\n  ✅ DEVIS TERRASSE DÉTAIL EN {elapsed:.1f}s — {filepath}")
            return filepath, date_livraison

        except Exception as e:
            print(f"\n  ❌ Erreur terrasse détail : {e}")
            raise
        finally:
            await browser.close()


# ═══════════════════════════════════════════════════════════════
# CLÔTURE — cloturebois.fr
# ═══════════════════════════════════════════════════════════════
# Deux produits WooCommerce variable :
#
# KIT CLASSIQUE (productId=18393)
# URL : /produit/kit-cloture-bois-classique/
#   longeur (sic) : "4","10","20","30","40" (mètres linéaires)
#   hauteur       : "1-9" = "1.9m"
#   bardage       : "27x130" | "27x130-gris"
#   type-de-poteaux : "90x90-h" | "metal7016"
#   longueur-des-lames : "2-m"
#   type-de-fixation-au-sol : "plots-beton"
#
# KIT MODERNE (productId=17434)
# URL : /produit/kit-cloture-bois-moderne/
#   longeur (sic) : "5","10","20","30","40"
#   hauteur       : "0-9"=0.9m | "1-9"=1.9m | "2-3"=2.3m
#   bardage       : "20x60"|"20x70-brun"|"20x70-gris"|"20x70-noir"|"21x130"|"21x145"|
#                   "45x45-esp0-015m"|"45x45-esp0-045m"
#   sens-du-bardage : "horizontal" | "vertical"
#   recto-verso  : "non" | "oui"
#   type-de-fixation-au-sol : "pieds-galvanises-en-h" | "plots-beton"

async def _configurer_et_ajouter_cloture(
    page, site_url: str, product_url: str,
    modele: str, longeur: str, hauteur: str, bardage: str, fixation_sol: str,
    type_poteaux: str, longueur_lames: str, sens_bardage: str, recto_verso: str,
    nb_attendu: int,
):
    """Configure une clôture sur la page produit et l'ajoute au panier."""
    print(f"  ➜ {product_url}")
    try:
        await page.goto(product_url, wait_until="domcontentloaded", timeout=30000)
    except Exception:
        print("    ⚠ Timeout, on attend...")
    await page.wait_for_timeout(3000)
    await _fermer_popups(page)

    await page.wait_for_selector('form.variations_form, select[name*="attribute"]', timeout=15000)
    await page.wait_for_timeout(1000)

    # Construire les attributs selon le modèle
    if modele == "classique":
        attrs = {
            "attribute_pa_longeur":                longeur,
            "attribute_pa_hauteur":                hauteur,
            "attribute_pa_bardage":                bardage,
            "attribute_pa_type-de-poteaux":        type_poteaux,
            "attribute_pa_longueur-des-lames":     longueur_lames,
            "attribute_pa_type-de-fixation-au-sol": fixation_sol,
        }
    else:
        attrs = {
            "attribute_pa_longeur":                longeur,
            "attribute_pa_hauteur":                hauteur,
            "attribute_pa_bardage":                bardage,
            "attribute_pa_sens-du-bardage":        sens_bardage,
            "attribute_pa_recto-verso":            recto_verso,
            "attribute_pa_type-de-fixation-au-sol": fixation_sol,
        }
    attrs = {k: v for k, v in attrs.items() if v}

    for attr, val in attrs.items():
        print(f"  ➜ {attr} = {val}")
        r = await _select_wc_attribute(page, attr, val)
        print(f"    ✓ {r or 'ok'}")

    await page.wait_for_timeout(2000)
    prix = await page.evaluate("""
        () => {
            var sel = '.woocommerce-variation-price .woocommerce-Price-amount, .summary .price .woocommerce-Price-amount';
            var p = document.querySelector(sel);
            return p ? p.textContent.trim() : null;
        }
    """)
    print(f"  ✓ Prix variation : {prix or '—'}")

    await _ajouter_au_panier_wc(page)
    await _verifier_panier(page, site_url, nb_attendu=nb_attendu)


async def generer_devis_cloture(
    modele: str,
    longeur: str,
    hauteur: str,
    bardage: str,
    fixation_sol: str,
    type_poteaux: str = "",
    longueur_lames: str = "",
    sens_bardage: str = "vertical",
    recto_verso: str = "non",
    client_nom: str = "",
    client_prenom: str = "",
    client_email: str = "",
    client_telephone: str = "",
    client_adresse: str = "",
    code_promo: str = "",
    mode_livraison: str = "",
    produits_complementaires: str = "[]",
    configurations_supplementaires: str = "[]",
    headless: bool = False,
) -> tuple:
    """
    Génère un devis clôture sur cloturebois.fr.

    Paramètres :
        modele      : "classique" | "moderne"

        Kit classique :
            longeur     : "4" | "10" | "20" | "30" | "40" (mètres)
            hauteur     : "1-9" (= 1.9m, seul choix disponible)
            bardage     : "27x130" | "27x130-gris"
            fixation_sol: "plots-beton" (seul choix)
            type_poteaux: "90x90-h" | "metal7016"
            longueur_lames: "2-m" (seul choix)

        Kit moderne :
            longeur     : "5" | "10" | "20" | "30" | "40"
            hauteur     : "0-9" (0.9m) | "1-9" (1.9m) | "2-3" (2.3m)
            bardage     : "20x60"|"20x70-brun"|"20x70-gris"|"20x70-noir"|
                          "21x130"|"21x145"|"45x45-esp0-015m"|"45x45-esp0-045m"
            fixation_sol: "plots-beton" | "pieds-galvanises-en-h"
            sens_bardage: "horizontal" | "vertical"
            recto_verso : "non" | "oui"

    Retourne : chemin vers le PDF
    """
    if modele not in ("classique", "moderne"):
        raise ValueError("modele doit être 'classique' ou 'moderne'")

    start_time = time.time()
    configs_sup = json.loads(configurations_supplementaires) if isinstance(configurations_supplementaires, str) and configurations_supplementaires != "[]" else []
    if isinstance(configurations_supplementaires, list):
        configs_sup = configurations_supplementaires

    SITE_URL = "https://cloturebois.fr"

    def _product_url_for(m: str) -> str:
        return SITE_URL + (
            "/produit/kit-cloture-bois-classique/" if m == "classique"
            else "/produit/kit-cloture-bois-moderne/"
        )

    PRODUCT_URL = _product_url_for(modele)

    print(f"\n{'='*60}")
    print(f"  DEVIS CLÔTURE {modele.upper()} — cloturebois.fr")
    print(f"  Client : {client_prenom} {client_nom}")
    print(f"  {longeur}m | h={hauteur} | bardage={bardage} | fixation={fixation_sol}")
    if configs_sup:
        print(f"  + {len(configs_sup)} configuration(s) supplémentaire(s)")
    print(f"{'='*60}\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            viewport={"width": 1400, "height": 900},
            locale="fr-FR",
            accept_downloads=True,
        )
        page = await context.new_page()
        try:
            nb_items_panier = 0

            # ── Configuration principale ───────────────────────────────
            nb_items_panier += 1
            await _configurer_et_ajouter_cloture(
                page, SITE_URL, PRODUCT_URL,
                modele=modele, longeur=longeur, hauteur=hauteur, bardage=bardage,
                fixation_sol=fixation_sol, type_poteaux=type_poteaux,
                longueur_lames=longueur_lames, sens_bardage=sens_bardage,
                recto_verso=recto_verso, nb_attendu=nb_items_panier,
            )

            # ── Configurations supplémentaires (multi-clôture) ─────────
            for idx, cfg in enumerate(configs_sup):
                print(f"\n  ─── Configuration supplémentaire {idx + 1}/{len(configs_sup)} ───")
                nb_items_panier += 1
                cfg_modele = cfg.get("modele", modele)
                await _configurer_et_ajouter_cloture(
                    page, SITE_URL, _product_url_for(cfg_modele),
                    modele=cfg_modele,
                    longeur=cfg.get("longeur", ""),
                    hauteur=cfg.get("hauteur", ""),
                    bardage=cfg.get("bardage", ""),
                    fixation_sol=cfg.get("fixation_sol", ""),
                    type_poteaux=cfg.get("type_poteaux", ""),
                    longueur_lames=cfg.get("longueur_lames", ""),
                    sens_bardage=cfg.get("sens_bardage", "vertical"),
                    recto_verso=cfg.get("recto_verso", "non"),
                    nb_attendu=nb_items_panier,
                )

            # Produits complémentaires
            produits_list = json.loads(produits_complementaires) if produits_complementaires and produits_complementaires != "[]" else []
            if produits_list:
                await _ajouter_produits_complementaires(page, produits_list, site_url=SITE_URL)

            # Panier : code promo, livraison, date estimée
            date_livraison = await _traiter_panier(page, SITE_URL, code_promo, mode_livraison)

            # Générer le devis via le générateur officiel
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filepath = os.path.join(DOWNLOAD_DIR, f"devis_{client_nom}_{client_prenom}_{timestamp}.pdf")
            filepath = await _generer_devis_via_generateur(
                page, SITE_URL,
                client_nom, client_prenom, client_email, client_telephone, client_adresse,
                filepath,
            )

            elapsed = time.time() - start_time
            print(f"\n  ✅ DEVIS CLÔTURE EN {elapsed:.1f}s — {filepath}")
            return filepath, date_livraison

        except Exception as e:
            print(f"\n  ❌ Erreur clôture : {e}")
            raise
        finally:
            await browser.close()


# ═══════════════════════════════════════════════════════════════
# EXEMPLES D'UTILISATION
# ═══════════════════════════════════════════════════════════════

async def exemple_pergola():
    """Pergola 4m × 3m, adossée, ventelle largeur."""
    return await generer_devis_pergola(
        largeur="4m",
        profondeur="3m",
        fixation="adossee",
        ventelle="largeur",
        option="non",
        client_nom="Dupont",
        client_prenom="Jean",
        client_email="jean.dupont@test.fr",
        client_telephone="0600000000",
        client_adresse="1 Rue de Test, 75001 Paris",
    )


async def exemple_terrasse():
    """Terrasse PIN 27mm Autoclave Vert, 4.2m."""
    return await generer_devis_terrasse(
        essence="PIN 27mm Autoclave Vert",
        longueur="4.2",
        quantite=20,
        client_nom="Dupont",
        client_prenom="Jean",
        client_email="jean.dupont@test.fr",
        client_telephone="0600000000",
        client_adresse="1 Rue de Test, 75001 Paris",
    )


async def exemple_cloture_classique():
    """Clôture classique 10m, hauteur 1.9m, bardage 27x130."""
    return await generer_devis_cloture(
        modele="classique",
        longeur="10",
        hauteur="1-9",
        bardage="27x130",
        fixation_sol="plots-beton",
        type_poteaux="90x90-h",
        longueur_lames="2-m",
        client_nom="Dupont",
        client_prenom="Jean",
        client_email="jean.dupont@test.fr",
        client_telephone="0600000000",
        client_adresse="1 Rue de Test, 75001 Paris",
    )


async def exemple_cloture_moderne():
    """Clôture moderne 20m, hauteur 1.9m, bardage 21x145, vertical."""
    return await generer_devis_cloture(
        modele="moderne",
        longeur="20",
        hauteur="1-9",
        bardage="21x145",
        fixation_sol="plots-beton",
        sens_bardage="vertical",
        recto_verso="non",
        client_nom="Dupont",
        client_prenom="Jean",
        client_email="jean.dupont@test.fr",
        client_telephone="0600000000",
        client_adresse="1 Rue de Test, 75001 Paris",
    )


if __name__ == "__main__":
    import sys
    examples = {
        "pergola":            exemple_pergola,
        "terrasse":           exemple_terrasse,
        "cloture_classique":  exemple_cloture_classique,
        "cloture_moderne":    exemple_cloture_moderne,
    }
    choice = sys.argv[1] if len(sys.argv) > 1 else "pergola"
    if choice in examples:
        asyncio.run(examples[choice]())
    else:
        print(f"Usage: python3 generateur_devis_3sites.py [{' | '.join(examples)}]")
