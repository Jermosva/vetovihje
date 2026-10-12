import json
import math
import requests
from datetime import datetime, timezone

# ===== ASETUKSET =====
KAUDET = [2024, 2025, 2026, 2027]
PUOLIINTUMINEN = 180     # päivää: näin vanha peli painaa puolet tuoreesta
KUTISTUS = 20             # "keskiarvopelejä", joilla harvoin pelanneet vedetään kohti keskitasoa
KIERROKSET = 30          # montako kertaa voimat lasketaan uudelleen
MAX_MAALIT = 12          # tulosjakaumassa lasketaan maalimäärät 0–11
TASAPELIKERROIN = 1.3    # >1 lisää tasapelejä (Poisson aliarvioi niitä jääkiekossa)

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

    return {
        "koti": peli["homeTeamName"],
        "vieras": peli["awayTeamName"],
        "k60": k60,
        "v60": v60,
        "koti_voitti": k > v,     # lopputulos jatkoaikoineen
        "jatkoaika": jatkoaika,
        "paiva": datetime.fromisoformat(peli["start"].replace("Z", "+00:00")),
    }


# ===== MALLIN SOVITUS (hidas osa) =====
def sovita(pelit, hetki, puoliintuminen=PUOLIINTUMINEN, kutistus=KUTISTUS):
    # 1. Aikapainot: tuore peli painaa 1, PUOLIINTUMINEN päivää vanha 0,5 jne.
    painot = []
    for p in pelit:
        ika_paivina = (hetki - p["paiva"]).days
        painot.append(0.5 ** (ika_paivina / puoliintuminen))

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
def keraa_ennusteet(pelit, puoliintuminen=PUOLIINTUMINEN, kutistus=KUTISTUS):
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

        paiva = p["paiva"].date()
        if paiva != mallin_paiva:
            aiemmat = [q for q in pelit if q["paiva"].date() < paiva]
            malli = sovita(aiemmat, p["paiva"], puoliintuminen, kutistus)
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
        })

    return ennusteet


def pisteyta(ennusteet, tasapelikerroin):
    # NOPEA: laskee tarkkuuden tallennetuista maaliodotuksista
    brier_1x2 = 0
    brier_perus = 0
    brier_voittaja = 0
    ennustettu_tasan = 0
    toteutunut_tasan = 0

    for e in ennusteet:
        t = todennakoisyydet(e["lk"], e["lv"], tasapelikerroin)
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
pelit = []
for kausi in KAUDET:
    for peli in hae_kausi(kausi):
        pelit.append(muunna(peli))

nyt = datetime.now(timezone.utc)
malli = sovita(pelit, nyt)

# Tallennetaan malli, jotta laske_value.py voi käyttää sitä
with open("poisson.json", "w", encoding="utf-8") as tiedosto:
    json.dump({
        "koti_ka": malli["koti_ka"],
        "vieras_ka": malli["vieras_ka"],
        "hyok": malli["hyok"],
        "puol": malli["puol"],
        "tasapelikerroin": TASAPELIKERROIN,
    }, tiedosto, ensure_ascii=False, indent=2)

print("Pelejä:", len(pelit))
print("Keskimäärin maaleja 60 min: koti", round(malli["koti_ka"], 2),
      "| vieras", round(malli["vieras_ka"], 2))

print()
print("Joukkueet (hyökkäys yli 1 = tekee keskimääräistä enemmän,")
print("           puolustus alle 1 = päästää keskimääräistä vähemmän):")
for j in sorted(malli["hyok"], key=lambda j: malli["hyok"][j] / malli["puol"][j], reverse=True):
    print(f"  {j:12} hyökkäys {malli['hyok'][j]:.2f}   puolustus {malli['puol'][j]:.2f}")

print()
e = ennusta(malli, "KooKoo", "Jukurit")
print("Esimerkki KooKoo - Jukurit (tasapelikerroin", TASAPELIKERROIN, "):")
print(f"  Maaliodotukset {e['lk']:.2f} - {e['lv']:.2f}")
print(f"  1X2: koti {e['koti60']:.1%}  tasan {e['tasan']:.1%}  vieras {e['vieras60']:.1%}")
print(f"  Voittaja (jatkoajat mukaan): KooKoo {e['koti_voittaja']:.1%}")

if TESTAA:
    print()
    print("===== WALK-FORWARD-TESTI =====")
    print("Kokeillaan 9 yhdistelmää, tämä kestää muutaman minuutin...")
    print()
    print("Puoliintuminen | Kutistus | 1X2 Brier | Voittaja Brier | Tasapelit enn. / tot.")

    for puoliintuminen in [150, 180, 240]:
        for kutistus in [10, 20, 40]:
            ennusteet = keraa_ennusteet(pelit, puoliintuminen, kutistus)
            t = pisteyta(ennusteet, TASAPELIKERROIN)
            print(f"     {puoliintuminen:3} pv     |    {kutistus:2}    |  {t['1x2']:.4f}   |"
                  f"     {t['voittaja']:.4f}     |   {t['ennustettu_tasan']:.1%} / {t['toteutunut_tasan']:.1%}")

    print()
    print(f"Perustaso 1X2 Brier: {t['perus']:.4f}")