import requests

osoite = ("https://www.shl.se/api/sports-v2/game-schedule"
          "?seasonUuid=ndcf81nlb3&seriesUuid=qQ9-bb0bzEWUk"
          "&gameTypeUuid=qQ9-af37Ti40B&gamePlace=all&played=all")

vastaus = requests.get(osoite)
print("Tilakoodi:", vastaus.status_code)

pelit = vastaus.json()["gameInfo"]
for peli in pelit:
    if peli["state"] == "post-game":
        koti = peli["homeTeamInfo"]
        vieras = peli["awayTeamInfo"]
        print(peli["rawStartDateTime"][:10], koti["names"]["long"], koti["score"], "-",
              vieras["score"], vieras["names"]["long"],
              "| OT" if peli["overtime"] else "", "| SO" if peli["shootout"] else "")