# Slad przy doklejaniu po powinowactwie fraz - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Doklejenie strony do biezacego dokumentu na podstawie trafionej frazy ma
zostawiac slad (`phrase_continuation:<fraza>(<strony>)` w `signals`), bez zmiany
jakiejkolwiek decyzji o podziale.

**Architecture:** Dwie warstwy. `RuleBasedClassifier` przestaje tylko LICZYC
trafione frazy i zaczyna je ZBIERAC - `PageClassification.phrase_affinities`
zmienia typ z `set[str]` na `dict[str, list[str]]` (typ dokumentu na frazy).
`ClassificationPipeline` gromadzi je per segment w `phrase_continuations`
(fraza na liste stron) i formatuje do `signals` przy budowie `DetectedDocument`.

**Tech Stack:** Python 3.11+, pytest, pydantic. Bez nowych zaleznosci.

**Spec:** `docs/superpowers/specs/2026-07-26-phrase-affinity-trace-design.md`

## Global Constraints

- **Niezmiennik nadrzedny: zero zmian w decyzjach.** Segmentacja,
  `requiresReview`, `confidence`, `removedPages` i `warnings` musza pozostac
  identyczne dla kazdego wejscia. Wszystkie istniejace testy segmentacji
  przechodza **bez modyfikacji**. Jedyne dozwolone zmiany w istniejacych testach
  to trzy asercje na `phrase_affinities` w `test_rule_classifier.py` (Task 1),
  wymuszone zmiana typu.
- **Format sygnalu:** `phrase_continuation:<fraza>(<strona>,<strona>,...)` -
  bez spacji po przecinku, frazy w kolejnosci pierwszego wystapienia, strony
  rosnaco.
- **Fraza w oryginalnym brzmieniu ze slownika** - nie znormalizowana
  (`wynagrodzenie`, nie `WYNAGRODZENIE`).
- **Bez zmian w kontrakcie i w C#.** `signals` juz jest `list[str]` w
  `DetectedDocument` i juz trafia do komentarza dziecka. Nowa paczka pluginu
  NIE jest potrzebna.
- **Komentarze w kodzie po polsku bez znakow diakrytycznych** (konwencja
  `splitter/src/`). README uzywa polskich znakow - tam je zachowac.
- **Katalog roboczy dla wszystkich komend:** `splitter/`.

## File Structure

| Plik | Odpowiedzialnosc | Zmiana |
|---|---|---|
| `splitter/src/webcon_pdf_splitter/classification/rules.py` | dopasowanie regulowe strony do wzorcow | `phrase_affinities` na slownik; zbieranie fraz zamiast liczenia |
| `splitter/src/webcon_pdf_splitter/classification/pipeline.py` | segmentacja stron w dokumenty | gromadzenie `phrase_continuations` per segment; formatowanie do `signals`; wzbogacenie logu |
| `splitter/tests/test_rule_classifier.py` | testy warstwy regulowej | 4 nowe testy + 3 asercje przeniesione na slownik |
| `splitter/tests/test_pipeline.py` | testy segmentacji | 6 nowych testow |
| `README.md` | dokumentacja | 3 wzmianki o nowym sygnale |

---

### Task 1: `phrase_affinities` niesie frazy, nie tylko typy

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/classification/rules.py:8-16` (dataclass), `:45-110` (`classify_page`)
- Test: `splitter/tests/test_rule_classifier.py`

**Interfaces:**
- Consumes: nic z wczesniejszych zadan (pierwsze zadanie).
- Produces: `PageClassification.phrase_affinities: dict[str, list[str]]` -
  klucz to `document_type` wzorca, wartosc to lista fraz w oryginalnym brzmieniu,
  ktore trafily w tekst strony, bez duplikatow, w kolejnosci ze slownika.
  Typy bez ani jednego trafienia **nie maja klucza**. Task 2 czyta
  `page.phrase_affinities[current.document_type]`.

- [ ] **Step 1: Write the failing tests**

Dopisz na koncu `splitter/tests/test_rule_classifier.py`:

```python
def test_phrase_affinities_carry_matched_phrases():
    classifier = RuleBasedClassifier(
        patterns=[
            DocumentPattern("Umowa o prace", "UMOWA O PRACE", ["pracodawca"], [], 1.0, True),
        ]
    )

    result = classifier.classify_page("dalszy ciag: pracodawca zapewnia...", page_number=2)

    assert result.phrase_affinities == {"Umowa o prace": ["pracodawca"]}


