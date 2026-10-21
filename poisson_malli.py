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

TESTATTAVA_SARJA = "Liiga"     # kumpaa sarjaa walk-forward-testi koskee: "Liiga" tai "SHL"
PUOLIINTUMINEN = 180     # päivää: näin vanha peli painaa puolet tuoreesta
KUTISTUS = 20             # "keskiarvopelejä", joilla harvoin pelanneet vedetään kohti keskitasoa
KIERROKSET = 30          # montako kertaa voimat lasketaan uudelleen
MAX_MAALIT = 12          # tulosjakaumassa lasketaan maalimäärät 0–11
TASAPELIKERROIN = 1.3    # >1 lisää tasapelejä (Poisson aliarvioi niitä jääkiekossa)
KAUSIKERROIN = 0.5       # edellisen kauden pelien lisäpaino (1.0 = ei vaikutusta)
ALKUKAUSI_KUUKAUDET = [9, 10]   # syys- ja lokakuu = "kauden alku" testissä
# Testeissä löydetyt sarjakohtaiset asetukset
SARJA_ASETUKSET = {
    "Liiga": {"kausikerroin": 0.5, "tasapelikerroin": 1.3,  "vasymys": 0.02, "xg_paino": 0.8},
    "SHL":   {"kausikerroin": 1.0, "tasapelikerroin": 1.15, "vasymys": 0.0,  "xg_paino": 0.0},
    "NHL":   {"kausikerroin": 0.5, "tasapelikerroin": 1.7,  "vasymys": 0.04, "xg_paino": 0.0},
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
        "kxg": peli.get("expectedHomeTeamGoals"),
        "vxg": peli.get("expectedAwayTeamGoals"),
                "id_avain": str(peli["season"]) + "_" + str(peli["id"]),
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
        "kxg": None,
        "vxg": None,
        "id_avain": None,
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
        "kxg": None,
        "vxg": None,
        "id_avain": None,
    }

def aseta_xg(pelit, xg_paino):
    # Mallin "maalit" = sekoitus oikeista maaleista ja odotetuista maaleista (xG).
    # xg_paino 0 = vain oikeat maalit, 1 = vain xG. Jos xG puuttuu, käytetään oikeita.
    for p in pelit:
        if p["kxg"] is None or p["vxg"] is None:
            p["k_malli"] = p["k60"]
            p["v_malli"] = p["v60"]
        else:
            p["k_malli"] = (1 - xg_paino) * p["k60"] + xg_paino * p["kxg"]
            p["v_malli"] = (1 - xg_paino) * p["v60"] + xg_paino * p["vxg"]


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

    # Aloittavat maalivahdit (vain Liiga, tiedosto tehdään hae_maalivahdit.py:llä)
    maalivahdit = {}
    if sarja == "Liiga" and os.path.exists("liiga_maalivahdit.json"):
        with open("liiga_maalivahdit.json", "r", encoding="utf-8") as tiedosto:
            maalivahdit = json.load(tiedosto)

    for p in pelit:
        tieto = maalivahdit.get(p["id_avain"]) if p["id_avain"] else None
        p["koti_mv"] = tieto["koti"]["id"] if tieto and tieto["koti"] else None
        p["vieras_mv"] = tieto["vieras"]["id"] if tieto and tieto["vieras"] else None

    aseta_xg(pelit, 0)      # oletus: vain oikeat maalit
    return pelit

