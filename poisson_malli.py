import json
import math
import requests
import os
from datetime import datetime, timezone, timedelta

# ===== ASETUKSET =====
KAUDET = [2024, 2025, 2026, 2027]
# SHL:n kaudet: avain = päättymisvuosi (kuten Liigassa), arvo = shl.se:n kausitunnus
SHL_KAUDET = {
    2024: "qcz-3NvSZ2Cmh",   # 2023/2024
    2025: "qeb-73bZkIm9A",   # 2024/2025
    2026: "xs4m9qupsi",      # 2025/2026
    2027: "ndcf81nlb3",      # 2026/2027
}

# NHL:n kaudet muodossa 20252026 = kausi 2025–26
NHL_KAUDET = [20232024, 20242025, 20252026, 20262027]

# Vanha nimi -> nykyinen nimi (sama joukkue, uusi nimi)
NHL_NIMET = {
    "Arizona Coyotes": "Utah Mammoth",
    "Utah Hockey Club": "Utah Mammoth",
}

TESTATTAVA_SARJA = "NHL"     # kumpaa sarjaa walk-forward-testi koskee: "Liiga" tai "SHL"
PUOLIINTUMINEN = 180     # päivää: näin vanha peli painaa puolet tuoreesta
KUTISTUS = 20             # "keskiarvopelejä", joilla harvoin pelanneet vedetään kohti keskitasoa
KIERROKSET = 30          # montako kertaa voimat lasketaan uudelleen
MAX_MAALIT = 12          # tulosjakaumassa lasketaan maalimäärät 0–11
TASAPELIKERROIN = 1.3    # >1 lisää tasapelejä (Poisson aliarvioi niitä jääkiekossa)
KAUSIKERROIN = 0.5       # edellisen kauden pelien lisäpaino (1.0 = ei vaikutusta)
ALKUKAUSI_KUUKAUDET = [9, 10]   # syys- ja lokakuu = "kauden alku" testissä
# Testeissä löydetyt sarjakohtaiset asetukset
SARJA_ASETUKSET = {
    "Liiga": {"kausikerroin": 0.5, "tasapelikerroin": 1.3, "vasymys": 0.02},
    "SHL":   {"kausikerroin": 1.0, "tasapelikerroin": 1.15, "vasymys": 0.0},
    "NHL":   {"kausikerroin": 0.5, "tasapelikerroin": 1.7,  "vasymys": 0.04},
}

TESTAA = False            # True = aja walk-forward-testi (hidas), False = vain sovitus
ARVIOINTI_ALKAA = datetime(2025, 9, 1, tzinfo=timezone.utc)   # arvioidaan kaksi viimeistä kautta


# ===== DATA =====
def hae_kausi(kausi):
    osoite = ("https://liiga.fi/api/v2/schedule?tournament=runkosarja&season="
              + str(kausi))
    vastaus = requests.get(osoite)
    if vastaus.status_code != 200:
        print("VIRHE: kausi", kausi, vastaus.status_code)
        return []
    return [peli for peli in vastaus.json() if peli["ended"]]

def kausi_vuosi(paiva):
    # Liigan kausi nimetään päättymisvuoden mukaan:
    # syyskuu 2026 -> kausi 2027, helmikuu 2027 -> kausi 2027
    if paiva.month >= 7:
        return paiva.year + 1
    return paiva.year


def muunna(peli):
    k = peli["homeTeamGoals"]
    v = peli["awayTeamGoals"]
    jatkoaika = peli["finishedType"] != "ENDED_DURING_REGULAR_GAME_TIME"

    # 60 min tulos: jatkoajalle menneessä pelissä oli tasan
    if jatkoaika:
        pienempi = min(k, v)
        k60 = pienempi
        v60 = pienempi
    else:
        k60 = k
        v60 = v

    paiva = datetime.fromisoformat(peli["start"].replace("Z", "+00:00"))

    return {
        "koti": peli["homeTeamName"],
        "vieras": peli["awayTeamName"],
        "k60": k60,
        "v60": v60,
        "koti_voitti": k > v,     # lopputulos jatkoaikoineen
        "jatkoaika": jatkoaika,
        "paiva": paiva,
        "kausi": kausi_vuosi(paiva),
    }

def hae_shl_kausi(tunnus):
    osoite = ("https://www.shl.se/api/sports-v2/game-schedule?seasonUuid=" + tunnus
              + "&seriesUuid=qQ9-bb0bzEWUk&gameTypeUuid=qQ9-af37Ti40B"
              + "&gamePlace=all&played=all")
    vastaus = requests.get(osoite)
    if vastaus.status_code != 200:
        print("VIRHE: SHL-kausi", tunnus, vastaus.status_code)
        return []
    # Vain pelatut pelit
    return [peli for peli in vastaus.json()["gameInfo"] if peli["state"] == "post-game"]


