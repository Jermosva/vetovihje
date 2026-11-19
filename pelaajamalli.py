import json
import math
import os
import re
import time
import unicodedata
from datetime import datetime, date, timedelta
import requests

from hae_maalivahdit import TAUKO, pelipaikka

# Pelaajamalli: todennäköisyys, että pelaaja tekee illan pelissä vähintään
# 1/2/3 maalia, syöttöä tai pistettä (jatkoaika mukaan, voittolaukaukset ei).
#
# 1. Pelaajan taso = suhdeluku roolinsa keskitasoon (rooli = pelipaikka + ketju):
#       taso = (toteutuneet + KUTISTUS) / (roolin odotus + KUTISTUS)
#    Sama kutistus kuin poisson_malli.py:n hyökkäysvoimissa: vähän pelannut
#    pelaaja vedetään kohti roolinsa keskitasoa (taso 1.0).
# 2. Muoto: viimeisten MUOTO_PELIT pelin taso, painolla MUOTO_PAINO.
# 3. Illan odotus = taso × illan roolin keskitaso × ottelukerroin, jossa
#    ottelukerroin = vastustajan puolustus × vastustajan maalivahti × koti/vieras × väsymys.
# 4. Todennäköisyys Poisson-jakaumasta: P(≥1) = 1 − e^(−λ). Pisteille λ = maalit + syötöt.

# ===== ASETUKSET =====
PELAAJADATA = "liiga_pelaajat.json"
POISSON = "poisson.json"
ENNUSTEET = "pelaajaennusteet.json"
VARJO = "pelaajavarjo.json"
LIIGA_KAUSI = 2027
VERSIO = 2                # 2 = sivu laskee ennusteet itse liiga.fi:n kokoonpanosta

# Walk-forward-testissä valitut arvot (ks. testin tuloste)
PUOLIINTUMINEN = 480      # päivää: näin vanha peli painaa puolet tuoreesta
KAUSIKERROIN = 0.7        # edellisen kauden pelien lisäpaino (1.0 = ei vaikutusta)
KUTISTUS_MAALIT = 5       # "keskitason maaleja", joilla pelaaja vedetään kohti roolinsa tasoa
KUTISTUS_SYOTOT = 8       # sama syötöille
MUOTO_PELIT = 15          # montako viimeistä peliä on "muoto"
MUOTO_PAINO = 0.3         # muodon paino (0 = ei muotoa, 1 = vain muoto). Testissä 0,2–0,3 yhtä
                          # hyviä kaikilla pelaajilla, mutta nousijoilla 0,3 osui oikeaan (0,2 aliarvioi)
MUOTO_KUTISTUS = 1        # muodon tasoa vedetään kohti pitkän ajan tasoa
OTTELUKERROIN_PAINO = 0.5  # 1 = ottelukerroin täysimääräisenä, 0 = ei vaikutusta
NOUSIJA_RAJA = 0.25       # nousija: odotus vähintään 25 % yli pelaajan tason ennen tätä kautta
NOUSIJA_MIN_PELIT = 8     # ja tällä kaudella vähintään näin monta peliä
AIKAKATKAISU = 30         # sekuntia: jumiin jäänyt haku ei saa pysäyttää GitHub Actionsia

# Unibetin, Pafin ja LeoVegasin pelaajavetojen kertoimet (Kambi, samat kaikilla kolmella).
# Tallennetaan varjokirjanpitoon, jotta vihjeiden tuotto voidaan mitata ilman omaa vaivaa.
# Sama logiikka kuin sivulla (pelaajat.js), jotta mitataan samoja vihjeitä.
KAMBI_OSOITE = "https://eu-offering-api.kambicdn.com/offering/v2018/ub/"
KAMBI_JOUKKUEET = {"K-Espoo": "Espoo"}     # liiga.fi:n nimi -> Kambin nimen osa
KAMBI_TYYPIT = ["maalit_1", "syotot_1", "pisteet_1", "pisteet_2"]   # testatut vetotyypit

TESTAA = False            # True = aja walk-forward-testi (hidas), False = vain illan ennusteet
ARVIOINTI_ALKAA = "2025-09-01"   # arvioidaan kaudet 2025–26 ja 2026–27


# ===== DATA =====
def kausi_vuosi(paiva):
    # Liigan kausi nimetään päättymisvuoden mukaan: syyskuu 2026 -> 2027
    if paiva.month >= 7:
        return paiva.year + 1
    return paiva.year


def rooli(paikka, rooli_koodi, ketju):
    # Esim. "H1" = ykkösketjun hyökkääjä, "P2" = kakkospari.
    # 13. hyökkääjä ja 7. puolustaja pelaavat vähän, joten ne ovat omia ryhmiään.
    # Samoin muut numeroidut lisäpelaajat ("14. H", "8. P") ja harvinaiset yhdistelmät
    # (puolustaja ketjussa 4, hyökkääjä ketjussa 5).
    lisapelaaja = bool(rooli_koodi) and rooli_koodi[0].isdigit()
    if paikka == "H" and (lisapelaaja or ketju >= 5):
        return "H13"
    if paikka == "P" and (lisapelaaja or ketju >= 4):
        return "P7"
    return paikka + str(ketju)


def lue_pelit():
    # Lukee hae_maalivahdit.py:n keräämän datan ja palauttaa pelit aikajärjestyksessä:
    # jokaisella pelillä lista pelaajarivejä (pelaaja, joukkue, vastustaja, rooli, maalit, syötöt)
    with open(PELAAJADATA, "r", encoding="utf-8") as tiedosto:
        data = json.load(tiedosto)

    pelit = []
    for avain, peli in data["pelit"].items():
        paiva = date.fromisoformat(peli["alkaa"][:10])
        rivit = []
        for pelaaja_id, puoli, paikka, koodi, ketju, m, s, _ in peli["pelaajat"]:
            koti = puoli == "K"
            rivit.append({
                "id": pelaaja_id,
                "joukkue": peli["koti"] if koti else peli["vieras"],
                "koti": koti,
                "paikka": paikka,
                "rooli": rooli(paikka, koodi, ketju),
                "ketju": ketju,
                "m": m,
                "s": s,
            })
        pelit.append({"avain": avain, "paiva": paiva, "kausi": kausi_vuosi(paiva),
                      "koti": peli["koti"], "vieras": peli["vieras"], "rivit": rivit})

    pelit.sort(key=lambda p: (p["paiva"], p["avain"]))
    return pelit, data["nimet"]


