from datetime import datetime, timezone, timedelta
from poisson_malli import hae_pelit, sovita, maaliodotukset

nyt = datetime.now(timezone.utc)

for sarja in ["Liiga", "SHL"]:
    pelit = hae_pelit(sarja)

    # Kaikki voimat samalla painolla (iso puoliintuminen), jotta odotukset
    # ovat koko jakson keskitasoa eivätkä vain tämän syksyn
    malli = sovita(pelit, nyt, puoliintuminen=100000, kausikerroin=1.0)

    # 1. Jokaisen joukkueen pelipäivät joukkona (set)
    pelipaivat = {}
    for p in pelit:
        for joukkue in [p["koti"], p["vieras"]]:
            if joukkue not in pelipaivat:
                pelipaivat[joukkue] = set()
            pelipaivat[joukkue].add(p["paiva"].date())

    # 2. Verrataan toteutuneita maaleja mallin odotukseen
    #    erikseen "väsyneille" (pelasi eilen) ja levänneille
    tilasto = {
        "pelasi eilen": {"pelejä": 0, "tehty": 0, "odotettu_tehty": 0, "päästetty": 0, "odotettu_päästetty": 0},
        "levännyt":     {"pelejä": 0, "tehty": 0, "odotettu_tehty": 0, "päästetty": 0, "odotettu_päästetty": 0},
    }

    for p in pelit:
        lk, lv = maaliodotukset(malli, p["koti"], p["vieras"])
        eilen = p["paiva"].date() - timedelta(days=1)

        # Kotijoukkueen ja vierasjoukkueen näkökulma vuorotellen
        for joukkue, tehty, paastetty, odot_tehty, odot_paastetty in [
            (p["koti"], p["k60"], p["v60"], lk, lv),
            (p["vieras"], p["v60"], p["k60"], lv, lk),
        ]:
            ryhma = "pelasi eilen" if eilen in pelipaivat[joukkue] else "levännyt"
            t = tilasto[ryhma]
            t["pelejä"] += 1
            t["tehty"] += tehty
            t["odotettu_tehty"] += odot_tehty
            t["päästetty"] += paastetty
            t["odotettu_päästetty"] += odot_paastetty

    print()
    print("=====", sarja, "=====")
    for ryhma in tilasto:
        t = tilasto[ryhma]
        if t["pelejä"] == 0:
            print(" ", ryhma, ": ei pelejä")
            continue
        # Suhde 1.00 = juuri odotetusti, 0.95 = 5 % vähemmän kuin malli odotti
        hyokkays = t["tehty"] / t["odotettu_tehty"]
        puolustus = t["päästetty"] / t["odotettu_päästetty"]
        # Satunnaisvaihtelun suuruus: noin 1 / neliöjuuri(odotettujen maalien määrä)
        virhe = 1 / t["odotettu_tehty"] ** 0.5
        print(f"  {ryhma:13} pelejä {t['pelejä']:5} | tehdyt / odotettu {hyokkays:.3f}"
              f" | päästetyt / odotettu {puolustus:.3f} | satunnaisvaihtelu ±{virhe:.3f}")