import json
import os
from datetime import date

MAX_MARGINAALI = 10
MIN_VALUE = 3
MIN_YHTIOT = 3
VERTAILUYHTIO = "Pinnacle"   # jos tämä yhtiö on mukana, sen arvio on "oikea"
PANOS = 10                       # leikkieuroa per veto
KIRJANPITO = "kirjanpito.json"   # tiedosto, johon vedot tallennetaan

loydetyt = []
# def = määritellään funktio. Suluissa ovat tiedot, jotka funktio saa käyttöönsä.
def markkinan_tyyppi(markkina, ottelu):
    vaihtoehdot = markkina["outcomes"]

    if markkina["key"] == "h2h":
        if len(vaihtoehdot) == 3:
            return "1X2"        # return = palauta tämä ja lopeta funktio
        return "Voittaja"

    if markkina["key"] == "totals":
        # [0] = listan ensimmäinen alkio (Python laskee nollasta)
        return "Yli/alle " + str(vaihtoehdot[0]["point"])

    # Tasoitus: nimetään kotijoukkueen tasoituksen mukaan, esim. "Tasoitus koti -1.5"
    for v in vaihtoehdot:
        if v["name"] == ottelu["home_team"]:
            return "Tasoitus koti " + str(v["point"])

    return "Tasoitus"

def reilut_todennakoisyydet(vaihtoehdot):
    summa = 0
    for v in vaihtoehdot:
        summa = summa + 1 / v["price"]

    reilut = {}
    for v in vaihtoehdot:
        reilut[v["name"]] = (1 / v["price"]) / summa

    marginaali = (summa - 1) * 100

    # Funktio voi palauttaa kaksi asiaa kerralla pilkulla erotettuna
    return reilut, marginaali

with open("ottelut.json", "r", encoding="utf-8") as tiedosto:
    ottelut = json.load(tiedosto)

for ottelu in ottelut:
    print()
    print(ottelu["home_team"], "vs", ottelu["away_team"])

    # Kerätään saman vetotyypin markkinat samaan ryhmään:
    # tyyppi -> lista pareja (yhtiön nimi, vaihtoehdot)
    ryhmat = {}
    for yhtio in ottelu["bookmakers"]:
        for markkina in yhtio["markets"]:
            tyyppi = markkinan_tyyppi(markkina, ottelu)   # funktion kutsu
            if tyyppi not in ryhmat:
                ryhmat[tyyppi] = []
            # Kaksi arvoa sulkeissa = pari (tuple)
            ryhmat[tyyppi].append((yhtio["title"], markkina["outcomes"]))
    for tyyppi in ryhmat:
        reilut = {}
        parhaat = {}
        parhaan_yhtio = {}
        vertailu = None      # None = "ei mitään vielä"

        # Pari puretaan suoraan kahteen muuttujaan
        for yhtio_nimi, vaihtoehdot in ryhmat[tyyppi]:
            yhtion_reilut, marginaali = reilut_todennakoisyydet(vaihtoehdot)

            if yhtio_nimi == VERTAILUYHTIO:
                vertailu = yhtion_reilut

            for v in vaihtoehdot:
                nimi = v["name"]

                if nimi not in parhaat or v["price"] > parhaat[nimi]:
                    parhaat[nimi] = v["price"]
                    parhaan_yhtio[nimi] = yhtio_nimi

                if marginaali <= MAX_MARGINAALI:
                    if nimi not in reilut:
                        reilut[nimi] = []
                    reilut[nimi].append(yhtion_reilut[nimi])
        for nimi in parhaat:
            if nimi not in reilut:
                continue

            yhtioita = len(reilut[nimi])

            # Pinnacle voittaa, jos se on mukana. Muuten keskiarvo.
            if vertailu is not None:
                oikea = vertailu[nimi]
                lahde = "Pinnacle"
            else:
                oikea = sum(reilut[nimi]) / yhtioita
                lahde = "keskiarvo"

            paras = parhaat[nimi]
            value = (oikea * paras - 1) * 100

            # Riittävän luotettava: Pinnacle mukana TAI tarpeeksi monta yhtiötä
            luotettava = (vertailu is not None) or (yhtioita >= MIN_YHTIOT)

            merkki = ""
            if value >= MIN_VALUE and luotettava:
                merkki = "  <-- VALUE"
                loydetyt.append({
                    "id": ottelu["id"],
                    "alkaa": ottelu["commence_time"],
                    "ottelu": ottelu["home_team"] + " - " + ottelu["away_team"],
                    "tyyppi": tyyppi,
                    "valinta": nimi,
                    "kerroin": paras,
                    "yhtio": parhaan_yhtio[nimi],
                    "value": round(value, 1),
                    "lahde": lahde,
                })

            print("   ", tyyppi, "|", nimi,
                  "| oikea", round(oikea * 100, 1), "%", "(" + lahde + ")",
                  "| paras", paras, "(" + parhaan_yhtio[nimi] + ")",
                  "| value", round(value, 1), "%",
                  "| yhtiöitä", yhtioita,
                  merkki)
print()
print("===== PÄIVÄN VALUE-VEDOT =====")

if len(loydetyt) == 0:
    print("Ei value-vetoja näillä rajoilla.")
else:
    for veto in loydetyt:
        print(veto["ottelu"], "|", veto["tyyppi"], veto["valinta"],
              "@", veto["kerroin"], "(" + veto["yhtio"] + ")",
              "| value", veto["value"], "% |", veto["lahde"])
        
# Valitaan jokaisesta ottelusta veto, jolla on suurin value
parhaat_vedot = {}   # ottelun id -> veto
for veto in loydetyt:
    oid = veto["id"]
    if oid not in parhaat_vedot or veto["value"] > parhaat_vedot[oid]["value"]:
        parhaat_vedot[oid] = veto
# Ensimmäisellä kerralla tiedostoa ei vielä ole, joten aloitetaan tyhjästä listasta
if os.path.exists(KIRJANPITO):
    with open(KIRJANPITO, "r", encoding="utf-8") as tiedosto:
        kirjanpito = json.load(tiedosto)
else:
    kirjanpito = []
kirjatut = []
for rivi in kirjanpito:
    kirjatut.append(rivi["id"])
    
uusia = 0
for oid in parhaat_vedot:
    if oid in kirjatut:
        continue          # tämä ottelu on jo kirjattu, ohitetaan

    veto = parhaat_vedot[oid]
    veto["pvm"] = str(date.today())   # esim. "2026-10-04"
    veto["panos"] = PANOS
    veto["tila"] = "avoin"            # myöhemmin: osui / ei osunut / mitätöity
    kirjanpito.append(veto)
    uusia = uusia + 1
    
with open(KIRJANPITO, "w", encoding="utf-8") as tiedosto:
    json.dump(kirjanpito, tiedosto, ensure_ascii=False, indent=2)

print()
print("Kirjanpitoon lisätty", uusia, "uutta vetoa. Yhteensä", len(kirjanpito), "vetoa.")