import json
import os
import sys
import time
from datetime import datetime, timezone

import requests

from hae_maalivahdit import TAUKO, lue, pelaajarivit

# Ratkaisee pelaajavedot (pelaajavedot.json) ja pelaajien varjokirjanpidon
# (pelaajavarjo.json) Liigan ottelutiedoista. Sääntö: jatkoaika mukaan,
# voittolaukaukset ja hylätyt maalit ei (hoituu hae_maalivahdit.py:n pelaajarivit-funktiolla).

PELAAJAVEDOT = "pelaajavedot.json"           # sivu kirjoittaa, täällä vain luetaan
TULOKSET = "pelaajavedot_tulokset.json"      # vain tämä tiedosto kirjoittaa
VARJO = "pelaajavarjo.json"
PELAAJADATA = "liiga_pelaajat.json"          # jo haetut pelit (hae_maalivahdit.py)
TYYPIT = ["maalit", "syotot", "pisteet"]

# Jokainen peli haetaan korkeintaan kerran ajon aikana: avain -> tilasto tai None
valimuisti = {}
tiedoston_pelit = None     # liiga_pelaajat.json:n pelit, luetaan vasta kun tarvitaan


def tilasto_riveista(rivit):
    # pelaajarivit-muoto: [id, puoli, pelipaikka, rooli, ketju, maalit, syötöt, yv-pisteet]
    return {rivi[0]: (rivi[5], rivi[6]) for rivi in rivit}


def tiedostosta(avain):
    global tiedoston_pelit
    if tiedoston_pelit is None:
        try:
            tiedoston_pelit = lue(PELAAJADATA, {"pelit": {}})["pelit"]
        except ValueError:
            print("VIRHE:", PELAAJADATA, "ei ole kelvollista JSONia, haetaan pelit verkosta")
            tiedoston_pelit = {}

    peli = tiedoston_pelit.get(avain)
    if peli is None:
        return None            # ei tiedostossa: haetaan verkosta
    # Molempien joukkueiden kokoonpano pitää olla, muuten vedot mitätöityisivät väärin
    puolet = {rivi[1] for rivi in peli["pelaajat"]}
    if "K" not in puolet or "V" not in puolet:
        return None            # kokoonpano puuttuu: kokeillaan verkosta
    return tilasto_riveista(peli["pelaajat"])


def verkosta(avain):
    # "2027_2701458" -> kausi 2027, peli 2701458
    kausi, peli_id = avain.split("_")
    osoite = "https://liiga.fi/api/v2/games/" + kausi + "/" + peli_id
    try:
        vastaus = requests.get(osoite, timeout=30)
        time.sleep(TAUKO)
        if vastaus.status_code != 200:
            print("VIRHE: peli", avain, vastaus.status_code)
            return None
        data = vastaus.json()
        if not data["game"]["ended"]:
            return None        # peli kesken tai ei vielä alkanut
    except (requests.RequestException, ValueError, KeyError) as virhe:
        # Verkkovirhe ei saa kaataa ajoa: yritetään uudestaan seuraavalla kerralla
        print("VIRHE: peli", avain, virhe)
        return None

    koti, _, _ = pelaajarivit(data, "K", {})
    vieras, _, _ = pelaajarivit(data, "V", {})
    if not koti or not vieras:
        # Ilman kokoonpanoa kaikki vedot mitätöityisivät väärin, joten odotetaan
        print("VAROITUS: peli", avain, "on päättynyt, mutta kokoonpano puuttuu")
        return None
    return tilasto_riveista(koti + vieras)


def pelin_tilasto(avain):
    # None = peli ei ole päättynyt (tai tietoja ei saatu).
    # Muuten {pelaaja_id: (maalit, syötöt)} kaikille kokoonpanon kenttäpelaajille.
    if avain not in valimuisti:
        tilasto = tiedostosta(avain)
        if tilasto is None:
            tilasto = verkosta(avain)
        valimuisti[avain] = tilasto
    return valimuisti[avain]


def tulevaisuudessa(pvm):
    # Suomen pelipäivä on aina sama tai myöhempi kuin UTC-päivä, joten jos pvm on
    # UTC-päivää myöhäisempi, peli ei ole voinut vielä alkaa (ei turhia hakuja)
    return pvm > datetime.now(timezone.utc).strftime("%Y-%m-%d")


def tallenna_peleittain(tiedosto, pelit):
    # Yksi peli per rivi (kuten liiga_pelaajat.json): git-muutokset pysyvät selkeinä
    rivit = []
    for avain in sorted(pelit):
        rivit.append(json.dumps(avain) + ": " + json.dumps(pelit[avain], ensure_ascii=False))
    with open(tiedosto, "w", encoding="utf-8") as f:
        f.write("{\n" + ",\n".join(rivit) + "\n}\n")


