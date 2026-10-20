"""Génère les tableaux de bord Grafana (infra/grafana/dashboards/*.json).

Usage : python scripts/build_dashboards.py
Grafana relit les fichiers automatiquement (provisionnement), sans redémarrage.
"""

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "infra" / "grafana" / "dashboards"
PROM = {"type": "prometheus", "uid": "prometheus"}
LOKI = {"type": "loki", "uid": "loki"}

GREEN, RED, ORANGE, BLUE = "green", "red", "orange", "blue"


class Layout:
    """Place les panneaux de gauche à droite sur une grille de 24 colonnes."""

    def __init__(self) -> None:
        self.x = self.y = self.row_h = 0
        self.panels: list[dict] = []

    def add(self, panel: dict, w: int, h: int) -> None:
        if self.x + w > 24:
            self.newline()
        panel["id"] = len(self.panels) + 1
        panel["gridPos"] = {"x": self.x, "y": self.y, "w": w, "h": h}
        self.panels.append(panel)
        self.x += w
        self.row_h = max(self.row_h, h)

    def newline(self) -> None:
        self.y += self.row_h
        self.x = self.row_h = 0

    def row(self, title: str) -> None:
        if self.x:
            self.newline()
        self.add({"type": "row", "title": title, "collapsed": False, "panels": []}, 24, 1)
        self.newline()


def prom(expr: str, legend: str = "", instant: bool = False, fmt: str = "time_series") -> dict:
    return {
        "datasource": PROM, "expr": expr, "legendFormat": legend, "refId": "A",
        "instant": instant, "range": not instant, "format": fmt,
    }


def loki(expr: str, kind: str = "range") -> dict:
    return {"datasource": LOKI, "expr": expr, "refId": "A", "queryType": kind}


def thresholds(*steps) -> dict:
    return {"mode": "absolute", "steps": [{"color": c, "value": v} for v, c in steps]}


def stat(title, target, unit="short", steps=((None, GREEN),), mappings=None, desc="", text_mode="auto", decimals=None):
    defaults = {"unit": unit, "thresholds": thresholds(*steps), "color": {"mode": "thresholds"}, "mappings": mappings or []}
    if decimals is not None:
        defaults["decimals"] = decimals
    return {
        "type": "stat", "title": title, "description": desc, "datasource": target["datasource"], "targets": [target],
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "colorMode": "background", "graphMode": "none", "textMode": text_mode,
            "justifyMode": "center", "orientation": "auto", "wideLayout": True,
        },
    }


def timeseries(title, targets, unit="short", desc="", stack=False, overrides=None):
    return {
        "type": "timeseries", "title": title, "description": desc, "datasource": targets[0]["datasource"],
        "targets": [dict(t, refId=chr(65 + i)) for i, t in enumerate(targets)],
        "fieldConfig": {
            "defaults": {
                "unit": unit, "color": {"mode": "palette-classic"},
                "custom": {
                    "drawStyle": "line", "lineWidth": 2, "fillOpacity": 15, "gradientMode": "opacity",
                    "showPoints": "never", "spanNulls": True,
                    "stacking": {"mode": "normal" if stack else "none", "group": "A"},
                },
            },
            "overrides": overrides or [],
        },
        "options": {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi", "sort": "desc"}},
    }


def color_for(name: str, color: str) -> dict:
    return {"matcher": {"id": "byName", "options": name},
            "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": color}}]}


def table(title, target, desc="", overrides=None, sort=None, rename=None, order=None):
    return {
        "type": "table", "title": title, "description": desc, "datasource": target["datasource"], "targets": [target],
        "fieldConfig": {"defaults": {"custom": {"align": "auto"}}, "overrides": overrides or []},
        "options": {"showHeader": True, "cellHeight": "sm", "sortBy": sort or []},
        "transformations": [{"id": "organize", "options": {
            "renameByName": rename or {}, "indexByName": {name: i for i, name in enumerate(order or [])},
            "excludeByName": {"Time": True}}}],
    }


def logs(title, expr, desc=""):
    return {
        "type": "logs", "title": title, "description": desc, "datasource": LOKI, "targets": [loki(expr)],
        "options": {"showTime": True, "wrapLogMessage": True, "sortOrder": "Descending",
                    "enableLogDetails": True, "dedupStrategy": "none", "prettifyLogMessage": False},
    }


