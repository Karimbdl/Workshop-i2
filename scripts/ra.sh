#!/bin/sh
# Lanceur d'exploitation de RESILIENCE-ALPHA pour Linux / macOS.
# Même rôle que scripts/ra.ps1 : Ansible et Compose tournent dans le poste de
# pilotage (ansible/Dockerfile), avec le dépôt monté au même chemin que sur l'hôte.
#
#   scripts/ra.sh deploy | verifier | desceller | arreter
#   scripts/ra.sh compose ps
set -eu

IMAGE="resilience-alpha/ops:1"
RACINE="$(cd "$(dirname "$0")/.." && pwd)"
CMD="${1:-aide}"
[ $# -gt 0 ] && shift

image() { docker build -t "$IMAGE" "$RACINE/ansible"; }

lancer() {
  docker image inspect "$IMAGE" >/dev/null 2>&1 || image
  TTY=""; [ -t 1 ] && TTY="-t"
  exec docker run --rm --init $TTY \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v "$RACINE:$RACINE" -w "$RACINE" \
    -e RA_ROOT="$RACINE" -e ANSIBLE_CONFIG="$RACINE/ansible/ansible.cfg" \
    --add-host host.docker.internal:host-gateway \
    "$IMAGE" "$@"
}

case "$CMD" in
  deploy)    lancer ansible-playbook "$RACINE/ansible/site.yml" "$@" ;;
  verifier)  lancer ansible-playbook "$RACINE/ansible/verifier.yml" "$@" ;;
  desceller) lancer ansible-playbook "$RACINE/ansible/desceller.yml" "$@" ;;
  arreter)   lancer ansible-playbook "$RACINE/ansible/arreter.yml" "$@" ;;
  sauvegarder|restaurer)
    if [ -z "${RA_BACKUP_PASSPHRASE:-}" ]; then
      printf "Phrase de passe de la sauvegarde : "; stty -echo; read -r RA_BACKUP_PASSPHRASE; stty echo; echo
      export RA_BACKUP_PASSPHRASE
    fi
    if [ "$CMD" = sauvegarder ]; then P=sauvegarder.yml; else P=restaurer.yml; fi
    lancer ansible-playbook "$RACINE/ansible/$P" "$@" ;;
  compose)   lancer docker compose -p resilience-alpha "$@" ;;
  ansible)   lancer "$@" ;;
  image)     image ;;
  *) echo "Usage : scripts/ra.sh deploy|verifier|desceller|arreter|sauvegarder|restaurer|compose ...|ansible ...|image" ;;
esac
