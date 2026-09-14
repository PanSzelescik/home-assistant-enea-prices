# Decyzje Prezesa URE – taryfy sprzedaży Enea S.A. dla grup G

Pełne teksty decyzji zatwierdzających taryfę Enea S.A. dla odbiorców z grup taryfowych G,
pobrane z [BIP URE](https://bip.ure.gov.pl/).

| Plik | Znak decyzji | Data | Czego dotyczy |
|------|--------------|------|---------------|
| [2019-12-30_taryfa-G-2020.pdf](2019-12-30_taryfa-G-2020.pdf) | DRE.WRE.4211.77.18.2019.KKu | 30.12.2019 | taryfa na okres do 31.03.2020 |
| [2020-12-09_taryfa-G-2021.pdf](2020-12-09_taryfa-G-2021.pdf) | DRE.WRE.4211.57.7.2020.KKu | 09.12.2020 | taryfa od 01.01.2021 |
| [2021-12-17_taryfa-G-2022.pdf](2021-12-17_taryfa-G-2022.pdf) | DRE.WRE.4211.63.8.2021.KKu | 17.12.2021 | taryfa od 01.01.2022 |
| [2022-02-15_zmiana-taryfy-G-2022.pdf](2022-02-15_zmiana-taryfy-G-2022.pdf) | DRE.WRE.4211.3.7.2022.KKu | 15.02.2022 | zmiana taryfy 2022 |
| [2022-12-17_taryfa-G-2023.pdf](2022-12-17_taryfa-G-2023.pdf) | DRE.WRE.4211.71.9.2022.MBa | 17.12.2022 | taryfa od 01.01.2023 |
| [2023-10-18_zmiana-taryfy-G-2023.pdf](2023-10-18_zmiana-taryfy-G-2023.pdf) | DRE.WRE.4211.48.3.2023.AKr3 | 18.10.2023 | podwyższenie limitów zużycia objętych ceną z 2022 r. |
| [2023-12-15_taryfa-G-2024.pdf](2023-12-15_taryfa-G-2024.pdf) | DRE.WRE.4211.61.13.2023.AKr3 | 15.12.2023 | taryfa od 01.01.2024 |
| [2024-01-30_zmiana-taryfy-G-2024-odbiorcy-uprawnieni.pdf](2024-01-30_zmiana-taryfy-G-2024-odbiorcy-uprawnieni.pdf) | DRE.WRE.4211.10.2.2024.AKr3 | 30.01.2024 | ceny dla odbiorców uprawnionych 01.01–30.06.2024 |
| [2024-06-28_zmiana-taryfy-G-do-2025-12-31.pdf](2024-06-28_zmiana-taryfy-G-do-2025-12-31.pdf) | DRE.WRE.4211.31.11.2024.JTr | 28.06.2024 | zmiana taryfy, obowiązuje do 31.12.2025 |

## Czego w tych plikach **nie ma**

To są **sentencje decyzji wraz z uzasadnieniem, bez załącznika z cennikiem**. Tabele cen
(zł/kWh per grupa i strefa) Enea publikuje osobno, w treści taryfy i w dokumentach
„Dodatkowa informacja ENEA S.A. o cenach BRUTTO" na enea.pl. Decyzje pozwalają ustalić
znak, datę i okres obowiązywania — nie same stawki.

Dotyczy to również dystrybucji: stawki sieciowe, jakościowa, abonament i opłaty stałe
pochodzą z taryfy **Enea Operator**, zatwierdzanej odrębnymi decyzjami, których tu nie ma.

## Dlaczego tabela zaczyna się w 2025 r.

Model danych integracji (`ZonePricing` — jedna cena na strefę w danym okresie) odwzorowuje
wyłącznie mrożenia oparte na **jednej cenie maksymalnej bez limitu zużycia**, czyli okres
od 1 lipca 2024 r. wzwyż.

Wcześniejsze mechanizmy osłonowe były oparte na **limitach zużycia**, czego ten model nie
wyraża:

- **2023** – do limitu (2000 / 2600 / 3000 kWh, zależnie od uprawnień odbiorcy) obowiązywała
  cena z taryfy na 2022 r.; powyżej limitu cena bieżąca. Limity podwyższono w trakcie roku
  (decyzja z 18.10.2023).
- **01.01–30.06.2024** – „ceny (…) zawarte w taryfie na dzień 1 stycznia 2022 roku, do 50%
  limitów zużycia określonych w ustawie" (decyzja z 30.01.2024); powyżej limitu cena maksymalna.

Limit jest roczny i narastający, a jego wysokość zależy od oświadczeń odbiorcy (osoba
z niepełnosprawnością, Karta Dużej Rodziny, rolnik). Cena obowiązująca danego dnia zależy więc
od skumulowanego zużycia od początku roku i od indywidualnych uprawnień — tabela stawek
per okres tego nie odda.

Dodatkowo w 2022 r. obowiązywała tarcza antyinflacyjna: obniżony VAT na energię i zerowa
akcyza. `const.py` ma `VAT_RATE` i `AKCYZA` jako stałe, więc ceny brutto liczone przez
integrację `enea` byłyby dla tego roku zawyżone.
