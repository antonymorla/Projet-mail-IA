#!/usr/bin/env python3
"""
Extraction complète des données WAPF du configurateur pergola.

Navigue sur mapergolabois.fr, sélectionne une variation, et extrait
TOUS les champs WAPF avec leurs valeurs possibles, leur état (visible/caché),
et les conditions de visibilité.

Teste aussi la visibilité de chaque champ selon différentes configurations
de variation (carport, platelage, voilage, etc.) pour comprendre les
dépendances conditionnelles.

Usage :
    python tests/test_extract_wapf_pergola.py                    # navigateur visible
    python tests/test_extract_wapf_pergola.py --headless         # sans navigateur
    python tests/test_extract_wapf_pergola.py --json             # sortie JSON
"""

import asyncio
import json
import os
import sys

from playwright.async_api import async_playwright

PERGOLA_URL = "https://mapergolabois.fr/produit/pergola-bois-en-kit/"

# Toutes les options à tester pour comprendre les conditions de visibilité
OPTIONS_VARIATIONS = [
    {"label": "carport", "attrs": {
        "attribute_pa_largeur": "5m", "attribute_pa_profondeur": "4m",
        "attribute_pa_fixation": "independante", "attribute_pa_ventelle": "largeur",
        "attribute_pa_option": "carport",
    }},
    {"label": "platelage", "attrs": {
        "attribute_pa_largeur": "5m", "attribute_pa_profondeur": "4m",
        "attribute_pa_fixation": "independante", "attribute_pa_ventelle": "largeur",
        "attribute_pa_option": "platelage",
    }},
    {"label": "voilage", "attrs": {
        "attribute_pa_largeur": "5m", "attribute_pa_profondeur": "4m",
        "attribute_pa_fixation": "independante", "attribute_pa_ventelle": "largeur",
        "attribute_pa_option": "voilage",
    }},
    {"label": "sans option", "attrs": {
        "attribute_pa_largeur": "5m", "attribute_pa_profondeur": "4m",
        "attribute_pa_fixation": "independante", "attribute_pa_ventelle": "largeur",
        "attribute_pa_option": "non",
    }},
    {"label": "lattage", "attrs": {
        "attribute_pa_largeur": "5m", "attribute_pa_profondeur": "4m",
        "attribute_pa_fixation": "independante", "attribute_pa_ventelle": "largeur",
        "attribute_pa_option": "lattage",
    }},
    {"label": "bioclimatique", "attrs": {
        "attribute_pa_largeur": "5m", "attribute_pa_profondeur": "4m",
        "attribute_pa_fixation": "independante", "attribute_pa_ventelle": "largeur",
        "attribute_pa_option": "bioclimatique",
    }},
    {"label": "polycarbonate", "attrs": {
        "attribute_pa_largeur": "5m", "attribute_pa_profondeur": "4m",
        "attribute_pa_fixation": "independante", "attribute_pa_ventelle": "largeur",
        "attribute_pa_option": "polycarbonate",
    }},
    {"label": "carport ventelle profondeur", "attrs": {
        "attribute_pa_largeur": "5m", "attribute_pa_profondeur": "4m",
        "attribute_pa_fixation": "independante", "attribute_pa_ventelle": "profondeur",
        "attribute_pa_option": "carport",
    }},
    {"label": "carport adossée", "attrs": {
        "attribute_pa_largeur": "5m", "attribute_pa_profondeur": "4m",
        "attribute_pa_fixation": "adossee", "attribute_pa_ventelle": "largeur",
        "attribute_pa_option": "carport",
    }},
]

