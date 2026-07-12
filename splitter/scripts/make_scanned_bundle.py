"""Generuje testowy "skan" - PDF BEZ warstwy tekstowej (strony jako obrazy).

Symuluje zeskanowane dokumenty HR: kazda strona jest renderowana przez
Pillow (czarny tekst na bialym tle) i zapisywana jako obraz w wielostronicowym
PDF. Taki plik nie ma osadzonej warstwy tekstowej - bez OCR wszystkie strony
sa puste. Sluzy do weryfikacji fallbacku Tesseract w splitterze.

Uzycie:
    python scripts/make_scanned_bundle.py [sciezka_wyjsciowa.pdf] [opcje]

Opcje:
    --z-nieznanym   dodaje dokument spoza slownika (wniosek o okulary) -
                    test sciezki "wymaga weryfikacji" + propozycji LLM
    --z-pusta       dodaje jedna pusta (biala) strone - test bramki
                    "pusta strona omija LLM" (doklejenie + requiresReview)
    --dpi N         rozdzielczosc renderu (domyslnie 150)

Domyslne wyjscie: test-data/skan_dokumenty_hr.pdf w katalogu glownym repo.
Wzorce do pola `patterns` bierz z test-data/wzorce_testowe.json
(generuje je scripts/make_test_documents.py) - naglowki pasuja.

Wymaga: pip install Pillow
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Tekst z polskimi znakami - realny skan ma diakrytyki; klasyfikator i tak
# normalizuje obie strony do ASCII, wiec naglowki pasuja do wzorcow.
UMOWA = [
    (
        "UMOWA O PRACĘ",
        "zawarta w dniu 1 czerwca 2026 r. w Warszawie pomiędzy pracodawcą "
        "ACME Sp. z o.o. z siedzibą w Warszawie a pracownikiem Janem "
        "Kowalskim. Rodzaj pracy: specjalista ds. kadr. Wynagrodzenie "
        "zasadnicze 8200 zł brutto miesięcznie. Wymiar czasu pracy: pełny "
        "etat. Miejsce wykonywania pracy: Warszawa.",
    ),
    (
        "",
        "Strona 2. Ciąg dalszy postanowień umowy. Pracownik zobowiązuje się "
        "do zachowania poufności informacji stanowiących tajemnicę "
        "przedsiębiorstwa. Pozostałe warunki zatrudnienia zgodnie z "
        "regulaminem pracy obowiązującym u pracodawcy. Umowę sporządzono "
        "w dwóch jednobrzmiących egzemplarzach.",
    ),
]

ANEKS = [
    (
        "ANEKS DO UMOWY O PRACĘ",
        "zawarty w dniu 15 czerwca 2026 r. Strony zgodnie postanawiają, że "
        "od dnia 1 lipca 2026 r. zmienia się wysokość wynagrodzenia "
        "zasadniczego na kwotę 9100 zł brutto. Pozostałe warunki umowy o "
        "pracę pozostają bez zmian.",
    ),
]

SWIADECTWO = [
    (
        "ŚWIADECTWO PRACY",
        "Stosunek pracy ustał w dniu 30 czerwca 2026 r. na mocy porozumienia "
        "stron. Okres zatrudnienia: od 1 stycznia 2024 r. do 30 czerwca "
        "2026 r. w pełnym wymiarze czasu pracy na stanowisku specjalisty "
        "ds. kadr.",
    ),
    (
        "",
        "Strona 2 świadectwa pracy. W okresie zatrudnienia pracownik "
        "wykorzystał urlop wypoczynkowy w wymiarze 13 dni. Pouczenie o "
        "możliwości wystąpienia z wnioskiem o sprostowanie świadectwa w "
        "terminie 14 dni od dnia jego otrzymania.",
    ),
]

WNIOSEK_OKULARY = [
    (
        "WNIOSEK O DOFINANSOWANIE OKULARÓW",
        "Zwracam się z prośbą o dofinansowanie zakupu okularów korygujących "
        "wzrok do pracy przy monitorze ekranowym, zgodnie z zarządzeniem "
        "wewnętrznym nr 7/2025. W załączeniu faktura na kwotę 450 zł.",
    ),
]


def _load_font(size: int, bold: bool) -> ImageFont.FreeTypeFont:
    candidates = (
        ["C:/Windows/Fonts/arialbd.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
        if bold
        else ["C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    )
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    # Ostatnia deska ratunku: wbudowany font (bez polskich glifow, ale nie wywali).
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        words = paragraph.split()
        line = ""
        for word in words:
            trial = f"{line} {word}".strip()
            if font.getlength(trial) <= max_width or not line:
                line = trial
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


def _render_page(header: str, body: str, dpi: int) -> Image.Image:
    # A4 w pikselach dla zadanego DPI (A4 = 8.27 x 11.69 cala).
    width = round(8.27 * dpi)
    height = round(11.69 * dpi)
    margin = round(dpi * 0.75)
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)

    header_font = _load_font(round(dpi * 0.30), bold=True)
    body_font = _load_font(round(dpi * 0.19), bold=False)
    max_width = width - 2 * margin

    y = margin
    if header:
        for line in _wrap(header, header_font, max_width):
            draw.text((margin, y), line, fill="black", font=header_font)
            y += round(header_font.size * 1.3)
        y += round(header_font.size * 0.6)
    for line in _wrap(body, body_font, max_width):
        draw.text((margin, y), line, fill="black", font=body_font)
        y += round(body_font.size * 1.45)
    return image


def _blank_page(dpi: int) -> Image.Image:
    width = round(8.27 * dpi)
    height = round(11.69 * dpi)
    return Image.new("RGB", (width, height), "white")


def main() -> None:
    with_unknown = with_blank = False
    dpi = 150
    positional: list[str] = []
    args = iter(sys.argv[1:])
    for arg in args:
        if arg == "--z-nieznanym":
            with_unknown = True
        elif arg == "--z-pusta":
            with_blank = True
        elif arg == "--dpi":
            dpi = int(next(args))
        else:
            positional.append(arg)

    default = Path(__file__).resolve().parents[2] / "test-data" / "skan_dokumenty_hr.pdf"
    output = Path(positional[0]) if positional else default
    output.parent.mkdir(parents=True, exist_ok=True)

    documents = [UMOWA, ANEKS, SWIADECTWO]
    if with_unknown:
        documents.insert(2, WNIOSEK_OKULARY)

    pages: list[Image.Image] = []
    for document in documents:
        for header, body in document:
            pages.append(_render_page(header, body, dpi))
    if with_blank:
        pages.append(_blank_page(dpi))

    pages[0].save(
        str(output),
        "PDF",
        save_all=True,
        append_images=pages[1:],
        resolution=float(dpi),
    )
    extras = []
    if with_unknown:
        extras.append("+ wniosek spoza slownika")
    if with_blank:
        extras.append("+ pusta strona")
    print(
        f"Zapisano {output.resolve()} ({len(pages)} stron, {dpi} DPI, "
        f"bez warstwy tekstowej) {' '.join(extras)}".strip()
    )
    print(
        "Test:\n"
        f'  curl.exe -s -X POST http://localhost:8010/api/split '
        f'-F "file=@{output.name}" -F "patterns=<test-data/wzorce_testowe.json"'
    )


if __name__ == "__main__":
    main()
