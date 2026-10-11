<div align="center">

# Chinese Postman Optimizer

**Optimize GPX road networks using the Chinese Postman Problem (CPP).**

A Python utility for generating efficient inspection routes while preserving the original geographic geometry of GPX tracks.

</div>

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Usage](#usage)
- [Command-Line Arguments](#command-line-arguments)
- [Input and Output](#input-and-output)
- [Releases](#releases)

## Overview

The **Chinese Postman Optimizer** processes GPX track data to calculate an efficient route that covers the edges of a road network while minimizing repeated traversal.

It is designed for spatial road networks where preserving geographic precision matters. The tool aims to retain original GPX coordinates and line geometries without unwanted coordinate merging or curve straightening.

## Features

- **Geographic precision** — preserves raw GPX node coordinates and original line geometries.
- **Disconnected component handling** — optionally removes smaller disconnected sub-graphs.
- **Edge validation** — generates summary statistics for edge coverage and missing segments after optimization.
- **Batch processing** — supports individual GPX files, glob patterns, and directories.
- **Parallel processing** — can process multiple routes or files in parallel.
- **Checkpoint control** — allows progress checkpointing to be disabled.

## Requirements

- Python 3.8 or newer
- [`networkx`](https://networkx.org/)

## Installation

1. Make sure Python 3.8 or newer is installed.
2. Install the required dependency:

   ```bash
   pip install networkx
   ```

3. Place `postman.py` and your input GPX files in the appropriate locations.
4. Run the script using one of the examples below.

## Usage

Run these commands from the directory containing `postman.py`, unless you have configured another path.

### Automatic input and output

```bash
python postman.py
```

Uses the script's configured default input and output locations.

### Process a specific GPX file

```bash
python postman.py input.gpx output.gpx
```

Passes an input GPX file and an output GPX file to the script.

### Process files matching a glob pattern

```bash
python postman.py "*.gpx" --out-dir ./optimized/
```

Processes files matching the pattern and writes generated GPX files to `./optimized/`.

### Process a directory in parallel

```bash
python postman.py ./routes/ --parallel
```

Processes routes from the specified directory with parallel processing enabled.

### Use a configuration file

```bash
python postman.py config.json
```

Passes a JSON configuration file to the script.

### Disable checkpointing

```bash
python postman.py --no-checkpoint
```

Disables progress checkpointing during execution.

### Remove smaller disconnected components

```bash
python postman.py --drop-components
```

Enables removal of smaller disconnected sub-graphs, retaining the largest connected component.

## Command-Line Arguments

| Argument | Description |
|---|---|
| `input_path` | Optional path to a GPX file, a glob pattern, or a directory. |
| `-o`, `--out-dir` | Sets the output directory for generated GPX files. |
| `--drop-components` | Removes smaller disconnected sub-graphs and retains the largest connected component. |
| `--no-checkpoint` | Disables progress checkpointing during execution. |
| `--parallel` | Enables parallel processing for multiple routes or files. |

> **Note:** The available arguments and their exact behavior depend on the implementation in `postman.py`. Run `python postman.py --help` if supported by your version to view the script's built-in help.

## Input and Output

- **Input:** GPX files containing track or road-network data.
- **Output:** Optimized GPX route files, written to the configured output location.

The exact output filenames, directory defaults, and validation reports depend on the script's configuration and implementation.

## Releases

For stable releases and packaged versions, visit the repository's [**Releases**](../../releases) page.

---

<div align="center">

Made for efficient GPX road-network optimization.

</div>
