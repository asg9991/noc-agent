#!/usr/bin/env bash
#
# backup-estado.sh - Backup + restore del estado del agente noc-agent.
#
# Estado: audit.jsonl, watch.db, outbox.jsonl y su cooldown — datos del
# cliente en claro, sin backup hasta P14. Sigue el esquema de backups de
# ops (scripts/engram-backup.sh, zbx-client-backup.sh): snapshot WAL-safe
# del SQLite -> cifrado (age, fallback openssl) -> staging local con
# rotación --keep -> upload al offsite vía google-agent CLI
# (Drive: backups/noc-agent/).
#
# Lab: el offsite se SIMULA con --dry-run (todo local) o --output DIR.
# Prod: el upload real es el camino allanado; NO probado en producción.
# La passphrase NUNCA se guarda en archivo: env NOC_BACKUP_PASSPHRASE
# (o --passphrase-env NAME) o prompt interactivo. Subir en claro está
# prohibido: el upload exige cifrado.
#
# Usage:
#   ./scripts/backup-estado.sh [--dry-run] [--output DIR] [--keep N]
#                               [--state-dir DIR] [--passphrase-env NAME]
#   ./scripts/backup-estado.sh --restore ARCHIVO [--state-dir DIR] [--force]
#                               [--passphrase-env NAME]
#
# Examples:
#   ./scripts/backup-estado.sh --dry-run --output /tmp/noc-bkp-test
#   NOC_BACKUP_PASSPHRASE=secret ./scripts/backup-estado.sh --dry-run
#   ./scripts/backup-estado.sh --restore ~/backups/noc-agent-estado/x.tar.gz.age
#
set -euo pipefail

# --- Defaults (override via flags or env) ---
STATE_DIR="${NOC_STATE_DIR:-.}"
STAGING_DIR="${NOC_BACKUP_DIR:-$HOME/backups/noc-agent-estado}"
KEEP="${NOC_BACKUP_KEEP:-3}"
PASSPHRASE_ENV="NOC_BACKUP_PASSPHRASE"
DRY_RUN=0
OUTPUT_DIR=""
RESTORE=""
FORCE=0

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_DIR="${GOOGLE_AGENT_DIR:-$HOME/projects/ops/google-agent}"
AGENT_PY="${AGENT_DIR}/.venv/bin/python"

ARTIFACTS=(audit.jsonl watch.db outbox.jsonl outbox.jsonl.cooldown.json)

usage() {
  sed -n '2,/^set -euo/{/^set -euo/d;p}' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

log() { printf '%s %s\n' "$(date '+%F %T')" "$*"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --output) OUTPUT_DIR="${2:?--output needs a directory}"; shift 2 ;;
    --keep) KEEP="${2:?--keep needs N}"; shift 2 ;;
    --state-dir) STATE_DIR="${2:?--state-dir needs a directory}"; shift 2 ;;
    --restore) RESTORE="${2:?--restore needs an archive}"; shift 2 ;;
    --force) FORCE=1; shift ;;
    --passphrase-env) PASSPHRASE_ENV="${2:?--passphrase-env needs a name}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage >&2; exit 2 ;;
  esac
done

# --- Passphrase (env o prompt; jamás en archivo) ---
PASSPHRASE="${!PASSPHRASE_ENV:-}"
FROM_ENV=1
if [[ -z "${PASSPHRASE}" && -t 0 && -z "${RESTORE}" ]]; then
  read -rsp "Backup passphrase (enter = sin cifrar, solo lab): " PASSPHRASE; echo
  FROM_ENV=0
fi

# El upload a offsite exige cifrado: estado en claro jamás sale del host.
if [[ "${DRY_RUN}" -eq 0 && -z "${RESTORE}" && -z "${PASSPHRASE}" ]]; then
  echo "ERROR: el upload al offsite exige cifrado; defina ${PASSPHRASE_ENV}" \
       "(o use --dry-run para simular el offsite en lab)" >&2
  exit 1
fi

WORK=""
cleanup() { [[ -n "${WORK}" ]] && rm -rf "${WORK}"; }
trap cleanup EXIT