def muunna_shl(peli):
    # Sama muoto kuin muunna(), jotta malli ei tiedä eikä välitä, mistä sarjasta peli on
    koti = peli["homeTeamInfo"]
    vieras = peli["awayTeamInfo"]
    k = koti["score"]
    v = vieras["score"]
    jatkoaika = peli["overtime"] or peli["shootout"]

    if jatkoaika:
        pienempi = min(k, v)
        k60 = pienempi
        v60 = pienempi
    else:
        k60 = k
        v60 = v

    paiva = datetime.fromisoformat(peli["rawStartDateTime"].replace("Z", "+00:00"))

    return {
        "koti": koti["names"]["long"],
        "vieras": vieras["names"]["long"],
        "k60": k60,
        "v60": v60,
        "koti_voitti": k > v,
        "jatkoaika": jatkoaika,
        "paiva": paiva,
        "kausi": kausi_vuosi(paiva),
    }

def hae_nhl_joukkueet():
    # NHL:n joukkueet: id-numero -> koko nimi, esim. 10 -> "Toronto Maple Leafs"
    vastaus = requests.get("https://api.nhle.com/stats/rest/en/team")
    if vastaus.status_code != 200:
        print("VIRHE: NHL:n joukkueet", vastaus.status_code)
        return {}
    nimet = {}
    for joukkue in vastaus.json()["data"]:
        nimet[joukkue["id"]] = joukkue["fullName"]
    return nimet


def hae_nhl_kausi(kausi):
    osoite = ("https://api.nhle.com/stats/rest/en/game?cayenneExp=season="
              + str(kausi) + "%20and%20gameType=2")
    vastaus = requests.get(osoite)
    if vastaus.status_code != 200:
        print("VIRHE: NHL-kausi", kausi, vastaus.status_code)
        return []
    # gameStateId 6 tai 7 = peli päättynyt
    return [peli for peli in vastaus.json()["data"] if peli["gameStateId"] in [6, 7]]


def muunna_nhl(peli, joukkueet):
    koti = joukkueet[peli["homeTeamId"]]
    vieras = joukkueet[peli["visitingTeamId"]]
    koti = NHL_NIMET.get(koti, koti)
    vieras = NHL_NIMET.get(vieras, vieras)

    k = peli["homeScore"]
    v = peli["visitingScore"]
    jatkoaika = peli["period"] > 3      # 4 = jatkoaika, 5 = voittolaukaukset

    if jatkoaika:
        pienempi = min(k, v)
        k60 = pienempi
        v60 = pienempi
    else:
        k60 = k
        v60 = v

    # NHL:n oma pelipäivä (itärannikon aika). Kellonajaksi keskipäivä, jotta
    # .date() antaa aina oikean päivän eikä UTC:n "huomista".
    paiva = datetime.fromisoformat(peli["gameDate"] + "T12:00:00+00:00")

    return {
        "koti": koti,
        "vieras": vieras,
        "k60": k60,
        "v60": v60,
        "koti_voitti": k > v,
        "jatkoaika": jatkoaika,
        "paiva": paiva,
        "kausi": kausi_vuosi(paiva),
    }


def hae_pelit(sarja):
    # Hakee ja muuntaa kaikkien kausien pelit samaan muotoon
    pelit = []
    if sarja == "Liiga":
        for kausi in KAUDET:
            for peli in hae_kausi(kausi):
                pelit.append(muunna(peli))
    elif sarja == "SHL":
        for kausi in SHL_KAUDET:
            for peli in hae_shl_kausi(SHL_KAUDET[kausi]):
                pelit.append(muunna_shl(peli))
    elif sarja == "NHL":
        joukkueet = hae_nhl_joukkueet()
        for kausi in NHL_KAUDET:
            for peli in hae_nhl_kausi(kausi):
                pelit.append(muunna_nhl(peli, joukkueet))

    # Merkitään jokaiseen peliin, pelasiko joukkue edellisenä päivänä
    pelipaivat = {}
    for p in pelit:
        for joukkue in [p["koti"], p["vieras"]]:
            if joukkue not in pelipaivat:
                pelipaivat[joukkue] = set()
            pelipaivat[joukkue].add(p["paiva"].date())

    for p in pelit:
        eilen = p["paiva"].date() - timedelta(days=1)
        p["koti_eilen"] = eilen in pelipaivat[p["koti"]]
        p["vieras_eilen"] = eilen in pelipaivat[p["vieras"]]

    return pelit

