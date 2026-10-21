// Kirjanpito haetaan suoraan GitHubista: sivu näyttää aina uusimman version
const OSOITE = "https://raw.githubusercontent.com/Jermosva/vetovihje/main/kirjanpito.json";
const VARJO_OSOITE = "https://raw.githubusercontent.com/Jermosva/vetovihje/main/varjo.json";

// Vedon tila -> merkki
const MERKIT = {
  "osui": "✅",
  "ei osunut": "❌",
  "mitätöity": "↩️",
  "avoin": "⏳",
  "tarkista": "❓",
};

// Päivän tila -> merkki
const PAIVAN_MERKIT = {
  "plussa": "✅",
  "miinus": "❌",
  "tasan": "➖",
  "kesken": "⏳",
};

// Muuttaa luvun euroiksi: 11.6 -> "+11,60 €"
function euro(luku) {
  const etumerkki = luku > 0 ? "+" : "";
  // toFixed(2) = kaksi desimaalia, replace vaihtaa pisteen pilkuksi
  return etumerkki + luku.toFixed(2).replace(".", ",") + " €";
}

// Muuttaa luvun prosenteiksi: 3.14 -> "+3,1 %"
function prosentti(luku) {
  const etumerkki = luku > 0 ? "+" : "";
  return etumerkki + luku.toFixed(1).replace(".", ",") + " %";
}

function naytaYhteenveto(vedot) {
  let saldo = 0;
  let ratkaistut = 0;
  let osuneet = 0;
  let odottaa = 0;

  for (const veto of vedot) {
    if ("voitto" in veto) {
      saldo += veto.voitto;
      ratkaistut += 1;
      if (veto.tila === "osui") {
        osuneet += 1;
      }
    } else {
      odottaa += 1;
    }
  }

  // Math.round pyöristää kokonaisluvuksi. Nollalla ei voi jakaa, joten tarkistetaan ensin.
  const osumaprosentti = ratkaistut > 0 ? Math.round(osuneet / ratkaistut * 100) : 0;
  const saldonLuokka = saldo >= 0 ? "plus" : "miinus";

  // innerHTML = korvataan elementin sisältö tällä HTML:llä
  document.getElementById("yhteenveto").innerHTML = `
    <div class="laatikko">
      <span>Saldo</span>
      <strong class="${saldonLuokka}">${euro(saldo)}</strong>
    </div>
    <div class="laatikko">
      <span>Osumat</span>
      <strong>${osuneet}/${ratkaistut} (${osumaprosentti} %)</strong>
    </div>
    <div class="laatikko">
      <span>Odottaa</span>
      <strong>${odottaa}</strong>
    </div>
  `;
}

function naytaPaivat(vedot) {
  // 1. Ryhmitellään vedot pelipäivän mukaan
  const paivat = {};
  for (const veto of vedot) {
    // Pelipäivä Suomen aikaa. "sv-SE" antaa päivämäärän muodossa 2026-10-07,
    // joka järjestyy oikein. Jos alkamisaika puuttuu, käytetään kirjauspäivää.
    const paiva = veto.alkaa
      ? new Date(veto.alkaa).toLocaleDateString("sv-SE")
      : veto.pvm;

    if (!(paiva in paivat)) {
      paivat[paiva] = [];
    }
    paivat[paiva].push(veto);
  }

  // 2. Uusin päivä ensin
  const jarjestys = Object.keys(paivat).sort().reverse();

  let html = "";
  for (const pvm of jarjestys) {
    let saldo = 0;
    let kesken = false;
    let rivit = "";

    // 3. Jokainen päivän veto omaksi rivikseen
    for (const veto of paivat[pvm]) {
      if ("voitto" in veto) {
        saldo += veto.voitto;
      } else {
        kesken = true;
      }

      const sarja = veto.sarja ? "[" + veto.sarja + "] " : "";
      const voitto = "voitto" in veto ? euro(veto.voitto) : "";
      const clv = "clv" in veto ? " · CLV " + prosentti(veto.clv) : "";

      rivit += `
        <li>
          <span class="merkki">${MERKIT[veto.tila] || ""}</span>
          <div>
            <div class="ottelu">${sarja}${veto.ottelu}</div>
            <div class="tiedot">${veto.tyyppi} ${veto.valinta} @ ${veto.kerroin} (${veto.yhtio}) · value ${veto.value} %${clv}</div>
          </div>
          <span class="voitto">${voitto}</span>
        </li>`;
    }

    // 4. Päivän tila
    let luokka = "kesken";
    if (!kesken) {
      if (saldo > 0) luokka = "plussa";
      else if (saldo < 0) luokka = "miinus";
      else luokka = "tasan";
    }

    // 5. "2026-10-04" -> "4.10.2026"
    const [vuosi, kk, pv] = pvm.split("-");
    const suomeksi = Number(pv) + "." + Number(kk) + "." + vuosi;

    html += `
      <details class="paiva ${luokka}">
        <summary>
          <span class="paivan-merkki">${PAIVAN_MERKIT[luokka]}</span>
          <span class="pvm">${suomeksi}</span>
          <span class="paivan-saldo">${kesken ? "kesken" : euro(saldo)}</span>
        </summary>
        <ul>${rivit}</ul>
      </details>`;
  }

  document.getElementById("paivat").innerHTML = html;
}

