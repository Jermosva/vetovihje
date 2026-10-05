import json
import os
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
API_AVAIN = os.getenv("ODDS_API_KEY")
KIRJANPITO = "kirjanpito.json"

# Sarjat, joiden tulokset haetaan The Odds API:sta (NHL:lle on oma lähde)
SARJATUNNUKSET = {
    "SHL": "icehockey_sweden_hockey_league",
}
# Liigan kausi nimetään päättymisvuoden mukaan: 2026–27 = 2027
LIIGA_KAUSI = 2027
# Kerroinpalvelun nimi -> liiga.fi:n nimi (vain ne, jotka eroavat)
LIIGA_NIMET = {
    "Kiekko-Espoo": "K-Espoo",
}

with open(KIRJANPITO, "r", encoding="utf-8") as tiedosto:
    kirjanpito = json.load(tiedosto)

def odds_tulos(ottelu):
    maalit = {}
    for rivi in ottelu["scores"]:
        maalit[rivi["name"]] = int(rivi["score"])

    koti = maalit[ottelu["home_team"]]
    vieras = maalit[ottelu["away_team"]]

    return {
        "koti_nimi": ottelu["home_team"],
        "vieras_nimi": ottelu["away_team"],
        "koti": koti,
        "vieras": vieras,
        # Tämä lähde ei kerro jatkoajasta: 60 min tulos on varma vain 2+ maalin erolla
        "koti_60": koti,
        "vieras_60": vieras,
        "varma60": abs(koti - vieras) >= 2,
    }

def nhl_tulos(veto):
    koti_nimi, vieras_nimi = veto["ottelu"].split(" - ")
    alkaa = datetime.fromisoformat(veto["alkaa"].replace("Z", "+00:00"))

    # NHL käyttää Pohjois-Amerikan päivämäärää. Esim. Suomen yöllä alkava peli
    # on siellä vielä edellistä päivää, joten katsotaan molemmat päivät.
    for paiva in [alkaa, alkaa - timedelta(days=1)]:
        osoite = "https://api-web.nhle.com/v1/score/" + paiva.strftime("%Y-%m-%d")
        vastaus = requests.get(osoite)
        if vastaus.status_code != 200:
            continue

        for peli in vastaus.json()["games"]:
            koti = peli["homeTeam"]
            vieras = peli["awayTeam"]

            # Onko tämä oikea peli?
            if not koti_nimi.endswith(koti["name"]["default"]):
                continue
            if not vieras_nimi.endswith(vieras["name"]["default"]):
                continue

            # Peli löytyi, mutta onko se päättynyt?
            if peli["gameState"] not in ["OFF", "FINAL"]:
                return None

            k = koti["score"]
            v = vieras["score"]

            if peli["gameOutcome"]["lastPeriodType"] == "REG":
                k60 = k
                v60 = v
            else:
                # Jatkoaika tai voittolaukaukset: 60 min jälkeen oli tasan
                k60 = min(k, v)
                v60 = min(k, v)

            return {
                "koti_nimi": koti_nimi,
                "vieras_nimi": vieras_nimi,
                "koti": k,
                "vieras": v,
                "koti_60": k60,
                "vieras_60": v60,
                "varma60": True,
            }

    return None   # peliä ei löytynyt

def hae_liigan_pelit():
    osoite = ("https://liiga.fi/api/v2/schedule?tournament=runkosarja&season="
              + str(LIIGA_KAUSI))
    vastaus = requests.get(osoite)
    if vastaus.status_code != 200:
        print("VIRHE: Liigan tulokset", vastaus.status_code)
        return []          # tyhjä lista: ei tuloksia, mutta ohjelma ei kaadu
    return vastaus.json()


def liiga_tulos(veto, pelit):
    koti_nimi, vieras_nimi = veto["ottelu"].split(" - ")

    # .get(nimi, nimi): jos nimeä ei löydy muunnoslistasta, käytetään sitä sellaisenaan
    liiga_koti = LIIGA_NIMET.get(koti_nimi, koti_nimi)
    liiga_vieras = LIIGA_NIMET.get(vieras_nimi, vieras_nimi)
    for peli in pelit:
        # Sama koti- ja vierasjoukkue...
        if peli["homeTeamName"] != liiga_koti or peli["awayTeamName"] != liiga_vieras:
            continue
        # ...ja sama päivä (joukkueet kohtaavat kaudella monta kertaa)
        if peli["start"][:10] != veto["alkaa"][:10]:
            continue

        if not peli["ended"]:
            return None

        k = peli["homeTeamGoals"]
        v = peli["awayTeamGoals"]

        if peli["finishedType"] == "ENDED_DURING_REGULAR_GAME_TIME":
            k60 = k
            v60 = v
        else:
            k60 = min(k, v)
            v60 = min(k, v)

        return {
            "koti_nimi": koti_nimi,
            "vieras_nimi": vieras_nimi,
            "koti": k,
            "vieras": v,
            "koti_60": k60,
            "vieras_60": v60,
            "varma60": True,
        }

    return None

