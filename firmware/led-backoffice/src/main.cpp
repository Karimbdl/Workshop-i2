// RESILIENCE-ALPHA — firmware de la LED bicolore du back-office.
//
// Rôle : l'ESP8266 se connecte au Wi-Fi, s'abonne au canal MQTT de la LED, et
// allume la LED selon l'état reçu. Les 5 états viennent de la consigne :
//   - éteinte               (au repos)
//   - vert clignotant       (personne reconnue, pendant la saisie du mot de passe)
//   - vert fixe 30 s        (mot de passe validé)
//   - rouge fixe 30 s       (visage non reconnu)
//   - rouge clignote 10x    (mot de passe faux)
//
// Câblage (LED à cathode commune, la patte commune va à G) :
//   D1 ── résistance 220 Ω ── patte ROUGE
//   D2 ── résistance 220 Ω ── patte VERTE
//   G  ───────────────────── patte COMMUNE

#include <Arduino.h>
#include <ESP8266WiFi.h>
#include <PubSubClient.h>

// ============================ À CONFIGURER ============================
// Wi-Fi du point d'accès du groupe (à remplir le jour J).
static const char* WIFI_SSID     = "RESILIENCE-G1";
static const char* WIFI_PASSWORD = "A_REMPLIR";

// Broker MQTT = le PC Hôte, sur le point d'accès RESILIENCE-G1.
static const char* MQTT_HOST = "192.168.137.1";
static const uint16_t MQTT_PORT = 1883;
static const char* MQTT_USER = "";   // laisser "" si le broker n'a pas d'authentification
static const char* MQTT_PASS = "";

// Canaux MQTT.
static const char* TOPIC_LED    = "resilience/backoffice/led";         // on reçoit les états ici
static const char* TOPIC_STATUS = "resilience/backoffice/led/status";  // on publie en ligne / hors ligne

// Broches de la LED. Si les couleurs sont inversées une fois branché,
// il suffit d'échanger ces deux lignes.
static const uint8_t PIN_ROUGE = D1;
static const uint8_t PIN_VERT  = D2;

// Durées (millisecondes).
static const unsigned long DUREE_FIXE       = 30000;  // vert/rouge fixe : 30 s
static const unsigned long PERIODE_VERT     = 400;    // demi-période du clignotement vert
static const unsigned long PERIODE_ROUGE    = 250;    // demi-période du clignotement rouge
static const uint8_t       NB_CLIGN_ROUGE   = 10;     // rouge clignote 10 fois
// =====================================================================

enum LedState { ETEINTE, VERT_CLIGNOTANT, VERT_FIXE, ROUGE_FIXE, ROUGE_CLIGNOTE };

WiFiClient espClient;
PubSubClient mqtt(espClient);

LedState etat = ETEINTE;
unsigned long etatDebut = 0;      // millis() au début de l'état courant
unsigned long dernierToggle = 0;  // pour cadencer les clignotements
bool phaseAllumee = false;        // LED allumée ou non pendant un clignotement
uint8_t clignEffectues = 0;       // nombre de clignotements rouges déjà faits
unsigned long dernierEssaiMqtt = 0;
unsigned long dernierWifiLog = 0;
bool wifiEtaitConnecte = false;

// Cathode commune : une couleur est allumée quand sa broche est à HIGH.
void setLed(bool rouge, bool vert) {
  digitalWrite(PIN_ROUGE, rouge ? HIGH : LOW);
  digitalWrite(PIN_VERT,  vert  ? HIGH : LOW);
}

void changerEtat(LedState nouvel) {
  etat = nouvel;
  etatDebut = millis();
  dernierToggle = etatDebut;
  clignEffectues = 0;
  switch (etat) {
    case ETEINTE:         setLed(false, false); phaseAllumee = false; break;
    case VERT_FIXE:       setLed(false, true);  phaseAllumee = true;  break;
    case ROUGE_FIXE:      setLed(true,  false); phaseAllumee = true;  break;
    case VERT_CLIGNOTANT: setLed(false, true);  phaseAllumee = true;  break;
    case ROUGE_CLIGNOTE:  setLed(true,  false); phaseAllumee = true;  break;
  }
}