# ===== MALLIN SOVITUS (hidas osa) =====
def sovita(pelit, hetki, puoliintuminen=PUOLIINTUMINEN, kutistus=KUTISTUS,
           kausikerroin=KAUSIKERROIN):
    # Voimat lasketaan kentistä k_malli ja v_malli: oikeat maalit tai
    # sekoitus oikeista maaleista ja xG:stä (ks. aseta_xg).

    # 1. Aikapainot: tuore peli painaa 1, puoliintuminen päivää vanha 0,5 jne.
    painot = []
    nykyinen_kausi = kausi_vuosi(hetki)
    for p in pelit:
        ika_paivina = (hetki - p["paiva"]).days
        kausiero = nykyinen_kausi - p["kausi"]      # 0 = tämä kausi, 1 = viime kausi...
        painot.append(0.5 ** (ika_paivina / puoliintuminen) * kausikerroin ** kausiero)

    # 2. Keskiarvot: mallin maaleista voimien laskentaan,
    #    oikeista maaleista ennusteen maalimäärään
    paino_summa = sum(painot)
    koti_ka = sum(w * p["k_malli"] for w, p in zip(painot, pelit)) / paino_summa
    vieras_ka = sum(w * p["v_malli"] for w, p in zip(painot, pelit)) / paino_summa
    koti_ka_oikea = sum(w * p["k60"] for w, p in zip(painot, pelit)) / paino_summa
    vieras_ka_oikea = sum(w * p["v60"] for w, p in zip(painot, pelit)) / paino_summa

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
            tehty[p["koti"]] += w * p["k_malli"]
            odotettu[p["koti"]] += w * koti_ka * puol[p["vieras"]]
            tehty[p["vieras"]] += w * p["v_malli"]
            odotettu[p["vieras"]] += w * vieras_ka * puol[p["koti"]]
        for j in joukkueet:
            hyok[j] = (tehty[j] + kutistus) / (odotettu[j] + kutistus)

        paastetty = {j: 0.0 for j in joukkueet}
        odotettu = {j: 0.0 for j in joukkueet}
        for w, p in zip(painot, pelit):
            paastetty[p["koti"]] += w * p["v_malli"]
            odotettu[p["koti"]] += w * vieras_ka * hyok[p["vieras"]]
            paastetty[p["vieras"]] += w * p["k_malli"]
            odotettu[p["vieras"]] += w * koti_ka * hyok[p["koti"]]
        for j in joukkueet:
            puol[j] = (paastetty[j] + kutistus) / (odotettu[j] + kutistus)

    return {"koti_ka": koti_ka_oikea, "vieras_ka": vieras_ka_oikea, "hyok": hyok, "puol": puol}

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

def maalivahtien_summat(pelit):
    # Jokaiselle maalivahdille: (odotetut − päästetyt maalit, odotetut maalit),
    # keskitettynä niin, että liigan keskitaso on 0.
    erotus = {}
    odotettu = {}
    kaikki_erotus = 0
    kaikki_odotettu = 0
    for p in pelit:
        if p["kxg"] is None:
            continue
        # Kotimaalivahti kohtasi vieraiden maalipaikat ja päinvastoin
        for mv, paastetyt, xg_vastaan in [(p["koti_mv"], p["v60"], p["vxg"]),
                                          (p["vieras_mv"], p["k60"], p["kxg"])]:
            kaikki_erotus += xg_vastaan - paastetyt
            kaikki_odotettu += xg_vastaan
            if mv is None:
                continue
            erotus[mv] = erotus.get(mv, 0) + (xg_vastaan - paastetyt)
            odotettu[mv] = odotettu.get(mv, 0) + xg_vastaan

    if kaikki_odotettu == 0:
        return {}
    keskitaso = kaikki_erotus / kaikki_odotettu
    return {mv: (erotus[mv] - keskitaso * odotettu[mv], odotettu[mv]) for mv in erotus}


def mv_taso(summat, kutistus):
    # Maalivahdin taso: +0.05 = päästää 5 % odotettua vähemmän
    if summat is None:
        return 0
    erotus, odotettu = summat
    return erotus / (odotettu + kutistus)

