# Otetaan requests-kirjasto käyttöön
import requests
import os
from dotenv import load_dotenv

# Luetaan .env-tiedoston sisältö käyttöön
load_dotenv()

API_AVAIN = os.getenv("ODDS_API_KEY")

# Mikä sarja haetaan (tunnus sarjalistasta)
SARJA = "icehockey_liiga"
# Osoite, josta sarjalista haetaan
osoite = "https://api.the-odds-api.com/v4/sports/?apiKey=" + API_AVAIN

# Lähetetään pyyntö ja saadaan vastaus
vastaus = requests.get(osoite)

# Muutetaan vastaus Pythonin ymmärtämään muotoon (JSON -> lista)
sarjat = vastaus.json()

# Käydään lista läpi ja tulostetaan jokaisen sarjan nimi ja tunnus
for sarja in sarjat:
    print(sarja["title"], "-", sarja["key"])