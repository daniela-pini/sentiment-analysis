#!/usr/bin/env python3
"""
generate_traffic.py — On-demand traffic generator for the Sentiment Analysis API.

Strumento di supporto a sviluppo / demo / load test. Non sostituisce in alcun
modo il traffico reale: lo stack monitora di default ESCLUSIVAMENTE il traffico
generato dai client veri (Prometheus parte sempre da zero ad ogni `docker
compose up`). Questo script serve a tre scopi:

  1. DEMO            — popolare velocemente le dashboard Grafana per dimostrare
                       che il monitoring funziona, senza dover fare manualmente
                       decine di POST /predict.
  2. SMOKE TEST      — verificare che l'API risponda correttamente dopo un
                       deploy.
  3. STRESS TEST     — generare un carico elevato per:
                         - verificare la latenza p95 sotto pressione
                         - far scattare alert (CPU > 90%) e validarli
                         - testare la resilienza del servizio
                       (NB: non è un load tester di livello produzione come
                        Locust o k6, ma è sufficiente per uso didattico.)

Esempi:

    # Modalità "demo" (50 richieste miste in ~30s, sequenziali)
    python scripts/generate_traffic.py

    # Volume custom
    python scripts/generate_traffic.py --requests 200

    # Target diverso (es. ambiente di produzione)
    python scripts/generate_traffic.py --url http://localhost:8001

    # STRESS test (carico parallelo per 60s, ~50 richieste/s)
    python scripts/generate_traffic.py --stress --duration 60 --workers 50

Requisiti: pip install requests
"""

import argparse
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from statistics import mean, median

try:
    import requests
except ImportError:
    print("ERRORE: serve la libreria 'requests'. Installa con: pip install requests")
    sys.exit(1)


# ─── Dataset di recensioni realistiche ───────────────────────────────────────
REVIEWS_POSITIVE = [
    "I love this product so much, it is fantastic!",
    "Best purchase I made this year, highly recommend.",
    "Excellent quality, exceeded my expectations.",
    "Amazing product, works perfectly out of the box.",
    "Great value for money, very satisfied with my order.",
    "Outstanding service and the product is wonderful.",
    "Perfect, exactly what I needed, very happy.",
    "Top quality, will definitely buy again.",
    "Fantastic, beats every other brand I've tried.",
    "Really impressive, much better than expected.",
]

REVIEWS_NEGATIVE = [
    "Terrible product, complete waste of money.",
    "Worst purchase ever, broke after one week.",
    "Very disappointed, does not work as advertised.",
    "Awful quality, do not buy this.",
    "Horrible experience, the item arrived defective.",
    "Total junk, save your money.",
    "Extremely poor quality, very frustrated.",
    "Bad product, bad service, avoid at all costs.",
    "Broken on arrival, customer support unhelpful.",
    "Don't waste your money on this garbage.",
]

REVIEWS_NEUTRAL = [
    "The product arrived on time and was as described.",
    "It works as expected, nothing special.",
    "Average quality for the price.",
    "Decent item, neither good nor bad.",
    "Standard product, does the job.",
    "Mediocre but functional.",
    "Okay, meets basic requirements.",
    "It is fine, serves its purpose.",
]

# Un paio di input invalidi per generare 422 e popolare il contatore errori
INVALID_PAYLOADS = [
    {"review": ""},
    {"review": "   "},
    {"wrong_field": "this should fail"},
]


def pick_payload(distribution: dict) -> dict:
    """Sceglie un payload pesato sulla distribuzione richiesta."""
    r = random.random()
    cum = 0.0
    for category, weight in distribution.items():
        cum += weight
        if r <= cum:
            if category == "positive":
                return {"review": random.choice(REVIEWS_POSITIVE)}
            if category == "negative":
                return {"review": random.choice(REVIEWS_NEGATIVE)}
            if category == "neutral":
                return {"review": random.choice(REVIEWS_NEUTRAL)}
            if category == "invalid":
                return random.choice(INVALID_PAYLOADS)
    return {"review": random.choice(REVIEWS_POSITIVE)}  # fallback


def send_one(url: str, payload: dict, timeout: float = 10.0) -> dict:
    """Invia una richiesta e restituisce il risultato."""
    start = time.time()
    try:
        r = requests.post(f"{url}/predict", json=payload, timeout=timeout)
        latency = time.time() - start
        return {
            "ok": r.status_code == 200,
            "status": r.status_code,
            "latency": latency,
            "sentiment": r.json().get("sentiment") if r.status_code == 200 else None,
        }
    except requests.RequestException as e:
        return {"ok": False, "status": None, "latency": time.time() - start, "error": str(e)}


