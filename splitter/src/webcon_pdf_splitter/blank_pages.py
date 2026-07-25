"""Wykrywanie stron wizualnie pustych (bramka atramentowa).

Kryterium tekstowe (liczba znakow po OCR) NIE odroznia bialej kartki od
strony, ktorej OCR nie odczytal - skan dowodu osobistego i pusta kartka
maja tak samo 0 znakow. Dlatego o pustce decyduje obraz: udzial ciemnych
pikseli na renderze w niskiej rozdzielczosci.

Patrz docs/superpowers/specs/2026-07-25-blank-page-detection-design.md.
"""

import logging

logger = logging.getLogger(__name__)

# Piksel ciemniejszy niz ta wartosc (skala 0-255) liczy sie jako atrament.
# Prog jest luzny, bo papier bywa szary/kremowy - "nie-biel" to za malo.
DARK_THRESHOLD = 200


def ink_ratio(image, margin_ratio: float = 0.04, dark_threshold: int = DARK_THRESHOLD) -> float:
    """Udzial ciemnych pikseli (0.0-1.0) po odcieciu marginesu.

    Margines odcinamy, bo skan pustej kartki niemal zawsze ma przy
    krawedziach czarne pasy z szyby skanera, dziurki po dziurkaczu albo
    czarne trojkaty w rogach przy przekrzywieniu.
    """
    grayscale = image.convert("L")
    width, height = grayscale.size
    margin_x, margin_y = int(width * margin_ratio), int(height * margin_ratio)
    core = grayscale.crop((margin_x, margin_y, width - margin_x, height - margin_y))
    core_width, core_height = core.size
    total = core_width * core_height
    if total <= 0:
        return 0.0
    histogram = core.histogram()
    dark = sum(histogram[: dark_threshold + 1])
    return dark / total