def statetimeline(title, targets, desc="", mappings=None, overrides=None):
    return {
        "type": "state-timeline", "title": title, "description": desc, "datasource": targets[0]["datasource"],
        "targets": [dict(t, refId=chr(65 + i)) for i, t in enumerate(targets)],
        "fieldConfig": {
            "defaults": {"custom": {"fillOpacity": 80, "lineWidth": 0}, "mappings": mappings or [],
                         "color": {"mode": "thresholds"}, "thresholds": thresholds((None, "transparent"), (1, RED))},
            "overrides": overrides or [],
        },
        "options": {"mergeValues": True, "showValue": "never", "rowHeight": 0.9,
                    "legend": {"displayMode": "list", "placement": "bottom"}, "alignValue": "left"},
    }


def dashboard(uid, title, description, layout, tags):
    return {
        "uid": uid, "title": title, "description": description, "tags": tags,
        "timezone": "browser", "editable": False, "graphTooltip": 1, "refresh": "10s",
        "time": {"from": "now-30m", "to": "now"}, "schemaVersion": 41, "version": 1,
        "templating": {"list": []}, "annotations": {"list": []},
        "links": [{"title": "Tableaux Devolut", "type": "dashboards", "tags": ["devolut"], "asDropdown": True}],
        "panels": layout.panels,
    }


UP_MAPPING = [{"type": "value", "options": {"1": {"text": "EN LIGNE", "color": GREEN}, "0": {"text": "HORS LIGNE", "color": RED}}}]
CORE = 'job=~"services|gateway|postgres|redis"'


def overview() -> dict:
    l = Layout()
    l.row("Santé de la plateforme")
    l.add(stat("Services en ligne", prom(f"sum(up{{{CORE}}})", instant=True), steps=((None, RED), (6, GREEN)),
               desc="Services métier (3), passerelle, PostgreSQL et Redis joignables : 6 attendus."), 4, 4)
    l.add(stat("Grand livre", prom("ledger_integrity_ok", instant=True), steps=((None, RED), (1, GREEN)),
               mappings=[{"type": "value", "options": {"1": {"text": "Cohérent"}, "0": {"text": "INCOHÉRENT"}}},
                         {"type": "special", "options": {"match": "null", "result": {"text": "Inconnu", "color": ORANGE}}}],
               desc="Contrôle d'intégrité toutes les 30 s : soldes égaux à la somme des écritures."), 4, 4)
    l.add(stat("Paiements en attente", prom("sum(payments_pending)", instant=True), steps=((None, GREEN), (1, ORANGE)),
               desc="Paiements acceptés mais pas encore inscrits au grand livre ; rejoués automatiquement."), 4, 4)
    l.add(stat("Requêtes / s", prom("sum(rate(devolut_gateway_requests_total[1m])) or vector(0)", instant=True),
               unit="reqps", steps=((None, BLUE),), decimals=1), 4, 4)
    l.add(stat("Erreurs serveur (5xx)", prom("devolut:gateway_error_ratio:rate1m or vector(0)", instant=True),
               unit="percentunit", steps=((None, GREEN), (0.01, ORANGE), (0.05, RED)), decimals=1), 4, 4)
    l.add(stat("Alertes actives", prom('count(ALERTS{alertstate="firing"}) or vector(0)', instant=True),
               steps=((None, GREEN), (1, RED))), 4, 4)

    l.add(stat("État des composants", prom(f"up{{{CORE}}}", legend="{{service}}", instant=True),
               steps=((None, RED), (1, GREEN)), mappings=UP_MAPPING, text_mode="value_and_name"), 24, 4)

    l.row("Trafic et performances")
    l.add(timeseries("Trafic de la passerelle par statut",
                     [prom("devolut:gateway_requests:rate1m", "{{status}}")], unit="reqps", stack=True,
                     overrides=[color_for("200", GREEN), color_for("201", "#73BF69"), color_for("401", ORANGE),
                                color_for("403", RED), color_for("429", "purple"), color_for("502", "dark-red")]), 12, 8)
    l.add(timeseries("Temps de réponse p95 par service",
                     [prom('histogram_quantile(0.95, sum by (le, service) (rate(http_request_duration_seconds_bucket{job="services", handler!~"/metrics|/health|/ready"}[1m])))', "{{service}}")],
                     unit="s"), 12, 8)

    l.row("Métier")
    l.add(timeseries("Paiements par statut (par minute)",
                     [prom("sum by (status) (rate(payments_total[2m])) * 60", "{{status}}")], stack=True,
                     overrides=[color_for("COMPLETED", GREEN), color_for("REJECTED", RED), color_for("PENDING", ORANGE)]), 8, 8)
    l.add(timeseries("Appels au grand livre (p95)",
                     [prom("histogram_quantile(0.95, sum by (le, outcome) (rate(payment_ledger_call_seconds_bucket[2m])))", "{{outcome}}")],
                     unit="s"), 8, 8)
    l.add(timeseries("Anomalies du grand livre",
                     [prom("ledger_integrity_anomalies", "anomalies")],
                     overrides=[color_for("anomalies", RED)]), 8, 8)

    l.row("Infrastructure")
    l.add(timeseries("Connexions PostgreSQL", [prom("sum by (state) (pg_stat_activity_count{datname=\"resilience\", state=~\"active|idle|idle in transaction\"})", "{{state}}")]), 8, 7)
    l.add(timeseries("Connexions ouvertes sur la passerelle", [prom("nginx_connections_active", "actives")]), 8, 7)
    l.add(timeseries("Mémoire Redis", [prom("redis_memory_used_bytes", "utilisée")], unit="bytes"), 8, 7)

    return dashboard("devolut-overview", "Devolut — Vue d'ensemble",
                     "Santé, trafic et indicateurs métier de la plateforme de paiement.", l, ["devolut"])