# ===== MALLI =====
def paino(paiva, kausi, hetki, kausi_nyt, puoliintuminen, kausikerroin):
    # Aikapaino kuten poisson_malli.py:ssä: tuore peli 1, puoliintuminen päivää vanha 0,5
    ika = (hetki - paiva).days
    return 0.5 ** (ika / puoliintuminen) * kausikerroin ** (kausi_nyt - kausi)


def roolien_tahdit(pelit, hetki, puoliintuminen=PUOLIINTUMINEN, kausikerroin=KAUSIKERROIN,
                   ryhma="rooli"):
    # Liigan keskitaso jokaiselle roolille: (maaleja per peli, syöttöjä per peli).
    # ryhma="paikka" antaa keskitason pelkälle pelipaikalle (H/P).
    kausi_nyt = kausi_vuosi(hetki)
    summat = {}     # rooli -> [paino, maalit, syötöt]
    for p in pelit:
        w = paino(p["paiva"], p["kausi"], hetki, kausi_nyt, puoliintuminen, kausikerroin)
        for r in p["rivit"]:
            s = summat.setdefault(r[ryhma], [0, 0, 0])
            s[0] += w
            s[1] += w * r["m"]
            s[2] += w * r["s"]
    return {rooli: (s[1] / s[0], s[2] / s[0]) for rooli, s in summat.items() if s[0] > 0}


def pelaajan_summat(historia, hetki, tahdit, muoto_pelit=MUOTO_PELIT,
                    puoliintuminen=PUOLIINTUMINEN, kausikerroin=KAUSIKERROIN):
    # historia: pelaajan aiemmat pelit aikajärjestyksessä [(päivä, kausi, rooli, maalit, syötöt)]
    # Palauttaa summat: toteutuneet ja roolin perusteella odotetut.
    #   koko  = kaikki pelit aikapainoin
    #   muoto = viimeiset muoto_pelit peliä ilman aikapainoa
    kausi_nyt = kausi_vuosi(hetki)
    koko = [0.0, 0.0, 0.0, 0.0]     # maalit, odotetut maalit, syötöt, odotetut syötöt
    muoto = [0.0, 0.0, 0.0, 0.0]
    raja = len(historia) - muoto_pelit
    for i, (paiva, kausi, r, m, s) in enumerate(historia):
        em, es = tahdit.get(r, (0, 0))
        w = paino(paiva, kausi, hetki, kausi_nyt, puoliintuminen, kausikerroin)
        rivi = (m, em, s, es)
        for j in range(4):
            koko[j] += w * rivi[j]
        if i >= raja:
            for j in range(4):
                muoto[j] += rivi[j]
    return koko, muoto


def tasot(koko, muoto, kutistus_m=KUTISTUS_MAALIT, kutistus_s=KUTISTUS_SYOTOT,
          muoto_paino=MUOTO_PAINO, muoto_kutistus=MUOTO_KUTISTUS):
    # Pelaajan taso (suhdeluku roolin keskitasoon) maaleille ja syötöille
    tulos = []
    for j, kutistus in [(0, kutistus_m), (2, kutistus_s)]:
        pitka = (koko[j] + kutistus) / (koko[j + 1] + kutistus)
        # Muoto vedetään kohti pitkän ajan tasoa, jottei yksi hyvä ilta heilauta liikaa
        lyhyt = (muoto[j] + muoto_kutistus * pitka) / (muoto[j + 1] + muoto_kutistus)
        tulos.append((1 - muoto_paino) * pitka + muoto_paino * lyhyt)
    return tulos


def ottelukerroin(pmalli, joukkue, vastustaja, koti, vastustajan_mv, joukkue_eilen, vastustaja_eilen):
    # Joukkueen odotetut maalit tässä ottelussa suhteessa sen tavalliseen tasoon.
    # Joukkueen oma hyökkäys on jo pelaajan tasossa, joten se jätetään pois.
    ka = (pmalli["koti_ka"] + pmalli["vieras_ka"]) / 2
    kerroin = (pmalli["koti_ka"] if koti else pmalli["vieras_ka"]) / ka
    kerroin *= pmalli["puol"].get(vastustaja, 1.0)
    kerroin *= 1 - pmalli.get("mv_paino", 0) * pmalli.get("mv_tasot", {}).get(str(vastustajan_mv), 0)
    vasymys = pmalli.get("vasymys", 0)
    if joukkue_eilen:
        kerroin *= 1 - vasymys
    if vastustaja_eilen:
        kerroin *= 1 + vasymys
    return kerroin


def vahintaan(lam, k):
    # Poisson: P(X ≥ k) = 1 − P(0) − ... − P(k−1)
    return 1 - sum(math.exp(-lam) * lam ** i / math.factorial(i) for i in range(k))


def todennakoisyydet(lam_m, lam_s):
    lam_p = lam_m + lam_s
    return {
        "maalit_1": vahintaan(lam_m, 1), "maalit_2": vahintaan(lam_m, 2),
        "syotot_1": vahintaan(lam_s, 1), "syotot_2": vahintaan(lam_s, 2),
        "pisteet_1": vahintaan(lam_p, 1), "pisteet_2": vahintaan(lam_p, 2),
        "pisteet_3": vahintaan(lam_p, 3),
    }


