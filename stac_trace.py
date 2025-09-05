#!/usr/bin/env python3

import os
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any, Tuple
import click
import requests
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
from rich.console import Console
from rich.table import Table
from rich.json import JSON
from rich import print as rprint

load_dotenv()

console = Console()

# Simple in-memory cache for geocoding and infrastructure results
geocode_cache = {}
infrastructure_cache = {}


def calculate_significance_score(element: Dict, tags: Dict) -> int:
    """Calculate significance score for an infrastructure element.
    
    Higher scores indicate more strategic/important infrastructure.
    """
    score = 0
    
    # Base scoring by element type (larger features score higher)
    if element.get("type") == "relation":
        score += 15
    elif element.get("type") == "way":
        score += 10
    elif element.get("type") == "node":
        score += 5
    
    # Named features are more significant
    if tags.get("name") and tags["name"] != "Unnamed":
        score += 20
    
    # Wikipedia/Wikidata presence indicates major landmark
    if tags.get("wikipedia") or tags.get("wikidata"):
        score += 30
    
    # Operator suggests organized/major facility
    if tags.get("operator"):
        score += 10
    
    # Category-specific scoring (strategic importance)
    if "military" in tags:
        score += 100
    if tags.get("aeroway") == "aerodrome":
        score += 80
    if tags.get("power") == "plant":
        score += 70
    if tags.get("amenity") == "embassy":
        score += 60
    if tags.get("amenity") == "government":
        score += 50
    if tags.get("amenity") == "university":
        score += 40
    if tags.get("amenity") == "hospital":
        score += 35
        # Large hospitals score higher
        if tags.get("beds"):
            try:
                beds = int(tags["beds"])
                score += min(beds // 10, 30)
            except:
                pass
    if tags.get("telecom") == "data_center" or tags.get("building") == "data_center":
        score += 45
    if tags.get("railway") == "station":
        score += 35
    if tags.get("landuse") == "industrial" and tags.get("name"):
        score += 30
    
    # Size indicators
    if tags.get("building:levels"):
        try:
            levels = int(tags["building:levels"])
            if levels > 10:
                score += levels * 2
        except:
            pass
    
    if tags.get("capacity"):
        try:
            capacity = int(tags["capacity"])
            score += min(capacity // 100, 20)
        except:
            pass
    
    # International/national importance
    if tags.get("importance") == "international":
        score += 40
    elif tags.get("importance") == "national":
        score += 30
    elif tags.get("importance") == "regional":
        score += 20
    
    return score


def get_infrastructure_data(lat: float, lon: float, radius_km: float = 3) -> Dict[str, Any]:
    """Query OpenStreetMap Overpass API for significant infrastructure and commercial activity.
    
    Fetches and intelligently filters infrastructure, prioritizing the most
    significant facilities based on strategic importance, size, and notability.
    Returns categorized infrastructure data for the location.
    """
    # Round to 0.1 degree for cache key (about 11km resolution)
    cache_key = f"infra_{lat:.1f},{lon:.1f},{radius_km}"
    
    if cache_key in infrastructure_cache:
        return infrastructure_cache[cache_key]
    
    # Convert radius to degrees (approximate)
    radius_deg = radius_km / 111.0  # 1 degree latitude ≈ 111km
    
    # Build optimized Overpass QL query - focus on most significant items only
    query = f"""
    [out:json][timeout:25];
    (
      // Military and defense (Always significant)
      way["military"](around:{radius_km * 1000},{lat},{lon});
      relation["military"](around:{radius_km * 1000},{lat},{lon});

      // Airports (Always significant)
      way["aeroway"="aerodrome"](around:{radius_km * 1000},{lat},{lon});

      // Government facilities (Named only)
      way["amenity"="government"]["name"](around:{radius_km * 1000},{lat},{lon});
      way["office"="government"]["name"](around:{radius_km * 1000},{lat},{lon});

      // Power plants (Always significant)
      way["power"="plant"](around:{radius_km * 1000},{lat},{lon});

      // Major industrial (Named only)
      way["landuse"="industrial"]["name"](around:{radius_km * 1000},{lat},{lon});

      // Ports
      way["harbour"](around:{radius_km * 1000},{lat},{lon});
      way["landuse"="harbour"](around:{radius_km * 1000},{lat},{lon});

      // Embassies and prisons
      way["amenity"="embassy"](around:{radius_km * 1000},{lat},{lon});
      way["amenity"="prison"](around:{radius_km * 1000},{lat},{lon});

      // Major hospitals
      way["amenity"="hospital"]["name"](around:{radius_km * 1000},{lat},{lon});

      // Rail stations
      way["railway"="station"]["name"](around:{radius_km * 1000},{lat},{lon});
    );
    out body;
    >;
    out skel qt;
    """
    
    try:
        # Query Overpass API with retry logic
        url = "https://overpass-api.de/api/interpreter"
        headers = {"User-Agent": "stac-trace/1.0"}
        max_retries = 2

        for attempt in range(max_retries + 1):
            try:
                response = requests.post(url, data=query, headers=headers, timeout=30)

                if response.status_code == 200:
                    break
                elif response.status_code == 429:  # Rate limited
                    if attempt < max_retries:
                        time.sleep(2 ** attempt)  # Exponential backoff
                        continue
                    else:
                        return {"error": "Overpass API rate limit exceeded"}
                elif response.status_code >= 500:  # Server error
                    if attempt < max_retries:
                        time.sleep(1)
                        continue
                    else:
                        return {"error": f"Overpass API server error: {response.status_code}"}
                else:
                    return {"error": f"Overpass API error: {response.status_code}"}

            except requests.exceptions.Timeout:
                if attempt < max_retries:
                    continue
                else:
                    return {"error": "Overpass query timeout"}
            except requests.exceptions.RequestException as e:
                if attempt < max_retries:
                    time.sleep(1)
                    continue
                else:
                    return {"error": f"Network error: {str(e)}"}

        # If we get here without breaking, all retries failed
        if response.status_code != 200:
            return {"error": f"Overpass API error after {max_retries + 1} attempts: {response.status_code}"}

        data = response.json()
        elements = data.get("elements", [])
        
        # Categorize infrastructure with expanded categories
        infrastructure = {
            "strategic": [],     # Military, government, embassies
            "airports": [],      # Airports and aerodromes
            "power": [],         # Power plants and major substations
            "transport": [],     # Rail stations, ports, terminals
            "technology": [],    # Data centers, telecom
            "industrial": [],    # Major industrial facilities
            "healthcare": [],    # Major hospitals
            "education": [],     # Universities, research institutes
            "commercial": [],    # Major commercial centers
            "critical": []       # Prisons and other critical infrastructure
        }
        
        # Process and score all elements
        scored_elements = []
        for element in elements:
            tags = element.get("tags", {})
            name = tags.get("name", tags.get("operator", "Unnamed"))
            
            # Calculate significance score
            score = calculate_significance_score(element, tags)
            
            # Skip low-scoring unnamed features
            if score < 15 and name == "Unnamed":
                continue
            
            item = {
                "name": name,
                "element": element,
                "tags": tags,
                "score": score
            }
            
            # Categorize by type with expanded categories
            if "military" in tags:
                item["type"] = tags.get("military", "facility")
                item["category"] = "strategic"
            elif tags.get("amenity") == "embassy":
                item["type"] = "embassy"
                item["category"] = "strategic"
            elif tags.get("amenity") == "government" or tags.get("office") == "government":
                item["type"] = tags.get("government", "office")
                item["category"] = "strategic"
            elif tags.get("aeroway") == "aerodrome":
                item["type"] = tags.get("aerodrome:type", "airport")
                item["category"] = "airports"
            elif tags.get("power") == "plant":
                item["type"] = f"power plant ({tags.get('plant:source', 'unknown')})"
                item["category"] = "power"
            elif tags.get("power") == "substation" and score >= 20:  # Only significant substations
                item["type"] = "substation"
                item["category"] = "power"
            elif tags.get("railway") == "station":
                item["type"] = "railway station"
                item["category"] = "transport"
            elif "harbour" in tags or tags.get("landuse") == "harbour":
                item["type"] = "port/harbour"
                item["category"] = "transport"
            elif tags.get("aeroway") == "terminal":
                item["type"] = "airport terminal"
                item["category"] = "transport"
            elif tags.get("telecom") == "data_center" or tags.get("building") == "data_center":
                item["type"] = "data center"
                item["category"] = "technology"
            elif tags.get("amenity") == "hospital":
                beds = tags.get("beds", "")
                item["type"] = f"hospital ({beds} beds)" if beds else "hospital"
                item["category"] = "healthcare"
            elif tags.get("amenity") == "university":
                item["type"] = "university"
                item["category"] = "education"
            elif tags.get("amenity") == "research_institute":
                item["type"] = tags.get("research", "research institute")
                item["category"] = "education"
            elif tags.get("landuse") == "industrial" or tags.get("man_made") == "works":
                item["type"] = tags.get("industrial", tags.get("product", "industrial facility"))
                item["category"] = "industrial"
            elif tags.get("shop") == "mall":
                item["type"] = "shopping mall"
                item["category"] = "commercial"
            elif tags.get("amenity") == "bank":
                item["type"] = "bank"
                item["category"] = "commercial"
            elif tags.get("office") == "company" and score >= 30:  # Only major offices
                item["type"] = "corporate office"
                item["category"] = "commercial"
            elif tags.get("tourism") == "hotel" and score >= 25:  # Only significant hotels
                item["type"] = "hotel"
                item["category"] = "commercial"
            elif tags.get("building") == "commercial" and score >= 35:  # Only large commercial buildings
                levels = tags.get("building:levels", "")
                item["type"] = f"commercial building ({levels} floors)" if levels else "commercial building"
                item["category"] = "commercial"
            elif tags.get("amenity") == "prison":
                item["type"] = "prison"
                item["category"] = "critical"
            else:
                continue  # Skip uncategorized items
            
            if "category" in item:
                scored_elements.append(item)
        
        # Sort by score and take top items per category
        scored_elements.sort(key=lambda x: x["score"], reverse=True)
        
        # Populate categories with top items only
        category_limits = {
            "strategic": 5,      # Show more strategic items
            "airports": 3,
            "power": 3,
            "transport": 4,
            "technology": 3,
            "industrial": 3,
            "healthcare": 2,
            "education": 3,
            "commercial": 3,
            "critical": 2
        }
        
        category_counts = {cat: 0 for cat in infrastructure.keys()}
        
        for item in scored_elements:
            category = item["category"]
            if category_counts[category] < category_limits[category]:
                infrastructure[category].append({
                    "name": item["name"],
                    "type": item["type"],
                    "score": item["score"]
                })
                category_counts[category] += 1
        
        # Remove empty categories and sort items by score within each category
        result = {}
        for category, items in infrastructure.items():
            if items:
                # Sort by score within category and remove score from output
                items.sort(key=lambda x: x["score"], reverse=True)
                for item in items:
                    del item["score"]  # Remove score from final output
                result[category] = items
        
        # Cache the result
        infrastructure_cache[cache_key] = result
        
        # Be nice to the free service
        time.sleep(0.5)
        
        return result
        
    except Exception as e:
        return {"error": f"Unexpected error: {str(e)}"}


def get_location_name(lat: float, lon: float) -> str:
    """Get human-readable location name using reverse geocoding.
    
    Uses OpenStreetMap Nominatim (no API key required). Implements
    caching and exponential backoff to handle rate limits gracefully.
    """
    # Round to 1 decimal for cache key (about 11km resolution)
    cache_key = f"{lat:.1f},{lon:.1f}"
    
    if cache_key in geocode_cache:
        return geocode_cache[cache_key]
    
    try:
        # Use Nominatim (OpenStreetMap) for reverse geocoding
        url = "https://nominatim.openstreetmap.org/reverse"
        params = {
            "lat": lat,
            "lon": lon,
            "format": "json",
            "zoom": 10,  # City/town level
            "accept-language": "en"
        }
        headers = {
            "User-Agent": "stac-trace/1.0"  # Required by Nominatim
        }
        
        response = requests.get(url, params=params, headers=headers, timeout=2)
        
        if response.status_code == 200:
            data = response.json()
            address = data.get("address", {})
            
            # Build location string from most specific to least specific
            parts = []
            
            # Try to get city/town/village
            for key in ["city", "town", "village", "municipality", "suburb"]:
                if key in address:
                    parts.append(address[key])
                    break
            
            # Add state/region if available
            for key in ["state", "region", "province"]:
                if key in address:
                    parts.append(address[key])
                    break
            
            # Add country
            if "country" in address:
                parts.append(address["country"])
            
            location = ", ".join(parts) if parts else f"{lat:.1f}, {lon:.1f}"
            
            # Cache the result
            geocode_cache[cache_key] = location
            
            # Be nice to the free service
            time.sleep(0.5)
            
            return location
        else:
            return f"{lat:.1f}, {lon:.1f}"
            
    except Exception:
        # If geocoding fails, just return coordinates
        return f"{lat:.1f}, {lon:.1f}"


class UP42Client:
    """Client for interacting with UP42 STAC API.
    
    Handles OAuth authentication and provides methods for searching
    satellite imagery catalogs with automatic pagination.
    """
    def __init__(self):
        self.username = os.getenv("UP42_USERNAME")
        self.password = os.getenv("UP42_PASSWORD")
        self.base_url = "https://api.up42.com"
        self.auth_url = "https://auth.up42.com"
        self.access_token = None
        self._authenticate()
    
    def _authenticate(self):
        """Get OAuth access token from UP42."""
        auth_endpoint = f"{self.auth_url}/realms/public/protocol/openid-connect/token"
        
        data = {
            "username": self.username,
            "password": self.password,
            "grant_type": "password",
            "client_id": "up42-api"
        }
        
        response = requests.post(
            auth_endpoint,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        
        if response.status_code == 200:
            token_data = response.json()
            self.access_token = token_data.get("access_token")
            console.print("[green]✓ Authentication successful[/green]")
        else:
            console.print(f"[red]Authentication failed: {response.status_code} - {response.text}[/red]")
            raise Exception("Failed to authenticate with UP42")
    
    @property
    def headers(self):
        """Get headers with current access token."""
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        
    def search_catalog(self, 
                      host: str = "oneatlas",
                      bbox: Optional[List[float]] = None,
                      start_date: Optional[str] = None,
                      end_date: Optional[str] = None,
                      collections: Optional[List[str]] = None,
                      limit: int = 100,
                      cloud_coverage: Optional[int] = None) -> Dict[str, Any]:
        """Search UP42 catalog for items from a specific host."""
        
        search_endpoint = f"{self.base_url}/catalog/hosts/{host}/stac/search"
        
        search_body = {
            "limit": min(limit, 500)  # API max is 500
        }
        
        if bbox:
            search_body["bbox"] = bbox
            
        if start_date and end_date:
            search_body["datetime"] = f"{start_date}/{end_date}"
        elif start_date:
            search_body["datetime"] = f"{start_date}/.."
        elif end_date:
            search_body["datetime"] = f"../{end_date}"
            
        if collections:
            search_body["collections"] = collections
            
        if cloud_coverage is not None:
            search_body["query"] = {
                "cloudCoverage": {
                    "lte": cloud_coverage
                }
            }
            
        response = requests.post(
            search_endpoint,
            headers=self.headers,
            json=search_body
        )
        
        if response.status_code != 200:
            console.print(f"[red]Error: {response.status_code} - {response.text}[/red]")
            return {}
            
        data = response.json()

        # Check for pagination in STAC response
        items = data.get("features", [])
        links = data.get("links", [])
        has_next = any(link.get("rel") == "next" for link in links)

        # If we got exactly the limit and there's a next link, warn about potential missing items
        if len(items) == 500 and has_next:
            console.print(f"  [yellow]Warning: Got 500 items with more results available. Consider using smaller time chunks.[/yellow]")

        return data
    
    def search_catalog_deep(self,
                            host: str = "oneatlas",
                            bbox: Optional[List[float]] = None,
                            start_date: Optional[str] = None,
                            end_date: Optional[str] = None,
                            collections: Optional[List[str]] = None,
                            cloud_coverage: Optional[int] = None,
                            show_progress: bool = True,
                            taskable_only: bool = False,
                            min_chunk_hours: int = 1,
                            max_workers: int = 4) -> List[Dict]:
        """Deep search that automatically handles API limits by time-slicing.
        
        Bypasses the 500-item API limit by breaking searches into time chunks
        and combining results. Essential for finding all surveillance activity
        in a given area/timeframe.
        """
        
        all_items = []
        
        # Parse dates
        if start_date:
            # Handle both Z and +00:00 formats
            if start_date.endswith("Z"):
                start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            else:
                start_dt = datetime.fromisoformat(start_date.split("+")[0] + "+00:00")
        else:
            start_dt = datetime.now(timezone.utc) - timedelta(days=30)
            
        if end_date:
            if end_date.endswith("Z"):
                end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            else:
                end_dt = datetime.fromisoformat(end_date.split("+")[0] + "+00:00")
        else:
            end_dt = datetime.now(timezone.utc)
        
        # Calculate time span in hours for more precise control
        time_span_hours = (end_dt - start_dt).total_seconds() / 3600

        # If less than 24 hours, do single search
        if time_span_hours <= 24:
            result = self.search_catalog(
                host=host, bbox=bbox, start_date=start_date, end_date=end_date,
                collections=collections, limit=500, cloud_coverage=cloud_coverage
            )
            return result.get("features", [])

        # Start with reasonable chunk size based on total time span
        if time_span_hours <= 168:  # 1 week
            chunk_hours = 24  # 1 day
        elif time_span_hours <= 720:  # 1 month
            chunk_hours = 72  # 3 days
        else:  # Longer periods
            chunk_hours = 168  # 1 week

        current_date = start_dt
        chunks_processed = 0

        # For very long periods, use parallel processing
        if time_span_hours > 168 * 4:  # More than 4 weeks
            return self._search_catalog_parallel(
                host=host, bbox=bbox, start_date=start_dt, end_date=end_dt,
                collections=collections, cloud_coverage=cloud_coverage,
                show_progress=show_progress, min_chunk_hours=min_chunk_hours,
                max_workers=max_workers
            )

        while current_date < end_dt:
            chunk_end = min(current_date + timedelta(hours=chunk_hours), end_dt)
            # Ensure we don't create a 0-duration chunk
            if chunk_end == current_date:
                break

            if show_progress:
                chunks_processed += 1
                # Show appropriate time format based on chunk size
                if chunk_hours >= 24:
                    start_str = current_date.date()
                    end_str = chunk_end.date()
                else:
                    start_str = current_date.strftime("%Y-%m-%d %H:%M")
                    end_str = chunk_end.strftime("%Y-%m-%d %H:%M")
                console.print(f"  Searching {start_str} to {end_str}... ", end="")
            
            result = self.search_catalog(
                host=host,
                bbox=bbox,
                start_date=current_date.isoformat() + "Z",
                end_date=chunk_end.isoformat() + "Z",
                collections=collections,
                limit=500,
                cloud_coverage=cloud_coverage
            )

            items = result.get("features", [])
            all_items.extend(items)

            # Check for pagination and try to get remaining items
            links = result.get("links", [])
            next_link = next((link for link in links if link.get("rel") == "next"), None)

            # If we hit the limit and there's pagination, try to get more items
            while len(items) == 500 and next_link:
                if show_progress:
                    console.print(f"  [dim]Fetching additional page...[/dim]", end="")

                # Make request to next page
                next_response = requests.get(
                    next_link["href"],
                    headers=self.headers
                )

                if next_response.status_code == 200:
                    next_data = next_response.json()
                    next_items = next_data.get("features", [])
                    all_items.extend(next_items)
                    items = next_items  # Update for next iteration

                    # Check for another next link
                    next_links = next_data.get("links", [])
                    next_link = next((link for link in next_links if link.get("rel") == "next"), None)

                    if show_progress:
                        console.print(f" [green]+{len(next_items)} items[/green] (total: {len(all_items)})")
                else:
                    if show_progress:
                        console.print(f" [red]Failed to fetch next page[/red]")
                    break
            
            if show_progress:
                console.print(f"[green]{len(items)} items[/green] (total: {len(all_items)})")
            
            # If we hit the limit, use smaller chunks next time
            if len(items) == 500 and chunk_hours > min_chunk_hours:
                old_chunk_hours = chunk_hours
                chunk_hours = max(min_chunk_hours, chunk_hours // 2)
                if show_progress:
                    if chunk_hours >= 24:
                        chunk_desc = f"{chunk_hours // 24} days"
                    elif chunk_hours >= 1:
                        chunk_desc = f"{chunk_hours} hours"
                    else:
                        chunk_desc = f"{chunk_hours * 60} minutes"
                    console.print(f"  [yellow]Hit limit, reducing chunk size to {chunk_desc}[/yellow]")
            # If we still hit the limit with minimum chunk size, warn the user
            elif len(items) == 500 and chunk_hours == min_chunk_hours:
                if show_progress:
                    console.print(f"  [yellow]Warning: Still hitting 500-item limit with minimum chunk size. May be missing items.[/yellow]")
            
            current_date = chunk_end

        if show_progress and chunks_processed > 1:
            console.print(f"  [green]Completed {chunks_processed} chunks, total items: {len(all_items)}[/green]")

        return all_items

    def _search_catalog_parallel(self,
                                host: str,
                                bbox: Optional[List[float]],
                                start_date: datetime,
                                end_date: datetime,
                                collections: Optional[List[str]],
                                cloud_coverage: Optional[int],
                                show_progress: bool,
                                min_chunk_hours: int,
                                max_workers: int) -> List[Dict]:
        """Parallel version of deep search for very long time periods."""

        # Create chunks for parallel processing
        chunks = []
        current_date = start_date

        while current_date < end_date:
            chunk_end = min(current_date + timedelta(hours=24), end_date)  # 1-day chunks for parallel
            if chunk_end > current_date:
                chunks.append((current_date, chunk_end))
            current_date = chunk_end

        if show_progress:
            console.print(f"  [cyan]Processing {len(chunks)} chunks in parallel with {max_workers} workers...[/cyan]")

        all_items = []

        def process_chunk(chunk_start, chunk_end):
            """Process a single time chunk."""
            result = self.search_catalog(
                host=host, bbox=bbox,
                start_date=chunk_start.isoformat() + "Z",
                end_date=chunk_end.isoformat() + "Z",
                collections=collections, limit=500, cloud_coverage=cloud_coverage
            )
            return result.get("features", [])

        # Process chunks in parallel
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_chunk = {
                executor.submit(process_chunk, chunk_start, chunk_end): (chunk_start, chunk_end)
                for chunk_start, chunk_end in chunks
            }

            for future in as_completed(future_to_chunk):
                chunk_start, chunk_end = future_to_chunk[future]
                try:
                    items = future.result()
                    all_items.extend(items)
                    if show_progress:
                        console.print(f"  [green]✓[/green] {chunk_start.date()} to {chunk_end.date()}: {len(items)} items (total: {len(all_items)})")
                except Exception as e:
                    if show_progress:
                        console.print(f"  [red]✗[/red] {chunk_start.date()} to {chunk_end.date()}: {str(e)}")

        return all_items

    def get_collections(self, max_resolution: Optional[float] = None) -> List[Dict[str, Any]]:
        """Get available collections from UP42 catalog, optionally filtered by resolution."""
        collections_endpoint = f"{self.base_url}/collections"
        
        response = requests.get(
            collections_endpoint,
            headers=self.headers
        )
        
        if response.status_code != 200:
            console.print(f"[red]Error: {response.status_code} - {response.text}[/red]")
            return []
            
        data = response.json()
        collections = data.get("data", [])
        
        if max_resolution:
            filtered = []
            for collection in collections:
                # Get resolution value in meters
                res_val = collection.get("resolutionValue", {})
                if res_val.get("minimum"):
                    resolution = res_val["minimum"]
                    if resolution <= max_resolution:
                        filtered.append(collection)
            return filtered
        
        return collections
    
    def get_taskable_collections(self) -> List[str]:
        """Get list of collection names for high-resolution taskable imagery.
        
        Returns only satellites with ≤0.75m resolution, which are typically
        taskable and represent intentional surveillance rather than routine
        Earth observation (excludes SPOT, Sentinel, Landsat, etc.).
        """
        # Filter to collections with ≤0.75m resolution (taskable satellites)
        high_res_collections = self.get_collections(max_resolution=0.75)
        return [c["name"] for c in high_res_collections]


def display_items(items: List[Dict], format: str = "table"):
    """Display STAC items in specified format."""
    
    if not items:
        console.print("[yellow]No items found[/yellow]")
        return
        
    if format == "json":
        for item in items:
            rprint(JSON.from_data(item))
            console.print("-" * 80)
    else:  # table format
        table = Table(title=f"Found {len(items)} items")
        table.add_column("Date", style="cyan")
        table.add_column("Satellite", style="green")
        table.add_column("Location", style="magenta")
        table.add_column("Cloud %", style="blue")
        table.add_column("ID", style="yellow")
        
        for item in items:
            properties = item.get("properties", {})
            provider_props = properties.get("providerProperties", {})
            
            # Get datetime from various possible fields
            datetime_str = properties.get("datetime")
            if not datetime_str:
                datetime_str = provider_props.get("acquisitionDate")
            if not datetime_str:
                datetime_str = provider_props.get("publicationDate")
            
            # Format datetime
            if datetime_str and datetime_str != "N/A":
                try:
                    dt = datetime.fromisoformat(datetime_str.replace("Z", "+00:00"))
                    datetime_str = dt.strftime("%Y-%m-%d %H:%M")
                except:
                    datetime_str = "N/A"
            else:
                datetime_str = "N/A"
            
            # Get satellite/constellation
            satellite = properties.get("constellation", 
                       properties.get("collection", "N/A"))
            
            # Get location from geometry centroid or bbox
            centroid = provider_props.get("geometryCentroid", {})
            if centroid:
                location_str = f"{centroid.get('lat', 0):.2f}, {centroid.get('lon', 0):.2f}"
            else:
                # Try bbox
                bbox = item.get("bbox", [])
                if bbox and len(bbox) >= 4:
                    lat = (bbox[1] + bbox[3]) / 2
                    lon = (bbox[0] + bbox[2]) / 2
                    location_str = f"{lat:.2f}, {lon:.2f}"
                else:
                    location_str = "N/A"
            
            # Get cloud cover
            cloud_cover = provider_props.get("cloudCover", 
                         properties.get("eo:cloud_cover", "N/A"))
            if cloud_cover != "N/A" and cloud_cover is not None:
                cloud_cover = f"{cloud_cover:.0f}"
            else:
                cloud_cover = "N/A"
            
            # Get ID
            item_id = properties.get("id", 
                     provider_props.get("sourceIdentifier", "N/A"))
            if len(item_id) > 25:
                item_id = item_id[:25] + "..."
            
            table.add_row(
                datetime_str,
                satellite,
                location_str,
                str(cloud_cover),
                item_id
            )
        
        console.print(table)


def analyze_recent_activity(items: List[Dict], taskable_only: bool = False) -> Dict[str, Any]:
    """Analyze patterns in recent imaging activity.
    
    Clusters satellite imagery by location using grid-based clustering
    with adjacent cell merging to avoid boundary splitting. Returns
    hotspots sorted by surveillance intensity.
    """
    
    # Get taskable collection names if filtering
    taskable_collections = set()
    if taskable_only:
        client = UP42Client()
        taskable_collections = set(client.get_taskable_collections())
    
    locations = {}
    collections_count = {}
    daily_count = {}
    filtered_items = []
    
    for item in items:
        properties = item.get("properties", {})
        provider_props = properties.get("providerProperties", {})
        
        # Get collection/constellation name
        collection = properties.get("constellation", 
                    properties.get("collection", "unknown"))
        
        # Skip if filtering for taskable and this isn't in taskable list
        if taskable_only and taskable_collections and collection not in taskable_collections:
            continue
            
        collections_count[collection] = collections_count.get(collection, 0) + 1
        
        # Count by date
        datetime_str = properties.get("datetime")
        if not datetime_str:
            datetime_str = provider_props.get("acquisitionDate")
        if not datetime_str:
            datetime_str = provider_props.get("publicationDate")
            
        if datetime_str:
            try:
                dt = datetime.fromisoformat(datetime_str.replace("Z", "+00:00"))
                date_key = dt.strftime("%Y-%m-%d")
                daily_count[date_key] = daily_count.get(date_key, 0) + 1
            except:
                pass
        
        # Track locations with overlapping grid cells to avoid boundary issues
        centroid = provider_props.get("geometryCentroid", {})
        if centroid:
            lat = centroid.get('lat', 0)
            lon = centroid.get('lon', 0)
        else:
            # Try bbox
            bbox = item.get("bbox", [])
            if len(bbox) >= 4:
                lat = (bbox[1] + bbox[3]) / 2
                lon = (bbox[0] + bbox[2]) / 2
            else:
                continue
        
        # Add to grid cell (simple integer rounding)
        lat_key = int(lat)
        lon_key = int(lon)
        loc_key = f"{lat_key},{lon_key}"
        locations[loc_key] = locations.get(loc_key, 0) + 1
    
    # Merge adjacent hotspots before sorting
    merged_locations = {}
    processed = set()
    
    # Sort locations by count (descending) then by key for deterministic processing
    sorted_locations = sorted(locations.items(), key=lambda x: (-x[1], x[0]))
    
    for loc_key, count in sorted_locations:
        if loc_key in processed:
            continue
            
        lat, lon = map(int, loc_key.split(','))
        cluster_count = count
        cluster_lats = [lat]
        cluster_lons = [lon]
        processed.add(loc_key)
        
        # Check all 8 adjacent cells
        for dlat in [-1, 0, 1]:
            for dlon in [-1, 0, 1]:
                if dlat == 0 and dlon == 0:
                    continue
                adj_key = f"{lat + dlat},{lon + dlon}"
                if adj_key in locations and adj_key not in processed:
                    # Merge if adjacent cell has significant activity (>30% of current)
                    if locations[adj_key] > count * 0.3:
                        cluster_count += locations[adj_key]
                        cluster_lats.append(lat + dlat)
                        cluster_lons.append(lon + dlon)
                        processed.add(adj_key)
        
        # Use center of cluster as key
        center_lat = sum(cluster_lats) // len(cluster_lats)
        center_lon = sum(cluster_lons) // len(cluster_lons)
        cluster_key = f"{center_lat},{center_lon}"
        
        # Keep the higher count if we already have this cluster center
        if cluster_key in merged_locations:
            merged_locations[cluster_key] = max(merged_locations[cluster_key], cluster_count)
        else:
            merged_locations[cluster_key] = cluster_count
    
    # Sort all hotspots by count
    all_hotspots = sorted(merged_locations.items(), key=lambda x: (-x[1], x[0]))
    
    # Calculate threshold (e.g., at least 5 items or 1% of total items, but cap at reasonable maximum)
    min_threshold = max(5, min(50, len(items) * 0.01))
    
    # Filter hotspots above threshold
    significant_hotspots = [(loc, count) for loc, count in all_hotspots if count >= min_threshold]
    
    return {
        "total_items": len(items),
        "collections": collections_count,
        "hotspots": significant_hotspots,
        "min_threshold": min_threshold,
        "daily_activity": dict(sorted(daily_count.items())[-7:])  # Last 7 days
    }


@click.group()
def cli():
    """STAC-Trace: Explore STAC catalogues to discover what's being watched."""
    pass


@cli.command()
@click.option('--all', is_flag=True, help='Show all collections (default: only taskable high-res)')
def collections(all):
    """List available collections in the UP42 catalog."""
    client = UP42Client()
    
    if all:
        collections = client.get_collections()
        title = f"All Available Collections ({len(collections)})"
    else:
        # Show only high-resolution taskable collections by default
        collections = client.get_collections(max_resolution=0.75)
        title = f"High-Resolution Taskable Collections ({len(collections)}) - ≤0.75m resolution"
    
    if not collections:
        return
        
    table = Table(title=title)
    table.add_column("Name", style="cyan")
    table.add_column("Host", style="green")
    table.add_column("Type", style="yellow")
    table.add_column("Resolution", style="magenta")
    
    # Sort by resolution for better readability
    collections.sort(key=lambda x: x.get("resolutionValue", {}).get("minimum", 999))
    
    for collection in collections:
        # Get resolution value
        res_val = collection.get("resolutionValue", {})
        if res_val.get("minimum"):
            resolution = f"{res_val['minimum']}m"
        else:
            resolution = collection.get("resolutionClass", "N/A")
            
        table.add_row(
            collection.get("name", "N/A"),
            collection.get("hostName", "N/A"),
            collection.get("type", "N/A"),
            resolution
        )
    
    console.print(table)


@cli.command()
@click.option('--host', default='oneatlas', help='Host to search (e.g., oneatlas, capella)')
@click.option('--bbox', help='Bounding box (min_lon,min_lat,max_lon,max_lat)')
@click.option('--days', default=30, help='Number of days to look back')
@click.option('--collection', help='Collection to search in')
@click.option('--cloud', type=int, help='Maximum cloud coverage percentage')
@click.option('--limit', default=100, help='Maximum number of results')
@click.option('--format', type=click.Choice(['table', 'json']), default='table', help='Output format')
def search(host, bbox, days, collection, cloud, limit, format):
    """Search for recent satellite imagery."""
    
    client = UP42Client()
    
    # Prepare search parameters
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=days)
    
    bbox_list = None
    if bbox:
        try:
            bbox_list = [float(x) for x in bbox.split(',')]
            if len(bbox_list) != 4:
                console.print("[red]Error: bbox must have 4 values[/red]")
                return
        except ValueError:
            console.print("[red]Error: Invalid bbox format[/red]")
            return
    
    collections_list = [collection] if collection else None
    
    console.print(f"[cyan]Searching {host} for imagery from {start_date.date()} to {end_date.date()}...[/cyan]")
    
    # Perform search
    results = client.search_catalog(
        host=host,
        bbox=bbox_list,
        start_date=start_date.isoformat() + "Z",
        end_date=end_date.isoformat() + "Z",
        collections=collections_list,
        cloud_coverage=cloud,
        limit=limit
    )
    
    if not results:
        return
        
    items = results.get("features", [])
    display_items(items, format)


@cli.command()
@click.option('--host', default='oneatlas', help='Host to analyze')
@click.option('--days', default=7, help='Number of days to analyze')
@click.option('--bbox', help='Bounding box (min_lon,min_lat,max_lon,max_lat)')
@click.option('--infra', is_flag=True, default=False, help='Query infrastructure data for each hotspot')
@click.option('--min-chunk-hours', default=1, type=int, help='Minimum chunk size in hours for API calls (default: 1)')
def hotspots(host, days, bbox, infra, min_chunk_hours):
    """Find locations with recent imaging activity."""
    
    client = UP42Client()
    
    # Prepare search parameters
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=days)
    
    bbox_list = None
    if bbox:
        try:
            bbox_list = [float(x) for x in bbox.split(',')]
            if len(bbox_list) != 4:
                console.print("[red]Error: bbox must have 4 values[/red]")
                return
        except ValueError:
            console.print("[red]Error: Invalid bbox format[/red]")
            return
    
    console.print(f"[cyan]Analyzing {host} activity from {start_date.date()} to {end_date.date()}...[/cyan]")

    # Get taskable collection names to filter at API level (more efficient)
    taskable_collections = client.get_taskable_collections()
    console.print(f"[dim]Found {len(taskable_collections)} taskable collections: {', '.join(taskable_collections[:5])}{'...' if len(taskable_collections) > 5 else ''}[/dim]")

    # Use deep search to get ALL items from taskable collections only (handles 500-item limit automatically)
    items = client.search_catalog_deep(
        host=host,
        bbox=bbox_list,
        start_date=start_date.isoformat().replace("+00:00", "Z"),
        end_date=end_date.isoformat().replace("+00:00", "Z"),
        collections=taskable_collections,
        min_chunk_hours=min_chunk_hours
    )
    
    if not items:
        console.print("[yellow]No items found[/yellow]")
        return
    
    # Analyze activity (already filtered to taskable collections at API level)
    analysis = analyze_recent_activity(items, taskable_only=False)

    # Display analysis
    console.print("\n[bold]Activity Analysis[/bold]")
    console.print(f"Total items: {analysis['total_items']}")
    console.print(f"Min threshold: {analysis.get('min_threshold', 'N/A')}")
    console.print(f"Raw locations found: {len(analysis.get('hotspots', []))}")

    # Collections breakdown
    console.print("\n[bold]Collections:[/bold]")
    for collection, count in analysis['collections'].items():
        console.print(f"  • {collection}: {count} items")
    
    # Hotspots with location names and infrastructure
    if analysis['hotspots']:
        threshold = analysis.get('min_threshold', 5)
        total_found = len(analysis['hotspots'])
        showing = min(10, total_found)
        
        console.print(f"\n[bold]Top {showing} Hotspots:[/bold]")
        if total_found > 10:
            console.print(f"[dim]({total_found} total locations with ≥{int(threshold)} items)[/dim]")
        
        # Show top 10 with geocoding and infrastructure data
        for i, (location, count) in enumerate(analysis['hotspots'][:10]):
            lat, lon = map(float, location.split(','))
            location_name = get_location_name(lat, lon)
            
            # Create Google Earth URL (altitude ~50km for good regional view)
            earth_url = f"https://earth.google.com/web/@{lat},{lon},0a,50000d,35y,0h,0t,0r"
            
            console.print(f"\n  {i+1:2}. [bold cyan]{location_name}[/bold cyan] ({lat}, {lon})")
            console.print(f"      [green]{int(count)} satellite images[/green]")
            console.print(f"      [white]{earth_url}[/white]")
            
            # Query and display infrastructure data if enabled
            if infra:
                console.print(f"      [dim]Querying infrastructure...[/dim]", end="")
                infra_data = get_infrastructure_data(lat, lon, radius_km=5)
                
                if "error" in infra_data:
                    console.print(f"\r      [yellow]Infrastructure query failed[/yellow]                ")
                elif infra_data:
                    console.print(f"\r      [bold]Key infrastructure:[/bold]                    ")
                    
                    # Display categories in priority order
                    category_display = {
                        "strategic": ("Strategic", "[red]", True),      # name, color, show_type
                        "airports": ("Airports", "[cyan]", False),
                        "power": ("Power", "[yellow]", True),
                        "transport": ("Transport", "[blue]", True),
                        "technology": ("Tech/Data", "[magenta]", True),
                        "industrial": ("Industrial", "[green]", False),
                        "healthcare": ("Healthcare", "[white]", True),
                        "education": ("Education", "[cyan]", False),
                        "commercial": ("Commercial", "[dim white]", True),
                        "critical": ("Critical", "[red]", True)
                    }
                    
                    displayed_count = 0
                    for category, items in infra_data.items():
                        if items and displayed_count < 6:  # Limit total output
                            label, color, show_type = category_display.get(category, (category.title(), "", True))
                            
                            if show_type:
                                # Show with type information
                                item_strings = []
                                for item in items[:2]:  # Limit items per category
                                    if item['name'] != "Unnamed":
                                        item_strings.append(f"{item['name']} ({item['type']})")
                                    else:
                                        item_strings.append(f"{item['type']}")
                                items_list = ', '.join(item_strings)
                            else:
                                # Just show names
                                items_list = ', '.join([item['name'] for item in items[:3] if item['name'] != "Unnamed"])
                            
                            if items_list:
                                console.print(f"        {color}• {label}:[/] {items_list}")
                                displayed_count += 1
                else:
                    console.print(f"\r      [dim]No significant infrastructure found[/dim]                ")
    
    # Daily activity
    if analysis['daily_activity']:
        console.print("\n[bold]Daily Activity:[/bold]")
        for date, count in analysis['daily_activity'].items():
            bar = "█" * min(count, 50)
            console.print(f"  {date}: {bar} ({count})")


@cli.command()
@click.option('--lat', required=True, type=float, help='Latitude')
@click.option('--lon', required=True, type=float, help='Longitude')
@click.option('--host', default='oneatlas', help='Host to search')
@click.option('--radius', default=0.1, type=float, help='Search radius in degrees')
@click.option('--days', default=30, help='Number of days to look back')
def watch(lat, lon, host, radius, days):
    """Check what's been watching a specific location."""
    
    client = UP42Client()
    
    # Create bounding box from point and radius
    bbox_list = [
        lon - radius,
        lat - radius,
        lon + radius,
        lat + radius
    ]
    
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=days)
    
    # Get location name
    location_name = get_location_name(lat, lon)
    console.print(f"[cyan]Checking {host} imagery for {location_name} ({lat}, {lon}) ±{radius}° from {start_date.date()} to {end_date.date()}...[/cyan]")
    
    # Search for items at this location
    results = client.search_catalog(
        host=host,
        bbox=bbox_list,
        start_date=start_date.isoformat() + "Z",
        end_date=end_date.isoformat() + "Z",
        limit=100
    )
    
    if not results:
        return
        
    items = results.get("features", [])
    
    if not items:
        console.print("[yellow]No recent imagery found for this location[/yellow]")
        return
    
    # Group by date and collection
    timeline = {}
    for item in items:
        properties = item.get("properties", {})
        provider_props = properties.get("providerProperties", {})
        
        # Get datetime
        datetime_str = properties.get("datetime")
        if not datetime_str:
            datetime_str = provider_props.get("acquisitionDate")
        if not datetime_str:
            datetime_str = provider_props.get("publicationDate")
            
        collection = properties.get("constellation", 
                    properties.get("collection", "unknown"))
        
        if datetime_str:
            try:
                dt = datetime.fromisoformat(datetime_str.replace("Z", "+00:00"))
                date_key = dt.strftime("%Y-%m-%d")
                if date_key not in timeline:
                    timeline[date_key] = []
                timeline[date_key].append({
                    "time": dt.strftime("%H:%M"),
                    "collection": collection,
                    "cloud_cover": provider_props.get("cloudCover", 
                                  properties.get("eo:cloud_cover", "N/A"))
                })
            except:
                pass
    
    # Display timeline
    console.print(f"\n[bold]Imaging Timeline for {location_name}:[/bold]")
    for date in sorted(timeline.keys(), reverse=True):
        console.print(f"\n[green]{date}:[/green]")
        for event in timeline[date]:
            cloud_str = f", cloud: {event['cloud_cover']}%" if event['cloud_cover'] != "N/A" else ""
            console.print(f"  • {event['time']} - {event['collection']}{cloud_str}")


if __name__ == "__main__":
    cli()