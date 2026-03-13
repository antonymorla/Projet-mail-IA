"""
terrasse — Générateurs de devis pour les terrasses bois (terrasseenbois.fr).

Deux modes :
- TerrasseGenerator : Configurateur WAPF (essence, longueur, m², lambourdes, etc.)
- TerrasseDetailGenerator : Produits au détail sans configurateur WAPF

Usage :
    gen = TerrasseGenerator()
    result = await gen.generer(essence="CUMARU", longueur="3.05", quantite=20, ...)

    gen_detail = TerrasseDetailGenerator()
    result = await gen_detail.generer(produits=[...], ...)
"""

from __future__ import annotations

import time
from typing import Any

from generators.base import BaseGenerator, ClientInfo, DevisResult
from generators.logging_config import get_logger

logger = get_logger(__name__)


class TerrasseGenerator(BaseGenerator):
    """Génère des devis terrasse bois via le configurateur WAPF.

    Site : terrasseenbois.fr (productId=57595).
    Gère les modes surface (m²) et nombre de lames direct,
    avec split automatique en 2 lignes de panier si nécessaire.

    Attributes:
        site_url: ``https://terrasseenbois.fr``
        site_name: ``Terrasse en Bois``
    """

    site_url = "https://terrasseenbois.fr"
    site_name = "Terrasse en Bois"

    async def generer(self, **kwargs: Any) -> DevisResult:
        """Génère un devis terrasse via le configurateur WAPF.

        Keyword Args:
            essence: Type de bois (``"PIN 27mm Autoclave Vert"``, ``"CUMARU"``, etc.).
            longueur: Longueur des lames en m (ex: ``"3.05"``).
            quantite: Nombre de m² (défaut 1).
            lambourdes: Type de lambourdes ou ``""`` pour aucune.
            lambourdes_longueur: Longueur des lambourdes en m.
            plots: Hauteur des plots (``"NON"`` par défaut).
            visserie: Type de visserie ou ``""`` pour aucune.
            densite_lambourdes: ``"simple"`` ou ``"double"``.
            nb_lames: Nombre exact de lames (mode direct).
            nb_lambourdes: Nombre exact de lambourdes.
            client_*: Coordonnées client.
            code_promo: Code promo.
            mode_livraison: Mode de livraison.
            produits_complementaires: JSON array de produits supplémentaires.
            headless: Mode sans interface.

        Returns:
            DevisResult avec chemin PDF et date de livraison.
        """
        from generateur_devis_3sites import generer_devis_terrasse

        start = time.time()
        self.logger.info(
            "Démarrage devis terrasse %s %sm | %d m²",
            kwargs.get("essence"), kwargs.get("longueur"), kwargs.get("quantite", 1),
        )

        try:
            filepath, date_livraison = await generer_devis_terrasse(**kwargs)
            elapsed = time.time() - start
            self.logger.info("Devis terrasse généré en %.1fs : %s", elapsed, filepath)
            return DevisResult(
                success=True,
                filepath=filepath,
                date_livraison=date_livraison or "",
                elapsed_seconds=elapsed,
            )
        except Exception as e:
            elapsed = time.time() - start
            self.logger.error("Échec devis terrasse : %s", e, exc_info=True)
            return DevisResult(success=False, error=str(e), elapsed_seconds=elapsed)


class TerrasseDetailGenerator(BaseGenerator):
    """Génère des devis terrasse en ajoutant des produits au détail.

    Contourne le configurateur WAPF pour commander des quantités exactes
    de lames, lambourdes, plots et visserie depuis le catalogue.

    Attributes:
        site_url: ``https://terrasseenbois.fr``
        site_name: ``Terrasse en Bois (détail)``
    """

    site_url = "https://terrasseenbois.fr"
    site_name = "Terrasse en Bois (détail)"

    async def generer(self, **kwargs: Any) -> DevisResult:
        """Génère un devis terrasse au détail.

        Keyword Args:
            produits: Liste de dicts ``{url, variation_id, quantite, attribut_selects, description}``.
            client_*: Coordonnées client.
            code_promo: Code promo.
            mode_livraison: Mode de livraison.
            headless: Mode sans interface.

        Returns:
            DevisResult avec chemin PDF et date de livraison.
        """
        from generateur_devis_3sites import generer_devis_terrasse_detail

        start = time.time()
        produits = kwargs.get("produits", [])
        self.logger.info("Démarrage devis terrasse détail : %d produits", len(produits))

        try:
            filepath, date_livraison = await generer_devis_terrasse_detail(**kwargs)
            elapsed = time.time() - start
            self.logger.info(
                "Devis terrasse détail généré en %.1fs : %s", elapsed, filepath
            )
            return DevisResult(
                success=True,
                filepath=filepath,
                date_livraison=date_livraison or "",
                elapsed_seconds=elapsed,
            )
        except Exception as e:
            elapsed = time.time() - start
            self.logger.error("Échec devis terrasse détail : %s", e, exc_info=True)
            return DevisResult(success=False, error=str(e), elapsed_seconds=elapsed)