# ============================ RESTORE ====================================
if [[ -n "${RESTORE}" ]]; then
  [[ -f "${RESTORE}" ]] || { echo "ERROR: archivo no encontrado: ${RESTORE}" >&2; exit 1; }
  WORK="$(mktemp -d "${TMPDIR:-/tmp}/noc-agent-restore.XXXXXX")"
  PLAIN="${RESTORE}"
  case "${RESTORE}" in
    *.age)
      [[ -n "${PASSPHRASE}" ]] || { echo "ERROR: archivo cifrado: defina ${PASSPHRASE_ENV}" >&2; exit 1; }
      PLAIN="${WORK}/estado.tar.gz"
      if [[ "${FROM_ENV}" -eq 1 ]]; then
        # age lee la passphrase de /dev/tty: lo manejamos por pty con script(1),
        # sin eco en logs y sin pasarla por argv (mismo patrón que engram-backup).
        command -v script >/dev/null 2>&1 || { echo "ERROR: 'script' (util-linux) requerido" >&2; exit 1; }
        printf '%s\n' "${PASSPHRASE}" | script -qec "age --decrypt -o '${PLAIN}' '${RESTORE}'" /dev/null >/dev/null
      else
        age --decrypt -o "${PLAIN}" "${RESTORE}"
      fi
      ;;
    *.enc)
      [[ -n "${PASSPHRASE}" ]] || { echo "ERROR: archivo cifrado: defina ${PASSPHRASE_ENV}" >&2; exit 1; }
      PLAIN="${WORK}/estado.tar.gz"
      export _NOC_BACKUP_TMP_PASS="${PASSPHRASE}"
      openssl enc -d -aes-256-cbc -pbkdf2 -in "${RESTORE}" -out "${PLAIN}" -pass env:_NOC_BACKUP_TMP_PASS
      unset _NOC_BACKUP_TMP_PASS
      ;;
  esac
  unset PASSPHRASE
  EXTRACT="${WORK}/x"
  mkdir -p "${EXTRACT}"
  tar -xzf "${PLAIN}" -C "${EXTRACT}"
  (cd "${EXTRACT}" && sha256sum -c sha256sums.txt >/dev/null) \
    || { echo "ERROR: sha256 del manifest no coincide — artefacto tampered o corrupto" >&2; exit 1; }
  mkdir -p "${STATE_DIR}"
  for f in "${ARTIFACTS[@]}"; do
    if [[ -f "${EXTRACT}/${f}" && -f "${STATE_DIR}/${f}" && "${FORCE}" -ne 1 ]]; then
      echo "ERROR: ${STATE_DIR}/${f} existe; use --force para pisar" >&2
      exit 1
    fi
  done
  for f in "${ARTIFACTS[@]}"; do
    if [[ -f "${EXTRACT}/${f}" ]]; then
      cp -- "${EXTRACT}/${f}" "${STATE_DIR}/${f}"
      log "  restaurado: ${f}"
    fi
  done
  echo "Restore OK -> ${STATE_DIR}"
  exit 0
fi

# ============================ BACKUP =====================================
echo "== noc-agent estado backup =="
echo "Step 1/6: collect de ${STATE_DIR}"
FOUND=()
for f in "${ARTIFACTS[@]}"; do
  [[ -f "${STATE_DIR}/${f}" ]] && FOUND+=("$f")
