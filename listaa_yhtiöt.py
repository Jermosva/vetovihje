import json

with open("ottelut.json", "r", encoding="utf-8") as tiedosto:
    ottelut = json.load(tiedosto)

# set = joukko: kuin lista, mutta sama arvo voi olla siinä vain kerran
nimet = set()

for ottelu in ottelut:
    for yhtio in ottelu["bookmakers"]:
        nimet.add(yhtio["title"])     # add = lisää joukkoon

# sorted = aakkosjärjestykseen
for nimi in sorted(nimet):
    print(nimi)
KAYTETTAVAT_YHTIOT = [
    # Käytössä nyt (löytyvät The Odds API:sta)
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

    # PUUTTUU: löytyy vain UK-alueelta (lisätään, jos "uk" otetaan alueisiin)
    # "Betway",

    # PUUTTUU: vain ruotsalainen versio saatavilla, ei käytetä parhaana kertoimena
    # "Mr Green (SE)",
    # "Nya Expekt (SE)",
    # "Betinia (SE)",

    # PUUTTUU: ei The Odds API:ssa, tarvitaan toinen kerroinlähde
    # bet365, Paf, Betsafe, ComeOn, bwin, Interwetten, 22Bet, Bet-at-home,
    # Sportingbet, 10bet, BetRegal, Parimatch, Vivatbet, TonyBet, Betmaster,
    # Rabona, Melbet, Megapari, Mostbet, Betandyou, Betonic, Campeonbet,
    # N1 Bet, Favbet, Stake, Cloudbet, BC.Game, Thunderpick, Roobet,
    # MyStake, BetFury, FortuneJack, EpicBet
]