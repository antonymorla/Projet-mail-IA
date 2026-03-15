#!/usr/bin/env python3
"""
Script d'inspection universelle des champs WAPF et attributs WooCommerce
de TOUS les configurateurs du Groupe Abri Français.

Scanne chaque page produit configurateur, détecte les champs WAPF,
les attributs WooCommerce (selects/swatches), et compare avec les
field IDs connus pour signaler tout nouveau champ.

Usage:
    python scripts/inspect_wapf_all.py              # Tous les configurateurs
    python scripts/inspect_wapf_all.py pergola       # Un seul site
    python scripts/inspect_wapf_all.py --headless    # Sans navigateur visible
    python scripts/inspect_wapf_all.py --json        # Sortie JSON (pour CI/diff)

Résultat : affiche les champs détectés vs connus, signale les NOUVEAUX.
Génère aussi scripts/wapf_reference.json pour suivi des changements.
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from playwright.async_api import async_playwright

# ═══════════════════════════════════════════════════════════════
# CONFIGURATEURS À SCANNER
# ═══════════════════════════════════════════════════════════════

CONFIGURATEURS = {
    "abri": {
        "name": "Abri Français",
        "url": "https://www.xn--abri-franais-sdb.fr/produit/configurateur-abri-de-jardin/",
        "type": "wpc_booster",  # WPC Booster — pas de WAPF attendu, mais on vérifie quand même
    },
    "studio": {
        "name": "Studio Français",
        "url": "https://xn--studio-franais-qjb.fr/produit/55-x-347/",  # Best-seller 5,5×3,5
        "type": "wpc_booster",
    },
    "pergola": {
        "name": "Ma Pergola Bois",
        "url": "https://mapergolabois.fr/produit/pergola-bois-en-kit/",
        "type": "wapf",
    },
    "terrasse": {
        "name": "Terrasse en Bois",
        "url": "https://terrasseenbois.fr/produit/configurateur-terrasse/",
        "type": "wapf",
    },
    "cloture_classique": {
        "name": "Clôture Bois (Classique)",
        "url": "https://cloturebois.fr/produit/kit-cloture-bois-classique/",
        "type": "wc_variations",
    },
    "cloture_moderne": {
        "name": "Clôture Bois (Moderne)",
        "url": "https://cloturebois.fr/produit/kit-cloture-bois-moderne/",
        "type": "wc_variations",
    },
}

# ═══════════════════════════════════════════════════════════════
# CHAMPS CONNUS — référence pour comparaison
# Si un champ n'est pas dans cette liste → NOUVEAU (★)
# ═══════════════════════════════════════════════════════════════

KNOWN_FIELDS = {
    "pergola": {
        "field-de3be54": "Sur-mesure (Oui/Non)",
        "field-fe25811": "Largeur Hors Tout (m)",
        "field-eb3cd46": "Profondeur Hors Tout (m)",
        "field-c6c5dea": "Hauteur Hors Tout (m)",
        "field-e8cec8d": "Pente de toiture",
        "field-5219ffc": "Claustra (type)",
        "field-6bf3105": "Quantité claustra",
        "field-60120c1": "Poteau lamellé-collé (Oui/Non)",
        "field-a7fc76f": "Quantité poteaux lamellé-collé",
        "field-8a0aad9": "Prix TOTAL (affichage)",
    },
    "terrasse": {
        # Champ principal essence
        "field_65c1e3eb8cfb0": "Essence (swatch principal)",
        # Champs longueur de lame par essence
        "field_65c1ebe60b472": "Longueur lame PIN 21mm",
        "field_65c1f585a5289": "Longueur lame PIN 27mm Vert",
        "field_65c1f6b1e8f8e": "Longueur lame PIN 27mm Marron",
        "field_65c1f6e97c942": "Longueur lame PIN 27mm Gris",
        "field_65c1f8a851cd3": "Longueur lame PIN 27mm Thermotraité",
        "field_65c1f822125ec": "Longueur lame FRAKE",
        "field_65c1f6e806c40": "Longueur lame JATOBA",
        "field_65c1f80e4202c": "Longueur lame CUMARU",
        "field_65c1f823a4def": "Longueur lame PADOUK",
        "field_65c1f823984c6": "Longueur lame IPE",
        # Lambourdes & options
        "field_65c249d0a5359": "Type de lambourdes",
        "field_65c5fc624fea1": "Densité lambourdes (simple/double)",
    },
    # Abri et Studio n'utilisent pas WAPF (WPC Booster) — mais on détecte si ça change
    "abri": {},
    "studio": {},
    "cloture_classique": {},
    "cloture_moderne": {},
}


# ═══════════════════════════════════════════════════════════════
# JAVASCRIPT : extraction des champs depuis la page
# ═══════════════════════════════════════════════════════════════

JS_EXTRACT_WAPF = """
() => {
    const fields = [];
    document.querySelectorAll('.wapf-field-container, [class*="wapf-field"]').forEach(container => {
        const classes = Array.from(container.classList);
        // Field ID : soit "field-XXXXXXX" soit "field_XXXXXXX"
        const fieldId = classes.find(c => /^field[-_]/.test(c));

        const label = container.querySelector('.wapf-field-label, label');
        const labelText = label ? label.textContent.trim() : '(no label)';

        const hasSwatch = container.querySelector('.wapf-swatch') !== null;
        const hasInputNum = container.querySelector('input[type="number"]') !== null;
        const hasInputText = container.querySelector('input[type="text"]') !== null;
        const hasSelect = container.querySelector('select') !== null;

        const swatchLabels = [];
        container.querySelectorAll('.wapf-swatch label').forEach(l => {
            const aria = l.getAttribute('aria-label');
            const text = l.textContent.trim();
            swatchLabels.push(aria || text || '(vide)');
        });

        const isHidden = container.classList.contains('wapf-hide');

        const input = container.querySelector('input, select');
        const inputName = input ? input.getAttribute('name') : null;

        let type = 'unknown';
        if (hasSwatch) type = 'swatch';
        else if (hasInputNum) type = 'number';
        else if (hasInputText) type = 'text';
        else if (hasSelect) type = 'select';

        fields.push({
            fieldId: fieldId || null,
            label: labelText,
            type,
            swatchValues: swatchLabels,
            hidden: isHidden,
            inputName,
        });
    });
    return fields;
}
"""

JS_EXTRACT_WC_ATTRIBUTES = """
() => {
    const attrs = [];
    // WooCommerce variation selects
    document.querySelectorAll('.variations select, select[name^="attribute_"]').forEach(sel => {
        const name = sel.getAttribute('name') || sel.getAttribute('id') || '(unknown)';
        const label = sel.closest('tr, .value')?.querySelector('label, th')?.textContent?.trim() || '';
        const options = [];
        sel.querySelectorAll('option').forEach(opt => {
            if (opt.value) options.push(opt.value);
        });
        attrs.push({ name, label, options, type: 'select' });
    });

    // WPC Booster selects (si présent)
    document.querySelectorAll('.wpcbf-select select, [data-wpcbf] select').forEach(sel => {
        const name = sel.getAttribute('name') || sel.getAttribute('id') || '(unknown)';
        const label = sel.closest('.wpcbf-group, .wpcbf-field')?.querySelector('label, .wpcbf-label')?.textContent?.trim() || '';
        const options = [];
        sel.querySelectorAll('option').forEach(opt => {
            if (opt.value) options.push(opt.value);
        });
        attrs.push({ name, label, options, type: 'wpc_select' });
    });

    // WPC Booster swatches (boutons visuels)
    document.querySelectorAll('.wpcbf-swatch-group, [class*="wpcbf-swatch"]').forEach(group => {
        const label = group.closest('.wpcbf-group, .wpcbf-field')?.querySelector('label, .wpcbf-label')?.textContent?.trim() || '';
        const name = group.getAttribute('data-attribute') || group.getAttribute('id') || '';
        const values = [];
        group.querySelectorAll('[data-value], .swatch-label, button, span').forEach(btn => {
            const val = btn.getAttribute('data-value') || btn.getAttribute('aria-label') || btn.textContent?.trim();
            if (val && !values.includes(val)) values.push(val);
        });
        if (values.length) attrs.push({ name, label, options: values, type: 'wpc_swatch' });
    });

    return attrs;
}
"""

JS_EXTRACT_PRODUCT_INFO = """
() => {
    const info = {};
    // Product ID
    const form = document.querySelector('form.cart, form.variations_form');
    if (form) {
        info.product_id = form.getAttribute('data-product_id') || '';
    }
    // Titre produit
    const title = document.querySelector('.product_title, h1.entry-title');
    info.title = title ? title.textContent.trim() : '';
    // Prix affiché
    const price = document.querySelector('.woocommerce-Price-amount, .price .amount');
    info.price = price ? price.textContent.trim() : '';
    // Nombre de variations
    const variationsData = form?.getAttribute('data-product_variations');
    if (variationsData && variationsData !== 'false') {
        try {
            info.nb_variations = JSON.parse(variationsData).length;
        } catch { info.nb_variations = '(JSON trop gros)'; }
    }
    return info;
}
"""


# ═══════════════════════════════════════════════════════════════
# FONCTIONS PRINCIPALES
# ═══════════════════════════════════════════════════════════════

async def fermer_popups(page):
    """Ferme les popups classiques (cookies, newsletter, etc.)."""
    for sel in [".popmake-close", "#cookie-accept", ".close-popup",
                ".cc-dismiss", ".cookie-close", "button.accept-cookies",
                "[aria-label='Close']", ".modal .close"]:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=800):
                await btn.click()
                await page.wait_for_timeout(300)
        except Exception:
            pass


async def inspecter_page(page, site_key: str, config: dict) -> dict:
    """Inspecte une page produit et retourne tous les champs détectés."""
    url = config["url"]
    result = {
        "site": site_key,
        "name": config["name"],
        "url": url,
        "type": config["type"],
        "product_info": {},
        "wapf_fields": [],
        "wc_attributes": [],
        "errors": [],
    }

    try:
        print(f"\n{'─' * 70}")
        print(f"  ► {config['name']} ({site_key})")
        print(f"    {url}")
        print(f"{'─' * 70}")

        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(4000)
        await fermer_popups(page)

        # Info produit
        result["product_info"] = await page.evaluate(JS_EXTRACT_PRODUCT_INFO)
        title = result["product_info"].get("title", "(titre inconnu)")
        print(f"  Produit : {title}")

        # Champs WAPF
        wapf = await page.evaluate(JS_EXTRACT_WAPF)
        result["wapf_fields"] = wapf

        # Attributs WooCommerce / WPC Booster
        wc = await page.evaluate(JS_EXTRACT_WC_ATTRIBUTES)
        result["wc_attributes"] = wc

        nb_wapf = len(wapf)
        nb_wc = len(wc)
        print(f"  WAPF : {nb_wapf} champ(s)  |  WC/WPC : {nb_wc} attribut(s)")

    except Exception as e:
        result["errors"].append(str(e))
        print(f"  ❌ Erreur : {e}")

    return result


def afficher_rapport(results: list[dict]):
    """Affiche le rapport comparatif : connu vs nouveau."""
    total_new = 0

    for r in results:
        site_key = r["site"]
        known = KNOWN_FIELDS.get(site_key, {})

        print(f"\n{'═' * 70}")
        print(f"  {r['name']}  ({site_key})")
        print(f"{'═' * 70}")

        # ── WAPF fields ──
        if r["wapf_fields"]:
            print(f"\n  Champs WAPF ({len(r['wapf_fields'])}) :")
            for f in r["wapf_fields"]:
                fid = f.get("fieldId") or "(sans ID)"
                vis = "🔒" if f["hidden"] else "👁"
                is_known = fid in known

                marker = "  ✓" if is_known else "  ★"
                status = f"(connu: {known[fid]})" if is_known else "NOUVEAU"

                if not is_known and fid != "(sans ID)":
                    total_new += 1

                print(f"  {marker} {vis} {fid}")
                print(f"       Label : {f['label']}")
                print(f"       Type  : {f['type']}  {status}")
                if f["swatchValues"]:
                    vals = ", ".join(f["swatchValues"][:8])
                    if len(f["swatchValues"]) > 8:
                        vals += f" ... (+{len(f['swatchValues']) - 8})"
                    print(f"       Valeurs : [{vals}]")
                if f.get("inputName"):
                    print(f"       Input : {f['inputName']}")
        else:
            print(f"\n  Aucun champ WAPF détecté (attendu pour {r['type']})")

        # ── WC / WPC attributes ──
        if r["wc_attributes"]:
            print(f"\n  Attributs WC/WPC ({len(r['wc_attributes'])}) :")
            for a in r["wc_attributes"]:
                opts = ", ".join(a["options"][:6])
                if len(a["options"]) > 6:
                    opts += f" ... (+{len(a['options']) - 6})"
                print(f"    • {a['label'] or a['name']}  ({a['type']})")
                print(f"      name={a['name']}  [{opts}]")

        if r["errors"]:
            print(f"\n  ⚠ Erreurs : {r['errors']}")

    # ── Résumé final ──
    print(f"\n{'═' * 70}")
    print("  RÉSUMÉ")
    print(f"{'═' * 70}")
    for r in results:
        nb_wapf = len(r["wapf_fields"])
        nb_wc = len(r["wc_attributes"])
        site_known = KNOWN_FIELDS.get(r["site"], {})
        nb_new = sum(
            1 for f in r["wapf_fields"]
            if f.get("fieldId") and f["fieldId"] not in site_known
        )
        status = f"  ★ {nb_new} NOUVEAU(X)" if nb_new else "  ✓ OK"
        print(f"  {r['name']:30s}  WAPF={nb_wapf:2d}  WC={nb_wc:2d}{status}")

    print(f"\n  Total nouveaux champs : {total_new}")
    if total_new:
        print("  → Mettez à jour KNOWN_FIELDS dans ce script + le code générateur.")
    print()

    return total_new


def sauvegarder_json(results: list[dict], output_path: str):
    """Sauvegarde le résultat complet en JSON pour historique/diff."""
    data = {
        "scan_date": datetime.now().isoformat(),
        "sites": {},
    }
    for r in results:
        site_known = KNOWN_FIELDS.get(r["site"], {})
        fields_summary = []
        for f in r["wapf_fields"]:
            fid = f.get("fieldId") or "(sans ID)"
            fields_summary.append({
                "field_id": fid,
                "label": f["label"],
                "type": f["type"],
                "swatch_values": f["swatchValues"],
                "hidden": f["hidden"],
                "input_name": f.get("inputName"),
                "known": fid in site_known,
            })

        data["sites"][r["site"]] = {
            "name": r["name"],
            "url": r["url"],
            "product_info": r["product_info"],
            "wapf_fields": fields_summary,
            "wc_attributes": r["wc_attributes"],
            "errors": r["errors"],
        }

    with open(output_path, "w", encoding="utf-8") as fp:
        json.dump(data, fp, indent=2, ensure_ascii=False)
    print(f"  📄 Résultat sauvegardé : {output_path}")


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

async def main():
    # Parse arguments
    args = sys.argv[1:]
    headless = "--headless" in args
    json_output = "--json" in args
    site_filter = [a for a in args if not a.startswith("--")]

    # Filtrer les sites demandés
    sites_to_scan = {}
    if site_filter:
        for key in site_filter:
            # Permettre "cloture" pour matcher les deux
            matches = {k: v for k, v in CONFIGURATEURS.items() if key in k}
            if matches:
                sites_to_scan.update(matches)
            else:
                print(f"  ⚠ Site '{key}' inconnu. Disponibles : {', '.join(CONFIGURATEURS.keys())}")
                sys.exit(1)
    else:
        sites_to_scan = CONFIGURATEURS

    print("=" * 70)
    print("  INSPECTION UNIVERSELLE — Configurateurs Groupe Abri Français")
    print(f"  {len(sites_to_scan)} site(s) à scanner")
    print(f"  Mode : {'headless' if headless else 'navigateur visible'}")
    print("=" * 70)

    results = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        page = await browser.new_page(viewport={"width": 1400, "height": 900})

        for site_key, config in sites_to_scan.items():
            result = await inspecter_page(page, site_key, config)
            results.append(result)

        await browser.close()

    # Rapport console
    total_new = afficher_rapport(results)

    # Sauvegarde JSON
    script_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(script_dir, "wapf_reference.json")
    sauvegarder_json(results, json_path)

    if json_output:
        # En mode --json, imprimer aussi sur stdout pour piping
        with open(json_path, "r") as fp:
            print(fp.read())

    # Exit code non-zéro si nouveaux champs détectés (utile pour CI)
    sys.exit(1 if total_new > 0 else 0)


if __name__ == "__main__":
    asyncio.run(main())
