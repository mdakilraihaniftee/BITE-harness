"""JSON-safe, nontruncating numerical capture with secret/media exclusion."""
import hashlib
import json
import math
import os
import re

_SECRET_KEY = re.compile(r"(?:.*_)?(?:api_?key|token|password|authorization|secret|credential)", re.I)


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()


class Serializer:
    def __init__(self):
        self.secrets = tuple(value for key, value in os.environ.items()
                             if _SECRET_KEY.search(key) and len(value) >= 8)

    def text(self, value):
        for secret in self.secrets:
            value = value.replace(secret, "<REDACTED>")
        # Serialized invalid arguments and error strings may contain credentials too.
        value = re.sub(r'(?i)("(?:api_key|authorization|password|access_token)"\s*:\s*)"[^"]*"',
                       r'\1"<REDACTED>"', value)
        value = re.sub(r'data:image/[a-zA-Z0-9.+-]+;base64,[a-zA-Z0-9+/=]+',
                       lambda m: '<image_sha256:' + digest(m.group()) + '>', value)
        value = re.sub(r'(?<=")[a-zA-Z0-9+/]{512,}={0,2}(?=")',
                       lambda m: '<encoded_media_sha256:' + digest(m.group()) + '>', value)
        return value

    def clean(self, value):
        if isinstance(value, str):
            if value.startswith("data:image/"):
                return {"media_omitted": True, "encoded_sha256": digest(value)}
            return self.text(value)
        if value is None or isinstance(value, (bool, int)):
            return value
        if isinstance(value, float):
            return value if math.isfinite(value) else {"non_finite": str(value)}
        if isinstance(value, dict):
            return {str(k): ("<REDACTED>" if _SECRET_KEY.fullmatch(str(k)) else self.clean(v))
                    for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.clean(v) for v in value]
        if isinstance(value, set):
            return [self.clean(v) for v in sorted(value)]
        if hasattr(value, "tolist"):
            return self.clean(value.tolist())
        return {"unavailable_type": type(value).__name__}

    def fingerprint(self, value):
        return digest(json.dumps(self.clean(value), sort_keys=True, ensure_ascii=False))
