"""Generuje testowa paczke skanow: jeden PDF z kilkoma dokumentami HR.

Uzycie:
    python scripts/make_test_bundle.py [sciezka_wyjsciowa.pdf]

Wymaga: pip install fpdf2
"""

import sys
from pathlib import Path

from fpdf import FPDF

PAGES = [
    (
        "UMOWA O PRACE",
        "zawarta w dniu 2026-06-01 pomiedzy pracodawca ACME Sp. z o.o. "
        "a pracownikiem Janem Kowalskim. Wynagrodzenie zasadnicze oraz "
        "wymiar czasu pracy okreslono ponizej.",
    ),
    (
        "",
        "Strona 2. Ciag dalszy postanowien umowy. Pozostale warunki "
        "zatrudnienia zgodnie z regulaminem pracy.",
    ),
    (
        "ANEKS DO UMOWY O PRACE",
        "zawarty w dniu 2026-06-15. Strony zgodnie postanawiaja, ze "
        "zmienia sie wysokosc wynagrodzenia. Pozostale warunki umowy "
        "pozostaja bez zmian.",
    ),
    (
        "SWIADECTWO PRACY",
        "Stosunek pracy ustal w dniu 2026-06-30. Okres zatrudnienia: "
        "od 2024-01-01 do 2026-06-30. Wykorzystano urlop wypoczynkowy "
        "w wymiarze 13 dni.",
    ),
    (
        "",
        "Strona 2 swiadectwa pracy. Informacje uzupelniajace i pouczenie "
        "o mozliwosci sprostowania.",
    ),
]


def main() -> None:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("test_bundle.pdf")

    pdf = FPDF()
    for header, body in PAGES:
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 12, header, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 11)
        pdf.multi_cell(0, 8, body)

    pdf.output(str(output))
    print(f"Zapisano {output.resolve()} ({len(PAGES)} stron)")


if __name__ == "__main__":
    main()