def test_phrase_affinities_carry_every_matched_phrase_in_pattern_order():
    classifier = RuleBasedClassifier(
        patterns=[
            DocumentPattern(
                "Umowa o prace", "UMOWA O PRACE", ["pracodawca", "wynagrodzenie"], [], 1.0, True
            ),
        ]
    )

    result = classifier.classify_page(
        "wynagrodzenie wyplaca pracodawca w terminie", page_number=2
    )

    assert result.phrase_affinities == {"Umowa o prace": ["pracodawca", "wynagrodzenie"]}


def test_patterns_sharing_document_type_merge_their_phrases():
    # slownik dopuszcza kilka wierszy na ten sam typ (rozne naglowki);
    # frazy musza sie sumowac, a nie nadpisywac
    classifier = RuleBasedClassifier(
        patterns=[
            DocumentPattern("Umowa o prace", "UMOWA O PRACE", ["pracodawca"], [], 1.0, True),
            DocumentPattern("Umowa o prace", "UMOWA ZLECENIA", ["zleceniobiorca"], [], 1.0, True),
        ]
    )

    result = classifier.classify_page(
        "strony: pracodawca oraz zleceniobiorca", page_number=2
    )

    assert result.phrase_affinities == {"Umowa o prace": ["pracodawca", "zleceniobiorca"]}


def test_phrase_repeated_across_patterns_of_one_type_is_listed_once():
    classifier = RuleBasedClassifier(
        patterns=[
            DocumentPattern("Umowa o prace", "UMOWA O PRACE", ["pracodawca"], [], 1.0, True),
            DocumentPattern("Umowa o prace", "UMOWA ZLECENIA", ["pracodawca"], [], 1.0, True),
        ]
    )

    result = classifier.classify_page("pracodawca oswiadcza, ze...", page_number=2)

    assert result.phrase_affinities == {"Umowa o prace": ["pracodawca"]}


def test_header_plus_two_phrases_at_weight_one_reaches_full_confidence():
    # regresja punktacji: zbieranie fraz nie moze zmienic sposobu liczenia
    # phrase_hits (0.80 naglowek + 2 x 0.10 frazy = 1.00)
    classifier = RuleBasedClassifier(
        patterns=[
            DocumentPattern(
                "Umowa o prace", "UMOWA O PRACE", ["pracodawca", "wynagrodzenie"], [], 1.0, True
            ),
        ]
    )

    result = classifier.classify_page(
        "UMOWA O PRACE zawarta z pracodawca, wynagrodzenie zasadnicze", page_number=1
    )

    assert result.confidence == 1.0
    assert "phrase_hits:2" in result.signals
```

Nastepnie zamien trzy istniejace asercje na slownikowe:

- `splitter/tests/test_rule_classifier.py:139` - z
  `assert result.phrase_affinities == {"Umowa o prace"}` na
  `assert result.phrase_affinities == {"Umowa o prace": ["pracodawca"]}`
- `splitter/tests/test_rule_classifier.py:163` - z
  `assert result.phrase_affinities == {"Umowa o prace"}` na
  `assert result.phrase_affinities == {"Umowa o prace": ["pracodawca"]}`
- `splitter/tests/test_rule_classifier.py:175` - z
  `assert result.phrase_affinities == set()` na
  `assert result.phrase_affinities == {}`

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_rule_classifier.py -v`
Expected: FAIL - nowe testy i trzy zmienione asercje wywalaja sie na porownaniu
zbioru ze slownikiem, np. `AssertionError: assert {'Umowa o prace'} == {'Umowa o prace': ['pracodawca']}`.
Test `test_header_plus_two_phrases_at_weight_one_reaches_full_confidence` moze
juz przechodzic - to poprawne, jest strażnikiem regresji.

