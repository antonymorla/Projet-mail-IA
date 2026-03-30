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
from dataclasses import dataclass, field
from pathlib import Path

try:
    from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
except ImportError:
    print("❌ Playwright non installé. Lancer :")
    print("   pip install playwright && playwright install chromium")
    sys.exit(1)

from utils_playwright import appliquer_code_promo as _appliquer_code_promo_utils
from generateur_devis_3sites import _traiter_panier


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

# Largeur d'un module de mur studio (préfabriqué ossature bois).
# Les positions disponibles dans le configurateur WPC sont espacées de 1,10 m.
# Deux menuiseries ne peuvent pas partager le même module sur un mur.
# Point 0 (origine) = angle mur de face / mur de gauche ET angle mur de droite / mur du fond.
MODULE_STUDIO = 1.10

# Menuiseries qui occupent 2 modules consécutifs (2 × 1,10 m = 2,20 m).
# Les autres menuiseries (PORTE VITREE, FENETRE SIMPLE) occupent 1 seul module.
DOUBLE_MODULE_TYPES = {"BAIE VITREE", "FENETRE DOUBLE", "PORTE DOUBLE VITREE"}


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
        print(f"  ➜ Ouverture du configurateur...")
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
            print(f"  ➜ Ajout plancher...")
            await self._click_by_data_text("OPTIONS")
            await self.page.wait_for_timeout(500)
            await self._click_visible_by_data_text("Plancher", parent_text="OPTIONS")
            await self.page.wait_for_timeout(300)
            await self._click_visible_by_data_text("OUI", parent_text="OPTIONS")
            await self.page.wait_for_timeout(500)

        if config.bac_acier:
            print(f"  ➜ Ajout bac acier anti-condensation...")
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
        dim_map = self.site_config.get("dimensions", {})
        product_path = dim_map.get(dim_key)
        if not product_path:
            raise ValueError(
                f"Dimension studio '{dim_key}' non trouvée. "
                f"Disponibles: {', '.join(sorted(dim_map.keys()))}"
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

        # --- Configuration via clics WPC (méthode universelle _wpc_select) ---

        # Bardage extérieur
        if config.bardage_exterieur:
            print(f"  ➜ Bardage extérieur : {config.bardage_exterieur}")
            await self._wpc_select("Bardage EXTERIEUR", config.bardage_exterieur)

        # Isolation
        if config.isolation:
            print(f"  ➜ Isolation : {config.isolation}")
            await self._wpc_select("ISOLATION", config.isolation)

        # Rehausse (disponible uniquement avec RE2020)
        if config.rehausse:
            print(f"  ➜ Rehausse : OUI")
            await self._wpc_select("Rehausse", "OUI")

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
            await self._wpc_select("BARDAGE INTERIEUR", config.bardage_interieur)

        # Plancher
        if config.plancher and config.plancher != "Sans plancher":
            print(f"  ➜ Plancher : {config.plancher}")
            await self._wpc_select("Plancher ", config.plancher)

        # Finition plancher
        if config.finition_plancher:
            print(f"  ➜ Finition plancher : OUI")
            await self._wpc_select("Finition Plancher", "OUI")

        # Terrasse (groupe WPC = "Terrasse bois" ou "Terrasse")
        if config.terrasse:
            print(f"  ➜ Terrasse : {config.terrasse}")
            try:
                await self._wpc_select("Terrasse bois", config.terrasse)
            except ValueError:
                await self._wpc_select("Terrasse", config.terrasse)

        # Pergola (groupe WPC = "PERGOLA" ou "Pergola")
        if config.pergola:
            print(f"  ➜ Pergola : {config.pergola}")
            try:
                await self._wpc_select("PERGOLA", config.pergola)
            except ValueError:
                await self._wpc_select("Pergola", config.pergola)

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

        Chaque menuiserie occupe 1 ou 2 modules de 1,10 m (MODULE_STUDIO) :
        - BAIE VITREE, FENETRE DOUBLE, PORTE DOUBLE VITREE → 2 modules (2,20 m)
        - PORTE VITREE, FENETRE SIMPLE → 1 module (1,10 m)

        Point 0 (origine) = angle mur de face / mur de gauche ET angle mur de droite / mur du fond.
        Les offsets dans le configurateur sont des multiples de 1,10 m depuis le point 0.

        position_hint :
          "auto" / "gauche"  → premier module(s) libre(s) (depuis l'angle origine du mur)
          "droite"           → dernier module(s) libre(s)
          "centre"           → module(s) libre(s) le(s) plus proche(s) du centre du mur
          "1,29" etc.        → offset exact souhaité (notation française) ; prend le
                               module libre le plus proche si non disponible

        Retourne l'offset sélectionné (ex: "1,29").
        Modifie used_modules_per_wall[mur] en place.
        """
        # ── Étape 1 : Ouvrir visuellement chaque niveau (type → matériau → mur) ──
        # Scroll + clic Playwright hiérarchique pour que l'utilisateur voie les blocs s'ouvrir
        # On utilise JS pour trouver le bon élément dans la hiérarchie (éviter les doublons data-text)
        # puis Playwright scrollIntoView + click sur le title-wrap
        nav = await self.page.evaluate("""
            (args) => {
                function isVisible(el) {
                    if (el.classList.contains('wpc-cl-hide-group')) return false;
                    return window.getComputedStyle(el).display !== 'none';
                }
                function findVisibleChild(parent, text) {
                    for (var item of parent.querySelectorAll('li.wpc-control-item'))
                        if (item.getAttribute('data-text') === text && isVisible(item))
                            return item;
                    return null;
                }
                // Trouver type (racine)
                var typeItem = null;
                for (var item of document.querySelectorAll('li.wpc-control-item'))
                    if (item.getAttribute('data-text') === args.type) { typeItem = item; break; }
                if (!typeItem) return {error: 'type not found: ' + args.type};
                // Trouver matériau dans type
                var matItem = findVisibleChild(typeItem, args.materiau);
                if (!matItem) return {error: 'materiau not found: ' + args.materiau + ' (BAIE VITREE et PORTE DOUBLE VITREE = ALU uniquement)'};
                // Trouver mur dans matériau
                var murItem = findVisibleChild(matItem, args.mur);
                if (!murItem) return {error: 'mur not found: ' + args.mur};
                // Retourner les UIDs pour scroll + clic Playwright
                return {
                    typeUid: typeItem.getAttribute('data-uid') || '',
                    matUid: matItem.getAttribute('data-uid') || '',
                    murUid: murItem.getAttribute('data-uid') || '',
                };
            }
        """, {"type": type_menu, "materiau": materiau, "mur": mur})

        if isinstance(nav, dict) and "error" in nav:
            raise ValueError(f"Menuiserie studio: {nav['error']}")

        # Scroll + clic Playwright sur chaque niveau pour ouvrir visuellement
        for uid in [nav["typeUid"], nav["matUid"], nav["murUid"]]:
            if not uid:
                continue
            selector = f'li.wpc-control-item[data-uid="{uid}"]'
            try:
                el = self.page.locator(selector).first
                await el.scroll_into_view_if_needed(timeout=3000)
                tw = self.page.locator(f'{selector} > .wpc-layer-title-wrap')
                if await tw.count() > 0:
                    await tw.first.click(timeout=3000)
                else:
                    await el.click(timeout=3000)
                await self.page.wait_for_timeout(400)
            except PlaywrightTimeout:
                # Fallback JS — cliquer directement
                await self.page.evaluate("""
                    (uid) => {
                        var el = document.querySelector('[data-uid="' + uid + '"]');
                        if (el) { var tw = el.querySelector('.wpc-layer-title-wrap'); if (tw) tw.click(); else el.click(); }
                    }
                """, uid)
                await self.page.wait_for_timeout(400)

        # Lire les positions disponibles sous le mur sélectionné
        nav = await self.page.evaluate("""
            (args) => {
                function isVisible(el) {
                    if (el.classList.contains('wpc-cl-hide-group')) return false;
                    return window.getComputedStyle(el).display !== 'none';
                }
                var murItem = args.murUid
                    ? document.querySelector('[data-uid="' + args.murUid + '"]')
                    : null;
                if (!murItem) return {error: 'mur not found by uid'};

                var ul = murItem.querySelector(':scope > ul, :scope > .wpc-control-lists > ul');
                if (!ul) return {positions: []};
                var positions = [];
                for (var li of ul.querySelectorAll(':scope > li.wpc-control-item'))
                    if (isVisible(li))
                        positions.push({text: li.getAttribute('data-text') || '', uid: li.getAttribute('data-uid') || ''});
                return {positions: positions};
            }
        """, {"murUid": nav["murUid"]})
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
            return int(round(offset / MODULE_STUDIO))

        # Nombre de modules occupés par cette menuiserie (1 ou 2)
        is_double = type_menu.upper() in DOUBLE_MODULE_TYPES
        nb_modules = 2 if is_double else 1

        offsets = [(p["text"], p["uid"], parse_fr(p["text"])) for p in available]
        used_modules = used_modules_per_wall.get(mur, set())

        def is_free(offset: float) -> bool:
            """Vérifie que les nb_modules consécutifs sont libres."""
            idx = module_idx(offset)
            return all((idx + k) not in used_modules for k in range(nb_modules))

        free = [(t, u, o) for t, u, o in offsets if is_free(o)]

        hint = (position_hint or "auto").strip().lower()

        if not free:
            print(f"    ⚠ Pas assez de modules consécutifs libres sur {mur} pour {type_menu} ({nb_modules} modules) — fallback premier")
            sel_text, sel_uid, sel_off = offsets[0]
        elif hint in ("auto", "gauche", "left", ""):
            sel_text, sel_uid, sel_off = free[0]
        elif hint in ("droite", "right"):
            sel_text, sel_uid, sel_off = free[-1]
        elif hint in ("centre", "center", "milieu"):
            mid = (offsets[0][2] + offsets[-1][2]) / 2
            sel_text, sel_uid, sel_off = min(free, key=lambda p: abs(p[2] - mid))
        else:
            # Position exacte demandée (ex: "1,29" ou "3,3")
            exact = next(((t, u, o) for t, u, o in free if t == hint), None)
            if exact:
                sel_text, sel_uid, sel_off = exact
            else:
                # Chercher dans toutes les positions (même module occupé)
                all_match = next(((t, u, o) for t, u, o in offsets if t == hint), None)
                if all_match and not is_free(all_match[2]):
                    print(f"    ⚠ Module(s) pour '{hint}' déjà occupé(s) — sélection forcée")
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

        # Enregistrer les modules occupés (1 ou 2 selon le type de menuiserie)
        idx = module_idx(sel_off)
        for k in range(nb_modules):
            used_modules_per_wall.setdefault(mur, set()).add(idx + k)
        await self.page.wait_for_timeout(500)
        modules_str = f"modules {idx}-{idx+1}" if is_double else f"module {idx}"
        print(f"    ✓ {type_menu} {materiau} > {mur} @ {sel_text} ({modules_str}, hint={position_hint or 'auto'})")
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
            print(f"    ✅ Produit ajouté (confirmation non détectée, on continue)")

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
        print(f"  ➜ Ajout au panier...")

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
                print(f"    ⚠ Image de configuration absente du POST !")
        else:
            print(f"    ⚠ Aucun POST add-to-cart capturé")

        self.page.remove_listener("request", on_request)

        if console_logs:
            for cl in console_logs[-5:]:
                print(f"    [console] {cl[:120]}")
        self.page.remove_listener("console", on_console)

        print(f"  ✓ Produit ajouté au panier")

    async def verifier_panier(self, nb_attendu: int) -> int:
        """Vérifie que le panier contient bien nb_attendu lignes.

        Si la page courante n'est pas le panier, y navigue d'abord.
        Retourne le nombre de lignes effectivement présentes.
        """
        panier_path = self.site_config.get("panier", "/panier/")
        cart_url = self.base_url + panier_path
        if panier_path.strip("/") not in self.page.url:
            await self.page.goto(cart_url, wait_until="domcontentloaded", timeout=20000)
            await self.page.wait_for_timeout(2000)

        nb_items = await self.page.evaluate("""
            () => {
                const rows = document.querySelectorAll(
                    '.woocommerce-cart-form__cart-item, tr.cart_item'
                );
                return rows.length;
            }
        """)
        if nb_items >= nb_attendu:
            print(f"    ✓ Panier OK : {nb_items} ligne(s) présente(s)")
        else:
            print(f"    ⚠ Panier : {nb_items} ligne(s) au lieu de {nb_attendu} attendue(s)")
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

    async def _wpc_select(self, group_text: str, option_text: str):
        """Méthode universelle pour sélectionner une option WPC dans un groupe.

        Fonctionne pour TOUS les configurateurs (Abri + Studio) :
        1. Vérifie d'abord si l'option est déjà sélectionnée (skip si oui)
        2. Scrolle vers le groupe et l'ouvre visuellement (Playwright click = trusted + scroll)
        3. Clique l'option enfant via JS item.click()
        4. Gère les items dupliqués (wpc-cl-hide-group), les toggles, les accordions

        Args:
            group_text: data-text du groupe parent (ex: "Plancher ", "ISOLATION")
            option_text: data-text de l'option à sélectionner (ex: "Plancher standard", "60mm")
        """
        # Étape 1 : Vérifier si l'option est déjà sélectionnée AVANT d'ouvrir le groupe
        already = await self.page.evaluate("""
            (args) => {
                var allItems = document.querySelectorAll('li.wpc-control-item');
                var group = null;
                for (var item of allItems) {
                    if (item.getAttribute('data-text') === args.groupText) { group = item; break; }
                }
                if (!group) return false;
                var descendants = group.querySelectorAll('li.wpc-control-item');
                for (var d of descendants) {
                    if (d.getAttribute('data-text') === args.optionText && d.classList.contains('current')) {
                        // Vérifier que c'est le bouton visible (pas un homonyme caché)
                        var isHidden = d.classList.contains('wpc-cl-hide-group')
                                    || d.classList.contains('wpc-cl-hide-layer')
                                    || window.getComputedStyle(d).display === 'none';
                        if (!isHidden) return true;
                    }
                }
                return false;
            }
        """, {"groupText": group_text, "optionText": option_text})

        if already:
            print(f"    ✓ {option_text} (déjà sélectionné)")
            return

        # Étape 2 : Ouvrir le groupe visuellement (scroll + clic Playwright sur le title-wrap)
        group_selector = f'li.wpc-control-item[data-text="{group_text}"]'
        try:
            group_el = self.page.locator(group_selector).first
            await group_el.scroll_into_view_if_needed(timeout=3000)
            # Cliquer le title-wrap pour ouvrir l'accordion
            tw_selector = f'{group_selector} > .wpc-layer-title-wrap'
            tw = self.page.locator(tw_selector)
            if await tw.count() > 0:
                await tw.first.click(timeout=3000)
            else:
                await group_el.click(timeout=3000)
        except PlaywrightTimeout:
            print(f"    ⚠ Groupe '{group_text}' non trouvé via Playwright — fallback JS")
        await self.page.wait_for_timeout(500)

        # Étape 3 : Trouver l'option visible dans le groupe → retourner son data-uid pour clic Playwright
        result = await self.page.evaluate("""
            (args) => {
                var allItems = document.querySelectorAll('li.wpc-control-item');
                var group = null;
                for (var item of allItems) {
                    if (item.getAttribute('data-text') === args.groupText) { group = item; break; }
                }
                if (!group) return {error: 'group not found: ' + args.groupText};

                var option = null;
                var descendants = group.querySelectorAll('li.wpc-control-item');
                for (var d of descendants) {
                    if (d.getAttribute('data-text') === args.optionText) {
                        // Vérifier les 2 classes de masquage WPC + le display CSS
                        var isHidden = d.classList.contains('wpc-cl-hide-group')
                                    || d.classList.contains('wpc-cl-hide-layer')
                                    || window.getComputedStyle(d).display === 'none';
                        if (!isHidden) { option = d; break; }
                        if (!option) option = d;
                    }
                }
                if (!option) {
                    var available = [];
                    for (var d of descendants) {
                        var dt = d.getAttribute('data-text');
                        var dHidden = d.classList.contains('wpc-cl-hide-group')
                                   || d.classList.contains('wpc-cl-hide-layer')
                                   || window.getComputedStyle(d).display === 'none';
                        if (dt && !dHidden) available.push(dt);
                    }
                    return {error: 'option not found: ' + args.optionText + ' in ' + args.groupText,
                            available: available.slice(0, 10)};
                }

                if (option.classList.contains('current')) return {ok: true, already: true};
                // Retourner l'uid pour clic Playwright (visible à l'écran)
                return {ok: true, already: false, uid: option.getAttribute('data-uid') || ''};
            }
        """, {"groupText": group_text, "optionText": option_text})

        if isinstance(result, dict) and result.get("error"):
            avail = result.get("available", [])
            raise ValueError(f"{result['error']}" + (f" — disponibles: {avail}" if avail else ""))

        if result.get("already"):
            print(f"    ✓ {option_text} (déjà sélectionné)")
        else:
            # Clic Playwright visible : scroll + clic trusted (l'utilisateur voit la sélection)
            uid = result.get("uid", "")
            if uid:
                opt_selector = f'li.wpc-control-item[data-uid="{uid}"]'
            else:
                opt_selector = f'li.wpc-control-item[data-text="{option_text}"]'
            try:
                opt_el = self.page.locator(opt_selector).first
                await opt_el.scroll_into_view_if_needed(timeout=3000)
                tw = self.page.locator(f'{opt_selector} > .wpc-layer-title-wrap')
                if await tw.count() > 0:
                    await tw.first.click(timeout=3000)
                else:
                    await opt_el.click(timeout=3000)
            except PlaywrightTimeout:
                # Fallback JS si Playwright ne trouve pas l'élément
                await self.page.evaluate("""
                    (optText) => {
                        var items = document.querySelectorAll('li.wpc-control-item');
                        for (var item of items) {
                            if (item.getAttribute('data-text') === optText) { item.click(); return; }
                        }
                    }
                """, option_text)
            await self.page.wait_for_timeout(800)
            print(f"    ✓ {option_text}")

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
        # 0. Ouvrir visuellement le groupe parent "OUVERTURES" (scroll + clic)
        await self._click_by_data_text("OUVERTURES")
        await self.page.wait_for_timeout(500)

        # 1. Cliquer sur le type d'ouverture pour l'expandre (scroll visible)
        await self._click_by_data_text(type_ouverture)
        await self.page.wait_for_timeout(800)

        # 2. Trouver et cliquer la face VISIBLE, puis la position DANS cette face
        await self._click_ouverture_face_and_position(type_ouverture, face, position)

    async def _click_ouverture_face_and_position(self, type_ouverture: str, face: str, position: str):
        """Trouve la bonne face visible sous le type d'ouverture et clique face + position.

        Utilise JS pour trouver les UIDs, puis Playwright pour les clics visibles (scroll + clic trusted).
        La position est recherchée uniquement DANS la face sélectionnée (via data-uid).
        """
        # Étape 1 : Trouver les UIDs de la face et de la position via JS
        result = await self.page.evaluate("""
            (args) => {
                var typeText = args.typeText;
                var faceText = args.faceText;
                var posText = args.posText;

                function isWpcVisible(el) {
                    if (el.classList.contains('wpc-cl-hide-group')) return false;
                    return window.getComputedStyle(el).display !== 'none';
                }

                var typeItem = document.querySelector('li.wpc-control-item[data-text="' + typeText + '"]');
                if (!typeItem) return {error: 'type not found: ' + typeText};

                var faces = typeItem.querySelectorAll('li.wpc-control-item[data-text="' + faceText + '"]');
                var bestFace = null;

                for (var f = 0; f < faces.length; f++) {
                    if (!isWpcVisible(faces[f])) continue;
                    var posItems = faces[f].querySelectorAll('li.wpc-control-item[data-text="' + posText + '"]');
                    for (var p = 0; p < posItems.length; p++) {
                        if (isWpcVisible(posItems[p])) { bestFace = faces[f]; break; }
                    }
                    if (bestFace) break;
                }
                if (!bestFace) {
                    for (var f = 0; f < faces.length; f++) {
                        if (isWpcVisible(faces[f])) { bestFace = faces[f]; break; }
                    }
                }
                if (!bestFace) return {error: 'face not found: ' + faceText + ' under ' + typeText};

                var faceUid = bestFace.getAttribute('data-uid') || '';

                // Trouver la position visible dans cette face
                var posUid = '';
                var posItems = bestFace.querySelectorAll('li.wpc-control-item[data-text="' + posText + '"]');
                for (var p = 0; p < posItems.length; p++) {
                    if (isWpcVisible(posItems[p])) { posUid = posItems[p].getAttribute('data-uid') || ''; break; }
                }
                // Fallback : premier item visible
                if (!posUid) {
                    var allPos = bestFace.querySelectorAll('li.wpc-control-item');
                    for (var a = 0; a < allPos.length; a++) {
                        if (isWpcVisible(allPos[a]) && allPos[a].getAttribute('data-text')) {
                            posUid = allPos[a].getAttribute('data-uid') || '';
                            break;
                        }
                    }
                }
                if (!posUid) return {error: 'position not found: ' + posText + ' in face ' + faceText};

                return {faceUid: faceUid, posUid: posUid, faceText: bestFace.getAttribute('data-text')};
            }
        """, {"typeText": type_ouverture, "faceText": face, "posText": position})

        if isinstance(result, dict) and result.get("error"):
            raise ValueError(f"Ouverture: {result['error']}")

        face_text = result.get("faceText", face)

        # Étape 2 : Clic Playwright sur la face (scroll visible + ouvre l'accordion)
        face_uid = result.get("faceUid", "")
        if face_uid:
            face_sel = f'li.wpc-control-item[data-uid="{face_uid}"]'
            try:
                face_el = self.page.locator(face_sel).first
                await face_el.scroll_into_view_if_needed(timeout=3000)
                tw = self.page.locator(f'{face_sel} > .wpc-layer-title-wrap')
                if await tw.count() > 0:
                    await tw.first.click(timeout=3000)
                else:
                    await face_el.click(timeout=3000)
                await self.page.wait_for_timeout(400)
            except PlaywrightTimeout:
                await self.page.evaluate("""(uid) => {
                    var el = document.querySelector('li.wpc-control-item[data-uid="' + uid + '"]');
                    if (el) { var tw = el.querySelector('.wpc-layer-title-wrap'); if (tw) tw.click(); else el.click(); }
                }""", face_uid)

        # Étape 3 : Clic Playwright sur la position (scroll visible)
        pos_uid = result.get("posUid", "")
        if pos_uid:
            pos_sel = f'li.wpc-control-item[data-uid="{pos_uid}"]'
            try:
                pos_el = self.page.locator(pos_sel).first
                await pos_el.scroll_into_view_if_needed(timeout=3000)
                tw = self.page.locator(f'{pos_sel} > .wpc-layer-title-wrap')
                if await tw.count() > 0:
                    await tw.first.click(timeout=3000)
                else:
                    await pos_el.click(timeout=3000)
            except PlaywrightTimeout:
                await self.page.evaluate("""(uid) => {
                    var el = document.querySelector('li.wpc-control-item[data-uid="' + uid + '"]');
                    if (el) { var tw = el.querySelector('.wpc-layer-title-wrap'); if (tw) tw.click(); else el.click(); }
                }""", pos_uid)

        await self.page.wait_for_timeout(500)
        print(f"    ✓ Ouverture: {type_ouverture} > {face_text} > {position}")

    async def _click_visible_by_data_text(self, text: str, parent_text: str = ""):
        """Clique sur le premier élément VISIBLE avec ce data-text.
        Utilisé pour extension de toiture, bac acier, etc.
        Utilise JS pour trouver l'uid, puis Playwright pour le clic visible."""
        uid = await self.page.evaluate("""
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
                        return items[i].getAttribute('data-uid') || '';
                    }
                }
                // Fallback: premier trouvé
                if (items.length > 0) return items[0].getAttribute('data-uid') || '';
                return null;
            }
        """, {"targetText": text, "parentText": parent_text})
        if uid is None:
            raise ValueError(f"Élément visible data-text='{text}' non trouvé (parent: {parent_text})")

        # Clic Playwright visible (scroll + clic trusted)
        if uid:
            selector = f'li.wpc-control-item[data-uid="{uid}"]'
        else:
            selector = f'li.wpc-control-item[data-text="{text}"]'
        try:
            el = self.page.locator(selector).first
            await el.scroll_into_view_if_needed(timeout=3000)
            tw = self.page.locator(f'{selector} > .wpc-layer-title-wrap')
            if await tw.count() > 0:
                await tw.first.click(timeout=3000)
            else:
                await el.click(timeout=3000)
        except PlaywrightTimeout:
            # Fallback JS
            await self.page.evaluate("""(uid) => {
                var el = document.querySelector('li.wpc-control-item[data-uid="' + uid + '"]');
                if (el) { var tw = el.querySelector('.wpc-layer-title-wrap'); if (tw) tw.click(); else el.click(); }
            }""", uid)

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
    print(f"  GÉNÉRATION DE DEVIS AUTOMATIQUE")
    print(f"  Client : {client_prenom} {client_nom}")
    if produits_uniquement:
        print(f"  Mode : produits_uniquement (sans configurateur)")
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
            prix = await gen.configurer_abri(config)

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
                prix_sup = await gen.configurer_abri(sup_config)
                await gen.ajouter_au_panier()
                nb_items_panier += 1
                await gen.verifier_panier(nb_attendu=nb_items_panier)

        # Ajouter les produits complémentaires au même panier
        if produits_complementaires:
            label = "Produits" if produits_uniquement else "Produits complémentaires"
            print(f"\n  ─── {label} ({len(produits_complementaires)}) ───")
            confirmed_count = nb_items_panier  # Tenir compte des items configurateur déjà au panier
            for prod in produits_complementaires:
                desc = prod.get("description", prod.get("url", "?").split("/produit/")[-1].strip("/"))
                print(f"\n  [{confirmed_count - nb_items_panier + 1}/{len(produits_complementaires)}] {desc}")
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
                            print(f"    ↺ Absent du panier — nouvelle tentative...")
                    except Exception as e:
                        print(f"    ⚠ Tentative {attempt + 1}/2 échouée : {e}")
                if confirmed:
                    confirmed_count += 1
                else:
                    print(f"    ⚠ {desc} potentiellement absent après 2 tentatives")

        # Panier : code promo + date de livraison estimée
        panier_path = gen.site_config.get("panier", "/panier/")
        date_livraison = await _traiter_panier(
            gen.page, gen.base_url, code_promo, mode_livraison="",
            panier_path=panier_path,
        )

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
            print(f"  📦 Livraison estimée : {date_livraison}")
        print(f"{'='*60}\n")

        return filepath, date_livraison or ""

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
    print(f"  GÉNÉRATION DE DEVIS STUDIO")
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
        prix = await gen.configurer_studio(config)

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
            prix_sup = await gen.configurer_studio(sup_config)
            await gen.ajouter_au_panier()
            nb_items_panier += 1
            await gen.verifier_panier(nb_attendu=nb_items_panier)

        # Ajouter les produits complémentaires au même panier
        if produits_complementaires:
            print(f"\n  ─── Produits complémentaires ({len(produits_complementaires)}) ───")
            confirmed_count = nb_items_panier  # Tenir compte des items configurateur déjà au panier
            for prod in produits_complementaires:
                desc = prod.get("description", prod.get("url", "?").split("/produit/")[-1].strip("/"))
                print(f"\n  [{confirmed_count - nb_items_panier + 1}/{len(produits_complementaires)}] {desc}")
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
                            print(f"    ↺ Absent du panier — nouvelle tentative...")
                    except Exception as e:
                        print(f"    ⚠ Tentative {attempt + 1}/2 échouée : {e}")
                if confirmed:
                    confirmed_count += 1
                else:
                    print(f"    ⚠ {desc} potentiellement absent après 2 tentatives")

        # Panier : code promo + date de livraison estimée
        panier_path = gen.site_config.get("panier", "/panier/")
        date_livraison = await _traiter_panier(
            gen.page, gen.base_url, code_promo, mode_livraison="",
            panier_path=panier_path,
        )

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
            print(f"  📦 Livraison estimée : {date_livraison}")
        print(f"{'='*60}\n")

        return filepath, date_livraison or ""

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
