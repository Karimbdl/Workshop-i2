"""Qualification de l'incident.

Le modèle dit « c'est anormal » ; cette étape dit « de quel genre ». La disponibilité ne se traite
pas comme une compromission : la remédiation choisira son playbook à partir de ce type. On combine
des règles sûres (intégrité, service à terre) et l'écart des indicateurs à la référence (z-scores),
ce qui reste explicable devant un jury.
"""

# Au-delà de ce nombre d'écarts-types, un indicateur est considéré comme « en pic ».
Z_THRESHOLD = 3.0

INCIDENTS = {
    "integrite": "Atteinte à l'intégrité du grand livre",
    "disponibilite": "Perte de disponibilité d'un service",
    "force_brute": "Force brute sur l'authentification",
    "intrusion_applicative": "Intrusion applicative (attaque web)",
    "surcharge": "Surcharge / pic de trafic anormal",
    "degradation": "Dégradation des performances",
    "indetermine": "Anomalie de nature indéterminée",
}


def classify(vector: dict, zscores: dict) -> tuple[str, str, list[str]]:
    """Renvoie (type, libellé, indicateurs_en_cause)."""

    # 1. Signaux durs, prioritaires.
    if vector.get("integrity_ok", 1) < 1 or vector.get("anomalies", 0) > 0:
        return "integrite", INCIDENTS["integrite"], ["integrity_ok", "anomalies"]
    if vector.get("up_ratio", 1) < 1:
        return "disponibilite", INCIDENTS["disponibilite"], ["up_ratio"]

    # 2. Indicateurs comportementaux en pic (triés par ampleur de l'écart).
    spikes = sorted(
        ((name, z) for name, z in zscores.items() if z >= Z_THRESHOLD),
        key=lambda kv: kv[1], reverse=True,
    )
    spiking = [name for name, _ in spikes]

    def hit(*names):
        return [n for n in spiking if n in names]

    if hit("login_fail"):
        return "force_brute", INCIDENTS["force_brute"], hit("login_fail", "rate_429")
    if hit("waf_blocks", "rate_403"):
        return "intrusion_applicative", INCIDENTS["intrusion_applicative"], hit("waf_blocks", "rate_403", "rate_4xx")
    if hit("rate_429", "req_rate"):
        return "surcharge", INCIDENTS["surcharge"], hit("rate_429", "req_rate", "rate_4xx")
    if hit("err_ratio", "latency_p95", "pending"):
        return "degradation", INCIDENTS["degradation"], hit("err_ratio", "latency_p95", "pending")

    return "indetermine", INCIDENTS["indetermine"], spiking[:3]