def historiat(pelit, ennen):
    # Jokaisen pelaajan aiemmat pelit ennen annettua päivää
    tulos = {}
    for p in pelit:
        if p["paiva"] >= ennen:
            break
        for r in p["rivit"]:
            tulos.setdefault(r["id"], []).append((p["paiva"], p["kausi"], r["rooli"], r["m"], r["s"]))
    return tulos


# ===== ILLAN ENNUSTEET =====
def hae_json(osoite):
    # None = haku epäonnistui (ei kaadeta ajoa, mutta ei myöskään tallenneta vajaita ennusteita)
    try:
        vastaus = requests.get(osoite, timeout=AIKAKATKAISU)
    except requests.RequestException as virhe:
        print("VIRHE:", osoite, virhe)
        return None
    if vastaus.status_code != 200:
        print("VIRHE:", osoite, vastaus.status_code)
        return None
    return vastaus.json()


def illan_pelit(ohjelma, tanaan):
    # Ensimmäinen pelipäivä tänään tai myöhemmin, jolla on päättymättömiä pelejä. Mukaan
    # koko päivä, myös jo alkaneet pelit, jotta myöhässä käynnistyvä ajo ei pudota niitä.
    tulevat = [p for p in ohjelma if not p["ended"] and p["start"][:10] >= tanaan.isoformat()]
    if not tulevat:
        return None, []
    paiva = min(p["start"][:10] for p in tulevat)
    return paiva, sorted([p for p in ohjelma if p["start"][:10] == paiva], key=lambda p: p["start"])


def kokoonpano(pelaajat):
    # Illan kokoonpano: kenttäpelaajat, joilla on ketju, ja aloittava maalivahti
    kentalla = [p for p in pelaajat if p.get("line") is not None and p.get("role") != "GOALIE"]
    vahti = None
    for p in pelaajat:
        if p.get("role") == "GOALIE" and p.get("line") == 1:
            vahti = p["id"]
    return kentalla, vahti


def tee_ennusteet(pelit, nimet, pmalli, tanaan):
    # Palauttaa None, jos jokin haku epäonnistui: silloin edellinen tiedosto jää voimaan
    ohjelma = hae_json("https://liiga.fi/api/v2/schedule?tournament=runkosarja&season=" + str(LIIGA_KAUSI))
    if ohjelma is None:
        return None
    paiva, illan = illan_pelit(ohjelma, tanaan)
    if paiva is None:
        print("Ei tulevia pelejä")
        return {"paivitetty": datetime.now().astimezone().isoformat(timespec="minutes"),
                "pvm": None, "versio": VERSIO, "viime_pelit": MUOTO_PELIT, "ottelut": []}

    hetki = date.fromisoformat(paiva)
    tahdit = roolien_tahdit([p for p in pelit if p["paiva"] < hetki], hetki)
    pelaajien_historia = historiat(pelit, hetki)
    kausi_nyt = kausi_vuosi(hetki)
    eilen = (hetki - timedelta(days=1)).isoformat()
    viimeisimmat = pmalli.get("viimeisin_peli", {})

    ottelut = []
    for peli in illan:
        avain = str(peli["season"]) + "_" + str(peli["id"])
        koti, vieras = peli["homeTeamName"], peli["awayTeamName"]
        data = hae_json("https://liiga.fi/api/v2/games/" + str(peli["season"]) + "/" + str(peli["id"]))
        time.sleep(TAUKO)
        if data is None:
            return None
        koti_kp, koti_mv = kokoonpano(data.get("homeTeamPlayers", []))
        vieras_kp, vieras_mv = kokoonpano(data.get("awayTeamPlayers", []))
        valmis = len(koti_kp) > 0 and len(vieras_kp) > 0

        koti_eilen = viimeisimmat.get(koti) == eilen
        vieras_eilen = viimeisimmat.get(vieras) == eilen
        kertoimet = {
            True: ottelukerroin(pmalli, koti, vieras, True, vieras_mv, koti_eilen, vieras_eilen),
            False: ottelukerroin(pmalli, vieras, koti, False, koti_mv, vieras_eilen, koti_eilen),
        }
        ka = (pmalli["koti_ka"] + pmalli["vieras_ka"]) / 2
        odotetut = [ka * pmalli["hyok"].get(koti, 1) * kertoimet[True],
                    ka * pmalli["hyok"].get(vieras, 1) * kertoimet[False]]

        # Koko pelaajiston tasot (myös ne, jotka eivät ole vielä kokoonpanossa). Sivu hakee
        # illan kokoonpanon itse liiga.fi:stä ja laskee niistä ennusteet, joten ennusteet
        # eivät riipu siitä, milloin GitHubin ajastettu ajo sattuu käynnistymään.
        pelaajatasot = {}
        for puoli, avain_pelaajat in [("K", "homeTeamPlayers"), ("V", "awayTeamPlayers")]:
            for p in data.get(avain_pelaajat, []):
                if p.get("role") == "GOALIE":
                    continue
                t = pelaajan_tasot(pelaajien_historia.get(p["id"], []), hetki, tahdit, kausi_nyt)
                t["nimi"] = p["firstName"] + " " + p["lastName"]
                t["puoli"] = puoli
                pelaajatasot[str(p["id"])] = t
        mv_tasot = pmalli.get("mv_tasot", {})
        vahdit = {str(p["id"]): round(mv_tasot.get(str(p["id"]), 0), 4)
                  for p in data.get("homeTeamPlayers", []) + data.get("awayTeamPlayers", [])
                  if p.get("role") == "GOALIE"}
        # Ottelukerroin ilman vastustajan maalivahtia: sivu lisää sen aloittajan mukaan
        pohja = [ottelukerroin(pmalli, koti, vieras, True, None, koti_eilen, vieras_eilen),
                 ottelukerroin(pmalli, vieras, koti, False, None, vieras_eilen, koti_eilen)]

        rivit = []
        if valmis:
            for on_koti, kp, joukkue in [(True, koti_kp, koti), (False, vieras_kp, vieras)]:
                kerroin = kertoimet[on_koti] ** OTTELUKERROIN_PAINO
                for p in kp:
                    t = pelaajatasot.get(str(p["id"])) or pelaajan_tasot(
                        pelaajien_historia.get(p["id"], []), hetki, tahdit, kausi_nyt)
                    rivit.append(pelaajan_ennuste(p, joukkue, kerroin, tahdit, t))

        rivit.sort(key=lambda r: r["tn"]["pisteet_1"], reverse=True)
        ottelut.append({"avain": avain, "alkaa": peli["start"], "koti": koti, "vieras": vieras,
                        "paattynyt": peli["ended"],
                        "odotetut_maalit": [round(x, 2) for x in odotetut],
                        "kokoonpano": valmis, "pelaajat": rivit,
                        "kerroin_pohja": [round(x, 4) for x in pohja],
                        "vahdit": vahdit, "pelaajatasot": pelaajatasot})
        print(f"{koti} - {vieras}: " + (f"{len(rivit)} pelaajaa" if valmis else "kokoonpano puuttuu"))

    # Mallin osat, joilla sivu laskee ennusteet itse (sama laskenta kuin pelaajan_ennuste)
    malli = {"tahdit": {r: [round(em, 5), round(es, 5)] for r, (em, es) in tahdit.items()},
             "ottelukerroin_paino": OTTELUKERROIN_PAINO, "mv_paino": pmalli.get("mv_paino", 0),
             "nousija_raja": NOUSIJA_RAJA, "nousija_min_pelit": NOUSIJA_MIN_PELIT}
    return {"paivitetty": datetime.now().astimezone().isoformat(timespec="minutes"),
            "pvm": paiva, "versio": VERSIO, "viime_pelit": MUOTO_PELIT, "malli": malli,
            "ottelut": ottelut}


