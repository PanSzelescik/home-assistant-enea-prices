# Współtworzenie Enea Ceny

Dzięki, że chcesz pomóc! Ten plik opisuje, jak przygotować zmianę, żeby dało się ją szybko
przejrzeć i wydać.

*In English: issues and pull requests in English are welcome. Run the tests with
`uv run --locked --group dev pytest -q`, cite the URE decision or tariff for every price
you add, write commit messages in English and add a test that fails without your fix.*

## Zanim zaczniesz

- **Błędy i pomysły** zgłaszaj przez szablony w zakładce Issues.
- **Nowe ceny** (taryfa na kolejny rok, zmiana stawek w trakcie roku) to najczęstsza
  potrzebna zmiana — zgłoszenie z linkiem do decyzji Prezesa URE wystarczy, żeby ją dodać.
- **Większą zmianę** (nowa grupa taryfowa, zmiana sposobu liczenia statystyk) najpierw opisz
  w zgłoszeniu — łatwiej ustalić podejście, zanim powstanie kod.

Model danych, strefy, święta i źródła cen są opisane w [`AGENTS.md`](AGENTS.md).

## Środowisko

Potrzebujesz [uv](https://docs.astral.sh/uv/); wersję Pythona (3.14) uv pobierze sam.

```sh
uv sync --locked --group dev
uv run --locked --group dev pytest -q
```

Pokrycie kodu (linie i rozgałęzienia, raport HTML w `htmlcov/index.html`):

```sh
uv run --locked --group dev coverage run -m pytest -q
uv run --locked --group dev coverage report
uv run --locked --group dev coverage html
```

Część testów uruchamia prawdziwy Home Assistant (`tests/ha_instance.py`) z atrapą
statystyk recordera i zegara.

### Testy kontraktu z Enea Licznik

Enea Ceny i [Enea Licznik](https://github.com/PanSzelescik/home-assistant-enea) czytają się
nawzajem po nazwach (atrybuty, klucze wpisów, moduły), bez importów.
`tests/test_enea_contract.py` ładuje prawdziwy kod Enea Licznik z checkoutu:

- domyślnie z katalogu `home-assistant-enea` obok tego repo,
- albo ze ścieżki w zmiennej `ENEA_PATH`.

Bez checkoutu te testy są pomijane. CI zawsze je uruchamia na gałęzi `master` Enea Licznik,
a lustrzane testy w Enea Licznik — na `master` tego repo. Zmiana czegoś, co czyta druga
integracja (nazwy grup i stref, klucze wpisu, `AKCYZA`, atrybuty `runtime_data`), wymaga
więc pull requestów w obu repo; opisz w nich, w jakiej kolejności je scalić.

## Ceny i taryfy

- Każda cena ma źródło: decyzję Prezesa URE (znak i data) lub taryfę Enea S.A. / Enea Operator
  (punkt taryfy). Dopisz je w sekcji „Źródła danych” w [`README.md`](README.md) i w
  [`AGENTS.md`](AGENTS.md), a PDF decyzji taryfy sprzedaży — do
  [`docs/decyzje-ure/`](docs/decyzje-ure/) z wierszem w tamtejszym indeksie.
- Nowy rok lub zmiana stawek to nowy `TariffPeriod` w `periods` grupy w `tariffs.py`
  (bez nakładania się okresów). Nowa grupa to nowy `TariffGroup` w `TARIFFS`.
- Cenę energii wpisuj netto i bez akcyzy, tak jak w taryfie — `total_brutto` sam dolicza
  `AKCYZA` i VAT.
- Testy `test_tariff_table.py` sprawdzają ciągłość i kształt tabeli — dopisz w nich
  ceny z nowego okresu.

## Kod

- „Teraz” i „dziś” wyłącznie z zegara Home Assistant: `dt_util.now()` — nigdy `date.today()`
  ani `datetime.now()`. Pilnuje tego `tests/test_clock.py`.
- Docstring dla każdej nowej funkcji, metody i klasy.
- Minimalna wersja `holidays` musi być taka sama w `manifest.json` i `pyproject.toml`
  (pilnuje `tests/test_requirement_pins.py`).
- Teksty interfejsu zmieniaj w obu tłumaczeniach: `translations/pl.json` i `translations/en.json`.

## Testy

- Poprawka błędu przychodzi z testem, który bez niej nie przechodzi.
- Nowe zachowanie testuj tam, gdzie widzi je użytkownik: config flow i scenariusze
  w działającym Home Assistant (`test_config_flow.py`, `test_scenarios.py`). Tabelę taryf
  i harmonogram stref testuj bezpośrednio.
- Testy muszą przechodzić w każdej strefie czasowej procesu — Home Assistant bez `TZ` działa
  w UTC, a liczy dni po polsku.

## Commity i pull requesty

- Commity po angielsku, w trybie rozkazującym, opisujące zachowanie, np.
  `Read today from Home Assistant's clock`. Jeden commit — jedna logiczna zmiana.
- Pull request kieruj do `master`. W opisie: co się zmienia i dlaczego (*Summary*) oraz jak
  zostało sprawdzone (*Test plan*).
- Przed scaleniem muszą przejść workflow **Tests**, **Validate HACS** i **Validate with hassfest**.
- Nie podbijaj wersji w `manifest.json` ani `pyproject.toml` — wydania przygotowuje opiekun.