def ratkaise(veto, tulos):
    tyyppi = veto["tyyppi"]
    valinta = veto["valinta"]

    # Kaikki paitsi Voittaja ratkaistaan 60 min tuloksella
    if tyyppi != "Voittaja" and not tulos["varma60"]:
        return "tarkista"

    # Voittaja: lopputulos jatkoaikoineen
    if tyyppi == "Voittaja":
        if tulos["koti"] > tulos["vieras"]:
            voittaja = tulos["koti_nimi"]
        else:
            voittaja = tulos["vieras_nimi"]
        if valinta == voittaja:
            return "osui"
        return "ei osunut"

    # Tästä eteenpäin käytetään varsinaisen peliajan tulosta
    koti = tulos["koti_60"]
    vieras = tulos["vieras_60"]

    if tyyppi == "1X2":
        if koti > vieras:
            oikea = tulos["koti_nimi"]
        elif koti < vieras:
            oikea = tulos["vieras_nimi"]
        else:
            oikea = "Draw"
        if valinta == oikea:
            return "osui"
        return "ei osunut"

    if tyyppi.startswith("Yli/alle"):
        raja = float(tyyppi.split(" ")[1])
        yhteensa = koti + vieras
        if yhteensa == raja:
            return "mitätöity"
        if valinta == "Over" and yhteensa > raja:
            return "osui"
        if valinta == "Under" and yhteensa < raja:
            return "osui"
        return "ei osunut"

    if tyyppi.startswith("Tasoitus"):
        raja = float(tyyppi.split(" ")[2])
        if valinta == tulos["koti_nimi"]:
            erotus = koti + raja - vieras
        else:
            erotus = vieras - raja - koti
        if erotus > 0:
            return "osui"
        if erotus == 0:
            return "mitätöity"
        return "ei osunut"

    return "tarkista"

tarvittavat = []
for veto in kirjanpito:
    sarja = veto.get("sarja")
    if veto["tila"] == "avoin" and sarja in SARJATUNNUKSET:
        tunnus = SARJATUNNUKSET[sarja]
        if tunnus not in tarvittavat:
            tarvittavat.append(tunnus)

tulokset = {}
for tunnus in tarvittavat:
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
        if ottelu["completed"]:
            tulokset[ottelu["id"]] = odds_tulos(ottelu)   # suoraan yhteiseen muotoon
ratkaistuja = 0
liigan_pelit = None   # haetaan vasta, kun ensimmäinen Liiga-veto tulee vastaan

for veto in kirjanpito:
    if veto["tila"] not in ["avoin", "tarkista"]:
        continue

    # Valitaan lähde sarjan mukaan
    if veto.get("sarja") == "NHL":
        tulos = nhl_tulos(veto)
    elif veto.get("sarja") == "Liiga":
        # Koko kausi tulee yhdellä haulla, joten haetaan se vain kerran
        if liigan_pelit is None:
            liigan_pelit = hae_liigan_pelit()
        tulos = liiga_tulos(veto, liigan_pelit)
    elif veto["id"] in tulokset:
        tulos = tulokset[veto["id"]]
    else:
        tulos = None

    if tulos is None:
        continue          # ei vielä päättynyt tai ei löytynyt

    tila = ratkaise(veto, tulos)

    # Jos veto oli jo "tarkista" eikä tieto parantunut, ei tehdä mitään
    if tila == veto["tila"]:
        continue

    veto["tila"] = tila
    if tila == "osui":
        veto["voitto"] = round(veto["panos"] * veto["kerroin"] - veto["panos"], 2)
    elif tila == "ei osunut":
        veto["voitto"] = -veto["panos"]
    elif tila == "mitätöity":
        veto["voitto"] = 0

    ratkaistuja += 1
    print(veto["ottelu"], "|", veto["tyyppi"], veto["valinta"],
          "| tulos", tulos["koti"], "-", tulos["vieras"],
          "(60 min:", tulos["koti_60"], "-", tulos["vieras_60"], ") ->", tila)

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
print("Nyt ratkaistu:", ratkaistuja)
print("Ratkaistuja vetoja yhteensä:", pelattuja, "| osuneita:", osuneita)
print("Leikkirahasaldo:", round(saldo, 2), "€")
print("Odottaa käsin tarkistusta:", tarkistettavia)
          