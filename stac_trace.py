#!/usr/bin/env python3

import os
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any, Tuple
import click
import requests
from dotenv import load_dotenv
from pystac_client import Client
from rich.console import Console
from rich.table import Table
from rich.json import JSON
from rich import print as rprint

load_dotenv()

console = Console()

# Simple in-memory cache for geocoding results
geocode_cache = {}


def get_location_name(lat: float, lon: float) -> str:
    """Get a human-readable location name from coordinates using Nominatim."""
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
            
        return response.json()
    
    def search_catalog_deep(self, 
                           host: str = "oneatlas",
                           bbox: Optional[List[float]] = None,
                           start_date: Optional[str] = None,
                           end_date: Optional[str] = None,
                           collections: Optional[List[str]] = None,
                           cloud_coverage: Optional[int] = None,
                           show_progress: bool = True,
                           taskable_only: bool = False) -> List[Dict]:
        """Deep search that automatically handles API limits by time-slicing."""
        
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
        
        # Calculate time span
        time_span = (end_dt - start_dt).days
        
        # If less than 7 days, do single search
        if time_span <= 7:
            result = self.search_catalog(
                host=host, bbox=bbox, start_date=start_date, end_date=end_date,
                collections=collections, limit=500, cloud_coverage=cloud_coverage
            )
            return result.get("features", [])
        
        # Otherwise, split into chunks (5-day chunks work well)
        chunk_days = 5
        current_date = start_dt
        chunks_processed = 0
        total_chunks = (time_span + chunk_days - 1) // chunk_days  # Ceiling division
        
        while current_date < end_dt:
            chunk_end = min(current_date + timedelta(days=chunk_days), end_dt)
            
            if show_progress:
                chunks_processed += 1
                console.print(f"  Searching {current_date.date()} to {chunk_end.date()}... ", end="")
            
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
            
            if show_progress:
                console.print(f"[green]{len(items)} items[/green] (total: {len(all_items)})")
            
            # If we hit the limit, use smaller chunks next time
            if len(items) == 500 and chunk_days > 1:
                chunk_days = max(1, chunk_days // 2)
                if show_progress:
                    console.print(f"  [yellow]Hit limit, reducing chunk size to {chunk_days} days[/yellow]")
            
            current_date = chunk_end
        
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
        """Get list of collection names for high-resolution taskable imagery."""
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
    """Analyze patterns in recent imaging activity."""
    
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
    
    # Calculate threshold (e.g., at least 5 items or 1% of total items)
    min_threshold = max(5, len(items) * 0.01)
    
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
def hotspots(host, days, bbox):
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
    
    # Use deep search to get ALL items (handles 500-item limit automatically)
    items = client.search_catalog_deep(
        host=host,
        bbox=bbox_list,
        start_date=start_date.isoformat().replace("+00:00", "Z"),
        end_date=end_date.isoformat().replace("+00:00", "Z")
    )
    
    if not items:
        console.print("[yellow]No items found[/yellow]")
        return
    
    # Analyze activity (filtering to only taskable high-res satellites)
    analysis = analyze_recent_activity(items, taskable_only=True)
    
    # Display analysis
    console.print("\n[bold]Activity Analysis[/bold]")
    console.print(f"Total items: {analysis['total_items']}")
    
    # Collections breakdown
    console.print("\n[bold]Collections:[/bold]")
    for collection, count in analysis['collections'].items():
        console.print(f"  • {collection}: {count} items")
    
    # Hotspots with location names
    if analysis['hotspots']:
        threshold = analysis.get('min_threshold', 5)
        total_found = len(analysis['hotspots'])
        showing = min(10, total_found)
        
        console.print(f"\n[bold]Top {showing} Hotspots:[/bold]")
        if total_found > 10:
            console.print(f"[dim]({total_found} total locations with ≥{int(threshold)} items)[/dim]")
        
        # Show top 10 with geocoding
        for i, (location, count) in enumerate(analysis['hotspots'][:10]):
            lat, lon = map(float, location.split(','))
            location_name = get_location_name(lat, lon)
            
            # Create Google Earth URL (altitude ~50km for good regional view)
            earth_url = f"https://earth.google.com/web/@{lat},{lon},0a,50000d,35y,0h,0t,0r"
            
            console.print(f"  {i+1:2}. {location_name} ({lat}, {lon}): {int(count)} items")
            console.print(f"      [white]{earth_url}[/white]")
    
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