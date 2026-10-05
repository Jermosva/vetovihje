import json
import os
import requests
from dotenv import load_dotenv

load_dotenv()
API_AVAIN = os.getenv("ODDS_API_KEY")
KIRJANPITO = "kirjanpito.json"

# Sarjan nimi kirjanpidossa -> sarjan tunnus API:ssa
SARJATUNNUKSET = {
    "NHL": "icehockey_nhl",
    "SHL": "icehockey_sweden_hockey_league",
}

with open(KIRJANPITO, "r", encoding="utf-8") as tiedosto:
    kirjanpito = json.load(tiedosto)
tarvittavat = []
for veto in kirjanpito:
    # .get() koska vanhoilta Liiga-vedoilta puuttuu "sarja"-kenttä
    sarja = veto.get("sarja")
    if veto["tila"] == "avoin" and sarja in SARJATUNNUKSET:
        tunnus = SARJATUNNUKSET[sarja]
        if tunnus not in tarvittavat:
            tarvittavat.append(tunnus)
# Tallennetaan päättyneet ottelut sanakirjaan: ottelun id -> ottelun tiedot
tulokset = {}

for tunnus in tarvittavat:
    # daysFrom=3 = hae myös enintään 3 päivää sitten päättyneet ottelut
    osoite = (
        "https://api.the-odds-api.com/v4/sports/" + tunnus + "/scores/"
        + "?apiKey=" + API_AVAIN
        + "&daysFrom=3"
    )
    vastaus = requests.get(osoite)

    if vastaus.status_code != 200:
        print("VIRHE:", tunnus, vastaus.status_code, vastaus.text)
        continue

    for ottelu in vastaus.json():
        if ottelu["completed"]:          # True = ottelu on päättynyt
            tulokset[ottelu["id"]] = ottelu

print("Haettu", len(tulokset), "päättynyttä ottelua")
def ratkaise(veto, ottelu):
    # Maalit joukkueittain: joukkueen nimi -> maalit
    maalit = {}
    for rivi in ottelu["scores"]:
        maalit[rivi["name"]] = int(rivi["score"])

    koti = maalit[ottelu["home_team"]]
    vieras = maalit[ottelu["away_team"]]
    ero = abs(koti - vieras)
    yhteensa = koti + vieras

    tyyppi = veto["tyyppi"]
    valinta = veto["valinta"]

    # Yhden maalin ero voi tarkoittaa jatkoaikaa -> vain Voittaja on varma
    if ero <= 1 and tyyppi != "Voittaja":
        return "tarkista"

    # Voittaja ja 1X2
    if tyyppi == "Voittaja" or tyyppi == "1X2":
        if koti > vieras:
            voittaja = ottelu["home_team"]
        else:
            voittaja = ottelu["away_team"]

        if valinta == voittaja:
            return "osui"
        return "ei osunut"      # myös "Draw", koska ero oli vähintään 2

    # Yli/alle, esim. "Yli/alle 5.5"
    if tyyppi.startswith("Yli/alle"):
        raja = float(tyyppi.split(" ")[1])
        if yhteensa == raja:
            return "mitätöity"   # tasaraja, esim. 6.0 ja 6 maalia -> panos palautetaan
        if valinta == "Over" and yhteensa > raja:
            return "osui"
        if valinta == "Under" and yhteensa < raja:
            return "osui"
        return "ei osunut"

    # Tasoitus, esim. "Tasoitus koti -1.5"
    if tyyppi.startswith("Tasoitus"):
        raja = float(tyyppi.split(" ")[2])   # kotijoukkueen tasoitus
        if valinta == ottelu["home_team"]:
            tulos = koti + raja - vieras
        else:
            tulos = vieras - raja - koti     # vierasjoukkueella on vastakkainen tasoitus
        if tulos > 0:
            return "osui"
        if tulos == 0:
            return "mitätöity"
        return "ei osunut"

    # Tuntematon vetotyyppi
    return "tarkista"
ratkaistuja = 0

for veto in kirjanpito:
    if veto["tila"] != "avoin":
        continue                  # jo ratkaistu aiemmin
    if veto["id"] not in tulokset:
        continue                  # ottelu ei ole vielä päättynyt

    tila = ratkaise(veto, tulokset[veto["id"]])
    veto["tila"] = tila

    if tila == "osui":
        veto["voitto"] = round(veto["panos"] * veto["kerroin"] - veto["panos"], 2)
    elif tila == "ei osunut":
        veto["voitto"] = -veto["panos"]
    elif tila == "mitätöity":
        veto["voitto"] = 0
    # "tarkista": voittoa ei merkitä, vaan katsot sen itse

    ratkaistuja += 1
    print(veto["ottelu"], "|", veto["tyyppi"], veto["valinta"], "->", tila)
with open(KIRJANPITO, "w", encoding="utf-8") as tiedosto:
    json.dump(kirjanpito, tiedosto, ensure_ascii=False, indent=2)

saldo = 0
pelattuja = 0
osuneita = 0
tarkistettavia = 0
for veto in kirjanpito:
    if "voitto" in veto:
        saldo += veto["voitto"]
        pelattuja += 1
        if veto["tila"] == "osui":
            osuneita += 1
    if veto["tila"] == "tarkista":
        tarkistettavia += 1

print()
print("Odottaa käsin tarkistusta:", tarkistettavia)
print("Nyt ratkaistu:", ratkaistuja)
print("Ratkaistuja vetoja yhteensä:", pelattuja, "| osuneita:", osuneita)
print("Leikkirahasaldo:", round(saldo, 2), "€")