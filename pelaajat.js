// Pelaajavedot-välilehti: pelaajien maali-, syöttö- ja pistetodennäköisyydet,
// omat kertoimet, vetojen tallennus GitHubiin, saldo ja mallin kalibraatio.
// Kaikki nimet ovat eri kuin sovellus.js:ssä, koska molemmat tiedostot jakavat saman sivun.

// ---------- Asetukset ----------

// Tiedostot luetaan GitHubista samalla tavalla kuin sovellus.js:ssä
const PELAAJA_RAAKA_OSOITE = "https://raw.githubusercontent.com/Jermosva/vetovihje/main/";

// Vetojen tallennus GitHub Contents API:lla. Token lähetetään VAIN tähän osoitteeseen.
const PELAAJA_API_OSOITE = "https://api.github.com/repos/Jermosva/vetovihje/contents/pelaajavedot.json";

// Illan kokoonpanot haetaan suoraan liiga.fi:stä (rajapinta sallii haut selaimesta)
const LIIGA_PELI_OSOITE = "https://liiga.fi/api/v2/games/";

// Pelaajavetojen kertoimet: Unibet, Paf ja LeoVegas käyttävät samaa Kambi-järjestelmää,
// jonka julkinen kerroinsyöte sallii haut selaimesta. Kertoimet ovat kaikilla samat.
const KAMBI_OSOITE = "https://eu-offering-api.kambicdn.com/offering/v2018/ub/";
const KAMBI_YHTIOT = "Unibet / Paf / LeoVegas";
const KAMBI_YHTIO = "Unibet";      // tallennuslomakkeen oletus, kun kerroin tulee Kambista
// Vihjelistaan vain, kun kerroin on vähintään 10 % yli rajakertoimen. Pienemmät erot ovat
// todennäköisemmin mallin virhettä kuin oikea ylikerroin.
const VIHJE_MARGINAALI = 0.10;
// Vain walk-forward-testissä mitatut vetotyypit (2+ maalia ja 3+ pistettä ei testattu)
const VIHJE_TYYPIT = ["maalit_1", "syotot_1", "pisteet_1", "pisteet_2"];
// Malli yli 10 %-yksikköä yhtiön arviota korkeammalla = todennäköinen mallin virhe
// (esim. ketju vaihtunut, loukkaantuminen), merkitään varoituksella
const VIHJE_RISTIRIITA = 0.10;
const VIHJEITA_NAKYVISSA = 10;    // loput "Näytä kaikki" -napin takana
// liiga.fi:n nimi -> Kambin nimen osa (muut nimet täsmäävät sellaisenaan, esim. "Sport" ~ "Vaasan Sport")
const KAMBI_JOUKKUEET = { "K-Espoo": "Espoo" };

// Vetotyypit valintalistaan: avain -> näytettävä nimi
const VETOTYYPIT = {
  "maalit_1": "Maali 1+",
  "maalit_2": "Maali 2+",
  "syotot_1": "Syöttö 1+",
  "syotot_2": "Syöttö 2+",
  "pisteet_1": "Piste 1+",
  "pisteet_2": "Piste 2+",
  "pisteet_3": "Piste 3+",
};
const OLETUS_VETOTYYPPI = "pisteet_1";

// Tyypin nimi saldotaulukossa
const TYYPPIEN_NIMET = { "maalit": "Maali", "syotot": "Syöttö", "pisteet": "Piste" };

const YHTIOT = ["Veikkaus", "Paf", "Unibet", "LeoVegas", "Expekt", "ComeOn",
                "Betsson", "NordicBet", "Betsafe", "EpicBet", "Muu"];
const OLETUS_PANOS = 10;

// Vedon tila -> merkki (samat kuin päävälilehdellä)
const VETOMERKIT = {
  "osui": "✅",
  "ei osunut": "❌",
  "mitätöity": "↩️",
  "avoin": "⏳",
};

// localStorage-avaimet (tallentuvat vain tähän selaimeen)
const TOKEN_AVAIN = "pelaajavedot_token";
const YHTIO_AVAIN = "pelaajavedot_yhtio";
const KERROIN_AVAIN = "pelaajavedot_kertoimet";

// ---------- Tila ----------

const pelaajaData = {
  ennusteet: null,      // pelaajaennusteet.json
  vedot: [],            // pelaajavedot.json
  tulokset: {},         // pelaajavedot_tulokset.json
  varjo: null,          // pelaajavarjo.json
  vedotLadattu: false,  // false = vetolistan lataus epäonnistui
  kokoonpanotHaettu: null,  // milloin illan kokoonpanot haettiin liiga.fi:stä
  kambi: {},            // ottelun avain -> pelaajan nimi -> vetotyyppi -> {kerroin, markkina}
  kambiTila: "haetaan", // "haetaan" | "ok" | "virhe"
};

const pelaajaValinnat = {
  ottelu: "kaikki",
  vetotyyppi: OLETUS_VETOTYYPPI,
  vainNousijat: false,
  kaikkiVihjeet: false,   // false = vihjelistassa vain parhaat
};

// Syötetyt kertoimet muistissa: "pvm|pelaaja_id|vetotyyppi" -> "2,15"
let kertoimet = {};
let pelaajadataLadattu = false;

// ---------- Pienet apufunktiot ----------

