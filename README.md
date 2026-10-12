<div align="center">

# Chinese Postman Optimizer

**A personal project for turning OpenStreetMap street data into practical routes.**

Built around a real use case: taking a town or city's street network, exporting it from Overpass Turbo as GPX, optimizing the route, and importing it into the Suunto app for use on a Suunto 5 watch.

</div>

---

## Why I made this

I originally made this tool for myself.

I wanted to map the streets of a city or a small village and then follow that route with my Suunto 5. I used [Overpass Turbo](https://overpass-turbo.eu/) to export street data from [OpenStreetMap](https://www.openstreetmap.org/) as a GPX file, then processed that file with this Python script so I could import the result into the Suunto app and put it on my watch.

The idea is to create a route that covers the street network while avoiding unnecessary repeated sections as much as possible. That makes it useful for exploring an area systematically, rather than choosing a normal point-to-point route.

I built it to solve my own mapping problem, but I figured other people might find it useful too — whether they have the same Suunto setup or just want to work with street networks for their own reasons.

## What it does

The tool uses the **Chinese Postman Problem (CPP)**, a route-planning problem focused on traversing every edge in a network while minimizing repeated travel.

The script processes GPX track and route data and creates an optimized GPX track. It is designed to preserve the original coordinates rather than snapping nearby points together.

### Current features

- **Street-network route optimization** — creates a route intended to cover the edges in the imported network with as little repeated travel as possible.
- **OpenStreetMap workflow** — works with GPX data you can export from Overpass Turbo.
- **Coordinate precision** — avoids snapping or merging nearby coordinates.
- **Disconnected components** — can connect separate parts of the network with straight-line bridges, or keep only the largest connected component.
- **Route checks and statistics** — reports information about route distance, processing time, and edge coverage.
- **Batch processing** — accepts individual GPX files, directories, glob patterns, or a JSON configuration file.
- **Parallel processing** — can process multiple input files concurrently.
- **Checkpointing** — saves progress during processing, with an option to disable it.

> **A note on bridges:** when separate components are connected, the script may add straight-line links that do not follow actual streets. Check the generated route before using it.

## My workflow

This is the workflow I built the project around:

1. Open [Overpass Turbo](https://overpass-turbo.eu/) and query the street network for a city, town, or village using OpenStreetMap data.
2. Export the result as a GPX file.
3. Run the GPX file through Chinese Postman Optimizer.
4. Import the resulting GPX into the Suunto app, provided it is compatible with the app's current import options.
5. Sync the route to a **Suunto 5** and use it while exploring the area.

The exact Overpass Turbo query depends on the area and the type of streets you want to include. The output also depends on the geometry and connectivity of the source data.

## Requirements

- Python 3.8 or newer
- [`networkx`](https://networkx.org/)

## Installation

1. Install Python 3.8 or newer.
2. Install the dependency:

   ```bash
   pip install -r requirements.txt
   ```
3. Clone or download this repository.
4. Put your GPX files in an input directory, or pass their paths to the script.

## Quick start

### Process the default input directory

```bash
python postman.py
```

With no input arguments, the script looks for `.gpx` files in an `input/` directory next to `postman.py`. Output files are written to `./output/` by default.

### Process one GPX file

```bash
python postman.py input.gpx
```

### Process a directory

```bash
python postman.py ./routes/
```

### Process files matching a pattern

```bash
python postman.py "*.gpx" --out-dir ./optimized/
```

### Process multiple files in parallel

```bash
python postman.py ./routes/ --parallel
```

### Use a JSON configuration file

```bash
python postman.py config.json
```

The JSON configuration file should contain an `inputs` array:

```json
{
  "inputs": [
    "routes/route1.gpx",
    "routes/route2.gpx"
  ]
}
```

### View available options

```bash
python postman.py --help
```

## Command-line arguments

| Argument | Description |
|---|---|
| `inputs` | Optional input paths: GPX files, directories, glob patterns, or a JSON configuration file. If omitted, the script searches `input/*.gpx` next to the script. |
| `-o`, `--out-dir` | Output directory for optimized GPX files. |
| `-p`, `--parallel` | Process multiple files in parallel when more than one task is pending. |
| `-w`, `--workers` | Number of parallel worker processes. |
| `-r`, `--resume` | Resume-related option declared by the CLI. See the implementation note below. |
| `-c`, `--clear-checkpoint` | Clear the saved checkpoint. If used without input files, exits after clearing. |
| `--checkpoint` | Enable checkpointing. |
| `--no-checkpoint` | Disable checkpointing. |
| `--bridge-components` | Keep disconnected components and connect them using straight-line bridges. |
| `--drop-components` | Keep only the largest connected component. |

> **Implementation note:** `--resume` is defined by the command-line parser, but the current main processing logic does not explicitly use this flag to change task selection.

## Output

Optimized files are written to the selected output directory. Output filenames are prefixed with `optimized_`, for example:

```text
output/
└── optimized_route.gpx
```

The output is a GPX track intended for use in compatible mapping and route-planning apps. Always check the route in your target app before relying on it for navigation.

## Planned future support

The current workflow is GPX-based. I'd like to explore support for more formats in future releases, depending on what would be useful and practical to implement:

- **KML / KMZ** — useful for viewing and exchanging routes and geographic data with tools such as Google Earth.
- **GeoJSON** — useful for working with road networks and geographic features in GIS tools.
- **GeoPackage (GPKG)** — a common GIS format for storing spatial vector data.
- **Shapefile** — useful for importing road-network data from GIS workflows.
- **FIT** — a fitness-activity format that may be useful for interoperability with sports devices and apps, though route/course support would need to be handled carefully.

These are ideas for future support, not features available in the current version. GPX remains the supported input/output format for the workflow described above.

## Limitations

- The tool processes the geometry present in the input data; it does not automatically retrieve missing streets from OpenStreetMap.
- The quality of the result depends on the GPX export and how the source network is connected.
- Straight-line bridges between disconnected components may not represent real streets.
- The output may need to be checked or adjusted before importing it into a navigation or sports app.
- The current validation output is a diagnostic aid, not a formal guarantee that every real-world street has been covered.

## Releases

See the repository's [Releases](../../releases) page for published versions and release notes.

---

<div align="center">

Made for my own street-mapping workflow — shared in case it helps yours, too.

</div>
