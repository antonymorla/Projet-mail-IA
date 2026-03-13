"""
generators — Package de génération de devis PDF pour le Groupe Abri Français.

Ce package contient les générateurs Playwright pour chaque marque du groupe :
- AbriGenerator      : Abris de jardin (abri-francais.fr) — WPC Booster
- StudioGenerator    : Studios de jardin (studio-francais.fr) — WPC Booster
- PergolaGenerator   : Pergolas bois (mapergolabois.fr) — WooCommerce variable
- TerrasseGenerator  : Terrasses bois (terrasseenbois.fr) — WAPF
- TerrasseDetailGenerator : Terrasses au détail (sans configurateur WAPF)
- ClotureGenerator   : Clôtures bois (cloturebois.fr) — WooCommerce variable

Architecture :
    BaseGenerator (base.py)
      ├── AbriGenerator (abri.py)
      ├── StudioGenerator (studio.py)
      ├── PergolaGenerator (pergola.py)
      ├── TerrasseGenerator (terrasse.py)
      ├── TerrasseDetailGenerator (terrasse.py)
      └── ClotureGenerator (cloture.py)

Usage depuis le serveur MCP :
    from generators import PergolaGenerator
    gen = PergolaGenerator()
    filepath, date = await gen.generer(largeur="4m", profondeur="3m", ...)
"""

from generators.base import BaseGenerator
from generators.abri import AbriGenerator
from generators.studio import StudioGenerator
from generators.pergola import PergolaGenerator
from generators.terrasse import TerrasseGenerator, TerrasseDetailGenerator
from generators.cloture import ClotureGenerator

__all__ = [
    "BaseGenerator",
    "AbriGenerator",
    "StudioGenerator",
    "PergolaGenerator",
    "TerrasseGenerator",
    "TerrasseDetailGenerator",
    "ClotureGenerator",
]
