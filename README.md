# census-geofiles

A processing pipeline for creating standardized nation-wide geography files from the US Census Bureau. The command retrieves geodata from the [US Census Bureau's FTP server](https://www2.census.gov/geo) (or a data mirror if specified), merges the files into single, nation-wide coverages, adds a few standard fields, and then exports the merged files into various formats. Optionally upload these files directly to S3.

[Direct file access](https://healthyregions.github.io/geodata/downloads.html) -- You can download or remotely access files we have uploaded to our own S3 bucket.

## Details

Given a geography, year, and scale, all matching files in the Census FTP will be processed accordingly:

1. Downloaded and unzipped within `.cache/`
2. Loaded and merged into a single geopandas dataframe
3. 3 fields added to the data frame:
    - `LABEL`: A human readable label is calculated using each unit's name and proper LSAD
    - `BBOX`: The bounding box of each feature is calculated and concatenated into a single text field with this format: "{minx},{miny},{maxx},{maxy}"
    - `HEROP_ID`: This is our own unique identifier (very similar to GEOID) to facilitate joins, and you can read more about the rationale behind it below.
4. The data frame is exported to one or more of the following file formats: Shapefile, GeoJSON, and PMTiles

<details>
  <summary><strong>About HEROP_IDs</strong></summary>

  In some of our projects we use what we call a <strong>HEROP_ID</strong> to identify geographic boundaries defined by the US Census Bureau, which is a slight variation on the commonly used standard <strong>GEOID</strong>. Our format is similar to what the American FactFinder used (now data.census.gov). 

  A HEROP_ID consists of three parts:

  1. The 3-digit [Summary Level Code](https://www.census.gov/programs-surveys/geography/technical-documentation/naming-convention/cartographic-boundary-file/carto-boundary-summary-level.html) for this geography. Common summary level codes are:
      - `040` -- **State**
      - `050` -- **County**
      - `140` -- **Census Tract**
      - `150` -- **Census Block Group**
      - `860` -- **Zip Code Tabulation Area (ZCTA)**
  2. The 2-letter string `US`
  3. The standard [GEOID](https://www.census.gov/programs-surveys/geography/guidance/geo-identifiers.html) for the given unit (length depends on unit summary)
      - GEOIDs are, in turn, hierarchical aggregations of FIPS codes

  Expanding out the FIPS codes for the five summary levels shown above, the full IDs would look like:

  | summary level | format | length | example |
  |---|---|---|---|
  |State|`040US` + `STATE (2)`|7|`040US17` (Illinois)|
  |County|`050US` + `STATE (2)` + `COUNTY (3)`|10|`050US17019` (Champaign County)|
  |Tract|`140US` + `STATE (2)` + `COUNTY (3)` + `TRACT (6)`|16|`140US17019005900`|
  |Block Group|`150US` + `STATE (2)` + `COUNTY (3)` + `TRACT (6)` + `BLOCK GROUP (1)`|17|`150US170190059002`|
  |ZCTA|`860US` + `ZIP CODE (5)`|10|`860US61801`|

  The advantages of this composite ID are:
  
  1. Unique across all geographic areas in the US
  2. Will always be forced to string formatting
  3. Easy to programmatically change back into the more standard GEOIDs

  **Convert to GEOID (integers)**

  The `HEROP_ID` can be converted back to standard GEOIDs by removing the first 5 characters, or by taking everything after the substring "US". Here are some examples of what this looks like in different software:
  
  - Excel: `REPLACE(A1, 1, 5, "")`
  - R: `geoid <- str_split_i(HEROP_ID, "US", -1)`
  - Python: `geoid = HEROP_ID.split("US")[1]`
  - JavaScript: `const geoid = HEROP_ID.split("US")[1]`

</details>

<details>
    <summary><strong>About file formats</strong></summary>

- **GeoJSON** A simple plain text format that is good for small to medium size datasets and can be used in a wide variety of web and desktop software [learn more](https://geojson.org/)
- **PMTiles** A "cloud-native" vector format that is very fast in the right web mapping environment [learn more](https://docs.protomaps.com/pmtiles/)
- **Shapefiles** Used in scripting and desktop software for performant display and analysis [learn more](https://www.geographyrealm.com/what-is-a-shapefile/)
    - **R Example**: `sf` allows you to directly open remote, zipped shapefiles without downloading them [learn more, `read_sf` seems not to be documented though (?)](https://r-spatial.github.io/sf):

        ```
        library('sf')
        tracts <- read_sf('/vsizip//vsicurl/https://herop-geodata.s3.us-east-2.amazonaws.com/oeps/tract-2018-500k-shp.zip')
        ```
    - **Python Example**: `geopandas` allows you to directly open remote, zipped shapefiles files without downloading them [learn more](https://geopandas.org/en/stable/docs/reference/api/geopandas.read_file.html):
        ```
        import geopandas as gpd
        tracts = gpd.read_file("/vsizip//vsicurl/https://herop-geodata.s3.us-east-2.amazonaws.com/oeps/state-2010-500k-shp.zip")
        ```

</details>

## Install

```
git clone https://github.com/healthyregions/census-geofiles
cd census-geofiles
python3 -m venv env && source ./env/bin/activate
pip install -e .
```

To create exports in PMTiles format, you must also install [tippecanoe](https://github.com/felt/tippecanoe?tab=readme-ov-file#installation) and provide the path to its executable through an environment variable or command line argument (see below)

## Configuration

A few environment variables should be set before running the command.

```
cp .env.example .env
```

Our defaults are provided in the example file along with comments on each variable. These variables can be overwritten at runtime like so:

```
AWS_BUCKET_NAME=my-bucket python ./census.py etc...
```

### Available mirrors

By default, the process will download files directly from the US Census FTP, https://www2.census.gov/geo. You can direct it to use mirrors of that FTP if needed.

|Institution|Link|`MIRROR_URL`|
|-|-|-|
|University of Chicago|[browse](https://datamirror.lib.uchicago.edu/census-tiger)|`https://pub-a835f667d17f4b6691fafec7e9ede33d.r2.dev`|

### Sources lookup

The file [lookups/sources.json](./lookups/sources.json) is a master list of all file urls and important field names for each year, geography, and scale. This is necessary because field names and file naming conventions have changed over the years (and I have had trouble running `ls`-type commands on the Census FTP server so for now this config is all just hard-coded).

## Usage

```
python ./census.py [OPTIONS]

```

Options:

  - -g, --geography [place|bg|tract|state|zcta|county]
    - Specify a geography to prepare. If left
                                  empty, all geographies will be processed.
  - -y, --year [2010|2018|2020]
    - Specify one or more years. If left empty,
                                  all years will be processed.
  - -s, --scale [500k|tiger]
    - Specify one or more scales of geographic boundary file. If left empty, all scales will be processed
  - -f, --format [shp|geojson|pmtiles]
    - Choose what output formats will be created. Options are `shp` (shapefile), `geojson` (GeoJSON), and/or `pmtiles` (PMTiles). If left empty, all formats will be exported
  - --upload
    - Upload the processed files to S3. Bucket name, AWS creds, and prefix will be acquired from environment variables.
  - --no-cache
    - Force re-retrieval of source files.
  - --destination
    - Output directory for export. If not provided, results will be in .cache/{{geography}}/processed.
  - --verbose
    - Enable verbose output during process.
  - --help
    - Show this message and exit.

The available choices for geography, year, and scale are collected from `sources.json` which will continue to expand, so the best way to see all options is by running:

```
python ./census.py --help
```

If no arguments are provided, the entire `sources` lookup will be traversed and an attempt will be made to generate each file format (ESRI Shapefile, GeoJSON, and PMTiles) for every configured year, geography, and scale.

### Examples

```
python ./census.py -y 2020 -g state -s 500k -f geojson --destination .
```

Result: A new GeoJSON file in the local directory, from the 500k Cartographic Boundary shapefile, 2020 vintage.

```
python ./census.py -g bg -s 500k -f pmtiles --upload
```

Result: 500k scale cartographic boundary files for block groups will be merged into nation-wide coverage and exported to PMTiles, one file per available year. Each file will be uploaded to the S3 bucket as described via environment variables.
