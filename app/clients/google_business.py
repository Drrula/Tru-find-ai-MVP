"""
Google Business data client.

Today this returns deterministic mock data so the rest of the system can be wired
up end-to-end. The shape of `GoogleBusinessData` and the `fetch_google_business`
signature match what a thin wrapper over the Google Places API (Place Details:
`places.googleapis.com/v1/places/{id}` with field mask `displayName,rating,
userRatingCount`) would return, so swapping in the real call is a body-only change.
"""

from dataclasses import dataclass
from hashlib import md5


@dataclass
class GoogleBusinessData:
    exists: bool
    rating: float       # 0.0–5.0; meaningful only when exists=True
    review_count: int   # 0+; meaningful only when exists=True


def _stable_int(business_name: str, location: str, salt: str) -> int:
    key = f"{business_name.lower().strip()}|{location.lower().strip()}|{salt}".encode()
    return int(md5(key).hexdigest(), 16)


def fetch_google_business(business_name: str, location: str) -> GoogleBusinessData:
    """
    Look up a business on Google.

    Replace the mock body below with a real Google Places API call:
        1. Text Search → resolve `business_name + location` to a place_id
        2. Place Details → read displayName, rating, userRatingCount
    Map the response into GoogleBusinessData and return it. The signal layer
    does not need to change.
    """
    presence_roll = _stable_int(business_name, location, "gbp-exists") % 100
    if presence_roll < 20:
        # ~20% of mock businesses have no listing at all.
        return GoogleBusinessData(exists=False, rating=0.0, review_count=0)

    rating = round(3.0 + (_stable_int(business_name, location, "gbp-rating") % 200) / 100.0, 1)
    review_count = _stable_int(business_name, location, "gbp-reviews") % 500

    return GoogleBusinessData(exists=True, rating=rating, review_count=review_count)
