# Telink Matter SBOM

This document describes the software bill of materials (SBOM) produced for
Telink Matter firmware builds: what is generated, what it does and does not
guarantee, and how to review the parts that need a human decision.

Read this before consuming or shipping an SBOM from this repository. Several
of the caveats below are not obvious from the output itself.

## Where it runs

The pipeline is [`.github/workflows/telink-build-sbom.yaml`][wf]. It builds one
example (`tl3238x` lighting-app by default) inside the prebuilt Telink
container and emits the SBOM alongside the firmware.

[wf]: ../../../.github/workflows/telink-build-sbom.yaml

The upstream `examples-telink.yaml` does **not** cover this: it builds 23
example targets and only triggers on `master` / `v*-branch`, so it never runs
on `dev-tlk_v1.5`. This workflow exists to fill that gap.

## Artifacts

Each run uploads five artifacts:

| Artifact | Contents | Consumer |
| --- | --- | --- |
| `telink-firmware` | `zephyr.elf`, `.bin`, `.map` | Flashing, size analysis |
| `telink-sbom-spdx-raw` | Four SPDX documents exactly as `west spdx` emits them | Debugging the pipeline |
| `telink-sbom-spdx-enriched` | The same documents with NTIA fields filled in | **Primary deliverable** |
| `telink-sbom-cyclonedx` | CycloneDX 1.6 JSON | SCA platforms that do not read SPDX |
| `telink-sbom-review` | `sbom-review.csv`, `sbom-gaps.md` | Human review |

Ship the **enriched** set, not the raw one. The raw documents leave
`PackageSupplier` empty, set every `PackageLicenseDeclared` to `NOASSERTION`,
and carry a purl for one package out of 142.

## What the SBOM guarantees

Measured on a `tl3238x` lighting-app build:

- **142 packages**, of which **21 are real components** carrying a purl. The
  remaining 121 are CMake build targets (`drivers--gpio`, `kernel`,
  `zephyr-pre0`, ...) — artifacts of the build itself with no upstream project
  and no independent license.
- **1136 dependency relationships**, and 639 file entries with SHA-256.
- All seven **NTIA minimum elements** present after enrichment.

### Source hashes are reproducible; binary hashes are not

Two CI runs of the same commit produced identical hashes for all **561 source
files**, but the five compiled artifacts differed:

```
./app/libapp.a
./modules/openthread/build/src/core/libopenthread-ftd.a
./zephyr/libzephyr.a
./zephyr/zephyr.elf
./zephyr/zephyr_pre0.elf
```

`ar` archives embed member mtimes and ELF files carry a build-id, so these are
not byte-reproducible with the current build flags.

**Consequence:** the SBOM can be used to audit *what source went into a
build*, but it **cannot** yet be used to verify that a shipped binary matches
a given SBOM. Doing that requires a reproducible build (`SOURCE_DATE_EPOCH`
plus `-ffile-prefix-map`), which is not currently enabled.

## Known limitations

### License detection is tag-only

zspdx recognizes only an explicit `SPDX-License-Identifier:` tag. Projects
that embed the full license text instead are reported as `NONE`, no matter how
many lines are scanned — the tag is simply absent.

openthread is the clearest example: its sources carry the complete 28-line
BSD-3-Clause body and no tag, so all 247 of its files come back `NONE` and the
package would be `NOASSERTION` without the manual map described below.

Across the build, **286 file entries have no detected license**. 31 of those
are in `telink_ble_sdk`, which is proprietary vendor code and carries no SPDX
headers by design.

### Package-level licenses are mostly asserted, not derived

zspdx leaves `PackageLicenseDeclared` at `NOASSERTION` for every package. The
enrichment step derives a value where it can, but 132 of 142 packages still
have no declared license because there is no evidence to derive one from —
they are the CMake build targets, which have no independent license to
declare. This is expected, not a defect.

### External references are sparse

Only components with a `PackageDownloadLocation` get a purl. That covers the
21 real components. **Vulnerability correlation therefore works for those 21
and not for the build targets** — which is the correct scope, since a CMake
target is not something a CVE is filed against.

### `-off` in version strings

`PackageVersion` values may end in `-off` or `-dirty`. These are Zephyr west
state markers, not part of the version:

