#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────
# blue-green-switch.sh
#
# Cambia il colore "attivo" in produzione modificando la config nginx
# DIRETTAMENTE DENTRO il container nginx-prod (via docker exec) e
# ricaricando nginx.
#
# Vantaggio rispetto a modificare il file dal filesystem locale: funziona
# uguale sia che lo script venga chiamato dal PC sia da dentro Jenkins
# (che gira in un container e non vede gli stessi path del PC host).
#
# Uso:
#   ./blue-green-switch.sh blue     # rende blue il colore attivo
#   ./blue-green-switch.sh green    # rende green il colore attivo
# ──────────────────────────────────────────────────────────────────────────
set -euo pipefail

TARGET_COLOR="${1:-}"

if [[ "$TARGET_COLOR" != "blue" && "$TARGET_COLOR" != "green" ]]; then
    echo "ERRORE: specificare 'blue' o 'green' come argomento" >&2
    exit 1
fi

if [[ "$TARGET_COLOR" == "blue" ]]; then
    OTHER_COLOR="green"
else
    OTHER_COLOR="blue"
fi

# Verifica che nginx-prod sia in esecuzione
if ! docker ps --format '{{.Names}}' | grep -q '^nginx-prod$'; then
    echo "ERRORE: nginx-prod non è in esecuzione." >&2
    echo "Avviare prima la produzione: docker compose --profile production up -d" >&2
    exit 1
fi

echo "→ Switch active color: $OTHER_COLOR → $TARGET_COLOR"

# Modifica la config nginx DENTRO al container e fa il reload.
# Tutto via docker exec, niente dipendenze dal filesystem locale.
docker exec nginx-prod sh -c "
    sed -i 's|server sentiment-api-${OTHER_COLOR}:8000;|# server sentiment-api-${OTHER_COLOR}:8000;|' /etc/nginx/nginx.conf
    sed -i 's|# server sentiment-api-${TARGET_COLOR}:8000;|server sentiment-api-${TARGET_COLOR}:8000;|' /etc/nginx/nginx.conf
    sed -i 's|# ACTIVE: [a-z]*|# ACTIVE: ${TARGET_COLOR}|' /etc/nginx/nginx.conf
    sed -i 's|# INACTIVE: [a-z]*|# INACTIVE: ${OTHER_COLOR}|' /etc/nginx/nginx.conf
"

docker exec nginx-prod nginx -s reload

echo "✓ Switch completato. Colore attivo: $TARGET_COLOR"
echo "  Per rollback rapido: ./blue-green-switch.sh $OTHER_COLOR"
