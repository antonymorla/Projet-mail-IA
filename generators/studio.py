"""
studio — Générateur de devis pour les studios de jardin (studio-francais.fr).

Utilise le configurateur WPC Performance Booster avec gestion des menuiseries
(PVC/ALU), positionnement par module 1,10m, et détection de conflits.

Usage :
    gen = StudioGenerator()
    result = await gen.generer(largeur="5,5", profondeur="3,5", ...)
"""

from __future__ import annotations

import time
from typing import Any

from generators.base import BaseGenerator, ClientInfo, DevisResult
from generators.logging_config import get_logger

logger = get_logger(__name__)


class StudioGenerator(BaseGenerator):
    """Génère des devis studio de jardin sur studio-francais.fr.

    Gère 28 combinaisons de dimensions (5,2 m² à 49,9 m²),
    les menuiseries PVC/ALU avec positionnement automatique par module,
    et toutes les options (bardage, isolation, rehausse, terrasse, pergola).

    Attributes:
        site_url: ``https://xn--studio-franais-qjb.fr``
        site_name: ``Studio Français``
    """

    site_url = "https://xn--studio-franais-qjb.fr"
    site_name = "Studio Français"

    async def generer(self, **kwargs: Any) -> DevisResult:
        """Génère un devis studio via le configurateur WPC Booster.

        Keyword Args:
            largeur: Largeur du studio en m (ex: ``"5,5"``).
            profondeur: Profondeur en m (ex: ``"3,5"``).
            menuiseries: Liste de dicts ``{type, materiau, mur, position}``.
            bardage_exterieur: ``"Gris"`` | ``"Brun"`` | ``"Noir"`` | ``"Vert"``.
            isolation: ``"60mm"`` | ``"100 mm (RE2020)"``.
            rehausse: True pour hauteur 3,20m.
            bardage_interieur: ``"OSB"`` | ``"Panneaux bois massif (3 plis épicéa)"``.
            plancher: ``"Sans plancher"`` | ``"Plancher standard"`` | etc.
            finition_plancher: True pour finition plancher.
            terrasse: ``""`` | ``"2m (11m2)"`` | ``"4m (22m2)"``.
            pergola: ``""`` | ``"4x2m (8m2)"`` | ``"4x4m (16m2)"``.
            client_*: Coordonnées client.
            produits_complementaires: Liste de produits supplémentaires.
            code_promo: Code promo.

        Returns:
            DevisResult avec chemin PDF.
        """
        from generateur_devis_auto import generer_devis_studio

        start = time.time()
        self.logger.info(
            "Démarrage devis studio %s x %s",
            kwargs.get("largeur"), kwargs.get("profondeur"),
        )

        try:
            filepath = await generer_devis_studio(**kwargs)
            elapsed = time.time() - start
            self.logger.info("Devis studio généré en %.1fs : %s", elapsed, filepath)
            return DevisResult(
                success=True,
                filepath=filepath,
                elapsed_seconds=elapsed,
            )
        except Exception as e:
            elapsed = time.time() - start
            self.logger.error("Échec devis studio : %s", e, exc_info=True)
            return DevisResult(success=False, error=str(e), elapsed_seconds=elapsed)