# ===== MALLIN SOVITUS (hidas osa) =====
def sovita(pelit, hetki, puoliintuminen=PUOLIINTUMINEN, kutistus=KUTISTUS,
           kausikerroin=KAUSIKERROIN):
    # 1. Aikapainot: tuore peli painaa 1, PUOLIINTUMINEN päivää vanha 0,5 jne.
    painot = []
    nykyinen_kausi = kausi_vuosi(hetki)
    for p in pelit:
        ika_paivina = (hetki - p["paiva"]).days
        kausiero = nykyinen_kausi - p["kausi"]      # 0 = tämä kausi, 1 = viime kausi...
        painot.append(0.5 ** (ika_paivina / puoliintuminen) * kausikerroin ** kausiero)

    # 2. Keskimääräiset maalit kotona ja vieraissa (painotettuina)
    paino_summa = sum(painot)
    koti_ka = sum(w * p["k60"] for w, p in zip(painot, pelit)) / paino_summa
    vieras_ka = sum(w * p["v60"] for w, p in zip(painot, pelit)) / paino_summa

    # 3. Kaikki aloittavat keskitasolta
    joukkueet = set()
    for p in pelit:
        joukkueet.add(p["koti"])
        joukkueet.add(p["vieras"])
    hyok = {j: 1.0 for j in joukkueet}
    puol = {j: 1.0 for j in joukkueet}

    # 4. Iteraatio: hyökkäys ja puolustus vuorotellen, kunnes luvut asettuvat
    for _ in range(KIERROKSET):
        tehty = {j: 0.0 for j in joukkueet}
        odotettu = {j: 0.0 for j in joukkueet}
        for w, p in zip(painot, pelit):
            tehty[p["koti"]] += w * p["k60"]
            odotettu[p["koti"]] += w * koti_ka * puol[p["vieras"]]
            tehty[p["vieras"]] += w * p["v60"]
            odotettu[p["vieras"]] += w * vieras_ka * puol[p["koti"]]
        for j in joukkueet:
            hyok[j] = (tehty[j] + kutistus) / (odotettu[j] + kutistus)

        paastetty = {j: 0.0 for j in joukkueet}
        odotettu = {j: 0.0 for j in joukkueet}
        for w, p in zip(painot, pelit):
            paastetty[p["koti"]] += w * p["v60"]
            odotettu[p["koti"]] += w * vieras_ka * hyok[p["vieras"]]
            paastetty[p["vieras"]] += w * p["k60"]
            odotettu[p["vieras"]] += w * koti_ka * hyok[p["koti"]]
        for j in joukkueet:
            puol[j] = (paastetty[j] + kutistus) / (odotettu[j] + kutistus)

    return {"koti_ka": koti_ka, "vieras_ka": vieras_ka, "hyok": hyok, "puol": puol}


# ===== ENNUSTE (nopea osa) =====
def poisson(maalit, odotus):
    # Todennäköisyys tehdä tasan "maalit" maalia, kun odotus on "odotus"
    return math.exp(-odotus) * odotus ** maalit / math.factorial(maalit)


def maaliodotukset(malli, koti, vieras):
    # Tuntematon joukkue (esim. uusi) = keskitaso
    lk = malli["koti_ka"] * malli["hyok"].get(koti, 1.0) * malli["puol"].get(vieras, 1.0)
    lv = malli["vieras_ka"] * malli["hyok"].get(vieras, 1.0) * malli["puol"].get(koti, 1.0)
    return lk, lv

def vasymyskorjaus(lk, lv, koti_eilen, vieras_eilen, vasymys):
    # Edellisenä päivänä pelannut joukkue tekee vähemmän ja päästää enemmän maaleja.
    # Jos molemmat pelasivat eilen, korjaukset lähes kumoavat toisensa.
    if koti_eilen:
        lk *= 1 - vasymys
        lv *= 1 + vasymys
    if vieras_eilen:
        lv *= 1 - vasymys
        lk *= 1 + vasymys
    return lk, lv


