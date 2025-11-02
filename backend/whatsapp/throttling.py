from __future__ import annotations
import json
from rest_framework.throttling import SimpleRateThrottle

from .utils import normalize_wa_id, compute_wa_hash


class IPRateThrottle(SimpleRateThrottle):
    scope = 'ip'

    def get_cache_key(self, request, view):
        ident = request.META.get('REMOTE_ADDR') or ''
        if not ident:
            ident = 'unknown'
        return f"throttle_ip_{ident}"


class WaHashRateThrottle(SimpleRateThrottle):
    scope = 'wa_hash'

    def get_cache_key(self, request, view):
        # Try a header override first (optional)
        wa_hash = request.headers.get('X-WA-Hash', '')
        if not wa_hash and request.body:
            try:
                payload = json.loads(request.body.decode('utf-8'))
                for entry in payload.get('entry', []):
                    for change in entry.get('changes', []):
                        value = change.get('value', {})
                        messages = value.get('messages', []) or []
                        for msg in messages:
                            wa_raw = str(msg.get('from', ''))
                            wa_norm = normalize_wa_id(wa_raw)
                            if wa_norm:
                                wa_hash = compute_wa_hash(wa_norm)
                                raise StopIteration
            except StopIteration:
                pass
            except Exception:
                pass
        ident = wa_hash or (request.META.get('REMOTE_ADDR') or 'unknown')
        return f"throttle_wh_{ident}"
