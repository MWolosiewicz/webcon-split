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


class BlankPageDetector:
    """Ocenia, czy wskazane strony PDF sa wizualnie puste.

    Render w niskim DPI (domyslnie 60) jest tani - to ulamek kosztu OCR,
    wiec detekcja moze biec PRZED Tesseractem i oszczedzic go na blankach.
    Render jest sekwencyjny, bo PDFium nie jest thread-safe.

    Kazdy blad oznacza "strona ma tresc": nieoceniona strona nigdy nie
    kwalifikuje sie do usuniecia.
    """

    def __init__(
        self,
        dpi: int = 60,
        max_ink_ratio: float = 0.002,
        margin_ratio: float = 0.04,
    ) -> None:
        self._dpi = dpi
        self._max_ink_ratio = max_ink_ratio
        self._margin_ratio = margin_ratio

    def detect_blank_pages(self, pdf_path: str, page_indices: list[int]) -> set[int]:
        if not page_indices:
            return set()
        try:
            import pypdfium2 as pdfium

            pdf = pdfium.PdfDocument(pdf_path)
        except Exception:
            logger.warning(
                "Nie udalo sie otworzyc dokumentu do oceny pustych stron - "
                "zadna strona nie zostanie uznana za pusta",
                exc_info=True,
            )
            return set()

        blank: set[int] = set()
        try:
            for index in page_indices:
                try:
                    bitmap = pdf[index].render(scale=self._dpi / 72.0)
                    ratio = ink_ratio(bitmap.to_pil(), self._margin_ratio)
                except Exception:
                    logger.warning(
                        "Nie udalo sie ocenic strony %s - traktowana jako niepusta",
                        index + 1,
                        exc_info=True,
                    )
                    continue
                if ratio <= self._max_ink_ratio:
                    blank.add(index)
                    logger.info(
                        "Strona %s: pokrycie atramentem %.3f%% -> wizualnie pusta",
                        index + 1,
                        ratio * 100,
                    )
                else:
                    logger.info(
                        "Strona %s: pokrycie atramentem %.3f%% -> ma tresc (mimo braku tekstu)",
                        index + 1,
                        ratio * 100,
                    )
        finally:
            pdf.close()
        return blank
