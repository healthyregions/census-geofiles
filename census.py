import os
import csv
import sys
import json
import shutil
import threading
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import geopandas as gpd
from tqdm import tqdm
import requests
import boto3
import click
from dotenv import load_dotenv

load_dotenv()

CACHE_DIR = Path(".cache")
LOOKUPS_DIR = Path("lookups")

def load_lookups():
    lookups = {}
    for f in LOOKUPS_DIR.glob("*.json"):
        with open(f, "r") as o:
            data = json.load(o)
            lookups[f.stem] = data

    return lookups

## create lookups now so they can be used to validate choices for arg parsing
LOOKUPS = load_lookups()

YEAR_CHOICES = []
SCALE_CHOICES = set()
GEOG_CHOICES = set()
for year, v in LOOKUPS['sources'].items():
    YEAR_CHOICES.append(year)
    for scale, geogs in v.items():
        SCALE_CHOICES.add(scale)
        for geog in geogs.keys():
            GEOG_CHOICES.add(geog)

SCALE_CHOICES = list(SCALE_CHOICES)
GEOG_CHOICES = list(GEOG_CHOICES)

def download_file(url, filepath, desc=None, progress_bar=False, no_cache: bool = False):
    if Path(filepath).is_file() and not no_cache:
        if progress_bar:
            print(f"{desc}: using cached file")
        return filepath

    # Streaming, so we can iterate over the response.
    r = requests.get(url, stream=True)

    # Total size in bytes.
    total_size = int(r.headers.get("content-length", 0))
    block_size = 1024

    if progress_bar:
        t = tqdm(total=total_size, unit="iB", unit_scale=True, desc=desc)

    with open(filepath, "wb") as f:
        for data in r.iter_content(block_size):
            if progress_bar:
                t.update(len(data))
            f.write(data)

    if progress_bar:
        t.close()

    return filepath

def upload_to_s3(path: Path, progress_bar: bool = False):
    s3 = boto3.resource("s3")
    bucket = os.getenv("AWS_BUCKET_NAME")
    prefix = os.getenv("S3_UPLOAD_PREFIX")
    region = "us-east-2"

    key = f"{prefix}/{path.name}" if prefix else path.name
    cb = S3ProgressPercentage(str(path)) if progress_bar else None
    s3.Bucket(bucket).upload_file(str(path), key, Callback=cb)

    out_url = f"https://{bucket}.s3.{region}.amazonaws.com/{key}"
    if progress_bar:
        print("\n  " +out_url)
    return out_url

def write_to_uploads_file(year, scale, geography, url):

    uploads_list = Path(LOOKUPS_DIR, "uploads-list.csv")
    out_rows = [{
        "geography": geography,
        "year":year,
        "scale": scale,
        "url": url,
        "uploaded": datetime.now(ZoneInfo("US/Central")).strftime("%Y-%m-%d %H:%M:%S")
    }]
    if uploads_list.is_file():
        with open(uploads_list, "r") as o:
            reader = csv.DictReader(o)
            for row in reader:
                if not row["url"] == url:
                    out_rows.append(row)
    out_rows.sort(key=lambda x: (x["geography"], x["year"], x["scale"]))
    with open(uploads_list, "w") as o:
        writer = csv.DictWriter(o, fieldnames=[
            "geography", "year", "scale", "url", "uploaded"
        ])
        writer.writeheader()
        writer.writerows(out_rows)

class S3ProgressPercentage(object):
    def __init__(self, filename):
        self._filename = filename
        self._size = float(os.path.getsize(filename))
        self._seen_so_far = 0
        self._lock = threading.Lock()

    def __call__(self, bytes_amount):
        # To simplify, assume this is hooked up to a single filename

        def b_to_mb(bytes):
            return round(bytes / (1024 * 1024), 2)

        with self._lock:
            self._seen_so_far += bytes_amount
            percentage = (self._seen_so_far / self._size) * 100
            sys.stdout.write(
                "\r - %s  %s / %s  (%.2f%%)"
                % (
                    Path(self._filename).name,
                    b_to_mb(self._seen_so_far),
                    b_to_mb(self._size),
                    percentage,
                )
            )
            sys.stdout.flush()


