"""
pergola — Générateur de devis pour les pergolas bois (mapergolabois.fr).

Produit WooCommerce variable (productId=16046) avec options WAPF
(sur-mesure, poteaux lamellé-collé).

Usage :
    gen = PergolaGenerator()
    result = await gen.generer(largeur="4m", profondeur="3m", ...)
"""

from __future__ import annotations

import time
from typing import Any

from generators.base import BaseGenerator, ClientInfo, DevisResult
from generators.logging_config import get_logger

logger = get_logger(__name__)


class PergolaGenerator(BaseGenerator):
    """Génère des devis pergola bois sur mapergolabois.fr.

    Utilise le produit WooCommerce variable (productId=16046) avec les
    attributs : largeur, profondeur, fixation, ventelle, option.
    Options WAPF : sur-mesure (+199.90 EUR), poteaux lamellé-collé.

    Attributes:
        site_url: ``https://mapergolabois.fr``
        site_name: ``Ma Pergola Bois``
    """

    site_url = "https://mapergolabois.fr"
    site_name = "Ma Pergola Bois"

    async def generer(self, **kwargs: Any) -> DevisResult:
        """Génère un devis pergola via Playwright.

        Délègue à ``generer_devis_pergola`` du module legacy pour
        préserver le comportement existant.

        Keyword Args:
            largeur: ``"2m"`` à ``"10m"``.
            profondeur: ``"2m"`` à ``"5m"``.
            fixation: ``"adossee"`` | ``"independante"``.
            ventelle: ``"largeur"`` | ``"profondeur"`` | ``"retro"`` | ``"sans"``.
            option: ``"non"`` | ``"platelage"`` | ... | ``"polycarbonate"``.
            poteau_lamelle_colle: True pour poteaux lamellé-collé.
            nb_poteaux_lamelle_colle: Nombre (0 = auto).
            sur_mesure: True pour dimensions personnalisées (+199.90 EUR).
            largeur_hors_tout: Largeur réelle en m (ex: ``"7.60"``).
            profondeur_hors_tout: Profondeur réelle en m.
            hauteur_hors_tout: Hauteur réelle en m (max 3.07m).
            client_nom, client_prenom, client_email, client_telephone, client_adresse:
                Coordonnées client.
            code_promo: Code promo à appliquer.
            mode_livraison: ``""`` | ``"retrait"`` | ``"livraison"``.
            produits_complementaires: JSON array de produits supplémentaires.
            headless: Mode sans interface graphique.

        Returns:
            DevisResult avec chemin PDF et date de livraison.
        """
        from generateur_devis_3sites import generer_devis_pergola

        start = time.time()
        client = ClientInfo(
            nom=kwargs.get("client_nom", ""),
            prenom=kwargs.get("client_prenom", ""),
            email=kwargs.get("client_email", ""),
            telephone=kwargs.get("client_telephone", ""),
            adresse=kwargs.get("client_adresse", ""),
        )

        self.logger.info(
            "Démarrage devis pergola %s x %s | %s | ventelle=%s",
            kwargs.get("largeur"), kwargs.get("profondeur"),
            kwargs.get("fixation"), kwargs.get("ventelle"),
        )

        try:
            filepath, date_livraison = await generer_devis_pergola(**kwargs)
            elapsed = time.time() - start
            self.logger.info("Devis pergola généré en %.1fs : %s", elapsed, filepath)
            return DevisResult(
                success=True,
                filepath=filepath,
                date_livraison=date_livraison or "",
                elapsed_seconds=elapsed,
            )
        except Exception as e:
            elapsed = time.time() - start
            self.logger.error("Échec devis pergola : %s", e, exc_info=True)
            return DevisResult(
                success=False,
                error=str(e),
                elapsed_seconds=elapsed,
            )
