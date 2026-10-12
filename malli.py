import requests
import json

KAUDET = [2024, 2025, 2026, 2027]   # edellinen (2025–26) ja nykyinen (2026–27) kausi
ALKU_ELO = 1500         # jokaisen joukkueen lähtöluku
K = 20                  # kuinka paljon yksi peli muuttaa lukuja
KOTIETU = 50            # kotijoukkueen etu Elo-pisteinä
PALAUTUS = 0.33         # kausien välissä luvut liukuvat kolmanneksen verran kohti 1500:aa
ARVIOINNIN_ALKU = 100   # ensimmäisiä pelejä ei arvioida: malli vasta opettelee
UUSI_ELO = 1450         # sarjaan uutena tuleva joukkue aloittaa keskitason alapuolelta

def hae_kausi(kausi):
    osoite = ("https://liiga.fi/api/v2/schedule?tournament=runkosarja&season="
              + str(kausi))
    vastaus = requests.get(osoite)
    if vastaus.status_code != 200:
        print("VIRHE: kausi", kausi, vastaus.status_code)
        return []

    # Vain pelatut ottelut. Tämä on "listakooste" (list comprehension):
    # lyhyt tapa kirjoittaa silmukka, joka poimii listasta osan.
    pelit = [peli for peli in vastaus.json() if peli["ended"]]

    # Järjestetään alkamisajan mukaan, koska Elo pitää laskea oikeassa järjestyksessä.
    # lambda = pieni nimetön funktio: "järjestä kentän start mukaan"
    return sorted(pelit, key=lambda peli: peli["start"])

def kotivoiton_tn(koti_elo, vieras_elo, kotietu):
    # Elo-ero kotiedun kanssa
    ero = (koti_elo + kotietu) - vieras_elo
    # Elon peruskaava: 400 pisteen ero = noin 10-kertainen voittomahdollisuus
    return 1 / (1 + 10 ** (-ero / 400))

# Haetaan pelit vain kerran, jotta testaus ei hae samaa dataa kymmeniä kertoja
kausien_pelit = []
for kausi in KAUDET:
    kausien_pelit.append(hae_kausi(kausi))

def aja_malli(k, kotietu, palautus, ):
    elo = {}
    brier_malli = 0
    brier_perus = 0
    arvioituja = 0
    pelattuja = 0
    kotivoittoja = 0

    for pelit in kausien_pelit:
        for joukkue in elo:
            elo[joukkue] = elo[joukkue] - palautus * (elo[joukkue] - ALKU_ELO)

        for peli in pelit:
            koti = peli["homeTeamName"]
            vieras = peli["awayTeamName"]
            # Ensimmäisellä kaudella kaikki aloittavat 1500:sta.
            # Myöhemmin mukaan tuleva joukkue on nousija ja aloittaa alempaa.
            aloitus = ALKU_ELO if len(elo) < 15 else UUSI_ELO
            if koti not in elo:
                elo[koti] = aloitus
            if vieras not in elo:
                elo[vieras] = aloitus
                
            tn = kotivoiton_tn(elo[koti], elo[vieras], kotietu)

            if peli["homeTeamGoals"] > peli["awayTeamGoals"]:
                tulos = 1
            else:
                tulos = 0

            # Arvioidaan ennen päivitystä (ei tietovuotoa)
            if pelattuja >= ARVIOINNIN_ALKU:
                perustaso = kotivoittoja / pelattuja
                brier_malli += (tn - tulos) ** 2
                brier_perus += (perustaso - tulos) ** 2
                arvioituja += 1

            muutos = k * (tulos - tn)
            elo[koti] += muutos
            elo[vieras] -= muutos

            pelattuja += 1
            kotivoittoja += tulos

    return brier_malli / arvioituja, brier_perus / arvioituja, elo

paras = None

# Kolme sisäkkäistä silmukkaa = kaikki yhdistelmät (6 × 5 × 3 = 90 kokeilua)
for k in [20, 25, 30, 35, 40, 50]:
    for kotietu in [0, 25, 50, 75, 100]:
        for palautus in [0.5, 0.6, 0.7, 0.8, 0.9, 1.0]:
            brier, perus, elo = aja_malli(k, kotietu, palautus)

            # Pienin Brier tähän mennessä? Tallennetaan se.
            if paras is None or brier < paras["brier"]:
                paras = {
                    "brier": brier,
                    "perus": perus,
                    "k": k,
                    "kotietu": kotietu,
                    "palautus": palautus,
                    "elo": elo,
                }

print("Paras yhdistelmä: K =", paras["k"],
      "| kotietu =", paras["kotietu"],
      "| palautus =", paras["palautus"])
print("Brier, malli:    ", round(paras["brier"], 4))
print("Brier, perustaso:", round(paras["perus"], 4))

print()
print("Joukkueiden vahvuudet nyt:")
for joukkue in sorted(paras["elo"], key=paras["elo"].get, reverse=True):
    print(f"  {joukkue:12} {round(paras['elo'][joukkue])}")

# Tallennetaan luvut ja kotietu, jotta muut ohjelmat voivat käyttää niitä
with open("elo.json", "w", encoding="utf-8") as tiedosto:
    json.dump({
        "kotietu": paras["kotietu"],
        "elo": paras["elo"],
    }, tiedosto, ensure_ascii=False, indent=2)

print()
print("Tallennettu elo.json")