def todennakoisyydet(lk, lv, tasapelikerroin):
    # Tulosjakauma: jokaisen lopputuloksen (k, v) todennäköisyys
    jakauma = {}
    for k in range(MAX_MAALIT):
        for v in range(MAX_MAALIT):
            tn = poisson(k, lk) * poisson(v, lv)
            if k == v:
                tn *= tasapelikerroin      # tasapelikorjaus
            jakauma[(k, v)] = tn

    # Skaalataan summa tasan 1:ksi
    summa = sum(jakauma.values())
    for tulos in jakauma:
        jakauma[tulos] /= summa

    koti60 = sum(tn for (k, v), tn in jakauma.items() if k > v)
    tasan = sum(tn for (k, v), tn in jakauma.items() if k == v)
    vieras60 = sum(tn for (k, v), tn in jakauma.items() if k < v)

    # Jatkoajan voittaja: kumpi tekee todennäköisemmin seuraavan maalin
    koti_jatkoaika = lk / (lk + lv)

    return {
        "lk": lk,
        "lv": lv,
        "koti60": koti60,
        "tasan": tasan,
        "vieras60": vieras60,
        "koti_voittaja": koti60 + tasan * koti_jatkoaika,
        "jakauma": jakauma,
    }


def ennusta(malli, koti, vieras, tasapelikerroin=TASAPELIKERROIN):
    lk, lv = maaliodotukset(malli, koti, vieras)
    return todennakoisyydet(lk, lv, tasapelikerroin)


# ===== WALK-FORWARD-TESTI =====
def keraa_ennusteet(pelit, puoliintuminen=PUOLIINTUMINEN, kutistus=KUTISTUS,
                    kausikerroin=KAUSIKERROIN, vain_alkukausi=False):
    # HIDAS: sovittaa mallin jokaiselle pelipäivälle vain aiemmilla peleillä
    # ja tallentaa maaliodotukset. Ajetaan vain kerran.
    pelit = sorted(pelit, key=lambda p: p["paiva"])
    ennusteet = []
    malli = None
    perus = None
    mallin_paiva = None

    for p in pelit:
        if p["paiva"] < ARVIOINTI_ALKAA:
            continue

        if vain_alkukausi and p["paiva"].month not in ALKUKAUSI_KUUKAUDET:
            continue

        paiva = p["paiva"].date()
        if paiva != mallin_paiva:
            aiemmat = [q for q in pelit if q["paiva"].date() < paiva]
            malli = sovita(aiemmat, p["paiva"], puoliintuminen, kutistus, kausikerroin)
            mallin_paiva = paiva
            n = len(aiemmat)
            perus = {
                "koti": sum(1 for q in aiemmat if q["k60"] > q["v60"]) / n,
                "tasan": sum(1 for q in aiemmat if q["k60"] == q["v60"]) / n,
                "vieras": sum(1 for q in aiemmat if q["k60"] < q["v60"]) / n,
            }

        lk, lv = maaliodotukset(malli, p["koti"], p["vieras"])

        if p["k60"] > p["v60"]:
            tulos = "koti"
        elif p["k60"] == p["v60"]:
            tulos = "tasan"
        else:
            tulos = "vieras"

        ennusteet.append({
            "lk": lk,
            "lv": lv,
            "tulos": tulos,
            "koti_voitti": 1 if p["koti_voitti"] else 0,
            "perus": perus,
            "koti_eilen": p["koti_eilen"],
            "vieras_eilen": p["vieras_eilen"],
        })

    return ennusteet


def pisteyta(ennusteet, tasapelikerroin, vasymys=0):
    # NOPEA: laskee tarkkuuden tallennetuista maaliodotuksista
    brier_1x2 = 0
    brier_perus = 0
    brier_voittaja = 0
    ennustettu_tasan = 0
    toteutunut_tasan = 0

    for e in ennusteet:
        lk, lv = vasymyskorjaus(e["lk"], e["lv"], e["koti_eilen"], e["vieras_eilen"], vasymys)
        t = todennakoisyydet(lk, lv, tasapelikerroin)
        ennuste = {"koti": t["koti60"], "tasan": t["tasan"], "vieras": t["vieras60"]}

        for x in ["koti", "tasan", "vieras"]:
            toteutui = 1 if e["tulos"] == x else 0
            brier_1x2 += (ennuste[x] - toteutui) ** 2
            brier_perus += (e["perus"][x] - toteutui) ** 2

        brier_voittaja += (t["koti_voittaja"] - e["koti_voitti"]) ** 2
        ennustettu_tasan += t["tasan"]
        toteutunut_tasan += 1 if e["tulos"] == "tasan" else 0

    n = len(ennusteet)
    return {
        "1x2": brier_1x2 / n,
        "perus": brier_perus / n,
        "voittaja": brier_voittaja / n,
        "ennustettu_tasan": ennustettu_tasan / n,
        "toteutunut_tasan": toteutunut_tasan / n,
    }


