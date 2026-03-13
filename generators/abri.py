"""
abri — Générateur de devis pour les abris de jardin (abri-francais.fr).

Utilise le configurateur WPC Performance Booster pour configurer l'abri,
ajouter au panier avec les images de configuration, puis générer le PDF.

Usage :
    gen = AbriGenerator()
    result = await gen.generer(largeur="5,50M", profondeur="4,35m", ...)
"""

from __future__ import annotations

import time
from typing import Any

from generators.base import BaseGenerator, ClientInfo, DevisResult
from generators.logging_config import get_logger

logger = get_logger(__name__)


class AbriGenerator(BaseGenerator):
    """Génère des devis abri de jardin sur abri-francais.fr.

    Utilise le WPC Performance Booster (compositeView.canvas) pour la
    configuration visuelle et la capture d'images.

    Attributes:
        site_url: ``https://www.xn--abri-franais-sdb.fr``
        site_name: ``Abri Français``
    """

    site_url = "https://www.xn--abri-franais-sdb.fr"
    site_name = "Abri Français"

    async def generer(self, **kwargs: Any) -> DevisResult:
        """Génère un devis abri via le configurateur WPC Booster.

        Keyword Args:
            largeur: Largeur de l'abri (ex: ``"5,50M"``).
            profondeur: Profondeur (ex: ``"4,35m"``).
            ouvertures: Liste de dicts ``{type, face, position}``.
            extension_toiture: ``""`` ou ``"Droite 1 M"``, etc.
            plancher: True/False pour ajouter un plancher.
            bac_acier: True pour bac acier anti-condensation.
            client_*: Coordonnées client.
            produits_complementaires: Liste de produits supplémentaires.
            code_promo: Code promo.

        Returns:
            DevisResult avec chemin PDF.
        """
        from generateur_devis_auto import generer_devis_abri

        start = time.time()
        self.logger.info(
            "Démarrage devis abri %s x %s",
            kwargs.get("largeur"), kwargs.get("profondeur"),
        )

        try:
            filepath = await generer_devis_abri(**kwargs)
            elapsed = time.time() - start
            self.logger.info("Devis abri généré en %.1fs : %s", elapsed, filepath)
            return DevisResult(
                success=True,
                filepath=filepath,
                elapsed_seconds=elapsed,
            )
        except Exception as e:
            elapsed = time.time() - start
            self.logger.error("Échec devis abri : %s", e, exc_info=True)
            return DevisResult(success=False, error=str(e), elapsed_seconds=elapsed)