- [ ] **Step 3: Zmien typ pola w `PageClassification`**

W `splitter/src/webcon_pdf_splitter/classification/rules.py` zamien:

```python
@dataclass(frozen=True)
class PageClassification:
    page_number: int
    is_first_page: bool
    document_type: str
    confidence: float
    signals: list[str] = field(default_factory=list)
    phrase_affinities: set[str] = field(default_factory=set)
```

na:

```python
@dataclass(frozen=True)
class PageClassification:
    page_number: int
    is_first_page: bool
    document_type: str
    confidence: float
    signals: list[str] = field(default_factory=list)
    # typ dokumentu -> frazy, ktore trafily, w oryginalnym brzmieniu ze slownika.
    # Sam numer strony nie mowi operatorowi, ktora pozycje slownika poprawic;
    # dopiero fraza wskazuje wiersz do zmiany.
    phrase_affinities: dict[str, list[str]] = field(default_factory=dict)
```

- [ ] **Step 4: Zbieraj frazy zamiast je liczyc**

W tym samym pliku, w `classify_page`, zamien:

```python
        best: PageClassification | None = None
        affinities: set[str] = set()
```

na:

```python
        best: PageClassification | None = None
        affinities: dict[str, list[str]] = {}
```

Nastepnie zamien:

```python
            header_match = fold_ocr_digits(header) in header_zone
            phrase_hits = sum(
                1 for phrase in pattern.phrases if self._normalize(phrase) in normalized
            )
            excluded_hit = any(
                self._normalize(phrase) in normalized for phrase in pattern.excluded_phrases
            )

            if excluded_hit:
                continue

            if phrase_hits:
                affinities.add(pattern.document_type)
```

na:

```python
            header_match = fold_ocr_digits(header) in header_zone
            matched_phrases = [
                phrase for phrase in pattern.phrases if self._normalize(phrase) in normalized
            ]
            phrase_hits = len(matched_phrases)
            excluded_hit = any(
                self._normalize(phrase) in normalized for phrase in pattern.excluded_phrases
            )

            if excluded_hit:
                continue

            if matched_phrases:
                # kilka wierszy slownika moze dzielic ten sam typ (rozne
                # naglowki) - frazy sumujemy, nie nadpisujemy; duplikaty
                # odpadaja, zeby ta sama fraza nie pojawila sie dwa razy
                known = affinities.setdefault(pattern.document_type, [])
                known.extend(phrase for phrase in matched_phrases if phrase not in known)
```

Reszta metody (punktacja, `best`, oba `return`) zostaje **bez zmian** -
`phrase_affinities=affinities` dziala tak samo dla slownika.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_rule_classifier.py -v`
Expected: PASS - wszystkie testy pliku.

- [ ] **Step 6: Uruchom pelny zestaw - nic sie nie zepsulo**

Run: `python -m pytest -q`
Expected: PASS. Baza przed zmiana to 227 passed + 2 skipped; po Task 1 ma byc
232 passed + 2 skipped (5 nowych testow). Zero failed.

Jesli cokolwiek w `test_pipeline.py` failuje, to znaczy, ze `in` albo `sorted()`
na `phrase_affinities` zachowuje sie inaczej niz zakladano - **zatrzymaj sie
i zglos**, nie obchodz tego zmiana testu pipeline'u.

- [ ] **Step 7: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/classification/rules.py splitter/tests/test_rule_classifier.py
git commit -m "feat(splitter): phrase_affinities niesie trafione frazy, nie tylko typy"
```

---

