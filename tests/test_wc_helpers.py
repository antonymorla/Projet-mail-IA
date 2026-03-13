"""Tests pour les fonctions utilitaires WooCommerce."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from generators.wc_helpers import (
    ajouter_au_panier_wc,
    select_wc_attribute,
    match_wc_variation,
    verifier_panier,
)


@pytest.mark.asyncio
class TestSelectWcAttribute:
    """Tests pour la sélection d'attributs WC."""

    async def test_swatch_click(self, mock_page: AsyncMock) -> None:
        """Clic sur un swatch wcboost réussi."""
        mock_page.evaluate = AsyncMock(return_value="swatch_li")
        mock_page.wait_for_function = AsyncMock()

        result = await select_wc_attribute(mock_page, "attribute_pa_largeur", "7m")

        assert result == "swatch_li"
        assert mock_page.evaluate.called

    async def test_already_selected(self, mock_page: AsyncMock) -> None:
        """Swatch déjà sélectionné — pas de reclic."""
        mock_page.evaluate = AsyncMock(return_value="already_selected")

        result = await select_wc_attribute(mock_page, "attribute_pa_largeur", "7m")

        assert result == "already_selected"

    async def test_jquery_fallback(self, mock_page: AsyncMock) -> None:
        """Fallback jQuery quand le swatch n'est pas trouvé."""
        mock_page.evaluate = AsyncMock(side_effect=[False, "jquery"])

        result = await select_wc_attribute(mock_page, "attribute_pa_largeur", "7m")

        assert result == "jquery"


@pytest.mark.asyncio
class TestMatchWcVariation:
    """Tests pour le match de variation WC."""

    async def test_variation_found(self, mock_page: AsyncMock) -> None:
        """Variation trouvée dans le JSON embarqué."""
        mock_page.evaluate = AsyncMock(return_value="12345")

        result = await match_wc_variation(
            mock_page, {"attribute_pa_largeur": "7m"}
        )

        assert result == "12345"

    async def test_variation_not_found(self, mock_page: AsyncMock) -> None:
        """Variation non trouvée → retourne None."""
        mock_page.evaluate = AsyncMock(return_value="not_found")

        result = await match_wc_variation(
            mock_page, {"attribute_pa_largeur": "99m"}
        )

        assert result is None

    async def test_no_form(self, mock_page: AsyncMock) -> None:
        """Pas de formulaire sur la page → retourne None."""
        mock_page.evaluate = AsyncMock(return_value="no_form")

        result = await match_wc_variation(mock_page, {})

        assert result is None


@pytest.mark.asyncio
class TestAjouterAuPanierWc:
    """Tests pour l'ajout au panier via clic natif."""

    async def test_ajout_reussi(self, mock_page: AsyncMock) -> None:
        """Ajout au panier réussi — bouton actif, confirmation reçue."""
        # evaluate retourne: 1) bouton non désactivé, 2) image vide (pas WAPF)
        mock_page.evaluate = AsyncMock(side_effect=[False, ""])
        mock_page.wait_for_selector = AsyncMock()

        btn = AsyncMock()
        btn.scroll_into_view_if_needed = AsyncMock()
        btn.click = AsyncMock()
        locator = MagicMock()
        locator.first = btn
        mock_page.locator = MagicMock(return_value=locator)

        result = await ajouter_au_panier_wc(mock_page)

        assert result is True
        btn.click.assert_called_once()

    async def test_bouton_desactive_raise(self, mock_page: AsyncMock) -> None:
        """Bouton désactivé → Exception levée."""
        mock_page.evaluate = AsyncMock(return_value=True)

        btn = AsyncMock()
        locator = MagicMock()
        locator.first = btn
        mock_page.locator = MagicMock(return_value=locator)

        with pytest.raises(Exception, match="désactivé"):
            await ajouter_au_panier_wc(mock_page)


@pytest.mark.asyncio
class TestVerifierPanier:
    """Tests pour la vérification du panier."""

    async def test_panier_ok(self, mock_page: AsyncMock) -> None:
        """Panier avec le bon nombre d'items."""
        mock_page.evaluate = AsyncMock(return_value=2)

        nb = await verifier_panier(mock_page, "https://example.com", nb_attendu=2)

        assert nb == 2
        mock_page.goto.assert_called_once()

    async def test_panier_incomplet(self, mock_page: AsyncMock) -> None:
        """Panier avec moins d'items que prévu."""
        mock_page.evaluate = AsyncMock(return_value=1)

        nb = await verifier_panier(mock_page, "https://example.com", nb_attendu=3)

        assert nb == 1
