#!/usr/bin/env python3
"""
Générateur automatique de devis — Abri Français
Utilise Playwright pour piloter un vrai navigateur Chrome comme un humain :
1. Configurer un abri sur le site
2. Ajouter au panier (avec images de configuration via compositeView)
3. Générer le devis PDF avec les coordonnées client
4. Télécharger le PDF

Le navigateur est lancé en mode visible (headless=False) pour garantir que le
compositing canvas du WPC Performance Booster génère des images identiques à
celles d'un vrai utilisateur.

Usage:
    python3 generateur_devis_auto.py

Installer Playwright:
    pip install playwright
    playwright install chromium
"""

import asyncio
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

try:
    from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
except ImportError:
    print("❌ Playwright non installé. Lancer :")
    print("   pip install playwright && playwright install chromium")
    sys.exit(1)

from utils_playwright import appliquer_code_promo as _appliquer_code_promo_utils


# ═══════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════

SITES = {
    "abri": {
        "name": "Abri Français",
        "url": "https://www.xn--abri-franais-sdb.fr",
        "configurateur": "/produit/configurateur-abri-de-jardin/",
        "panier": "/votre-panier/",
        "devis": "/generer-un-devis/",
        "has_booster": True,
    },
    "studio": {
        "name": "Studio Français",
        "url": "https://xn--studio-franais-qjb.fr",
        # Pas de configurateur unique — 1 URL par dimension (ex: /produit/44-x-347/)
        "configurateur": "/configurateur-studio-de-jardin-surface/",
        "panier": "/panier/",
        "devis": "/generateur-de-devis/",
        "has_booster": True,  # WPC Performance Booster v4.0 actif (même plugin que abri)
        # Mapping dimensions → slugs produit
        "dimensions": {
            "2,2x2,4":  "/produit/22-x-237/",
            "3,3x2,4":  "/produit/33-x-237/",
            "2,2x3,5":  "/produit/22-x-347/",
            "4,4x2,4":  "/produit/44-x-237/",
            "2,2x4,6":  "/produit/22-x-457/",
            "3,3x3,5":  "/produit/33-x-347/",
            "5,5x2,4":  "/produit/55-x-237/",
            "3,3x4,6":  "/produit/33-x-457/",
            "2,2x5,7":  "/produit/22-x-567/",
            "4,4x3,5":  "/produit/44-x-347/",
            "6,6x2,4":  "/produit/66-x-237/",
            "5,5x3,5":  "/produit/55-x-347/",
            "3,3x5,7":  "/produit/33-x-567/",
            "7,7x2,4":  "/produit/77-x-237/",
            "4,4x4,6":  "/produit/44-x-457/",
            "5,5x4,6":  "/produit/55-x-457/",
            "6,6x3,5":  "/produit/66-x-347/",
            "8,8x2,4":  "/produit/88-x-237/",
            "4,4x5,7":  "/produit/44-x-567/",
            "7,7x3,5":  "/produit/77-x-347/",
            "5,5x5,7":  "/produit/55-x-567/",
            "6,6x4,6":  "/produit/66-x-457/",
            "8,8x3,5":  "/produit/88-x-347/",
            "7,7x4,6":  "/produit/77-x-457/",
            "6,6x5,7":  "/produit/66-x-567/",
            "8,8x4,6":  "/produit/88-x-457/",
            "7,7x5,7":  "/produit/77-x-567/",
            "8,8x5,7":  "/produit/88-x-567/",
        },
    },
    # pergola, terrasse, cloture : domaines pas encore déployés
}

DOWNLOAD_DIR = os.path.expanduser("~/Downloads")


def _chercher_url_studio_wc(base_url: str, largeur: str, profondeur: str) -> str | None:
    """Cherche l'URL du produit Studio via l'API WooCommerce Store.

    Recherche parmi tous les produits du site Studio celui dont le titre
    correspond aux dimensions demandées (ex: "5,5 x 3,47" ou "55-x-347").

    Returns:
        Le path relatif du produit (ex: "/produit/55-x-347/") ou None.
    """
    import html as _html
    import re as _re

    # Normaliser les dimensions pour la recherche (ex: "5,5" → "55", "3,5" → "35")
    def _norm(dim: str) -> str:
        """Normalise une dimension : '5,5' → '55', '2,4' → '24'."""
        return dim.replace(",", "").replace(".", "").strip()

    l_norm = _norm(largeur)
    p_norm = _norm(profondeur)

    # Termes de recherche : essayer "LxP" d'abord, puis juste la largeur
    search_terms = [f"{largeur} x {profondeur}", f"{l_norm} x {p_norm}", largeur]

    for term in search_terms:
        try:
            url = f"{base_url}/wp-json/wc/store/v1/products?search={urllib.parse.quote(term)}&per_page=50"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; DevisBot/1.0)"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                products = json.loads(resp.read())
        except Exception:
            continue

        if not products:
            continue

        # Chercher le produit dont le slug ou le titre contient les bonnes dimensions
        for p in products:
            name = _re.sub(r"<[^>]+>", "", _html.unescape(p.get("name", ""))).strip().lower()
            slug = p.get("slug", "").lower()
            permalink = p.get("permalink", "")

            # Vérifier si les dimensions correspondent dans le slug ou le nom
            # Patterns à vérifier : "55-x-347", "5,5 x 3,47", "55 x 347", etc.
            patterns = [
                f"{l_norm}-x-{p_norm}",      # slug style : "55-x-347"
                f"{largeur} x {profondeur}",  # titre style : "5,5 x 3,47"
                f"{l_norm} x {p_norm}",       # "55 x 347"
            ]
            for pat in patterns:
                if pat.lower() in slug or pat.lower() in name:
                    # Extraire le path relatif depuis le permalink
                    if permalink:
                        from urllib.parse import urlparse
                        path = urlparse(permalink).path
                        if path:
                            print(f"    ✓ Produit Studio trouvé via API WC : {path}")
                            return path
            # Fallback : vérifier si le permalink contient le pattern slug
            if permalink:
                from urllib.parse import urlparse
                path = urlparse(permalink).path.lower()
                if f"{l_norm}-x-{p_norm}" in path:
                    print(f"    ✓ Produit Studio trouvé via API WC (fallback) : {path}")
                    return urlparse(permalink).path

    return None


# Largeur d'un module de mur studio (préfabriqué ossature bois).
# Chaque menuiserie occupe exactement UN module de 1,10 m.
# Les positions disponibles dans le configurateur WPC sont espacées de 1,10 m.
# Deux menuiseries ne peuvent pas partager le même module sur un mur.
MODULE_STUDIO = 1.10


@dataclass
class ConfigAbri:
    """Configuration d'un abri de jardin."""
    largeur: str          # Ex: "4,20M" — texte du data-text "Largeur 4,20M"
    profondeur: str       # Ex: "3,45m" — texte du data-text "Profondeur 3,45m"
    ouvertures: list = field(default_factory=list)
    # Chaque ouverture = {"type": "Porte double Vitrée", "face": "Face 1", "position": "Centre"}
    extension_toiture: str = ""  # "" = pas d'extension, ou "Droite 1 M", "Gauche 2 M", etc.
    plancher: bool = False
    bac_acier: bool = False  # True = Bac acier anti condensation


@dataclass
class ConfigStudio:
    """Configuration d'un studio de jardin."""
    largeur: str          # Ex: "4,4" — première partie de la clé dimensions (mètres)
    profondeur: str       # Ex: "3,5" — deuxième partie de la clé dimensions (mètres)
    menuiseries: list = field(default_factory=list)
    # Chaque menuiserie = {"type": "PORTE VITREE", "materiau": "PVC", "mur": "MUR DE FACE", "position": "gauche"}
    # Types: PORTE VITREE, FENETRE SIMPLE, FENETRE DOUBLE, BAIE VITREE, PORTE DOUBLE VITREE
    # Matériaux: PVC, ALU  (BAIE VITREE et PORTE DOUBLE VITREE = ALU uniquement)
    # Murs: MUR DE FACE, MUR DE GAUCHE, MUR DE DROITE, MUR DU FOND
    # Position (hint sémantique ou valeur exacte) :
    #   "auto" / "gauche" → premier module libre en partant de l'angle origine
    #   "droite"          → dernier module libre
    #   "centre"          → module libre le plus proche du centre du mur
    #   "1,29" etc.       → offset exact en mètres (notation française)
    # Note : chaque menuiserie occupe un module de 1,10 m — pas de chevauchement possible
    bardage_exterieur: str = "Gris"    # Gris, Brun, Noir, Vert
    isolation: str = "60mm"            # "60mm" ou "100 mm (RE2020)"
    rehausse: bool = False             # OUI/NON (hauteur 3,20m)
    bardage_interieur: str = "OSB"     # "OSB" ou "Panneaux bois massif (3 plis épicéa)"
    plancher: str = "Sans plancher"    # "Sans plancher", "Plancher standard", "Plancher RE2020", "Plancher porteur"
    finition_plancher: bool = False    # OUI/NON
    terrasse: str = ""                 # "" (pas de terrasse), "2m (11m2)", "4m (22m2)"
    pergola: str = ""                  # "" (pas de pergola), "4x2m (8m2)", "4x4m (16m2)"


@dataclass
class Client:
    """Coordonnées client pour le devis."""
    nom: str
    prenom: str
    email: str
    telephone: str
    adresse: str


# ═══════════════════════════════════════════════════════════════
# MOTEUR PRINCIPAL
# ═══════════════════════════════════════════════════════════════

