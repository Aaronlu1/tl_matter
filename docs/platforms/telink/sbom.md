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
| `telink-sbom-spdx-raw` | The SPDX documents exactly as emitted | Debugging the pipeline |
| `telink-sbom-spdx-enriched` | The same documents with NTIA fields filled in | **Primary deliverable** |
| `telink-sbom-cyclonedx` | CycloneDX 1.6 JSON | SCA platforms that do not read SPDX |
| `telink-sbom-review` | `sbom-review.csv`, `sbom-gaps.md` | Human review |

Ship the **enriched** set, not the raw one. The raw documents leave
`PackageSupplier` empty, set every `PackageLicenseDeclared` to `NOASSERTION`,
and carry a purl for one package out of 143.

## What the SBOM guarantees

Measured on a `tl3238x` lighting-app build:

- **143 packages and 927 file entries** with SHA-256, across five documents:

  | Document | Packages | Files | Covers |
  | --- | ---: | ---: | --- |
  | `zephyr.spdx` | 21 | 561 | Zephyr and its modules |
  | `matter-sources.spdx` | 1 | 288 | The Matter stack (see below) |
  | `build.spdx` | 100 | 76 | CMake build targets |
  | `modules-deps.spdx` | 20 | 0 | Module dependency references |
  | `app.spdx` | 1 | 2 | The example application |

- Of the 143 packages, **22 are real components** carrying a purl. The
  remaining 121 are CMake build targets (`drivers--gpio`, `kernel`,
  `zephyr-pre0`, ...) — artifacts of the build itself with no upstream project
  and no independent license.
- All seven **NTIA minimum elements** present after enrichment.

### The Matter stack is tracked via ninja, not zspdx

zspdx walks the CMake codemodel, but the Matter chip library is built by GN
through `ExternalProject_Add` (`config/common/cmake/chip_gn.cmake`), so GN's
targets are invisible to it. Without extra work the entire protocol stack
appears as a single opaque package with a commit SHA and `FilesAnalyzed:
false`.

`gn_sources_to_spdx.py` closes that gap and emits `matter-sources.spdx` with
the 288 sources that actually went into the firmware — `src/app` (93),
`src/lib` (50), `src/platform` (32), `src/protocols` (28), `src/credentials`
(18), `src/transport` (13) and the rest.

The discriminator is **`.ninja_log`**, not `compile_commands.json`. The
database lists what gn *could* build and includes test targets that
`chip_build_tests = false` keeps out of the firmware — 711 of its 999 entries
are never built. Intersecting ninja's actual outputs with the database's `-o`
paths is what yields the real set. Two approaches that look reasonable and do
not work:

- `gn desc` on the root target. Failed repeatedly: the target label
  `//config/telink/chip-gn:telink` does not resolve, and gn needs the pigweed
  environment active.
- Filtering the database by compiler. 974 of 999 entries use
  `riscv64-zephyr-elf-g++`, `pw_unit_test` files included, so it
  discriminates nothing.

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

### License detection: zspdx reads tags only

zspdx recognizes only an explicit `SPDX-License-Identifier:` tag. Projects
that embed the full license text instead are reported as `NONE`, no matter how
many lines are scanned — the tag is simply absent.

This is not a fringe case. **Both** major inputs to this build do it:

- **openthread** carries the complete 28-line BSD-3-Clause body and no tag, so
  all 247 of its files come back `NONE`. The manual map below covers it.
- **The Matter stack** carries the full Apache-2.0 boilerplate and no tag. A
  sample of 300 files found zero SPDX tags. `gn_sources_to_spdx.py`
  recognises the Apache-2.0 grant sentence directly, which resolves 286 of the
  288 sources it emits.

  That second pass is deliberately narrow: it matches the Apache-2.0 grant
  sentence, not "any licence-looking text", so it cannot mislabel a file under
  a different licence.

Across the build, **286 file entries still have no detected license**. 31 of
those are in `telink_ble_sdk`, which is proprietary vendor code and carries no
SPDX headers by design.

> Anything added here that reads licences should check for full-text headers
> first. Assuming SPDX tags are present is the mistake this section exists to
> prevent — it was made twice while building this pipeline.

### Package-level licenses are mostly asserted, not derived

zspdx leaves `PackageLicenseDeclared` at `NOASSERTION` for every package. The
enrichment step derives a value where it can, but 132 of 143 packages still
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
