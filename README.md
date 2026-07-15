# HEMS Predittivo — Huawei SUN2000 / LUNA2000

**Home Energy Management System con controllo attivo e predittivo della batteria.**

Questo software non si limita a *guardare* l'impianto fotovoltaico: lo *comanda*.
Ogni giorno incrocia i prezzi orari dell'energia elettrica con le previsioni di
irraggiamento solare, decide quando conviene caricare la batteria dalla rete e
quando scaricarla, e invia i comandi all'inverter via Modbus TCP.

---

## Indice

1. [Cosa fa](#cosa-fa)
2. [Cosa serve](#cosa-serve)
3. [Come funziona](#come-funziona)
4. [Installazione](#installazione)
5. [Configurazione](#configurazione)
6. [Uso — le 4 fasi operative](#uso--le-4-fasi-operative)
7. [Messa in produzione](#messa-in-produzione)
8. [Sicurezza operativa](#sicurezza-operativa)
9. [Riferimento tecnico](#riferimento-tecnico)
10. [Troubleshooting](#troubleshooting)

---

## Cosa fa

### Il problema

Un impianto fotovoltaico con accumulo, lasciato nella modalità di fabbrica
("Massimo Autoconsumo"), segue una logica semplice: il surplus solare va in
batteria, i deficit vengono coperti dalla batteria. Funziona, ma **ignora
completamente i prezzi dell'energia**:

- nelle giornate di pioggia la batteria resta vuota e la casa compra tutta
  l'energia serale al prezzo di picco (spesso 200–300 €/MWh);
- di notte l'energia costa una frazione del prezzo serale (a volte meno del
  40%), ma la batteria non ne approfitta mai.

### La soluzione

Il sistema pianifica il giorno successivo **ogni pomeriggio alle 13:30**,
quando il GME pubblica i prezzi del giorno dopo:

| Situazione rilevata | Azione pianificata |
|---|---|
| Notte economica + domani piove | **Carica la batteria dalla rete di notte** a prezzo basso (arbitraggio) |
| Ore serali di picco prezzi | **Scarica la batteria** al posto di comprare a prezzo pieno |
| Giornata di sole normale | Nessun intervento: resta il massimo autoconsumo Huawei |

Il risparmio è misurabile: il motore di **backtesting** integrato simula la
strategia sui dati storici reali dell'impianto e risponde alla domanda
*"se il sistema avesse girato il mese scorso, quanti euro avrei risparmiato?"*.

### A chi serve

- **Uso domestico**: riduzione della bolletta con tariffe orarie/PUN.
- **C&I (Commercial & Industrial)**: base per peak shaving e ottimizzazione
  di tariffe multiorarie.
- **CER / Aggregatori**: il motore logico è progettato per essere replicato su
  più batterie distribuite (orchestrazione dell'energia condivisa).

---

## Cosa serve

### Hardware (impianto)

| Componente | Modello | Note |
|---|---|---|
| Inverter | **Huawei SUN2000** (serie L1/M1/MAP0...) | Qualsiasi taglia |
| Batteria | **Huawei LUNA2000** | LiFePO4, 5–30 kWh |
| Misuratore di rete | **Smart Power Sensor DTSU666-H** | ⚠️ **Indispensabile**: senza meter non esiste il bilancio di casa e il sistema non può funzionare |
| Comunicazione | **Smart Dongle WLAN-FE** | Collegata **via cavo ethernet** alla LAN, con **IP statico** (riservare l'IP sul router via DHCP) |

Sulla dongle deve essere **abilitato il Modbus TCP** (da app FusionSolar:
`Impostazioni → Comunicazione → Dongle → Modbus TCP → Abilita senza restrizioni`,
porta 502).

> ⚠️ **Vincolo critico della dongle**: accetta **una sola connessione Modbus
> attiva alla volta**. Se Home Assistant o altri servizi già la interrogano,
> serve un Modbus proxy (es. [modbus-proxy](https://github.com/tiagocoutinho/modbus-proxy))
> davanti alla dongle, e tutti i client puntano al proxy.

### Hardware (edge controller)

Un piccolo computer Linux sempre acceso sulla stessa LAN dell'inverter:

- Raspberry Pi 3/4/5 (anche Zero 2 W va bene),
- oppure un mini PC, un NAS con Docker, una VM su un server di casa.

Requisiti minimi: 512 MB RAM, 1 GB disco, Python 3.11+.

### Software e servizi esterni

| Cosa | Serve per | Costo / registrazione |
|---|---|---|
| **Python ≥ 3.11** | Tutto | gratis |
| **Open-Meteo API** | Previsioni di irraggiamento solare | gratis, **nessuna API key** |
| **Prezzi MGP del GME** | Prezzi orari del giorno dopo | gratis; il download dal sito richiede l'accettazione delle condizioni d'uso (vedi [Configurazione](#prezzi-gme)) |

### Dati dell'impianto da conoscere

Prima di configurare, procurarsi:

- coordinate dell'impianto (latitudine/longitudine);
- **tilt** (inclinazione dei moduli, tipicamente 20–35°) e **azimuth**
  (orientamento: 0 = sud, −90 = est, +90 = ovest);
- potenza di picco in **kWp**;
- capacità batteria in **kWh** e potenze massime di carica/scarica in W;
- IP statico assegnato alla dongle.

---

## Come funziona

### Architettura a 3 livelli

```
     CLOUD / OTTIMIZZATORE             EDGE CONTROLLER                PHYSICAL LAYER
    (pianificazione, 1×/giorno)      (esecuzione, 24/7)              (impianto)
   ┌─────────────────────────┐     ┌──────────────────────┐        ┌──────────────────┐
   │  Open-Meteo ──┐         │     │  hems collect        │ Modbus │ SUN2000 inverter │
   │  GME (MGP) ───┤         │ DB  │   (telemetria 60s)   │  TCP   │ LUNA2000 battery │
   │               ▼         │────▶│  hems control        │───────▶│ DTSU666-H meter  │
   │  hems plan → piano 24h  │     │   (control loop 30s) │  :502  │ Dongle WLAN-FE   │
   └─────────────────────────┘     └──────────────────────┘        └──────────────────┘
```

Il principio guida è la **resilienza**: se internet cade, la casa continua a
funzionare. Il control loop locale legge il piano dal database; se per l'ora
corrente non c'è un piano, resta in IDLE, che coincide con la modalità di
fabbrica Huawei "Massimo Autoconsumo".

### Il ciclo giornaliero

```
13:00  Il GME pubblica i prezzi MGP di domani
13:30  cron:  hems fetch-prices     → prezzi orari in DB
              hems fetch-forecast   → forecast solare in DB
              hems plan             → piano di 24 comandi in DB
─────────────────────────────────────────────────────────────
00:00→ Il control loop esegue il piano ora per ora:
02:00  FORZATURA_RETE   (se arbitraggio attivo: carica a 45 €/MWh)
07:00  IDLE             (autoconsumo normale)
19:00  SCARICA_MASSIMA  (evita di comprare a 240 €/MWh)
22:00  IDLE
```

### Le regole dell'ottimizzatore

1. **Arbitraggio notturno** — attivo solo se valgono *entrambe* le condizioni:
   - prezzo medio notturno (02–05) **< 40%** del picco serale (19–22);
   - produzione solare prevista per domani **< 8 kWh** (giornata scarsa).

   In tal caso le ore notturne diventano `FORZATURA_RETE` (carica dalla rete).
2. **Scarica serale** — le ore di picco diventano `SCARICA_MASSIMA`: la
   batteria (caricata di notte o dal sole) copre i consumi serali.
3. **Protezione SoC** — indipendentemente dal piano, il control loop **blocca
   la scarica sotto il 15%** di SoC (preserva i cicli di vita LiFePO4).

Tutte le soglie e le finestre orarie sono configurabili.

---

## Installazione

Sull'edge controller (esempio: Raspberry Pi OS / Debian):

```bash
# 1. Prerequisiti di sistema
sudo apt update && sudo apt install -y python3 python3-venv git

# 2. Clona il repository
git clone https://github.com/Pablo95byte/EMS.git /opt/hems
cd /opt/hems

# 3. Ambiente virtuale e dipendenze
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 4. Verifica: la suite di test non richiede hardware
pytest

# 5. Crea la configurazione dal template
cp config/config.example.yaml config/config.yaml
nano config/config.yaml     # vedi sezione seguente
```

---

## Configurazione

Tutto vive in `config/config.yaml`. Le sezioni essenziali:

### Inverter

```yaml
inverter:
  host: "192.168.1.100"    # IP statico della dongle
  port: 502
  slave_id: 1              # di norma 1; se non risponde provare 0 o 16
```

### Impianto e batteria

```yaml
plant:
  latitude: 45.464
  longitude: 9.190
  tilt_deg: 30             # inclinazione moduli
  azimuth_deg: 0           # 0=sud, -90=est, +90=ovest (convenzione Open-Meteo)
  kwp: 6.0
  performance_ratio: 0.85  # perdite di sistema (cavi, inverter, sporco): 0.80-0.90

battery:
  capacity_kwh: 10.0
  max_charge_w: 5000
  max_discharge_w: 5000
  soc_floor_perc: 15.0     # protezione: mai scaricare sotto questa soglia
```

### Prezzi GME

```yaml
gme:
  zone: "PUN"              # oppure la zona di mercato: NORD, CNOR, CSUD, SUD, SICI, SARD
  xml_dir: "data/gme"
```

Il GME pubblica i prezzi in file XML `YYYYMMDDMGPPrezzi.xml`. Il download
automatico dal sito richiede l'accettazione delle condizioni d'uso, quindi ci
sono due strade:

1. **File locale** (consigliata per iniziare): scaricare manualmente — o con un
   proprio script che ha accettato le condizioni — il file del giorno dopo e
   depositarlo in `data/gme/`. Il comando `hems fetch-prices` lo trova da solo.
2. **URL diretto**: se si dispone di un endpoint raggiungibile, configurare
   `download_url_template` e il download diventa automatico.

### Ottimizzatore

```yaml
optimizer:
  night_hours: [2, 3, 4]        # finestra di carica notturna
  peak_hours: [19, 20, 21]      # finestra di scarica serale
  night_price_ratio: 0.40       # arbitraggio se notte < 40% del picco
  low_solar_day_kwh: 8.0        # sotto questa produzione prevista il giorno è "scarso"
  forced_charge_w: 3000         # potenza di carica notturna
  max_grid_power_w: 4000        # limite di prelievo dalla rete (non superare il contatore!)
```

> 💡 `forced_charge_w + consumi notturni di casa` deve restare sotto la potenza
> contrattuale del contatore, altrimenti scatta la limitazione del distributore.

### Control loop

```yaml
control:
  loop_interval_s: 30
  dry_run: true            # ⚠️ default: NON scrive sull'inverter, logga soltanto
```

---

## Uso — le 4 fasi operative

Il progetto è pensato per essere messo in produzione **gradualmente**, in 4
fasi. Non saltare le fasi: ognuna valida la precedente.

### Fase 1 — Telemetria (solo lettura) ✅ si parte da qui

```bash
hems collect
```

Legge ogni 60 s produzione, scambio rete, potenza e SoC batteria, e salva
tutto nella tabella `telemetria_reale`. Lasciarlo girare **qualche giorno** e
confrontare i valori con l'app FusionSolar: devono coincidere.

```bash
# Controllare i dati raccolti
sqlite3 data/hems.sqlite3 "SELECT * FROM telemetria_reale ORDER BY timestamp DESC LIMIT 5;"
```

### Fase 2 — Data-lake esterno (prezzi + meteo)

```bash
hems fetch-prices                 # prezzi MGP di domani (default: domani)
hems fetch-forecast               # forecast solare di domani
hems fetch-prices --date 2026-07-20   # oppure una data specifica
```

Riempiono la tabella `pianificazione_oraria`. Automatizzare con cron (vedi
[Messa in produzione](#messa-in-produzione)).

### Fase 3 — Piano e backtesting (ancora nessuna scrittura)

```bash
hems plan          # calcola e stampa il piano di domani
```

Esempio di output:

```
2026-07-16 02:00    45.00 EUR/MWh  PV      0 W  FORZATURA_RETE
2026-07-16 03:00    45.00 EUR/MWh  PV      0 W  FORZATURA_RETE
...
2026-07-16 19:00   240.00 EUR/MWh  PV      0 W  SCARICA_MASSIMA
```

Dopo qualche settimana di telemetria e prezzi accumulati, misurare il
potenziale risparmio sui **dati reali del proprio impianto**:

```bash
hems backtest --start 2026-06-01 --end 2026-07-01
# Costo baseline:          62.40 EUR
# Costo ottimizzato:       51.15 EUR
# Risparmio stimato:       11.25 EUR
```

Se il risparmio non giustifica l'usura extra della batteria, fermarsi qui:
si ha comunque un ottimo sistema di monitoraggio.

### Fase 4 — Write-mode (controllo attivo) ⚠️

**Passo 1 — dry-run.** Con `dry_run: true` (il default), lanciare il control
loop e osservare per qualche giorno cosa *farebbe*:

```bash
hems control
# I comandi finiscono in log_comandi con esito DRY_RUN, l'inverter non viene toccato
sqlite3 data/hems.sqlite3 "SELECT * FROM log_comandi ORDER BY id DESC LIMIT 10;"
```

**Passo 2 — test isolato.** Verificare che l'inverter risponda fisicamente ai
comandi con un test controllato di 5 minuti (con `dry_run: false`):

```bash
hems test-force --minutes 5
# SoC iniziale 78.4% - forzo la scarica per 5 min
#   batteria -2980 W, SoC 78.1%
#   batteria -3010 W, SoC 77.9%
# Inverter riportato a Massimo Autoconsumo
```

Il test si interrompe da solo se il SoC scende alla soglia e **ripristina
sempre** la modalità di default all'uscita, anche in caso di errore.

**Passo 3 — produzione.** Solo quando piani e test convincono: impostare
`dry_run: false` e installare il servizio (sezione seguente).

---

## Messa in produzione

### Cron (pianificazione giornaliera)

```cron
# Il GME pubblica i prezzi di domani alle ~13:00; alle 13:30 scarichiamo tutto e pianifichiamo
30 13 * * * cd /opt/hems && .venv/bin/hems fetch-prices && .venv/bin/hems fetch-forecast && .venv/bin/hems plan >> /var/log/hems-plan.log 2>&1
```

### systemd (servizi 24/7)

```bash
sudo useradd -r -s /usr/sbin/nologin hems
sudo chown -R hems:hems /opt/hems
sudo cp deploy/hems-collector.service /etc/systemd/system/
sudo cp deploy/hems-control.service   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hems-collector      # Fase 1: sempre
sudo systemctl enable --now hems-control        # Fase 4: solo a validazione conclusa
```

Log in tempo reale: `journalctl -u hems-collector -f`

---

## Sicurezza operativa

Regole non negoziabili, tutte **già imposte dal codice**:

| Protezione | Implementazione |
|---|---|
| **Polling ≥ 10 s** | Intervalli inferiori possono far **crashare la dongle**. Il client Modbus impone 10 s come minimo assoluto tra transazioni, qualunque cosa dica la configurazione. |
| **Connessione singola** | `HuaweiClient` serializza tutti gli accessi con un lock interno. Se altri servizi usano la dongle → Modbus proxy. |
| **Protezione SoC** | La scarica forzata è rifiutata a runtime sotto `soc_floor_perc` (default 15%), anche se il piano la richiede. |
| **Fall-back to normal** | Qualsiasi errore nel control loop — o la semplice uscita del processo (Ctrl-C, SIGTERM, crash) — riporta l'inverter a "Massimo Autoconsumo" (`47100=0`, `47087=0`). L'impianto non resta *mai* in uno stato forzato senza supervisione. |
| **Dry-run di default** | `control.dry_run: true` alla prima installazione: nessuna scrittura finché non viene disattivato consapevolmente. |
| **Audit trail** | Ogni comando (anche in dry-run) è registrato in `log_comandi` con timestamp, registro, valore ed esito. |

E una regola che spetta a chi configura: `max_grid_power_w` + consumi notturni
**sotto la potenza contrattuale** del contatore.

---

## Riferimento tecnico

### Registri Modbus (Huawei SUN2000 via Smart Dongle, porta 502)

| Registro | Tipo | R/W | Significato |
|---|---|---|---|
| 32080 | Int32 | R | Potenza attiva inverter — produzione AC (W) |
| 37113 | Int32 | R | Smart meter: + immette in rete, − preleva (W) |
| 37004 | Uint16, passo 0.1 | R | SoC batteria (500 → 50.0%) |
| 37001 | Int32 | R | Potenza batteria: + carica, − scarica (W) |
| 47087 | Uint16 | W | Abilitazione carica da rete: 1 on, 0 off |
| 47100 | Uint16 | W | Forzatura: 0 stop, 1 carica, 2 scarica |
| 47247 | Uint32 | W | Potenza massima di carica forzata (W) |
| 47242 | Uint32 | W | Potenza massima prelevabile dalla rete (W) |

I registri a 32 bit occupano 2 word big-endian (word alta prima).
Il **consumo di casa** non ha un registro dedicato: è calcolato come
`produzione − scambio_rete − potenza_batteria`.

### Schema del database (SQLite, portabile a PostgreSQL)

```sql
telemetria_reale        (timestamp PK, produzione_w, consumo_casa_w,
                         meter_rete_w, batteria_w, batteria_soc_perc)
pianificazione_oraria   (data_ora_target PK, prezzo_energia_mwh,
                         produzione_solare_prevista_w, comando_strategico)
log_comandi             (id PK, timestamp, registro, valore, comando, esito, dry_run)
```

`comando_strategico` ∈ { `IDLE`, `FORZATURA_RETE`, `SCARICA_MASSIMA`, `BLOCCO_SCARICA` }

### Struttura del codice

```
hems/
├── config.py                 # caricamento YAML + limiti di sicurezza
├── cli.py                    # entry point `hems`
├── modbus/
│   ├── registers.py          # mappa registri + encode/decode
│   └── client.py             # HuaweiClient: lock, throttling ≥10s, fallback
├── db/database.py            # SQLite: le 3 tabelle
├── telemetry/collector.py    # Fase 1: polling telemetria
├── datalake/
│   ├── openmeteo.py          # Fase 2: forecast GTI → W attesi
│   └── gme.py                # Fase 2: parser XML MGPPrezzi
├── optimizer/planner.py      # Fase 3: regole → piano 24h
├── simulation/backtest.py    # Fase 3: baseline vs ottimizzata → € risparmiati
└── control/control_loop.py   # Fase 4: piano → registri, SoC guard, fallback
tests/                        # 24 test, nessun hardware richiesto (client finto)
deploy/                       # unit systemd per collector e control loop
```

### Stima del forecast solare

Open-Meteo fornisce la **GTI** (Global Tilted Irradiance, W/m²) già calcolata
sul piano dei moduli dati tilt e azimuth. La potenza AC attesa è:

```
P_ac [W] = kWp × 1000 × (GTI / 1000) × performance_ratio
```

È un modello lineare semplice (niente dipendenza da temperatura): adeguato per
la decisione binaria "giornata buona / giornata scarsa" che serve al planner.

---

## Troubleshooting

**La connessione Modbus va in timeout**
- Verificare che il Modbus TCP sia abilitato sulla dongle (da FusionSolar).
- La dongle accetta **un solo client**: chiudere Home Assistant/altri client o
  usare un Modbus proxy.
- Dopo il connect la dongle impiega qualche secondo a rispondere: il client lo
  gestisce già (attesa di 3 s), ma un firewall sulla porta 502 no.

**I valori non coincidono con FusionSolar**
- FusionSolar media su finestre diverse: scarti di ±50 W sono normali.
- Se i segni sono invertiti (immissione/prelievo), verificare l'installazione
  del DTSU666-H (direzione dei TA).

**`hems fetch-prices` fallisce**
- Controllare che il file `YYYYMMDDMGPPrezzi.xml` di *domani* sia in `data/gme/`
  (il GME lo pubblica dopo le 13:00).
- Verificare che la `zone` configurata esista nel file (PUN, NORD, ...).

**La dongle è crashata / non risponde più**
- Quasi sempre causato da polling troppo aggressivo di *altri* client.
  Togliere alimentazione alla dongle per 30 s. Questo software non scende mai
  sotto i 10 s tra transazioni.

**Il control loop è morto: l'inverter è rimasto in forzatura?**
- No, se il processo è uscito in modo ordinato: il fallback scrive `47100=0` e
  `47087=0` all'uscita. In caso di kill −9 o blackout dell'edge, l'inverter
  mantiene l'ultimo comando: rientrando, il control loop riallinea lo stato al
  primo giro. Per sicurezza si può verificare da FusionSolar.

**Voglio ricominciare da zero**
- `rm data/hems.sqlite3` — il database viene ricreato al primo comando.

---

## Test

```bash
pytest          # 24 test: registri, planner, parser GME, backtest, control loop
```

Nessun test richiede hardware: il control loop è testato con un client Modbus
finto.

## Licenza e stato del progetto

MVP in sviluppo attivo. Le 4 fasi della roadmap sono implementate; la
validazione sull'impianto reale (Fase 1 → confronto con FusionSolar) è il
prossimo passo operativo.
