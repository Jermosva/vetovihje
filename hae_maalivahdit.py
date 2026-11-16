import json
import os
import time
import requests

# Hakee jokaisesta pelatusta Liigan pelistä sekä aloittavat maalivahdit että
# pelaajien tehopisteet. Sama ottelutietohaku täyttää molemmat tiedostot,
# joten yhtä peliä ei haeta kahdesti.

KAUDET = [2024, 2025, 2026, 2027]
TIEDOSTO = "liiga_maalivahdit.json"
PELAAJATIEDOSTO = "liiga_pelaajat.json"
TAUKO = 0.2                  # sekuntia hakujen välillä, ettei kuormiteta palvelinta

# Maalityypit, joita ei lasketa: VL = voittolaukaus. Lisäksi kaikki nollaan
# päättyvät tyypit ovat hylättyjä maaleja (VT0 = hylätty videotarkistuksessa,
# RL0 = epäonnistunut rangaistuslaukaus).
YLIVOIMA = ["YV", "YV2"]     # YV = 5 vs 4, YV2 = 5 vs 3


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


def hyvaksytty(maali):
    # Pelaajavedot: jatkoaika mukaan, voittolaukaukset ja hylätyt maalit ei
    tyypit = maali.get("goalTypes") or []
    if maali.get("period", 0) >= 5 or "VL" in tyypit:
        return False
    return not any(tyyppi.endswith("0") for tyyppi in tyypit)


def pelipaikka(pelaaja):
    # "P" = puolustaja, "H" = hyökkääjä. Kokoonpanossa roolit ovat esim.
    # LEFT_DEFENSEMAN, SEVENTH_DEFENSEMAN, CENTER, THIRTEENTH_STRIKER.
    if "DEFENSEMAN" in (pelaaja.get("role") or ""):
        return "P"
    return "H"


def pelaajarivit(data, puoli, nimet):
    # Yksi rivi jokaiselle kokoonpanossa olleelle kenttäpelaajalle:
    # [id, puoli, pelipaikka, rooli, ketju, maalit, syötöt, ylivoimapisteet]
    if puoli == "K":
        pelaajat = data.get("homeTeamPlayers", [])
        maalit = data["game"]["homeTeam"].get("goalEvents", [])
    else:
        pelaajat = data.get("awayTeamPlayers", [])
        maalit = data["game"]["awayTeam"].get("goalEvents", [])

    tilasto = {}      # id -> [maalit, syötöt, ylivoimapisteet]
    for maali in maalit:
        if not hyvaksytty(maali):
            continue
        ylivoima = any(t in YLIVOIMA for t in (maali.get("goalTypes") or []))
        tekijat = [(maali.get("scorerPlayerId"), 0)]
        tekijat += [(s, 1) for s in (maali.get("assistantPlayerIds") or [])]
        for pelaaja_id, sarake in tekijat:
            if pelaaja_id is None:
                continue
            rivi = tilasto.setdefault(pelaaja_id, [0, 0, 0])
            rivi[sarake] += 1
            if ylivoima:
                rivi[2] += 1

    rivit = []
    kokoonpanossa = set()
    for pelaaja in pelaajat:
        if pelaaja.get("line") is None or pelaaja.get("role") == "GOALIE":
            continue
        kokoonpanossa.add(pelaaja["id"])
        nimet[str(pelaaja["id"])] = pelaaja["firstName"] + " " + pelaaja["lastName"]
        m, s, yv = tilasto.get(pelaaja["id"], [0, 0, 0])
        rivit.append([pelaaja["id"], puoli, pelipaikka(pelaaja), pelaaja.get("roleCode"),
                      pelaaja["line"], m, s, yv])

    # Pisteet pelaajille, jotka eivät olleet kokoonpanossa (pitäisi olla 0)
    orvot = sum(1 for pelaaja_id in tilasto if pelaaja_id not in kokoonpanossa)
    hyvaksytyt = sum(1 for maali in maalit if hyvaksytty(maali))
    return rivit, hyvaksytyt, orvot


def peli_tiedot(peli, data, nimet):
    koti_rivit, koti_maalit, koti_orvot = pelaajarivit(data, "K", nimet)
    vieras_rivit, vieras_maalit, vieras_orvot = pelaajarivit(data, "V", nimet)
    return {
        "alkaa": peli["start"],
        "koti": peli["homeTeamName"],
        "vieras": peli["awayTeamName"],
        # Maalit ilman voittolaukauksia (= pelaajavetojen sääntö)
        "maalit": [koti_maalit, vieras_maalit],
        "paattyi": peli["finishedType"],
        "orvot": koti_orvot + vieras_orvot,
        "pelaajat": koti_rivit + vieras_rivit,
    }


def lue(tiedosto, oletus):
    if os.path.exists(tiedosto):
        with open(tiedosto, "r", encoding="utf-8") as f:
            return json.load(f)
    return oletus


def tallenna(tiedot):
    with open(TIEDOSTO, "w", encoding="utf-8") as tiedosto:
        json.dump(tiedot, tiedosto, ensure_ascii=False, indent=1)


