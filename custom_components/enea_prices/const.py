"""Constants for the Enea Ceny integration."""

from homeassistant.const import Platform

# Zdefiniowane przy danych taryfowych; re-eksportowane, bo integracja enea
# importuje je stąd (getattr(const, "AKCYZA", 0.0) – brak nazwy po cichu
# wyzerowałby akcyzę w każdej statystyce kosztów).
from .tariffs import AKCYZA, VAT_RATE  # noqa: F401

# --- Integration identity ---
DOMAIN = "enea_prices"
PLATFORMS = [Platform.SENSOR]
# Integracja licznika (Enea Licznik): jej wykryte ustawienia instalacji podpowiadają
# formularz, a ona sama liczy koszty i rachunek z cen tej integracji.
ENEA_DOMAIN = "enea"

# --- Config entry keys ---
CONF_TARIFF = "tariff"
CONF_PHASES = "phases"
CONF_ANNUAL_KWH = "annual_kwh"
CONF_BILLING_MONTHS = "billing_months"

# Historia cen energii klienta: taryfa URE ↔ oferty rynkowe.  Lista posortowana po dacie;
# każda zmiana obowiązuje do następnej, przed pierwszą – taryfa.  Brak klucza = sama taryfa.
#   ceny z umowy:     {"valid_from": "RRRR-MM-DD", "energy": {strefa: cena z faktury Z AKCYZĄ},
#                      "trade_fee": zł/mies.}
#   powrót do taryfy: {"valid_from": "RRRR-MM-DD"}
CONF_PRICE_CHANGES = "price_changes"
CHANGE_VALID_FROM = "valid_from"
CHANGE_ENERGY = "energy"
CHANGE_TRADE_FEE = "trade_fee"

# --- Defaults ---
DEFAULT_PHASES = "3"
DEFAULT_ANNUAL_KWH = "2000"
DEFAULT_BILLING_MONTHS = "1"

# --- Units ---
UNIT_PRICE = "PLN/kWh"
UNIT_MONTHLY = "PLN"

# --- Statistics ---
# Każdy atrybut tutaj to backfill ok. 35 tys. wierszy na grupę u każdego użytkownika
# przy najbliższym starcie. Brutto celowo brak: koszty brutto dla panelu Energia
# liczy integracja enea z tych samych danych.
ZONE_PRICE_ATTRS: list[tuple[str, str]] = [
    ("price_total", "total"),
    ("price_energy", "energy"),
]

# --- Config flow selectors ---
PHASES_OPTIONS = [
    {"value": "1", "label": "1-fazowa"},
    {"value": "3", "label": "3-fazowa"},
]

ANNUAL_KWH_OPTIONS = [
    {"value": "250", "label": "< 500 kWh/rok"},
    {"value": "850", "label": "500–1200 kWh/rok"},
    {"value": "2000", "label": "1200–2800 kWh/rok"},
    {"value": "5000", "label": "> 2800 kWh/rok"},
]

BILLING_OPTIONS = [
    {"value": "1", "label": "Miesięczne (1 miesiąc)"},
    {"value": "2", "label": "Dwumiesięczne (2 miesiące)"},
    {"value": "6", "label": "Półroczne (6 miesięcy)"},
    {"value": "12", "label": "Roczne (12 miesięcy)"},
]