done
[[ ${#FOUND[@]} -gt 0 ]] || { echo "ERROR: sin artefactos de estado en ${STATE_DIR}" >&2; exit 1; }
for f in "${FOUND[@]}"; do
  echo "  - ${f} ($(du -h "${STATE_DIR}/${f}" | cut -f1))"
done

WORK="$(mktemp -d "${TMPDIR:-/tmp}/noc-agent-backup.XXXXXX")"
STATE="${WORK}/state"
mkdir -p "${STATE}"

for f in "${FOUND[@]}"; do
  if [[ "${f}" == "watch.db" ]]; then
    # Snapshot WAL-safe (mismo patrón que engram-backup.sh).
    if command -v sqlite3 >/dev/null 2>&1; then
      sqlite3 "${STATE_DIR}/watch.db" ".backup '${STATE}/watch.db'"
    elif python3 -c 'import sqlite3' 2>/dev/null; then
      python3 - "${STATE_DIR}/watch.db" "${STATE}/watch.db" <<'PYEOF'
import sqlite3, sys
src = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
dst = sqlite3.connect(sys.argv[2])
with dst:
    src.backup(dst)
dst.close(); src.close()
PYEOF
    else
      echo "  WARNING: sin sqlite3/python3: cp simple NO es WAL-safe" >&2
      cp -- "${STATE_DIR}/watch.db" "${STATE}/watch.db"
    fi
  else
    cp -- "${STATE_DIR}/${f}" "${STATE}/${f}"
  fi
done

echo "Step 2/6: manifest"
{
  echo "date: $(date -u +%FT%TZ)"
  echo "host: $(hostname)"
  echo "files:"
  for f in "${FOUND[@]}"; do
    echo "  - ${f} ($(stat -c%s "${STATE}/${f}") bytes)"
  done
} > "${STATE}/MANIFEST.txt"
(cd "${STATE}" && sha256sum "${FOUND[@]}" > sha256sums.txt)

echo "Step 3/6: archive"
DATE_TAG="$(date +%Y%m%d-%H%M%S)"
BASENAME="noc-agent-estado-${DATE_TAG}"
ARCHIVE="${WORK}/${BASENAME}.tar.gz"
tar -czf "${ARCHIVE}" -C "${STATE}" "${FOUND[@]}" MANIFEST.txt sha256sums.txt

echo "Step 4/6: encrypt"
ENCRYPTED="${ARCHIVE}"
ENCRYPT_TOOL="none (plain tar.gz, solo lab)"
if [[ -n "${PASSPHRASE}" ]]; then
  if command -v age >/dev/null 2>&1; then
    ENCRYPTED="${WORK}/${BASENAME}.tar.gz.age"
    if [[ "${FROM_ENV}" -eq 1 ]]; then
      command -v script >/dev/null 2>&1 || { echo "ERROR: 'script' (util-linux) requerido para cifrado no interactivo" >&2; exit 1; }
      printf '%s\n%s\n' "${PASSPHRASE}" "${PASSPHRASE}" | script -qec "age --encrypt --passphrase -o '${ENCRYPTED}' '${ARCHIVE}'" /dev/null >/dev/null
    else
      age --encrypt --passphrase -o "${ENCRYPTED}" "${ARCHIVE}"
    fi
    ENCRYPT_TOOL="age --passphrase (symmetric)"
  else
    echo "  NOTE: 'age' no encontrado, fallback openssl enc -aes-256-cbc -pbkdf2." >&2
    ENCRYPTED="${WORK}/${BASENAME}.tar.gz.enc"
    export _NOC_BACKUP_TMP_PASS="${PASSPHRASE}"
    openssl enc -aes-256-cbc -pbkdf2 -salt -in "${ARCHIVE}" -out "${ENCRYPTED}" -pass env:_NOC_BACKUP_TMP_PASS
    unset _NOC_BACKUP_TMP_PASS
    ENCRYPT_TOOL="openssl enc -aes-256-cbc -pbkdf2"
  fi
else
  echo "  WARNING: sin passphrase — artefacto en CLARO. Válido solo para lab;" >&2
  echo "           el offsite de prod exige cifrado (el upload lo rechaza)." >&2
fi
unset PASSPHRASE
echo "  encryption: ${ENCRYPT_TOOL}"

echo "Step 5/6: staging + rotation"
mkdir -p "${STAGING_DIR}"
TARGET="${STAGING_DIR}/$(basename "${ENCRYPTED}")"
N=1
while [[ -e "${TARGET}" ]]; do
  # colisión por segundo: sufijo antes de la extensión para que el restore
  # siga reconociendo el formato por sufijo
  case "$(basename "${ENCRYPTED}")" in
    *.tar.gz.age) TARGET="${STAGING_DIR}/${BASENAME}-${N}.tar.gz.age" ;;
    *.tar.gz.enc) TARGET="${STAGING_DIR}/${BASENAME}-${N}.tar.gz.enc" ;;
    *)            TARGET="${STAGING_DIR}/${BASENAME}-${N}.tar.gz" ;;
  esac
  N=$((N + 1))
done
cp -- "${ENCRYPTED}" "${TARGET}"
log "  staging: ${TARGET}"
if [[ "${KEEP}" -gt 0 ]]; then
  mapfile -t ALL < <(ls -1 "${STAGING_DIR}"/noc-agent-estado-* 2>/dev/null | sort || true)
  COUNT=${#ALL[@]}
  if [[ "${COUNT}" -gt "${KEEP}" ]]; then
    for f in "${ALL[@]:0:COUNT-KEEP}"; do
      rm -f -- "$f"
      log "  rotation: removido $(basename "$f")"
    done
  fi
fi

if [[ -n "${OUTPUT_DIR}" ]]; then
  mkdir -p "${OUTPUT_DIR}"
  cp -- "${TARGET}" "${OUTPUT_DIR}/"
  log "  copia local (offsite simulado): ${OUTPUT_DIR}/$(basename "${TARGET}")"
fi

echo "Step 6/6: upload al offsite"
if [[ "${DRY_RUN}" -eq 1 ]]; then
  echo "  dry-run: upload omitido (offsite simulado)."
else
  [[ -x "${AGENT_PY}" ]] || { echo "ERROR: google-agent python no encontrado en ${AGENT_PY}" >&2; exit 1; }
  echo "  destino: backups/noc-agent/$(basename "${TARGET}")"
  (cd "${AGENT_DIR}" && ./.venv/bin/python -m google_agent.cli upload "${TARGET}" "backups/noc-agent/$(basename "${TARGET}")")
  echo "  upload done."
fi

echo "Done."