class GenerateurDevis:
    """Automatise la génération de devis via Playwright (Chrome visible).

    Architecture du configurateur WPC :
    - Chaque item a un attribut data-text (ex: "Largeur 4,20M", "Profondeur 3,45m")
    - Les sub_groups s'expandent au clic sur leur title-wrap
    - Les images (feuilles) se sélectionnent au clic
    - Hiérarchie : GROUP > SUB_GROUP > SUB_GROUP > IMAGE
    - Exemple DIMENSION :
        DIMENSION (group) > Largeur 4,20M (sub_group) > Profondeur 3,45m (image)
    - Exemple OUVERTURES :
        OUVERTURES (group) > Porte double Vitrée (sub_group) > Face 1 (sub_group) > Centre (image)
    """

    def __init__(self, site: str = "abri", headless: bool = False):
        self.site_config = SITES[site]
        self.headless = headless
        self.base_url = self.site_config["url"]
        self.browser = None
        self.page = None
        self.context = None

    async def start(self):
        """Démarre le navigateur.

        En mode headed (headless=False, par défaut) : utilise le Chrome système
        pour un rendu identique à un navigateur humain. Indispensable pour que
        le compositing canvas (compositeView) génère des images valides.
        """
        self.playwright = await async_playwright().start()

        if not self.headless:
            # Mode humain : préférer le Chrome système (meilleur rendu canvas/WebGL)
            try:
                self.browser = await self.playwright.chromium.launch(
                    headless=False, channel="chrome"
                )
            except Exception:
                # Chrome non installé → Chromium bundled en mode visible
                self.browser = await self.playwright.chromium.launch(headless=False)
        else:
            self.browser = await self.playwright.chromium.launch(headless=True)

        self.context = await self.browser.new_context(
            viewport={"width": 1400, "height": 900},
            locale="fr-FR",
            accept_downloads=True,
        )
        self.page = await self.context.new_page()
        # En headless, bloquer les fonts pour gagner un peu de vitesse
        # (on ne bloque JAMAIS les images : nécessaires pour compositeView)
        if self.headless:
            await self.page.route("**/*.{woff,woff2,ttf,eot}",
                                  lambda route: route.abort())

    async def stop(self):
        """Ferme le navigateur."""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    # ─── Navigation ─────────────────────────────────────────

    async def fermer_popups(self):
        """Ferme les popups : cookies, newsletter, etc.
        Indispensable pour que le clic sur 'Ajouter au panier' fonctionne.
        Stratégie agressive : clic + JS removal pour garantir qu'aucun overlay ne bloque.
        """

        # 1. Accepter les cookies (plusieurs sélecteurs possibles)
        cookie_selectors = [
            '.cmplz-accept',
            '#cookie-law-info-bar .cli_action_button',
            '.cookie-popup .accept',
            '#moove_gdpr_cookie_info_bar .moove-gdpr-infobar-allow-all',
            'button[data-cli_action="accept"]',
            '.cli-bar-btn_container a.cli_action_button',
            '#cookie_action_close_header',
            '.cookie-notice .button',
            '#cookieChoiceDismiss',
            'a.cc-btn.cc-dismiss',
            '#onetrust-accept-btn-handler',
        ]
        for sel in cookie_selectors:
            try:
                btn = self.page.locator(sel).first
                if await btn.is_visible(timeout=500):
                    await btn.click(timeout=2000)
                    print(f"    ✓ Cookie popup fermé ({sel})")
                    await self.page.wait_for_timeout(500)
                    break
            except Exception:
                continue

        # 2. Fermer les popups newsletter / promotion (overlay, modal)
        popup_close_selectors = [
            '.popup-close',
            '.modal-close',
            '.close-popup',
            '.sg-popup-close',
            '.spu-close',
            '.elementor-popup-modal .dialog-close-button',
            '.pum-close',  # Popup Maker
            'button.pum-close',
            '.popmake-close',
            '.newsletter-dismiss',
        ]
        for sel in popup_close_selectors:
            try:
                btn = self.page.locator(sel).first
                if await btn.is_visible(timeout=300):
                    await btn.click(timeout=1000)
                    print(f"    ✓ Popup fermé ({sel})")
                    await self.page.wait_for_timeout(300)
            except Exception:
                continue

        # 3. Appuyer Escape pour fermer tout popup restant
        await self.page.keyboard.press("Escape")
        await self.page.wait_for_timeout(300)
        await self.page.keyboard.press("Escape")
        await self.page.wait_for_timeout(300)

        # 4. Suppression agressive via JS : retire tous les overlays/popups du DOM
        removed = await self.page.evaluate("""
            () => {
                var removed = [];
                // Sélecteurs de popups courants
                var selectors = [
                    '.pum-overlay', '.pum-container', '#pum-',
                    '.popup-overlay', '.modal-overlay',
                    '.sg-popup-overlay', '.sg-popup-content',
                    '.spu-overlay',
                    '.cmplz-cookiebanner',
                    '#cookie-law-info-bar',
                    '.elementor-popup-modal',
                    '[class*="cookie-banner"]',
                    '[class*="cookie-bar"]',
                    '[id*="cookie"]',
                ];
                for (var sel of selectors) {
                    var els = document.querySelectorAll(sel);
                    for (var el of els) {
                        if (el && el.parentNode) {
                            removed.push(sel + ' (' + (el.className || '').substring(0, 40) + ')');
                            el.parentNode.removeChild(el);
                        }
                    }
                }
                // Retirer les body overflow:hidden qui bloquent le scroll
                if (document.body.style.overflow === 'hidden') {
                    document.body.style.overflow = '';
                    removed.push('body overflow reset');
                }
                if (document.documentElement.style.overflow === 'hidden') {
                    document.documentElement.style.overflow = '';
                    removed.push('html overflow reset');
                }
                return removed;
            }
        """)
        if removed:
            print(f"    ✓ Popups supprimés du DOM : {len(removed)} éléments")

    async def vider_panier(self):
        """Vide le panier existant."""
        await self.page.goto(self.base_url + self.site_config["panier"],
                             wait_until="domcontentloaded")
        remove_buttons = self.page.locator("a.remove, .product-remove a")
        count = await remove_buttons.count()
        for i in range(count):
            try:
                await remove_buttons.nth(0).click()
                await self.page.wait_for_timeout(500)
            except Exception:
                pass

    # ─── Configuration de l'abri ────────────────────────────

    async def configurer_abri(self, config: ConfigAbri):
        """Configure un abri sur le configurateur."""
        print("  ➜ Ouverture du configurateur...")
        await self.page.goto(
            self.base_url + self.site_config["configurateur"],
            wait_until="domcontentloaded"
        )
        # Attendre que le configurateur charge
        await self.page.wait_for_selector("li.wpc-control-item", timeout=15000)
        await self.page.wait_for_timeout(1500)

        # Fermer les popups (cookies, newsletter, etc.)
        await self.fermer_popups()

        # --- ÉTAPE 1+2 : Sélectionner la dimension (largeur + profondeur) ---
        # IMPORTANT : Ne PAS cliquer sur le sub_group "Largeur X" car ça auto-sélectionne
        # la première profondeur. On expand le groupe via CSS, puis on clique UNIQUEMENT
        # sur la profondeur cible à l'intérieur du bon groupe.
        largeur_text = f"Largeur {config.largeur}"
        profondeur_text = f"Profondeur {config.profondeur}"
        print(f"  ➜ Sélection dimension {largeur_text} / {profondeur_text}...")
        await self._select_dimension(largeur_text, profondeur_text)
        await self.page.wait_for_timeout(1000)

        # --- ÉTAPE 3 : Ouvertures ---
        for ouverture in config.ouvertures:
            o_type = ouverture["type"]
            o_face = ouverture.get("face", "Face 1")
            o_pos = ouverture.get("position", "Centre")
            print(f"  ➜ Ajout ouverture : {o_type} sur {o_face} ({o_pos})...")
            await self._ajouter_ouverture(o_type, o_face, o_pos)

        # --- ÉTAPE 4 : Extension de toiture ---
        if config.extension_toiture:
            # Format attendu : "Droite 1 M" ou "Gauche 2 M"
            parts = config.extension_toiture.split(" ", 1)
            ext_cote = parts[0]  # "Droite" ou "Gauche"
            ext_taille = parts[1] if len(parts) > 1 else "1 M"  # "1 M", "2 M", "3,5 M"
            print(f"  ➜ Ajout extension de toiture {ext_taille} côté {ext_cote}...")
            await self._click_by_data_text("Extension de toiture")
            await self.page.wait_for_timeout(500)
            await self._click_visible_by_data_text(ext_cote, parent_text="Extension de toiture")
            await self.page.wait_for_timeout(500)
            await self._click_visible_by_data_text(ext_taille, parent_text="Extension de toiture")
            await self.page.wait_for_timeout(500)

        # --- ÉTAPE 5 : Options (Plancher, Bac Acier) ---
        if config.plancher:
            print("  ➜ Ajout plancher...")
            await self._click_by_data_text("OPTIONS")
            await self.page.wait_for_timeout(500)
            await self._click_visible_by_data_text("Plancher", parent_text="OPTIONS")
            await self.page.wait_for_timeout(300)
            await self._click_visible_by_data_text("OUI", parent_text="OPTIONS")
            await self.page.wait_for_timeout(500)

        if config.bac_acier:
            print("  ➜ Ajout bac acier anti-condensation...")
            await self._click_by_data_text("OPTIONS")
            await self.page.wait_for_timeout(500)
            await self._click_visible_by_data_text("Bac Acier", parent_text="OPTIONS")
            await self.page.wait_for_timeout(300)
            await self._click_visible_by_data_text("Bac acier anti condensation", parent_text="OPTIONS")
            await self.page.wait_for_timeout(500)

        # Vérification finale : s'assurer que tous les éléments sont bien sélectionnés
        # avant d'ajouter au panier (détecte les désélections accidentelles)
        await self._verifier_config_wpc(label="abri")

        # Récupérer le prix
        prix = await self._get_prix()
        print(f"  ✓ Configuration terminée — Prix : {prix}")
        return prix

    # ─── Configuration du studio ────────────────────────────

    async def configurer_studio(self, config: ConfigStudio):
        """Configure un studio sur le configurateur."""
        # Construire la clé de dimension pour trouver l'URL produit
        dim_key = f"{config.largeur}x{config.profondeur}"

        # 1) Chercher dynamiquement via l'API WooCommerce Store (source de vérité)
        print(f"  ➜ Recherche du produit Studio {dim_key} via API WooCommerce...")
        product_path = _chercher_url_studio_wc(
            self.base_url, config.largeur, config.profondeur
        )

        # 2) Fallback sur le mapping statique si l'API WC n'a rien trouvé
        if not product_path:
            dim_map = self.site_config.get("dimensions", {})
            product_path = dim_map.get(dim_key)
            if product_path:
                print(f"  ⚠ API WC n'a rien trouvé, fallback mapping statique : {product_path}")

        if not product_path:
            raise ValueError(
                f"Dimension studio '{dim_key}' non trouvée (ni API WC, ni mapping statique). "
                f"Vérifier que le produit existe sur {self.base_url}"
            )

        print(f"  ➜ Ouverture du configurateur studio {dim_key}...")
        await self.page.goto(
            self.base_url + product_path,
            wait_until="domcontentloaded"
        )
        await self.page.wait_for_selector("li.wpc-control-item", timeout=20000)
        await self.page.wait_for_timeout(2000)

        # Fermer les popups
        await self.fermer_popups()

        # --- Configuration via clics WPC ---
        # Helper JS pour sélectionner une option par data-text dans un groupe
        async def select_option(group_text: str, option_text: str):
            """Clique sur option_text dans le groupe group_text.

            Découvre les options disponibles dans le groupe avant de cliquer.
            Vérifie si l'option est DÉJÀ sélectionnée (via wpc-encoded) pour
            éviter de la désélectionner par un double-clic.
            Lève ValueError si le groupe ou l'option n'existe pas.
            """
            result = await self.page.evaluate("""
                (args) => {
                    function findByText(parent, text) {
                        var items = parent.querySelectorAll('li.wpc-control-item');
                        for (var item of items) {
                            if (item.getAttribute('data-text') === text) return item;
                        }
                        return null;
                    }
                    function clickItem(item) {
                        var tw = item.querySelector('.wpc-layer-title-wrap');
                        if (tw) tw.click();
                        else item.click();
                    }
                    function listChildren(parent) {
                        var items = parent.querySelectorAll(':scope > ul > li.wpc-control-item');
                        return Array.from(items).map(i => i.getAttribute('data-text')).filter(Boolean);
                    }
                    function isAlreadySelected(item) {
                        // Vérifier via wpc-encoded si le data-uid de l'item est déjà sélectionné
                        var uid = item.getAttribute('data-uid');
                        if (!uid) return false;
                        var form = document.querySelector('form.cart');
                        var enc = form ? form.querySelector('[name="wpc-encoded"]') : null;
                        if (!enc || !enc.value) return false;
                        try {
                            var selectedUids = atob(enc.value).split(',').map(function(s) { return s.trim(); });
                            return selectedUids.indexOf(uid) !== -1;
                        } catch(e) {
                            return false;
                        }
                    }
                    var allItems = document.querySelectorAll('li.wpc-control-item');
                    var group = null;
                    for (var item of allItems) {
                        if (item.getAttribute('data-text') === args.groupText) {
                            group = item;
                            break;
                        }
                    }
                    if (!group) {
                        var allGroups = Array.from(allItems).map(i => i.getAttribute('data-text')).filter(Boolean);
                        return {error: 'group_not_found', group: args.groupText, available_groups: allGroups.slice(0, 20)};
                    }
                    var option = findByText(group, args.optionText);
                    if (!option) {
                        var available = listChildren(group);
                        return {error: 'option_not_found', option: args.optionText, group: args.groupText, available_options: available};
                    }
                    // Vérifier si déjà sélectionné AVANT de cliquer
                    if (isAlreadySelected(option)) {
                        var available = listChildren(group);
                        return {ok: true, already_selected: true, available_options: available};
                    }
                    clickItem(option);
                    var available = listChildren(group);
                    return {ok: true, already_selected: false, available_options: available};
                }
            """, {"groupText": group_text, "optionText": option_text})
            if isinstance(result, dict) and result.get("error"):
                err_type = result["error"]
                if err_type == "group_not_found":
                    raise ValueError(
                        f"Groupe '{group_text}' introuvable dans le configurateur. "
                        f"Groupes disponibles : {result.get('available_groups', [])}"
                    )
                else:
                    raise ValueError(
                        f"Option '{option_text}' introuvable dans '{group_text}'. "
                        f"Options disponibles : {result.get('available_options', [])}"
                    )
            if isinstance(result, dict) and result.get("ok"):
                if result.get("already_selected"):
                    print(f"    ✓ {group_text} → {option_text} (déjà sélectionné — clic ignoré)")
                else:
                    print(f"    ✓ {group_text} → {option_text} (dispo: {result.get('available_options', [])})")
            await self.page.wait_for_timeout(300)

        # Bardage extérieur
        if config.bardage_exterieur:
            print(f"  ➜ Bardage extérieur : {config.bardage_exterieur}")
            await select_option("Bardage EXTERIEUR", config.bardage_exterieur)

        # Isolation
        if config.isolation:
            print(f"  ➜ Isolation : {config.isolation}")
            await select_option("ISOLATION", config.isolation)

        # Rehausse
        if config.rehausse:
            print("  ➜ Rehausse : OUI")
            await self._click_by_data_text("Rehausse")
            await self.page.wait_for_timeout(300)
            # Cliquer le premier OUI visible
            await self.page.evaluate("""
                () => {
                    var rehausse = null;
                    var items = document.querySelectorAll('li.wpc-control-item');
                    for (var item of items) {
                        if (item.getAttribute('data-text') === 'Rehausse') { rehausse = item; break; }
                    }
                    if (!rehausse) return;
                    var ouis = rehausse.querySelectorAll('li.wpc-control-item[data-text="OUI"]');
                    for (var o of ouis) {
                        if (!o.classList.contains('wpc-cl-hide-group')) {
                            var tw = o.querySelector('.wpc-layer-title-wrap');
                            if (tw) tw.click(); else o.click();
                            return;
                        }
                    }
                }
            """)

        # Menuiseries — positionnement intelligent par modules de 1,10 m
        # used_modules_per_wall : {mur_str: set(module_index)} — initialisé vide
        used_modules_per_wall: dict = {}
        for menu in config.menuiseries:
            m_type = menu["type"]                      # Ex: "BAIE VITREE"
            m_mat  = menu.get("materiau", "PVC")       # "PVC" ou "ALU"
            m_mur  = menu["mur"]                       # Ex: "MUR DE FACE"
            m_pos  = menu.get("position", "auto")      # Hint sémantique ou offset exact
            print(f"  ➜ Menuiserie : {m_type} {m_mat} > {m_mur} > hint={m_pos}")
            await self._ajouter_menuiserie_studio(m_type, m_mat, m_mur, m_pos, used_modules_per_wall)

        # Bardage intérieur
        if config.bardage_interieur:
            print(f"  ➜ Bardage intérieur : {config.bardage_interieur}")
            await select_option("BARDAGE INTERIEUR", config.bardage_interieur)

        # Plancher
        if config.plancher and config.plancher != "Sans plancher":
            print(f"  ➜ Plancher : {config.plancher}")
            await select_option("Plancher ", config.plancher)

        # Finition plancher
        if config.finition_plancher:
            print("  ➜ Finition plancher : OUI")
            await select_option("Finition Plancher", "OUI")

        # Terrasse
        if config.terrasse:
            print(f"  ➜ Terrasse : {config.terrasse}")
            await select_option("Terrasse", config.terrasse)

        # Pergola
        if config.pergola:
            print(f"  ➜ Pergola : {config.pergola}")
            await select_option("Pergola", config.pergola)

        # Vérification finale : s'assurer que tous les éléments sont bien sélectionnés
        await self._verifier_config_wpc(label="studio")

        # Récupérer le prix
        prix = await self._get_prix()
        print(f"  ✓ Configuration terminée — Prix : {prix}")
        return prix

    async def _ajouter_menuiserie_studio(
        self,
        type_menu: str,
        materiau: str,
        mur: str,
        position_hint: str,
        used_modules_per_wall: dict,
    ) -> str:
        """Ajoute une menuiserie studio avec positionnement intelligent anti-chevauchement.

        Chaque menuiserie occupe exactement un module de 1,10 m (MODULE_STUDIO).
        Deux menuiseries sur le même mur ne peuvent pas partager le même module.

        position_hint :
          "auto" / "gauche"  → premier module libre (depuis l'angle origine du mur)
          "droite"           → dernier module libre
          "centre"           → module libre le plus proche du centre du mur
          "1,29" etc.        → offset exact souhaité (notation française) ; prend le
                               module libre le plus proche si non disponible

        Retourne l'offset sélectionné (ex: "1,29").
        Modifie used_modules_per_wall[mur] en place.
        """
        # ── Étape 1 : Naviguer jusqu'au mur et lire toutes les positions disponibles ──
        nav = await self.page.evaluate("""
            (args) => {
                function isVisible(el) {
                    if (el.classList.contains('wpc-cl-hide-group')) return false;
                    return window.getComputedStyle(el).display !== 'none';
                }
                function clickItem(item) {
                    var tw = item.querySelector('.wpc-layer-title-wrap');
                    if (tw) tw.click(); else item.click();
                }
                function findVisibleChild(parent, text) {
                    for (var item of parent.querySelectorAll('li.wpc-control-item'))
                        if (item.getAttribute('data-text') === text && isVisible(item))
                            return item;
                    return null;
                }
                var typeItem = null;
                for (var item of document.querySelectorAll('li.wpc-control-item'))
                    if (item.getAttribute('data-text') === args.type) { typeItem = item; break; }
                if (!typeItem) return {error: 'type not found: ' + args.type};
                clickItem(typeItem);

                var matItem = findVisibleChild(typeItem, args.materiau);
                if (!matItem) return {error: 'materiau not found: ' + args.materiau + ' (BAIE VITREE et PORTE DOUBLE VITREE = ALU uniquement)'};
                clickItem(matItem);

                var murItem = findVisibleChild(matItem, args.mur);
                if (!murItem) return {error: 'mur not found: ' + args.mur};
                clickItem(murItem);

                var ul = murItem.querySelector(':scope > ul, :scope > .wpc-control-lists > ul');
                if (!ul) return {positions: []};
                var positions = [];
                for (var li of ul.querySelectorAll(':scope > li.wpc-control-item'))
                    if (isVisible(li))
                        positions.push({text: li.getAttribute('data-text') || '', uid: li.getAttribute('data-uid') || ''});
                return {positions: positions};
            }
        """, {"type": type_menu, "materiau": materiau, "mur": mur})
        await self.page.wait_for_timeout(300)

        if isinstance(nav, dict) and "error" in nav:
            raise ValueError(f"Menuiserie studio: {nav['error']}")
        available = nav.get("positions", [])
        if not available:
            raise ValueError(f"Aucune position disponible pour {type_menu} {materiau} > {mur}")

        # ── Étape 2 : Sélectionner le module libre selon le hint ──
        def parse_fr(s: str) -> float:
            return float(s.replace(",", "."))

        def module_idx(offset: float) -> int:
            return int(offset / MODULE_STUDIO)

        offsets = [(p["text"], p["uid"], parse_fr(p["text"])) for p in available]
        used_modules = used_modules_per_wall.get(mur, set())
        free = [(t, u, o) for t, u, o in offsets if module_idx(o) not in used_modules]

        hint = (position_hint or "auto").strip().lower()

        if not free:
            print(f"    ⚠ Tous les modules occupés sur {mur} pour {type_menu} — fallback premier")
            sel_text, sel_uid, sel_off = offsets[0]
        elif hint in ("auto", "gauche", "left", ""):
            sel_text, sel_uid, sel_off = free[0]
        elif hint in ("droite", "right"):
            sel_text, sel_uid, sel_off = free[-1]
        elif hint in ("centre", "center", "milieu"):
            mid = (offsets[0][2] + offsets[-1][2]) / 2
            sel_text, sel_uid, sel_off = min(free, key=lambda p: abs(p[2] - mid))
        else:
            # Position exacte demandée (ex: "1,29")
            exact = next(((t, u, o) for t, u, o in free if t == hint), None)
            if exact:
                sel_text, sel_uid, sel_off = exact
            else:
                # Chercher dans toutes les positions (même module occupé)
                all_match = next(((t, u, o) for t, u, o in offsets if t == hint), None)
                if all_match and module_idx(all_match[2]) in used_modules:
                    print(f"    ⚠ Module pour '{hint}' déjà occupé — sélection forcée")
                    sel_text, sel_uid, sel_off = all_match
                elif all_match:
                    sel_text, sel_uid, sel_off = all_match
                else:
                    # Offset inconnu → prendre le module libre le plus proche
                    try:
                        target = parse_fr(hint)
                        closest = min(free, key=lambda p: abs(p[2] - target))
                        print(f"    ⚠ Position '{hint}' inconnue → plus proche libre: {closest[0]}")
                        sel_text, sel_uid, sel_off = closest
                    except ValueError:
                        sel_text, sel_uid, sel_off = free[0]

        # ── Étape 3 : Cliquer la position sélectionnée par UID ──
        click = await self.page.evaluate("""
            (args) => {
                var posItem = args.uid ? document.querySelector('[data-uid="' + args.uid + '"]') : null;
                if (!posItem) {
                    for (var item of document.querySelectorAll('li.wpc-control-item'))
                        if (item.getAttribute('data-text') === args.text) { posItem = item; break; }
                }
                if (!posItem) return {error: 'position not found: ' + args.text};
                var tw = posItem.querySelector('.wpc-layer-title-wrap');
                if (tw) tw.click(); else posItem.click();
                return {ok: true};
            }
        """, {"uid": sel_uid, "text": sel_text})

        if isinstance(click, dict) and click.get("error"):
            raise ValueError(f"Menuiserie studio click: {click['error']}")

        used_modules_per_wall.setdefault(mur, set()).add(module_idx(sel_off))
        await self.page.wait_for_timeout(500)
        print(f"    ✓ {type_menu} {materiau} > {mur} @ {sel_text} (hint={position_hint or 'auto'})")
        return sel_text

    async def ajouter_produit_woo(
        self,
        product_url: str,
        variation_id: int,
        quantite: int,
        attribut_selects: dict = None,
    ):
        """Ajoute n'importe quel produit WooCommerce variable ou simple au panier.

        Compatible avec tous les sites du groupe (abri, pergola, terrasse, cloture).
        Utilisé pour les produits "au détail" et complémentaires.

        Le produit est identifié dynamiquement via l'API WooCommerce Store
        (voir rechercher_produits_detail dans mcp_server_devis.py).

        Args:
            product_url     : URL de la page produit WooCommerce
            variation_id    : ID de la variation WooCommerce (0 pour produit simple)
            quantite        : Nombre d'unités à ajouter
            attribut_selects: Dict {select_name: value} des attributs à sélectionner
                              Ex: {"attribute_pa_longueur": "2"} pour 2m
                              Valeur selon slug WooCommerce (ex: "2-5" pour 2.5m)
        """
        print(f"  ➜ Ajout produit détail : {product_url.split('/')[-2][:50]} | var={variation_id} | qté={quantite}")

        await self.page.goto(product_url, wait_until="domcontentloaded", timeout=30000)
        await self.page.wait_for_timeout(2000)

        # Fermer popups (version légère)
        for sel in [".cmplz-accept", ".cmplz-btn", "button:has-text('Accepter')"]:
            try:
                btn = self.page.locator(sel).first
                if await btn.is_visible(timeout=800):
                    await btn.click()
                    await self.page.wait_for_timeout(400)
                    break
            except Exception:
                pass
        await self.page.evaluate("""
            () => {
                ["#popup-modal",".cmplz-cookiebanner","#cmplz-cookiebanner-container",".pum-overlay"]
                    .forEach(s => document.querySelectorAll(s).forEach(el => el.remove()));
                document.body.style.overflow = "";
            }
        """)

        # ── Sélectionner les attributs via swatches wcboost (même approche que 3sites.py) ──
        if attribut_selects:
            for attr_name, attr_value in attribut_selects.items():
                # Essai 1 : clic swatch wcboost (structure réelle sur tous les sites du groupe)
                swatch_clicked = await self.page.evaluate(f"""
                    () => {{
                        var item = document.querySelector('li.wcboost-variation-swatches__item[data-value="{attr_value}"]');
                        if (!item || item.classList.contains('disabled') || item.classList.contains('is-invalid')) {{
                            var swatch = document.querySelector('[data-value="{attr_value}"][class*="swatches"]');
                            if (swatch) {{ swatch.click(); return 'swatch_legacy'; }}
                            return false;
                        }}
                        if (item.classList.contains('selected')) return 'already_selected';
                        item.click();
                        return 'swatch_li';
                    }}
                """)
                if swatch_clicked and swatch_clicked != 'already_selected':
                    try:
                        await self.page.wait_for_function(
                            "() => { var inp = document.querySelector('input.variation_id'); return inp && inp.value && inp.value !== '0'; }",
                            timeout=3000,
                        )
                    except Exception:
                        await self.page.wait_for_timeout(1500)
                elif not swatch_clicked:
                    # Fallback : jQuery sur le select caché
                    await self.page.evaluate("""
                        (args) => {
                            var sel = document.querySelector('select[name="' + args.name + '"]');
                            if (!sel) return;
                            if (typeof jQuery !== 'undefined') {
                                jQuery(sel).val(args.value).trigger('change');
                            } else {
                                sel.value = args.value;
                                sel.dispatchEvent(new Event('change', {bubbles: true}));
                            }
                        }
                    """, {"name": attr_name, "value": attr_value})
                    await self.page.wait_for_timeout(800)
                print(f"    ↳ {attr_name}={attr_value} → {swatch_clicked or 'jquery_fallback'}")

            # ── Autocontrôle : vérifier que tous les swatches sont bien sélectionnés ──
            for _pass in range(2):
                mismatches = await self.page.evaluate("""
                    (vals) => {
                        var missing = [];
                        for (var val of vals) {
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
                        await self.page.evaluate(f"""
                            () => {{
                                var item = document.querySelector(
                                    'li.wcboost-variation-swatches__item[data-value="{attr_value}"]'
                                );
                                if (item && !item.classList.contains('selected')) item.click();
                            }}
                        """)
                        await self.page.wait_for_timeout(800)

        # Variation_id final
        selected_var = await self.page.evaluate("""
            () => {
                var inp = document.querySelector('input.variation_id, input[name="variation_id"]');
                return inp ? inp.value : '0';
            }
        """)
        print(f"    ✓ variation_id sélectionné : {selected_var}")

        # Définir la quantité
        try:
            qty = self.page.locator('input.qty, input[name="quantity"]').first
            await qty.fill(str(quantite))
            await qty.dispatch_event("change")
            print(f"    ✓ Quantité : {quantite}")
        except Exception:
            pass

        # Fermer les popups avant clic
        await self.page.evaluate("""
            () => {
                ["#popup-modal",".cmplz-cookiebanner","#cmplz-cookiebanner-container",".pum-overlay"]
                    .forEach(s => document.querySelectorAll(s).forEach(el => el.remove()));
                document.body.style.overflow = "";
            }
        """)

        # Vérifier que le bouton n'est pas désactivé
        is_disabled = await self.page.evaluate("""
            () => {
                const b = document.querySelector('button.single_add_to_cart_button');
                return !b || b.disabled || b.classList.contains('disabled') || b.classList.contains('wc-variation-is-unavailable');
            }
        """)
        if is_disabled:
            print("    ⚠ Bouton add-to-cart désactivé — attente 3s supplémentaires...")
            await self.page.wait_for_timeout(3000)

        # Cliquer "Ajouter au panier" (.first pour éviter le strict mode si 2 boutons)
        add_btn = self.page.locator("button.single_add_to_cart_button").first
        await add_btn.scroll_into_view_if_needed()
        await self.page.wait_for_timeout(300)
        await add_btn.click()

        # Attendre confirmation
        try:
            await self.page.wait_for_selector(
                ".woocommerce-message, .added_to_cart, .woocommerce-notices-wrapper",
                timeout=8000,
            )
            print(f"    ✅ Produit ajouté au panier ({quantite}×)")
        except Exception:
            await self.page.wait_for_timeout(3000)
            print("    ✅ Produit ajouté (confirmation non détectée, on continue)")

    async def ajouter_au_panier(self):
        """Ajoute le produit configuré au panier.

        Appelle directement wpc.submitForm('cart-form', jQuery('form.cart'))
        du WPC Performance Booster, qui :
        1. Génère la vignette panier via compositeView (canvas natif)
        2. Capture toutes les vues pour le devis PDF
        3. Soumet le formulaire avec les images encodées en base64

        Note : on ne peut PAS cliquer le bouton "Ajouter au panier" car il est
        dans un header sticky souvent hors viewport. L'appel JS direct reproduit
        exactement le même flux qu'un clic humain sur le bouton.
        """
        print("  ➜ Ajout au panier...")

        # 1. Attendre que toutes les images du preview soient chargées
        await self._wait_for_preview_images()

        # 2. Capturer les messages console du Booster pour debug
        console_logs = []
        def on_console(msg):
            if any(kw in msg.text for kw in ["WPC", "Booster", "composite", "Submit"]):
                console_logs.append(msg.text)
        self.page.on("console", on_console)

        # 3. Capturer les POST pour vérifier les données envoyées
        all_posts = []
        def on_request(request):
            if request.method == "POST":
                try:
                    buf = request.post_data_buffer
                    data = buf.decode("latin-1") if buf else ""
                    info = {
                        "url": request.url[:120],
                        "len": len(data),
                        "has_config_image": "wpc-config-image" in data,
                        "has_all_views": "wpc_all_views_images" in data,
                        "has_add_to_cart": "add-to-cart" in data,
                    }
                    all_posts.append(info)
                except Exception as e:
                    all_posts.append({"url": request.url[:80], "error": str(e)})
        self.page.on("request", on_request)

        # 4. Soumettre le formulaire
        has_booster = self.site_config.get("has_booster", False)

        if has_booster:
            # Site avec WPC Performance Booster (abri + studio)
            # IMPORTANT : type='cart-form' est REQUIS, sinon le Booster
            # tombe dans la branche incorrecte ($form[0].submit() → crash)
            await self.page.evaluate("""
                () => {
                    var $form = jQuery('form.cart');
                    if (!$form.length) {
                        console.error('[WPC Script] form.cart non trouvé !');
                        return;
                    }
                    if (typeof wpc === 'undefined' || typeof wpc.submitForm !== 'function') {
                        console.error('[WPC Script] wpc.submitForm non disponible !');
                        $form[0].submit();
                        return;
                    }
                    // Certaines versions du Booster ne preinitialise pas wpc.notices
                    if (!wpc.notices) wpc.notices = {};
                    console.log('[WPC Script] Appel wpc.submitForm(cart-form, form.cart)');
                    wpc.submitForm('cart-form', $form);
                }
            """)
        else:
            # Site sans Booster → submit natif (fallback)
            await self.page.evaluate("""
                () => {
                    var form = document.querySelector('form.cart');
                    if (form) form.submit();
                    else console.error('[WPC Script] form.cart non trouvé !');
                }
            """)

        # 5. Attendre la redirection vers le panier
        #    Abri: redirige vers /votre-panier/ après compositeView
        #    Studio: redirige vers la page produit, il faut naviguer au panier
        panier_path = self.site_config.get("panier", "/panier/")
        try:
            await self.page.wait_for_url(f"**{panier_path}**", timeout=45000)
        except PlaywrightTimeout:
            try:
                await self.page.wait_for_url("**/cart/**", timeout=5000)
            except PlaywrightTimeout:
                # Studio: form.submit redirige vers la page produit, naviguer au panier
                await self.page.wait_for_timeout(3000)
                if "panier" not in self.page.url and "cart" not in self.page.url:
                    await self.page.goto(
                        self.base_url + panier_path,
                        wait_until="domcontentloaded",
                        timeout=30000
                    )
        await self.page.wait_for_timeout(1000)

        # Debug : vérifier que les images ont été envoyées
        site_posts = [p for p in all_posts if p.get("has_add_to_cart")]
        if site_posts:
            p = site_posts[-1]
            has_img = p.get("has_config_image", False)
            has_views = p.get("has_all_views", False)
            print(f"    POST: {p['len']} chars | image: {has_img} | multi-vues: {has_views}")
            if not has_img:
                print("    ⚠ Image de configuration absente du POST !")
        else:
            print("    ⚠ Aucun POST add-to-cart capturé")

        self.page.remove_listener("request", on_request)

        if console_logs:
            for cl in console_logs[-5:]:
                print(f"    [console] {cl[:120]}")
        self.page.remove_listener("console", on_console)

        print("  ✓ Produit ajouté au panier")

    async def verifier_panier(self, nb_attendu: int) -> int:
        """Vérifie que le panier contient bien nb_attendu lignes.

        Si la page courante n'est pas le panier, y navigue d'abord.
        Retourne le nombre de lignes effectivement présentes.
        Affiche un récapitulatif détaillé de chaque ligne (nom + quantité + prix).
        """
        panier_path = self.site_config.get("panier", "/panier/")
        cart_url = self.base_url + panier_path
        if panier_path.strip("/") not in self.page.url:
            await self.page.goto(cart_url, wait_until="domcontentloaded", timeout=20000)
            await self.page.wait_for_timeout(2000)

        # Récupérer le détail de chaque ligne du panier
        cart_details = await self.page.evaluate("""
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

    async def _appliquer_code_promo(self, code_promo: str):
        """Applique un code promo dans le panier WooCommerce.

        Navigue vers /panier/, puis délègue à utils_playwright.appliquer_code_promo
        (stratégie double AJAX + formulaire HTML).
        """
        if not code_promo:
            return
        panier_url = self.base_url + self.site_config.get("panier", "/panier/")
        try:
            await self.page.goto(panier_url, wait_until="load", timeout=25000)
            await self.page.wait_for_timeout(1500)
        except Exception as e:
            print(f"    ⚠ Impossible de charger le panier pour le code promo : {e}")
            return
        await _appliquer_code_promo_utils(self.page, code_promo)

    async def _scraper_date_livraison(self) -> tuple:
        """Scrape la date de livraison estimée depuis la page panier.

        Délègue à _traiter_panier() de generateur_devis_3sites.py qui contient
        la logique exhaustive de scraping (sélecteurs plugins WPC, Pi, YITH,
        patterns date français, dump diagnostic).

        Returns: (date_livraison, diag_lines) — date estimée et diagnostic si non trouvée.
        """
        try:
            from generateur_devis_3sites import _traiter_panier
            panier_path = self.site_config.get("panier", "/panier/")
            date_livraison, diag_lines = await _traiter_panier(
                page=self.page,
                site_url=self.base_url,
                code_promo="",       # déjà appliqué avant cet appel
                mode_livraison="",   # ne pas changer
                panier_path=panier_path,
            )
            return date_livraison or "", diag_lines or []
        except Exception as e:
            print(f"  ⚠ Erreur scraping date livraison : {e}")
            return "", []

    async def _wait_for_preview_images(self):
        """Attend que toutes les images du preview du configurateur soient chargées.

        Le Booster JS compositeView lit les <img> visibles via getBoundingClientRect
        et les dessine sur un canvas. Si les images ne sont pas chargées, le canvas
        sera vide → pas d'image de configuration sur le devis.
        """
        for attempt in range(10):  # Max ~5 secondes
            result = await self.page.evaluate("""
                () => {
                    var preview = document.querySelector('.active [data-preview-inner]')
                              || document.querySelector('[data-preview-inner]');
                    if (!preview) return {ready: false, reason: 'no preview element'};
                    var imgs = preview.querySelectorAll('img');
                    var total = 0, loaded = 0;
                    for (var i = 0; i < imgs.length; i++) {
                        var img = imgs[i];
                        if (img.src && !img.src.startsWith('data:') && img.offsetWidth > 0) {
                            total++;
                            if (img.complete && img.naturalWidth > 0) loaded++;
                        }
                    }
                    return {ready: total > 0 && loaded === total, total: total, loaded: loaded};
                }
            """)
            if result.get("ready"):
                print(f"    ✓ Preview : {result['loaded']}/{result['total']} images chargées")
                return
            await self.page.wait_for_timeout(500)
        print(f"    ⚠ Preview : timeout attente images ({result})")

    async def generer_devis(self, client: Client) -> str:
        """Génère le devis PDF et le télécharge. Retourne le chemin du fichier.

        Utilise _generer_devis_via_generateur (generateur_devis_3sites.py) —
        la même fonction que pour pergola, terrasse et clôture.
        Le chemin de la page de devis est configurable via site_config["devis"].
        """
        from generateur_devis_3sites import _generer_devis_via_generateur

        Path(DOWNLOAD_DIR).mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"devis_{client.nom}_{client.prenom}_{timestamp}.pdf"
        filepath = os.path.join(DOWNLOAD_DIR, filename)

        devis_path = self.site_config["devis"]  # ex: "/generer-un-devis/" ou "/generateur-de-devis/"

        return await _generer_devis_via_generateur(
            page=self.page,
            site_url=self.base_url,
            client_nom=client.nom,
            client_prenom=client.prenom,
            client_email=client.email,
            client_telephone=client.telephone,
            client_adresse=client.adresse,
            filepath=filepath,
            devis_path=devis_path,
        )

    # ─── Méthodes internes (sélecteurs data-text) ───────────

    async def _select_dimension(self, largeur_text: str, profondeur_text: str):
        """Sélectionne une dimension via les vrais clics WPC.

        Stratégie :
        1. Cliquer sur le sub_group "Largeur X" (vrai clic WPC → expand + auto-sélectionne 1ère profondeur)
        2. Vérifier si la profondeur souhaitée est déjà auto-sélectionnée via wpc-encoded
        3. Si déjà sélectionnée → NE PAS cliquer (un clic sur un item déjà sélectionné le DÉSÉLECTIONNE)
        4. Si une autre profondeur est sélectionnée → cliquer sur la bonne

        Règle critique : toujours vérifier l'état courant avant de cliquer pour éviter la désélection.
        """
        # Étape 1 : Cliquer sur la largeur (vrai clic WPC, expand + active le preview)
        await self._click_by_data_text(largeur_text)
        await self.page.wait_for_timeout(800)

        # Étape 2 : Vérifier si la profondeur cible est déjà auto-sélectionnée par WPC
        # Lorsqu'on clique sur une largeur, WPC auto-sélectionne la 1ère profondeur disponible.
        # Si la profondeur voulue EST cette 1ère profondeur → recliquer la désélectionnerait !
        target_already_selected = await self.page.evaluate(f"""
            () => {{
                // Lire les UIDs actuellement encodés dans wpc-encoded
                const form = document.querySelector('form.cart');
                const enc = form ? form.querySelector('[name="wpc-encoded"]') : null;
                if (!enc || !enc.value) return false;
                const selectedUids = new Set(atob(enc.value).split(',').map(s => s.trim()).filter(Boolean));

                // Trouver l'UID de la profondeur cible dans le sous-groupe de la largeur
                const largeurItem = document.querySelector('li.wpc-control-item[data-text="{largeur_text}"]');
                if (!largeurItem) return false;
                const profItems = largeurItem.querySelectorAll('li.wpc-control-item[data-text="{profondeur_text}"]');
                for (const item of profItems) {{
                    const uid = item.getAttribute('data-uid') || item.getAttribute('data-id') || '';
                    if (uid && selectedUids.has(uid)) {{
                        return true;  // Déjà sélectionnée via auto-sélection WPC
                    }}
                }}
                return false;
            }}
        """)

        if target_already_selected:
            print(f"  ✓ Profondeur '{profondeur_text}' déjà auto-sélectionnée par WPC — clic ignoré (évite désélection)")
        else:
            # Étape 3 : La profondeur cible n'est pas encore sélectionnée → cliquer
            clicked = await self.page.evaluate(f"""
                () => {{
                    const largeur = document.querySelector('li.wpc-control-item[data-text="{largeur_text}"]');
                    if (!largeur) return false;
                    const profItems = largeur.querySelectorAll('li.wpc-control-item[data-text="{profondeur_text}"]');
                    for (const item of profItems) {{
                        const titleWrap = item.querySelector('.wpc-layer-title-wrap');
                        if (titleWrap) titleWrap.click();
                        else item.click();
                        return true;
                    }}
                    return false;
                }}
            """)
            if not clicked:
                raise ValueError(f"Profondeur '{profondeur_text}' non trouvée dans '{largeur_text}'")
            await self.page.wait_for_timeout(800)

        # Vérification finale : s'assurer que la profondeur est bien sélectionnée
        check = await self.page.evaluate(f"""
            () => {{
                const form = document.querySelector('form.cart');
                const enc = form ? form.querySelector('[name="wpc-encoded"]') : null;
                if (!enc || !enc.value) return {{ok: false, uidCount: 0, decoded: ''}};
                const decoded = atob(enc.value);
                const uids = decoded.split(',').filter(Boolean);

                // Vérifier que l'UID de la profondeur cible est présent
                const largeurItem = document.querySelector('li.wpc-control-item[data-text="{largeur_text}"]');
                let profUidFound = false;
                if (largeurItem) {{
                    const profItems = largeurItem.querySelectorAll('li.wpc-control-item[data-text="{profondeur_text}"]');
                    const selectedSet = new Set(uids.map(s => s.trim()));
                    for (const item of profItems) {{
                        const uid = item.getAttribute('data-uid') || item.getAttribute('data-id') || '';
                        if (uid && selectedSet.has(uid)) {{ profUidFound = true; break; }}
                    }}
                }}
                return {{ok: true, uidCount: uids.length, decoded: decoded.substring(0, 80), profUidFound}};
            }}
        """)
        if check.get("ok"):
            prof_ok = check.get("profUidFound", False)
            status = "✓" if prof_ok else "⚠"
            print(f"  {status} Dimension sélectionnée ({check.get('uidCount')} UIDs) — profondeur dans encoded: {prof_ok}")
            if not prof_ok:
                print(f"    ⚠ ATTENTION : '{profondeur_text}' non trouvée dans wpc-encoded — la config risque d'être incomplète")

    async def _verifier_config_wpc(self, label: str = ""):
        """Vérifie et affiche tous les éléments sélectionnés dans le configurateur WPC.

        Double approche :
        1. Lit wpc-encoded pour compter les UIDs validés → mesure fiable de la config
        2. Scanne les li.wpc-control-item avec classe active/selected → textes lisibles

        Retourne True si au moins 1 UID est sélectionné, False sinon.
        À appeler avant ajouter_au_panier() pour valider que la config est complète.
        """
        result = await self.page.evaluate("""
            () => {
                // ── Approche 1 : lire wpc-encoded ──
                const form = document.querySelector('form.cart');
                const enc = form ? form.querySelector('[name="wpc-encoded"]') : null;
                if (!enc || !enc.value) return {uids: [], items: [], error: 'wpc-encoded introuvable'};

                const encodedUids = atob(enc.value).split(',').map(s => s.trim()).filter(Boolean);
                const selectedUidSet = new Set(encodedUids);

                // ── Approche 2 : scanner les items visuellement sélectionnés ──
                // WPC marque les items actifs avec data-uid correspondant au wpc-encoded
                const selectedItems = [];
                for (const item of document.querySelectorAll('li.wpc-control-item')) {
                    const uid = item.getAttribute('data-uid') || '';
                    if (uid && selectedUidSet.has(uid)) {
                        selectedItems.push({
                            text: item.getAttribute('data-text') || uid,
                            uid: uid
                        });
                    }
                }

                return {
                    uids: encodedUids,
                    items: selectedItems,
                    itemsFound: selectedItems.length
                };
            }
        """)

        prefix = f"[{label}] " if label else ""
        uids = result.get("uids", [])
        items = result.get("items", [])
        error = result.get("error", "")

        if error:
            print(f"  ⚠ {prefix}Vérification WPC : {error}")
            return False

        if not uids:
            print(f"  ⚠ {prefix}AUCUN élément sélectionné dans wpc-encoded ! La config est vide.")
            return False

        print(f"  ✅ {prefix}Configuration WPC — {len(uids)} UIDs encodés / {len(items)} items identifiés :")
        if items:
            for item in items:
                print(f"     • {item['text']}")
        else:
            # Les UIDs existent mais ne correspondent pas aux data-uid des li → afficher les UIDs bruts
            for uid in uids:
                print(f"     • uid={uid[:12]}...")
        return True

    async def _click_by_data_text(self, text: str):
        """Clique sur un élément du configurateur via son attribut data-text."""
        selector = f'li.wpc-control-item[data-text="{text}"]'
        el = self.page.locator(selector).first
        try:
            await el.scroll_into_view_if_needed(timeout=3000)
            await el.click(timeout=5000)
        except PlaywrightTimeout:
            # Fallback: chercher avec un match partiel via JS
            clicked = await self.page.evaluate(f"""
                () => {{
                    const items = document.querySelectorAll('li.wpc-control-item');
                    for (const item of items) {{
                        const dt = item.getAttribute('data-text') || '';
                        if (dt.toLowerCase().includes('{text.lower()}')) {{
                            const titleWrap = item.querySelector('.wpc-layer-title-wrap');
                            if (titleWrap) titleWrap.click();
                            else item.click();
                            return true;
                        }}
                    }}
                    return false;
                }}
            """)
            if not clicked:
                raise ValueError(f"Élément avec data-text '{text}' non trouvé")
        await self.page.wait_for_timeout(300)

    async def _ajouter_ouverture(self, type_ouverture: str, face: str, position: str = "Centre"):
        """Ajoute une ouverture sur une face à une position donnée.

        Hiérarchie du configurateur OUVERTURES (via .wpc-control-lists > ul > li) :
          OUVERTURES (group)
            └─ Porte double Vitrée (type, depth 1)
                └─ Face 1 (face, depth 2) — × N (un par largeur, un seul visible)
                │   └─ Gauche / Centre / Droite (position, depth 3)
                └─ Droite (face, depth 2) — mur droit
                │   └─ Gauche / Centre / Droite (position, depth 3)
                └─ Gauche (face, depth 2) — mur gauche
                │   └─ Gauche / Centre / Droite (position, depth 3)
                └─ Fond 1 (face, depth 2) — mur du fond
                    └─ Gauche / Centre / Droite (position, depth 3)

        Faces disponibles : Face 1, Face 2, Droite, Gauche, Fond 1, Fond 2
        Positions disponibles : Gauche, Centre, Droite (selon dimension)

        Chaque face existe en N exemplaires (un par largeur). Le WPC masque
        ceux qui ne correspondent pas à la dimension via wpc-cl-hide-group.
        On cherche la face VISIBLE + contenant la position demandée.

        IMPORTANT : La recherche de position est scopée à la face sélectionnée
        pour éviter de cliquer une position d'une autre face.
        """
        # 1. Cliquer sur le type d'ouverture pour l'expandre
        await self._click_by_data_text(type_ouverture)
        await self.page.wait_for_timeout(800)

        # 2. Trouver et cliquer la face VISIBLE, puis la position DANS cette face
        await self._click_ouverture_face_and_position(type_ouverture, face, position)

    async def _click_ouverture_face_and_position(self, type_ouverture: str, face: str, position: str):
        """Trouve la bonne face visible sous le type d'ouverture et clique face + position.

        IMPORTANT: La position est recherchée uniquement DANS la face sélectionnée
        (via data-uid), pas dans tout le type. Cela évite de sélectionner une
        position d'une autre face qui porte le même nom (ex: "Centre" sous Face 1
        au lieu de "Centre" sous Droite).
        """
        result = await self.page.evaluate("""
            (args) => {
                var typeText = args.typeText;
                var faceText = args.faceText;
                var posText = args.posText;

                function isWpcVisible(el) {
                    if (el.classList.contains('wpc-cl-hide-group')) return false;
                    var display = window.getComputedStyle(el).display;
                    return display !== 'none';
                }

                // 1. Trouver le type d'ouverture
                var typeItem = document.querySelector('li.wpc-control-item[data-text="' + typeText + '"]');
                if (!typeItem) return {error: 'type not found: ' + typeText};

                // 2. Trouver toutes les faces avec ce nom sous ce type
                var faces = typeItem.querySelectorAll('li.wpc-control-item[data-text="' + faceText + '"]');
                var bestFace = null;

                // Priorité 1 : face visible + contient la position demandée
                for (var f = 0; f < faces.length; f++) {
                    if (!isWpcVisible(faces[f])) continue;
                    var posItems = faces[f].querySelectorAll('li.wpc-control-item[data-text="' + posText + '"]');
                    for (var p = 0; p < posItems.length; p++) {
                        if (isWpcVisible(posItems[p])) {
                            bestFace = faces[f];
                            break;
                        }
                    }
                    if (bestFace) break;
                }

                // Priorité 2 : face visible (même sans la position exacte visible)
                if (!bestFace) {
                    for (var f = 0; f < faces.length; f++) {
                        if (isWpcVisible(faces[f])) {
                            bestFace = faces[f];
                            break;
                        }
                    }
                }

                if (!bestFace) return {error: 'face not found: ' + faceText + ' under ' + typeText};

                // 3. Cliquer sur la face pour l'expandre
                var tw = bestFace.querySelector('.wpc-layer-title-wrap');
                if (tw) tw.click();
                else bestFace.click();

                var faceUid = bestFace.getAttribute('data-uid');

                // 4. Cliquer la position DANS cette face (scopé au bestFace)
                var posItems = bestFace.querySelectorAll('li.wpc-control-item[data-text="' + posText + '"]');
                var clickedPos = null;
                for (var p = 0; p < posItems.length; p++) {
                    if (isWpcVisible(posItems[p])) {
                        var ptw = posItems[p].querySelector('.wpc-layer-title-wrap');
                        if (ptw) ptw.click();
                        else posItems[p].click();
                        clickedPos = posItems[p].getAttribute('data-uid');
                        break;
                    }
                }

                // Fallback position : premier item visible dans la face
                if (!clickedPos) {
                    var allPos = bestFace.querySelectorAll('li.wpc-control-item');
                    for (var a = 0; a < allPos.length; a++) {
                        if (isWpcVisible(allPos[a]) && allPos[a].getAttribute('data-text')) {
                            var atw = allPos[a].querySelector('.wpc-layer-title-wrap');
                            if (atw) atw.click();
                            else allPos[a].click();
                            clickedPos = allPos[a].getAttribute('data-uid');
                            break;
                        }
                    }
                }

                if (!clickedPos) return {error: 'position not found: ' + posText + ' in face ' + faceText, faceUid: faceUid};

                return {
                    clicked: true,
                    faceUid: faceUid,
                    posUid: clickedPos,
                    faceText: bestFace.getAttribute('data-text'),
                    debug: 'face+pos clicked in single pass'
                };
            }
        """, {"typeText": type_ouverture, "faceText": face, "posText": position})

        if isinstance(result, dict) and result.get("error"):
            raise ValueError(f"Ouverture: {result['error']}")

        await self.page.wait_for_timeout(500)
        face_text = result.get("faceText", face) if isinstance(result, dict) else face
        print(f"    ✓ Ouverture: {type_ouverture} > {face_text} > {position}")

    async def _click_visible_by_data_text(self, text: str, parent_text: str = ""):
        """Clique sur le premier élément VISIBLE avec ce data-text.
        Utilisé pour extension de toiture et options (pas pour les ouvertures)."""
        clicked = await self.page.evaluate("""
            (args) => {
                var targetText = args.targetText;
                var parentText = args.parentText;
                var searchRoot = document;
                if (parentText) {
                    var parents = document.querySelectorAll('li.wpc-control-item[data-text="' + parentText + '"]');
                    for (var i = 0; i < parents.length; i++) {
                        if (parents[i].offsetParent !== null || parents[i].offsetHeight > 0) {
                            searchRoot = parents[i];
                            break;
                        }
                    }
                }

                var items = searchRoot.querySelectorAll('li.wpc-control-item[data-text="' + targetText + '"]');
                for (var i = 0; i < items.length; i++) {
                    if (items[i].offsetHeight > 0 || items[i].offsetParent !== null) {
                        var tw = items[i].querySelector('.wpc-layer-title-wrap');
                        if (tw) tw.click();
                        else items[i].click();
                        return true;
                    }
                }

                // Fallback: cliquer le premier trouvé
                if (items.length > 0) {
                    var tw = items[0].querySelector('.wpc-layer-title-wrap');
                    if (tw) tw.click();
                    else items[0].click();
                    return true;
                }
                return false;
            }
        """, {"targetText": text, "parentText": parent_text})
        if not clicked:
            raise ValueError(f"Élément visible data-text='{text}' non trouvé (parent: {parent_text})")

    async def _click_first_visible_image_in_group(self, group_text: str):
        """Clique sur le premier item IMAGE visible dans un groupe."""
        await self.page.evaluate(f"""
            () => {{
                const group = document.querySelector('li.wpc-control-item[data-text="{group_text}"]');
                if (!group) return false;
                const images = group.querySelectorAll('li.wpc-control-item:not(.wpc-layer-type-group):not(.wpc-layer-type-sub_group)');
                for (const img of images) {{
                    if (img.offsetHeight > 0) {{
                        img.click();
                        return true;
                    }}
                }}
                return false;
            }}
        """)

    async def _get_prix(self) -> str:
        """Récupère le prix total affiché."""
        price = await self.page.evaluate("""
            () => {
                // Chercher le prix WPC
                const selectors = [
                    '.wpc-product-price .amount',
                    '.wpc-total-price',
                    'p.price .amount',
                    '.summary .price .amount',
                    '[class*="price"] .amount'
                ];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el && el.textContent.trim()) return el.textContent.trim();
                }
                return 'Prix non trouvé';
            }
        """)
        return price


# ═══════════════════════════════════════════════════════════════
# FONCTION PRINCIPALE
# ═══════════════════════════════════════════════════════════════

async def generer_devis_abri(
    largeur: str,
    profondeur: str,
    ouvertures: list,
    client_nom: str,
    client_prenom: str,
    client_email: str,
    client_telephone: str,
    client_adresse: str,
    headless: bool = False,
    extension_toiture: str = "",
    plancher: bool = False,
    bac_acier: bool = False,
    produits_complementaires: list = None,
    code_promo: str = "",
    produits_uniquement: bool = False,
    configurations_supplementaires: list = None,
) -> str:
    """
    Fonction principale — génère un devis abri complet.

    Paramètres :
        largeur: "4,20M", "3,45M", "5,50M", etc. (texte après "Largeur ")
        profondeur: "3,45m", "2,15m", etc. (texte après "Profondeur ", minuscule m)
        ouvertures: [{"type": "Porte double Vitrée", "face": "Face 1", "position": "Centre"}]
        extension_toiture: "" (pas d'extension) ou "Droite 1 M", "Gauche 2 M", etc.
        client_*: coordonnées du client
        headless: True = invisible, False = voir le navigateur (debug)
        produits_complementaires: [{
            "url": "https://...",       # URL de la page produit
            "variation_id": 53609,      # ID de variation WooCommerce (0 si simple)
            "quantite": 16,             # Quantité
            "attribut_selects": {       # Sélecteurs d'attributs (optionnel)
                "attribute_pa_longueur": "2"
            },
            "description": "Planches 27×130mm 2m"  # Pour le log
        }]
        produits_uniquement: True = sauter le configurateur, ajouter UNIQUEMENT
            les produits_complementaires au panier. Utile pour les modèles préconçus
            (Gamme Essentiel, Haut de Gamme) qui ne passent pas par le configurateur WPC.
            Les paramètres largeur/profondeur/ouvertures sont ignorés dans ce mode.
        configurations_supplementaires: liste de configurations supplémentaires à ajouter
            au même panier. Chaque élément est un dict avec les mêmes clés que la config
            principale : {"largeur": "4,70M", "profondeur": "3,45m",
            "ouvertures": [...], "extension_toiture": "", "plancher": False, "bac_acier": False}
            Permet de mettre plusieurs abris personnalisés sur le même devis PDF.

    Retourne : chemin vers le fichier PDF du devis

    Note : headless=False (navigateur visible) est recommandé pour que le
    compositing canvas génère des images de configuration valides.
    """
    start_time = time.time()
    produits_complementaires = produits_complementaires or []
    configurations_supplementaires = configurations_supplementaires or []
    print(f"\n{'='*60}")
    print("  GÉNÉRATION DE DEVIS AUTOMATIQUE")
    print(f"  Client : {client_prenom} {client_nom}")
    if produits_uniquement:
        print("  Mode : produits_uniquement (sans configurateur)")
        print(f"  {len(produits_complementaires)} produit(s) à ajouter")
    else:
        print(f"  Abri : Largeur {largeur} / Profondeur {profondeur}")
        if configurations_supplementaires:
            print(f"  + {len(configurations_supplementaires)} configuration(s) supplémentaire(s)")
        if produits_complementaires:
            print(f"  + {len(produits_complementaires)} produit(s) complémentaire(s)")
    print(f"{'='*60}\n")

    gen = GenerateurDevis(site="abri", headless=headless)

    try:
        await gen.start()

        nb_items_panier = 0

        # --- Mode produits_uniquement : sauter le configurateur ---
        if not produits_uniquement:
            config = ConfigAbri(
                largeur=largeur,
                profondeur=profondeur,
                ouvertures=ouvertures,
                extension_toiture=extension_toiture,
                plancher=plancher,
                bac_acier=bac_acier,
            )
            await gen.configurer_abri(config)

            await gen.ajouter_au_panier()
            nb_items_panier += 1
            await gen.verifier_panier(nb_attendu=nb_items_panier)

            # --- Configurations supplémentaires (multi-abri sur même devis) ---
            for idx, cfg_sup in enumerate(configurations_supplementaires):
                print(f"\n  ─── Configuration supplémentaire {idx + 1}/{len(configurations_supplementaires)} ───")
                sup_config = ConfigAbri(
                    largeur=cfg_sup.get("largeur", ""),
                    profondeur=cfg_sup.get("profondeur", ""),
                    ouvertures=cfg_sup.get("ouvertures", []),
                    extension_toiture=cfg_sup.get("extension_toiture", ""),
                    plancher=cfg_sup.get("plancher", False),
                    bac_acier=cfg_sup.get("bac_acier", False),
                )
                await gen.configurer_abri(sup_config)
                await gen.ajouter_au_panier()
                nb_items_panier += 1
                await gen.verifier_panier(nb_attendu=nb_items_panier)

        # Ajouter les produits complémentaires au même panier
        if produits_complementaires:
            label = "Produits" if produits_uniquement else "Produits complémentaires"
            print(f"\n  ─── {label} ({len(produits_complementaires)}) ───")
            confirmed_count = nb_items_panier  # Tenir compte des items configurateur déjà au panier
            for idx, prod in enumerate(produits_complementaires):
                desc = prod.get("description", prod.get("url", "?").split("/produit/")[-1].strip("/"))
                print(f"\n  [{idx + 1}/{len(produits_complementaires)}] {desc}")
                confirmed = False
                for attempt in range(2):
                    try:
                        await gen.ajouter_produit_woo(
                            product_url=prod["url"],
                            variation_id=prod.get("variation_id", 0),
                            quantite=prod.get("quantite", 1),
                            attribut_selects=prod.get("attribut_selects"),
                        )
                        nb = await gen.verifier_panier(nb_attendu=confirmed_count + 1)
                        if nb >= confirmed_count + 1:
                            confirmed = True
                            break
                        if attempt == 0:
                            print("    ↺ Absent du panier — nouvelle tentative...")
                    except Exception as e:
                        print(f"    ⚠ Tentative {attempt + 1}/2 échouée : {e}")
                if confirmed:
                    confirmed_count += 1
                else:
                    print(f"    ⚠ {desc} potentiellement absent après 2 tentatives")

        # Appliquer le code promo dans le panier (si fourni)
        await gen._appliquer_code_promo(code_promo)

        # Scraper la date de livraison estimée depuis le panier
        date_livraison, diag_lines = await gen._scraper_date_livraison()

        client = Client(
            nom=client_nom,
            prenom=client_prenom,
            email=client_email,
            telephone=client_telephone,
            adresse=client_adresse,
        )
        filepath = await gen.generer_devis(client)

        elapsed = time.time() - start_time
        print(f"\n{'='*60}")
        print(f"  ✅ DEVIS GÉNÉRÉ EN {elapsed:.1f} SECONDES")
        print(f"  📄 Fichier : {filepath}")
        if date_livraison:
            print(f"  📅 Livraison estimée : {date_livraison}")
        print(f"{'='*60}\n")

        return filepath, date_livraison, diag_lines

    except Exception as e:
        print(f"\n  ❌ Erreur : {e}")
        raise
    finally:
        await gen.stop()


async def generer_devis_studio(
    largeur: str,
    profondeur: str,
    menuiseries: list,
    client_nom: str,
    client_prenom: str,
    client_email: str,
    client_telephone: str,
    client_adresse: str,
    headless: bool = False,
    bardage_exterieur: str = "Gris",
    isolation: str = "60mm",
    rehausse: bool = False,
    bardage_interieur: str = "OSB",
    plancher: str = "Sans plancher",
    finition_plancher: bool = False,
    terrasse: str = "",
    pergola: str = "",
    produits_complementaires: list = None,
    code_promo: str = "",
    configurations_supplementaires: list = None,
) -> str:
    """
    Fonction principale — génère un devis studio complet.

    Paramètres :
        largeur: "4,4", "5,5", "6,6", etc. (mètres, sans unité)
        profondeur: "3,5", "4,6", "5,7", etc.
        menuiseries: [{"type": "PORTE VITREE", "materiau": "PVC", "mur": "MUR DE FACE", "position": "1,1"}]
            Types: PORTE VITREE, FENETRE SIMPLE, FENETRE DOUBLE, BAIE VITREE, PORTE DOUBLE VITREE
            Matériaux: PVC, ALU
            Murs: MUR DE FACE, MUR DE GAUCHE, MUR DE DROITE, MUR DU FOND
            Positions: valeurs numériques (offset en mètres)
        bardage_exterieur: "Gris", "Brun", "Noir", "Vert"
        isolation: "60mm" ou "100 mm (RE2020)"
        plancher: "Sans plancher", "Plancher standard", "Plancher RE2020", "Plancher porteur"
        terrasse: "" (aucune), "2m (11m2)", "4m (22m2)"
        pergola: "" (aucune), "4x2m (8m2)", "4x4m (16m2)"
        client_*: coordonnées du client
        produits_complementaires: [{
            "url": "https://...",       # URL de la page produit
            "variation_id": 53609,      # ID de variation WooCommerce (0 si simple)
            "quantite": 16,             # Quantité
            "attribut_selects": {       # Sélecteurs d'attributs (optionnel)
                "attribute_pa_longueur": "2"
            },
            "description": "Cloison 60€/ml"  # Pour le log
        }]
        configurations_supplementaires: liste de configurations supplémentaires à ajouter
            au même panier. Chaque élément est un dict avec les clés de ConfigStudio :
            {"largeur": "3,3", "profondeur": "3,5", "menuiseries": [...],
            "bardage_exterieur": "Gris", "isolation": "60mm", ...}
            Permet de mettre plusieurs studios personnalisés sur le même devis PDF.

    Retourne : chemin vers le fichier PDF du devis
    """
    start_time = time.time()
    produits_complementaires = produits_complementaires or []
    configurations_supplementaires = configurations_supplementaires or []
    dim_key = f"{largeur}x{profondeur}"
    print(f"\n{'='*60}")
    print("  GÉNÉRATION DE DEVIS STUDIO")
    print(f"  Client : {client_prenom} {client_nom}")
    print(f"  Studio : {dim_key}")
    if configurations_supplementaires:
        print(f"  + {len(configurations_supplementaires)} configuration(s) supplémentaire(s)")
    if produits_complementaires:
        print(f"  + {len(produits_complementaires)} produit(s) complémentaire(s)")
    print(f"{'='*60}\n")

    gen = GenerateurDevis(site="studio", headless=headless)

    try:
        await gen.start()

        nb_items_panier = 0

        config = ConfigStudio(
            largeur=largeur,
            profondeur=profondeur,
            menuiseries=menuiseries,
            bardage_exterieur=bardage_exterieur,
            isolation=isolation,
            rehausse=rehausse,
            bardage_interieur=bardage_interieur,
            plancher=plancher,
            finition_plancher=finition_plancher,
            terrasse=terrasse,
            pergola=pergola,
        )
        await gen.configurer_studio(config)

        await gen.ajouter_au_panier()
        nb_items_panier += 1
        await gen.verifier_panier(nb_attendu=nb_items_panier)

        # --- Configurations supplémentaires (multi-studio sur même devis) ---
        for idx, cfg_sup in enumerate(configurations_supplementaires):
            print(f"\n  ─── Configuration supplémentaire {idx + 1}/{len(configurations_supplementaires)} ───")
            sup_config = ConfigStudio(
                largeur=cfg_sup.get("largeur", ""),
                profondeur=cfg_sup.get("profondeur", ""),
                menuiseries=cfg_sup.get("menuiseries", []),
                bardage_exterieur=cfg_sup.get("bardage_exterieur", "Gris"),
                isolation=cfg_sup.get("isolation", "60mm"),
                rehausse=cfg_sup.get("rehausse", False),
                bardage_interieur=cfg_sup.get("bardage_interieur", "OSB"),
                plancher=cfg_sup.get("plancher", "Sans plancher"),
                finition_plancher=cfg_sup.get("finition_plancher", False),
                terrasse=cfg_sup.get("terrasse", ""),
                pergola=cfg_sup.get("pergola", ""),
            )
            await gen.configurer_studio(sup_config)
            await gen.ajouter_au_panier()
            nb_items_panier += 1
            await gen.verifier_panier(nb_attendu=nb_items_panier)

        # Ajouter les produits complémentaires au même panier
        if produits_complementaires:
            print(f"\n  ─── Produits complémentaires ({len(produits_complementaires)}) ───")
            confirmed_count = nb_items_panier  # Tenir compte des items configurateur déjà au panier
            for idx, prod in enumerate(produits_complementaires):
                desc = prod.get("description", prod.get("url", "?").split("/produit/")[-1].strip("/"))
                print(f"\n  [{idx + 1}/{len(produits_complementaires)}] {desc}")
                confirmed = False
                for attempt in range(2):
                    try:
                        await gen.ajouter_produit_woo(
                            product_url=prod["url"],
                            variation_id=prod.get("variation_id", 0),
                            quantite=prod.get("quantite", 1),
                            attribut_selects=prod.get("attribut_selects"),
                        )
                        nb = await gen.verifier_panier(nb_attendu=confirmed_count + 1)
                        if nb >= confirmed_count + 1:
                            confirmed = True
                            break
                        if attempt == 0:
                            print("    ↺ Absent du panier — nouvelle tentative...")
                    except Exception as e:
                        print(f"    ⚠ Tentative {attempt + 1}/2 échouée : {e}")
                if confirmed:
                    confirmed_count += 1
                else:
                    print(f"    ⚠ {desc} potentiellement absent après 2 tentatives")

        # Appliquer le code promo dans le panier (si fourni)
        await gen._appliquer_code_promo(code_promo)

        # Scraper la date de livraison estimée depuis le panier
        date_livraison, diag_lines = await gen._scraper_date_livraison()

        client = Client(
            nom=client_nom,
            prenom=client_prenom,
            email=client_email,
            telephone=client_telephone,
            adresse=client_adresse,
        )
        filepath = await gen.generer_devis(client)

        elapsed = time.time() - start_time
        print(f"\n{'='*60}")
        print(f"  ✅ DEVIS STUDIO GÉNÉRÉ EN {elapsed:.1f} SECONDES")
        print(f"  📄 Fichier : {filepath}")
        if date_livraison:
            print(f"  📅 Livraison estimée : {date_livraison}")
        print(f"{'='*60}\n")

        return filepath, date_livraison, diag_lines

    except Exception as e:
        print(f"\n  ❌ Erreur : {e}")
        raise
    finally:
        await gen.stop()


# ═══════════════════════════════════════════════════════════════
# EXEMPLES D'UTILISATION
# ═══════════════════════════════════════════════════════════════

async def exemple_devis_simple():
    """Exemple : abri 4,35M x 4,35m avec options complètes."""
    return await generer_devis_abri(
        largeur="4,35M",
        profondeur="4,35m",
        ouvertures=[
            {"type": "Porte double Vitrée", "face": "Face 1", "position": "Gauche"},
            {"type": "Fenêtre Horizontale", "face": "Droite", "position": "Centre"},
        ],
        extension_toiture="Droite 1 M",
        bac_acier=True,
        client_nom="Dupont",
        client_prenom="Jean",
        client_email="jean.dupont@example.com",
        client_telephone="06 12 34 56 78",
        client_adresse="15 rue de la Paix, 75002 Paris",
        headless=False,  # Navigateur visible = rendu canvas identique à un humain
    )


# ═══════════════════════════════════════════════════════════════
# POINT D'ENTRÉE
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    asyncio.run(exemple_devis_simple())