def pelaajan_tasot(historia, hetki, tahdit, kausi_nyt):
    # Pelaajan tasot, jotka eivät riipu illan roolista: taso = suhdeluku roolin
    # keskitasoon (maalit, syötöt), aiempi = sama ennen tätä kautta (nousijat).
    # Pyöristys 4 desimaaliin, jotta sivu ja tämä tiedosto laskevat saman tuloksen.
    koko, muoto = pelaajan_summat(historia, hetki, tahdit)
    taso_m, taso_s = tasot(koko, muoto)
    # Uusi pelaaja = roolinsa keskitaso (taso 1)
    aiempi, _ = pelaajan_summat([h for h in historia if h[1] < kausi_nyt], hetki, tahdit, 0)
    aiempi_m, aiempi_s = tasot(aiempi, [0, 0, 0, 0], muoto_paino=0)
    kauden = [h for h in historia if h[1] == kausi_nyt]
    viime = historia[-MUOTO_PELIT:]
    km = sum(h[3] for h in kauden)
    ks = sum(h[4] for h in kauden)
    vm = sum(h[3] for h in viime)
    vs = sum(h[4] for h in viime)
    return {
        "taso": [round(taso_m, 4), round(taso_s, 4)],
        "aiempi": [round(aiempi_m, 4), round(aiempi_s, 4)],
        "kausi": {"ottelut": len(kauden), "maalit": km, "syotot": ks, "pisteet": km + ks},
        "viime": {"ottelut": len(viime), "maalit": vm, "syotot": vs, "pisteet": vm + vs},
    }


def pelaajan_ennuste(p, joukkue, kerroin, tahdit, t):
    # Illan ennuste: pelaajan taso × illan roolin keskitaso × ottelukerroin
    paikka = pelipaikka(p)
    r = rooli(paikka, p.get("roleCode"), p["line"])
    em, es = tahdit.get(r, tahdit.get(paikka + "4", (0.05, 0.1)))
    lam_m = t["taso"][0] * em * kerroin
    lam_s = t["taso"][1] * es * kerroin

    # Nousija: mallin odotus verrattuna pelaajan tasoon ennen tätä kautta. Vetoyhtiöt
    # nojaavat usein tähän vanhaan tasoon. Ottelukerroin supistuu suhteesta pois.
    aiempi_lam = (t["aiempi"][0] * em + t["aiempi"][1] * es) * kerroin
    nosto = (lam_m + lam_s) / aiempi_lam - 1
    nousija = None
    if nosto >= NOUSIJA_RAJA and t["kausi"]["ottelut"] >= NOUSIJA_MIN_PELIT:
        nousija = {"nosto": round(nosto, 2), "aiempi": round(aiempi_lam, 3),
                   "nyt": round(lam_m + lam_s, 3)}

    return {
        "id": p["id"], "nimi": p["firstName"] + " " + p["lastName"], "joukkue": joukkue,
        "pp": paikka, "ketju": p["line"],
        "kausi": t["kausi"],
        "viime": t["viime"],
        "lambda": {"maalit": round(lam_m, 3), "syotot": round(lam_s, 3)},
        "tn": {k: round(v, 4) for k, v in todennakoisyydet(lam_m, lam_s).items()},
        "nousija": nousija,
    }


# ===== KAMBI-KERTOIMET =====
def vertailunimi(nimi):
    # "Jiří Ticháček" -> "jiri tichacek", "K-Espoo" -> "k espoo"
    nimi = unicodedata.normalize("NFD", (nimi or "").lower())
    nimi = "".join(merkki for merkki in nimi if not unicodedata.combining(merkki))
    return re.sub(r"[^a-z0-9]+", " ", nimi).strip()


def sama_joukkue(liiga_nimi, kambi_nimi):
    a = vertailunimi(KAMBI_JOUKKUEET.get(liiga_nimi, liiga_nimi))
    b = vertailunimi(kambi_nimi)
    return a != "" and b != "" and (a in b or b in a)


