import json
import os
from datetime import date, datetime, timezone, timedelta

# Oman Poisson-mallin funktiot (poisson_malli.py samassa kansiossa)
from poisson_malli import maaliodotukset, todennakoisyydet

# ===== ASETUKSET =====
MAX_MARGINAALI = 10          # yhtiöt, joiden marginaali on tätä suurempi, eivät vaikuta "oikeaan" arvioon
MIN_VALUE = 3                # kerroinvertailun value vähintään 3 %
MAX_VALUE = 10               # tätä suurempi value on todennäköisesti virhe -> merkitään tarkistettavaksi
MIN_YHTIOT = 3               # "oikea" todennäköisyys vähintään 3 yhtiön perusteella
VERTAILUYHTIO = "Pinnacle"   # jos tämä yhtiö on mukana, sen arvio on "oikea"
MAX_POIKKEAMA = 0.05         # jos Pinnacle poikkeaa keskiarvosta yli 5 %-yksikköä, käytetään keskiarvoa
MAX_TUNNIT = 24              # vain seuraavan 24 tunnin ottelut
PANOS = 10                   # leikkieuroa per veto
KIRJANPITO = "kirjanpito.json"   # oikeat leikkirahavedot
VARJO = "varjo.json"             # kaikki ehdokkaat tilastoa varten
VERSIO = 4                      # 3 = Poisson-malli Liigaan

# Yhtiöt, joilta paras kerroin saa tulla (nimet täsmälleen kuten tulosteessa)
KAYTETTAVAT_YHTIOT = [
    "Betsson",
    "Nordic Bet",
    "Unibet (FI)",
    "LeoVegas (FI)",
    "Veikkaus (FI)",
    "Coolbet",
    "William Hill",
    "888sport",
    "Tipico",
    "Marathon Bet",
    "Bet Victor",
    "1xBet",
]

# Yli/alle- ja tasoitusvedot lasketaan varsinaisen peliajan (60 min) mukaan.
# Niissä käytetään VAIN näitä yhtiöitä. Tarkista säännöt ja karsi lista!
YHTIOT_60MIN = [
    "Betsson",
    "Nordic Bet",
    "Unibet (FI)",
    "LeoVegas (FI)",
    "Veikkaus (FI)",
    "Coolbet",
    "888sport",
    "Tipico",
    "1xBet",
]

# Oma Poisson-malli (Liiga): kaikki vetotyypit
MALLIN_PAINO = 0.2       # yhdistetty arvio = 80 % markkina + 20 % malli
MALLI_MIN_VALUE = 4      # yhdistetyn arvion alaraja
MALLI_MAX_VALUE = 10     # tätä suurempi = epäilyttävä, ei kirjata
MALLI_MAX_POIKKEAMA = 0.08   # malli saa poiketa markkinasta enintään 8 %-yksikköä

# Kerroinpalvelun nimi -> malliin tallennettu nimi (liiga.fi / shl.se), sarjoittain
MALLIN_NIMET = {
    "Liiga": {
        "Kiekko-Espoo": "K-Espoo",
    },
    "SHL": {
        "Luleå HF": "Luleå Hockey",
        "Örebro HK": "Örebro Hockey",
        "IF Björklöven": "Björklöven",
    },
}

# Luetaan mallit: {"Liiga": {...}, "SHL": {...}}
if os.path.exists("poisson.json"):
    with open("poisson.json", "r", encoding="utf-8") as tiedosto:
        PMALLIT = json.load(tiedosto)
else:
    PMALLIT = {}

loydetyt = []     # vedot, jotka ylittävät rajat -> oikeaan kirjanpitoon
ehdokkaat = []    # kaikki positiiviset valuet -> varjokirjanpitoon


# ===== FUNKTIOT =====
def markkinan_tyyppi(markkina, ottelu):
    vaihtoehdot = markkina["outcomes"]

    if markkina["key"] == "h2h":
        if len(vaihtoehdot) == 3:
            return "1X2"
        return "Voittaja"

    if markkina["key"] == "totals":
        return "Yli/alle " + str(vaihtoehdot[0]["point"])

    if markkina["key"] == "spreads":
        # Nimetään kotijoukkueen tasoituksen mukaan, esim. "Tasoitus koti -1.5"
        for v in vaihtoehdot:
            if v["name"] == ottelu["home_team"]:
                return "Tasoitus koti " + str(v["point"])

    # Tuntematon markkina: ei käytetä
    return None


