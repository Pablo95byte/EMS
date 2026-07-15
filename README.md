# HEMS Predittivo — Huawei SUN2000 / LUNA2000

Sistema di gestione energetica Edge-to-Cloud per il controllo attivo e
predittivo della batteria, basato su tre flussi di dati:

1. **Telemetria fisica locale** via Modbus TCP (Smart Dongle WLAN-FE, porta 502);
2. **Forecast solare** da Open-Meteo (`global_tilted_irradiance` sul piano moduli);
3. **Prezzi orari MGP** dal GME (Mercato del Giorno Prima).

## Architettura

```
CLOUD/OTTIMIZZATORE          EDGE CONTROLLER              PHYSICAL LAYER
┌──────────────────┐        ┌──────────────────┐        ┌──────────────────┐
│ hems fetch-prices│        │ hems collect     │ Modbus │ SUN2000 inverter │
│ hems fetch-      │  DB    │  (telemetria)    │  TCP   │ LUNA2000 battery │
│      forecast    │───────▶│ hems control     │───────▶│ DTSU666-H meter  │
│ hems plan        │ piano  │  (control loop)  │  :502  │ Dongle WLAN-FE   │
└──────────────────┘        └──────────────────┘        └──────────────────┘
```

Il piano giornaliero vive nella tabella `pianificazione_oraria`; il control
loop locale lo esegue e resta funzionante anche senza internet (senza piano
per l'ora corrente resta in IDLE = massimo autoconsumo Huawei).

## Installazione

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp config/config.example.yaml config/config.yaml   # poi adattare all'impianto
```

## Comandi (uno per fase della roadmap)

| Comando | Fase | Descrizione |
|---|---|---|
| `hems collect` | 1 | Loop telemetria → tabella `telemetria_reale` (validare con FusionSolar) |
| `hems fetch-forecast` | 2 | Forecast solare Open-Meteo per domani |
| `hems fetch-prices` | 2 | Prezzi MGP GME per domani |
| `hems plan` | 3 | Calcola il piano di comandi per domani |
| `hems backtest --start 2026-03-01 --end 2026-04-01` | 3 | "Quanto avrebbe risparmiato a marzo?" |
| `hems control` | 4 | Control loop write-mode (partire con `dry_run: true`!) |
| `hems test-force --minutes 5` | 4 | Test isolato: scarica forzata 5 min + ripristino |

### Scheduling consigliato (crontab sull'edge)

```cron
# GME pubblica i prezzi del giorno dopo alle ~13:00
30 13 * * *  hems fetch-prices  && hems fetch-forecast && hems plan
```

`hems collect` e `hems control` girano come servizi (systemd/docker), vedi
`deploy/`.

## Sicurezza operativa (leggere prima di scrivere sull'inverter)

- **Una sola connessione Modbus**: la dongle Huawei accetta un solo client
  attivo. `HuaweiClient` serializza gli accessi con un lock, ma se altri
  servizi (Home Assistant, ecc.) parlano con la dongle serve un Modbus proxy.
- **Polling ≥ 10 s**: intervalli inferiori possono far crashare la dongle. Il
  limite è imposto a livello di client e non è configurabile sotto i 10 s.
- **Fall-back to normal**: qualsiasi errore nel control loop (o l'uscita del
  processo) riporta l'inverter alla modalità di default "Massimo Autoconsumo"
  (`47100=0`, `47087=0`).
- **Protezione SoC**: la scarica forzata è bloccata a runtime sotto
  `battery.soc_floor_perc` (default 15%) per preservare i cicli LiFePO4.
- **Dry-run first**: `control.dry_run: true` è il default; i comandi vengono
  loggati in `log_comandi` senza scrivere sull'inverter. Passare a `false`
  solo dopo aver validato i piani per qualche giorno.

## Registri Modbus usati

| Registro | Tipo | R/W | Significato |
|---|---|---|---|
| 32080 | Int32 | R | Potenza attiva inverter (W) |
| 37113 | Int32 | R | Smart meter (+ immette, − preleva) (W) |
| 37004 | Uint16 ×0.1 | R | SoC batteria (%) |
| 37001 | Int32 | R | Potenza batteria (+ carica, − scarica) (W) |
| 47087 | Uint16 | W | Abilitazione carica da rete (0/1) |
| 47100 | Uint16 | W | Forzatura: 0 stop, 1 carica, 2 scarica |
| 47247 | Uint32 | W | Potenza massima carica forzata (W) |
| 47242 | Uint32 | W | Potenza massima prelevabile dalla rete (W) |

## Logica dell'ottimizzatore

1. **Arbitraggio notturno** — se il prezzo medio nelle ore notturne (02–05) è
   sotto il 40% del picco serale (19–22) **e** il forecast solare del giorno è
   scarso (< 8 kWh), le ore notturne diventano `FORZATURA_RETE`.
2. **Scarica serale** — le ore di picco diventano `SCARICA_MASSIMA` (la
   batteria contiene la carica notturna o il surplus solare del giorno).
3. **Protezione SoC** — applicata a runtime dal control loop, mai dal piano.

Soglie e finestre orarie sono configurabili in `config.yaml` → `optimizer`.

## Test

```bash
pytest
```

I test coprono la codifica/decodifica dei registri, le regole del planner, il
parser XML GME, il motore di backtest e il control loop (con client finto —
nessun hardware necessario).

## Struttura del codice

```
hems/
├── config.py          # caricamento YAML + limiti di sicurezza
├── cli.py             # entry point `hems`
├── modbus/
│   ├── registers.py   # mappa registri + encode/decode
│   └── client.py      # HuaweiClient (lock, throttling, fallback)
├── db/database.py     # SQLite: telemetria_reale, pianificazione_oraria, log_comandi
├── telemetry/collector.py   # Fase 1
├── datalake/
│   ├── openmeteo.py   # Fase 2: forecast solare
│   └── gme.py         # Fase 2: prezzi MGP
├── optimizer/planner.py     # Fase 3: regole → piano giornaliero
├── simulation/backtest.py   # Fase 3: baseline vs ottimizzata
└── control/control_loop.py  # Fase 4: write-mode + fallback
```