def run_demo(url: str, n_requests: int) -> list:
    """Modalità demo: richieste sequenziali distribuite nel tempo."""
    print(f"\n→ Demo mode: {n_requests} richieste sequenziali verso {url}")
    print(f"  Distribuzione: 50% positive, 30% negative, 15% neutral, 5% invalid\n")
    distribution = {"positive": 0.50, "negative": 0.30, "neutral": 0.15, "invalid": 0.05}
    results = []
    delay = 30.0 / n_requests  # spalmare su ~30 secondi
    for i in range(n_requests):
        payload = pick_payload(distribution)
        result = send_one(url, payload)
        results.append(result)
        # Progress inline
        status_char = "✓" if result["ok"] else ("·" if result["status"] == 422 else "✗")
        print(f"  [{i+1:>3}/{n_requests}] {status_char} HTTP {result['status']} "
              f"latency={result['latency']*1000:.0f}ms  "
              f"{'sentiment='+result['sentiment'] if result.get('sentiment') else ''}")
        time.sleep(delay)
    return results


def run_stress(url: str, duration: int, workers: int) -> list:
    """Modalità stress: richieste in parallelo per un periodo definito."""
    print(f"\n→ Stress mode: {workers} workers paralleli per {duration}s verso {url}")
    print("  Distribuzione: 100% richieste valide (no 422)\n")
    distribution = {"positive": 0.50, "negative": 0.35, "neutral": 0.15, "invalid": 0.0}
    results = []
    end_time = time.time() + duration
    sent = 0

    def worker_task():
        nonlocal sent
        while time.time() < end_time:
            payload = pick_payload(distribution)
            r = send_one(url, payload)
            results.append(r)
            sent += 1

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(worker_task) for _ in range(workers)]
        # Progress reporter
        start = time.time()
        while time.time() < end_time:
            time.sleep(2)
            elapsed = time.time() - start
            rps = sent / elapsed if elapsed > 0 else 0
            print(f"  [{elapsed:>4.0f}s] richieste totali: {sent}  ({rps:.1f} req/s)")
        for f in as_completed(futures):
            f.result()

    return results


def print_summary(results: list, label: str) -> None:
    """Stampa statistiche aggregate."""
    if not results:
        print("Nessuna richiesta completata.")
        return

    total = len(results)
    ok = sum(1 for r in results if r["ok"])
    errors_422 = sum(1 for r in results if r["status"] == 422)
    other_errors = total - ok - errors_422
    latencies = [r["latency"] for r in results if r["latency"] is not None]

    print("\n" + "═" * 60)
    print(f"  RIEPILOGO — {label}")
    print("═" * 60)
    print(f"  Totale richieste:      {total}")
    print(f"  Successi (200):        {ok}  ({ok/total*100:.1f}%)")
    print(f"  Validation errors:     {errors_422}  ({errors_422/total*100:.1f}%)  ← attesi")
    print(f"  Altri errori:          {other_errors}")
    if latencies:
        latencies.sort()
        p50 = median(latencies)
        p95 = latencies[int(len(latencies) * 0.95)]
        p99 = latencies[int(len(latencies) * 0.99)]
        print(f"  Latency mean:          {mean(latencies)*1000:.1f}ms")
        print(f"  Latency p50:           {p50*1000:.1f}ms")
        print(f"  Latency p95:           {p95*1000:.1f}ms")
        print(f"  Latency p99:           {p99*1000:.1f}ms")
    print("═" * 60)
    print("\n→ Apri Grafana per vedere le metriche: http://localhost:3000")
    print("  (Dashboards → Sentiment Analysis → Sentiment Analysis API - Monitoring)\n")


def main():
    parser = argparse.ArgumentParser(
        description="Generatore di traffico per la Sentiment Analysis API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--url", default="http://localhost:8000",
                        help="URL base dell'API (default: %(default)s)")
    parser.add_argument("--requests", type=int, default=50,
                        help="Numero di richieste in modalità demo (default: %(default)s)")
    parser.add_argument("--stress", action="store_true",
                        help="Attiva modalità STRESS (richieste in parallelo)")
    parser.add_argument("--duration", type=int, default=60,
                        help="Durata in secondi della modalità stress (default: %(default)s)")
    parser.add_argument("--workers", type=int, default=20,
                        help="Numero di worker paralleli in modalità stress (default: %(default)s)")
    args = parser.parse_args()

    # Verifica preliminare: l'API è raggiungibile?
    try:
        r = requests.get(f"{args.url}/health", timeout=5)
        if r.status_code != 200:
            print(f"ERRORE: l'API a {args.url} non risponde correttamente (HTTP {r.status_code})")
            sys.exit(1)
    except requests.RequestException as e:
        print(f"ERRORE: impossibile raggiungere l'API a {args.url}")
        print(f"  Dettagli: {e}")
        print(f"  Verifica che lo stack sia avviato: docker compose ps")
        sys.exit(1)

    if args.stress:
        results = run_stress(args.url, args.duration, args.workers)
        print_summary(results, "STRESS TEST")
    else:
        results = run_demo(args.url, args.requests)
        print_summary(results, "DEMO")


if __name__ == "__main__":
    main()
