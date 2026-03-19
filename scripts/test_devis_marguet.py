"""Test live : génère le devis studio Marguet 8,8×5,7m avec positionnement menuiseries.

Usage :
    python scripts/test_devis_marguet.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from generateur_devis_auto import generer_devis_studio


async def main():
    result = await generer_devis_studio(
        largeur="8,8",
        profondeur="5,7",
        menuiseries=[
            # MUR DE FACE (8,8m = 8 modules) — côté terrasse
            # Modules 0-1 : mur plein (coffret/vestiaire)
            {"type": "BAIE VITREE",    "materiau": "ALU", "mur": "MUR DE FACE",   "position": "2,20"},   # modules 2-3 (salon)
            {"type": "PORTE VITREE",   "materiau": "ALU", "mur": "MUR DE FACE",   "position": "4,40"},   # module 4 (entrée)
            {"type": "FENETRE DOUBLE", "materiau": "ALU", "mur": "MUR DE FACE",   "position": "5,50"},   # modules 5-6 (chambre)
            # Module 7 : mur plein (angle SDB)

            # MUR DE GAUCHE (5,7m = 5 modules) — fenêtre salon
            {"type": "FENETRE SIMPLE", "materiau": "PVC", "mur": "MUR DE GAUCHE", "position": "centre"},

            # MUR DE DROITE (5,7m = 5 modules) — fenêtre chambre
            {"type": "FENETRE SIMPLE", "materiau": "PVC", "mur": "MUR DE DROITE", "position": "centre"},

            # MUR DU FOND (8,8m = 8 modules) — fenêtre SDB
            {"type": "FENETRE SIMPLE", "materiau": "PVC", "mur": "MUR DU FOND",   "position": "droite"},
        ],
        bardage_exterieur="Gris",
        isolation="100 mm (RE2020)",
        rehausse=False,
        bardage_interieur="OSB",
        plancher="Plancher RE2020",
        finition_plancher=False,
        terrasse="",
        pergola="",
        client_nom="Marguet",
        client_prenom="Thierry",
        client_email="thierry.marguet@pagesgroup.net",
        client_telephone="0675953085",
        client_adresse="Foncine-le-Haut, 39460",
        headless=False,  # navigateur visible pour vérifier le plan de masse
    )
    print(f"\n✅ Devis généré : {result}")


if __name__ == "__main__":
    asyncio.run(main())
