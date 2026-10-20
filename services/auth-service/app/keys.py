"""Clé de signature des jetons (RS256) et publication JWKS.

La clé privée est lue depuis un fichier secret et rechargée si le fichier
change : un renouvellement de clé ne demande pas de redémarrer le service.
"""

import hashlib
import threading
from dataclasses import dataclass

from cryptography.hazmat.primitives import serialization
from jwt.algorithms import RSAAlgorithm

from resilience_common.secrets import SECRETS_DIR

KEY_FILE = SECRETS_DIR / "jwt_private_key"


@dataclass(frozen=True)
class SigningKey:
    kid: str
    private_pem: bytes
    jwk: dict


class KeyStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._mtime: float | None = None
        self._key: SigningKey | None = None

    def current(self) -> SigningKey:
        mtime = KEY_FILE.stat().st_mtime
        with self._lock:
            if self._key is None or mtime != self._mtime:
                self._key = self._load()
                self._mtime = mtime
            return self._key

    @staticmethod
    def _load() -> SigningKey:
        private_pem = KEY_FILE.read_bytes()
        private_key = serialization.load_pem_private_key(private_pem, password=None)
        public_key = private_key.public_key()
        der = public_key.public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        kid = hashlib.sha256(der).hexdigest()[:16]
        jwk = RSAAlgorithm.to_jwk(public_key, as_dict=True)
        jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
        return SigningKey(kid=kid, private_pem=private_pem, jwk=jwk)


key_store = KeyStore()
