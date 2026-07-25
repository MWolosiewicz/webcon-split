from PIL import Image, ImageDraw

from webcon_pdf_splitter.blank_pages import ink_ratio


def _white(width=500, height=700):
    return Image.new("RGB", (width, height), "white")


def test_ink_ratio_of_white_page_is_zero():
    assert ink_ratio(_white()) == 0.0


def test_ink_ratio_counts_dark_area():
    # po odcieciu 4% marginesu obszar to 460x660 = 303600 px;
    # prostokat 100x100 = 10000 px -> 10000/303600 = 0.0329
    image = _white(500, 700)
    ImageDraw.Draw(image).rectangle([200, 300, 299, 399], fill="black")

    assert 0.032 < ink_ratio(image) < 0.034


def test_ink_ratio_ignores_scanner_edge_after_margin_crop():
    # czarne pasy przy krawedziach (szyba skanera, przekrzywienie) leza
    # w odcinanym marginesie - strona nadal jest pusta
    image = _white(500, 700)
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, 499, 4], fill="black")
    draw.rectangle([0, 0, 4, 699], fill="black")

    assert ink_ratio(image, margin_ratio=0.04) == 0.0


def test_ink_ratio_treats_light_grey_paper_as_blank():
    # papier kremowy/szary: jasniejszy niz prog ciemnosci -> nie jest atramentem
    assert ink_ratio(Image.new("RGB", (500, 700), (230, 230, 230))) == 0.0


def test_ink_ratio_of_speckle_stays_below_default_threshold():
    # 40 pikseli kurzu -> 40/303600 = 0.00013, ponizej domyslnego progu 0.002
    image = _white(500, 700)
    draw = ImageDraw.Draw(image)
    for x in range(100, 140):
        draw.point((x, 350), fill="black")

    assert 0 < ink_ratio(image) < 0.002
