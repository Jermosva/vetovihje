import json
import requests
import os
from dotenv import load_dotenv

# Luetaan .env-tiedoston sisältö käyttöön
load_dotenv()

API_AVAIN = os.getenv("ODDS_API_KEY")

# Mikä sarja haetaan (tunnus sarjalistasta)
SARJA = "icehockey_liiga"

# Osoitteeseen lisätään nyt asetuksia &-merkillä:
# regions = mistä yhtiöistä, markets = mikä vetotyyppi,
# oddsFormat = decimal tarkoittaa tuttuja kertoimia, kuten 2.30
osoite = (
    "https://api.the-odds-api.com/v4/sports/" + SARJA + "/odds/"
    + "?apiKey=" + API_AVAIN
    + "&regions=fi,eu"
    + "&markets=h2h,totals,spreads"
    + "&oddsFormat=decimal"
)

vastaus = requests.get(osoite)
ottelut = vastaus.json()

# Kerros 1: jokainen ottelu
for ottelu in ottelut:
    print()
    print(ottelu["home_team"], "vs", ottelu["away_team"])
    print("Alkaa:", ottelu["commence_time"])

    # Kerros 2: jokainen vetoyhtiö tässä ottelussa
    for yhtio in ottelu["bookmakers"]:

        # Kerros 3: yhtiön markkinat (meillä vain h2h)
        for markkina in yhtio["markets"]:

            maara = len(markkina["outcomes"])

            # Markkinan nimi löytyy "key"-kentästä: h2h, totals tai spreads
            if markkina["key"] == "h2h":
                if maara == 3:
                    tyyppi = "1X2"
                else:
                    tyyppi = "Voittaja"
            elif markkina["key"] == "totals":
                tyyppi = "Yli/alle"
            else:
                tyyppi = "Tasoitus"

            # Lasketaan todennäköisyyksien summa: aloitetaan nollasta
            summa = 0
            for vaihtoehto in markkina["outcomes"]:
                summa = summa + 1 / vaihtoehto["price"]

            # Marginaali prosentteina (summa yli 1 = yhtiön palkkio)
            marginaali = (summa - 1) * 100

            # Kootaan kertoimet yhdelle riville
            kertoimet = ""
            for vaihtoehto in markkina["outcomes"]:
                # Raja ("point") on vain yli/alle- ja tasoitusvedoissa.
                # .get() palauttaa tyhjän tekstin, jos kenttää ei ole, eikä kaada ohjelmaa
                raja = str(vaihtoehto.get("point", ""))
                kertoimet = kertoimet + vaihtoehto["name"] + " " + raja + " " + str(vaihtoehto["price"]) + "  "

            print("   ", tyyppi, "|", yhtio["title"], "|", kertoimet, "| marginaali", round(marginaali, 1), "%")

# Paljonko kiintiötä on jäljellä (tieto tulee vastauksen "otsakkeista")
print()
print("Kiintiötä jäljellä:", vastaus.headers["x-requests-remaining"])

# Tallennetaan ottelut tiedostoon, jotta niitä voi käyttää ilman uutta hakua
with open("ottelut.json", "w", encoding="utf-8") as tiedosto:
    json.dump(ottelut, tiedosto, ensure_ascii=False, indent=2)

print("Tallennettu tiedostoon ottelut.json")