def kambi_vetotyyppi(markkina, raja):
    # "Player to score at least 2 points - Including Overtime" + 2 -> "pisteet_2"
    nimi = markkina.lower()
    if "including overtime" not in nimi or "1st" in nimi or "last" in nimi:
        return None
    if "assist" in nimi:
        tyyppi = "syotot"
    elif "point" in nimi:
        tyyppi = "pisteet"
    elif nimi.startswith("to score"):
        tyyppi = "maalit"
    else:
        return None
    avain = tyyppi + "_" + str(raja)
    return avain if avain in KAMBI_TYYPIT else None


def lue_pelaajakertoimet(tarjoukset):
    # -> {pelaajan vertailunimi: {vetotyyppi: [kerroin, markkina]}}
    # markkina = yhtiön oma todennäköisyys ilman marginaalia (None, jos "Ei" puuttuu)
    kylla = {}
    ei = {}
    for tarjous in tarjoukset or []:
        for vaihtoehto in tarjous.get("outcomes", []):
            if not vaihtoehto.get("participant") or vaihtoehto.get("status") != "OPEN" \
                    or not vaihtoehto.get("odds"):
                continue
            raja = round((vaihtoehto.get("line") or 1000) / 1000)
            avain = kambi_vetotyyppi(tarjous["criterion"].get("englishLabel", ""), raja)
            if avain is None:
                continue
            kohde = ei if vaihtoehto.get("type") == "OT_NO" else kylla
            kohde[(vertailunimi(vaihtoehto["participant"]), avain)] = vaihtoehto["odds"] / 1000
    tulos = {}
    for (nimi, avain), kerroin in kylla.items():
        markkina = None
        if (nimi, avain) in ei:
            markkina = round((1 / kerroin) / (1 / kerroin + 1 / ei[(nimi, avain)]), 4)
        tulos.setdefault(nimi, {})[avain] = [kerroin, markkina]
    return tulos


def pelaajan_kertoimet(kertoimet, nimi, omat_nimet):
    # Sama nimi, samat nimen osat eri järjestyksessä tai sukunimi + alkukirjain.
    # Varanimeksi ei kelpaa toisen saman ottelun pelaajan oma nimi.
    nimi = vertailunimi(nimi)
    if nimi in kertoimet:
        return kertoimet[nimi]
    osat = nimi.split(" ")
    ehdokkaat_kaikki = [n for n in kertoimet if n not in omat_nimet]
    kokeilut = [
        lambda n: sorted(n.split(" ")) == sorted(osat),
        lambda n: n.split(" ")[1:] == osat[1:] and n[:1] == osat[0][:1],
    ]
    for kokeilu in kokeilut:
        ehdokkaat = [n for n in ehdokkaat_kaikki if kokeilu(n)]
        if len(ehdokkaat) == 1:
            return kertoimet[ehdokkaat[0]]
    return {}


def hae_kambi_kertoimet(ottelut):
    # -> {ottelun avain: {"pelaaja_id": {vetotyyppi: [kerroin, markkina]}}}
    lista = hae_json(KAMBI_OSOITE + "listView/ice_hockey/finland/liiga/all/matches.json"
                     "?lang=en_GB&market=FI")
    if lista is None:
        return {}
    tulos = {}
    for ottelu in ottelut:
        if not ottelu["kokoonpano"]:
            continue
        alkaa = datetime.fromisoformat(ottelu["alkaa"].replace("Z", "+00:00"))
        pari = None
        for k in lista.get("events", []):
            tapahtuma = k["event"]
            kambi_alkaa = datetime.fromisoformat(tapahtuma["start"].replace("Z", "+00:00"))
            if sama_joukkue(ottelu["koti"], tapahtuma.get("homeName")) \
                    and sama_joukkue(ottelu["vieras"], tapahtuma.get("awayName")) \
                    and abs((kambi_alkaa - alkaa).total_seconds()) < 3 * 3600:
                pari = tapahtuma["id"]
        if pari is None:
            continue
        data = hae_json(KAMBI_OSOITE + "betoffer/event/" + str(pari) + ".json?lang=en_GB&market=FI")
        time.sleep(TAUKO)
        if data is None:
            continue
        kertoimet = lue_pelaajakertoimet(data.get("betOffers"))
        omat_nimet = {vertailunimi(p["nimi"]) for p in ottelu["pelaajat"]}
        pelaajat = {}
        for p in ottelu["pelaajat"]:
            k = pelaajan_kertoimet(kertoimet, p["nimi"], omat_nimet)
            if k:
                pelaajat[str(p["id"])] = k
        if pelaajat:
            tulos[ottelu["avain"]] = pelaajat
    return tulos


def lue_varjo():
    if os.path.exists(VARJO):
        with open(VARJO, "r", encoding="utf-8") as tiedosto:
            return json.load(tiedosto)
    return {}


def tallenna_varjo(varjo):
    # Yksi peli per rivi, kuten liiga_pelaajat.json
    rivit = [json.dumps(avain) + ": " + json.dumps(varjo[avain], ensure_ascii=False)
             for avain in sorted(varjo)]
    with open(VARJO, "w", encoding="utf-8") as tiedosto:
        tiedosto.write("{\n" + ",\n".join(rivit) + "\n}\n")