def reilut_todennakoisyydet(vaihtoehdot):
    summa = 0
    for v in vaihtoehdot:
        summa = summa + 1 / v["price"]

    reilut = {}
    for v in vaihtoehdot:
        reilut[v["name"]] = (1 / v["price"]) / summa

    marginaali = (summa - 1) * 100
    return reilut, marginaali


def mallin_arviot(ottelu, tyyppi):
    # Palauttaa mallin todennäköisyydet tämän vetotyypin vaihtoehdoille,
    # esim. {"Ilves": 0.55, "Sport": 0.45}. None = malli ei osaa arvioida.
    sarja = ottelu["sport_title"]
    if sarja not in PMALLIT:
        return None
    pmalli = PMALLIT[sarja]
    nimet = MALLIN_NIMET.get(sarja, {})

    koti = ottelu["home_team"]
    vieras = ottelu["away_team"]
    m_koti = nimet.get(koti, koti)
    m_vieras = nimet.get(vieras, vieras)

    # Jos joukkuetta ei löydy mallista, ei arvata. Tulostetaan, jotta puuttuva
    # nimimuunnos huomataan heti.
    if m_koti not in pmalli["hyok"] or m_vieras not in pmalli["hyok"]:
        print("    (malli ei tunne joukkuetta:", m_koti, "/", m_vieras, ")")
        return None

    lk, lv = maaliodotukset(pmalli, m_koti, m_vieras)
    t = todennakoisyydet(lk, lv, pmalli["tasapelikerroin"])
    jakauma = t["jakauma"]

    if tyyppi == "Voittaja":
        return {koti: t["koti_voittaja"], vieras: 1 - t["koti_voittaja"]}

    if tyyppi == "1X2":
        return {koti: t["koti60"], vieras: t["vieras60"], "Draw": t["tasan"]}

    if tyyppi.startswith("Yli/alle"):
        raja = float(tyyppi.split(" ")[1])
        yli = sum(tn for (k, v), tn in jakauma.items() if k + v > raja)
        ali = sum(tn for (k, v), tn in jakauma.items() if k + v < raja)
        # Tasan rajalla = panos palautetaan, joten se jätetään pois
        return {"Over": yli / (yli + ali), "Under": ali / (yli + ali)}

    if tyyppi.startswith("Tasoitus"):
        raja = float(tyyppi.split(" ")[2])     # kotijoukkueen tasoitus
        koti_ok = sum(tn for (k, v), tn in jakauma.items() if k + raja - v > 0)
        vieras_ok = sum(tn for (k, v), tn in jakauma.items() if k + raja - v < 0)
        return {koti: koti_ok / (koti_ok + vieras_ok),
                vieras: vieras_ok / (koti_ok + vieras_ok)}

    return None


def tee_veto(ottelu, tyyppi, valinta, kerroin, yhtio, value, lahde):
    return {
        "sarja": ottelu["sport_title"],
        "id": ottelu["id"],
        "alkaa": ottelu["commence_time"],
        "ottelu": ottelu["home_team"] + " - " + ottelu["away_team"],
        "tyyppi": tyyppi,
        "valinta": valinta,
        "kerroin": kerroin,
        "yhtio": yhtio,
        "value": round(value, 1),
        "lahde": lahde,
    }


# ===== OTTELUIDEN KÄSITTELY =====
with open("ottelut.json", "r", encoding="utf-8") as tiedosto:
    ottelut = json.load(tiedosto)

# Nykyhetki UTC-aikana ja raja MAX_TUNNIT päähän
nyt = datetime.now(timezone.utc)
aikaraja = nyt + timedelta(hours=MAX_TUNNIT)

