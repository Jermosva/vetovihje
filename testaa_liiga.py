import requests

osoite = "https://liiga.fi/api/v2/schedule?tournament=runkosarja&season=2027"
pelit = requests.get(osoite).json()

for peli in pelit:
    if peli["ended"]:
        # [:10] = tekstin 10 ensimmäistä merkkiä, eli päivämäärä "2026-09-01"
        print(peli["start"][:10], peli["homeTeamName"], peli["homeTeamGoals"], "-",
              peli["awayTeamGoals"], peli["awayTeamName"], "|", peli["finishedType"])