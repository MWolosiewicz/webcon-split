from webcon_pdf_splitter.ocr import alnum_count


def test_alnum_count_ignores_whitespace_and_punctuation():
    assert alnum_count("   \n\t  ") == 0
    assert alnum_count("... --- ,,, ;") == 0


def test_alnum_count_counts_letters_and_digits():
    # "Umowa 2024" -> U m o w a 2 0 2 4 = 9
    assert alnum_count("Umowa 2024") == 9


def test_alnum_count_counts_polish_letters():
    # str.isalnum() jest swiadome Unicode: polskie litery licza sie
    assert alnum_count("zazolc gesla jazn") == 15
    assert alnum_count("łódź") == 4