def tallenna_pelaajat(pelaajadata):
    # Yksi peli per rivi: tiedosto pysyy pienenä ja git-muutokset selkeinä
    rivit = []
    for avain in sorted(pelaajadata["pelit"]):
        rivit.append(json.dumps(avain) + ": "
                     + json.dumps(pelaajadata["pelit"][avain], ensure_ascii=False))
    with open(PELAAJATIEDOSTO, "w", encoding="utf-8") as tiedosto:
        tiedosto.write('{"nimet": ' + json.dumps(pelaajadata["nimet"], ensure_ascii=False,
                                                 sort_keys=True) + ',\n"pelit": {\n')
        tiedosto.write(",\n".join(rivit))
        tiedosto.write("\n}}\n")


def tarkista_maalit(peli, tiedot):
    # Hyväksyttyjen maalien pitää täsmätä lopputulokseen. Voittolaukauskisan
    # voittaja saa lopputulokseen yhden maalin, jota ei lasketa pelaajille.
    koti = peli["homeTeamGoals"]
    vieras = peli["awayTeamGoals"]
    if peli["finishedType"] == "ENDED_DURING_WINNING_SHOT_COMPETITION":
        if koti > vieras:
            koti -= 1
        else:
            vieras -= 1
    return tiedot["maalit"] == [koti, vieras]


if __name__ == "__main__":
    # Jatketaan siitä, mihin edellinen ajo jäi
    tallennetut = lue(TIEDOSTO, {})
    pelaajadata = lue(PELAAJATIEDOSTO, {"nimet": {}, "pelit": {}})

    uusia = 0
    eivat_tasmaa = []
    for kausi in KAUDET:
        pelit = hae_kauden_pelit(kausi)
        print("Kausi", kausi, ":", len(pelit), "pelattua peliä")

        for peli in pelit:
            # Sama id voi esiintyä eri kausilla, joten avaimeksi kausi + id
            avain = str(peli["season"]) + "_" + str(peli["id"])
            if avain in tallennetut and avain in pelaajadata["pelit"]:
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
            # Poikkeava data ei saa kaataa ajoa: peli jää pois ja haetaan uudelleen seuraavalla kerralla
            try:
                tiedot = peli_tiedot(peli, data, pelaajadata["nimet"])
                pelaajadata["pelit"][avain] = tiedot
                if not tarkista_maalit(peli, tiedot):
                    eivat_tasmaa.append(avain)
            except (KeyError, TypeError, ValueError) as virhe:
                print("  VIRHE: pelaajadata", avain, virhe)
            uusia += 1

            # Tallennetaan välillä, ettei mitään menetetä, jos ajo keskeytyy
            if uusia % 100 == 0:
                print("  haettu", uusia, "peliä...")
                tallenna(tallennetut)
                tallenna_pelaajat(pelaajadata)

            time.sleep(TAUKO)

    tallenna(tallennetut)
    tallenna_pelaajat(pelaajadata)

    # ===== Yhteenveto: maalivahdit =====
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

    # ===== Yhteenveto: pelaajat =====
    pelit = pelaajadata["pelit"]
    nimet = pelaajadata["nimet"]
    print()
    print("Pelaajadata:", len(pelit), "peliä,", len(nimet), "eri pelaajaa")
    if eivat_tasmaa:
        print("VAROITUS: maalit eivät täsmää lopputulokseen:", len(eivat_tasmaa), "pelissä:",
              ", ".join(eivat_tasmaa[:10]))
    orvot = sum(p["orvot"] for p in pelit.values())
    ilman_kokoonpanoa = sum(1 for p in pelit.values() if len(p["pelaajat"]) == 0)
    print("Pisteitä kokoonpanon ulkopuolisille (yleensä maalivahtien syöttöjä):", orvot,
          "| pelejä ilman kokoonpanoa:", ilman_kokoonpanoa)

    # Kauden pistepörssin kärki
    uusin = max((int(avain[:4]) for avain in pelit), default=None)
    porssi = {}       # id -> [ottelut, maalit, syötöt, ylivoimapisteet, joukkue, pelipaikka]
    for avain, peli in pelit.items():
        if int(avain[:4]) != uusin:
            continue
        for pelaaja_id, puoli, paikka, _, _, m, s, yv in peli["pelaajat"]:
            joukkue = peli["koti"] if puoli == "K" else peli["vieras"]
            rivi = porssi.setdefault(pelaaja_id, [0, 0, 0, 0, joukkue, paikka])
            rivi[0] += 1
            rivi[1] += m
            rivi[2] += s
            rivi[3] += yv
            rivi[4] = joukkue
    print()
    print("Kauden", uusin, "pistepörssin kärki (sis. jatkoaika, ei voittolaukauksia):")
    print(f"  {'Pelaaja':25} {'Joukkue':10} PP   O   M   S   P  YVP")
    jarjestys = sorted(porssi, key=lambda i: (porssi[i][1] + porssi[i][2], porssi[i][1]), reverse=True)
    for pelaaja_id in jarjestys[:15]:
        o, m, s, yv, joukkue, paikka = porssi[pelaaja_id]
        print(f"  {nimet.get(str(pelaaja_id), pelaaja_id):25} {joukkue:10} {paikka}  {o:3} {m:3} {s:3} {m + s:3} {yv:3}")
