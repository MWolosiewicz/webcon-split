"""Generuje zestaw testowych paczek PDF z dokumentami HR do klasyfikacji.

Kazda paczka to jeden PDF (symulacja skanu zbiorczego) pokrywajacy inny
scenariusz pipeline'u: czysty podzial, wtracenie nieznanej strony, obcy
poczatek, obcy ogon, wieksza paczka wielu typow, paczka w calosci nieznana.

Uzycie:
    python scripts/make_test_documents.py [katalog_wyjsciowy]

Domyslny katalog wyjsciowy: test-data/ w katalogu glownym repozytorium.
Obok PDF-ow zapisywany jest wzorce_testowe.json - payload pola `patterns`
do recznych testow przez curl (albo sciaga do slownika WEBCON).

Wymaga: pip install fpdf2
"""

import json
import sys
from pathlib import Path

from fpdf import FPDF

# Wzorce odpowiadajace slownikowi WEBCON (naglowek = typ, frazy pomocnicze).
# Tekst ASCII bez diakrytykow - tak jak zwraca je warstwa tekstowa OCR.
PATTERNS = [
    {
        "documentType": "Umowa o prace",
        "header": "UMOWA O PRACE",
        "phrases": ["pracodawca", "pracownik", "wynagrodzenie", "wymiar czasu pracy"],
        "excludedPhrases": ["aneks"],
        "weight": 1.2,
    },
    {
        "documentType": "Aneks do umowy o prace",
        "header": "ANEKS DO UMOWY O PRACE",
        "phrases": ["aneks", "zmienia sie", "pozostale warunki"],
        "weight": 1.2,
    },
    {
        "documentType": "Swiadectwo pracy",
        "header": "SWIADECTWO PRACY",
        "phrases": ["okres zatrudnienia", "stosunek pracy", "urlop wypoczynkowy"],
        "weight": 1.2,
    },
    {
        "documentType": "Kwestionariusz osobowy",
        "header": "KWESTIONARIUSZ OSOBOWY",
        "phrases": ["dane osobowe", "imie i nazwisko", "adres zamieszkania"],
        "weight": 1.0,
    },
    {
        "documentType": "Zaswiadczenie o zatrudnieniu i zarobkach",
        "header": "ZASWIADCZENIE O ZATRUDNIENIU",
        "phrases": ["zaswiadcza sie", "srednie miesieczne wynagrodzenie"],
        "weight": 1.0,
    },
    {
        "documentType": "Wypowiedzenie umowy o prace",
        "header": "WYPOWIEDZENIE UMOWY O PRACE",
        "phrases": ["okres wypowiedzenia", "rozwiazanie umowy"],
        "weight": 1.0,
    },
]

# --- Dokumenty skladowe (naglowek pierwszej strony + tresci kolejnych stron) ---

UMOWA = [
    (
        "UMOWA O PRACE",
        "zawarta w dniu 2026-06-01 w Warszawie pomiedzy pracodawca "
        "ACME Sp. z o.o. z siedziba w Warszawie a pracownikiem Janem "
        "Kowalskim. Rodzaj pracy: specjalista ds. kadr. Wynagrodzenie "
        "zasadnicze 8200 zl brutto. Wymiar czasu pracy: pelny etat.",
    ),
    (
        "",
        "Strona 2. Ciag dalszy postanowien umowy. Pracownik zobowiazuje sie "
        "do zachowania poufnosci. Pozostale warunki zatrudnienia zgodnie "
        "z regulaminem pracy obowiazujacym u pracodawcy.",
    ),
]

ANEKS = [
    (
        "ANEKS DO UMOWY O PRACE",
        "zawarty w dniu 2026-06-15. Strony zgodnie postanawiaja, ze od dnia "
        "2026-07-01 zmienia sie wysokosc wynagrodzenia zasadniczego na "
        "9100 zl brutto. Pozostale warunki umowy pozostaja bez zmian.",
    ),
]

SWIADECTWO = [
    (
        "SWIADECTWO PRACY",
        "Stosunek pracy ustal w dniu 2026-06-30 na mocy porozumienia stron. "
        "Okres zatrudnienia: od 2024-01-01 do 2026-06-30 w pelnym wymiarze "
        "czasu pracy na stanowisku specjalisty ds. kadr.",
    ),
    (
        "",
        "Strona 2 swiadectwa pracy. W okresie zatrudnienia wykorzystano "
        "urlop wypoczynkowy w wymiarze 13 dni. Pouczenie o mozliwosci "
        "wystapienia o sprostowanie swiadectwa w terminie 14 dni.",
    ),
]

KWESTIONARIUSZ = [
    (
        "KWESTIONARIUSZ OSOBOWY",
        "Dane osobowe osoby ubiegajacej sie o zatrudnienie. Imie i nazwisko: "
        "Anna Nowak. Data urodzenia: 1991-03-12. Adres zamieszkania: "
        "ul. Polna 5, 00-001 Warszawa. Wyksztalcenie: wyzsze.",
    ),
]

