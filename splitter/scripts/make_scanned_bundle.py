"""Generuje testowy "skan" - PDF BEZ warstwy tekstowej (strony jako obrazy).

Symuluje zeskanowane dokumenty HR: kazda strona jest renderowana przez
Pillow (czarny tekst na bialym tle) i zapisywana jako obraz w wielostronicowym
PDF. Taki plik nie ma osadzonej warstwy tekstowej - bez OCR wszystkie strony
sa puste. Sluzy do weryfikacji fallbacku Tesseract w splitterze.

Uzycie:
    python scripts/make_scanned_bundle.py [sciezka_wyjsciowa.pdf] [opcje]

Opcje:
    --z-nieznanym     dodaje dokument spoza slownika (wniosek o okulary) -
                      test sciezki "wymaga weryfikacji" + propozycji LLM
    --z-pusta         dodaje jedna pusta (biala) strone na koncu paczki
    --z-separatorami  wstawia biala kartke miedzy dokumenty, z artefaktami
                      realnego skanu (czarna krawedz szyby, dziurki po
                      dziurkaczu, kurz) - test progu pokrycia atramentem
    --z-dowodem       wstawia skan dowodu osobistego: duzo atramentu, zero
                      czytelnego tekstu. KLUCZOWY przypadek regresji -
                      taka strona MUSI przetrwac podzial
    --dpi N           rozdzielczosc renderu (domyslnie 150)

Do weryfikacji wykrywania pustych stron uzywaj:
    python scripts/make_scanned_bundle.py --z-separatorami --z-dowodem

Domyslne wyjscie: test-data/skan_dokumenty_hr.pdf w katalogu glownym repo.
Wzorce do pola `patterns` bierz z test-data/wzorce_testowe.json
(generuje je scripts/make_test_documents.py) - naglowki pasuja.

Wymaga: pip install Pillow
"""

import sys
import unicodedata
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def _ascii(text: str) -> str:
    """Diakrytyki poza konsole Windows (cp1252) - tylko do wydruku opisu."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")

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


def _scanner_noise(image: Image.Image, dpi: int) -> Image.Image:
    """Dokleja artefakty realnego skanu pustej kartki.

    Czarny pas przy krawedzi (szyba skanera), dziurki po dziurkaczu i kurz.
    Wszystko lezy w odcinanym marginesie albo jest ponizej progu pokrycia,
    wiec strona MA pozostac wykryta jako pusta - to test odpornosci progu,
    a nie prosty przypadek idealnej bieli.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    edge = round(dpi * 0.04)
    draw.rectangle([0, 0, edge, height], fill=(30, 30, 30))
    hole_r = round(dpi * 0.06)
    for fraction in (0.30, 0.50, 0.70):
        cy = round(height * fraction)
        cx = round(dpi * 0.18)
        draw.ellipse([cx - hole_r, cy - hole_r, cx + hole_r, cy + hole_r], fill=(40, 40, 40))
    for index in range(40):
        x = round(width * (0.2 + 0.015 * (index % 40)))
        y = round(height * (0.15 + 0.02 * (index % 35)))
        draw.point((x, y), fill=(90, 90, 90))
    return image


def _id_card_page(dpi: int) -> Image.Image:
    """Skan dowodu osobistego: DUZO atramentu, ZERO czytelnego tekstu.

    Kluczowy przypadek regresji incydentu 2026-07-24: Tesseract nie odczyta
    z takiej strony nic (0 znakow alnum), ale strona jest pelna tresci
    i NIE MOZE zostac usunieta. Zamiast tekstu rysujemy mikrodruk (cienkie
    kreski) - dla OCR nieczytelny, dla bramki atramentowej wyraznie widoczny.
    """
    width = round(8.27 * dpi)
    height = round(11.69 * dpi)
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)

    # kartonik w formacie ID-1 (85.6 x 54 mm) mniej wiecej na srodku strony
    card_w, card_h = round(dpi * 3.37), round(dpi * 2.13)
    x0 = (width - card_w) // 2
    y0 = round(height * 0.32)
    draw.rectangle(
        [x0, y0, x0 + card_w, y0 + card_h],
        fill=(198, 206, 214),
        outline=(60, 60, 60),
        width=max(2, round(dpi * 0.02)),
    )
    # zdjecie posiadacza
    photo_x = x0 + round(card_w * 0.06)
    photo_y = y0 + round(card_h * 0.20)
    draw.rectangle(
        [photo_x, photo_y, photo_x + round(card_w * 0.26), photo_y + round(card_h * 0.62)],
        fill=(78, 78, 78),
    )
    # mikrodruk: kreski imitujace pola danych - OCR nie zrobi z tego znakow
    line_x = x0 + round(card_w * 0.38)
    line_w = round(card_w * 0.52)
    for index in range(7):
        ly = y0 + round(card_h * (0.22 + index * 0.085))
        draw.rectangle(
            [line_x, ly, line_x + round(line_w * (0.55 + 0.06 * (index % 5))), ly + max(2, round(dpi * 0.022))],
            fill=(55, 55, 55),
        )
    # pasek MRZ na dole kartonika
    draw.rectangle(
        [x0 + round(card_w * 0.05), y0 + round(card_h * 0.86),
         x0 + round(card_w * 0.95), y0 + round(card_h * 0.93)],
        fill=(70, 70, 70),
    )
    return image


def main() -> None:
    with_unknown = with_blank = with_separators = with_id_card = False
    dpi = 150
    positional: list[str] = []
    args = iter(sys.argv[1:])
    for arg in args:
        if arg == "--z-nieznanym":
            with_unknown = True
        elif arg == "--z-pusta":
            with_blank = True
        elif arg == "--z-separatorami":
            with_separators = True
        elif arg == "--z-dowodem":
            with_id_card = True
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

    # opis stron - drukowany na koncu, zeby bylo z czym porownac wynik podzialu
    pages: list[Image.Image] = []
    layout: list[str] = []

    def add(image: Image.Image, description: str) -> None:
        pages.append(image)
        layout.append(f"  strona {len(pages):>2}: {_ascii(description)}")

    for index, document in enumerate(documents):
        for header, body in document:
            add(_render_page(header, body, dpi), header or "  (ciag dalszy)")
        # separator po kazdym dokumencie procz ostatniego - tak wyglada
        # realna paczka ze skanera z kartkami rozdzielajacymi
        if with_separators and index < len(documents) - 1:
            add(
                _scanner_noise(_blank_page(dpi), dpi),
                "BIALA KARTKA (separator, z artefaktami skanu) -> do usuniecia",
            )
        if with_id_card and index == 0:
            add(
                _id_card_page(dpi),
                "SKAN DOWODU (atrament, zero tekstu dla OCR) -> MUSI zostac",
            )
    if with_blank:
        add(_blank_page(dpi), "BIALA KARTKA (na koncu paczki) -> do usuniecia")

    pages[0].save(
        str(output),
        "PDF",
        save_all=True,
        append_images=pages[1:],
        resolution=float(dpi),
    )
    print(
        f"Zapisano {output.resolve()} ({len(pages)} stron, {dpi} DPI, "
        "bez warstwy tekstowej)"
    )
    print("Uklad paczki:")
    print("\n".join(layout))
    print(
        "\nTest (tryb keep - nic nie zniknie, ale log pokaze pokrycie atramentem):\n"
        f'  curl.exe -s -X POST http://localhost:8010/api/split '
        f'-F "file=@{output.name}" -F "patterns=<test-data/wzorce_testowe.json"\n'
        "  docker compose logs --tail 200 | Select-String \"pokrycie atramentem\""
    )


if __name__ == "__main__":
    main()
