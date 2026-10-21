import json
import os
import time
import requests

KAUDET = [2024, 2025, 2026, 2027]
TIEDOSTO = "liiga_maalivahdit.json"


def hae_kauden_pelit(kausi):
    osoite = ("https://liiga.fi/api/v2/schedule?tournament=runkosarja&season="
              + str(kausi))
    vastaus = requests.get(osoite)
    if vastaus.status_code != 200:
        print("VIRHE: kausi", kausi, vastaus.status_code)
        return []
    return [peli for peli in vastaus.json() if peli["ended"]]


def aloittaja(pelaajat):
    # Aloittava maalivahti = maalivahti, jonka "line" on 1
    for pelaaja in pelaajat:
        if pelaaja.get("role") == "GOALIE" and pelaaja.get("line") == 1:
            return {"id": pelaaja["id"],
                    "nimi": pelaaja["firstName"] + " " + pelaaja["lastName"]}
    return None


def tallenna(tiedot):
    with open(TIEDOSTO, "w", encoding="utf-8") as tiedosto:
        json.dump(tiedot, tiedosto, ensure_ascii=False, indent=1)


# Jatketaan siitä, mihin edellinen ajo jäi
if os.path.exists(TIEDOSTO):
    with open(TIEDOSTO, "r", encoding="utf-8") as tiedosto:
        tallennetut = json.load(tiedosto)
else:
    tallennetut = {}

uusia = 0
for kausi in KAUDET:
    pelit = hae_kauden_pelit(kausi)
    print("Kausi", kausi, ":", len(pelit), "pelattua peliä")

    for peli in pelit:
        # Sama id voi esiintyä eri kausilla, joten avaimeksi kausi + id
        avain = str(peli["season"]) + "_" + str(peli["id"])
        if avain in tallennetut:
            continue                     # haettu jo aiemmin

        osoite = "https://liiga.fi/api/v2/games/" + str(peli["season"]) + "/" + str(peli["id"])
        vastaus = requests.get(osoite)
        if vastaus.status_code != 200:
            print("  VIRHE: peli", avain, vastaus.status_code)
            continue

        data = vastaus.json()
        koti = data["game"]["homeTeam"]
        vieras = data["game"]["awayTeam"]
        tallennetut[avain] = {
            "koti": aloittaja(data.get("homeTeamPlayers", [])),
            "vieras": aloittaja(data.get("awayTeamPlayers", [])),
            "vaihtoja": len(koti.get("goalKeeperChanges", [])) + len(vieras.get("goalKeeperChanges", [])),
        }
        uusia += 1

        # Tallennetaan välillä, ettei mitään menetetä, jos ajo keskeytyy
        if uusia % 100 == 0:
            print("  haettu", uusia, "peliä...")
            tallenna(tallennetut)

        time.sleep(0.2)                  # pieni tauko, ettei kuormiteta palvelinta

tallenna(tallennetut)

# Yhteenveto
puuttuu = sum(1 for t in tallennetut.values() if t["koti"] is None or t["vieras"] is None)
vaihdot = sum(1 for t in tallennetut.values() if t["vaihtoja"] > 0)
aloitukset = {}
for t in tallennetut.values():
    for puoli in ["koti", "vieras"]:
        if t[puoli] is not None:
            nimi = t[puoli]["nimi"]
            aloitukset[nimi] = aloitukset.get(nimi, 0) + 1

print()
print("Uusia haettu:", uusia, "| pelejä tiedostossa yhteensä:", len(tallennetut))
print("Peleistä aloittaja puuttuu:", puuttuu, "| maalivahtia vaihdettiin kesken pelin:", vaihdot)
print("Eri maalivahteja:", len(aloitukset))
print("Eniten aloituksia:")
for nimi in sorted(aloitukset, key=aloitukset.get, reverse=True)[:10]:
    print(f"  {nimi:25} {aloitukset[nimi]}")