def soc() -> dict:
    l = Layout()
    l.row("Indicateurs de sécurité (sur la période affichée)")
    l.add(stat("Requêtes bloquées par le WAF", prom("sum(increase(devolut_waf_blocked_total[$__range])) or vector(0)", instant=True),
               steps=((None, GREEN), (1, ORANGE), (50, RED)), decimals=0), 6, 4)
    l.add(stat("Requêtes limitées (429)", prom('sum(increase(devolut_gateway_requests_total{status="429"}[$__range])) or vector(0)', instant=True),
               steps=((None, GREEN), (1, ORANGE), (100, RED)), decimals=0), 6, 4)
    l.add(stat("Échecs de connexion", prom('sum(increase(auth_login_attempts_total{result!="success"}[$__range])) or vector(0)', instant=True),
               steps=((None, GREEN), (5, ORANGE), (30, RED)), decimals=0), 6, 4)
    l.add(stat("Alertes de sécurité actives", prom('count(ALERTS{alertstate="firing", category="security"}) or vector(0)', instant=True),
               steps=((None, GREEN), (1, RED))), 6, 4)

    l.add(timeseries("Activité suspecte (par minute)", [
        prom("sum(rate(devolut_waf_blocked_total[1m])) * 60", "bloquées par le WAF"),
        prom('sum(rate(devolut_gateway_requests_total{status="429"}[1m])) * 60', "limitées (429)"),
        prom('sum(rate(devolut_gateway_requests_total{status="401"}[1m])) * 60', "non authentifiées (401)"),
        prom('sum(rate(auth_login_attempts_total{result!="success"}[1m])) * 60', "échecs de connexion"),
    ], overrides=[color_for("bloquées par le WAF", RED), color_for("limitées (429)", "purple"),
                  color_for("non authentifiées (401)", ORANGE), color_for("échecs de connexion", "yellow")]), 16, 8)
    l.add(table("Alertes en cours",
                prom('ALERTS{alertstate="firing"}', instant=True, fmt="table"),
                desc="Règles Prometheus déclenchées (infra/prometheus/alerts.yml).",
                overrides=[{"matcher": {"id": "byRegexp", "options": "^(Time|Value|__name__|alertstate|job|instance|platform)$"},
                            "properties": [{"id": "custom.hidden", "value": True}]}]), 8, 8)

    l.row("Détection d'anomalies (ML)")
    l.add(stat("Détecteur", prom("ml_state", instant=True), steps=((None, BLUE), (1, GREEN)),
               mappings=[{"type": "value", "options": {"0": {"text": "Apprentissage", "color": BLUE},
                                                        "1": {"text": "Surveillance", "color": GREEN}}}],
               desc="Apprend le trafic normal, puis surveille les écarts."), 6, 4)
    l.add(stat("Score d'anomalie", prom("ml_anomaly_score", instant=True), decimals=3,
               steps=((None, GREEN), (0.05, ORANGE), (0.15, RED)),
               desc="Écart au comportement normal. Négatif = normal ; au-delà de 0,05 = anomalie retenue."), 6, 4)
    l.add(stat("Incident en cours", prom("ml_incident_active or vector(0)", instant=True),
               steps=((None, GREEN), (1, RED)),
               mappings=[{"type": "value", "options": {"0": {"text": "Non"}, "1": {"text": "Oui"}}}]), 6, 4)
    l.add(stat("Référence (échantillons)", prom("ml_baseline_samples or vector(0)", instant=True),
               steps=((None, BLUE),), decimals=0), 6, 4)
    l.add(timeseries("Score d'anomalie du détecteur", [prom("ml_anomaly_score", "score")],
                     desc="Une montée nette au-dessus de 0 signale un comportement anormal.",
                     overrides=[color_for("score", "purple")]), 16, 7)
    l.add(statetimeline("Type d'incident détecté",
                        [prom("ml_incident", "{{type}}")],
                        desc="Qualification de l'incident par le détecteur (force brute, intrusion, surcharge, intégrité…)."), 8, 7)

    l.row("Sources")
    l.add(table("Adresses IP les plus actives",
                loki('topk(10, sum by (client_ip) (count_over_time({service="gateway", log_type="access"} | json client_ip [$__range])))', "instant"),
                desc="Nombre de requêtes par adresse source sur la période affichée.",
                rename={"client_ip": "Adresse IP", "Value #A": "Requêtes"}, sort=[{"displayName": "Requêtes", "desc": True}],
                overrides=[{"matcher": {"id": "byName", "options": "Time"}, "properties": [{"id": "custom.hidden", "value": True}]}]), 8, 9)
    l.add(table("Adresses IP bloquées par le WAF",
                loki('topk(10, sum by (client_ip) (count_over_time({service="gateway", log_type="waf_audit"} | json client_ip="transaction.client_ip", code="transaction.response.http_code" | code="403" [$__range])))', "instant"),
                rename={"client_ip": "Adresse IP", "Value #A": "Blocages"}, sort=[{"displayName": "Blocages", "desc": True}],
                overrides=[{"matcher": {"id": "byName", "options": "Time"}, "properties": [{"id": "custom.hidden", "value": True}]}]), 8, 9)
    l.add(table("Règles du WAF déclenchées",
                loki('topk(10, sum by (rule, message) (count_over_time({service="gateway", log_type="waf_audit"} | json rule="transaction.messages[0].details.ruleId", message="transaction.messages[0].message", code="transaction.response.http_code" | code="403" [$__range])))', "instant"),
                rename={"rule": "Règle", "message": "Attaque détectée", "Value #A": "Blocages"},
                order=["rule", "message", "Value #A"], sort=[{"displayName": "Blocages", "desc": True}],
                overrides=[{"matcher": {"id": "byName", "options": "rule"}, "properties": [{"id": "custom.width", "value": 80}]},
                           {"matcher": {"id": "byName", "options": "Value #A"}, "properties": [{"id": "custom.width", "value": 90}]}]), 8, 9)

    l.row("Journaux")
    l.add(logs("Requêtes bloquées par le pare-feu applicatif",
               '{service="gateway", log_type="waf_audit"} | json ip="transaction.client_ip", method="transaction.request.method", uri="transaction.request.uri", code="transaction.response.http_code", rule="transaction.messages[0].details.ruleId", message="transaction.messages[0].message" | code="403" | line_format "{{.ip}}  {{.method}} {{.uri}}  →  règle {{.rule}} : {{.message}}"'), 12, 10)
    l.add(logs("Événements de sécurité applicatifs",
               '{service=~"auth-service|ledger-service|payment-api"} | json | msg=~"login_failed|login_blocked|limiter_unavailable|ledger_integrity_failed|transfer_integrity_error|account_status_changed" | line_format "{{.service}}  {{.msg}}  {{if .username}}utilisateur={{.username}} {{end}}{{if .client_ip}}ip={{.client_ip}} {{end}}{{if .reason}}motif={{.reason}}{{end}}"'), 12, 10)
    l.add(logs("Erreurs et avertissements de tous les services",
               '{service=~"auth-service|ledger-service|payment-api"} | level=~"warning|error|critical"'), 24, 8)

    return dashboard("devolut-soc", "Devolut — Vue SOC",
                     "Événements de sécurité : pare-feu applicatif, limitation de débit, connexions, alertes.", l, ["devolut", "securite"])


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, board in (("devolut-overview.json", overview()), ("devolut-soc.json", soc())):
        (OUT / name).write_text(json.dumps(board, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{name} : {len(board['panels'])} panneaux")


if __name__ == "__main__":
    main()