for ottelu in ottelut:
    alkaa = datetime.fromisoformat(ottelu["commence_time"].replace("Z", "+00:00"))

    # Ohitetaan jo alkaneet ja liian kaukana olevat ottelut
    if alkaa < nyt or alkaa > aikaraja:
        continue

    print()
    aika_fi = alkaa.astimezone().strftime("%d.%m. klo %H:%M")
    print("[" + ottelu["sport_title"] + "]", ottelu["home_team"], "vs", ottelu["away_team"], "|", aika_fi)

    # Kerätään saman vetotyypin markkinat samaan ryhmään:
    # tyyppi -> lista pareja (yhtiön nimi, vaihtoehdot)
    ryhmat = {}
    for yhtio in ottelu["bookmakers"]:
        for markkina in yhtio["markets"]:
            tyyppi = markkinan_tyyppi(markkina, ottelu)
            if tyyppi is None:
                continue
            if tyyppi not in ryhmat:
                ryhmat[tyyppi] = []
            ryhmat[tyyppi].append((yhtio["title"], markkina["outcomes"]))

    for tyyppi in ryhmat:
        reilut = {}
        parhaat = {}
        parhaan_yhtio = {}
        vertailu = None
        vaatii_60min = tyyppi.startswith("Yli/alle") or tyyppi.startswith("Tasoitus")

        for yhtio_nimi, vaihtoehdot in ryhmat[tyyppi]:
            # Ohitetaan yhtiöt, joiden säännöt voivat sisältää jatkoajan
            if vaatii_60min and yhtio_nimi not in YHTIOT_60MIN:
                continue
            yhtion_reilut, marginaali = reilut_todennakoisyydet(vaihtoehdot)

            if yhtio_nimi == VERTAILUYHTIO:
                vertailu = yhtion_reilut

            for v in vaihtoehdot:
                nimi = v["name"]

                # Paras kerroin vain yhtiöiltä, joita voi oikeasti käyttää
                if yhtio_nimi in KAYTETTAVAT_YHTIOT:
                    if nimi not in parhaat or v["price"] > parhaat[nimi]:
                        parhaat[nimi] = v["price"]
                        parhaan_yhtio[nimi] = yhtio_nimi

                # "Oikeaan" arvioon kaikki pienen marginaalin yhtiöt
                if marginaali <= MAX_MARGINAALI:
                    if nimi not in reilut:
                        reilut[nimi] = []
                    reilut[nimi].append(yhtion_reilut[nimi])

        # --- Kerroinvertailu ---
        markkinan_tn = {}   # vaihtoehto -> markkinan reilu todennäköisyys

        for nimi in parhaat:
            if nimi not in reilut:
                continue

            yhtioita = len(reilut[nimi])

            # Pinnacle voittaa, jos se on mukana. Muuten keskiarvo.
            if vertailu is not None:
                oikea = vertailu[nimi]
                lahde = "Pinnacle"
                # Jos Pinnacle on yksin eri mieltä kuin muut, käytetään keskiarvoa
                keskiarvo = sum(reilut[nimi]) / yhtioita
                if abs(oikea - keskiarvo) > MAX_POIKKEAMA:
                    oikea = keskiarvo
                    lahde = "keskiarvo (Pinnacle poikkesi)"
            else:
                oikea = sum(reilut[nimi]) / yhtioita
                lahde = "keskiarvo"

            markkinan_tn[nimi] = oikea

            paras = parhaat[nimi]
            value = (oikea * paras - 1) * 100

            # Riittävän luotettava: Pinnacle mukana TAI tarpeeksi monta yhtiötä
            luotettava = (vertailu is not None) or (yhtioita >= MIN_YHTIOT)

            merkki = ""
            if value >= MIN_VALUE and luotettava:
                if value > MAX_VALUE:
                    merkki = "  <-- TARKISTA (liian hyvä?)"
                else:
                    merkki = "  <-- VALUE"
                    loydetyt.append(tee_veto(ottelu, tyyppi, nimi, paras,
                                             parhaan_yhtio[nimi], value, lahde))

            # Varjokirjanpitoon kaikki positiiviset (myös yli 10 %, analyysiä varten)
            if value > 0 and luotettava:
                ehdokkaat.append(tee_veto(ottelu, tyyppi, nimi, paras,
                                          parhaan_yhtio[nimi], value, lahde))

            print("   ", tyyppi, "|", nimi,
                  "| oikea", round(oikea * 100, 1), "%", "(" + lahde + ")",
                  "| paras", paras, "(" + parhaan_yhtio[nimi] + ")",
                  "| value", round(value, 1), "%",
                  "| yhtiöitä", yhtioita,
                  merkki)

        # --- Oma Poisson-malli: Liigan kaikki vetotyypit ---
        arviot = mallin_arviot(ottelu, tyyppi)

        if arviot is not None:
            for nimi in parhaat:
                # Tarvitaan sekä mallin että markkinan arvio
                if nimi not in arviot or nimi not in markkinan_tn:
                    continue

                malli_tn = arviot[nimi]
                markkina_tn = markkinan_tn[nimi]
                yhdistetty = (1 - MALLIN_PAINO) * markkina_tn + MALLIN_PAINO * malli_tn

                paras = parhaat[nimi]
                malli_value = (yhdistetty * paras - 1) * 100

                merkki = ""
                if abs(malli_tn - markkina_tn) > MALLI_MAX_POIKKEAMA:
                    # Malli ei näe kokoonpanoja eikä kesän siirtoja: iso ero = mallin sokea piste
                    merkki = "  <-- OHITETAAN (malli liian eri mieltä kuin markkina)"
                elif malli_value > MALLI_MAX_VALUE:
                    merkki = "  <-- TARKISTA (malli ja markkina liian eri mieltä)"
                elif malli_value >= MALLI_MIN_VALUE:
                    merkki = "  <-- MALLIN YLIKERROIN"
                    loydetyt.append(tee_veto(ottelu, tyyppi, nimi, paras,
                                             parhaan_yhtio[nimi], malli_value, "Poisson-malli"))

                if malli_value > 0:
                    ehdokkaat.append(tee_veto(ottelu, tyyppi, nimi, paras,
                                              parhaan_yhtio[nimi], malli_value, "Poisson-malli"))

                print("    MALLI", tyyppi, "|", nimi,
                      "| markkina", round(markkina_tn * 100, 1), "%",
                      "| malli", round(malli_tn * 100, 1), "%",
                      "| yhdistetty", round(yhdistetty * 100, 1), "%",
                      "| paras", paras, "(" + parhaan_yhtio[nimi] + ")",
                      "| value", round(malli_value, 1), "%",
                      merkki)