def ratkaise_vedot():
    if not os.path.exists(PELAAJAVEDOT):
        return
    vedot = lue(PELAAJAVEDOT, [])
    tulokset = lue(TULOKSET, {})

    uusia = 0
    for veto in vedot:
        if veto["id"] in tulokset or tulevaisuudessa(veto["pvm"]):
            continue
        if veto["tyyppi"] not in TYYPIT:
            print("VAROITUS: tuntematon vetotyyppi", veto["tyyppi"], "vedossa", veto["id"])
            continue

        tilasto = pelin_tilasto(veto["avain"])
        if tilasto is None:
            continue

        pelaaja_id = int(veto["pelaaja_id"])
        if pelaaja_id not in tilasto:
            # Pelaaja ei ollut kokoonpanossa: veto mitätöidään
            tila = "mitätöity"
            toteuma = None
            voitto = 0
        else:
            maalit, syotot = tilasto[pelaaja_id]
            if veto["tyyppi"] == "maalit":
                toteuma = maalit
            elif veto["tyyppi"] == "syotot":
                toteuma = syotot
            else:
                toteuma = maalit + syotot

            if toteuma >= veto["raja"]:
                tila = "osui"
                voitto = round(veto["panos"] * veto["kerroin"] - veto["panos"], 2)
            else:
                tila = "ei osunut"
                voitto = -veto["panos"]

        tulokset[veto["id"]] = {"tila": tila, "toteuma": toteuma, "voitto": voitto}
        uusia += 1
        print(veto["ottelu"], "|", veto["pelaaja"], veto["tyyppi"], str(veto["raja"]) + "+",
              "| toteuma", toteuma, "->", tila)

    if uusia > 0:
        with open(TULOKSET, "w", encoding="utf-8") as tiedosto:
            json.dump(tulokset, tiedosto, ensure_ascii=False, indent=1)

    # Yhteenveto tyypeittäin: [vetoja, osuneita, panokset, saldo]
    yhteenveto = {}
    for veto in vedot:
        tulos = tulokset.get(veto["id"])
        if tulos is None:
            continue
        rivi = yhteenveto.setdefault(veto["tyyppi"], [0, 0, 0, 0])
        rivi[0] += 1
        if tulos["tila"] == "osui":
            rivi[1] += 1
        if tulos["tila"] != "mitätöity":
            rivi[2] += veto["panos"]      # mitätöity panos palautetaan, ei lasketa ROI:hin
        rivi[3] += tulos["voitto"]

    print()
    print("Pelaajavetoja nyt ratkaistu:", uusia)
    for tyyppi in TYYPIT:
        if tyyppi not in yhteenveto:
            continue
        vetoja, osuneita, panokset, saldo = yhteenveto[tyyppi]
        roi = saldo / panokset * 100 if panokset > 0 else 0
        print(f"  {tyyppi:8} vetoja {vetoja:3} | osuneita {osuneita:3}"
              f" | saldo {saldo:8.2f} € | ROI {roi:6.1f} %")


def ratkaise_varjo():
    if not os.path.exists(VARJO):
        return
    varjo = lue(VARJO, {})

    ratkaistuja = 0
    for avain, peli in varjo.items():
        if peli.get("tulokset") is not None or tulevaisuudessa(peli["pvm"]):
            continue
        tilasto = pelin_tilasto(avain)
        if tilasto is None:
            continue
        peli["tulokset"] = [[pelaaja_id, m, s] for pelaaja_id, (m, s) in tilasto.items()]
        ratkaistuja += 1

    if ratkaistuja > 0:
        tallenna_peleittain(VARJO, varjo)
    print("Pelaajavarjosta ratkaistu:", ratkaistuja, "peliä")

    # Kalibraatio: osuuko mallin pisteet_1-todennäköisyys keskimäärin oikeaan?
    # Mukana vain kokoonpanossa olleet pelaajat (muut olisivat mitätöityjä).
    ennuste = 0
    toteutui = 0
    pelaajia = 0
    peleja = 0
    for peli in varjo.values():
        if peli.get("tulokset") is None:
            continue
        peleja += 1
        pisteet = {rivi[0]: rivi[1] + rivi[2] for rivi in peli["tulokset"]}
        # ennusteet: [id, tn_maalit_1, tn_syotot_1, tn_pisteet_1, tn_pisteet_2]
        for rivi in peli["ennusteet"]:
            if rivi[0] not in pisteet:
                continue
            ennuste += rivi[3]
            if pisteet[rivi[0]] >= 1:
                toteutui += 1
            pelaajia += 1
    if pelaajia > 0:
        print(f"Kalibraatio pisteet_1: ennuste {ennuste / pelaajia:.3f}"
              f" | toteutunut {toteutui / pelaajia:.3f} ({pelaajia} pelaajaa, {peleja} peliä)")


def paivita():
    # Virhe pelaajapuolella ei saa kaataa GitHub Actionsin ajoa
    # Windowsissa tulostus ei osaa kaikkia nimien kirjaimia (esim. Ř): korvataan ne ?-merkillä
    sys.stdout.reconfigure(errors="replace")
    print()
    try:
        ratkaise_vedot()
    except Exception as virhe:
        print("VIRHE: pelaajavetojen ratkaisu:", repr(virhe))
    try:
        ratkaise_varjo()
    except Exception as virhe:
        print("VIRHE: pelaajavarjon ratkaisu:", repr(virhe))


if __name__ == "__main__":
    paivita()