def todennakoinen_aloittaja(aiemmat, joukkue, paiva, kierratys, n=5):
    # Arvaa aloittajan joukkueen viimeisestä n pelistä: useimmin aloittanut,
    # tasatilanteessa tuorein. Kierrätys: jos joukkue pelasi eilen, eilinen
    # aloittaja oletetaan lepäävän (jos joukkueella on muitakin vahteja).
    viimeiset = []      # (maalivahti, pelipäivä), uusin ensin
    for q in reversed(aiemmat):
        if q["koti"] == joukkue:
            viimeiset.append((q["koti_mv"], q["paiva"].date()))
        elif q["vieras"] == joukkue:
            viimeiset.append((q["vieras_mv"], q["paiva"].date()))
        if len(viimeiset) == n:
            break

    if len(viimeiset) == 0:
        return None

    ehdokkaat = [mv for mv, _ in viimeiset]
    if kierratys and viimeiset[0][1] == paiva - timedelta(days=1):
        eilinen = viimeiset[0][0]
        muut = [mv for mv in ehdokkaat if mv != eilinen]
        if muut:
            ehdokkaat = muut

    return max(ehdokkaat, key=lambda mv: (ehdokkaat.count(mv), -ehdokkaat.index(mv)))

def viimeiset_aloittajat(aiemmat, joukkue, paiva, kierratys, n=10):
    # Lista joukkueen viimeisen n pelin aloittajista. Kierrätys: jos joukkue
    # pelasi eilen, eilinen aloittaja poistetaan listasta (jos muita on).
    viimeiset = []
    for q in reversed(aiemmat):
        if q["koti"] == joukkue:
            viimeiset.append((q["koti_mv"], q["paiva"].date()))
        elif q["vieras"] == joukkue:
            viimeiset.append((q["vieras_mv"], q["paiva"].date()))
        if len(viimeiset) == n:
            break

    lista = [mv for mv, _ in viimeiset]
    if kierratys and viimeiset and viimeiset[0][1] == paiva - timedelta(days=1):
        muut = [mv for mv in lista if mv != viimeiset[0][0]]
        if muut:
            lista = muut
    return lista


def mv_taso_lahteesta(e, puoli, lahde, kutistus):
    # Yksi maalivahti -> sen taso. Lista maalivahteja -> tasojen keskiarvo.
    arvo = e[puoli + "_mv" + lahde]
    if isinstance(arvo, list):
        if len(arvo) == 0:
            return 0
        return sum(mv_taso(s, kutistus) for s in arvo) / len(arvo)
    return mv_taso(arvo, kutistus)

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
        paiva_nyt = p["paiva"].date()
        e1_koti = todennakoinen_aloittaja(aiemmat, p["koti"], paiva_nyt, False)
        e1_vieras = todennakoinen_aloittaja(aiemmat, p["vieras"], paiva_nyt, False)
        e2_koti = todennakoinen_aloittaja(aiemmat, p["koti"], paiva_nyt, True)
        e2_vieras = todennakoinen_aloittaja(aiemmat, p["vieras"], paiva_nyt, True)
        e3_koti = viimeiset_aloittajat(aiemmat, p["koti"], paiva_nyt, False)
        e3_vieras = viimeiset_aloittajat(aiemmat, p["vieras"], paiva_nyt, False)
        e4_koti = viimeiset_aloittajat(aiemmat, p["koti"], paiva_nyt, True)
        e4_vieras = viimeiset_aloittajat(aiemmat, p["vieras"], paiva_nyt, True)

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
            "koti_mv": summat.get(p["koti_mv"]),
            "vieras_mv": summat.get(p["vieras_mv"]),
            "koti_mv_e1": summat.get(e1_koti),
            "vieras_mv_e1": summat.get(e1_vieras),
            "koti_mv_e2": summat.get(e2_koti),
            "vieras_mv_e2": summat.get(e2_vieras),
            "osumat_e1": (e1_koti == p["koti_mv"]) + (e1_vieras == p["vieras_mv"]),
            "osumat_e2": (e2_koti == p["koti_mv"]) + (e2_vieras == p["vieras_mv"]),
            "koti_mv_e3": [summat.get(mv) for mv in e3_koti],
            "vieras_mv_e3": [summat.get(mv) for mv in e3_vieras],
            "koti_mv_e4": [summat.get(mv) for mv in e4_koti],
            "vieras_mv_e4": [summat.get(mv) for mv in e4_vieras],
        })

    return ennusteet