### Task 2: Sygnal `phrase_continuation` na dokumencie

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/classification/pipeline.py:22-31` (`_Segment`), `:123-130` (galaz kontynuacji), `:221-245` (budowa `DetectedDocument`)
- Test: `splitter/tests/test_pipeline.py`
- Modify: `README.md:171-172`, `README.md:225`, `README.md:413`

**Interfaces:**
- Consumes: `PageClassification.phrase_affinities: dict[str, list[str]]` z Task 1.
- Produces: wpisy w `DetectedDocument.signals` w formacie
  `phrase_continuation:<fraza>(<strony przecinkami>)`. Zadne pozostale pole
  `DetectedDocument` sie nie zmienia.

- [ ] **Step 1: Write the failing tests**

Dopisz na koncu `splitter/tests/test_pipeline.py`:

```python
def test_phrase_continuation_leaves_a_signal():
    result = _make_pipeline().split_pages(
        "scan.pdf",
        ["UMOWA O PRACE zawarta z pracodawca", "wynagrodzenie zasadnicze wynosi"],
    )

    doc = result.documents[0]
    assert (doc.startPage, doc.endPage) == (1, 2)
    assert "phrase_continuation:wynagrodzenie(2)" in doc.signals


def test_phrase_continuation_groups_pages_under_one_phrase():
    result = _make_pipeline().split_pages(
        "scan.pdf",
        [
            "UMOWA O PRACE zawarta z pracodawca",
            "wynagrodzenie zasadnicze wynosi",
            "wynagrodzenie platne do 10 dnia",
            "wynagrodzenie moze byc zmienione",
        ],
    )

    doc = result.documents[0]
    traces = [s for s in doc.signals if s.startswith("phrase_continuation:")]
    assert traces == ["phrase_continuation:wynagrodzenie(2,3,4)"]


def test_phrase_continuation_lists_each_phrase_separately():
    result = _make_pipeline().split_pages(
        "scan.pdf",
        [
            "UMOWA O PRACE zawarta z pracodawca",
            "wynagrodzenie zasadnicze wynosi",
            "pracodawca zapewnia szkolenie",
        ],
    )

    doc = result.documents[0]
    traces = [s for s in doc.signals if s.startswith("phrase_continuation:")]
    # kolejnosc pierwszego wystapienia: wynagrodzenie (str. 2), pracodawca (str. 3)
    assert traces == [
        "phrase_continuation:wynagrodzenie(2)",
        "phrase_continuation:pracodawca(3)",
    ]


def test_phrase_continuation_does_not_force_review():
    # STRAZNIK NIEZMIENNIKA: slad jest zapisem, nie decyzja
    result = _make_pipeline().split_pages(
        "scan.pdf",
        ["UMOWA O PRACE zawarta z pracodawca", "wynagrodzenie zasadnicze wynosi"],
    )

    doc = result.documents[0]
    assert doc.requiresReview is False
    assert doc.reviewReasons == []
    assert result.warnings == []
    assert result.status == "completed"


def test_document_without_phrase_continuation_has_no_such_signal():
    result = _make_pipeline().split_pages(
        "scan.pdf",
        ["UMOWA O PRACE zawarta z pracodawca"],
    )

    doc = result.documents[0]
    assert [s for s in doc.signals if s.startswith("phrase_continuation:")] == []


def test_phrase_continuation_signal_coexists_with_glued_unknown_page():
    result = _make_pipeline().split_pages(
        "scan.pdf",
        [
            "UMOWA O PRACE zawarta z pracodawca",
            "wynagrodzenie zasadnicze wynosi",
            "zupelnie obce pismo przewodnie",
            "SWIADECTWO PRACY okres zatrudnienia",
        ],
    )

    # ten sam podzial co przed zmiana - por. test_unmatched_middle_page_is_glued_and_flagged_without_llm
    assert [(d.documentType, d.startPage, d.endPage) for d in result.documents] == [
        ("Umowa o prace", 1, 3),
        ("Swiadectwo pracy", 4, 4),
    ]
    umowa = result.documents[0]
    assert "phrase_continuation:wynagrodzenie(2)" in umowa.signals
    assert "glued_unknown_page:3" in umowa.signals
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_pipeline.py -v -k phrase_continuation`
Expected: FAIL - piec testow na brakujacym sygnale (np.
`assert 'phrase_continuation:wynagrodzenie(2)' in ['header_match:UMOWA O PRACE', 'phrase_hits:1']`).
`test_document_without_phrase_continuation_has_no_such_signal` przechodzi juz
teraz - to poprawne, pilnuje braku smieciowych sygnalow.

- [ ] **Step 3: Dodaj pole gromadzace do `_Segment`**

W `splitter/src/webcon_pdf_splitter/classification/pipeline.py` zamien:

```python
@dataclass
class _Segment:
    document_type: str
    confidence: float
    signals: list[str]
    start_page: int
    end_page: int
    known: bool
    forced_review: bool = False
    unmatched_pages: list[_UnmatchedPage] = field(default_factory=list)
