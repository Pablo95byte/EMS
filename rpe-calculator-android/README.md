# RPE Calculator (Android)

App Android per powerlifter ispirata a [rpecalculator.com](https://www.rpecalculator.com/):
dato un set eseguito (peso × ripetizioni @ RPE) stima l'1RM e calcola il peso da
caricare per un set target (ripetizioni @ RPE desiderati).

## Come funziona

Usa la tabella RPE di Reactive Training Systems (Mike Tuchscherer), la stessa del
sito: ogni coppia (RPE, ripetizioni) corrisponde a una percentuale dell'1RM.

1. **Set eseguito** — inserisci peso, ripetizioni (1–12) e RPE (6–10, passi da 0.5).
   L'app calcola l'1RM stimato: `e1RM = peso / percentuale × 100`.
2. **Set target** — scegli ripetizioni e RPE del prossimo set. L'app restituisce il
   peso: `peso = e1RM × percentuale / 100`, arrotondato al carico realmente
   caricabile (2.5 kg oppure 5 lb).
3. **Tabella rapida** — per il RPE target mostra i pesi per tutte le ripetizioni 1–12.

Unità selezionabile kg / lb.

## Struttura

```
app/src/main/java/com/pablo/rpecalculator/
├── RpeChart.kt        # tabella RPE → % 1RM (RTS)
├── RpeCalculator.kt   # stima 1RM, peso target, arrotondamento
├── MainActivity.kt    # UI Jetpack Compose (Material 3)
└── ui/theme/Theme.kt
```

## Build

Richiede Android Studio (o Android SDK 34 + JDK 17):

```bash
./gradlew assembleDebug      # APK in app/build/outputs/apk/debug/
./gradlew test               # unit test della logica di calcolo
```

Oppure apri la cartella `rpe-calculator-android/` direttamente in Android Studio
e premi Run.

- minSdk 26 (Android 8.0), targetSdk 34
- Kotlin 2.0 + Jetpack Compose (Material 3), nessuna dipendenza di rete: tutto offline