class CensusGeoETL:
    def __init__(self, year: str, geography: str, scale: str, verbose=False, destination: Path=None):
        self.verbose = verbose

        self.year = year
        self.geography = geography
        self.scale = scale

        self.output_dir = destination if destination else Path(CACHE_DIR, self.geography, "processed")
        self.output_dir.mkdir(exist_ok=True, parents=True)
        self.output_files = []

    @property
    def name_string(self):
        return f"{self.geography}-{self.year}-{self.scale}"

    def log(self, message):
        if self.verbose:
            print(message)

    def download_all_files(self, no_cache=False):
        download_dir = Path(
            CACHE_DIR, self.geography, "raw", self.year, self.scale
        )
        download_dir.mkdir(exist_ok=True, parents=True)

        file_urls = LOOKUPS["sources"][self.year][self.scale][
            self.geography
        ]["file_list"]

        url_prefix = os.getenv("MIRROR_URL", "https://www2.census.gov/geo")
        download_urls = [f"{url_prefix}{i}" for i in file_urls]
        if self.verbose:
            for i in download_urls:
                self.log(f" -{i}")
            self.log("downloading...")

        out_paths = []
        for url in download_urls:
            filename = url.split("/")[-1]
            outpath = Path(download_dir, filename)
            out_path = download_file(
                url,
                outpath,
                desc=f" - {filename}",
                progress_bar=self.verbose,
                no_cache=no_cache,
            )
            out_paths.append(out_path)

        return out_paths

    def unzip_files(self, paths):
        shp_paths = []
        for p in paths:
            name = p.name
            shp_file = Path(p.parent, name.replace("zip", "shp"))
            shutil.unpack_archive(p, p.parent)
            shp_paths.append(shp_file)

        return shp_paths

    def create_dataframe_from_files(self, paths):
        df_list = []
        for p in paths:
            df = gpd.read_file(p)
            df_list.append(df)

        if len(df_list) > 1:
            out_df = gpd.GeoDataFrame(
                pd.concat(df_list, ignore_index=True), crs=df_list[0].crs
            )
        else:
            out_df = df_list[0]

        return out_df

    def add_herop_id_to_dataframe(self, df: pd.DataFrame):
        lvl = LOOKUPS["summary-levels"][self.geography]
        suffixes = LOOKUPS["sources"][self.year][self.scale][
            self.geography
        ]["herop_id_suffixes"]

        df["HEROP_ID"] = df.apply(
            lambda row: f"{lvl}US{''.join([row[i] for i in suffixes])}", axis=1
        )

        return df

    def add_bbox_to_dataframe(self, df: pd.DataFrame):
        df = pd.concat([df, df.bounds], axis=1)

        def concat_bounds(row):
            minx = round(row["minx"], 3)
            miny = round(row["miny"], 3)
            maxx = round(row["maxx"], 3)
            maxy = round(row["maxy"], 3)
            return f"{minx},{miny},{maxx},{maxy}"

        df["BBOX"] = df.apply(concat_bounds, axis=1)

        return df

    def add_label_to_dataframe(self, df: pd.DataFrame):
        name_field = LOOKUPS["sources"][self.year][self.scale][
            self.geography
        ]["name_field"]

        def generate_label(row):
            lsad = row.get("LSAD")
            name = row.get(name_field)
            if lsad:
                position = None
                if lsad in LOOKUPS["lsad"]:
                    lsad_value = LOOKUPS["lsad"][lsad]["value"]
                    position = LOOKUPS["lsad"][lsad]["position"]
                else:
                    for k, v in LOOKUPS["lsad"].items():
                        if lsad == v["value"]:
                            lsad_value = lsad
                            position = v["position"]

                if position:
                    if position == "prefix":
                        name = f"{lsad_value} {name}"
                    else:
                        name = f"{name} {lsad_value}"

            return name

        df["LABEL"] = df.apply(generate_label, axis=1)

        return df

    def export_to_shapefile(self, df: pd.DataFrame):

        processed_dir = Path(self.output_dir, f"{self.name_string}-shp")
        processed_dir.mkdir(parents=True, exist_ok=True)
        outfile_shp = Path(processed_dir, f"{self.name_string}.shp")
        df.to_file(outfile_shp)

        shutil.make_archive(processed_dir, "zip", processed_dir)

        shp_files = list(processed_dir.glob("*"))
        zip_file = Path(f"{processed_dir}.zip")

        self.output_files.append(zip_file)

        return {
            "files": shp_files,
            "zipped": zip_file,
        }

    def export_to_geojson(self, df: pd.DataFrame, overwrite=False):

        df = df.to_crs("EPSG:4326")
        outfile = Path(self.output_dir, f"{self.name_string}.geojson")

        if not outfile.is_file() or overwrite:
            df.to_file(outfile, driver="GeoJSON")

        self.output_files.append(outfile)

        return outfile

    def export_to_pmtiles(self, geojson_path):

        outfile_pmtiles = Path(self.output_dir, f"{self.name_string}.pmtiles")
        cmd = [
            os.getenv("TIPPECANOE_PATH"),
            # "-zg",
            # tried a lot of zoom level directives, and seems like for block group
            # (which I believe is the densest)shp_paths 10 is needed to preserve shapes well enough.
            "-z10",
            "-x",
            "STATEFP",
            "-x",
            "COUNTYFP",
            "-x",
            "COUNTYNS",
            "-x",
            "TRACTCE",
            "-x",
            "BLKGRPCE",
            "-x",
            "STATENS",
            "-x",
            "STATE",
            "-x",
            "AFFGEOID",
            "-x",
            "CENSUSAREA",
            "-x",
            "GEOID",
            "-x",
            "GEO_ID",
            "-x",
            "STUSPS",
            "-x",
            "NAME",
            "-x",
            "LSAD",
            "-x",
            "ALAND",
            "-x",
            "AWATER",
            "-x",
            "minx",
            "-x",
            "miny",
            "-x",
            "maxx",
            "-x",
            "maxy",
            "--no-simplification-of-shared-nodes",
            "--coalesce-densest-as-needed",
            "--extend-zooms-if-still-dropping",
            "--projection",
            "EPSG:4326",
            "-o",
            str(outfile_pmtiles),
            "-l",
            f"{self.name_string}",
            "--force",
            str(geojson_path),
        ]
        self.log(" ".join(cmd))
        subprocess.run(cmd)

        self.output_files.append(outfile_pmtiles)

        return outfile_pmtiles

    def run_job(self, formats: list, no_cache: bool=False):

        print(f"\nPROCESSING: {self.geography}, {self.scale}, {self.year}")

        self.log("downloading files...")
        paths = self.download_all_files(no_cache=no_cache)

        self.log("unzipping files...")
        unzipped = self.unzip_files(paths)

        self.log("creating dataframe...")
        df = self.create_dataframe_from_files(unzipped)

        self.log("add HEROP_ID...")
        df = self.add_herop_id_to_dataframe(df)

        self.log("add BBOX...")
        df = self.add_bbox_to_dataframe(df)

        self.log("add LABEL...")
        df = self.add_label_to_dataframe(df)

        if "shp" in formats:
            print("generating shapefile...")
            self.export_to_shapefile(df)

        geojson_path = None
        if "geojson" in formats:
            print("generating geojson...")
            geojson_path = self.export_to_geojson(df, overwrite=True)

        if "pmtiles" in formats:
            print("generating pmtiles...")

            # need geojson for this, but use existing if it was created already
            if not geojson_path:
                geojson_path = self.export_to_geojson(df, overwrite=True)
            self.export_to_pmtiles(geojson_path)

