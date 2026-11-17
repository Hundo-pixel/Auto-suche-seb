# Autosuche – Gebrauchtwagen aus mehreren Portalen, bewertet nach Preis-Leistung

Kostenlose iPhone-App (PWA), die Gebrauchtwagen-Inserate aus mehreren Portalen sammelt, Duplikate
zusammenführt und jedes Fahrzeug mit einem regelbasierten **Preis-Leistungs-Score (0–100)** bewertet.
Keine Anmeldung, kein Konto, keine bezahlten Dienste, keine KI-API, keine API-Keys.

<p align="center">
  <img src="docs/screenshots/liste.png" width="230" alt="Liste">
  <img src="docs/screenshots/detail.png" width="230" alt="Detail mit Score">
  <img src="docs/screenshots/karte.png" width="230" alt="Karte mit Umkreis">
</p>

---

## Inhalt

1. [Architektur & Entscheidungen](#1-architektur--entscheidungen)
2. [Schnellstart lokal](#2-schnellstart-lokal)
3. [Deployment (kostenlos)](#3-deployment-kostenlos)
4. [Auf dem iPhone installieren](#4-auf-dem-iphone-installieren)
5. [Konfiguration & Score](#5-konfiguration--score)
6. [Neues Portal ergänzen](#6-neues-portal-ergänzen)
7. [Tests](#7-tests)
8. [Bekannte Grenzen](#8-bekannte-grenzen)
9. [Rechtliches & Fairness](#9-rechtliches--fairness)

---

## 1. Architektur & Entscheidungen

```
┌──────────────── Scraper (Python) ────────────────┐        ┌──── App (PWA, statisch) ────┐
│ Adapter je Portal ─► PoliteClient (robots.txt,   │        │ index.html + ES-Module       │
│   AutoScout24        Rate-Limit, Retries,        │        │ liest NUR JSON-Dateien:      │
│   Kleinanzeigen      Block-Erkennung)            │  JSON  │  data/listings.json          │
│   mobile.de (Status) │                           │ ─────► │  data/meta.json              │
│        ▼             ▼                           │        │  data/d/<id>.json            │
│ SQLite (Inserate, Preisverlauf, Taxonomie)       │        │  data/thumbs/*.webp          │
│        ▼                                         │        │ Leaflet + OpenStreetMap      │
│ Bildanalyse (pHash, Qualität, CLIP lokal)        │        │ Favoriten/Standort lokal     │
│ Score + Duplikaterkennung ─► Export JSON         │        └──────────────────────────────┘
└──────────────────────────────────────────────────┘          gehostet auf GitHub Pages
         läuft per GitHub-Actions-Cron (oder Docker/Raspberry Pi)
```

| Entscheidung | Gewählt | Warum |
|---|---|---|
| App-Technik | **PWA** (Vanilla JS, kein Build-Schritt) | Läuft ohne Apple-Developer-Account (99 €/Jahr) und ohne 7-Tage-Signatur-Ablauf beim kostenlosen Sideloading. Installierbar über „Zum Home-Bildschirm", Updates sofort, ein Code für iPhone/iPad/Desktop. SwiftUI brächte hier keinen Mehrwert, weil die App ohnehin nur statische JSON-Dateien liest. |
| Scraping | **httpx + BeautifulSoup**, kein Playwright | Beide Portale liefern die Daten serverseitig im HTML (AutoScout24: Next.js-JSON `__NEXT_DATA__`). Ein Headless-Browser wäre langsamer, schwerer (Raspberry Pi!) und rückt in die Nähe von Bot-Schutz-Umgehung – das ist ausdrücklich nicht gewollt. |
| Zeitplan | **GitHub Actions Cron** als Standard, **Docker/Raspberry Pi** als Ausweichlösung | Actions ist kostenlos (öffentliches Repo), braucht keine Hardware und speichert den Zustand im Branch `data`. **Falls Portale GitHub-/Azure-IPs blocken** (bei Kleinanzeigen und mobile.de bekannt), ist der Pi mit privater IP robuster: dann `SCRAPE_IN_ACTIONS=false` setzen und lokal laufen lassen – der Pi pusht die Daten, GitHub Pages deployt automatisch. Der Scraper meldet Sperren in jedem Fall klar im Log und im Reiter „Mehr" der App. |
| Speicher | **SQLite → kompakte JSON-Dateien** | SQLite hält Historie (Preisverlauf, zuerst/zuletzt gesehen). Die App bekommt nur, was sie braucht: Liste (~1 KB/Inserat) und Details on demand. |
| Hosting | **GitHub Pages** | Kostenlos, HTTPS (nötig für PWA + Geolocation). Cloudflare Pages funktioniert identisch mit dem Ordner `_site`. |
| Bildanalyse | **CLIP ViT-B/32 (ONNX, quantisiert) lokal** + Heuristiken | Kostenlos, ~150 MB, CPU-tauglich (~0,3 s/Bild). Fällt automatisch auf Heuristiken zurück, wenn das Modell fehlt. |
| Karte | **Leaflet + OpenStreetMap** | Kostenlos, kein API-Key. |
| Entfernung | **Offline-PLZ-Tabelle (GeoNames, CC BY 4.0) + Haversine** | Kein Geocoding-Dienst nötig; 10.815 deutsche PLZ. |

### Verzeichnisstruktur

```
scraper/
  autosuche/
    adapters/        base.py (Schnittstelle), autoscout24.py, kleinanzeigen.py, mobile_de.py
    http.py          PoliteClient: robots.txt, Rate-Limit, Retries, Block-Erkennung
    textparse.py     Normalisierung, Reifen, Kennzeichen, Warn-Schlagworte, Unfall aus Text
    scoring.py       Preis-Leistungs-Score
    dedupe.py        Duplikate (Fahrzeugdaten + pHash)
    images.py/clip.py Thumbnails, pHash, Bildqualität, Innenraum (CLIP)
    db.py export.py run.py
  config.toml        alle Gewichte, Limits, Schwellen
  tests/             Parser-, Text-, Score-, Duplikat-Tests (Fixtures = echte, anonymisierte Seiten)
  tools/             build_plz.py, fetch_clip.py, local_publish.sh
web/                 die PWA (index.html, css/, js/, sw.js, manifest, vendor/leaflet)
.github/workflows/   scrape.yml (Cron), deploy-pages.yml, tests.yml
Dockerfile, docker-compose.yml   lokaler Betrieb (Raspberry Pi)
```

---

## 2. Schnellstart lokal

Voraussetzung: Python ≥ 3.11.

```bash
cd scraper
pip install -r requirements.txt
python tools/fetch_clip.py          # optional: lokales CLIP-Modell (~150 MB) für die Innenraum-Erkennung
python -m autosuche.run             # scrapen + Bildanalyse + JSON nach ../web/data
python -m pytest -q                 # Tests

cd ../web && python -m http.server 8000
# -> http://localhost:8000 im Browser öffnen
```

Nützliche Optionen:

```bash
python -m autosuche.run --sources kleinanzeigen   # nur ein Portal
python -m autosuche.run --export-only             # nur JSON neu erzeugen (z. B. nach Score-Änderung in config.toml)
python -m autosuche.run -v                        # ausführliches Log
```

---

## 3. Deployment (kostenlos)

### Variante A: GitHub Actions + GitHub Pages (Standard)

1. Repository auf GitHub (öffentlich → unbegrenzte Actions-Minuten).
2. **Settings → Pages → Build and deployment → Source: „GitHub Actions"**.
3. **Actions → „scrape" → „Run workflow"** für den ersten Lauf. Danach läuft er automatisch alle 6 Stunden.
4. Die Seite liegt unter `https://<benutzer>.github.io/<repo>/`.

Der Workflow holt Datenbank + Thumbnails aus dem Branch `data`, scrapt (max. 45 Minuten, davon ~60 % Scraping
und ~40 % Bildanalyse), schreibt den Zustand zurück (der Branch `data` wird jedes Mal ohne Historie neu
geschrieben, damit das Repo klein bleibt) und deployt die Seite. Änderungen an `web/` lösen `deploy-pages.yml` aus.

### Variante B: Raspberry Pi / eigener Rechner per Docker (wenn Portale GitHub-IPs blocken)

```bash
git clone https://github.com/<benutzer>/<repo>.git /opt/autosuche && cd /opt/autosuche
# Deploy-Key mit Schreibrecht anlegen (GitHub → Settings → Deploy keys) und in ~/.ssh hinterlegen
export REPO_URL=git@github.com:<benutzer>/<repo>.git
docker compose run --rm scraper            # ein Lauf: scrapen + Branch "data" pushen
# Zeitplan (crontab -e):
# 17 */6 * * * cd /opt/autosuche && REPO_URL=git@github.com:<benutzer>/<repo>.git docker compose run --rm scraper
```

In GitHub dann unter **Settings → Secrets and variables → Actions → Variables** `SCRAPE_IN_ACTIONS=false`
setzen. Der Push in `data` löst `deploy-pages.yml` aus, die Seite wird ohne weitere Kosten aktualisiert.
Ohne Docker geht es genauso: `pip install -r scraper/requirements.txt && ./scraper/tools/local_publish.sh`.

**Was ist besser?** Mit GitHub Actions starten. Meldet das Log `QUELLE BLOCKIERT` (HTTP 403/429/Captcha) dauerhaft
für ein Portal, auf den Pi wechseln. Beides lässt sich auch kombinieren (Pi für das blockierte Portal per
`--sources`, Actions für den Rest) – dann aber nur einer von beiden pushen lassen.

---

## 4. Auf dem iPhone installieren

1. Seite in **Safari** öffnen.
2. **Teilen** (Quadrat mit Pfeil) → **„Zum Home-Bildschirm"**.
3. Die App startet danach im Vollbild wie eine native App, funktioniert offline mit dem letzten Datenstand und
   speichert Favoriten/Standort nur auf dem Gerät.

Bedienung: **Suche** (Liste, Freitext, Filter-Sheet, Sortierung), **Karte** (Pins mit Preis in Score-Farbe,
Gruppen beim Herauszoomen, Umkreis-Kreis), **Favoriten**, **Mehr** (Hell/Dunkel/Automatisch, Quellenstatus,
Erklärung des Scores). Detailansicht: Galerie mit Swipe, Tippen öffnet Vollbild mit Pinch-/Doppeltipp-Zoom,
Score-Aufschlüsselung, Preisverlauf, „Zur Originalanzeige".

---

## 5. Konfiguration & Score

Alles in [`scraper/config.toml`](scraper/config.toml) – nach Änderungen genügt `python -m autosuche.run --export-only`.

### Score (0–100)

| Teilwert | Gewicht (Standard) | Berechnung |
|---|---|---|
| Preis vs. Markt | 45 % | Vergleichsgruppe: gleiche Marke + Modell(-reihe) + Baujahr ±1 + Kraftstoff. Erwarteter Preis per linearer Regression `Preis ~ km + Alter` (5 %-/95 %-Ausreißer entfernt, das bewertete Inserat selbst ausgeschlossen). −30 % ⇒ 100 Punkte, +30 % ⇒ 0 Punkte. **Zu kleine Gruppe (< 6)** ⇒ Rückfall auf Modell+Kraftstoff (alle Baujahre) ⇒ Modell ⇒ Marke+Kraftstoff ⇒ neutral (50). Die App zeigt dann „Breitere Vergleichsgruppe" bzw. „neutral bewertet". |
| Kilometer | 20 % | km pro Jahr: ≤ 5.000 ⇒ 100, ≥ 35.000 ⇒ 0. Unplausible Angaben (z. B. „280 km" bei EZ 2006) werden markiert und neutral gewertet. |
| Unfallstatus | 20 % | unfallfrei 100, unbekannt 40, Unfallwagen 0. |
| Fotos & Innenraum | 15 % | 50 % Anzahl (≥ 8 = voll), 25 % technische Bildqualität, 25 % Innenraumfoto vorhanden/gepflegt. |
| Warnungen | Abzug | Kennzeichen-Auffälligkeit −10, Preis > 35 % unter Markt −15, Schlagwort (Export, defekt, Motorschaden, Bastler …) −12, < 3 Fotos −8 (max. 3 Abzüge). |

Marktpreise werden aus den **gesammelten Inseraten** geschätzt – je mehr Inserate einer Modellreihe vorliegen,
desto belastbarer. Modellnamen werden portalübergreifend vereinheitlicht (z. B. Kleinanzeigen „330" →
Baureihe „3er" über die Taxonomie von AutoScout24).

### Wie belastbar ist die Bildanalyse? (ehrlich)

* **Innenraum vorhanden ja/nein** (CLIP-Zero-Shot gegen Texte wie „Innenraum mit Sitzen und Armaturenbrett"):
  in Stichproben zuverlässig, Fehler v. a. bei Detailfotos (Schaltknauf, Tacho) oder Fotos durch die offene Tür.
  Analysiert werden pro Inserat 6 über die Galerie verteilte Bilder; wird keins erkannt, obwohl die Galerie viel
  größer ist, gilt der Status als „unbekannt" statt „nein".
* **„Wirkt gepflegt"**: nur ein grober Hinweis (CLIP vergleicht mit „sauber/gepflegt" vs. „schmutzig/abgenutzt").
  Licht, Winkel und Bildbearbeitung beeinflussen das stark – deshalb fließt es nur mit wenigen Prozent ein.
* **Bildqualität** (Schärfe, Belichtung, Kontrast auf kleinen Bildvarianten): robust gegen extreme Ausreißer
  (dunkel, unscharf), sagt aber nichts über das Fahrzeug selbst.
* **Kennzeichen auf Fotos** werden **nicht** per Bilderkennung geprüft (dafür bräuchte es OCR mit eigenem Modell);
  Kennzeichen-Warnungen stammen aus Titel/Beschreibung.

### Weitere Auswertungen

* **Reifen**: erkennt „Sommer- und Winterreifen", „8-fach bereift", „Ganzjahres-/Allwetterreifen",
  „Kompletträder", „zusätzlich ein Satz Winterreifen" → Badge + Filter „Reifensätze ≥ 1/≥ 2". Verneinungen
  („keine Winterreifen") werden ignoriert.
* **Kennzeichen-Hinweise**: Kurzzeit-, Ausfuhr-/Zoll-, rotes (06/07er), Händler-/Überführungskennzeichen, Auslandszulassung.
* **Duplikate**: gleiche Marke + EZ-Jahr, km ±1.500 (bzw. ±3 %), Preis ±12 % **und** (pHash-Abstand ≤ 10 bei
  irgendeinem Bildpaar **oder** anderes Portal mit Standort ≤ 40 km). Das vollständigste Inserat wird Hauptinserat,
  die anderen erscheinen als „Auch inseriert auf …".

---

## 6. Neues Portal ergänzen

1. `scraper/autosuche/adapters/<portal>.py` anlegen, Klasse von `SourceAdapter` ableiten:
   * `discover_makes()` – Marken (und Modelle) **dynamisch** vom Portal lesen,
   * `iter_search(makes)` – Ergebnislisten → `Listing`-Objekte,
   * `fetch_detail(listing)` – Detailseite (falls per robots.txt erlaubt).
   Parser als reine Funktionen `HTML → Daten` schreiben.
2. In `adapters/__init__.py` in `ADAPTERS` eintragen, in `config.toml` `[sources.<portal>]` anlegen.
3. Eine echte Seite (gekürzt, Telefonnummern entfernt) unter `tests/fixtures/` ablegen und Parser-Tests schreiben.

Alle Abrufe laufen über `self.client.get()`; robots.txt, Rate-Limit, Retries und Block-Erkennung gelten damit automatisch.

---

## 7. Tests

```bash
cd scraper && python -m pytest -q
```

* `test_parsers.py` – AutoScout24- und Kleinanzeigen-Parser auf echten (gekürzten, anonymisierten) Seiten vom 17.11.2026
* `test_textparse.py` – Zahlen/Datum, Normalisierung, Reifen, Kennzeichen, Schlagworte inkl. Verneinung, Unfall, Kontakt-Schwärzung
* `test_scoring.py` – Regression, Rückfallgruppen, Unfall/Warnungen, Grenzen 0–100
* `test_dedupe_geo.py` – Duplikate (pHash/Standort), Haversine, PLZ-Tabelle

---

## 8. Bekannte Grenzen

Stand der Prüfung: **17.11.2026**. Portale ändern robots.txt und HTML regelmäßig – der Scraper prüft beides bei jedem Lauf.

| Portal | Status | Details |
|---|---|---|
| **AutoScout24** | ✅ aktiv (nur Ergebnislisten) | robots.txt erlaubt `/lst/<marke>?…`, **verbietet aber `/lst?…` und die Detailseiten `/angebote/`** für allgemeine Bots. Daher: Suche pro Marke (alle ~300 Marken rotierend), Daten nur aus den Listen. Vorhanden: Preis, km, EZ, PS/kW, Kraftstoff, Getriebe, Verkäufertyp, PLZ/Ort, **alle Galeriebilder**, Farbe (aus URL). **Fehlt: Beschreibung und Unfallhistorie** → Unfallstatus meist „unbekannt" (außer „unfallfrei" steht im Titel/Variantentext); Reifen-/Kennzeichen-Erkennung nur aus dem Titel. Der Filter „nur Unfallfahrzeuge" des Portals liefert keine Treffer und wird nicht genutzt. |
| **Kleinanzeigen** | ✅ aktiv | Liste + Detailseiten erlaubt. Gesuche („Suche Auto …") werden aussortiert (der Filter `anzeige:angebote` ist per robots.txt verboten). Detailseiten werden pro Lauf begrenzt (Standard 120), Inserate ohne geladene Detailseite haben ggf. noch keine Marke und erscheinen erst nach dem Detailabruf. **Kleinanzeigen blockt Rechenzentrums-IPs häufig** → bei `QUELLE BLOCKIERT` Variante B (Raspberry Pi). |
| **mobile.de** | ⛔ gesperrt | robots.txt verbietet `/fahrzeuge/search.html` und `*isSearchRequest=true`, zusätzlich antwortet mobile.de Bots mit HTTP 403 (Bot-Schutz). Der Adapter prüft das bei jedem Lauf und meldet es; es wird **nicht** versucht, die Sperre zu umgehen. |

Weitere Grenzen:

* **Abdeckung**: Pro Lauf werden je Marke nur die neuesten Seiten gelesen (konfigurierbar). Über die Rotation
  werden alle Marken nach und nach abgedeckt; wenig gehandelte Modelle haben anfangs kleine Vergleichsgruppen.
* **Marktpreis** basiert auf Angebotspreisen, nicht auf Verkaufspreisen; Ausstattung und Zustand fließen nicht ein.
* **Standort**: Entfernung über PLZ-Mittelpunkt (± einige km); Inserate ohne PLZ erscheinen nicht, sobald ein Umkreis gesetzt ist.
* **Bilder** werden als Original-URL vom Portal geladen (Hotlink, `no-referrer`); ändert ein Portal seine
  Bild-URLs, fehlen Bilder bis zum nächsten Lauf. Thumbnails (360 px) werden lokal gecacht.
* **Inaktive Inserate**: Nach 72 h ohne Sichtung verschwindet ein Inserat aus der App (Favoriten bleiben mit Hinweis erhalten).
* **OpenStreetMap-Kacheln** unterliegen der [Tile Usage Policy](https://operations.osmfoundation.org/policies/tiles/) – für private Nutzung unkritisch.
* **Laufzeit** auf GitHub Actions: CLIP braucht ~2–3 s pro Inserat (6 Bilder). Nicht analysierte Inserate werden
  im nächsten Lauf nachgeholt; bis dahin zählt der Fototeil nur die Anzahl.

---

## 9. Rechtliches & Fairness

* Privates, nicht-kommerzielles Projekt. Der Scraper identifiziert sich per User-Agent, hält robots.txt ein,
  hält Abstand zwischen Anfragen (≥ 3 s + Zufall pro Host, Crawl-delay wird respektiert), wiederholt Fehler mit
  Backoff und **umgeht keine Captchas oder Bot-Schutzmaßnahmen**.
* Prüfe vor dem Betrieb die Nutzungsbedingungen der Portale. Inhalte (Texte, Fotos) gehören den Anbietern; jede
  Karte verlinkt auf die Originalanzeige. Telefonnummern/E-Mails werden aus Beschreibungen entfernt und Namen
  privater Verkäufer nicht veröffentlicht.
* Daten: PLZ-Koordinaten © [GeoNames](https://www.geonames.org) (CC BY 4.0), Karte © OpenStreetMap-Mitwirkende,
  [Leaflet](https://leafletjs.com) (BSD-2), CLIP-Gewichte © OpenAI (MIT) via [Xenova/clip-vit-base-patch32](https://huggingface.co/Xenova/clip-vit-base-patch32).
* Der Score ist eine Orientierungshilfe, kein Gutachten.