// Suojaa tekstin ennen innerHTML:ää, ettei esim. nimi "<b>" muutu HTML:ksi
function suojaa(teksti) {
  const korvaukset = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  return String(teksti === undefined || teksti === null ? "" : teksti)
    .replace(/[&<>"']/g, merkki => korvaukset[merkki]);
}

// Luku suomalaisittain: 2.045 -> "2,05" (desimaalit = montako desimaalia)
function desimaali(luku, desimaalit) {
  return luku.toFixed(desimaalit).replace(".", ",");
}

// 11.6 -> "+11,60 €"
function euroina(luku) {
  const etumerkki = luku > 0 ? "+" : "";
  return etumerkki + desimaali(luku, 2) + " €";
}

// 5.43 -> "+5,4 %"
function prosenttina(luku) {
  const etumerkki = luku > 0 ? "+" : "";
  return etumerkki + desimaali(luku, 1) + " %";
}

// Todennäköisyys prosentteina: 0.49 -> "49 %", alle 1 % -> "<1 %"
function tnTekstina(tn) {
  if (typeof tn !== "number") return "–";
  if (tn > 0 && tn < 0.005) return "<1 %";
  return Math.round(tn * 100) + " %";
}

// Rajakerroin = pienin kerroin, jolla veto kannattaa: 1 / tn
function rajakerroin(tn) {
  return tn > 0 ? 1 / tn : null;
}

function rajakerroinTekstina(tn) {
  const raja = rajakerroin(tn);
  return raja === null ? "–" : desimaali(raja, 2);
}

// Kerroin tekstistä: hyväksyy pilkun tai pisteen. Virheellinen -> null.
function lueKerroin(teksti) {
  const luku = parseFloat(String(teksti).trim().replace(",", "."));
  return Number.isFinite(luku) && luku > 1 ? luku : null;
}

// Value prosentteina yhdellä desimaalilla: (tn × kerroin − 1) × 100
// Pieni lisä korjaa liukulukuvirheen: 0.49 × 2.15 − 1 = 0.05349999... -> 5,4 eikä 5,3
function laskeValue(tn, kerroin) {
  const promillet = (tn * kerroin - 1) * 1000;
  return Math.sign(promillet) * Math.round(Math.abs(promillet) + 1e-6) / 10;
}

// "2026-11-18" -> "18.11.2026"
function pvmSuomeksi(pvm) {
  if (!pvm) {
    return "–";                       // ei tulevia pelejä (esim. kauden tauko)
  }
  const [vuosi, kk, pv] = pvm.split("-");
  return Number(pv) + "." + Number(kk) + "." + vuosi;
}

// ISO-aika -> kellonaika Suomen aikaa, esim. "18.30"
function kelloSuomeksi(aika) {
  return new Date(aika).toLocaleTimeString("fi-FI",
    { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Helsinki" });
}

// ISO-aika -> "18.11.2026" Suomen aikaa
function paivaSuomeksi(aika) {
  return new Date(aika).toLocaleDateString("fi-FI",
    { day: "numeric", month: "numeric", year: "numeric", timeZone: "Europe/Helsinki" });
}

// UTF-8-teksti base64:ksi (GitHub API haluaa sisällön base64-muodossa).
// Muunnetaan paloissa, ettei pitkä teksti kaada selainta liian monella argumentilla.
function tekstiBase64(teksti) {
  const tavut = new TextEncoder().encode(teksti);
  const PALA = 0x8000;
  let binaari = "";
  for (let i = 0; i < tavut.length; i += PALA) {
    binaari += String.fromCharCode.apply(null, tavut.subarray(i, i + PALA));
  }
  return btoa(binaari);
}

// base64 -> UTF-8-teksti (ä ja ö säilyvät oikein)
function base64Tekstiksi(base64) {
  const binaari = atob(base64.replace(/\s/g, ""));   // GitHub lisää rivinvaihtoja
  const tavut = new Uint8Array(binaari.length);
  for (let i = 0; i < binaari.length; i++) {
    tavut[i] = binaari.charCodeAt(i);
  }
  return new TextDecoder().decode(tavut);
}

// Neljä satunnaista merkkiä 0-9a-z vedon tunnisteeseen
function satunnainenTunniste() {
  let tulos = "";
  for (let i = 0; i < 4; i++) {
    tulos += Math.floor(Math.random() * 36).toString(36);
  }
  return tulos;
}

// "pisteet_1" -> { tyyppi: "pisteet", raja: 1 }
function puraVetotyyppi(avain) {
  const [tyyppi, raja] = avain.split("_");
  return { tyyppi: tyyppi, raja: Number(raja) };
}

// Rakentaa tallennettavan vedon tiedostosopimuksen mukaan
function rakennaVeto(ennusteet, ottelu, pelaaja, vetotyyppi, kerroin, yhtio, panos) {
  const { tyyppi, raja } = puraVetotyyppi(vetotyyppi);
  const tn = pelaaja.tn[vetotyyppi];
  return {
    id: "pv-" + ennusteet.pvm.replace(/-/g, "") + "-" + pelaaja.id + "-" + vetotyyppi + "-" + satunnainenTunniste(),
    pvm: ennusteet.pvm,
    avain: ottelu.avain,
    alkaa: ottelu.alkaa,
    ottelu: ottelu.koti + " - " + ottelu.vieras,
    pelaaja_id: pelaaja.id,
    pelaaja: pelaaja.nimi,
    joukkue: pelaaja.joukkue,
    tyyppi: tyyppi,
    raja: raja,
    kerroin: kerroin,
    yhtio: yhtio,
    panos: panos,
    tn: tn,
    value: laskeValue(tn, kerroin),
  };
}

// Yhdistää vedot ja tulokset id:n perusteella. Ratkaisematon veto saa tilan "avoin".
function yhdistaTulokset(vedot, tulokset) {
  return vedot.map(veto => {
    const tulos = tulokset[veto.id];
    return tulos ? Object.assign({}, veto, tulos) : Object.assign({}, veto, { tila: "avoin" });
  });
}

// Saldo ryhmittäin: Maali, Syöttö, Piste ja Yhteensä.
// Mitätöity veto palautetaan, joten se ei vaikuta osumiin eikä ROI:hin.
function laskePelaajasaldo(yhdistetyt) {
  const ryhmat = {};
  for (const nimi of ["Maali", "Syöttö", "Piste", "Yhteensä"]) {
    ryhmat[nimi] = { vedot: 0, osumat: 0, saldo: 0, panokset: 0, avoimet: 0 };
  }
  for (const veto of yhdistetyt) {
    for (const nimi of [TYYPPIEN_NIMET[veto.tyyppi], "Yhteensä"]) {
      const r = ryhmat[nimi];
      if (!r) continue;
      if (veto.tila === "avoin") {
        r.avoimet += 1;
      } else if (veto.tila === "osui" || veto.tila === "ei osunut") {
        r.vedot += 1;
        r.panokset += veto.panos;
        r.saldo += veto.voitto;
        if (veto.tila === "osui") r.osumat += 1;
      }
    }
  }
  return ryhmat;
}

// Kalibraatio: ennusteet 10 %:n väleihin ja kuinka usein ne toteutuivat.
// Palauttaa { avain: [ {n, malli, osui}, ... 10 väliä ] } ja ratkaistujen pelien määrän.
function laskeKalibraatio(varjo) {
  const avaimet = ["maalit_1", "syotot_1", "pisteet_1", "pisteet_2"];
  const valit = {};
  for (const avain of avaimet) {
    valit[avain] = [];
    for (let i = 0; i < 10; i++) valit[avain].push({ n: 0, malli: 0, osui: 0 });
  }

  let pelit = 0;
  for (const peli of Object.values(varjo || {})) {
    if (!peli || !Array.isArray(peli.tulokset)) continue;   // ratkaisematta
    pelit += 1;

    // pelaaja_id -> [maalit, syotot]
    const tulokset = {};
    for (const [id, maalit, syotot] of peli.tulokset) {
      tulokset[id] = [maalit, syotot];
    }

    for (const [id, m1, s1, p1, p2] of peli.ennusteet || []) {
      if (!(id in tulokset)) continue;       // ei kokoonpanossa -> ei lasketa
      const [maalit, syotot] = tulokset[id];
      const pisteet = maalit + syotot;
      const rivit = [
        ["maalit_1", m1, maalit >= 1],
        ["syotot_1", s1, syotot >= 1],
        ["pisteet_1", p1, pisteet >= 1],
        ["pisteet_2", p2, pisteet >= 2],
      ];
      for (const [avain, tn, osui] of rivit) {
        if (typeof tn !== "number") continue;
        // Pieni lisä estää liukulukuvirheen (0.3*10 = 2.9999...)
        const vali = Math.min(9, Math.max(0, Math.floor(tn * 10 + 1e-9)));
        const v = valit[avain][vali];
        v.n += 1;
        v.malli += tn;
        if (osui) v.osui += 1;
      }
    }
  }
  return { valit: valit, pelit: pelit };
}

// ---------- localStorage (aina try/catch: voi puuttua yksityisessä selaimessa) ----------

function lueMuisti(avain) {
  try {
    return localStorage.getItem(avain);
  } catch (virhe) {
    return null;
  }
}

function kirjoitaMuisti(avain, arvo) {
  try {
    if (arvo === null) localStorage.removeItem(avain);
    else localStorage.setItem(avain, arvo);
  } catch (virhe) {
    // Ei haittaa: tieto vain unohtuu sivun uudelleenlatauksessa
  }
}

function lueToken() {
  return lueMuisti(TOKEN_AVAIN) || "";
}

function lueKertoimetMuistista() {
  try {
    kertoimet = JSON.parse(lueMuisti(KERROIN_AVAIN) || "{}") || {};
  } catch (virhe) {
    kertoimet = {};
  }
}

// Unohdetaan muiden päivien kertoimet, ettei muisti kasva loputtomasti
function siivoaKertoimet(pvm) {
  for (const avain of Object.keys(kertoimet)) {
    if (!avain.startsWith(pvm + "|")) delete kertoimet[avain];
  }
  kirjoitaMuisti(KERROIN_AVAIN, JSON.stringify(kertoimet));
}

function kerroinAvain(pelaajaId, vetotyyppi) {
  return pelaajaData.ennusteet.pvm + "|" + pelaajaId + "|" + vetotyyppi;
}

// ---------- Tiedostojen lataus ----------

// Paikallisessa testissä luetaan tiedostot samasta kansiosta kuin sivu
function onPaikallinen() {
  return location.protocol === "file:" ||
    location.hostname === "localhost" || location.hostname === "127.0.0.1";
}

function tiedostonOsoite(nimi) {
  const pohja = onPaikallinen() ? "" : PELAAJA_RAAKA_OSOITE;
  return pohja + nimi + "?t=" + Date.now();
}

// Hakee JSON-tiedoston. Palauttaa { tila: "ok" | "puuttuu" | "virhe", data }.
async function haeTiedosto(nimi) {
  try {
    const vastaus = await fetch(tiedostonOsoite(nimi));
    if (vastaus.status === 404) return { tila: "puuttuu", data: null };
    if (!vastaus.ok) return { tila: "virhe", data: null };
    return { tila: "ok", data: await vastaus.json() };
  } catch (virhe) {
    return { tila: "virhe", data: null };
  }
}

// Ystävällinen viesti, kun tiedostoa ei saatu
function latausviesti(tulos, puuttuuTeksti) {
  if (tulos.tila === "puuttuu") return puuttuuTeksti;
  if (location.protocol === "file:") {
    return "Tiedostoa ei voi lukea suoraan levyltä. Käynnistä kansiossa: python -m http.server ja avaa http://localhost:8000";
  }
  return "Lataus epäonnistui. Yritä hetken päästä uudelleen.";
}

async function lataaPelaajadata() {
  pelaajadataLadattu = true;
  lueKertoimetMuistista();

  // Haetaan kaikki neljä tiedostoa yhtä aikaa
  const [ennusteet, vedot, tulokset, varjo] = await Promise.all([
    haeTiedosto("pelaajaennusteet.json"),
    haeVedotLuettavaksi(),
    haeTiedosto("pelaajavedot_tulokset.json"),
    haeTiedosto("pelaajavarjo.json"),
  ]);

  pelaajaData.vedot = Array.isArray(vedot.data) ? vedot.data : [];
  pelaajaData.vedotLadattu = vedot.tila !== "virhe";
  pelaajaData.tulokset = tulokset.data || {};
  pelaajaData.varjo = varjo.data;

  // Jokainen osa piirretään erikseen: yhden osan virhe ei kaada muita
  try {
    if (ennusteet.tila === "ok") {
      pelaajaData.ennusteet = ennusteet.data;
      siivoaKertoimet(ennusteet.data.pvm);
      naytaPelaajaOtsikko();
      naytaSuodattimet();
      naytaOttelut();
      // Ei odoteta: sivu näkyy heti, ja ennusteet ja kertoimet päivittyvät, kun ne saapuvat
      paivitaKokoonpanot();
      paivitaKambi();
    } else {
      document.getElementById("pelaaja-ottelut").innerHTML = `<div class="viestikortti">${suojaa(
        latausviesti(ennusteet, "Pelaajaennusteita ei ole vielä julkaistu. Ne päivittyvät pelipäivinä."))}</div>`;
    }
  } catch (virhe) {
    document.getElementById("pelaaja-ottelut").innerHTML =
      `<div class="viestikortti">Ennusteiden näyttäminen epäonnistui: ${suojaa(virhe.message)}</div>`;
  }

  try {
    naytaPelaajasaldo(tulokset.tila === "virhe");
  } catch (virhe) {
    document.getElementById("pelaaja-saldo").innerHTML =
      `<div class="viestikortti">Saldon näyttäminen epäonnistui: ${suojaa(virhe.message)}</div>`;
  }

  try {
    naytaKalibraatio(varjo);
  } catch (virhe) {
    document.getElementById("pelaaja-kalibraatio").innerHTML =
      `<div class="viestikortti">Kalibraation näyttäminen epäonnistui: ${suojaa(virhe.message)}</div>`;
  }
}

// Jos token on asetettu, vetolista luetaan API:sta (raw-osoite voi näyttää
// vanhaa versiota muutaman minuutin). Muuten luetaan kuten muutkin tiedostot.
async function haeVedotLuettavaksi() {
  if (lueToken()) {
    try {
      const tiedosto = await haeVedotApista();
      return { tila: "ok", data: tiedosto.lista };
    } catch (virhe) {
      // Ei haittaa: kokeillaan tavallista latausta
    }
  }
  return haeTiedosto("pelaajavedot.json");
}

// ---------- Illan kokoonpanot suoraan liiga.fi:stä ----------
// GitHubin ajastetut ajot käynnistyvät usein tunteja myöhässä, joten ajo ei ehdi
// laskea ennusteita kokoonpanojen julkaisun (klo 12) ja pelien alun välissä.
// Siksi ajo tallentaa pelaajien tasot valmiiksi, ja sivu hakee kokoonpanon itse
// ja laskee ennusteet samalla tavalla kuin pelaajamalli.py (pelaajan_ennuste).

// Sama kuin pelaajamalli.py:n rooli(): esim. "H1" = ykkösketjun hyökkääjä
function pelaajanRooli(paikka, roolikoodi, ketju) {
  const lisapelaaja = Boolean(roolikoodi) && /^\d/.test(roolikoodi);   // "13. H", "7. P"...
  if (paikka === "H" && (lisapelaaja || ketju >= 5)) return "H13";
  if (paikka === "P" && (lisapelaaja || ketju >= 4)) return "P7";
  return paikka + ketju;
}

// Poisson: P(X ≥ k) = 1 − P(0) − ... − P(k−1)
function vahintaan(lam, k) {
  let summa = 0;
  let termi = Math.exp(-lam);
  for (let i = 0; i < k; i++) {
    summa += termi;
    termi *= lam / (i + 1);
  }
  return 1 - summa;
}

function pyorista(luku, desimaalit) {
  const kerroin = 10 ** desimaalit;
  return Math.round(luku * kerroin) / kerroin;
}

// Yksi pelaajarivi samassa muodossa kuin pelaajaennusteet.json:n "pelaajat"
function laskePelaajanEnnuste(malli, pelaaja, joukkue, kerroin, tasot) {
  const paikka = (pelaaja.role || "").includes("DEFENSEMAN") ? "P" : "H";
  const rooli = pelaajanRooli(paikka, pelaaja.roleCode, pelaaja.line);
  const [em, es] = malli.tahdit[rooli] || malli.tahdit[paikka + "4"] || [0.05, 0.1];

  // Uusi pelaaja, jota ei ollut pelaajistossa ajon aikaan = roolinsa keskitaso
  const t = tasot || {
    taso: [1, 1], aiempi: [1, 1],
    kausi: { ottelut: 0, maalit: 0, syotot: 0, pisteet: 0 },
    viime: { ottelut: 0, maalit: 0, syotot: 0, pisteet: 0 },
  };
  const lamM = t.taso[0] * em * kerroin;
  const lamS = t.taso[1] * es * kerroin;
  const lamP = lamM + lamS;

  // Nousija: odotus verrattuna pelaajan tasoon ennen tätä kautta
  const aiempi = (t.aiempi[0] * em + t.aiempi[1] * es) * kerroin;
  const nosto = lamP / aiempi - 1;
  const nousija = nosto >= malli.nousija_raja && t.kausi.ottelut >= malli.nousija_min_pelit
    ? { nosto: pyorista(nosto, 2), aiempi: pyorista(aiempi, 3), nyt: pyorista(lamP, 3) }
    : null;

  const tn = {
    maalit_1: vahintaan(lamM, 1), maalit_2: vahintaan(lamM, 2),
    syotot_1: vahintaan(lamS, 1), syotot_2: vahintaan(lamS, 2),
    pisteet_1: vahintaan(lamP, 1), pisteet_2: vahintaan(lamP, 2), pisteet_3: vahintaan(lamP, 3),
  };
  for (const avain in tn) tn[avain] = pyorista(tn[avain], 4);

  return {
    id: pelaaja.id, nimi: pelaaja.firstName + " " + pelaaja.lastName, joukkue: joukkue,
    pp: paikka, ketju: pelaaja.line,
    kausi: t.kausi, viime: t.viime,
    lambda: { maalit: pyorista(lamM, 3), syotot: pyorista(lamS, 3) },
    tn: tn, nousija: nousija,
  };
}

// Laskee ottelun pelaajat liiga.fi:n ottelutiedoista. Palauttaa false, jos
// kokoonpanoa ei ole vielä julkaistu.
function laskeOttelunPelaajat(malli, ottelu, data) {
  const kentalla = lista => (lista || []).filter(p => p.line != null && p.role !== "GOALIE");
  const aloittaja = lista => {
    const vahti = (lista || []).find(p => p.role === "GOALIE" && p.line === 1);
    return vahti ? String(vahti.id) : null;
  };
  const koti = kentalla(data.homeTeamPlayers);
  const vieras = kentalla(data.awayTeamPlayers);
  if (koti.length === 0 || vieras.length === 0) return false;

  // Ottelukerroin: pohja × vastustajan aloittavan maalivahdin vaikutus, painotettuna
  const kerroin = (pohja, vastustajanVahti) => {
    const taso = (ottelu.vahdit || {})[vastustajanVahti] || 0;
    return (pohja * (1 - malli.mv_paino * taso)) ** malli.ottelukerroin_paino;
  };
  const kotiKerroin = kerroin(ottelu.kerroin_pohja[0], aloittaja(data.awayTeamPlayers));
  const vierasKerroin = kerroin(ottelu.kerroin_pohja[1], aloittaja(data.homeTeamPlayers));

  const tasot = ottelu.pelaajatasot || {};
  const rivit = [
    ...koti.map(p => laskePelaajanEnnuste(malli, p, ottelu.koti, kotiKerroin, tasot[String(p.id)])),
    ...vieras.map(p => laskePelaajanEnnuste(malli, p, ottelu.vieras, vierasKerroin, tasot[String(p.id)])),
  ];
  rivit.sort((a, b) => b.tn.pisteet_1 - a.tn.pisteet_1);
  ottelu.pelaajat = rivit;
  ottelu.kokoonpano = true;
  return true;
}

// Hakee illan kokoonpanot ja laskee ennusteet uudelleen. Jos haku epäonnistuu,
// sivulla pysyvät tiedoston ennusteet (jos ajo ehti laskea ne).
async function paivitaKokoonpanot() {
  const e = pelaajaData.ennusteet;
  if (!e || !e.malli) return;              // vanha tiedostomuoto: ei tasoja
  const ottelut = (e.ottelut || []).filter(o => o.pelaajatasot && o.kerroin_pohja);

  const tulokset = await Promise.all(ottelut.map(async ottelu => {
    const [kausi, id] = ottelu.avain.split("_");
    try {
      const vastaus = await fetch(LIIGA_PELI_OSOITE + kausi + "/" + id, { cache: "no-store" });
      if (!vastaus.ok) return false;
      return laskeOttelunPelaajat(e.malli, ottelu, await vastaus.json());
    } catch (virhe) {
      return false;
    }
  }));

  if (tulokset.some(Boolean)) {
    pelaajaData.kokoonpanotHaettu = new Date().toISOString();
    naytaPelaajaOtsikko();
    naytaOttelut();
  }
}

// ---------- Kertoimet Kambista (Unibet, Paf, LeoVegas) ----------

// Nimi vertailukelpoiseksi: "Jiří Ticháček" -> "jiri tichacek", "K-Espoo" -> "k espoo"
function vertailunimi(nimi) {
  return (nimi || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, " ").trim();
}

function samaJoukkue(liigaNimi, kambiNimi) {
  const a = vertailunimi(KAMBI_JOUKKUEET[liigaNimi] || liigaNimi);
  const b = vertailunimi(kambiNimi);
  return a !== "" && b !== "" && (b.includes(a) || a.includes(b));
}

// Kambin markkina -> vetotyypin avain, esim. "Player to score at least 2 points -
// Including Overtime" + raja 2 -> "pisteet_2". Muut markkinat (1. maalintekijä,
// ilman jatkoaikaa olevat ym.) ohitetaan.
function kambiVetotyyppi(markkina, raja) {
  const nimi = markkina.toLowerCase();
  if (!nimi.includes("including overtime") || nimi.includes("1st") || nimi.includes("last")) return null;
  let tyyppi = null;
  if (nimi.includes("assist")) tyyppi = "syotot";
  else if (nimi.includes("point")) tyyppi = "pisteet";
  else if (nimi.startsWith("to score")) tyyppi = "maalit";
  if (tyyppi === null) return null;
  const avain = tyyppi + "_" + raja;
  return avain in VETOTYYPIT ? avain : null;
}

// Yhden ottelun vetotarjoukset -> {pelaajan vertailunimi: {vetotyyppi: {kerroin, markkina}}}
// markkina = yhtiön oma todennäköisyys ilman marginaalia (vain jos "Ei"-vaihtoehto on tarjolla)
function luePelaajakertoimet(vetotarjoukset) {
  const tulos = {};
  for (const tarjous of vetotarjoukset || []) {
    const kylla = {};
    const ei = {};
    for (const vaihtoehto of tarjous.outcomes || []) {
      if (!vaihtoehto.participant || vaihtoehto.status !== "OPEN" || !vaihtoehto.odds) continue;
      const raja = Math.round((vaihtoehto.line || 1000) / 1000);
      const avain = kambiVetotyyppi(tarjous.criterion.englishLabel || "", raja);
      if (avain === null) continue;
      const kohde = vaihtoehto.type === "OT_NO" ? ei : kylla;
      kohde[vertailunimi(vaihtoehto.participant) + "|" + avain] = vaihtoehto.odds / 1000;
    }
    for (const tunniste in kylla) {
      const [nimi, avain] = tunniste.split("|");
      const kerroin = kylla[tunniste];
      let markkina = null;
      if (ei[tunniste]) {
        markkina = (1 / kerroin) / (1 / kerroin + 1 / ei[tunniste]);
      }
      if (!tulos[nimi]) tulos[nimi] = {};
      tulos[nimi][avain] = { kerroin: kerroin, markkina: markkina };
    }
  }
  return tulos;
}

// Pelaajan kertoimet. Kambin nimet poikkeavat joskus liiga.fi:stä, joten kokeillaan
// järjestyksessä: sama nimi, samat nimen osat eri järjestyksessä ("Makinen Ilari"),
// sama sukunimi ja etunimen alkukirjain ("Matt Caito" ~ "Matthew Caito").
function pelaajanKertoimet(ottelu, pelaaja) {
  const kertoimetOttelu = pelaajaData.kambi[ottelu.avain];
  if (!kertoimetOttelu) return {};
  const nimi = vertailunimi(pelaaja.nimi);
  if (kertoimetOttelu[nimi]) return kertoimetOttelu[nimi];

  const osat = nimi.split(" ");
  const jarjestetty = osat.slice().sort().join(" ");
  const sukunimi = osat.slice(1).join(" ");
  // Varanimiksi ei kelpaa nimi, joka on jonkun toisen ottelun pelaajan oma nimi
  // (esim. veljekset samalla sukunimellä ja alkukirjaimella)
  const omatNimet = new Set([
    ...Object.values(ottelu.pelaajatasot || {}).map(t => vertailunimi(t.nimi)),
    ...(ottelu.pelaajat || []).map(p => vertailunimi(p.nimi)),
  ]);
  const kambiNimet = Object.keys(kertoimetOttelu).filter(n => !omatNimet.has(n));
  const kokeilut = [
    n => n.split(" ").sort().join(" ") === jarjestetty,
    n => {
      const o = n.split(" ");
      return o.slice(1).join(" ") === sukunimi && o[0][0] === osat[0][0];
    },
  ];
  for (const kokeilu of kokeilut) {
    const ehdokkaat = kambiNimet.filter(kokeilu);
    if (ehdokkaat.length === 1) return kertoimetOttelu[ehdokkaat[0]];
  }
  return {};
}

// Paras tiedossa oleva kerroin: itse syötetty (esim. EpicBet) tai Kambin, kumpi suurempi.
// Palauttaa {kerroin, lahde, markkina} tai null. markkina tulee aina Kambista.
function pelaajanKerroin(ottelu, pelaaja, avain) {
  const kambi = pelaajanKertoimet(ottelu, pelaaja)[avain] || null;
  const oma = lueKerroin(kertoimet[kerroinAvain(pelaaja.id, avain)] || "");
  const markkina = kambi ? kambi.markkina : null;
  if (oma !== null && (!kambi || oma > kambi.kerroin)) {
    return { kerroin: oma, lahde: "oma", markkina: markkina };
  }
  return kambi ? { kerroin: kambi.kerroin, lahde: KAMBI_YHTIO, markkina: markkina } : null;
}

async function haeKambi(polku) {
  const vastaus = await fetch(KAMBI_OSOITE + polku + (polku.includes("?") ? "&" : "?") +
    "lang=en_GB&market=FI", { cache: "no-store" });
  if (!vastaus.ok) throw new Error("Kambi " + vastaus.status);
  return vastaus.json();
}

async function paivitaKambi() {
  const e = pelaajaData.ennusteet;
  try {
    const lista = await haeKambi("listView/ice_hockey/finland/liiga/all/matches.json");
    // Liigan ottelu -> Kambin ottelu: samat joukkueet ja alkuaika enintään 3 h eri
    const parit = [];
    for (const ottelu of e.ottelut || []) {
      const alkaa = new Date(ottelu.alkaa).getTime();
      const loydetty = (lista.events || []).find(k =>
        samaJoukkue(ottelu.koti, k.event.homeName) && samaJoukkue(ottelu.vieras, k.event.awayName) &&
        Math.abs(new Date(k.event.start).getTime() - alkaa) < 3 * 3600 * 1000);
      if (loydetty) parit.push([ottelu.avain, loydetty.event.id]);
    }
    await Promise.all(parit.map(async ([avain, id]) => {
      try {
        const tarjoukset = await haeKambi("betoffer/event/" + id + ".json");
        pelaajaData.kambi[avain] = luePelaajakertoimet(tarjoukset.betOffers);
      } catch (virhe) {
        // Yhden ottelun virhe ei estä muita
      }
    }));
    pelaajaData.kambiTila = "ok";
  } catch (virhe) {
    pelaajaData.kambiTila = "virhe";
  }
  naytaOttelut();
}

// ---------- Näkymä: vihjelista ----------

// Kaikki illan vedot, joissa paras kerroin (Kambi tai oma) on selvästi yli mallin rajakertoimen
function laskeVihjeet() {
  const vihjeet = [];
  for (const ottelu of pelaajaData.ennusteet.ottelut || []) {
    for (const pelaaja of ottelu.pelaajat || []) {
      for (const avain of VIHJE_TYYPIT) {
        const paras = pelaajanKerroin(ottelu, pelaaja, avain);
        const tn = pelaaja.tn[avain];
        if (!paras || typeof tn !== "number" || tn * paras.kerroin < 1 + VIHJE_MARGINAALI) continue;
        vihjeet.push({ ottelu, pelaaja, avain, tn, kerroin: paras.kerroin, lahde: paras.lahde,
                       markkina: paras.markkina, value: laskeValue(tn, paras.kerroin) });
      }
    }
  }
  vihjeet.sort((a, b) => b.value - a.value);
  return vihjeet;
}

function naytaVihjeet() {
  const kohde = document.getElementById("pelaaja-vihjeet");
  if (!kohde || !pelaajaData.ennusteet) return;

  const otsikko = `<h2>Vihjeet · ${KAMBI_YHTIOT}</h2>`;
  if (pelaajaData.kambiTila === "haetaan") {
    kohde.innerHTML = `<div class="peli-kortti">${otsikko}<p class="selite">Haetaan kertoimia...</p></div>`;
    return;
  }
  if (pelaajaData.kambiTila === "virhe") {
    kohde.innerHTML = `<div class="peli-kortti">${otsikko}<p class="selite">Kertoimien haku epäonnistui. Syötä kertoimet itse taulukkoon.</p></div>`;
    return;
  }

  const vihjeet = laskeVihjeet();
  const selite = `<p class="selite">Kerroin vähintään ${Math.round(VIHJE_MARGINAALI * 100)} % yli mallin rajakertoimen.
    Jos olet syöttänyt taulukkoon paremman kertoimen (esim. EpicBet), käytetään sitä (merkintä "oma").
    Markkina = yhtiön oma arvio ilman marginaalia. ⚠ = malli yli ${Math.round(VIHJE_RISTIRIITA * 100)} %-yks.
    markkinaa korkeammalla: tarkista kokoonpano ja uutiset ennen pelaamista.
    Paina riviä nähdäksesi pelaajan taulukossa.</p>`;
  if (vihjeet.length === 0) {
    const kokoonpanoja = (pelaajaData.ennusteet.ottelut || []).some(o => o.kokoonpano);
    kohde.innerHTML = `<div class="peli-kortti">${otsikko}<p class="selite">${kokoonpanoja
      ? "Ei ylikertoimia tällä hetkellä."
      : "Kokoonpanoja ei ole vielä julkaistu (pelipäivänä klo 12)."}</p></div>`;
    return;
  }

  const nakyvat = pelaajaValinnat.kaikkiVihjeet ? vihjeet : vihjeet.slice(0, VIHJEITA_NAKYVISSA);
  const rivit = nakyvat.map(v => {
    const nousija = v.pelaaja.nousija
      ? ` <span class="nousija">▲ +${Math.round(v.pelaaja.nousija.nosto * 100)} %</span>` : "";
    const ristiriita = v.markkina !== null && v.tn - v.markkina > VIHJE_RISTIRIITA
      ? ` <span title="Malli on selvästi yhtiön arviota korkeammalla: tarkista kokoonpano ja uutiset">⚠</span>` : "";
    return `
      <tr class="vihjerivi" data-avain="${suojaa(v.ottelu.avain)}" data-id="${suojaa(v.pelaaja.id)}" data-tyyppi="${v.avain}">
        <td class="nimi">${suojaa(v.pelaaja.nimi)}${nousija}${ristiriita}</td>
        <td>${suojaa(v.pelaaja.joukkue)}</td>
        <td>${VETOTYYPIT[v.avain]}</td>
        <td><strong>${desimaali(v.kerroin, 2)}</strong>${v.lahde === "oma" ? ` <span class="kambi-tieto">oma</span>` : ""}</td>
        <td>${rajakerroinTekstina(v.tn)}</td>
        <td>${tnTekstina(v.tn)}</td>
        <td>${v.markkina === null ? "–" : tnTekstina(v.markkina)}</td>
        <td class="plus">${prosenttina(v.value)}</td>
      </tr>`;
  }).join("");

  kohde.innerHTML = `
    <div class="peli-kortti">
      ${otsikko}
      ${selite}
      <div class="taulukko-vieritys">
        <table class="pelaajataulukko">
          <thead><tr><th class="nimi">Pelaaja</th><th>Joukkue</th><th>Veto</th><th>Kerroin</th>
            <th>Raja</th><th>Malli</th><th>Markkina</th><th>Value</th></tr></thead>
          <tbody>${rivit}</tbody>
        </table>
      </div>
      ${vihjeet.length > VIHJEITA_NAKYVISSA
        ? `<button type="button" class="pieni-nappi" id="vihjeet-kaikki">${pelaajaValinnat.kaikkiVihjeet
          ? "Näytä vain " + VIHJEITA_NAKYVISSA + " parasta" : "Näytä kaikki (" + vihjeet.length + ")"}</button>`
        : ""}
    </div>`;
}

// Vihjeen painallus: valitaan sen ottelu ja vetotyyppi ja vieritetään pelaajan riville
function kytkeVihjeet() {
  document.getElementById("pelaaja-vihjeet").addEventListener("click", tapahtuma => {
    if (tapahtuma.target.id === "vihjeet-kaikki") {
      pelaajaValinnat.kaikkiVihjeet = !pelaajaValinnat.kaikkiVihjeet;
      naytaVihjeet();
      return;
    }
    const rivi = tapahtuma.target.closest(".vihjerivi");
    if (!rivi) return;
    pelaajaValinnat.ottelu = rivi.dataset.avain;
    pelaajaValinnat.vetotyyppi = rivi.dataset.tyyppi;
    pelaajaValinnat.vainNousijat = false;
    document.getElementById("valitse-ottelu").value = pelaajaValinnat.ottelu;
    document.getElementById("valitse-vetotyyppi").value = pelaajaValinnat.vetotyyppi;
    document.getElementById("vain-nousijat").checked = false;
    naytaOttelut();
    const kohde = document.querySelector(`#pelaaja-ottelut tr[data-id="${CSS.escape(rivi.dataset.id)}"]`);
    if (kohde) {
      kohde.scrollIntoView({ behavior: "smooth", block: "center" });
      kohde.classList.add("korostus");
    }
  });
}

// ---------- GitHub API ----------

function apiOtsakkeet() {
  return {
    "Authorization": "Bearer " + lueToken(),
    "Accept": "application/vnd.github+json",
  };
}

// Virheilmoitus ilman tokenia tai muuta salaista
function apiVirhe(status) {
  if (status === 401) return new Error("Token ei kelpaa tai se on vanhentunut (401).");
  if (status === 403) return new Error("Tokenilta puuttuu oikeus Contents: Read and write (403).");
  if (status === 404) return new Error("Repoa ei löytynyt tai token ei näe sitä (404).");
  return new Error("GitHub vastasi virheellä " + status + ".");
}

// Hakee pelaajavedot.json:n API:sta. Palauttaa { lista, sha } (sha = null jos tiedostoa ei ole).
async function haeVedotApista() {
  const vastaus = await fetch(PELAAJA_API_OSOITE + "?ref=main",
    { headers: apiOtsakkeet(), cache: "no-store" });
  if (vastaus.status === 404) {
    // 404 voi tarkoittaa myös, ettei token näe repoa. Tarkistetaan repo erikseen.
    const repo = await fetch("https://api.github.com/repos/Jermosva/vetovihje",
      { headers: apiOtsakkeet(), cache: "no-store" });
    if (!repo.ok) throw apiVirhe(repo.status);
    return { lista: [], sha: null };
  }
  if (!vastaus.ok) throw apiVirhe(vastaus.status);

  const tiedosto = await vastaus.json();
  // Yli 1 Mt:n tiedostosta API ei palauta sisältöä. Silloin ei saa tallentaa
  // tyhjää listaa vanhojen vetojen päälle, joten keskeytetään.
  if (tiedosto.encoding !== "base64" && tiedosto.size > 0) {
    throw new Error("pelaajavedot.json on liian suuri luettavaksi API:n kautta.");
  }
  const teksti = base64Tekstiksi(tiedosto.content || "").trim();
  const lista = teksti === "" ? [] : JSON.parse(teksti);
  if (!Array.isArray(lista)) throw new Error("pelaajavedot.json ei ole lista.");
  return { lista: lista, sha: tiedosto.sha };
}

// Muokkaa vetolistaa GitHubissa: hae -> muuta -> tallenna.
// Jos joku ehti muuttaa tiedostoa välissä (409/422), yritetään kerran uudelleen.
async function muokkaaVetoja(muutos, viesti) {
  for (let yritys = 1; yritys <= 2; yritys++) {
    const { lista, sha } = await haeVedotApista();
    const uusiLista = muutos(lista);

    const runko = {
      message: viesti,
      content: tekstiBase64(JSON.stringify(uusiLista, null, 2) + "\n"),
      branch: "main",
    };
    if (sha) runko.sha = sha;

    const vastaus = await fetch(PELAAJA_API_OSOITE, {
      method: "PUT",
      headers: Object.assign({ "Content-Type": "application/json" }, apiOtsakkeet()),
      body: JSON.stringify(runko),
    });

    if (vastaus.ok) return uusiLista;
    if ((vastaus.status === 409 || vastaus.status === 422) && yritys === 1) continue;
    throw apiVirhe(vastaus.status);
  }
}

// ---------- Näkymä: otsikko ja suodattimet ----------

function naytaPelaajaOtsikko() {
  const e = pelaajaData.ennusteet;
  let paivitetty = "";
  if (e.paivitetty) {
    // Päivämäärä näytetään vain, jos päivitys on tehty eri päivänä kuin pelipäivä
    const paiva = paivaSuomeksi(e.paivitetty);
    paivitetty = " · päivitetty " + (paiva === pvmSuomeksi(e.pvm) ? "" : paiva + " ") +
      "klo " + kelloSuomeksi(e.paivitetty);
  }
  // Kokoonpanot haetaan selaimessa suoraan liiga.fi:stä (ks. paivitaKokoonpanot)
  const kokoonpanot = pelaajaData.kokoonpanotHaettu
    ? " · kokoonpanot liiga.fi:stä klo " + kelloSuomeksi(pelaajaData.kokoonpanotHaettu)
    : "";
  document.getElementById("pelaaja-otsikko").textContent =
    "Pelipäivä " + pvmSuomeksi(e.pvm) + paivitetty + kokoonpanot;
}

function ottelunNimi(ottelu) {
  return ottelu.koti + " - " + ottelu.vieras + " klo " + kelloSuomeksi(ottelu.alkaa);
}

function naytaSuodattimet() {
  const ottelut = pelaajaData.ennusteet.ottelut || [];

  let otteluvaihtoehdot = `<option value="kaikki">Kaikki</option>`;
  for (const ottelu of ottelut) {
    otteluvaihtoehdot += `<option value="${suojaa(ottelu.avain)}">${suojaa(ottelunNimi(ottelu))}</option>`;
  }

  let tyyppivaihtoehdot = "";
  for (const avain in VETOTYYPIT) {
    const valittu = avain === pelaajaValinnat.vetotyyppi ? " selected" : "";
    tyyppivaihtoehdot += `<option value="${avain}"${valittu}>${VETOTYYPIT[avain]}</option>`;
  }

  const suodattimet = document.getElementById("pelaaja-suodattimet");
  suodattimet.innerHTML = `
    <label>Ottelu
      <select id="valitse-ottelu">${otteluvaihtoehdot}</select>
    </label>
    <label>Vetotyyppi
      <select id="valitse-vetotyyppi">${tyyppivaihtoehdot}</select>
    </label>
    <label class="valintaruutu">
      <input type="checkbox" id="vain-nousijat"${pelaajaValinnat.vainNousijat ? " checked" : ""}> Vain nousijat
    </label>
    <p class="selite">Veikkaus tarjoaa vain maali- ja syöttövetoja. Vedot sis. jatkoajan, ei voittolaukauksia.</p>
    <p class="selite">▲ = nousija: mallin pisteodotus on prosentin verran korkeampi kuin pelaajan taso ennen tätä kautta.</p>`;

  document.getElementById("valitse-ottelu").value = pelaajaValinnat.ottelu;

  // Kun valinta muuttuu, piirretään ottelut uudelleen
  suodattimet.addEventListener("change", tapahtuma => {
    const kohde = tapahtuma.target;
    if (kohde.id === "valitse-ottelu") pelaajaValinnat.ottelu = kohde.value;
    else if (kohde.id === "valitse-vetotyyppi") pelaajaValinnat.vetotyyppi = kohde.value;
    else if (kohde.id === "vain-nousijat") pelaajaValinnat.vainNousijat = kohde.checked;
    else return;
    naytaOttelut();
  });
}

// ---------- Näkymä: ottelukortit ja pelaajataulukot ----------

// Onko tälle pelaajalle jo tallennettu veto tästä vetotyypistä tänään?
function onPelattu(pelaajaId, vetotyyppi) {
  const { tyyppi, raja } = puraVetotyyppi(vetotyyppi);
  return pelaajaData.vedot.some(veto => veto.pvm === pelaajaData.ennusteet.pvm &&
    veto.pelaaja_id === pelaajaId && veto.tyyppi === tyyppi && veto.raja === raja);
}

// Pienet "tn + rajakerroin" -solut yleiskatsaukseen
function tnSolu(tn) {
  return `<td class="tn-solu">${tnTekstina(tn)}<small>${rajakerroinTekstina(tn)}</small></td>`;
}

function pelaajaRivi(ottelu, pelaaja) {
  const vetotyyppi = pelaajaValinnat.vetotyyppi;
  const tn = pelaaja.tn[vetotyyppi];
  const kausi = pelaaja.kausi || {};
  const viime = pelaaja.viime || {};

  // Nousija = mallin pisteodotus on selvästi yli pelaajan tason ennen tätä kautta
  let nousija = "";
  if (pelaaja.nousija && typeof pelaaja.nousija.nosto === "number") {
    const nosto = Math.round(pelaaja.nousija.nosto * 100);
    const etumerkki = nosto > 0 ? "+" : "";
    nousija = ` <span class="nousija" title="Mallin pisteodotus on ${nosto} % korkeampi kuin pelaajan taso ennen tätä kautta">▲ ${etumerkki}${nosto} %</span>`;
  }
  const pelattu = onPelattu(pelaaja.id, vetotyyppi)
    ? ` <span class="pelattu" title="Tästä on jo tallennettu veto">pelattu</span>` : "";

  // Oma syötetty kerroin ensin, muuten Kambin (Unibet/Paf/LeoVegas) kerroin
  const omaKerroin = kertoimet[kerroinAvain(pelaaja.id, vetotyyppi)];
  const kambi = pelaajanKertoimet(ottelu, pelaaja)[vetotyyppi];
  const kambista = !omaKerroin && Boolean(kambi);
  const kerroinTeksti = omaKerroin || (kambi ? desimaali(kambi.kerroin, 2) : "");
  // Unibetin kerroin näkyy aina vertailuna, vaikka olisi syöttänyt oman (esim. EpicBet)
  const kambiTieto = kambi
    ? `<div class="kambi-tieto">${KAMBI_YHTIO} ${desimaali(kambi.kerroin, 2)}${kambi.markkina !== null ? " · markkina " + tnTekstina(kambi.markkina) : ""}</div>`
    : "";

  return `
    <tr data-avain="${suojaa(ottelu.avain)}" data-id="${suojaa(pelaaja.id)}"${kambista ? ' data-lahde="kambi"' : ""}>
      <td class="nimi">${suojaa(pelaaja.nimi)}${nousija}${pelattu}</td>
      <td>${suojaa(pelaaja.joukkue)}</td>
      <td>${suojaa(pelaaja.pp)}</td>
      <td>${suojaa(pelaaja.ketju)}</td>
      <td>${suojaa(kausi.ottelut)} / ${suojaa(kausi.maalit)} / ${suojaa(kausi.syotot)} / ${suojaa(kausi.pisteet)}</td>
      <td>${suojaa(viime.maalit)}+${suojaa(viime.syotot)} (${suojaa(viime.ottelut)} o)</td>
      ${tnSolu(pelaaja.tn.maalit_1)}
      ${tnSolu(pelaaja.tn.syotot_1)}
      ${tnSolu(pelaaja.tn.pisteet_1)}
      <td class="valittu">${tnTekstina(tn)}</td>
      <td class="valittu">${rajakerroinTekstina(tn)}</td>
      <td class="valittu"><input class="kerroin-syotto" type="text" inputmode="decimal"
        autocomplete="off" placeholder="kerroin" value="${suojaa(kerroinTeksti)}">${kambiTieto}</td>
      <td class="valittu value-solu"></td>
      <td class="tallenna-solu"></td>
    </tr>`;
}

function naytaOttelut() {
  const e = pelaajaData.ennusteet;
  const vetotyyppi = pelaajaValinnat.vetotyyppi;
  const tyypinNimi = VETOTYYPIT[vetotyyppi];
  const viimePelit = e.viime_pelit || "";

  let html = "";
  for (const ottelu of e.ottelut || []) {
    if (pelaajaValinnat.ottelu !== "kaikki" && pelaajaValinnat.ottelu !== ottelu.avain) continue;

    let sisalto;
    if (!ottelu.kokoonpano) {
      sisalto = `<p class="selite">Kokoonpanoa ei ole vielä julkaistu (julkaistaan pelipäivänä klo 12, ennusteet päivittyvät sen jälkeen useaan kertaan iltapäivällä)</p>`;
    } else {
      // Suodatetaan nousijat ja järjestetään todennäköisin ensin
      let pelaajat = (ottelu.pelaajat || []).filter(p => !pelaajaValinnat.vainNousijat || p.nousija);
      pelaajat = pelaajat.slice().sort((a, b) => (b.tn[vetotyyppi] || 0) - (a.tn[vetotyyppi] || 0));

      if (pelaajat.length === 0) {
        sisalto = pelaajaValinnat.vainNousijat
          ? `<p class="selite">Ei nousijoita tässä ottelussa.</p>`
          : `<p class="selite">Ei pelaajia tässä ottelussa.</p>`;
      } else {
        const rivit = pelaajat.map(p => pelaajaRivi(ottelu, p)).join("");
        sisalto = `
          <div class="taulukko-vieritys">
            <table class="pelaajataulukko">
              <thead>
                <tr>
                  <th class="nimi">Nimi</th><th>Joukkue</th><th>PP</th><th>Ketju</th>
                  <th>Kausi O/M/S/P</th><th>Viime ${suojaa(viimePelit)} M+S</th>
                  <th>Maali 1+</th><th>Syöttö 1+</th><th>Piste 1+</th>
                  <th class="valittu">${tyypinNimi}</th><th class="valittu">Raja</th>
                  <th class="valittu">Kerroin</th><th class="valittu">Value</th><th></th>
                </tr>
              </thead>
              <tbody>${rivit}</tbody>
            </table>
          </div>`;
      }
    }

    // Myöhässä käynnistynyt ajo voi tuoda sivulle jo alkaneen pelin: merkitään se
    const alkanut = ottelu.alkaa && new Date(ottelu.alkaa) <= new Date() ? " (alkanut)" : "";

    const odotetut = Array.isArray(ottelu.odotetut_maalit)
      ? `<p class="selite">Odotetut maalit (60 min) ${desimaali(ottelu.odotetut_maalit[0], 2)} – ${desimaali(ottelu.odotetut_maalit[1], 2)}</p>`
      : "";

    html += `
      <div class="peli-kortti">
        <h2>${suojaa(ottelunNimi(ottelu))}${alkanut}</h2>
        ${odotetut}
        ${sisalto}
      </div>`;
  }

  if (html === "") {
    html = `<div class="viestikortti">Tälle päivälle ei ole otteluita.</div>`;
  }

  const kohde = document.getElementById("pelaaja-ottelut");
  kohde.innerHTML = html;

  // Lasketaan valuet valmiiksi syötetyille kertoimille
  for (const rivi of kohde.querySelectorAll("tr[data-id]")) {
    paivitaValue(rivi);
  }

  naytaVihjeet();
}

function etsiOttelu(avain) {
  return (pelaajaData.ennusteet.ottelut || []).find(o => o.avain === avain);
}

function etsiPelaaja(ottelu, id) {
  return (ottelu.pelaajat || []).find(p => String(p.id) === String(id));
}

// Päivittää rivin value-solun ja Tallenna-napin heti kertoimen syötön jälkeen
function paivitaValue(rivi) {
  const ottelu = etsiOttelu(rivi.dataset.avain);
  const pelaaja = etsiPelaaja(ottelu, rivi.dataset.id);
  const tn = pelaaja.tn[pelaajaValinnat.vetotyyppi];
  const syotto = rivi.querySelector(".kerroin-syotto");
  const valueSolu = rivi.querySelector(".value-solu");
  const tallennaSolu = rivi.querySelector(".tallenna-solu");
  const kerroin = lueKerroin(syotto.value);

  valueSolu.classList.remove("plus", "miinus");
  syotto.classList.remove("hyva");

  if (kerroin === null || typeof tn !== "number") {
    valueSolu.textContent = "";
    tallennaSolu.innerHTML = "";
    return;
  }

  const value = laskeValue(tn, kerroin);
  valueSolu.textContent = prosenttina(value);
  // Kerroin yli rajakertoimen = tn × kerroin > 1 = vihreä
  if (tn * kerroin > 1) {
    valueSolu.classList.add("plus");
    syotto.classList.add("hyva");
  } else {
    valueSolu.classList.add("miinus");
  }
  if (!tallennaSolu.querySelector("button")) {
    tallennaSolu.innerHTML = `<button type="button" class="pieni-nappi tallenna-veto">Tallenna veto</button>`;
  }
}

// Tallennuslomake avautuu pelaajarivin alle omaksi rivikseen
function avaaTallennuslomake(rivi) {
  const seuraava = rivi.nextElementSibling;
  if (seuraava && seuraava.classList.contains("lomakerivi")) {
    seuraava.remove();                  // toinen painallus sulkee lomakkeen
    return;
  }

  // Kambin kerroin -> Unibet oletuksena, muuten viimeksi käytetty yhtiö
  const viimeYhtio = rivi.dataset.lahde === "kambi" ? KAMBI_YHTIO : (lueMuisti(YHTIO_AVAIN) || YHTIOT[0]);
  let vaihtoehdot = "";
  for (const yhtio of YHTIOT) {
    vaihtoehdot += `<option${yhtio === viimeYhtio ? " selected" : ""}>${yhtio}</option>`;
  }

  const lomakerivi = document.createElement("tr");
  lomakerivi.className = "lomakerivi";
  lomakerivi.innerHTML = `
    <td colspan="14">
      <form class="tallennuslomake">
        <label>Yhtiö <select name="yhtio">${vaihtoehdot}</select></label>
        <label>Panos <input name="panos" type="text" inputmode="decimal" value="${OLETUS_PANOS}"></label>
        <button type="submit" class="pieni-nappi">Tallenna</button>
        <button type="button" class="pieni-nappi peruuta">Peruuta</button>
        <div class="lomakeviesti"></div>
      </form>
    </td>`;
  rivi.after(lomakerivi);
  paivitaVeikkausVaroitus(lomakerivi.querySelector("form"));
}

// Veikkaus ei tarjoa pistevetoja: varoitetaan, mutta ei estetä
function paivitaVeikkausVaroitus(lomake) {
  const viesti = lomake.querySelector(".lomakeviesti");
  const pisteet = puraVetotyyppi(pelaajaValinnat.vetotyyppi).tyyppi === "pisteet";
  if (lomake.yhtio.value === "Veikkaus" && pisteet) {
    viesti.className = "lomakeviesti varoitus";
    viesti.textContent = "Huom: Veikkaus ei tarjoa pistevetoja. Tarkista yhtiö.";
  } else if (viesti.classList.contains("varoitus")) {
    viesti.className = "lomakeviesti";
    viesti.textContent = "";
  }
}

async function tallennaLomake(lomake) {
  const lomakerivi = lomake.closest("tr");
  const rivi = lomakerivi.previousElementSibling;
  const viesti = lomake.querySelector(".lomakeviesti");
  const ottelu = etsiOttelu(rivi.dataset.avain);
  const pelaaja = etsiPelaaja(ottelu, rivi.dataset.id);
  const kerroin = lueKerroin(rivi.querySelector(".kerroin-syotto").value);
  const panos = parseFloat(String(lomake.panos.value).replace(",", "."));

  if (kerroin === null) {
    viesti.className = "lomakeviesti miinus";
    viesti.textContent = "Kerroin puuttuu tai on virheellinen.";
    return;
  }
  if (!(panos > 0)) {
    viesti.className = "lomakeviesti miinus";
    viesti.textContent = "Panoksen pitää olla suurempi kuin 0.";
    return;
  }

  const yhtio = lomake.yhtio.value;
  kirjoitaMuisti(YHTIO_AVAIN, yhtio);
  const veto = rakennaVeto(pelaajaData.ennusteet, ottelu, pelaaja,
    pelaajaValinnat.vetotyyppi, kerroin, yhtio, panos);

  // Ilman tokenia näytetään veto kopioitavaksi
  if (!lueToken()) {
    naytaKopioitava(lomakerivi.querySelector("td"), veto);
    return;
  }

  const napit = lomake.querySelectorAll("button");
  napit.forEach(nappi => { nappi.disabled = true; });
  viesti.className = "lomakeviesti";
  viesti.textContent = "Tallennetaan GitHubiin...";

  try {
    const viestiGithubiin = "Pelaajaveto: " + veto.pelaaja + " " + veto.tyyppi + " " +
      veto.raja + "+ @ " + veto.kerroin;
    pelaajaData.vedot = await muokkaaVetoja(lista => lista.concat([veto]), viestiGithubiin);
    pelaajaData.vedotLadattu = true;
    // Piirretään heti uudelleen: raw-osoite voi näyttää vanhaa listaa vielä minuutteja
    naytaOttelut();
    naytaPelaajasaldo(false);
  } catch (virhe) {
    napit.forEach(nappi => { nappi.disabled = false; });
    viesti.className = "lomakeviesti miinus";
    viesti.textContent = "Tallennus epäonnistui: " + virhe.message;
  }
}

// Näyttää vedon JSON-muodossa, jotta sen voi lisätä GitHubissa käsin
function naytaKopioitava(solu, veto) {
  solu.innerHTML = `
    <div class="tallennuslomake">
      <p class="selite">Tokenia ei ole asetettu (Asetukset). Kopioi veto ja lisää se GitHubissa
        tiedoston pelaajavedot.json listaan (hakasulkeiden sisään, pilkku edellisen vedon perään).</p>
      <textarea class="kopioitava" rows="8" readonly></textarea>
      <button type="button" class="pieni-nappi kopioi">Kopioi</button>
      <button type="button" class="pieni-nappi peruuta">Sulje</button>
      <div class="lomakeviesti"></div>
    </div>`;
  // textContent/value ei tulkitse HTML:ää, joten suojausta ei tarvita
  solu.querySelector("textarea").value = JSON.stringify(veto, null, 2);
}

async function kopioi(nappi) {
  const alue = nappi.parentElement.querySelector("textarea");
  const viesti = nappi.parentElement.querySelector(".lomakeviesti");
  try {
    await navigator.clipboard.writeText(alue.value);
  } catch (virhe) {
    // Vanhempi selain tai ei https: valitaan teksti ja kopioidaan vanhalla tavalla
    alue.select();
    document.execCommand("copy");
  }
  viesti.textContent = "Kopioitu ✓";
}

// Kaikki taulukon napit ja syötöt käsitellään yhdessä paikassa (tapahtumien delegointi)
function kytkeOttelutapahtumat() {
  const kohde = document.getElementById("pelaaja-ottelut");

  kohde.addEventListener("input", tapahtuma => {
    const syotto = tapahtuma.target;
    if (!syotto.classList.contains("kerroin-syotto")) return;
    const rivi = syotto.closest("tr");
    // Muistetaan kerroin, ettei se katoa sivun uudelleenlatauksessa
    const avain = kerroinAvain(rivi.dataset.id, pelaajaValinnat.vetotyyppi);
    if (syotto.value.trim() === "") delete kertoimet[avain];
    else kertoimet[avain] = syotto.value.trim();
    kirjoitaMuisti(KERROIN_AVAIN, JSON.stringify(kertoimet));
    // Itse syötetty kerroin ei ole enää Kambin kerroin (Unibetin kerroin jää näkyviin vertailuksi)
    delete rivi.dataset.lahde;
    paivitaValue(rivi);
    naytaVihjeet();                   // oma parempi kerroin voi nostaa pelaajan vihjeeksi
  });

  kohde.addEventListener("change", tapahtuma => {
    if (tapahtuma.target.name === "yhtio") {
      paivitaVeikkausVaroitus(tapahtuma.target.form);
    }
  });

  kohde.addEventListener("click", tapahtuma => {
    const nappi = tapahtuma.target.closest("button");
    if (!nappi) return;
    if (nappi.classList.contains("tallenna-veto")) avaaTallennuslomake(nappi.closest("tr"));
    else if (nappi.classList.contains("peruuta")) nappi.closest("tr").remove();
    else if (nappi.classList.contains("kopioi")) kopioi(nappi);
  });

  kohde.addEventListener("submit", tapahtuma => {
    tapahtuma.preventDefault();          // ei ladata sivua uudelleen
    tallennaLomake(tapahtuma.target);
  });
}

// ---------- Näkymä: saldo ja vetolista ----------

function naytaPelaajasaldo(tuloksetVirhe) {
  const kohde = document.getElementById("pelaaja-saldo");
  if (!pelaajaData.vedotLadattu) {
    kohde.innerHTML = `<div class="viestikortti">Pelaajavetojen lataus epäonnistui. Yritä hetken päästä uudelleen.</div>`;
    return;
  }

  const yhdistetyt = yhdistaTulokset(pelaajaData.vedot, pelaajaData.tulokset);
  const ryhmat = laskePelaajasaldo(yhdistetyt);

  let rivit = "";
  for (const nimi in ryhmat) {
    const r = ryhmat[nimi];
    const roi = r.panokset > 0 ? r.saldo / r.panokset * 100 : 0;
    const luokka = r.saldo >= 0 ? "plus" : "miinus";
    rivit += `
      <tr>
        <td>${nimi}</td>
        <td>${r.osumat}/${r.vedot}</td>
        <td class="${luokka}">${euroina(r.saldo)}</td>
        <td class="${luokka}">${desimaali(roi, 1)} %</td>
        <td>${r.avoimet}</td>
      </tr>`;
  }

  const virheteksti = tuloksetVirhe
    ? `<p class="selite">Tulosten lataus epäonnistui, joten kaikki vedot näkyvät avoimina.</p>` : "";

  // Vetolista: uusin ensin
  const jarjestetyt = yhdistetyt.slice().sort((a, b) =>
    String(b.alkaa || b.pvm).localeCompare(String(a.alkaa || a.pvm)) || String(b.id).localeCompare(String(a.id)));
  const tokenOn = lueToken() !== "";

  let lista = "";
  for (const veto of jarjestetyt) {
    const voitto = typeof veto.voitto === "number" ? euroina(veto.voitto) : "";
    const toteuma = typeof veto.toteuma === "number" ? " · toteuma " + veto.toteuma : "";
    const poista = veto.tila === "avoin" && tokenOn
      ? `<button type="button" class="pieni-nappi poista-veto" data-id="${suojaa(veto.id)}">Poista</button>` : "";
    const paiva = veto.alkaa ? paivaSuomeksi(veto.alkaa) : pvmSuomeksi(veto.pvm);
    const tyyppi = TYYPPIEN_NIMET[veto.tyyppi] || veto.tyyppi;
    const value = typeof veto.value === "number" ? desimaali(veto.value, 1) : "";
    const kerroin = typeof veto.kerroin === "number" ? desimaali(veto.kerroin, 2) : veto.kerroin;

    lista += `
      <li>
        <span class="merkki">${VETOMERKIT[veto.tila] || ""}</span>
        <div>
          <div class="ottelu">${suojaa(veto.pelaaja)} · ${suojaa(tyyppi)} ${suojaa(veto.raja)}+</div>
          <div class="tiedot">@ ${suojaa(kerroin)} (${suojaa(veto.yhtio)}) · value ${suojaa(value)} %${suojaa(toteuma)}</div>
          <div class="tiedot">${suojaa(veto.ottelu)} ${suojaa(paiva)}</div>
          ${poista}
        </div>
        <span class="voitto">${voitto}</span>
      </li>`;
  }
  if (lista === "") {
    lista = `<li><div class="tiedot">Ei vielä pelaajavetoja.</div></li>`;
  }

  kohde.innerHTML = `
    <div class="erittely-kortti">
      <h2>Pelaajavetojen saldo</h2>
      ${virheteksti}
      <table>
        <thead>
          <tr><th></th><th>Osumat</th><th>Saldo</th><th>ROI</th><th>Avoimet</th></tr>
        </thead>
        <tbody>${rivit}</tbody>
      </table>
    </div>
    <div class="pelaajavetolista">
      <ul>${lista}</ul>
    </div>`;
}

async function poistaVeto(nappi) {
  const id = nappi.dataset.id;
  const veto = pelaajaData.vedot.find(v => v.id === id);
  if (!veto) return;
  const kuvaus = veto.pelaaja + " " + (TYYPPIEN_NIMET[veto.tyyppi] || veto.tyyppi) + " " + veto.raja + "+ @ " + veto.kerroin;
  if (!confirm("Poistetaanko veto " + kuvaus + "?")) return;

  nappi.disabled = true;
  nappi.textContent = "Poistetaan...";
  try {
    pelaajaData.vedot = await muokkaaVetoja(lista => lista.filter(v => v.id !== id),
      "Poista pelaajaveto: " + veto.pelaaja + " " + veto.tyyppi + " " + veto.raja + "+ @ " + veto.kerroin);
    naytaPelaajasaldo(false);
    if (pelaajaData.ennusteet) naytaOttelut();
  } catch (virhe) {
    nappi.disabled = false;
    nappi.textContent = "Poista";
    alert("Poisto epäonnistui: " + virhe.message);
  }
}

// ---------- Näkymä: kalibraatio ----------

// Vihjeiden seuranta: mitä vihjelista olisi tuottanut Unibetin kertoimilla, jos
// jokaiseen vihjeeseen olisi laitettu sama panos. Ennusteet ja kertoimet tallentaa
// pelaajamalli.py ennen peliä, tulokset tarkista_tulokset.py pelin jälkeen.
function laskeSeuranta(varjo) {
  const sarakkeet = { "maalit_1": 1, "syotot_1": 2, "pisteet_1": 3, "pisteet_2": 4 };  // paikka ennusteissa
  const ryhmat = {};
  const lisaa = (nimi, osui, kerroin) => {
    const r = ryhmat[nimi] || (ryhmat[nimi] = { n: 0, osui: 0, voitto: 0 });
    r.n += 1;
    if (osui) r.osui += 1;
    r.voitto += osui ? kerroin - 1 : -1;
  };

  for (const peli of Object.values(varjo || {})) {
    if (!peli || !Array.isArray(peli.tulokset) || !peli.kertoimet) continue;
    const tulokset = {};
    for (const [id, maalit, syotot] of peli.tulokset) tulokset[id] = [maalit, syotot];

    for (const rivi of peli.ennusteet || []) {
      const id = rivi[0];
      const kertoimetPelaaja = peli.kertoimet[String(id)];
      if (!kertoimetPelaaja || !(id in tulokset)) continue;     // ei kokoonpanossa = mitätöity
      const [maalit, syotot] = tulokset[id];
      const toteuma = { maalit_1: maalit >= 1, syotot_1: syotot >= 1,
                        pisteet_1: maalit + syotot >= 1, pisteet_2: maalit + syotot >= 2 };
      for (const avain in sarakkeet) {
        const tn = rivi[sarakkeet[avain]];
        const kerroinTieto = kertoimetPelaaja[avain];
        if (typeof tn !== "number" || !kerroinTieto) continue;
        const [kerroin, markkina] = kerroinTieto;
        if (tn * kerroin < 1 + VIHJE_MARGINAALI) continue;      // ei vihje
        lisaa(VETOTYYPIT[avain], toteuma[avain], kerroin);
        lisaa("Kaikki vihjeet", toteuma[avain], kerroin);
        const ristiriita = markkina !== null && tn - markkina > VIHJE_RISTIRIITA;
        lisaa(ristiriita ? "Vain ⚠-vihjeet" : "Ilman ⚠-vihjeitä", toteuma[avain], kerroin);
      }
    }
  }
  return ryhmat;
}

function seurantaKortti(varjo) {
  const ryhmat = laskeSeuranta(varjo);
  const jarjestys = ["Kaikki vihjeet", "Ilman ⚠-vihjeitä", "Vain ⚠-vihjeet",
                     "Maali 1+", "Syöttö 1+", "Piste 1+", "Piste 2+"];
  let rivit = "";
  for (const nimi of jarjestys) {
    const r = ryhmat[nimi];
    if (!r) continue;
    const roi = r.voitto / r.n * 100;
    const luokka = roi >= 0 ? "plus" : "miinus";
    rivit += `
      <tr>
        <td>${nimi}</td>
        <td>${r.osui}/${r.n}</td>
        <td class="${luokka}">${prosenttina(roi)}</td>
      </tr>`;
  }
  if (rivit === "") {
    rivit = `<tr><td colspan="3">Ei vielä ratkaistuja vihjeitä</td></tr>`;
  }
  return `
    <div class="erittely-kortti">
      <h2>Vihjeiden seuranta (${KAMBI_YHTIOT})</h2>
      <p class="selite">Mitä vihjelista olisi tuottanut, jos jokaiseen vihjeeseen olisi laittanut saman panoksen.
        Luotettava arvio vaatii satoja vihjeitä.</p>
      <table>
        <thead><tr><th></th><th>Osumat</th><th>ROI</th></tr></thead>
        <tbody>${rivit}</tbody>
      </table>
    </div>`;
}

function naytaKalibraatio(varjoTulos) {
  const kohde = document.getElementById("pelaaja-kalibraatio");
  if (varjoTulos.tila !== "ok") {
    kohde.innerHTML = `<div class="viestikortti">Kalibraatio: ${suojaa(
      latausviesti(varjoTulos, "ei vielä ratkaistuja pelejä."))}</div>`;
    return;
  }

  const { valit, pelit } = laskeKalibraatio(varjoTulos.data);
  if (pelit === 0) {
    kohde.innerHTML = `<div class="viestikortti">Kalibraatio: ei vielä ratkaistuja pelejä.</div>`;
    return;
  }

  const nimet = { "maalit_1": "Maali 1+", "syotot_1": "Syöttö 1+", "pisteet_1": "Piste 1+", "pisteet_2": "Piste 2+" };
  let kortit = "";
  for (const avain in nimet) {
    let rivit = "";
    valit[avain].forEach((v, i) => {
      if (v.n === 0) return;                      // tyhjiä välejä ei näytetä
      rivit += `
        <tr>
          <td>${i * 10}–${i * 10 + 10} %</td>
          <td>${v.n}</td>
          <td>${desimaali(v.malli / v.n * 100, 1)} %</td>
          <td>${desimaali(v.osui / v.n * 100, 1)} %</td>
        </tr>`;
    });
    kortit += `
      <div class="erittely-kortti">
        <h2>${nimet[avain]}</h2>
        <table>
          <thead><tr><th></th><th>n</th><th>Malli</th><th>Toteutui</th></tr></thead>
          <tbody>${rivit}</tbody>
        </table>
      </div>`;
  }

  kohde.innerHTML = `
    ${seurantaKortti(varjoTulos.data)}
    <h2 class="osio-otsikko">Mallin kalibraatio</h2>
    <p class="selite valkoinen">Kun malli sanoo 40 %, pitäisi toteutua noin 40 %. Ratkaistuja pelejä ${pelit}.</p>
    <div class="kalibraatio-ruudukko">${kortit}</div>`;
}

// ---------- Asetukset (token) ----------

function naytaAsetukset() {
  const kohde = document.getElementById("pelaaja-asetukset");
  const ohje = `<p class="selite">Luo fine-grained token osoitteessa github.com/settings/personal-access-tokens:
    pääsy vain repoon Jermosva/vetovihje ja oikeus Contents: Read and write.
    Token tallentuu vain tähän selaimeen.</p>`;

  // Tokenia ei koskaan kirjoiteta sivulle, vain tieto onko se asetettu
  if (lueToken()) {
    kohde.innerHTML = `
      <h2>Asetukset</h2>
      <p>GitHub-token on asetettu. Vedot tallentuvat suoraan GitHubiin.</p>
      <button type="button" class="pieni-nappi" id="poista-token">Poista token</button>
      ${ohje}`;
  } else {
    kohde.innerHTML = `
      <h2>Asetukset</h2>
      <form id="token-lomake">
        <input type="password" name="token" autocomplete="off" placeholder="Liitä token tähän">
        <button type="submit" class="pieni-nappi">Tallenna token</button>
      </form>
      ${ohje}`;
  }
}

function kytkeAsetukset() {
  const nappi = document.getElementById("asetukset-nappi");
  const kohde = document.getElementById("pelaaja-asetukset");

  nappi.addEventListener("click", () => {
    kohde.hidden = !kohde.hidden;
    if (!kohde.hidden) naytaAsetukset();
  });

  kohde.addEventListener("submit", tapahtuma => {
    tapahtuma.preventDefault();
    const kentta = tapahtuma.target.token;
    const token = kentta.value.trim();
    kentta.value = "";                     // ei jätetä tokenia sivulle
    if (token === "") return;
    kirjoitaMuisti(TOKEN_AVAIN, token);
    naytaAsetukset();
    if (pelaajadataLadattu) naytaPelaajasaldo(false);   // Poista-napit näkyviin
  });

  kohde.addEventListener("click", tapahtuma => {
    if (tapahtuma.target.id !== "poista-token") return;
    kirjoitaMuisti(TOKEN_AVAIN, null);
    naytaAsetukset();
    if (pelaajadataLadattu) naytaPelaajasaldo(false);
  });

  document.getElementById("pelaaja-saldo").addEventListener("click", tapahtuma => {
    if (tapahtuma.target.classList.contains("poista-veto")) poistaVeto(tapahtuma.target);
  });
}

// ---------- Välilehdet ----------

// #pelaajat osoitteen lopussa = Pelaajavedot auki (toimii myös kirjanmerkkinä)
function naytaValilehti() {
  const pelaajat = location.hash === "#pelaajat";
  document.getElementById("nakyma-vedot").hidden = pelaajat;
  document.getElementById("nakyma-pelaajat").hidden = !pelaajat;
  document.getElementById("valilehti-vedot").classList.toggle("aktiivinen", !pelaajat);
  document.getElementById("valilehti-pelaajat").classList.toggle("aktiivinen", pelaajat);

  // Pelaajadata ladataan vasta, kun välilehti avataan ensimmäisen kerran
  if (pelaajat && !pelaajadataLadattu) {
    lataaPelaajadata();
  }
}

// Node-testeissä document puuttuu: silloin vain apufunktiot ladataan
if (typeof document !== "undefined") {
  kytkeOttelutapahtumat();
  kytkeVihjeet();
  kytkeAsetukset();
  window.addEventListener("hashchange", naytaValilehti);
  naytaValilehti();
}