def paivita_varjo(ennusteet, kambi):
    # Varjokirjanpito: kaikkien kokoonpanon pelaajien ennusteet ennen peliä ja
    # Unibetin kertoimet. tarkista_tulokset.py täyttää tulokset pelin jälkeen.
    # Alkanutkin peli kelpaa: kokoonpano, pelaajien tasot ja joukkuemalli ovat kaikki
    # ennen peliä tiedossa olevaa tietoa (päättymätön peli ei ole vielä missään datassa).
    varjo = lue_varjo()
    lisatty = 0
    for ottelu in ennusteet["ottelut"]:
        if not ottelu["kokoonpano"] or ottelu.get("paattynyt"):
            continue
        vanha = varjo.get(ottelu["avain"])
        if vanha and vanha.get("tulokset") is not None:
            continue
        varjo[ottelu["avain"]] = {
            "pvm": ennusteet["pvm"], "ottelu": ottelu["koti"] + " - " + ottelu["vieras"],
            "versio": VERSIO,
            "ennusteet": [[p["id"], round(p["tn"]["maalit_1"], 3), round(p["tn"]["syotot_1"], 3),
                           round(p["tn"]["pisteet_1"], 3), round(p["tn"]["pisteet_2"], 3)]
                          for p in ottelu["pelaajat"]],
            # Kambi poistaa pelaajavedot pelin alettua: silloin vanhat kertoimet jäävät voimaan
            "kertoimet": kambi.get(ottelu["avain"]) or (vanha or {}).get("kertoimet") or {},
            "tulokset": None,
        }
        lisatty += 1
    tallenna_varjo(varjo)
    print("Varjokirjanpitoon tallennettu", lisatty, "pelin ennusteet")


# ===== WALK-FORWARD-TESTI =====
TESTI_MUODOT = [5, 10, 15]      # kokeiltavat muotoikkunat (pelejä)
VETOTYYPIT = ["maalit_1", "syotot_1", "pisteet_1", "pisteet_2"]


def ottelukertoimet_testiin(pelit):
    # Joukkueiden ottelukertoimet jokaiselle testipelille: Poisson-malli sovitetaan
    # jokaiselle pelipäivälle vain aiemmilla peleillä (kuten poisson_malli.py:n testissä).
    import poisson_malli as pm
    asetukset = pm.SARJA_ASETUKSET["Liiga"]
    joukkuepelit = pm.hae_pelit("Liiga")
    pm.aseta_xg(joukkuepelit, asetukset["xg_paino"])
    joukkuepelit.sort(key=lambda q: q["paiva"])
    tunnetut = {q["id_avain"]: q for q in joukkuepelit}

    tulos = {}
    mallin_paiva = None
    for p in pelit:
        if p["paiva"].isoformat() < ARVIOINTI_ALKAA or p["avain"] not in tunnetut:
            continue
        q = tunnetut[p["avain"]]
        if p["paiva"] != mallin_paiva:
            aiemmat = [a for a in joukkuepelit if a["paiva"].date() < p["paiva"]]
            malli = pm.sovita(aiemmat, q["paiva"], kausikerroin=asetukset["kausikerroin"])
            summat = pm.maalivahtien_summat(aiemmat)
            malli["mv_paino"] = asetukset["mv_paino"]
            malli["mv_tasot"] = {str(mv): pm.mv_taso(summat[mv], asetukset["mv_kutistus"]) for mv in summat}
            malli["vasymys"] = asetukset["vasymys"]
            mallin_paiva = p["paiva"]
        tulos[p["avain"]] = {
            True: ottelukerroin(malli, q["koti"], q["vieras"], True, q["vieras_mv"],
                                q["koti_eilen"], q["vieras_eilen"]),
            False: ottelukerroin(malli, q["vieras"], q["koti"], False, q["koti_mv"],
                                 q["vieras_eilen"], q["koti_eilen"]),
        }
    return tulos


def keraa_ennusteet(pelit, kertoimet, puoliintuminen=PUOLIINTUMINEN, kausikerroin=KAUSIKERROIN):
    # HIDAS: jokaiselle testipelin pelaajalle tallennetaan summat vain aiemmista peleistä.
    # Pisteytys eri asetuksilla on sen jälkeen nopea.
    ennusteet = []
    historia = {}
    paiva_nyt = None
    tahdit = paikkatahdit = None
    for i, p in enumerate(pelit):
        if p["paiva"] != paiva_nyt:
            # Uusi pelipäivä: päivän pelit lisätään historiaan vasta kun päivä vaihtuu
            if paiva_nyt is not None:
                for q in pelit[:i]:
                    if q["paiva"] == paiva_nyt:
                        for r in q["rivit"]:
                            historia.setdefault(r["id"], []).append(
                                (q["paiva"], q["kausi"], r["rooli"], r["m"], r["s"]))
            paiva_nyt = p["paiva"]
            if p["paiva"].isoformat() >= ARVIOINTI_ALKAA:
                tahdit = roolien_tahdit(pelit[:i], p["paiva"], puoliintuminen, kausikerroin)
                # Pelkkä pelipaikka (vertailukohta)
                paikkatahdit = roolien_tahdit(pelit[:i], p["paiva"], puoliintuminen, kausikerroin, "paikka")

        if p["paiva"].isoformat() < ARVIOINTI_ALKAA or p["avain"] not in kertoimet:
            continue

        for r in p["rivit"]:
            h = historia.get(r["id"], [])
            em, es = tahdit.get(r["rooli"], (0.05, 0.1))
            muodot = {}
            for n in TESTI_MUODOT:
                koko, muoto = pelaajan_summat(h, p["paiva"], tahdit, n, puoliintuminen, kausikerroin)
                muodot[n] = muoto
            kauden = [x for x in h if x[1] == p["kausi"]]
            aiempi, _ = pelaajan_summat([x for x in h if x[1] < p["kausi"]], p["paiva"], tahdit, 0,
                                        puoliintuminen, kausikerroin)
            ennusteet.append({
                "aiempi": aiempi,
                "koko": koko, "muodot": muodot, "em": em, "es": es,
                "paikka": paikkatahdit[r["paikka"]],
                "kerroin": kertoimet[p["avain"]][r["koti"]],
                "kausi": (len(kauden), sum(x[3] for x in kauden), sum(x[4] for x in kauden)),
                "m": r["m"], "s": r["s"], "rooli": r["rooli"],
            })
    return ennusteet


