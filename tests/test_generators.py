"""Tests pour les classes de générateurs de devis."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from generators.base import ClientInfo, DevisResult
from generators.pergola import PergolaGenerator
from generators.terrasse import TerrasseGenerator, TerrasseDetailGenerator
from generators.cloture import ClotureGenerator
from generators.abri import AbriGenerator
from generators.studio import StudioGenerator


class TestClientInfo:
    """Tests pour le dataclass ClientInfo."""

    def test_defaults(self) -> None:
        """Les champs sont vides par défaut."""
        client = ClientInfo()
        assert client.nom == ""
        assert client.prenom == ""
        assert client.email == ""

    def test_with_values(self) -> None:
        """Création avec des valeurs."""
        client = ClientInfo(
            nom="Dupont", prenom="Jean", email="jean@test.fr"
        )
        assert client.nom == "Dupont"
        assert client.prenom == "Jean"


class TestDevisResult:
    """Tests pour le dataclass DevisResult."""

    def test_success_json(self, tmp_path) -> None:
        """Un résultat réussi se sérialise en JSON avec les bons champs."""
        pdf = tmp_path / "test.pdf"
        pdf.write_bytes(b"%PDF-1.4 content")

        result = DevisResult(
            success=True,
            filepath=str(pdf),
            date_livraison="15/03/2025",
            elapsed_seconds=42.5,
        )
        data = json.loads(result.to_json())

        assert data["success"] is True
        assert data["filepath"] == str(pdf)
        assert data["date_livraison"] == "15/03/2025"
        assert "size_kb" in data

    def test_failure_json(self) -> None:
        """Un résultat échoué contient le message d'erreur."""
        result = DevisResult(success=False, error="Timeout")
        data = json.loads(result.to_json())

        assert data["success"] is False
        assert data["error"] == "Timeout"


@pytest.mark.asyncio
class TestPergolaGenerator:
    """Tests pour PergolaGenerator."""

    async def test_generer_success(self) -> None:
        """Génération réussie via le module legacy mocké."""
        with patch(
            "generators.pergola.generer_devis_pergola",
            new_callable=AsyncMock,
            return_value=("/tmp/devis.pdf", "20/03/2025"),
            create=True,
        ) as mock_gen:
            # Patch aussi l'import dans le module
            with patch.dict("sys.modules", {
                "generateur_devis_3sites": type("M", (), {
                    "generer_devis_pergola": mock_gen,
                })(),
            }):
                gen = PergolaGenerator()
                result = await gen.generer(
                    largeur="4m", profondeur="3m",
                    fixation="adossee", ventelle="largeur",
                    client_nom="Dupont", client_prenom="Jean",
                )

                assert result.success is True
                assert result.date_livraison == "20/03/2025"

    async def test_generer_failure(self) -> None:
        """Échec de génération retourne un DevisResult d'erreur."""
        with patch.dict("sys.modules", {
            "generateur_devis_3sites": type("M", (), {
                "generer_devis_pergola": AsyncMock(
                    side_effect=RuntimeError("Chrome crash")
                ),
            })(),
        }):
            gen = PergolaGenerator()
            result = await gen.generer(
                largeur="4m", profondeur="3m",
                fixation="adossee", ventelle="largeur",
            )

            assert result.success is False
            assert "Chrome crash" in result.error


@pytest.mark.asyncio
class TestTerrasseGenerator:
    """Tests pour TerrasseGenerator."""

    async def test_site_attributes(self) -> None:
        """Vérification des attributs de classe."""
        gen = TerrasseGenerator()
        assert gen.site_url == "https://terrasseenbois.fr"
        assert gen.site_name == "Terrasse en Bois"


@pytest.mark.asyncio
class TestTerrasseDetailGenerator:
    """Tests pour TerrasseDetailGenerator."""

    async def test_site_attributes(self) -> None:
        """Vérification des attributs de classe."""
        gen = TerrasseDetailGenerator()
        assert "terrasseenbois" in gen.site_url


@pytest.mark.asyncio
class TestClotureGenerator:
    """Tests pour ClotureGenerator."""

    async def test_site_attributes(self) -> None:
        """Vérification des attributs de classe."""
        gen = ClotureGenerator()
        assert gen.site_url == "https://cloturebois.fr"


@pytest.mark.asyncio
class TestAbriGenerator:
    """Tests pour AbriGenerator."""

    async def test_site_attributes(self) -> None:
        """Vérification des attributs de classe."""
        gen = AbriGenerator()
        assert "abri" in gen.site_url.lower() or "xn--abri" in gen.site_url


@pytest.mark.asyncio
class TestStudioGenerator:
    """Tests pour StudioGenerator."""

    async def test_site_attributes(self) -> None:
        """Vérification des attributs de classe."""
        gen = StudioGenerator()
        assert "studio" in gen.site_url.lower() or "xn--studio" in gen.site_url
