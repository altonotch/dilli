from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib import parse, request, error

from django.conf import settings
from django.contrib.gis.geos import Point


class GeoapifyError(Exception):
    """Raised when Geoapify returns an error or no API key is configured."""


@dataclass
class GeoapifyResult:
    latitude: float
    longitude: float
    formatted: str
    city: str | None = None

    @property
    def point(self) -> Point:
        return Point(self.longitude, self.latitude, srid=4326)


def search_place(text: str, limit: int = 3, api_key: Optional[str] = None) -> List[GeoapifyResult]:
    api_key = api_key or getattr(settings, "GEOAPIFY_API_KEY", "")
    if not api_key:
        raise GeoapifyError("Geoapify API key is not configured")

    query = parse.urlencode(
        {
            "text": text,
            "limit": limit,
            "format": "json",
            "apiKey": api_key,
        }
    )
    url = f"https://api.geoapify.com/v1/geocode/search?{query}"
    req = request.Request(url, headers={"Accept": "application/json"})
    try:
        with request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        raise GeoapifyError(f"Geoapify error: {exc.code}") from exc
    except Exception as exc:
        raise GeoapifyError("Geoapify request failed") from exc

    features = payload.get("features") or []
    results: List[GeoapifyResult] = []
    for feature in features:
        props: Dict[str, Any] = feature.get("properties", {})
        lat = props.get("lat")
        lon = props.get("lon")
        formatted = props.get("formatted")
        if lat is None or lon is None or formatted is None:
            continue
        results.append(
            GeoapifyResult(
                latitude=float(lat),
                longitude=float(lon),
                formatted=formatted,
                city=props.get("city"),
            )
        )
    return results


def geocode_store_name(name: str, city: str | None = None, api_key: Optional[str] = None) -> GeoapifyResult | None:
    text = " ".join(filter(None, [name, city])).strip() or name
    results = search_place(text, limit=1, api_key=api_key)
    return results[0] if results else None
