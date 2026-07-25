from PIL import Image, ImageDraw

from webcon_pdf_splitter.blank_pages import BlankPageDetector, ink_ratio


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


def _pdf_with_pages(tmp_path, images, name="scan.pdf"):
    path = tmp_path / name
    images[0].save(str(path), "PDF", save_all=True, append_images=images[1:])
    return str(path)


def test_detects_blank_page_and_keeps_page_with_content(tmp_path):
    blank = _white(500, 700)
    card = _white(500, 700)
    # kartonik dowodu osobistego: ciemny prostokat na srodku strony
    ImageDraw.Draw(card).rectangle([100, 250, 400, 450], fill="black")
    path = _pdf_with_pages(tmp_path, [blank, card])

    detector = BlankPageDetector(dpi=60, max_ink_ratio=0.002)

    assert detector.detect_blank_pages(path, [0, 1]) == {0}


def test_empty_index_list_returns_empty_set():
    assert BlankPageDetector().detect_blank_pages("nieistniejacy.pdf", []) == set()


def test_unreadable_pdf_yields_no_blank_pages(tmp_path):
    # zasada bezpieczenstwa: nie umiemy ocenic -> zadna strona nie jest pusta
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"to nie jest plik pdf")

    assert BlankPageDetector().detect_blank_pages(str(path), [0]) == set()


def test_logs_coverage_for_page_with_content(tmp_path, caplog):
    import logging

    caplog.set_level(logging.INFO, logger="webcon_pdf_splitter.blank_pages")
    card = _white(500, 700)
    ImageDraw.Draw(card).rectangle([100, 250, 400, 450], fill="black")
    path = _pdf_with_pages(tmp_path, [card], name="dowod.pdf")

    BlankPageDetector(dpi=60, max_ink_ratio=0.002).detect_blank_pages(path, [0])

    messages = [record.getMessage() for record in caplog.records]
    assert any("ma tresc (mimo braku tekstu)" in message for message in messages)