JS_EXTRACT_ALL_WAPF = """
() => {
    const fields = [];
    document.querySelectorAll('.wapf-field-container, [class*="wapf-field"]').forEach(container => {
        const classes = Array.from(container.classList);
        const fieldId = classes.find(c => /^field[-_]/.test(c));

        const label = container.querySelector('.wapf-field-label, label');
        const labelText = label ? label.textContent.trim() : '(no label)';

        const isHidden = container.classList.contains('wapf-hide');
        const computedDisplay = getComputedStyle(container).display;

        // Détection du type de champ
        const hasSwatch = container.querySelector('.wapf-swatch') !== null;
        const hasInputNum = container.querySelector('input[type="number"]') !== null;
        const hasInputText = container.querySelector('input[type="text"]') !== null;
        const hasSelect = container.querySelector('select') !== null;

        let type = 'unknown';
        if (hasSwatch) type = 'swatch';
        else if (hasInputNum) type = 'number';
        else if (hasInputText) type = 'text';
        else if (hasSelect) type = 'select';

        // Extraire les valeurs swatch
        const swatchValues = [];
        container.querySelectorAll('.wapf-swatch label').forEach(l => {
            const aria = l.getAttribute('aria-label') || '';
            const text = l.textContent.trim();
            const input = l.querySelector('input');
            const inputChecked = input ? input.checked : false;
            const inputValue = input ? input.value : '';
            const inputName = input ? input.name : '';
            const inputType = input ? input.type : '';
            const isSelected = l.classList.contains('selected');
            swatchValues.push({
                aria_label: aria,
                text: text,
                input_checked: inputChecked,
                input_value: inputValue,
                input_name: inputName,
                input_type: inputType,
                is_selected: isSelected,
            });
        });

        // Extraire les valeurs input
        const inputValues = [];
        container.querySelectorAll('input').forEach(inp => {
            inputValues.push({
                type: inp.type,
                name: inp.name,
                value: inp.value,
                checked: inp.checked,
                disabled: inp.disabled,
                placeholder: inp.placeholder,
            });
        });

        // Extraire les valeurs select
        const selectValues = [];
        container.querySelectorAll('select').forEach(sel => {
            const options = [];
            sel.querySelectorAll('option').forEach(opt => {
                options.push({value: opt.value, text: opt.textContent.trim(), selected: opt.selected});
            });
            selectValues.push({name: sel.name, options: options, selected_value: sel.value});
        });

        // Conditions de visibilité (data attributes)
        const dataAttrs = {};
        for (const attr of container.attributes) {
            if (attr.name.startsWith('data-')) {
                dataAttrs[attr.name] = attr.value.substring(0, 300);
            }
        }

        fields.push({
            field_id: fieldId || null,
            label: labelText,
            type: type,
            hidden: isHidden,
            computed_display: computedDisplay,
            swatch_values: swatchValues,
            input_values: inputValues,
            select_values: selectValues,
            data_attrs: dataAttrs,
            classes: classes,
        });
    });
    return fields;
}
"""


async def fermer_popups(page):
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


async def select_variation(page, attrs: dict):
    """Sélectionner une variation WC via jQuery."""
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


async def extract_wc_attributes(page):
    """Extraire tous les attributs WC (select/swatch) et leurs options."""
    return await page.evaluate("""
        () => {
            const attrs = [];
            document.querySelectorAll('select[name^="attribute_"]').forEach(sel => {
                const name = sel.getAttribute('name');
                const label = sel.closest('tr, .value')?.querySelector('label, th')?.textContent?.trim() || '';
                const options = [];
                sel.querySelectorAll('option').forEach(opt => {
                    if (opt.value) options.push({value: opt.value, text: opt.textContent.trim()});
                });
                const selected = sel.value;
                attrs.push({name, label, options, selected});
            });
            return attrs;
        }
    """)