def pisteyta(ennusteet, tasapelikerroin, vasymys=0, mv_paino=0, mv_kutistus=30, mv_lahde=""):
    # NOPEA: laskee tarkkuuden tallennetuista maaliodotuksista
    brier_1x2 = 0
    brier_perus = 0
    brier_voittaja = 0
    ennustettu_tasan = 0
    toteutunut_tasan = 0

    for e in ennusteet:
        lk, lv = vasymyskorjaus(e["lk"], e["lv"], e["koti_eilen"], e["vieras_eilen"], vasymys)
        # Vastustajan maalivahti vähentää (tai lisää) joukkueen maaliodotusta
        # mv_lahde: "" = oikea aloittaja, "_e1" = arvaus, "_e2" = arvaus + kierrätys
        lk *= 1 - mv_paino * mv_taso_lahteesta(e, "vieras", mv_lahde, mv_kutistus)
        lv *= 1 - mv_paino * mv_taso_lahteesta(e, "koti", mv_lahde, mv_kutistus)
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

        aseta_xg(pelit, asetukset["xg_paino"])

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
        asetukset = SARJA_ASETUKSET[TESTATTAVA_SARJA]
        aseta_xg(testipelit, asetukset["xg_paino"])

        # Tarkistus: parhaat ja heikoimmat maalivahdit
        with open("liiga_maalivahdit.json", "r", encoding="utf-8") as tiedosto:
            nimet = {}
            for tieto in json.load(tiedosto).values():
                for puoli in ["koti", "vieras"]:
                    if tieto[puoli]:
                        nimet[tieto[puoli]["id"]] = tieto[puoli]["nimi"]
        summat = maalivahtien_summat(testipelit)
        jarjestys = sorted(summat, key=lambda mv: mv_taso(summat[mv], 30), reverse=True)
        print()
        print("Parhaat ja heikoimmat maalivahdit (kutistus 30):")
        for mv in jarjestys[:5] + jarjestys[-5:]:
            print(f"  {nimet.get(mv, mv):25} taso {mv_taso(summat[mv], 30):+.3f}"
                  f"   (odotettuja maaleja {summat[mv][1]:.0f})")

        print()        
        print("Maalivahtitesti, tämä kestää pari minuuttia...")
        enn = keraa_ennusteet(testipelit, PUOLIINTUMINEN, KUTISTUS, asetukset["kausikerroin"])

        n = len(enn)
        print()
        print(f"Arvaus osui: ykkösvahti {sum(e['osumat_e1'] for e in enn) / (2 * n):.1%}"
              f" | ykkösvahti + kierrätys {sum(e['osumat_e2'] for e in enn) / (2 * n):.1%}")
        print()
        print("Aloittaja              | MV-paino | Kutistus | 1X2 Brier | Voittaja Brier")

        tavat = [("", "oikea (tiedossa)"), ("_e1", "arvaus: ykkösvahti"), ("_e2", "arvaus + kierrätys"),
                 ("_e3", "pehmeä arvaus"), ("_e4", "pehmeä + kierrätys")]
        for lahde, nimi in tavat:
            for mv_paino in [0.5, 1.0]:
                for mv_kutistus in [5, 10, 20]:
                    t = pisteyta(enn, asetukset["tasapelikerroin"], asetukset["vasymys"],
                                 mv_paino, mv_kutistus, lahde)
                    print(f"{nimi:22} |   {mv_paino:.1f}    |   {mv_kutistus:3}    |  {t['1x2']:.5f}  |"
                          f"    {t['voittaja']:.5f}")
            print()

        t = pisteyta(enn, asetukset["tasapelikerroin"], asetukset["vasymys"])
        print(f"Ilman maalivahtia: 1X2 {t['1x2']:.5f} | Voittaja {t['voittaja']:.5f}")
        print(f"Perustaso 1X2: {t['perus']:.5f}")