# ===== PÄÄOHJELMA =====
if __name__ == "__main__":
    nyt = datetime.now(timezone.utc)

    # Aloitetaan edellisestä tallennuksesta: jos jonkin sarjan haku epäonnistuu,
    # sen vanha malli jää voimaan eikä katoa
    tallennettavat = {}
    if os.path.exists("poisson.json"):
        with open("poisson.json", "r", encoding="utf-8") as tiedosto:
            vanha = json.load(tiedosto)
        if "hyok" not in vanha:      # vanha muoto (pelkkä Liiga) ohitetaan
            tallennettavat = vanha

    for sarja in SARJA_ASETUKSET:
        asetukset = SARJA_ASETUKSET[sarja]
        pelit = hae_pelit(sarja)
        if len(pelit) == 0:
            print("VAROITUS:", sarja, "- pelejä ei saatu, vanha malli jää voimaan")
            continue

        malli = sovita(pelit, nyt, kausikerroin=asetukset["kausikerroin"])
        # Jokaisen joukkueen viimeisin pelattu päivä (väsymyskorjausta varten)
        viimeisimmat = {}
        for p in pelit:
            paiva = p["paiva"].date().isoformat()     # esim. "2026-10-20"
            for joukkue in [p["koti"], p["vieras"]]:
                if joukkue not in viimeisimmat or paiva > viimeisimmat[joukkue]:
                    viimeisimmat[joukkue] = paiva
        tallennettavat[sarja] = {
            "koti_ka": malli["koti_ka"],
            "vieras_ka": malli["vieras_ka"],
            "hyok": malli["hyok"],
            "puol": malli["puol"],
            "tasapelikerroin": asetukset["tasapelikerroin"],
            "vasymys": asetukset["vasymys"],
            "viimeisin_peli": viimeisimmat,
        }

        print()
        print("=====", sarja, "=====")
        print("Pelejä:", len(pelit))
        print("Keskimäärin maaleja 60 min: koti", round(malli["koti_ka"], 2),
              "| vieras", round(malli["vieras_ka"], 2))
        for j in sorted(malli["hyok"], key=lambda j: malli["hyok"][j] / malli["puol"][j], reverse=True):
            print(f"  {j:16} hyökkäys {malli['hyok'][j]:.2f}   puolustus {malli['puol'][j]:.2f}")

    # Tallennetaan kaikki mallit samaan tiedostoon, jotta laske_value.py voi käyttää niitä
    with open("poisson.json", "w", encoding="utf-8") as tiedosto:
        json.dump(tallennettavat, tiedosto, ensure_ascii=False, indent=2)
    print()
    print("Malli tallennettu sarjoille:", ", ".join(tallennettavat))

    if TESTAA:
        testipelit = hae_pelit(TESTATTAVA_SARJA)
        print()
        print("===== WALK-FORWARD-TESTI:", TESTATTAVA_SARJA, "=====")
        print("Pelejä yhteensä:", len(testipelit))

        # Tarkistus: näyttävätkö joukkueiden voimat järkeviltä?
        testimalli = sovita(testipelit, nyt)
        print("Keskimäärin maaleja 60 min: koti", round(testimalli["koti_ka"], 2),
              "| vieras", round(testimalli["vieras_ka"], 2))
        for j in sorted(testimalli["hyok"],
                        key=lambda j: testimalli["hyok"][j] / testimalli["puol"][j], reverse=True):
            print(f"  {j:16} hyökkäys {testimalli['hyok'][j]:.2f}   puolustus {testimalli['puol'][j]:.2f}")

        print()
        print("NHL-testi, tämä kestää useita minuutteja...")

        for kausikerroin in [0.5]:
            enn = keraa_ennusteet(testipelit, PUOLIINTUMINEN, KUTISTUS, kausikerroin)
            ep = [e for e in enn if e["koti_eilen"] != e["vieras_eilen"]]

            print()
            print("Kausikerroin", kausikerroin, "| arvioituja pelejä", len(enn),
                  "| joista vain toinen pelasi eilen", len(ep))
            print("Tasapelik. | Väsymys | 1X2 Brier | Voittaja Brier | Epätas. 1X2 | Tasapelit enn. / tot.")

            for tasapelikerroin in [1.5, 1.6, 1.7, 1.8]:
                for vasymys in [0.03, 0.045, 0.06, 0.08]:
                    t = pisteyta(enn, tasapelikerroin, vasymys)
                    ep_1x2 = pisteyta(ep, tasapelikerroin, vasymys)["1x2"] if ep else 0
                    print(f"   {tasapelikerroin:4.2f}    |  {vasymys:.2f}   |  {t['1x2']:.5f}  |"
                          f"    {t['voittaja']:.5f}    |   {ep_1x2:.5f}   |"
                          f"  {t['ennustettu_tasan']:.1%} / {t['toteutunut_tasan']:.1%}")

        print()
        print(f"Perustaso 1X2: {t['perus']:.5f}")