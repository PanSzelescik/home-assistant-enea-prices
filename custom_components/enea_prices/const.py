"""Constants for the Enea Ceny integration."""

from homeassistant.const import Platform

# --- Integration identity ---
DOMAIN = "enea_prices"
PLATFORMS = [Platform.SENSOR]

# --- Config entry keys ---
CONF_TARIFF = "tariff"
CONF_PHASES = "phases"
CONF_ANNUAL_KWH = "annual_kwh"
CONF_BILLING_MONTHS = "billing_months"

# --- Defaults ---
DEFAULT_PHASES = "3"
DEFAULT_ANNUAL_KWH = "2000"
DEFAULT_BILLING_MONTHS = "1"

# --- Units ---
UNIT_PRICE = "PLN/kWh"
UNIT_MONTHLY = "PLN"

# --- Tax rates ---
VAT_RATE = 0.23
AKCYZA = 0.005  # zł/kWh, podatek akcyzowy na energię elektryczną

# --- Statistics ---
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
