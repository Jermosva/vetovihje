import json

# Yhtiöt, joiden marginaali on tätä suurempi, eivät vaikuta "oikeaan" todennäköisyyteen
MAX_MARGINAALI = 10
# Value-vedon vaatimukset
MIN_VALUE = 3      # value vähintään 3 %
MIN_YHTIOT = 3     # "oikea" todennäköisyys vähintään 3 yhtiön perusteella

# Tähän listaan kerätään kaikki löydetyt value-vedot
loydetyt = []

# Luetaan tallennetut ottelut ("r" = read eli luku)
with open("ottelut.json", "r", encoding="utf-8") as tiedosto:
    ottelut = json.load(tiedosto)

for ottelu in ottelut:
    print()
    print(ottelu["home_team"], "vs", ottelu["away_team"])

    for tyyppi in ["Voittaja", "1X2"]:
        reilut = {}         # vaihtoehto -> lista reiluja todennäköisyyksiä
        parhaat = {}        # vaihtoehto -> paras kerroin
        parhaan_yhtio = {}  # vaihtoehto -> kuka tarjoaa parhaan kertoimen
        for yhtio in ottelu["bookmakers"]:
            for markkina in yhtio["markets"]:
                vaihtoehdot = markkina["outcomes"]

                if len(vaihtoehdot) == 3:
                    tama_tyyppi = "1X2"
                else:
                    tama_tyyppi = "Voittaja"

                # Jos tämä ei ole se vetotyyppi, jota nyt käsitellään, ohitetaan
                if tama_tyyppi != tyyppi:
                    continue

                # Marginaali kuten ennenkin
                summa = 0
                for v in vaihtoehdot:
                    summa = summa + 1 / v["price"]
                marginaali = (summa - 1) * 100
                for v in vaihtoehdot:
                    nimi = v["name"]
                    kerroin = v["price"]

                    # Onko tämä paras kerroin tähän mennessä? (kaikki yhtiöt mukana)
                    if nimi not in parhaat or kerroin > parhaat[nimi]:
                        parhaat[nimi] = kerroin
                        parhaan_yhtio[nimi] = yhtio["title"]

                    # Reilu todennäköisyys vain luotettavilta yhtiöiltä:
                    # jaetaan summalla, jolloin marginaali poistuu
                    if marginaali <= MAX_MARGINAALI:
                        reilu = (1 / kerroin) / summa
                        if nimi not in reilut:
                            reilut[nimi] = []
                        reilut[nimi].append(reilu)
        for nimi in parhaat:
            # Jos yksikään luotettava yhtiö ei tarjonnut tätä, ohitetaan
            if nimi not in reilut:
                continue

            oikea = sum(reilut[nimi]) / len(reilut[nimi])   # keskiarvo
            paras = parhaat[nimi]
            value = (oikea * paras - 1) * 100               # prosentteina

            yhtioita = len(reilut[nimi])

            merkki = ""
            # and = molempien ehtojen pitää olla totta
            if value >= MIN_VALUE and yhtioita >= MIN_YHTIOT:
                merkki = "  <-- VALUE"

                # Tallennetaan löytö sanakirjana listaan
                loydetyt.append({
                    "ottelu": ottelu["home_team"] + " - " + ottelu["away_team"],
                    "tyyppi": tyyppi,
                    "valinta": nimi,
                    "kerroin": paras,
                    "yhtio": parhaan_yhtio[nimi],
                    "value": round(value, 1),
                })

            print("   ", tyyppi, "|", nimi,
                  "| oikea", round(oikea * 100, 1), "%",
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
              "| value", veto["value"], "%")