# Canada experiment replay

For the project overview, see the [team guide](../../docs/team-guide.md).
The `seconds.html` and `template.html` files are build templates, not ready-to-view
demos. Complete real recordings and generated HTML are distributed separately.
A generated page also includes Compare for matched v2 replay JSON recordings;
see [Live / Compare setup and status](LIVE.md).

The current page includes Live / Replay tabs. Live requires the loopback relay
and a manually prepared VM session; see [LIVE.md](LIVE.md). The HTML alone
continues to support offline replay. New Live modes use the actual northbound
`shortest_path` and `qos_priority`; historical archives retain their old label.

## One-second replay (current demo)

```sh
python3 tools/replay/build_seconds.py /path/to/seconds-20260905.tar.gz /path/to/tinyleo-replay.html
```

Reads the archive directly, without extraction. Includes all 301 recorded
Shortest-path controller states at t=0…300 seconds, with a default playback
interval of 1 second. Each frame includes its actual controller timing and VM
memory telemetry. Play/pause, seeking, and Canada/global views work offline;
playback stops at the end and pauses when the tab is hidden.

Continuous ping statistics describe the whole run. Other packet measurements
are labeled by batch start time and span multiple states; they are not exact
per-frame measurements. The Geographic 20-frame preflight and historical
failure/recovery narrative are deliberately excluded from this full-run demo.

Browser regression test (requires Playwright and Chrome):

```sh
node tools/replay/test_seconds.cjs /absolute/path/to/tinyleo-replay.html
```

Checks all 301 frames, one-second playback boundaries, pause/seek/end behavior,
English UI, and mobile page width.

## Historical 12-epoch replay

Build a single HTML file from the extracted September 1 Canada experiment:

```sh
python3 tools/replay/build.py /path/to/canada-parity-20260901T232741Z /path/to/replay.html
```

Open the HTML in a browser. No Python packages, server, VM, or internet are
needed to view it. The builder uses Python's standard library. The artifact
contains both routing modes, all 12 controller snapshots, and raw measurements
at epochs 0, 5, 6, 7, 11. Play/pause, frame selection, algorithm selection,
playback speed, and Canada/global viewport controls are provided.

This is recorded replay, not live telemetry. ISL/GSL lines describe controller
snapshots; failure handling can change the network after a snapshot is written.
The raw packet measurements are shown separately. Missing observations are not
interpolated. The reported traceroute count includes responding hops even when
the destination was not reached; it is not always a complete route length.
Fixed ground station coordinates come from example_canada_parity.py.

Map boundary: https://github.com/johan/world.geo.json/blob/master/countries/CAN.geo.json
(Natural Earth, public-domain geographic data). Map coordinates use a simple
equirectangular projection and are illustrative, not distance measurements.

Demo sequence: epoch 5 baseline → epoch 6 failure → epoch 7 recovery;
switch between shortest and geographic at each frame. This historical replay
does not connect to live VM telemetry; the newer Live mode is documented above.
