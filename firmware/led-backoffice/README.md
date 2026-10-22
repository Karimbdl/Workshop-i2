# LED bicolore du back-office — firmware ESP8266

Objet connecté de RESILIENCE-ALPHA. L'ESP8266 allume la LED bicolore selon l'état
reçu par MQTT (reconnaissance faciale et saisie du mot de passe au login).

## Câblage

| Broche ESP | vers | Patte LED |
|---|---|---|
| D1 | résistance 220 Ω | verte |
| D2 | résistance 220 Ω | rouge |
| G  | fil direct | commune (la plus longue) |

## Ouvrir et téléverser (CLion + PlatformIO)

1. Ouvre le dossier `firmware/led-backoffice` dans CLion (PlatformIO détecte `platformio.ini`).
2. Dans `src/main.cpp`, remplis la section **À CONFIGURER** :
   - `WIFI_SSID` / `WIFI_PASSWORD` : le point d'accès du groupe (`RESILIENCE-G<n>`).
   - `MQTT_HOST` : l'IP du PC Hôte (souvent `192.168.137.1`).
   - `MQTT_USER` / `MQTT_PASS` : laisse `""` tant que le broker n'a pas d'authentification.
3. Branche l'ESP en USB, puis **Upload** (l'icône PlatformIO, ou `pio run -t upload`).
4. Ouvre le **moniteur série** (115200 bauds) pour voir les messages.

## Vérifier sans MQTT

Au démarrage, la LED fait un **autotest** : vert ~0,7 s, puis rouge ~0,7 s, puis éteinte.
Si tu vois ça, le câblage est bon. Si les couleurs sont inversées, échange `PIN_ROUGE`
et `PIN_VERT` dans `main.cpp`.

## Tester les états à la main

Une fois le broker MQTT en place, depuis le PC Hôte :

```bash
mosquitto_pub -h 192.168.137.1 -t resilience/backoffice/led -m vert_clignotant
mosquitto_pub -h 192.168.137.1 -t resilience/backoffice/led -m vert_fixe
mosquitto_pub -h 192.168.137.1 -t resilience/backoffice/led -m rouge_fixe
mosquitto_pub -h 192.168.137.1 -t resilience/backoffice/led -m rouge_clignote
mosquitto_pub -h 192.168.137.1 -t resilience/backoffice/led -m off
```

## États reconnus (messages MQTT)

| Message | Effet |
|---|---|
| `off` / `eteinte` | LED éteinte |
| `vert_clignotant` | vert clignotant (personne reconnue) |
| `vert_fixe` | vert fixe 30 s (mot de passe validé) |
| `rouge_fixe` | rouge fixe 30 s (visage non reconnu) |
| `rouge_clignote` | rouge clignote 10 fois (mot de passe faux) |

L'ESP publie aussi son état sur `resilience/backoffice/led/status` (`en_ligne` /
`hors_ligne` via le *Last Will* MQTT).