# ===== YHTEENVETO =====
print()
print("===== PÄIVÄN VALUE-VEDOT =====")

if len(loydetyt) == 0:
    print("Ei value-vetoja näillä rajoilla.")
else:
    for veto in loydetyt:
        print("[" + veto["sarja"] + "]", veto["ottelu"], "|", veto["tyyppi"], veto["valinta"],
              "@", veto["kerroin"], "(" + veto["yhtio"] + ")",
              "| value", veto["value"], "% |", veto["lahde"])


# ===== OIKEA KIRJANPITO =====
# Valitaan jokaisesta ottelusta veto, jolla on suurin value
parhaat_vedot = {}   # ottelun id -> veto
for veto in loydetyt:
    oid = veto["id"]
    if oid not in parhaat_vedot or veto["value"] > parhaat_vedot[oid]["value"]:
        parhaat_vedot[oid] = veto

if os.path.exists(KIRJANPITO):
    with open(KIRJANPITO, "r", encoding="utf-8") as tiedosto:
        kirjanpito = json.load(tiedosto)
else:
    kirjanpito = []

kirjatut = []
for rivi in kirjanpito:
    kirjatut.append(rivi["id"])

uusia = 0
for oid in parhaat_vedot:
    if oid in kirjatut:
        continue          # tämä ottelu on jo kirjattu

    veto = parhaat_vedot[oid]
    veto["pvm"] = str(date.today())
    veto["panos"] = PANOS
    veto["tila"] = "avoin"            # myöhemmin: osui / ei osunut / mitätöity
    veto["versio"] = VERSIO
    kirjanpito.append(veto)
    uusia += 1

with open(KIRJANPITO, "w", encoding="utf-8") as tiedosto:
    json.dump(kirjanpito, tiedosto, ensure_ascii=False, indent=2)

print()
print("Kirjanpitoon lisätty", uusia, "uutta vetoa. Yhteensä", len(kirjanpito), "vetoa.")


# ===== VARJOKIRJANPITO =====
if os.path.exists(VARJO):
    with open(VARJO, "r", encoding="utf-8") as tiedosto:
        varjo = json.load(tiedosto)
else:
    varjo = []

# set = joukko, jossa sama arvo voi olla vain kerran
avaimet = set()
for rivi in varjo:
    avaimet.add(rivi["id"] + rivi["tyyppi"] + rivi["valinta"] + rivi["lahde"])

uusia_varjo = 0
for ehdokas in ehdokkaat:
    avain = ehdokas["id"] + ehdokas["tyyppi"] + ehdokas["valinta"] + ehdokas["lahde"]
    if avain in avaimet:
        continue            # sama ehdokas on jo kirjattu aiemmalla ajolla
    ehdokas["pvm"] = str(date.today())
    ehdokas["panos"] = PANOS
    ehdokas["tila"] = "avoin"
    ehdokas["versio"] = VERSIO
    varjo.append(ehdokas)
    avaimet.add(avain)
    uusia_varjo += 1

with open(VARJO, "w", encoding="utf-8") as tiedosto:
    json.dump(varjo, tiedosto, ensure_ascii=False, indent=2)

print("Varjokirjanpitoon lisätty", uusia_varjo, "ehdokasta. Yhteensä", len(varjo), ".")