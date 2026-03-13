"""
base — Classe de base pour tous les générateurs de devis Playwright.

Fournit le cycle de vie commun :
- Lancement du navigateur Chromium
- Gestion du contexte (viewport, locale, downloads)
- Fermeture des popups
- Méthodes d'ajout au panier, traitement panier, génération PDF
- Logging structuré

Les sous-classes implémentent ``_configurer_produit()`` et ``generer()``.
"""

from __future__ import annotations

import json
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from generators.logging_config import get_logger
from generators.wc_helpers import (
    DOWNLOAD_DIR,
    ajouter_au_panier_wc,
    ajouter_produits_complementaires,
    fermer_popups,
    generer_devis_via_generateur,
    generer_pdf_panier,
    match_wc_variation,
    select_wc_attribute,
    traiter_panier,
    verifier_panier,
)

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page

logger = get_logger(__name__)


@dataclass
class ClientInfo:
    """Informations client pour la génération du devis PDF.

    Attributes:
        nom: Nom de famille.
        prenom: Prénom.
        email: Adresse email.
        telephone: Numéro de téléphone.
        adresse: Adresse postale complète.
    """

    nom: str = ""
    prenom: str = ""
    email: str = ""
    telephone: str = ""
    adresse: str = ""


@dataclass
class DevisResult:
    """Résultat d'une génération de devis.

    Attributes:
        success: True si le PDF a été généré.
        filepath: Chemin absolu du fichier PDF.
        date_livraison: Date de livraison estimée (si disponible).
        elapsed_seconds: Durée de génération en secondes.
        error: Message d'erreur (si échec).
    """

    success: bool = False
    filepath: str = ""
    date_livraison: str = ""
    elapsed_seconds: float = 0.0
    error: str = ""

    def to_json(self) -> str:
        """Sérialise le résultat en JSON."""
        if self.success:
            return json.dumps({
                "success": True,
                "filepath": self.filepath,
                "filename": os.path.basename(self.filepath),
                "size_kb": round(os.path.getsize(self.filepath) / 1024, 1)
                if self.filepath and os.path.exists(self.filepath)
                else 0,
                "date_livraison": self.date_livraison,
                "elapsed_seconds": round(self.elapsed_seconds, 1),
            }, ensure_ascii=False)
        return json.dumps({
            "success": False,
            "error": self.error,
        }, ensure_ascii=False)


class BaseGenerator(ABC):
    """Classe de base abstraite pour les générateurs de devis Playwright.

    Gère le cycle de vie du navigateur et fournit les méthodes communes
    d'interaction avec les sites WooCommerce.

    Attributes:
        site_url: URL de base du site WooCommerce.
        site_name: Nom lisible du site (pour les logs).
        headless: True pour lancer Chrome sans interface graphique.
        download_dir: Répertoire de téléchargement des PDF.
    """

    site_url: str = ""
    site_name: str = ""

    def __init__(self, *, headless: bool = False, download_dir: str = DOWNLOAD_DIR):
        self.headless = headless
        self.download_dir = download_dir
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self.logger = get_logger(f"generators.{self.__class__.__name__}")

    async def _launch_browser(self, playwright: Any) -> Page:
        """Lance le navigateur et retourne une page prête à l'emploi.

        Args:
            playwright: Instance ``async_playwright``.

        Returns:
            Page Playwright configurée.
        """
        self._browser = await playwright.chromium.launch(headless=self.headless)
        self._context = await self._browser.new_context(
            viewport={"width": 1400, "height": 900},
            locale="fr-FR",
            accept_downloads=True,
        )
        self._page = await self._context.new_page()
        return self._page

    async def _close_browser(self) -> None:
        """Ferme proprement le navigateur."""
        if self._browser:
            await self._browser.close()
            self._browser = None

    def _build_filepath(
        self,
        prefix: str,
        client: ClientInfo,
        suffix: str = "",
    ) -> str:
        """Construit le chemin du fichier PDF de sortie.

        Args:
            prefix: Préfixe du nom de fichier (ex: ``"devis_pergola"``).
            client: Informations client.
            suffix: Suffixe optionnel avant l'extension.

        Returns:
            Chemin absolu du fichier PDF.
        """
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        parts = [prefix]
        if client.nom:
            parts.append(client.nom)
        if client.prenom:
            parts.append(client.prenom)
        parts.append(timestamp)
        if suffix:
            parts.append(suffix)
        filename = "_".join(parts) + ".pdf"
        return os.path.join(self.download_dir, filename)

    @abstractmethod
    async def generer(self, **kwargs: Any) -> DevisResult:
        """Génère un devis PDF. À implémenter dans chaque sous-classe.

        Returns:
            DevisResult avec le résultat de la génération.
        """
        ...
