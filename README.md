# Sentiment Analysis — Deploy e Monitoraggio

Progetto per il corso DevOps. L'obiettivo è prendere un modello di Sentiment Analysis già addestrato (file `.pkl`) ed esporlo come servizio REST, automatizzando il deploy con una pipeline CI/CD e monitorando il sistema con Prometheus e Grafana.

Repository: https://github.com/daniela-pini/sentiment-analysis

## Indice

1. [Cosa fa il progetto](#1-cosa-fa-il-progetto)
2. [Tecnologie usate](#2-tecnologie-usate)
3. [Struttura delle cartelle](#3-struttura-delle-cartelle)
4. [Come avviare il progetto](#4-come-avviare-il-progetto)
5. [Come usare l'API](#5-come-usare-lapi)
6. [Note sul modello e suoi limiti](#6-note-sul-modello-e-suoi-limiti)
7. [Pipeline CI/CD con Jenkins](#7-pipeline-cicd-con-jenkins)
8. [Monitoraggio e alert](#8-monitoraggio-e-alert)
9. [Generare traffico per la demo](#9-generare-traffico-per-la-demo)
10. [Comandi utili e manutenzione](#10-comandi-utili-e-manutenzione)
11. [Problemi comuni](#11-problemi-comuni)

## 1. Cosa fa il progetto

Un'azienda di e-commerce ha bisogno di classificare automaticamente le recensioni dei prodotti in **positive**, **negative** o **neutre**. Il progetto:

- Espone il modello tramite un'API REST (`POST /predict`).
- Costruisce un'immagine Docker dell'applicazione.
- Usa Jenkins per testare, costruire e deployare automaticamente ad ogni modifica del codice.
- Raccoglie metriche con Prometheus (richieste, latenza, CPU, memoria, errori).
- Mostra dashboard in tempo reale su Grafana.
- Manda alert quando qualcosa va male (es. CPU sopra il 90%).

Sono presenti due ambienti: **staging** (deploy automatico ad ogni commit) e **production** (deploy automatico con strategia blue/green per non avere downtime).

## 2. Tecnologie usate

- **Python 3.11** + **FastAPI** per l'API REST
- **scikit-learn** per il modello (Pipeline con CountVectorizer + MultinomialNB)
- **Docker** + **Docker Compose** per i container
- **Jenkins** per la pipeline CI/CD
- **Prometheus** per raccogliere le metriche
- **Grafana** per le dashboard
- **Nginx** come reverse proxy per il blue/green deployment
- **pytest** per i test

## 3. Struttura delle cartelle

```
sentiment-project/
├── app/                          # codice dell'API
│   ├── main.py                   # FastAPI app
│   ├── requirements.txt
│   ├── sentimentanalysismodel.pkl
│   └── .dockerignore             # file esclusi dall'immagine Docker
├── tests/                        # test
│   ├── test_model.py             # test sul modello
│   └── test_api.py               # test sull'API
├── docker/
│   ├── Dockerfile                # immagine dell'API
│   ├── Dockerfile.jenkins        # immagine custom di Jenkins (con Python e Docker)
│   └── docker-compose.yml        # orchestrazione di tutti i servizi
├── jenkins/
│   ├── Jenkinsfile               # pipeline principale (blue/green)
│   └── Jenkinsfile.canary        # esempio alternativo con canary deployment
├── monitoring/
│   ├── nginx/nginx.conf          # config nginx per il blue/green
│   ├── prometheus/
│   │   ├── prometheus.yml        # cosa monitorare
│   │   └── alerts.yml            # regole di alert
│   └── grafana/                  # dashboard preconfigurata
├── scripts/
│   ├── blue-green-switch.sh      # script per lo switch fra colori
│   └── generate_traffic.py       # genera richieste per popolare le dashboard
└── README.md
```

## 4. Come avviare il progetto

**Requisiti:** Docker Desktop installato e in esecuzione.

### Passo 1 — Avviare lo stack principale

```powershell
cd docker
docker compose up -d
```

La prima volta richiede qualche minuto perché scarica le immagini e costruisce quella custom di Jenkins. Una volta finito, questi servizi sono raggiungibili:

- API in staging: http://localhost:8000
- Documentazione interattiva dell'API (Swagger): http://localhost:8000/docs
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000 (login: `admin` / `admin123`)
- Jenkins: http://localhost:8090

> Jenkins è sulla porta 8090 invece della 8080 perché spesso quella è già occupata da altri processi Java su Windows.

### Passo 2 — Avviare l'ambiente di produzione (blue/green)

```powershell
docker compose --profile production up -d
```

Questo aggiunge i container `sentiment-api-blue`, `sentiment-api-green` e `nginx-prod`. L'API di produzione è raggiungibile su http://localhost:8001.

### Passo 3 — Verificare che tutto sia attivo

```powershell
docker compose ps
```

Devono apparire tutti i container con stato `running` o `healthy`.

## 5. Come usare l'API

Il modo più semplice per provare l'API è la **Swagger UI**, una pagina web interattiva che fornisce FastAPI in automatico. Apri nel browser:

**http://localhost:8000/docs**

Vedrai la lista dei tre endpoint principali. Per fare una predizione:

1. Clicca su `POST /predict` per espanderlo
2. Clicca il pulsante **Try it out** in alto a destra
3. Nel riquadro **Request body** modifica il campo `review` con una recensione in inglese, ad esempio:
   ```json
   {
     "review": "This product is amazing!"
   }
   ```
4. Clicca **Execute**
5. Scorri sotto: in **Server response** appare la risposta JSON

Esempio di risposta:

```json
{
  "sentiment": "positive",
  "confidence": 0.7092,
  "review": "This product is amazing!",
  "request_id": "8f3a2c9b-4d5e-6f7a-8b9c-0d1e2f3a4b5c",
  "color": "staging"
}
```

I valori possibili per `sentiment` sono `positive`, `negative`, `neutral`.

Il campo `request_id` serve per il **distributed tracing**: ogni richiesta ha un identificativo unico che compare anche nei log dell'applicazione, così è possibile correlare cosa è successo a una specifica chiamata.

Prova con frasi diverse per vedere come cambia la classificazione:

- *"I love this product so much, it is fantastic!"* → positive
- *"Terrible quality, complete waste of money"* → negative
- *"It works as expected, nothing special"* → neutral

### Gli altri endpoint

**`GET /health`** — verifica lo stato del servizio. Risposta:
```json
{"status":"healthy","environment":"staging","color":"staging"}
```

**`GET /metrics`** — espone le metriche in formato Prometheus. Non serve chiamarlo a mano: lo fa Prometheus automaticamente ogni 10 secondi.

### Test da PowerShell (alternativa)

Se preferisci usare il terminale invece della Swagger UI, il comando nativo di PowerShell è `Invoke-RestMethod`:

```powershell
$body = @{ review = "This product is amazing!" } | ConvertTo-Json
Invoke-RestMethod -Uri http://localhost:8000/predict -Method POST -Body $body -ContentType "application/json"
```

Nota: il classico `curl` su Windows spesso non è installato di default, quindi `Invoke-RestMethod` è la scelta più portabile.

## 6. Note sul modello e suoi limiti

Il modello fornito è un classificatore **Naive Bayes** addestrato su un approccio **bag-of-words** (`CountVectorizer + MultinomialNB` di scikit-learn). Funziona contando le parole della recensione e calcolando la probabilità di appartenenza a ciascuna classe in base a quanto ogni parola è "tipica" di quella classe nei dati di training.

È un modello semplice ed efficace per recensioni dirette, ma ha alcuni limiti noti tipici dei modelli bag-of-words.

**Non comprende le negazioni.** Le parole vengono pesate singolarmente senza tenere conto del contesto. Ad esempio:

| Recensione | Sentimento atteso | Sentimento previsto |
|---|---|---|
| `"This product is good"` | positive | positive ✅ |
| `"This product is not good"` | negative | **positive ❌** |
| `"Never buy this"` | negative | neutral/positive ❌ |

Nel secondo caso, il modello vede separatamente `not` e `good`: il peso positivo di `good` nelle recensioni di training supera quello (debole) di `not`, e la frase viene classificata come positiva.

**Non capisce ironia, sarcasmo o frasi complesse.** È un limite strutturale degli approcci bag-of-words.

**Confidence bassa su frasi neutre.** Recensioni come `"It's okay"` o `"Standard product"` ottengono spesso confidence intorno a 0.50-0.65, perché poche parole hanno un segnale forte.

### Possibili miglioramenti futuri

Per gestire correttamente le negazioni e il contesto servirebbero modelli più sofisticati, non implementati in questo progetto perché esulano dall'obiettivo principale (deploy e monitoraggio):

- **N-grammi**: configurare il `CountVectorizer` con `ngram_range=(1,2)` farebbe sì che il modello veda `not good` come un'unica unità, distinta da `good` da solo
- **Modelli neurali pre-addestrati**: BERT, RoBERTa o un transformer più piccolo (DistilBERT) gestiscono il contesto naturalmente, al costo di risorse computazionali maggiori
- **Re-training su un dataset più ampio**: includere esempi specifici con negazioni nei dati di training

### Frasi consigliate per la demo

Per evitare effetti sorpresa durante test manuali su Swagger UI, sotto qualche esempio di frasi che il modello classifica in modo affidabile:

- **Positive:** `"I love this product so much, it is fantastic!"`, `"Excellent quality, highly recommend!"`, `"Best purchase I made this year!"`
- **Negative:** `"Terrible quality, complete waste of money"`, `"Worst purchase ever, broken on arrival"`, `"Awful experience, totally disappointed"`
- **Neutral:** `"It works as expected, nothing special"`, `"Average product for the price"`

## 7. Pipeline CI/CD con Jenkins

La pipeline è completamente automatica: ad ogni `git push` sul branch `main`, Jenkins fa tutto da solo, senza intervento manuale.

### Stage della pipeline

```
1.  Checkout                          (scarica il codice da GitHub)
2.  Setup                             (crea venv e installa dipendenze)
3.  Unit Tests                        (pytest sui test del modello)
4.  Integration Tests                 (pytest sui test dell'API)
5.  Build Docker Image                (costruisce l'immagine)
6.  Push to Registry                  (opzionale, se configurato)
7.  Deploy to Staging                 (deploy automatico)
8.  Staging Smoke Test                (verifica che lo staging risponda)
9.  Determine Inactive Color          (capisce se è inattivo blue o green)
10. Deploy to Production              (deploya sul colore inattivo)
11. Production Smoke Test             (testa il colore inattivo)
12. Blue/Green Switch                 (nginx -s reload, switch atomico)
13. Post-Switch Verification          (verifica che il nuovo colore sia live)
```

Se uno stage fallisce, la pipeline si ferma e la produzione resta intatta.

### Come funziona il Blue/Green

In produzione ci sono due container identici dell'API, chiamati `blue` e `green`. In ogni momento solo uno dei due (il "colore attivo") riceve traffico utenti, l'altro è inattivo. Nginx sa qual è quello attivo perché è scritto in `nginx.conf`.

Quando arriva una nuova versione:

1. Si capisce qual è il colore inattivo (es. `green`).
2. Si ricrea il container `green` con la nuova immagine.
3. Si fa uno smoke test su `green` (senza traffico utenti).
4. Se tutto ok, lo script `blue-green-switch.sh` modifica `nginx.conf` e fa `nginx -s reload`. Nello stesso istante il traffico passa da `blue` a `green`.
5. `blue` resta acceso pronto a riprendere il traffico se servisse un rollback rapido.

Il vantaggio è che gli utenti non vedono mai downtime durante il deploy.

### Primo accesso a Jenkins

La prima volta che apri Jenkins su http://localhost:8090 viene richiesta una password di sblocco generata casualmente al primo avvio e salvata in un file dentro il container. Per leggerla esegui da PowerShell:

```powershell
docker exec jenkins cat /var/jenkins_home/secrets/initialAdminPassword
```

Copia la stringa di output (es. `8f3a2c9b4d5e6f...`) e incollala nel campo **Administrator password** del browser, poi clicca **Continue**.

Jenkins ti guiderà nella configurazione iniziale:

1. **Install suggested plugins**: scegli questa opzione, installa i plugin standard (Git, Pipeline, Email, ecc.). Richiede 3-5 minuti.
2. **Create First Admin User**: crea l'utente che userai d'ora in poi (es. `admin` con una password a tua scelta). Annota le credenziali, ti serviranno per i prossimi accessi.
3. **Instance Configuration**: lascia pre-compilato (`http://localhost:8090/`) e clicca **Save and Finish**.
4. **Start using Jenkins** → arrivi alla dashboard principale.

A questo punto sei pronta per configurare il job della pipeline (sezione successiva).

### Configurare il job in Jenkins

1. Vai su http://localhost:8090, fai login.
2. Clicca **New Item** in alto a sinistra.
3. Nome del job: `sentiment-analysis`, tipo: **Pipeline**, poi OK.
4. Nella sezione **Pipeline**:
   - Definition: `Pipeline script from SCM`
   - SCM: `Git`
   - Repository URL: `https://github.com/daniela-pini/sentiment-analysis.git`
   - Branch Specifier: `*/main`
   - Script Path: `jenkins/Jenkinsfile`
5. Save, poi **Build Now**.

**Precondizione importante:** prima di lanciare la pipeline, l'ambiente di produzione deve essere già attivo (`docker compose --profile production up -d`). Jenkins non gestisce l'intera infrastruttura ma solo l'aggiornamento del container del colore inattivo — è il pattern standard in un workflow GitOps reale, dove l'infrastruttura è pre-esistente e la pipeline aggiorna soltanto le applicazioni.

### Perché Jenkins usa un'immagine custom

L'immagine ufficiale di Jenkins (`jenkins/jenkins:lts-jdk17`) contiene solo Java e Jenkins. La nostra pipeline ha bisogno anche di:

- **Python 3** per eseguire i test con pytest
- **Docker CLI** per costruire l'immagine dell'API e gestire i container
- **curl** per gli smoke test

Per questo c'è il file `docker/Dockerfile.jenkins` che parte dall'immagine ufficiale e aggiunge questi strumenti. Docker Compose la costruisce automaticamente al primo `up`.

Il Docker CLI dentro Jenkins comunica con Docker Desktop dell'host tramite il socket `/var/run/docker.sock` montato nel container.

### Canary deployment (alternativa)

Nel file `jenkins/Jenkinsfile.canary` c'è un esempio di pipeline alternativa che usa il **canary deployment** invece del blue/green: il traffico viene spostato in modo graduale (10% → 50% → 100%) controllando le metriche tra uno step e l'altro. Non è quella usata di default, ma è inclusa come esempio per mostrare un'altra strategia.

## 8. Monitoraggio e alert

### Cosa misuriamo

L'API espone metriche su `/metrics`, raccolte da Prometheus ogni 10 secondi:

- **Richieste totali** — diviso per sentimento (positive/negative/neutral)
- **Latenza** — con bucket per calcolare p50 e p95
- **Errori di predizione** — quante richieste sono fallite
- **CPU** — utilizzo del processo
- **Memoria** — utilizzo del processo

Tutte le metriche hanno una label `environment` (staging o production) e `color` (blue, green o staging), così si possono distinguere nelle dashboard.

### Dashboard Grafana

Su http://localhost:3000 → menu **Dashboards** → cartella **Sentiment Analysis** → dashboard **Sentiment Analysis API - Monitoring**.

Contiene:

- Numero totale di richieste e di errori
- Gauge di CPU e memoria con soglie colorate
- Grafico delle richieste al secondo, diviso per sentimento
- Grafico della latenza p50 e p95
- Torta con la distribuzione dei sentimenti
- Tasso di errore percentuale

### Alert configurati

Le regole di alert sono in `monitoring/prometheus/alerts.yml`. Sono visibili su http://localhost:9090/alerts.

| Alert | Quando scatta |
|---|---|
| SentimentAPIDown | API non risponde per 1 minuto |
| HighErrorRate | tasso di errore > 5% per 2 minuti |
| HighP95Latency | p95 > 1s per 2 minuti |
| VeryHighP95Latency | p95 > 2s per 2 minuti |
| HighCPUUsage | CPU > 90% per 1 minuto |
| ElevatedCPUUsage | CPU > 70% per 5 minuti |
| HighMemoryUsage | memoria > 500MB per 5 minuti |

In un sistema reale gli alert verrebbero mandati su Slack o via email tramite **Alertmanager**. Per questo progetto si vedono solo nella UI di Prometheus.

## 9. Generare traffico per la demo

Quando lo stack parte, Prometheus inizia da zero (è il comportamento corretto: misura solo il traffico vero). Per popolare velocemente le dashboard, c'è uno script Python.

> **Tutti i comandi di questa sezione vanno lanciati dalla root del progetto:**
> ```powershell
> cd "C:\Users\User\Documents\Progetto sentiment\sentiment-project"
> ```
> (sostituire il percorso con quello effettivo se il progetto è stato estratto altrove).

### Setup iniziale (solo la prima volta)

Lo script usa un virtual environment Python per non sporcare l'installazione di sistema. Va creato una sola volta:

```powershell
# Crea il virtual environment nella cartella venv/
python -m venv venv

# Attivalo
.\venv\Scripts\Activate.ps1

# Installa la dipendenza dello script
pip install requests
```

Quando il venv è attivo, il prompt cambia mostrando `(venv)` davanti, ad esempio:
```
(venv) PS C:\Users\User\Documents\Progetto sentiment\sentiment-project>
```

> **Se PowerShell blocca l'attivazione** con un errore tipo *"L'esecuzione di script è disabilitata"*, abilita l'esecuzione degli script una sola volta per il proprio utente:
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
> ```
> Confermare con `S`, poi riprovare ad attivare il venv.

### Uso normale (ogni volta che si apre un nuovo terminale)

Basta riattivare il venv:

```powershell
.\venv\Scripts\Activate.ps1
```

### Lanciare lo script

```powershell
python scripts\generate_traffic.py
```

Lo script fa 50 chiamate miste (positive, negative, neutral, qualche invalida) in circa 30 secondi. Dopo, su Grafana si vedono le dashboard popolate.

Per uno stress test che fa scattare gli alert:

```powershell
python scripts\generate_traffic.py --stress --duration 60 --workers 50
```

Genera 50 richieste in parallelo per 60 secondi. Dopo qualche istante CPU schizza in alto e gli alert su Prometheus passano in stato FIRING.

## 10. Comandi utili e manutenzione

### Vedere i log di un container

```powershell
docker logs sentiment-api-staging -f
docker logs jenkins -f
docker logs prometheus --tail 100
```

### Fermare tutto

```powershell
cd docker
docker compose --profile production down
```

### Ricostruire Jenkins (se modifichi `Dockerfile.jenkins`)

```powershell
cd docker
docker compose stop jenkins
docker compose rm -f jenkins
docker compose build jenkins
docker compose up -d jenkins
```

I dati di Jenkins (login, job, plugin) sono salvati nel volume `jenkins-data` e sopravvivono al rebuild.

### Reset completo (cancella anche dati di Jenkins, Grafana, metriche)

```powershell
cd docker
docker compose --profile production down -v
docker compose up -d
```

### Aggiornare il modello

1. Sostituisci `app/sentimentanalysismodel.pkl` con la nuova versione.
2. Lancia i test: `pytest tests/test_model.py -v`.
3. Fai commit e push. Jenkins farà il resto in automatico.

## 11. Problemi comuni

Questa sezione raccoglie i problemi che ho incontrato durante lo sviluppo e come li ho risolti.

**Docker dice `port is already allocated` all'avvio.**
Un'altra applicazione sta usando una delle porte (8000, 8001, 8090, 3000, 9090). Per scoprire chi:
```powershell
Get-Process -Id (Get-NetTCPConnection -LocalPort 8080).OwningProcess
```
Si può chiudere l'altro programma o cambiare la porta nel `docker-compose.yml`.

**Docker dice `failed to connect to the docker API`.**
Docker Desktop non è in esecuzione. Aprilo dal menu Start e aspetta che l'icona della balena nel system tray sia stabile.

**Il container `sentiment-api-staging` parte ma la porta 8000 non risponde.**
Succede se il container è stato creato durante un errore di rete. La colonna PORTS di `docker compose ps` mostra `8000/tcp` invece di `0.0.0.0:8000->8000/tcp`. Soluzione: forzare la ricreazione del container.
```powershell
docker compose up -d --force-recreate sentiment-api-staging
```

**PowerShell rifiuta di eseguire `Activate.ps1` con errore di sicurezza.**
La policy di esecuzione blocca gli script. Si abilita una sola volta per il proprio utente:
```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

**La pipeline Jenkins fallisce con `python3: not found` o `docker: not found`.**
Significa che Jenkins sta girando con l'immagine ufficiale invece di quella custom. Vedi la sezione *Ricostruire Jenkins* sopra.

**In Prometheus l'alert `SentimentAPIDown` è in stato FIRING.**
Probabilmente non hai avviato il profilo production. Prometheus prova a raggiungere anche `blue` e `green` ma sono spenti. Avviali con:
```powershell
docker compose --profile production up -d
```

**Git rifiuta il push con `non-fast-forward`.**
La repo remota ha commit che il locale non conosce.
```powershell
git pull origin main --allow-unrelated-histories
git push origin main
```

**Non ricordo la password admin di Jenkins.**
Se la perdi devi resettare il volume di Jenkins (perderai i job configurati):
```powershell
cd docker
docker compose stop jenkins
docker compose rm -f jenkins
docker volume rm docker_jenkins-data
docker compose up -d jenkins
```
Poi recuperi la nuova password iniziale come per il primo accesso:
```powershell
docker exec jenkins cat /var/jenkins_home/secrets/initialAdminPassword
```