```

na:

```python
@dataclass
class _Segment:
    document_type: str
    confidence: float
    signals: list[str]
    start_page: int
    end_page: int
    known: bool
    forced_review: bool = False
    unmatched_pages: list[_UnmatchedPage] = field(default_factory=list)
    # fraza -> strony, ktore ta fraza przykleila do tego segmentu
    phrase_continuations: dict[str, list[int]] = field(default_factory=dict)
```

- [ ] **Step 4: Zbieraj slad w galezi kontynuacji i wzbogac log**

W tym samym pliku, w `split_pages`, zamien:

```python
            if current is not None and current.known and current.document_type in page.phrase_affinities:
                current.end_page = page_number
                logger.info(
                    "Strona %s: kontynuacja '%s' (dopasowanie fraz)",
                    page_number,
                    current.document_type,
                )
                continue
```

na:

```python
            if current is not None and current.known and current.document_type in page.phrase_affinities:
                current.end_page = page_number
                # Jedyna sciezka podzialu, ktora do niedawna nie zostawiala
                # zadnego sladu. Strona obcego dokumentu potrafi tu wsiaknac
                # w biezacy przez jedna generyczna fraze ("pracownik"),
                # bez LLM i bez requiresReview - bez zapisu operator nie ma
                # jak tego zobaczyc inaczej niz czytajac PDF.
                matched_phrases = page.phrase_affinities[current.document_type]
                for phrase in matched_phrases:
                    current.phrase_continuations.setdefault(phrase, []).append(page_number)
                logger.info(
                    "Strona %s: kontynuacja '%s' (dopasowanie fraz: %s)",
                    page_number,
                    current.document_type,
                    ", ".join(matched_phrases),
                )
                continue
```

- [ ] **Step 5: Formatuj slad do `signals`**

W tym samym pliku dodaj funkcje modulowa tuz pod definicja klasy `_Segment`
(czyli przed `class ClassificationPipeline`):

```python
def _phrase_continuation_signals(segment: _Segment) -> list[str]:
    """Slad po stronach doklejonych na podstawie trafionej frazy.

    Grupowanie po FRAZIE, nie po stronie: liczba wpisow jest wtedy ograniczona
    liczba fraz typu w slowniku (typowo kilka), a nie dlugoscia dokumentu -
    30-stronicowa umowa nie zamienia komentarza dziecka w sciane tekstu.
    Fraza jest tez jednostka, ktora operator realnie poprawia w slowniku;
    sam numer strony nie wskazuje, co zmienic.
    """
    return [
        f"phrase_continuation:{phrase}({','.join(str(page) for page in pages)})"
        for phrase, pages in segment.phrase_continuations.items()
    ]
```

Nastepnie w petli budujacej dokumenty zamien:

```python
                    signals=segment.signals,
```

na:

```python
                    signals=segment.signals + _phrase_continuation_signals(segment),