// Fait vivre l'état courant sans jamais bloquer (clignotements, extinctions).
void majLed() {
  unsigned long maintenant = millis();
  switch (etat) {
    case VERT_CLIGNOTANT:
      if (maintenant - dernierToggle >= PERIODE_VERT) {
        dernierToggle = maintenant;
        phaseAllumee = !phaseAllumee;
        setLed(false, phaseAllumee);
      }
      break;

    case VERT_FIXE:
    case ROUGE_FIXE:
      if (maintenant - etatDebut >= DUREE_FIXE) changerEtat(ETEINTE);
      break;

    case ROUGE_CLIGNOTE:
      if (maintenant - dernierToggle >= PERIODE_ROUGE) {
        dernierToggle = maintenant;
        phaseAllumee = !phaseAllumee;
        setLed(phaseAllumee, false);
        if (!phaseAllumee) {                 // une extinction = un clignotement terminé
          clignEffectues++;
          if (clignEffectues >= NB_CLIGN_ROUGE) changerEtat(ETEINTE);
        }
      }
      break;

    case ETEINTE:
    default:
      break;
  }
}

void appliquerCommande(const String& cmd) {
  if      (cmd == "off" || cmd == "eteinte") changerEtat(ETEINTE);
  else if (cmd == "vert_clignotant")         changerEtat(VERT_CLIGNOTANT);
  else if (cmd == "vert_fixe")               changerEtat(VERT_FIXE);
  else if (cmd == "rouge_fixe")              changerEtat(ROUGE_FIXE);
  else if (cmd == "rouge_clignote")          changerEtat(ROUGE_CLIGNOTE);
  // commande inconnue : ignorée
}

void onMessage(char* topic, byte* payload, unsigned int length) {
  String cmd;
  for (unsigned int i = 0; i < length; i++) cmd += (char)payload[i];
  cmd.trim();
  cmd.toLowerCase();
  Serial.println("MQTT reçu : " + cmd);
  appliquerCommande(cmd);
}

// Petit test visuel au démarrage : prouve que la LED et le câblage fonctionnent,
// même sans Wi-Fi ni MQTT. Vert, puis rouge, puis éteint.
void autotest() {
  setLed(false, true);  delay(700);
  setLed(true,  false); delay(700);
  setLed(false, false);
}

bool essayerMqtt() {
  String clientId = "esp8266-led-" + String(ESP.getChipId(), HEX);
  // Last Will : si l'ESP se déconnecte brutalement, le broker publie "hors_ligne".
  bool ok = (strlen(MQTT_USER) > 0)
    ? mqtt.connect(clientId.c_str(), MQTT_USER, MQTT_PASS, TOPIC_STATUS, 0, true, "hors_ligne")
    : mqtt.connect(clientId.c_str(), TOPIC_STATUS, 0, true, "hors_ligne");
  if (ok) {
    Serial.println("MQTT connecté");
    mqtt.publish(TOPIC_STATUS, "en_ligne", true);
    mqtt.subscribe(TOPIC_LED);
  } else {
    Serial.print("MQTT échec (code ");
    Serial.print(mqtt.state());
    Serial.println(")");
  }
  return ok;
}

void setup() {
  Serial.begin(115200);
  delay(50);
  pinMode(PIN_ROUGE, OUTPUT);
  pinMode(PIN_VERT, OUTPUT);
  setLed(false, false);

  autotest();  // confirmation visuelle immédiate

  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Connexion Wi-Fi à ");
  Serial.println(WIFI_SSID);

  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setCallback(onMessage);
}

void loop() {
  majLed();  // la LED reste fluide quoi qu'il arrive

  if (WiFi.status() == WL_CONNECTED) {
    if (!wifiEtaitConnecte) {
      wifiEtaitConnecte = true;
      Serial.print("Wi-Fi connecte, IP ");
      Serial.println(WiFi.localIP());
    }
    if (!mqtt.connected()) {
      if (millis() - dernierEssaiMqtt > 2000) {
        dernierEssaiMqtt = millis();
        essayerMqtt();
      }
    } else {
      mqtt.loop();
    }
  } else {
    wifiEtaitConnecte = false;
    // Diagnostic : code d'état WiFi (1=SSID introuvable, 4=mauvais mot de passe, 6=en cours).
    if (millis() - dernierWifiLog > 2000) {
      dernierWifiLog = millis();
      Serial.print("Wi-Fi status=");
      Serial.println(WiFi.status());
    }
  }
}
