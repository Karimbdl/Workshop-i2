# Poste de pilotage Ansible de RESILIENCE-ALPHA.
#
# Ansible ne tourne pas nativement sous Windows : on l'embarque dans un conteneur
# qui pilote le moteur Docker de l'hôte (socket monté). Le même conteneur sert
# aussi pour les commandes Compose manuelles (scripts/ra.ps1 compose ...), pour que
# la stack soit toujours lancée avec les mêmes chemins et ne soit pas recréée
# à chaque changement d'outil.
FROM docker:29-cli

RUN apk add --no-cache \
        ansible-core \
        py3-requests \
        py3-cryptography \
        python3 \
        openssl \
        git \
        curl \
        tzdata \
 && ansible-galaxy collection install --no-cache 'community.docker:>=4.0.0' -p /usr/share/ansible/collections \
 && git config --system --add safe.directory '*'

# ANSIBLE_CONFIG est passé par le lanceur : un dossier monté depuis Windows est vu
# « accessible à tous en écriture » et Ansible ignorerait un ansible.cfg trouvé seul.
ENV TZ=Europe/Paris \
    ANSIBLE_FORCE_COLOR=1 \
    PYTHONDONTWRITEBYTECODE=1

ENTRYPOINT []
CMD ["ansible-playbook", "--version"]