def lambdat(e, tapa, asetukset):
    # Palauttaa (maalien λ, syöttöjen λ) valitulla tavalla
    if tapa == "paikka":
        return e["paikka"]
    if tapa == "kausi":
        n, m, s = e["kausi"]
        if n == 0:
            return e["paikka"]
        return m / n, s / n
    if tapa == "rooli":
        return e["em"], e["es"]
    a = asetukset
    taso_m, taso_s = tasot(e["koko"], e["muodot"][a["muoto_pelit"]], a["kutistus_m"], a["kutistus_s"],
                           a["muoto_paino"], MUOTO_KUTISTUS)
    kerroin = e["kerroin"] ** a["ottelukerroin"]
    return taso_m * e["em"] * kerroin, taso_s * e["es"] * kerroin


def pisteyta(ennusteet, tapa="malli", asetukset=None, kalibraatio=False):
    # NOPEA: Brier ja log loss vedoille 1+ maali, 1+ syöttö, 1+ piste, 2+ pistettä
    tulos = {v: [0.0, 0.0] for v in VETOTYYPIT}
    lokerot = {v: {} for v in VETOTYYPIT}
    for e in ennusteet:
        lam_m, lam_s = lambdat(e, tapa, asetukset)
        tn = todennakoisyydet(lam_m, lam_s)
        toteutui = {"maalit_1": e["m"] >= 1, "syotot_1": e["s"] >= 1,
                    "pisteet_1": e["m"] + e["s"] >= 1, "pisteet_2": e["m"] + e["s"] >= 2}
        for v in VETOTYYPIT:
            x = min(max(tn[v], 0.001), 0.999)     # log(0) ei onnistu
            y = 1 if toteutui[v] else 0
            tulos[v][0] += (x - y) ** 2
            tulos[v][1] += -math.log(x if y else 1 - x)
            if kalibraatio:
                lokero = min(int(tn[v] * 10), 9)
                l = lokerot[v].setdefault(lokero, [0, 0.0, 0])
                l[0] += 1
                l[1] += tn[v]
                l[2] += y
    n = len(ennusteet)
    pisteet = {v: (tulos[v][0] / n, tulos[v][1] / n) for v in VETOTYYPIT}
    return (pisteet, lokerot) if kalibraatio else pisteet


def testaa(pelit, nimet):
    print()
    print("===== WALK-FORWARD-TESTI: pelaajamalli =====")
    alku = time.time()
    kertoimet = ottelukertoimet_testiin(pelit)
    print(f"Ottelukertoimet {len(kertoimet)} peliin ({time.time() - alku:.0f} s)")

    def rivi(nimi, p):
        osat = "  ".join(f"{p[v][0]:.4f} {p[v][1]:.4f}" for v in VETOTYYPIT)
        print(f"{nimi:44} {osat}")

    otsikko = "  ".join(f"{v:>13}" for v in VETOTYYPIT)
    oletus = {"muoto_pelit": MUOTO_PELIT, "kutistus_m": KUTISTUS_MAALIT, "kutistus_s": KUTISTUS_SYOTOT,
              "muoto_paino": MUOTO_PAINO, "ottelukerroin": OTTELUKERROIN_PAINO}

    paras = None
    for puoliintuminen, kausikerroin in [(120, 0.7), (240, 0.7), (480, 0.7), (240, 0.5), (240, 1.0)]:
        alku = time.time()
        enn = keraa_ennusteet(pelit, kertoimet, puoliintuminen, kausikerroin)
        print()
        print(f"--- Puoliintuminen {puoliintuminen} pv, kausikerroin {kausikerroin}:"
              f" {len(enn)} pelaajaennustetta ({time.time() - alku:.0f} s)")
        print(f"{'(Brier, log loss)':44} {otsikko}")
        if paras is None:
            rivi("Vertailu: pelipaikan keskitaso", pisteyta(enn, "paikka"))
            rivi("Vertailu: kauden tahti ilman kutistusta", pisteyta(enn, "kausi"))
            rivi("Vertailu: roolin (paikka + ketju) keskitaso", pisteyta(enn, "rooli"))

        # Ruudukko: kutistus, muodon ikkuna ja paino, ottelukertoimen paino
        tulokset = []
        for kutistus in [2, 3, 5, 8, 12]:
            for muoto_pelit in TESTI_MUODOT:
                for muoto_paino in [0, 0.1, 0.2, 0.3, 0.5]:
                    for ok in [0, 0.5, 1.0]:
                        a = {"muoto_pelit": muoto_pelit, "kutistus_m": kutistus, "kutistus_s": kutistus,
                             "muoto_paino": muoto_paino, "ottelukerroin": ok}
                        p = pisteyta(enn, "malli", a)
                        # Valintamittari: log lossien summa kolmelle päävedolle
                        mittari = p["maalit_1"][1] + p["syotot_1"][1] + p["pisteet_1"][1]
                        tulokset.append((mittari, a, p))
        tulokset.sort(key=lambda t: t[0])
        for mittari, a, p in tulokset[:5]:
            rivi(f"K {a['kutistus_m']}, muoto {a['muoto_pelit']} p × {a['muoto_paino']}, ok {a['ottelukerroin']}", p)
        # Muodon vaikutus parhailla muilla asetuksilla
        print("Muodon paino (muut parhaat):")
        a0 = tulokset[0][1]
        for muoto_paino in [0, 0.1, 0.2, 0.3, 0.5]:
            a = dict(a0, muoto_paino=muoto_paino)
            rivi(f"  muoto {a['muoto_pelit']} p × {muoto_paino}", pisteyta(enn, "malli", a))
        # Kutistus erikseen maaleille ja syötöille
        for km in [2, 3, 5, 8, 12, 20]:
            for ks in [2, 3, 5, 8, 12, 20]:
                a = dict(a0, kutistus_m=km, kutistus_s=ks)
                p = pisteyta(enn, "malli", a)
                mittari = p["maalit_1"][1] + p["syotot_1"][1] + p["pisteet_1"][1]
                tulokset.append((mittari, a, p))
        tulokset.sort(key=lambda t: t[0])
        rivi(f"Paras: K {tulokset[0][1]['kutistus_m']}/{tulokset[0][1]['kutistus_s']}, "
             f"muoto {tulokset[0][1]['muoto_pelit']} × {tulokset[0][1]['muoto_paino']}, "
             f"ok {tulokset[0][1]['ottelukerroin']}", tulokset[0][2])
        if paras is None or tulokset[0][0] < paras[0]:
            paras = (tulokset[0][0], tulokset[0][1], puoliintuminen, kausikerroin, enn)

    _, a, puoliintuminen, kausikerroin, enn = paras
    print()
    print(f"PARAS: puoliintuminen {puoliintuminen}, kausikerroin {kausikerroin}, {a}")
    print(f"Nykyiset asetukset: {oletus}")

    # Kalibraatio: kun malli sanoo 40 %, toteutuuko noin 40 %?
    _, lokerot = pisteyta(enn, "malli", a, kalibraatio=True)
    print()
    print("Kalibraatio (paras malli):")
    for v in VETOTYYPIT:
        print(f"  {v}:   ennuste   n      malli   toteutui")
        for lokero in sorted(lokerot[v]):
            n, summa, osui = lokerot[v][lokero]
            print(f"           {lokero * 10:3}–{lokero * 10 + 10:3} % {n:6}   {summa / n:6.1%}   {osui / n:6.1%}")

    # Nousijat: jatkuuko tahti? Joukko valitaan kerran nykyisillä asetuksilla, ja
    # eri muodon painoja verrataan samoihin pelaajiin (muuten joukko muuttuisi painon mukana).
    nykyinen = dict(a, muoto_paino=MUOTO_PAINO)

    def on_nousija(e):
        lam_m, lam_s = lambdat(e, "malli", nykyinen)
        aiempi_m, aiempi_s = tasot(e["aiempi"], [0, 0, 0, 0], a["kutistus_m"], a["kutistus_s"], 0)
        aiempi_lam = (aiempi_m * e["em"] + aiempi_s * e["es"]) * e["kerroin"] ** a["ottelukerroin"]
        return (lam_m + lam_s) / aiempi_lam - 1 >= NOUSIJA_RAJA and e["kausi"][0] >= NOUSIJA_MIN_PELIT

    nousijat = [e for e in enn if on_nousija(e)]
    print()
    print(f"Nousijat ({len(nousijat)} ennustetta: odotus ≥ +{NOUSIJA_RAJA:.0%} tasosta ennen kautta,"
          f" kaudella ≥ {NOUSIJA_MIN_PELIT} peliä):")
    print("  muodon paino   1+ piste malli  toteutui  log loss")
    for muoto_paino in [0, 0.1, 0.2, 0.3, 0.5]:
        p, _ = pisteyta(nousijat, "malli", dict(a, muoto_paino=muoto_paino), kalibraatio=True)
        malli = sum(todennakoisyydet(*lambdat(e, "malli", dict(a, muoto_paino=muoto_paino)))["pisteet_1"]
                    for e in nousijat) / len(nousijat)
        osui = sum(1 for e in nousijat if e["m"] + e["s"] >= 1) / len(nousijat)
        print(f"  {muoto_paino:5}           {malli:6.1%}    {osui:6.1%}   {p['pisteet_1'][1]:.4f}")

    # Roolien keskitasot (tarkistus)
    tahdit = roolien_tahdit(pelit, pelit[-1]["paiva"])
    print()
    print("Roolien keskitasot nyt (maalit / syötöt per peli):")
    for r in sorted(tahdit):
        print(f"  {r:4} {tahdit[r][0]:.3f} {tahdit[r][1]:.3f}")


