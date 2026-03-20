#!/usr/bin/env python3
"""
Analyse un configurateur WPC (Abri ou Studio) et affiche toutes les options disponibles.
Lance le navigateur, charge la page produit, et parcourt l'arborescence WPC complète.

Usage:
    python3 analyser_configurateur.py studio 5,5x3,5
    python3 analyser_configurateur.py abri
"""
import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("❌ Playwright non installé.")
    sys.exit(1)

from generateur_devis_auto import SITES


async def analyser_wpc(page) -> dict:
    """Parcourt l'arborescence WPC et retourne toutes les options disponibles."""
    tree = await page.evaluate("""
        () => {
            function parseItem(li, depth) {
                var text = li.getAttribute('data-text') || '';
                var uid = li.getAttribute('data-uid') || '';
                var isCurrent = li.classList.contains('current');
                var isHidden = li.classList.contains('wpc-cl-hide-group');

                // Chercher les enfants dans .wpc-control-lists > ul > li OU > ul > li
                var children = [];
                var container = li.querySelector(':scope > .wpc-control-lists > ul')
                             || li.querySelector(':scope > ul');
                if (container) {
                    for (var child of container.querySelectorAll(':scope > li.wpc-control-item')) {
                        children.push(parseItem(child, depth + 1));
                    }
                }

                var node = {text: text, depth: depth};
                if (isCurrent) node.selected = true;
                if (isHidden) node.hidden = true;
                if (uid) node.uid = uid;
                if (children.length > 0) node.children = children;
                return node;
            }

            // Trouver les groupes racine (niveau 0)
            var roots = [];
            var allItems = document.querySelectorAll('li.wpc-control-item');
            var processed = new Set();

            for (var item of allItems) {
                // Un item racine n'a pas de parent li.wpc-control-item
                var parent = item.parentElement;
                while (parent && parent.tagName !== 'LI') parent = parent.parentElement;
                if (parent && parent.classList && parent.classList.contains('wpc-control-item')) continue;

                if (!processed.has(item)) {
                    processed.add(item);
                    roots.push(parseItem(item, 0));
                }
            }
            return roots;
        }
    """)
    return tree


def print_tree(nodes, indent=0):
    """Affiche l'arborescence de façon lisible."""
    for node in nodes:
        prefix = "  " * indent
        markers = []
        if node.get("selected"):
            markers.append("✓ SÉLECTIONNÉ")
        if node.get("hidden"):
            markers.append("⊘ MASQUÉ")
        suffix = f"  [{', '.join(markers)}]" if markers else ""
        print(f"{prefix}├─ {node['text']}{suffix}")
        if "children" in node:
            print_tree(node["children"], indent + 1)


def flatten_groups(nodes, path=None):
    """Aplatit l'arbre en groupes avec leurs options visibles."""
    if path is None:
        path = []
    groups = {}
    for node in nodes:
        current_path = path + [node["text"]]
        children = node.get("children", [])
        if children:
            # C'est un groupe — lister ses enfants directs
            visible_options = [c["text"] for c in children if not c.get("hidden")]
            hidden_options = [c["text"] for c in children if c.get("hidden")]
            key = " > ".join(current_path)
            if visible_options and not any(c.get("children") for c in children):
                # Feuilles uniquement
                groups[key] = {"visible": visible_options, "hidden": hidden_options}
            # Récurser
            sub = flatten_groups(children, current_path)
            groups.update(sub)
    return groups


async def main():
    if len(sys.argv) < 2:
        print("Usage: python3 analyser_configurateur.py <site> [dimensions]")
        print("  site: abri | studio")
        print("  dimensions (studio): 5,5x3,5 | 8,8x5,7 | etc.")
        print("\nExemples:")
        print("  python3 analyser_configurateur.py abri")
        print("  python3 analyser_configurateur.py studio 5,5x3,5")
        sys.exit(1)

    site = sys.argv[1].lower()
    if site not in SITES:
        print(f"❌ Site inconnu: {site}. Disponibles: {', '.join(SITES.keys())}")
        sys.exit(1)

    site_config = SITES[site]
    base_url = site_config["url"]

    if site == "studio":
        if len(sys.argv) < 3:
            print("❌ Dimensions requises pour studio. Ex: python3 analyser_configurateur.py studio 5,5x3,5")
            dims = sorted(site_config["dimensions"].keys())
            print(f"Disponibles: {', '.join(dims)}")
            sys.exit(1)
        dim_key = sys.argv[2]
        dim_map = site_config.get("dimensions", {})
        product_path = dim_map.get(dim_key)
        if not product_path:
            print(f"❌ Dimension '{dim_key}' non trouvée.")
            print(f"Disponibles: {', '.join(sorted(dim_map.keys()))}")
            sys.exit(1)
        url = base_url + product_path
    else:
        url = base_url + site_config["configurateur"]

    print(f"{'='*70}")
    print(f"  ANALYSE CONFIGURATEUR — {site_config['name']}")
    print(f"  URL: {url}")
    print(f"{'='*70}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page(viewport={"width": 1400, "height": 900})

        # Bloquer les popups via CSS
        await page.add_style_tag(content="""
            #popup-modal, .cmplz-cookiebanner, .pum-overlay,
            .cmplz-modal { pointer-events: none !important; display: none !important; }
        """)

        print("\n  Chargement de la page...")
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_selector("li.wpc-control-item", timeout=20000)
        await page.wait_for_timeout(2000)

        # Fermer cookies si visible
        for sel in [".cmplz-accept", "button:has-text('Accepter')"]:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=1000):
                    await btn.click()
                    await page.wait_for_timeout(500)
            except Exception:
                pass

        print("  Analyse de l'arborescence WPC...\n")
        tree = await analyser_wpc(page)

        # Affichage arbre complet
        print(f"{'─'*70}")
        print("  ARBORESCENCE COMPLÈTE")
        print(f"{'─'*70}")
        print_tree(tree)

        # Affichage groupes aplatis (options disponibles)
        print(f"\n{'─'*70}")
        print("  OPTIONS PAR GROUPE (visibles uniquement)")
        print(f"{'─'*70}")
        groups = flatten_groups(tree)
        for group_path, opts in groups.items():
            print(f"\n  {group_path}:")
            for o in opts["visible"]:
                print(f"    • {o}")
            if opts["hidden"]:
                print(f"    (masqués: {', '.join(opts['hidden'])})")

        # Résumé
        total_visible = sum(len(g["visible"]) for g in groups.values())
        total_hidden = sum(len(g["hidden"]) for g in groups.values())
        print(f"\n{'─'*70}")
        print(f"  RÉSUMÉ: {len(groups)} groupes | {total_visible} options visibles | {total_hidden} masquées")
        print(f"{'─'*70}")

        # Exporter en JSON (optionnel)
        json_path = os.path.join(os.path.dirname(__file__), f"wpc_analysis_{site}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({"site": site, "url": url, "tree": tree, "groups": {k: v for k, v in groups.items()}}, f, ensure_ascii=False, indent=2)
        print(f"  Export JSON: {json_path}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
