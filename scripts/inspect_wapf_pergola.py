#!/usr/bin/env python3
"""
Script d'inspection des champs WAPF du configurateur pergola.
Exécuter en local pour trouver les field IDs claustra/bardage.

Usage:
    python scripts/inspect_wapf_pergola.py
"""

import asyncio
from playwright.async_api import async_playwright


async def main():
    PRODUCT_URL = "https://mapergolabois.fr/produit/pergola-bois-en-kit/"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page(viewport={"width": 1400, "height": 900})

        print(f"→ Chargement de {PRODUCT_URL}")
        await page.goto(PRODUCT_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(5000)

        # Fermer les popups
        for sel in [".popmake-close", "#cookie-accept", ".close-popup"]:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=1000):
                    await btn.click()
            except Exception:
                pass

        # ── 1. Lister TOUS les champs WAPF ────────────────────────────
        print("\n" + "=" * 70)
        print("  TOUS LES CHAMPS WAPF DÉTECTÉS")
        print("=" * 70)

        wapf_fields = await page.evaluate("""
            () => {
                const fields = [];
                document.querySelectorAll('.wapf-field-container').forEach(container => {
                    const classes = Array.from(container.classList);
                    const fieldId = classes.find(c => c.startsWith('field-'));

                    // Trouver le label
                    const label = container.querySelector('.wapf-field-label, label');
                    const labelText = label ? label.textContent.trim() : '(no label)';

                    // Type de champ
                    const hasSwatch = container.querySelector('.wapf-swatch') !== null;
                    const hasInput = container.querySelector('input[type="number"], input[type="text"]') !== null;
                    const hasSelect = container.querySelector('select') !== null;

                    // Valeurs des swatches
                    const swatchLabels = [];
                    container.querySelectorAll('.wapf-swatch label').forEach(l => {
                        swatchLabels.push(l.getAttribute('aria-label') || l.textContent.trim());
                    });

                    // Visibilité
                    const isHidden = container.classList.contains('wapf-hide');

                    // Input name
                    const input = container.querySelector('input, select');
                    const inputName = input ? input.getAttribute('name') : null;

                    fields.push({
                        fieldId,
                        label: labelText,
                        type: hasSwatch ? 'swatch' : hasInput ? 'input' : hasSelect ? 'select' : 'unknown',
                        swatchValues: swatchLabels,
                        hidden: isHidden,
                        inputName,
                    });
                });
                return fields;
            }
        """)

        for f in wapf_fields:
            visibility = "HIDDEN" if f["hidden"] else "VISIBLE"
            print(f"\n  [{visibility}] {f['fieldId']}")
            print(f"    Label: {f['label']}")
            print(f"    Type: {f['type']}")
            if f["swatchValues"]:
                print(f"    Swatch values: {f['swatchValues']}")
            if f["inputName"]:
                print(f"    Input name: {f['inputName']}")

        # ── 2. Chercher spécifiquement les claustras ──────────────────
        print("\n" + "=" * 70)
        print("  RECHERCHE CLAUSTRA / BARDAGE")
        print("=" * 70)

        claustra_fields = [f for f in wapf_fields
                          if any(kw in (f["label"] or "").lower()
                                for kw in ["claustra", "bardage", "panneau", "claustra"])]

        claustra_swatch_fields = [f for f in wapf_fields
                                  if f["type"] == "swatch"
                                  and any("claustra" in v.lower() or "bardage" in v.lower()
                                         for v in f.get("swatchValues", []))]

        all_claustra = {f["fieldId"]: f for f in claustra_fields + claustra_swatch_fields}

        if all_claustra:
            for fid, f in all_claustra.items():
                print(f"\n  ✅ TROUVÉ: {fid}")
                print(f"    Label: {f['label']}")
                print(f"    Type: {f['type']}")
                print(f"    Swatch values: {f.get('swatchValues', [])}")
                print(f"    Input name: {f.get('inputName', '')}")
                print(f"    Hidden: {f['hidden']}")
        else:
            print("\n  ⚠ Aucun champ claustra/bardage trouvé directement.")
            print("  Vérifiez la liste complète ci-dessus pour identifier le bon champ.")

        # ── 3. Résumé des field IDs connus vs nouveaux ────────────────
        print("\n" + "=" * 70)
        print("  RÉSUMÉ — Field IDs")
        print("=" * 70)

        KNOWN_FIELDS = {
            "field-de3be54": "Sur-mesure (Oui/Non)",
            "field-fe25811": "Largeur Hors Tout",
            "field-eb3cd46": "Profondeur Hors Tout",
            "field-c6c5dea": "Hauteur Hors Tout",
            "field-60120c1": "Poteau lamellé-collé (Oui/Non)",
            "field-a7fc76f": "Quantité poteaux",
        }

        for f in wapf_fields:
            fid = f["fieldId"]
            if fid in KNOWN_FIELDS:
                print(f"  ✓ {fid} → {KNOWN_FIELDS[fid]} (déjà dans le code)")
            else:
                print(f"  ★ {fid} → {f['label']} — NOUVEAU (à ajouter ?)")

        print("\n" + "=" * 70)
        print("  Copie-colle les field IDs claustra dans le code !")
        print("=" * 70)

        # Attendre que l'utilisateur ferme le navigateur
        input("\nAppuie sur Entrée pour fermer le navigateur...")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