```

Uwaga: `segment.signals + [...]` tworzy **nowa** liste. Nie uzywaj
`segment.signals.extend(...)` - `signals` segmentu to ta sama lista, ktora
`PageClassification` zwrocil dla strony naglowkowej, i jest mutowana w innym
miejscu (`glued_unknown_page`).

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: PASS - caly plik, wlacznie z istniejacymi testami segmentacji.

Sprawdz w wyniku dwa istniejace testy, ktore sa tu strażnikami niezmiennika
i musza przejsc **bez zadnej modyfikacji**:

- `test_llm_not_called_for_affine_continuation_pages` - strona doklejona po
  frazie nadal NIE wola LLM (slad nie moze zmienic sciezki sterowania);
- `test_unmatched_middle_page_is_glued_and_flagged_without_llm` - podzial
  i `warnings` bez zmian mimo nowego sygnalu na tym samym dokumencie.

- [ ] **Step 7: Uruchom pelny zestaw**

Run: `python -m pytest -q`
Expected: PASS, 238 passed + 2 skipped (232 po Task 1 + 6 nowych). Zero failed.

- [ ] **Step 8: Zaktualizuj README**

W `README.md` (uwaga: ten plik uzywa polskich znakow diakrytycznych) zamien:

```markdown
2. **≥1 fraza typu bieżącego dokumentu** (powinowactwo) → kontynuacja bieżącego
   dokumentu (bez LLM).
```

na:

```markdown
2. **≥1 fraza typu bieżącego dokumentu** (powinowactwo) → kontynuacja bieżącego
   dokumentu (bez LLM). Ta ścieżka nie podnosi `requiresReview`, ale zostawia
   ślad `phrase_continuation:<fraza>(<strony>)` w `signals` — po nim widać,
   która pozycja słownika przykleiła stronę, gdy okaże się zbyt generyczna.
```

Nastepnie zamien:

```markdown
`reviewReasons` (lista po polsku) zawiera m.in.: nierozpoznany typ, strona bez
tekstu, strona doklejona bez dopasowania (z pasującymi frazami innych typów i
propozycją LLM), odrzucony werdykt niespójny, pewność poniżej progu. `signals`
niosą ślad techniczny (`header_match:...`, `phrase_hits:N`, `glued_unknown_page:N`,
`llm:<kod>`).
```

na:

```markdown
`reviewReasons` (lista po polsku) zawiera m.in.: nierozpoznany typ, strona bez
tekstu, strona doklejona bez dopasowania (z pasującymi frazami innych typów i
propozycją LLM), odrzucony werdykt niespójny, pewność poniżej progu. `signals`
niosą ślad techniczny (`header_match:...`, `phrase_hits:N`, `glued_unknown_page:N`,
`phrase_continuation:<fraza>(<strony>)`, `llm:<kod>`).
```

Nastepnie w tabeli kontraktu zamien:

```markdown
| `signals` | ślad techniczny decyzji klasyfikacji (`header_match:…`, `phrase_hits:…`, `llm:…`) — akcja dopisuje go do komentarza dokumentu |
```

na:

```markdown
| `signals` | ślad techniczny decyzji klasyfikacji (`header_match:…`, `phrase_hits:…`, `phrase_continuation:…`, `llm:…`) — akcja dopisuje go do komentarza dokumentu |
```

- [ ] **Step 9: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/classification/pipeline.py splitter/tests/test_pipeline.py README.md
git commit -m "feat(splitter): slad phrase_continuation przy doklejaniu po frazach"
```

---

## Weryfikacja koncowa

- [ ] **Pelny zestaw testow**

Run: `python -m pytest -q` w `splitter/`
Expected: 238 passed, 2 skipped (skipped = testy tesseract bez binarki na
Windows). Zero failed.

- [ ] **Reczny przeglad niezmiennika**

Run: `git diff main --stat -- splitter/tests/`
Expected: w `test_pipeline.py` **wylacznie dopisane** linie (zero usunietych);
w `test_rule_classifier.py` dopisane linie plus dokladnie trzy zmienione
asercje `phrase_affinities`. Kazda inna zmieniona linia w istniejacych testach
oznacza zlamany niezmiennik - zatrzymaj sie i zglos.

- [ ] **Brak zmian w C#**

Run: `git diff main --stat -- webcon-action/`
Expected: pusto.
