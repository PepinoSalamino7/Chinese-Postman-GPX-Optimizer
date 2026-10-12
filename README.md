<div align="center">

# Chinese Postman Optimizer

**v6.0 — Ultra-Precise Edition**

Optimize GPX road networks with the Chinese Postman Problem (CPP), with a focus on preserving every original coordinate and road segment.

</div>

---

## Overview

Chinese Postman Optimizer is a Python command-line tool that processes GPX tracks and routes to generate an inspection route covering road-network edges while minimizing additional traversal.

Version 6.0 focuses on coordinate precision: it does not snap or merge nearby coordinates. GPX track and route points are used to build a multigraph, and the resulting Eulerian circuit is exported as a new GPX track.

## Features

- **Exact coordinate handling** — no coordinate snapping or merging of distinct coordinates.
- **GPX support** — reads tracks (`trk`), routes (`rte`), and waypoints (`wpt`).
- **Dead-end backtracking** — adds return traversal along dead-end paths while retaining intermediate points.
- **Chinese Postman optimization** — pairs odd-degree nodes using shortest paths and minimum-weight matching.
- **Disconnected component options** — either connect components with straight-line bridges or keep only the largest component.
- **Route validation** — reports edge coverage and potentially missing segments.
- **Progress and statistics** — reports distances, processing time, route efficiency, warnings, and validation results.
- **Batch processing** — accepts individual GPX files, directories, glob patterns, or a JSON configuration file.
- **Parallel processing** — optionally processes multiple input files concurrently.
- **Checkpointing** — saves progress and can be disabled.
- **Terminal output** — supports `NO_COLOR` for environments where ANSI colors should be disabled.

## Requirements

- Python 3.8 or newer
- [`networkx`](https://networkx.org/)

The script uses Python's standard library for GPX/XML handling, command-line parsing, JSON, file operations, and parallel processing.

## Installation

1. Install Python 3.8 or newer.
2. Install the dependency:

   ```bash
   pip install networkx
   ```
3. Download or clone this repository.
4. Put your GPX files in an input directory, or pass their paths as command-line arguments.

## Quick Start

### Use the default input directory

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

### Process files matching a glob pattern

```bash
python postman.py "*.gpx" --out-dir ./optimized/
```

### Process files in parallel

```bash
python postman.py ./routes/ --parallel
```

### Use a JSON configuration file

```bash
python postman.py config.json
```

The JSON configuration file should contain an `inputs` array listing the input paths:

```json
{
  "inputs": [
    "routes/route1.gpx",
    "routes/route2.gpx"
  ]
}
```

### Show help

```bash
python postman.py --help
```

## Command-Line Arguments

| Argument | Description | Default |
|---|---|---|
| `inputs` | Zero or more GPX files, directories, glob patterns, or a JSON configuration file. | Searches `input/*.gpx` next to the script |
| `-o`, `--out-dir` | Output directory for optimized GPX files. | `./output` |
| `-p`, `--parallel` | Process multiple files in parallel when more than one task is pending. | Disabled |
| `-w`, `--workers` | Number of parallel worker processes. | Number of CPUs reported by Python |
| `-r`, `--resume` | Resume-related option declared by the CLI. See note below. | Disabled |
| `-c`, `--clear-checkpoint` | Clear the saved checkpoint. If used without input files, exits after clearing. | Disabled |
| `--checkpoint` | Enable checkpointing. | Enabled |
| `--no-checkpoint` | Disable checkpointing. | — |
| `--bridge-components` | Keep disconnected components and connect them using straight-line bridges. | Enabled |
| `--drop-components` | Keep only the largest connected component; smaller components are excluded. | Disabled |

> **Implementation note:** `--resume` is defined in the command-line parser, but the current main processing logic does not explicitly use this flag to change task selection.

## Output

Generated files are written to the selected output directory. Each output filename is prefixed with `optimized_`, for example:

```text
output/
└── optimized_route.gpx
```

The exported GPX contains an optimized track. The script prints a summary including success status, route distance, processing time, and edge-validation counts.

## Disconnected Components

By default, the optimizer attempts to retain and connect disconnected components. It chooses a connection order using a nearest-component strategy and inserts straight-line links between selected points.

To keep only the largest component:

```bash
python postman.py ./routes/ --drop-components
```

**Important:** Straight-line bridges may not follow real roads. The script reports when these links are added, so inspect the resulting GPX before using it for navigation.

## Checkpointing

Checkpointing is enabled by default. Progress is stored in `.postman_checkpoint.json` next to the script.

Disable checkpointing for a run:

```bash
python postman.py ./routes/ --no-checkpoint
```

Clear the saved checkpoint:

```bash
python postman.py --clear-checkpoint
```

## Releases

See the repository's [Releases](../../releases) page for published versions and release notes.

## Limitations

- The tool processes the geometry represented in the input GPX data; it does not fetch missing roads from an external map service.
- When disconnected components are bridged, straight-line connections can be created that do not correspond to actual roads.
- The route-validation implementation checks whether original coordinate-pair edges appear in the generated route. Treat its results as a diagnostic rather than a formal proof of complete geometric coverage.
- Test the output GPX in your intended mapping or navigation software before relying on it.

---

<div align="center">

Made for precise GPX road-network processing.

</div>
