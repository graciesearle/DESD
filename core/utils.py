import math
import requests
from django.core.cache import cache


def get_lat_lon_bulk(postcodes):
    # Fetch lat/lon for a list of postcodes, using local cache where possible.
    result = {}
    to_fetch = []

    for pc in postcodes:
        if not pc: continue
        clean_pc = pc.replace(" ", "").upper()
        cache_key = f"pc_coord_{clean_pc}"
        coords = cache.get(cache_key)
        if coords:
            result[clean_pc] = coords
        else:
            to_fetch.append(pc)

    if to_fetch:
        try:
            # Postcodes.io supports bulk lookups
            resp = requests.post(
                "https://api.postcodes.io/postcodes",
                json={"postcodes": list(set(to_fetch))},
                timeout=5
            )
            if resp.status_code == 200:
                for item in resp.json().get("result", []):
                    if item["query"] and item["result"]:
                        clean_pc = item["query"].replace(" ", "").upper()
                        coords = (item["result"]["latitude"], item["result"]["longitude"])
                        result[clean_pc] = coords
                        cache.set(f"pc_coord_{clean_pc}", coords, timeout=86400 * 30)  # cache for 30 days
        except requests.RequestException:
            pass

    return result


def haversine(lat1, lon1, lat2, lon2):
    # Calculate the great circle distance between two points on the earth in miles.
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    lon = lon2 - lon1
    lat = lat2 - lat1
    a = math.sin(lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(lon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))
    r = 3956  # Radius of earth in miles
    return c * r


def calculate_food_miles(origin_postcode, dest_postcode):
    # Calculates miles between two UK postcodes.
    if not origin_postcode or not dest_postcode:
        return None

    bulk_res = get_lat_lon_bulk([origin_postcode, dest_postcode])
    c1 = bulk_res.get(origin_postcode.replace(" ", "").upper())
    c2 = bulk_res.get(dest_postcode.replace(" ", "").upper())

    if c1 and c2:
        miles = haversine(c1[0], c1[1], c2[0], c2[1])
        return round(miles, 1)

    return None