async def main():
    headless = "--headless" in sys.argv
    json_output = "--json" in sys.argv

    print("=" * 70)
    print("  EXTRACTION WAPF COMPLÈTE — Pergola mapergolabois.fr")
    print(f"  Mode : {'headless' if headless else 'navigateur visible'}")
    print("=" * 70)

    all_results = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        page = await browser.new_page(viewport={"width": 1400, "height": 900})

        # Charger la page
        print("\nChargement de la page produit...")
        await page.goto(PERGOLA_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(4000)
        await fermer_popups(page)
        await page.wait_for_selector("form.variations_form", timeout=15000)

        # ── Extraire les attributs WC (les selects de variation) ──
        print("\n" + "─" * 70)
        print("  ATTRIBUTS WC (sélecteurs de variation)")
        print("─" * 70)
        wc_attrs = await extract_wc_attributes(page)
        for attr in wc_attrs:
            print(f"\n  {attr['name']} ({attr['label']}):")
            for opt in attr["options"]:
                print(f"    • {opt['value']:20s}  {opt['text']}")
        all_results["wc_attributes"] = wc_attrs

        # ── Tester chaque option et extraire les champs WAPF ──────
        all_results["variations_wapf"] = {}

        for var_config in OPTIONS_VARIATIONS:
            label = var_config["label"]
            attrs = var_config["attrs"]

            print(f"\n{'─' * 70}")
            print(f"  Variation : {label}")
            print(f"  {attrs}")
            print(f"{'─' * 70}")

            # Recharger la page pour chaque test (état propre)
            await page.goto(PERGOLA_URL, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)
            await fermer_popups(page)
            await page.wait_for_selector("form.variations_form", timeout=15000)
            await page.wait_for_timeout(1500)

            # Sélectionner la variation
            await select_variation(page, attrs)
            await page.wait_for_timeout(2500)

            # Prix
            prix = await page.evaluate("""
                () => {
                    var p = document.querySelector('.woocommerce-variation-price .woocommerce-Price-amount');
                    return p ? p.textContent.trim() : null;
                }
            """)
            print(f"  Prix : {prix or '(pas de prix)'}")

            # Extraire TOUS les champs WAPF
            wapf_fields = await page.evaluate(JS_EXTRACT_ALL_WAPF)

            var_result = {"prix": prix, "fields": []}

            for field in wapf_fields:
                fid = field.get("field_id", "(sans ID)")
                visible = "VISIBLE" if not field["hidden"] else "CACHÉ"
                ftype = field["type"]
                label_text = field["label"]

                field_info = {
                    "field_id": fid,
                    "label": label_text,
                    "type": ftype,
                    "visible": not field["hidden"],
                }

                print(f"\n  [{visible:7s}] {fid}")
                print(f"    Label : {label_text}")
                print(f"    Type  : {ftype}")

                if field["swatch_values"]:
                    vals = []
                    for s in field["swatch_values"]:
                        marker = "●" if s["input_checked"] else "○"
                        vals.append(f"{marker} {s['aria_label']}")
                        print(f"      {marker} aria-label=\"{s['aria_label']}\"  "
                              f"value=\"{s['input_value']}\"  "
                              f"name=\"{s['input_name']}\"  "
                              f"checked={s['input_checked']}")
                    field_info["swatch_values"] = [s["aria_label"] for s in field["swatch_values"]]
                    field_info["swatch_details"] = field["swatch_values"]

                if field["input_values"]:
                    for inp in field["input_values"]:
                        if inp["type"] not in ("hidden", "radio"):
                            print(f"      input type={inp['type']} name=\"{inp['name']}\" "
                                  f"value=\"{inp['value']}\" disabled={inp['disabled']}")
                    field_info["inputs"] = field["input_values"]

                if field["select_values"]:
                    for sel in field["select_values"]:
                        print(f"      select name=\"{sel['name']}\" selected=\"{sel['selected_value']}\"")
                        for opt in sel["options"][:10]:
                            print(f"        • {opt['value']}: {opt['text']}")
                    field_info["selects"] = field["select_values"]

                if field["data_attrs"]:
                    for k, v in field["data_attrs"].items():
                        print(f"      {k}={v[:100]}")
                    field_info["data_attrs"] = field["data_attrs"]

                var_result["fields"].append(field_info)

            all_results["variations_wapf"][label] = var_result

        await browser.close()

    # ── Résumé : matrice de visibilité ────────────────────────────
    print("\n" + "=" * 70)
    print("  MATRICE DE VISIBILITÉ WAPF × OPTION")
    print("=" * 70)

    # Collecter tous les field_ids uniques
    all_field_ids = set()
    field_labels = {}
    for var_label, var_data in all_results["variations_wapf"].items():
        for f in var_data["fields"]:
            fid = f["field_id"]
            all_field_ids.add(fid)
            field_labels[fid] = f["label"]

    # En-tête
    option_labels = [v["label"] for v in OPTIONS_VARIATIONS]
    header = f"{'Field ID':<20s} {'Label':<30s} " + " ".join(f"{l:>12s}" for l in option_labels)
    print(f"\n{header}")
    print("─" * len(header))

    for fid in sorted(all_field_ids, key=lambda x: x or ""):
        label = field_labels.get(fid, "?")[:28]
        row = f"{(fid or '?'):<20s} {label:<30s} "
        for opt_label in option_labels:
            var_data = all_results["variations_wapf"].get(opt_label, {})
            field_match = next((f for f in var_data.get("fields", []) if f["field_id"] == fid), None)
            if field_match:
                status = "✓" if field_match["visible"] else "✗"
            else:
                status = "—"
            row += f"{status:>12s} "
        print(row)

    # ── Sortie JSON ───────────────────────────────────────────────
    if json_output:
        output_path = os.path.join(os.path.dirname(__file__), "..", "scripts", "wapf_pergola_extract.json")
        with open(output_path, "w", encoding="utf-8") as fp:
            json.dump(all_results, fp, indent=2, ensure_ascii=False)
        print(f"\n  📄 JSON sauvegardé : {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
