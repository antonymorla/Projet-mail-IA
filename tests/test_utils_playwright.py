"""Tests pour les utilitaires Playwright (fermer_popups, appliquer_code_promo)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from utils_playwright import appliquer_code_promo, fermer_popups


@pytest.mark.asyncio
class TestFermerPopups:
    """Tests pour la fermeture des popups GDPR/cookies."""

    async def test_clic_bouton_accepter(self, mock_page: AsyncMock) -> None:
        """Clique sur le bouton d'acceptation si visible."""
        locator = AsyncMock()
        locator.first = locator
        locator.is_visible = AsyncMock(return_value=True)
        locator.click = AsyncMock()
        mock_page.locator = MagicMock(return_value=locator)

        await fermer_popups(mock_page)

        # Vérifie que evaluate a été appelé (injection CSS)
        assert mock_page.evaluate.called

    async def test_pas_de_popup(self, mock_page: AsyncMock) -> None:
        """Pas de popup visible — continue sans erreur."""
        locator = AsyncMock()
        locator.first = locator
        locator.is_visible = AsyncMock(return_value=False)
        mock_page.locator = MagicMock(return_value=locator)

        # Ne doit pas lever d'exception
        await fermer_popups(mock_page)


@pytest.mark.asyncio
class TestAppliquerCodePromo:
    """Tests pour l'application des codes promo."""

    async def test_code_vide(self, mock_page: AsyncMock) -> None:
        """Code promo vide → retour immédiat."""
        await appliquer_code_promo(mock_page, "")

        # Aucun evaluate ne doit être appelé
        mock_page.evaluate.assert_not_called()

    async def test_code_none(self, mock_page: AsyncMock) -> None:
        """Code promo None → retour immédiat."""
        await appliquer_code_promo(mock_page, None)
        mock_page.evaluate.assert_not_called()

    async def test_ajax_success(self, mock_page: AsyncMock) -> None:
        """Application AJAX réussie."""
        mock_page.evaluate = AsyncMock(return_value={"ok": True})

        await appliquer_code_promo(mock_page, "LEROYMERLIN10")

        mock_page.evaluate.assert_called_once()

    async def test_ajax_error_fallback_formulaire(self, mock_page: AsyncMock) -> None:
        """AJAX échoue → fallback sur le formulaire HTML."""
        # AJAX retourne nonce_absent → fallback
        mock_page.evaluate = AsyncMock(
            return_value={"ok": False, "msg": "nonce_absent"}
        )

        locator = AsyncMock()
        locator.first = locator
        locator.is_visible = AsyncMock(return_value=True)
        locator.fill = AsyncMock()
        locator.click = AsyncMock()
        mock_page.locator = MagicMock(return_value=locator)

        await appliquer_code_promo(mock_page, "TEST123")
