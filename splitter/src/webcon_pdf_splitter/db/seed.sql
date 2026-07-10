-- Startowe typy dokumentow HR i wzorce rozpoznawania.
-- Uruchamiac na bazie WebconPdfSplitter po zastosowaniu schema.sql.
-- Naglowki i frazy sa zapisane bez polskich znakow diakrytycznych,
-- poniewaz klasyfikator normalizuje tekst do ASCII przed dopasowaniem.

SET NOCOUNT ON;

DECLARE @types TABLE (name NVARCHAR(200));

INSERT INTO dbo.document_type (name, auto_accept_threshold)
SELECT v.name, v.threshold
FROM (VALUES
    (N'Umowa o prace', 0.9000),
    (N'Aneks do umowy o prace', 0.9000),
    (N'Umowa zlecenie', 0.9000),
    (N'Wypowiedzenie umowy o prace', 0.9000),
    (N'Swiadectwo pracy', 0.9000),
    (N'Kwestionariusz osobowy', 0.9000),
    (N'Orzeczenie lekarskie', 0.9000),
    (N'Zaswiadczenie o ukonczeniu szkolenia BHP', 0.9000),
    (N'Oswiadczenie PIT-2', 0.9000),
    (N'Zgoda na przetwarzanie danych osobowych', 0.9000)
) AS v(name, threshold)
WHERE NOT EXISTS (SELECT 1 FROM dbo.document_type dt WHERE dt.name = v.name);

INSERT INTO dbo.document_pattern (document_type_id, header, phrases_json, excluded_phrases_json, weight, source)
SELECT dt.document_type_id, p.header, p.phrases, p.excluded, p.weight, N'initial_configuration'
FROM (VALUES
    (N'Umowa o prace',                              N'UMOWA O PRACE',                        N'["pracodawca", "pracownik", "wynagrodzenie", "wymiar czasu pracy"]', N'["aneks", "wypowiedzenie", "rozwiazanie umowy"]', 1.2000),
    (N'Aneks do umowy o prace',                     N'ANEKS DO UMOWY O PRACE',               N'["zmienia sie", "pozostale warunki", "porozumienie stron"]',         N'[]',                                              1.2000),
    (N'Aneks do umowy o prace',                     N'ANEKS DO UMOWY',                       N'["umowy o prace", "zmienia sie"]',                                   N'[]',                                              1.0000),
    (N'Umowa zlecenie',                             N'UMOWA ZLECENIE',                       N'["zleceniodawca", "zleceniobiorca"]',                                 N'[]',                                              1.2000),
    (N'Umowa zlecenie',                             N'UMOWA ZLECENIA',                       N'["zleceniodawca", "zleceniobiorca"]',                                 N'[]',                                              1.2000),
    (N'Wypowiedzenie umowy o prace',                N'WYPOWIEDZENIE UMOWY O PRACE',          N'["okres wypowiedzenia", "rozwiazanie umowy"]',                        N'[]',                                              1.2000),
    (N'Wypowiedzenie umowy o prace',                N'ROZWIAZANIE UMOWY O PRACE',            N'["za wypowiedzeniem", "bez wypowiedzenia", "porozumienie stron"]',    N'[]',                                              1.1000),
    (N'Swiadectwo pracy',                           N'SWIADECTWO PRACY',                     N'["stosunek pracy", "okres zatrudnienia", "urlop wypoczynkowy"]',      N'[]',                                              1.2000),
    (N'Kwestionariusz osobowy',                     N'KWESTIONARIUSZ OSOBOWY',               N'["imie i nazwisko", "data urodzenia", "adres zamieszkania"]',         N'[]',                                              1.2000),
    (N'Orzeczenie lekarskie',                       N'ORZECZENIE LEKARSKIE',                 N'["zdolny do pracy", "badania profilaktyczne", "medycyna pracy"]',     N'[]',                                              1.2000),
    (N'Orzeczenie lekarskie',                       N'ZASWIADCZENIE LEKARSKIE',              N'["zdolny do pracy", "przeciwwskazania"]',                              N'[]',                                              1.0000),
    (N'Zaswiadczenie o ukonczeniu szkolenia BHP',   N'ZASWIADCZENIE O UKONCZENIU SZKOLENIA', N'["bezpieczenstwa i higieny pracy", "bhp", "szkolenie okresowe"]',     N'[]',                                              1.1000),
    (N'Zaswiadczenie o ukonczeniu szkolenia BHP',   N'KARTA SZKOLENIA WSTEPNEGO',            N'["instruktaz ogolny", "instruktaz stanowiskowy", "bhp"]',             N'[]',                                              1.2000),
    (N'Oswiadczenie PIT-2',                         N'PIT-2',                                N'["oswiadczenie", "zaliczek na podatek", "kwoty zmniejszajacej"]',     N'[]',                                              1.2000),
    (N'Zgoda na przetwarzanie danych osobowych',    N'ZGODA NA PRZETWARZANIE DANYCH',        N'["danych osobowych", "rodo", "administratorem danych"]',              N'[]',                                              1.2000)
) AS p(type_name, header, phrases, excluded, weight)
JOIN dbo.document_type dt ON dt.name = p.type_name
WHERE NOT EXISTS (
    SELECT 1
    FROM dbo.document_pattern dp
    WHERE dp.document_type_id = dt.document_type_id AND dp.header = p.header
);
