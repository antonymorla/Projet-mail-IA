#!/usr/bin/env python3
"""Scrape le configurateur WPC Booster du studio pour découvrir la structure DOM complète.

Ouvre le configurateur studio, dump TOUS les groupes/options WPC avec :
- data-text, data-uid, classes, visibilité, sélection
- Structure d'imbrication (parent → enfants)
- Test avec isolation 60mm puis RE2020 pour voir les options qui changent

Usage :
    python3 scripts/scrape_wpc_studio.py
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("❌ Playwright non installé. Lancer :")
    print("   pip install playwright && playwright install chromium")
    sys.exit(1)

from utils_playwright import fermer_popups

STUDIO_URL = "https://xn--studio-franais-qjb.fr/produit/44-x-347/"

JS_DUMP_ALL = """
() => {
    function dumpTree(root, depth) {
        var results = [];
        // Chercher les items WPC à ce niveau
        var items = root.querySelectorAll(':scope > li.wpc-control-item, :scope > ul > li.wpc-control-item');
        for (var item of items) {
            var text = item.getAttribute('data-text') || '';
            var uid = item.getAttribute('data-uid') || '';
            var id = item.getAttribute('data-id') || '';
            var visible = item.offsetParent !== null;
            var style = window.getComputedStyle(item);
            var display = style.display;
            var visibility = style.visibility;
            var classes = item.className || '';

            // Chercher les enfants (sous-options)
            var children = [];
            var childUls = item.querySelectorAll(':scope > ul');
            for (var ul of childUls) {
                var sub = dumpTree(ul, depth + 1);
                children = children.concat(sub);
            }
            // Aussi chercher les enfants directs li (sans ul intermédiaire)
            var directLis = item.querySelectorAll(':scope > li.wpc-control-item');
            for (var li of directLis) {
                children.push({
                    text: li.getAttribute('data-text') || '',
                    uid: li.getAttribute('data-uid') || '',
                    id: li.getAttribute('data-id') || '',
                    visible: li.offsetParent !== null,
                    display: window.getComputedStyle(li).display,
                    classes: (li.className || '').substring(0, 120),
                    depth: depth + 1,
                    children: [],
                    tag: li.tagName,
                    parentTag: li.parentElement ? li.parentElement.tagName : '',
                });
            }

            results.push({
                text: text,
                uid: uid,
                id: id,
                visible: visible,
                display: display,
                visibility: visibility,
                classes: classes.substring(0, 120),
                depth: depth,
                children: children,
                tag: item.tagName,
                parentTag: item.parentElement ? item.parentElement.tagName : '',
                innerHTML_snippet: item.innerHTML.substring(0, 200),
            });
        }
        return results;
    }

    // Point d'entrée : chercher le form.cart ou le conteneur WPC principal
    var form = document.querySelector('form.cart');
    if (!form) return {error: 'form.cart introuvable'};

    var tree = dumpTree(form, 0);

    // Aussi chercher wpc-encoded pour voir les sélections actuelles
    var enc = form.querySelector('[name="wpc-encoded"]');
    var encoded = enc ? atob(enc.value) : '';

    return {
        tree: tree,
        wpc_encoded: encoded,
        total_items: document.querySelectorAll('li.wpc-control-item').length,
    };
}
"""

# Script JS ciblé pour chercher le groupe "Plancher" spécifiquement
JS_DUMP_PLANCHER = """
() => {
    var allItems = document.querySelectorAll('li.wpc-control-item');
    var results = [];
    for (var item of allItems) {
        var text = item.getAttribute('data-text') || '';
        if (text.toLowerCase().includes('plancher') || text.toLowerCase().includes('floor')) {
            // Dump complet de cet élément et de tous ses descendants
            var desc = item.querySelectorAll('*');
            var innerItems = [];
            for (var d of desc) {
                if (d.tagName === 'LI' || d.getAttribute('data-text')) {
                    innerItems.push({
                        tag: d.tagName,
                        dataText: d.getAttribute('data-text') || '',
                        dataUid: d.getAttribute('data-uid') || '',
                        classes: (d.className || '').substring(0, 150),
                        visible: d.offsetParent !== null,
                        display: window.getComputedStyle(d).display,
                    });
                }
            }
            results.push({
                text: text,
                uid: item.getAttribute('data-uid') || '',
                classes: (item.className || '').substring(0, 150),
                visible: item.offsetParent !== null,
                display: window.getComputedStyle(item).display,
                parentTag: item.parentElement ? item.parentElement.tagName : '',
                parentClasses: item.parentElement ? (item.parentElement.className || '').substring(0, 100) : '',
                grandParentTag: item.parentElement && item.parentElement.parentElement ?
                    item.parentElement.parentElement.tagName : '',
                grandParentDataText: item.parentElement && item.parentElement.parentElement ?
                    (item.parentElement.parentElement.getAttribute('data-text') || '') : '',
                innerHTML: item.innerHTML.substring(0, 500),
                innerItems: innerItems,
            });
        }
    }
    return results;
}
"""

# Script JS pour trouver la structure exacte autour de "Plancher" dans le DOM
JS_DOM_PATH = """
() => {
    var allItems = document.querySelectorAll('li.wpc-control-item');
    var plancher_group = null;
    for (var item of allItems) {
        var text = item.getAttribute('data-text') || '';
        if (text.trim() === 'Plancher') {
            plancher_group = item;
            break;
        }
    }
    if (!plancher_group) {
        // Chercher avec espace trailing
        for (var item of allItems) {
            var text = item.getAttribute('data-text') || '';
            if (text.startsWith('Plancher')) {
                plancher_group = item;
                break;
            }
        }
    }
    if (!plancher_group) return {error: 'Groupe Plancher introuvable', all_texts: Array.from(allItems).map(i => i.getAttribute('data-text'))};

    // Remonter la hiérarchie DOM
    var path = [];
    var el = plancher_group;
    for (var i = 0; i < 10 && el; i++) {
        path.push({
            tag: el.tagName,
            dataText: el.getAttribute ? (el.getAttribute('data-text') || '') : '',
            classes: el.className ? (el.className + '').substring(0, 100) : '',
            childrenCount: el.children ? el.children.length : 0,
        });
        el = el.parentElement;
    }

    // Lister TOUT le contenu du groupe Plancher
    var allDescendants = plancher_group.querySelectorAll('*');
    var descendantInfo = [];
    for (var d of allDescendants) {
        descendantInfo.push({
            tag: d.tagName,
            dataText: d.getAttribute('data-text') || '',
            dataUid: d.getAttribute('data-uid') || '',
            classes: (d.className || '').substring(0, 80),
            visible: d.offsetParent !== null,
            textContent: (d.textContent || '').trim().substring(0, 60),
        });
    }

    // Tester différents sélecteurs
    var tests = {
        'scope_ul_li': plancher_group.querySelectorAll(':scope > ul > li.wpc-control-item').length,
        'scope_ul_li_any': plancher_group.querySelectorAll(':scope > ul > li').length,
        'scope_li': plancher_group.querySelectorAll(':scope > li').length,
        'all_li': plancher_group.querySelectorAll('li').length,
        'all_wpc_items': plancher_group.querySelectorAll('li.wpc-control-item').length,
        'scope_div_ul_li': plancher_group.querySelectorAll(':scope > div > ul > li.wpc-control-item').length,
        'scope_any_ul_li': plancher_group.querySelectorAll('ul > li.wpc-control-item').length,
        'all_data_text': Array.from(plancher_group.querySelectorAll('[data-text]')).map(e => e.getAttribute('data-text')),
    };

    return {
        plancher_data_text: plancher_group.getAttribute('data-text'),
        plancher_uid: plancher_group.getAttribute('data-uid'),
        dom_path: path,
        selector_tests: tests,
        descendants_count: descendantInfo.length,
        descendants: descendantInfo.slice(0, 50),  // premiers 50
    };
}
"""


def print_tree(items, indent=0):
    """Affiche l'arbre WPC de manière lisible."""
    for item in items:
        prefix = "  " * indent
        vis = "👁" if item.get("visible") else "🚫"
        text = item.get("text", "")
        uid = item.get("uid", "")
        display = item.get("display", "")
        tag = item.get("tag", "")
        parent_tag = item.get("parentTag", "")
        print(f"{prefix}{vis} [{tag}<-{parent_tag}] data-text=\"{text}\" uid={uid} display={display}")
        if item.get("children"):
            print_tree(item["children"], indent + 1)


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page(viewport={"width": 1400, "height": 900})

        print(f"\n{'='*70}")
        print("  SCRAPING CONFIGURATEUR STUDIO WPC BOOSTER")
        print(f"  URL : {STUDIO_URL}")
        print(f"{'='*70}\n")

        await page.goto(STUDIO_URL, wait_until="domcontentloaded")
        await page.wait_for_selector("li.wpc-control-item", timeout=20000)
        await page.wait_for_timeout(3000)

        # Fermer popups
        removed = await fermer_popups(page)
        print(f"  Popups supprimés : {removed}")

        # ============================================================
        # 1. DUMP DE L'ARBRE WPC COMPLET (état par défaut = 60mm)
        # ============================================================
        print(f"\n{'─'*70}")
        print("  PHASE 1 : ARBRE WPC COMPLET (isolation par défaut = 60mm)")
        print(f"{'─'*70}\n")

        tree_result = await page.evaluate(JS_DUMP_ALL)
        if isinstance(tree_result, dict) and tree_result.get("error"):
            print(f"  ❌ Erreur : {tree_result['error']}")
        else:
            print(f"  Total items WPC : {tree_result.get('total_items', '?')}")
            print(f"  wpc-encoded : {tree_result.get('wpc_encoded', '')}")
            print(f"\n  Arbre :")
            print_tree(tree_result.get("tree", []))

        # ============================================================
        # 2. FOCUS SUR LE GROUPE "PLANCHER"
        # ============================================================
        print(f"\n{'─'*70}")
        print("  PHASE 2 : DÉTAIL GROUPE PLANCHER (isolation 60mm)")
        print(f"{'─'*70}\n")

        plancher_detail = await page.evaluate(JS_DUMP_PLANCHER)
        print(f"  Éléments contenant 'plancher' : {len(plancher_detail)}")
        for p_item in plancher_detail:
            print(f"\n  ── data-text=\"{p_item['text']}\" uid={p_item['uid']}")
            print(f"     visible={p_item['visible']} display={p_item['display']}")
            print(f"     parent={p_item['parentTag']} parentClasses={p_item['parentClasses']}")
            print(f"     grandParent={p_item['grandParentTag']} gpDataText={p_item['grandParentDataText']}")
            print(f"     innerItems ({len(p_item.get('innerItems', []))}) :")
            for ii in p_item.get("innerItems", []):
                print(f"       {ii['tag']} data-text=\"{ii['dataText']}\" uid={ii['dataUid']} "
                      f"visible={ii['visible']} classes={ii['classes'][:60]}")
            print(f"     innerHTML[:500] :")
            # Afficher en lignes courtes
            html = p_item.get("innerHTML", "")
            for line in html.split(">"):
                if line.strip():
                    print(f"       {line.strip()}>")

        # ============================================================
        # 3. ANALYSE STRUCTURELLE DU GROUPE PLANCHER
        # ============================================================
        print(f"\n{'─'*70}")
        print("  PHASE 3 : STRUCTURE DOM PLANCHER + TESTS SÉLECTEURS")
        print(f"{'─'*70}\n")

        dom_path = await page.evaluate(JS_DOM_PATH)
        if isinstance(dom_path, dict) and dom_path.get("error"):
            print(f"  ❌ {dom_path['error']}")
            if dom_path.get("all_texts"):
                print(f"  Tous les data-text : {dom_path['all_texts']}")
        else:
            print(f"  Plancher data-text : \"{dom_path.get('plancher_data_text')}\"")
            print(f"  Plancher uid : {dom_path.get('plancher_uid')}")
            print(f"\n  Chemin DOM (enfant → parent) :")
            for i, node in enumerate(dom_path.get("dom_path", [])):
                print(f"    {'  ' * i}{node['tag']} data-text=\"{node['dataText']}\" "
                      f"classes={node['classes'][:60]} children={node['childrenCount']}")
            print(f"\n  Tests de sélecteurs CSS :")
            for sel, count in dom_path.get("selector_tests", {}).items():
                if isinstance(count, list):
                    print(f"    {sel} : {count}")
                else:
                    print(f"    {sel} : {count} résultat(s)")
            print(f"\n  Descendants ({dom_path.get('descendants_count', 0)} total, premiers 50) :")
            for d in dom_path.get("descendants", []):
                if d.get("dataText") or d.get("textContent"):
                    vis = "👁" if d.get("visible") else "🚫"
                    print(f"    {vis} {d['tag']} data-text=\"{d.get('dataText', '')}\" "
                          f"uid={d.get('dataUid', '')} text=\"{d.get('textContent', '')[:40]}\"")

        # ============================================================
        # 4. BASCULER EN RE2020 ET RESCANNER PLANCHER
        # ============================================================
        print(f"\n{'─'*70}")
        print("  PHASE 4 : BASCULER ISOLATION RE2020 → RESCANNER PLANCHER")
        print(f"{'─'*70}\n")

        # Cliquer sur RE2020
        clicked = await page.evaluate("""
            () => {
                var allItems = document.querySelectorAll('li.wpc-control-item');
                for (var item of allItems) {
                    if (item.getAttribute('data-text') === '100 mm (RE2020)') {
                        var tw = item.querySelector('.wpc-layer-title-wrap');
                        if (tw) tw.click();
                        else item.click();
                        return {ok: true, text: item.getAttribute('data-text')};
                    }
                }
                return {error: 'RE2020 non trouvé'};
            }
        """)
        print(f"  Clic isolation RE2020 : {clicked}")
        await page.wait_for_timeout(2000)

        # Rescanner plancher avec RE2020
        plancher_re2020 = await page.evaluate(JS_DUMP_PLANCHER)
        print(f"\n  Éléments 'plancher' avec RE2020 : {len(plancher_re2020)}")
        for p_item in plancher_re2020:
            print(f"\n  ── data-text=\"{p_item['text']}\" uid={p_item['uid']}")
            print(f"     visible={p_item['visible']} display={p_item['display']}")
            print(f"     innerItems ({len(p_item.get('innerItems', []))}) :")
            for ii in p_item.get("innerItems", []):
                vis = "👁" if ii.get("visible") else "🚫"
                print(f"       {vis} {ii['tag']} data-text=\"{ii['dataText']}\" uid={ii['dataUid']}")

        dom_path_re2020 = await page.evaluate(JS_DOM_PATH)
        if isinstance(dom_path_re2020, dict) and not dom_path_re2020.get("error"):
            print(f"\n  Tests sélecteurs (RE2020) :")
            for sel, count in dom_path_re2020.get("selector_tests", {}).items():
                if isinstance(count, list):
                    print(f"    {sel} : {count}")
                else:
                    print(f"    {sel} : {count} résultat(s)")
            print(f"\n  Descendants avec data-text ou textContent :")
            for d in dom_path_re2020.get("descendants", []):
                if d.get("dataText") or d.get("textContent"):
                    vis = "👁" if d.get("visible") else "🚫"
                    print(f"    {vis} {d['tag']} data-text=\"{d.get('dataText', '')}\" "
                          f"uid={d.get('dataUid', '')} text=\"{d.get('textContent', '')[:40]}\"")

        print(f"\n{'='*70}")
        print("  SCRAPING TERMINÉ")
        print(f"{'='*70}\n")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