// Laskee ratkaistuista vedoista luvut ryhmittäin.
// ryhmanNimi on funktio, joka kertoo, mihin ryhmään veto kuuluu.
function laskeRyhmat(vedot, ryhmanNimi) {
  const ryhmat = {};

  for (const veto of vedot) {
    if (!("voitto" in veto)) {
      continue;                       // vain ratkaistut vedot
    }

    const nimi = ryhmanNimi(veto);
    if (!(nimi in ryhmat)) {
      ryhmat[nimi] = { vedot: 0, osumat: 0, saldo: 0, panokset: 0 };
    }

    const r = ryhmat[nimi];
    r.vedot += 1;
    if (veto.tila === "osui") {
      r.osumat += 1;
    }
    r.saldo += veto.voitto;
    r.panokset += veto.panos;
  }

  return ryhmat;
}

// Rakentaa yhden taulukon HTML:n
function erittelyTaulukko(otsikko, ryhmat) {
  let rivit = "";

  for (const nimi in ryhmat) {
    const r = ryhmat[nimi];
    const roi = r.panokset > 0 ? r.saldo / r.panokset * 100 : 0;
    const luokka = r.saldo >= 0 ? "plus" : "miinus";

    rivit += `
      <tr>
        <td>${nimi}</td>
        <td>${r.osumat}/${r.vedot}</td>
        <td class="${luokka}">${euro(r.saldo)}</td>
        <td class="${luokka}">${roi.toFixed(1).replace(".", ",")} %</td>
      </tr>`;
  }

  return `
    <div class="erittely-kortti">
      <h2>${otsikko}</h2>
      <table>
        <thead>
          <tr><th></th><th>Osumat</th><th>Saldo</th><th>ROI</th></tr>
        </thead>
        <tbody>${rivit}</tbody>
      </table>
    </div>`;
}

function naytaErittely(vedot) {
  // Elo-mallin vedoilla on lähteenä "Elo-malli", kaikki muut ovat kerroinvertailua
  const menetelmat = laskeRyhmat(vedot,
    veto => (veto.lahde === "Elo-malli" || veto.lahde === "Poisson-malli")
      ? veto.lahde
      : "Kerroinvertailu");

  // Vanhoilta vedoilta voi puuttua sarja
  const sarjat = laskeRyhmat(vedot, veto => veto.sarja || "Muu");

  // Vanhoilla vedoilla ei ole versiota, joten ne merkitään versioksi 1
  const versiot = laskeRyhmat(vedot, veto => "Versio " + (veto.versio || 1));

  document.getElementById("erittely").innerHTML =
    erittelyTaulukko("Menetelmittäin", menetelmat) +
    erittelyTaulukko("Sarjoittain", sarjat) +
    erittelyTaulukko("Versioittain", versiot);
}

function naytaClv(vedot) {
  // Ryhmitellään mitatut vedot menetelmän ja sarjan mukaan
  const ryhmat = {};
  for (const veto of vedot) {
    if (!("clv" in veto)) {
      continue;                      // tälle vedolle ei ole vielä mittausta
    }
    const menetelma = veto.lahde === "Poisson-malli" ? "Poisson-malli" : "Kerroinvertailu";
    const nimi = menetelma + " · " + (veto.sarja || "Muu");

    if (!(nimi in ryhmat)) {
      ryhmat[nimi] = { maara: 0, value: 0, clv: 0, positiivisia: 0 };
    }
    const r = ryhmat[nimi];
    r.maara += 1;
    r.value += veto.value;
    r.clv += veto.clv;
    if (veto.clv > 0) {
      r.positiivisia += 1;
    }
  }

  let rivit = "";
  for (const nimi of Object.keys(ryhmat).sort()) {
    const r = ryhmat[nimi];
    const keskiarvo = r.clv / r.maara;
    const luokka = keskiarvo >= 0 ? "plus" : "miinus";
    rivit += `
      <tr>
        <td>${nimi}</td>
        <td>${r.maara}</td>
        <td>${prosentti(r.value / r.maara)}</td>
        <td class="${luokka}">${prosentti(keskiarvo)}</td>
        <td>${Math.round(r.positiivisia / r.maara * 100)} %</td>
      </tr>`;
  }

  if (rivit === "") {
    rivit = `<tr><td colspan="5">Ei vielä mittauksia</td></tr>`;
  }

  document.getElementById("clv").innerHTML = `
    <div class="erittely-kortti">
      <h2>Kertoimen liike (CLV)</h2>
      <p class="selite">Kaikki ehdokkaat. Plus = saimme paremman kertoimen kuin markkinan viimeisin arvio ennen peliä.</p>
      <table>
        <thead>
          <tr><th></th><th>Mitattu</th><th>Value</th><th>CLV</th><th>CLV&nbsp;&gt;&nbsp;0</th></tr>
        </thead>
        <tbody>${rivit}</tbody>
      </table>
    </div>`;
}

// async = funktio, joka voi odottaa (await) esim. verkkohakua
async function lataa() {
  try {
    // ?t=... estää selainta näyttämästä vanhaa välimuistiin tallennettua versiota
    const vastaus = await fetch(OSOITE + "?t=" + Date.now());
    const vedot = await vastaus.json();
    naytaYhteenveto(vedot);
    naytaErittely(vedot);
    naytaPaivat(vedot);

    const varjoVastaus = await fetch(VARJO_OSOITE + "?t=" + Date.now());
    const varjo = await varjoVastaus.json();
    naytaClv(varjo);
  } catch (virhe) {
    // try/catch = jos jokin epäonnistuu, näytetään virhe sivun kaatumisen sijaan
    document.getElementById("paivat").textContent = "Kirjanpidon lataus epäonnistui: " + virhe;
  }
}

lataa();