ZASWIADCZENIE = [
    (
        "ZASWIADCZENIE O ZATRUDNIENIU",
        "Zaswiadcza sie, ze Pan Jan Kowalski jest zatrudniony w ACME "
        "Sp. z o.o. od dnia 2024-01-01 na czas nieokreslony. Srednie "
        "miesieczne wynagrodzenie z ostatnich 3 miesiecy: 8200 zl brutto. "
        "Zaswiadczenie wydaje sie na prosbe pracownika.",
    ),
]

WYPOWIEDZENIE = [
    (
        "WYPOWIEDZENIE UMOWY O PRACE",
        "Z dniem 2026-06-30 wypowiadam umowe o prace zawarta 2024-01-01 "
        "z zachowaniem miesiecznego okresu wypowiedzenia. Rozwiazanie umowy "
        "nastapi z dniem 2026-07-31. Przyczyna: likwidacja stanowiska.",
    ),
]

# Dokumenty spoza slownika (do testu doklejania / propozycji LLM):
WNIOSEK_OKULARY = [
    (
        "WNIOSEK O DOFINANSOWANIE OKULAROW",
        "Zwracam sie z prosba o dofinansowanie zakupu okularow korygujacych "
        "wzrok do pracy przy monitorze ekranowym, zgodnie z zarzadzeniem "
        "wewnetrznym nr 7/2025. W zalaczeniu faktura na kwote 450 zl.",
    ),
]

PISMO_PRZEWODNIE = [
    (
        "",
        "Dzien dobry, w zalaczeniu przesylam komplet dokumentow pracowniczych "
        "Pana Jana Kowalskiego zgodnie z ustaleniami telefonicznymi. "
        "Prosze o potwierdzenie otrzymania. Pozdrawiam, Maria Wisniewska.",
    ),
]

NOTATKA_ODRECZNA = [
    (
        "",
        "Notatka: dokumenty odebrano 2026-07-10, oryginaly w segregatorze "
        "kadrowym K-12, skan wykonano na urzadzeniu w sekretariacie.",
    ),
]

# --- Scenariusze paczek ---

BUNDLES = {
    "paczka_1_czysta.pdf": {
        "opis": "3 znane dokumenty, pelne dopasowanie - oczekiwany status completed",
        "dokumenty": [UMOWA, ANEKS, SWIADECTWO],
    },
    "paczka_2_wtracenie.pdf": {
        "opis": "nieznany wniosek wtracony miedzy znane dokumenty - test doklejenia "
                "w srodku i propozycji LLM (przypadek 'wniosek o okulary')",
        "dokumenty": [UMOWA, WNIOSEK_OKULARY, SWIADECTWO],
    },
    "paczka_3_obcy_poczatek.pdf": {
        "opis": "pismo przewodnie bez naglowka przed pierwszym znanym dokumentem - "
                "test segmentu 'Nieznany typ dokumentu' na starcie",
        "dokumenty": [PISMO_PRZEWODNIE, UMOWA, ANEKS],
    },
    "paczka_4_obcy_ogon.pdf": {
        "opis": "odreczna notatka po ostatnim znanym dokumencie - test doklejenia ogona",
        "dokumenty": [SWIADECTWO, NOTATKA_ODRECZNA],
    },
    "paczka_5_szesc_typow.pdf": {
        "opis": "wieksza paczka: 6 dokumentow roznych typow, 8 stron - test "
                "rozdzielania sasiadujacych jednostronicowych dokumentow",
        "dokumenty": [KWESTIONARIUSZ, UMOWA, ZASWIADCZENIE, ANEKS, WYPOWIEDZENIE, SWIADECTWO],
    },
    "paczka_6_nieznana.pdf": {
        "opis": "wylacznie nierozpoznawalne strony - caly PDF jako jeden dokument "
                "'Nieznany typ dokumentu' z pelna lista powodow",
        "dokumenty": [PISMO_PRZEWODNIE, NOTATKA_ODRECZNA],
    },
}


def write_bundle(path: Path, documents: list[list[tuple[str, str]]]) -> int:
    pdf = FPDF()
    page_count = 0
    for document in documents:
        for header, body in document:
            pdf.add_page()
            page_count += 1
            if header:
                pdf.set_font("Helvetica", "B", 16)
                pdf.cell(0, 12, header, new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 11)
            pdf.multi_cell(0, 8, body)
    pdf.output(str(path))
    return page_count


def main() -> None:
    default_dir = Path(__file__).resolve().parents[2] / "test-data"
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else default_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    for file_name, bundle in BUNDLES.items():
        pages = write_bundle(out_dir / file_name, bundle["dokumenty"])
        print(f"{file_name}: {pages} stron - {bundle['opis']}")

    patterns_path = out_dir / "wzorce_testowe.json"
    patterns_path.write_text(
        json.dumps(PATTERNS, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nWzorce do pola 'patterns': {patterns_path}")
    print(
        "Przyklad:\n"
        '  curl.exe -s -X POST http://localhost:8010/api/split '
        '-F "file=@test-data/paczka_2_wtracenie.pdf" '
        '-F "patterns=<test-data/wzorce_testowe.json"'
    )


if __name__ == "__main__":
    main()
