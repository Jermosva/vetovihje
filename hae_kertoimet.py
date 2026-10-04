import json
import os
import requests
from dotenv import load_dotenv

load_dotenv()
API_AVAIN = os.getenv("ODDS_API_KEY")

# Haettavat sarjat: uuden sarjan saa mukaan lisäämällä tunnuksen tähän listaan.
# Tunnukset löytyvät hae_sarjat.py:n tulosteesta.
SARJAT = [
    "icehockey_liiga",
    "icehockey_nhl",
    "icehockey_sweden_hockey_league",
]

ALUEET = "fi,eu,se"
MARKKINAT = "h2h,totals,spreads"

kaikki_ottelut = []

for sarja in SARJAT:
    osoite = (
        "https://api.the-odds-api.com/v4/sports/" + sarja + "/odds/"
        + "?apiKey=" + API_AVAIN
        + "&regions=" + ALUEET
        + "&markets=" + MARKKINAT
        + "&oddsFormat=decimal"
    )

    vastaus = requests.get(osoite)

    # Tilakoodi 200 = "kaikki ok". Muu koodi = jokin meni pieleen
    # (esim. 401 = väärä avain, 422 = sarjalle ei löydy jotain markkinaa).
    if vastaus.status_code != 200:
        print("VIRHE sarjassa", sarja, "- koodi", vastaus.status_code, ":", vastaus.text)
        continue

    ottelut = vastaus.json()
    print(sarja, "-", len(ottelut), "ottelua")

    # extend = lisää kaikki listan alkiot toiseen listaan kerralla
    kaikki_ottelut.extend(ottelut)

with open("ottelut.json", "w", encoding="utf-8") as tiedosto:
    json.dump(kaikki_ottelut, tiedosto, ensure_ascii=False, indent=2)

print()
print("Tallennettu", len(kaikki_ottelut), "ottelua tiedostoon ottelut.json")
print("Kiintiötä jäljellä:", vastaus.headers["x-requests-remaining"])