# call this function from external modules for full batch processing
# need to handle how to pass tippecanoe into this environment
def process_all_sources():

    for y, v in LOOKUPS["sources"].items():
        for s, z in v.items():
            for g in z.keys():
                client = CensusGeoETL(y, g, s)
                client.run_job(formats=['geojson', 'shp'])

@click.command()
@click.option(
    "--geography",
    "-g",
    type=click.Choice(GEOG_CHOICES),
    default=GEOG_CHOICES,
    multiple=True,
    help="Specify a geography to prepare. If left empty, all geographies will be processed.",
)
@click.option(
    "--year",
    "-y",
    type=click.Choice(YEAR_CHOICES),
    default=YEAR_CHOICES,
    multiple=True,
    help="Specify one or more years. If left empty, all years will be processed."
)
@click.option(
    "--scale",
    "-s",
    type=click.Choice(SCALE_CHOICES),
    default=SCALE_CHOICES,
    multiple=True,
    help="Specify one or more scales of geographic boundary file. If left empty, all scales will be processed",
)
@click.option(
    "--format",
    "-f",
    type=click.Choice(["shp", "geojson", "pmtiles"]),
    default=["shp", "geojson", "pmtiles"],
    multiple=True,
    help="Choose what output formats will be created. Options are `shp` (shapefile), `geojson` "
    "(GeoJSON), and/or `pmtiles` (PMTiles). If left empty, all formats will be exported",
)
@click.option(
    "--upload",
    is_flag=True,
    default=False,
    help="Upload the processed files to S3. Bucket name, AWS creds, and prefix will be acquired from environment variables."
)
@click.option(
    "--no-cache",
    is_flag=True,
    default=False,
    help="Force re-retrieval of source files.",
)
@click.option(
    "--destination",
    default=None,
    help="Output directory for export. If not provided, results will be in .cache/{{geography}}/processed.",
    type=click.Path(
        resolve_path=True,
        path_type=Path,
    ),
)
@click.option(
    "--verbose",
    is_flag=True,
    default=False,
    help="Enable verbose output during process.",
)
def run_command(
    geography,
    year,
    scale,
    format,
    destination,
    upload,
    no_cache,
    verbose,
):
    """This command retrieves geodata from the US Census Bureau's FTP server, merges the files into single,
    nation-wide coverages, and then exports the merged files into various formats. Optionally upload these
    files directly to S3."""

    if "pmtiles" in format and not os.getenv("TIPPECANOE_PATH"):
        print("TIPPECANOE_PATH is not set, but is needed to support PMTiles output.")
        exit()

    print("year(s):", year)
    print("geography(s):", geography)
    print("scale(s):", scale)

    ## compile all argument sets into combinations to process
    combos = []

    print("checking input...")
    for y in year:
        for s in scale:
            for g in geography:
                if y not in LOOKUPS["sources"] \
                    or s not in LOOKUPS["sources"][y] \
                    or g not in LOOKUPS["sources"][y][s]:
                    print(f"✘ {g} -> {y} -> {s} (no matching source information)")
                    continue
                print(f"✔ {g} -> {y} -> {s}")
                combos.append((y, s, g))
    print(f"{len(combos)} year/geography/scale combinations will be processed")
    print("output format(s):", format)

    for y, s, g in combos:

        client = CensusGeoETL(y, g, s, verbose=verbose, destination=destination)
        client.run_job(formats=format, no_cache=no_cache)

        if upload:
            print(f"uploading {len(client.output_files)} files to S3...")
            for path in client.output_files:
                url = upload_to_s3(path, progress_bar=verbose)

                ## only write to the uploads list if this is our default config
                if os.getenv("AWS_BUCKET_NAME") == "herop-geodata" \
                    and os.getenv("S3_UPLOAD_PREFIX") == "census":
                    write_to_uploads_file(y, s, g, url)

    print("\ndone.")

if __name__ == "__main__":
    run_command()