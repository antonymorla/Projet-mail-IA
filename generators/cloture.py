"""
cloture — Générateur de devis pour les clôtures bois (cloturebois.fr).

Deux modèles WooCommerce variable :
- Classique (productId=18393) : bardage 27x130, hauteur 1.9m
- Moderne (productId=17434) : multiples bardages, 3 hauteurs, recto-verso

Usage :
    gen = ClotureGenerator()
    result = await gen.generer(modele="classique", longeur="10", ...)
"""

from __future__ import annotations

import time
from typing import Any

from generators.base import BaseGenerator, ClientInfo, DevisResult
from generators.logging_config import get_logger

logger = get_logger(__name__)


class ClotureGenerator(BaseGenerator):
    """Génère des devis clôture bois sur cloturebois.fr.

    Gère les kits Classique et Moderne avec toutes leurs variantes
    (bardage, hauteur, fixation, sens, recto-verso).

    Attributes:
        site_url: ``https://cloturebois.fr``
        site_name: ``Clôture Bois``
    """

    site_url = "https://cloturebois.fr"
    site_name = "Clôture Bois"

    async def generer(self, **kwargs: Any) -> DevisResult:
        """Génère un devis clôture via Playwright.

        Keyword Args:
            modele: ``"classique"`` | ``"moderne"``.
            longeur: ``"4"`` | ``"10"`` | ``"20"`` | ``"30"`` | ``"40"`` (mètres).
            hauteur: ``"0-9"`` | ``"1-9"`` | ``"2-3"``.
            bardage: Code bardage WC.
            fixation_sol: ``"plots-beton"`` | ``"pieds-galvanises-en-h"``.
            type_poteaux: ``"90x90-h"`` | ``"metal7016"`` (classique).
            longueur_lames: ``"2-m"`` (classique).
            sens_bardage: ``"horizontal"`` | ``"vertical"`` (moderne).
            recto_verso: ``"non"`` | ``"oui"`` (moderne).
            client_*: Coordonnées client.
            code_promo: Code promo.
            mode_livraison: Mode de livraison.
            produits_complementaires: JSON array de produits supplémentaires.
            headless: Mode sans interface.

        Returns:
            DevisResult avec chemin PDF et date de livraison.
        """
        from generateur_devis_3sites import generer_devis_cloture

        start = time.time()
        modele = kwargs.get("modele", "classique")
        self.logger.info(
            "Démarrage devis clôture %s %sm | h=%s | bardage=%s",
            modele, kwargs.get("longeur"), kwargs.get("hauteur"), kwargs.get("bardage"),
        )

        try:
            filepath, date_livraison = await generer_devis_cloture(**kwargs)
            elapsed = time.time() - start
            self.logger.info("Devis clôture généré en %.1fs : %s", elapsed, filepath)
            return DevisResult(
                success=True,
                filepath=filepath,
                date_livraison=date_livraison or "",
                elapsed_seconds=elapsed,
            )
        except Exception as e:
            elapsed = time.time() - start
            self.logger.error("Échec devis clôture : %s", e, exc_info=True)
            return DevisResult(success=False, error=str(e), elapsed_seconds=elapsed)