# ===== PÄÄOHJELMA =====
if __name__ == "__main__":
    pelit, nimet = lue_pelit()
    print("Pelaajadataa:", len(pelit), "peliä")

    with open(POISSON, "r", encoding="utf-8") as tiedosto:
        pmalli = json.load(tiedosto)["Liiga"]

    ennusteet = tee_ennusteet(pelit, nimet, pmalli, datetime.now().date())
    if ennusteet is None:
        print("Haku epäonnistui: edelliset ennusteet jäävät voimaan")
        raise SystemExit(1)
    with open(ENNUSTEET, "w", encoding="utf-8") as tiedosto:
        # Tiivis muoto: tiedosto ladataan puhelimeen joka kerta
        json.dump(ennusteet, tiedosto, ensure_ascii=False, separators=(",", ":"))
    # Kertoimien haku ei saa kaataa ennusteita: virheessä varjoon jää ilman kertoimia
    try:
        kambi = hae_kambi_kertoimet(ennusteet["ottelut"])
    except (requests.RequestException, KeyError, TypeError, ValueError) as virhe:
        print("VIRHE: Kambin kertoimet:", virhe)
        kambi = {}
    print("Unibetin kertoimet", sum(len(k) for k in kambi.values()), "pelaajalle")
    paivita_varjo(ennusteet, kambi)

    # Tuloste: illan todennäköisimmät pistemiehet ja nousijat
    kaikki = [p for o in ennusteet["ottelut"] for p in o["pelaajat"]]
    print()
    print("Pelipäivä:", ennusteet["pvm"])
    print("Todennäköisimmät 1+ piste:")
    for p in sorted(kaikki, key=lambda p: p["tn"]["pisteet_1"], reverse=True)[:10]:
        print(f"  {p['nimi']:25} {p['joukkue']:10} {p['tn']['pisteet_1']:.0%}"
              f"  (raja {1 / p['tn']['pisteet_1']:.2f})")
    print("Nousijat:")
    for p in sorted([p for p in kaikki if p["nousija"]], key=lambda p: p["nousija"]["nosto"], reverse=True):
        print(f"  {p['nimi']:25} {p['joukkue']:10} +{p['nousija']['nosto']:.0%}"
              f"  kausi {p['kausi']['maalit']}+{p['kausi']['syotot']} / {p['kausi']['ottelut']} o")

    if TESTAA:
        testaa(pelit, nimet)