| Suffix | Meaning |
| --- | --- |
| `-dirty` | The working tree had uncommitted changes |
| `-off` | The repository SHA differs from what the west manifest expected |

`-off` appears because the pipeline deliberately checks out the tl_zephyr
revision named in the release notes rather than whatever the manifest points
at. An auditor asking "why does this say `-off`" should be pointed here.

## Reviewing unresolved components

`sbom-review.csv` lists the 21 real components, one per row, with a
`confirmed_license` column. Around 12 are typically blank.

CSV rather than a spreadsheet format on purpose: the review record is itself
what an audit examines, so it has to be diffable in a pull request. A binary
`.xlsx` shows up as "cannot compare" and loses that property. CSV opens
directly in Excel.

The loop:

1. Open `sbom-review.csv` and fill `confirmed_license` with an SPDX identifier
   or expression (for example `BSD-1-Clause`, or `MIT OR GPL-2.0-or-later`).
   The `notes` column says why each row is unresolved.
2. Fold the answers back into the maintained map:

   ```bash
   python3 scripts/tools/telink/sbom_review.py --merge sbom-review.csv
   ```

3. Commit the updated
   [`module_licenses.json`](../../../scripts/tools/telink/module_licenses.json).
   The next run resolves those components automatically and the review list
   shrinks.

`module_licenses.json` holds two sections. `licenses` is applied
automatically. `needs_review` is not applied — it exists so the review report
can explain what is still open. Move an entry up to `licenses` once confirmed.

Human input is a one-off cost that decreases over time: once every component
is confirmed, the review list stays empty unless a new module is introduced.

> **The enrichment step never invents a license.** A component with no
> evidence stays `NOASSERTION`. Filling the map is a legal determination and
> has to be made deliberately, not inferred.

## Maintenance

### Bumping the toolchain container

The container is pinned by digest, not by tag, so the RISC-V toolchain and the
Zephyr tree cannot shift under a build. A mutable tag would mean two SBOMs
from the same commit could disagree.

To move to a newer image, resolve the digest first and update the `image:`
line:

```bash
TOK=$(curl -s "https://ghcr.io/token?scope=repository:project-chip/chip-build-telink:pull&service=ghcr.io" | jq -r .token)
curl -sI -H "Authorization: Bearer $TOK" \
  -H "Accept: application/vnd.docker.distribution.manifest.v2+json" \
  https://ghcr.io/v2/project-chip/chip-build-telink/manifests/<TAG> \
  | grep -i docker-content-digest
```

### Pinning the Zephyr and BLE SDK revisions

`TELINK_ZEPHYR_REV` and `TELINK_BLE_SDK_REV` in the workflow are set to the
matched pair from the
[release notes](./releases/telink_release_notes.md). Upstream CI pins a
slightly different tl_zephyr revision marked "for developers purpose"; this
pipeline deliberately uses the released pair instead so the SBOM has a
reproducible baseline.

## Why the workarounds exist

Three things in the pipeline are non-obvious enough to warrant an explanation,
because they will otherwise look like accidental complexity.

### `CONFIG_BUILD_OUTPUT_META=y`

`west spdx` needs a metadata file that Zephyr's top-level `CMakeLists.txt`
only generates when this option is set — otherwise it actively deletes the
file. This mirrors Zephyr's own SBOM test at
`tests/application_development/software_bill_of_materials/`, which sets
exactly this one option.

### `west spdx --init` before the build

The CMake file-based API query file has to exist *before* CMake configures,
otherwise there is no compile graph for zspdx to walk. Zephyr's SBOM test does
the same thing via a `PreLoad.cmake`.

### The runtime patch to `walker.py`

zspdx in the pinned Zephyr revision crashes with a `NoneType` dereference in
`collectTargetDependencies` on any target that has no build product on disk.
Newer Zephyr guards the equivalent line. The build script applies the guard at
runtime rather than forking the SDK; it detects an already-patched file and
fails loudly if the surrounding source changes, so a Zephyr bump cannot
silently turn it into a no-op.

This is worth reporting upstream. The walker has clearly not been exercised
against a non-standard Zephyr integration like Matter's.
