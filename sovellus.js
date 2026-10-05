// Kirjanpito haetaan suoraan GitHubista: sivu näyttää aina uusimman version
const OSOITE = "https://raw.githubusercontent.com/Jermosva/vetovihje/main/kirjanpito.json";

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
  // 1. Ryhmitellään vedot päivittäin: "2026-10-04" -> [veto, veto, ...]
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

      rivit += `
        <li>
          <span class="merkki">${MERKIT[veto.tila] || ""}</span>
          <div>
            <div class="ottelu">${sarja}${veto.ottelu}</div>
            <div class="tiedot">${veto.tyyppi} ${veto.valinta} @ ${veto.kerroin} (${veto.yhtio}) · value ${veto.value} %</div>
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
// async = funktio, joka voi odottaa (await) esim. verkkohakua
async function lataa() {
  try {
    // ?t=... estää selainta näyttämästä vanhaa välimuistiin tallennettua versiota
    const vastaus = await fetch(OSOITE + "?t=" + Date.now());
    const vedot = await vastaus.json();
    naytaYhteenveto(vedot);
    naytaPaivat(vedot);
  } catch (virhe) {
    // try/catch = jos jokin epäonnistuu, näytetään virhe sivun kaatumisen sijaan
    document.getElementById("paivat").textContent = "Kirjanpidon lataus epäonnistui: " + virhe;
  }
}

lataa();