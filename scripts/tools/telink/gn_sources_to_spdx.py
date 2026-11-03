#!/usr/bin/env python3
#
# Copyright (c) 2026 Project CHIP Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
"""Emit SPDX File entries for the Matter sources that GN compiled.

Why this exists
---------------
zspdx walks the CMake codemodel, but the Matter stack is built by GN through
ExternalProject_Add (config/common/cmake/chip_gn.cmake), so GN's targets are
invisible to it. The whole protocol stack therefore appears in the SBOM as one
opaque package with a commit SHA and FilesAnalyzed: false.

Getting the real set of files turned out to be the hard part, and three
plausible approaches were wrong:

  * Filtering compile_commands.json by path -- the database lists what gn
    *could* build, not what ninja built. It includes test targets that
    chip_build_tests = false keeps out of the firmware.
  * gn desc on the root target -- failed for three rounds (missing pigweed
    environment, then a target label that does not resolve).
  * Filtering by compiler -- 974 of 999 entries use riscv64-zephyr-elf-g++,
    pw_unit_test files included, so it discriminates nothing.

What works is ninja's own execution log. .ninja_log records the commands ninja
actually ran, so intersecting its outputs with the compile database's -o paths
yields exactly the sources that went into the build.

Usage
-----
    gn_sources_to_spdx.py --ninja-log <gn_out>/.ninja_log \
                          --compile-db <gn_out>/compile_commands.json \
                          --repo-root <repo> --out <file.spdx> \
                          [--name NAME] [--purl PURL] [--version VER]
"""

import argparse
import hashlib
import os
import re
import sys
import uuid

# Same scan depth zspdx uses (zspdx ScannerConfig.numLinesScanned defaults to
# 20), so the two stay comparable.
_LICENSE_SCAN_LINES = 20
_LICENSE_RE = re.compile(r"SPDX-License-Identifier:\s*(.+)")


def spdx_id_safe(text):
    """Make a string safe for use in an SPDXID (letters, digits, . and -)."""
    return re.sub(r"[^A-Za-z0-9.-]", "-", text)


def parse_ninja_log(path, out_dir):
    """Return the set of output paths ninja actually produced."""
    built = set()
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("#"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 4:
                built.add(os.path.normpath(os.path.join(out_dir, parts[3])))
    return built


def parse_compile_db(path):
    """Return {normalised object path: source path} from a compile database."""
    import json
    with open(path, encoding="utf-8") as f:
        entries = json.load(f)

    src_for_obj = {}
    for e in entries:
        cmd = e.get("command") or " ".join(e.get("arguments", []))
        toks = cmd.split()
        obj = None
        for i, t in enumerate(toks):
            if t == "-o" and i + 1 < len(toks):
                obj = toks[i + 1]
                break
        if obj and e.get("file"):
            src_for_obj[os.path.normpath(obj)] = e["file"]
    return src_for_obj


def sha1_of(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def license_of(path):
    """Read an SPDX-License-Identifier from the file head, or None."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for _ in range(_LICENSE_SCAN_LINES):
                line = f.readline()
                if not line:
                    break
                m = _LICENSE_RE.search(line)
                if m:
                    value = m.group(1).strip().rstrip("*/").strip()
                    return value or None
    except OSError:
        pass
    return None


def select_sources(ninja_log, compile_db, gn_out_dir):
    """Return the sorted list of sources that were compiled and still exist."""
    built = parse_ninja_log(ninja_log, gn_out_dir)
    src_for_obj = parse_compile_db(compile_db)

    objs = [b for b in built if b.endswith((".o", ".obj"))]
    sources = {src_for_obj[o] for o in objs if o in src_for_obj}
    return sorted(s for s in sources if os.path.isfile(s)), len(objs), len(src_for_obj)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ninja-log", required=True,
                    help="path to the GN build's .ninja_log")
    ap.add_argument("--compile-db", required=True,
                    help="path to the GN build's compile_commands.json")
    ap.add_argument("--repo-root", required=True,
                    help="repository root, used to make paths relative")
    ap.add_argument("--out", required=True, help="SPDX document to write")
    ap.add_argument("--name", default="matter-chip-sources",
                    help="PackageName for the emitted package")
    ap.add_argument("--purl", default=None, help="purl for the package")
    ap.add_argument("--version", default=None, help="PackageVersion")
    ap.add_argument("--namespace", default=None,
                    help="DocumentNamespace (default: derived from --purl)")
    args = ap.parse_args()

    gn_out_dir = os.path.dirname(os.path.abspath(args.ninja_log))
    sources, n_objs, n_db = select_sources(args.ninja_log, args.compile_db, gn_out_dir)

    if not sources:
        sys.exit(f"ERROR: no compiled sources found.\n"
                 f"  ninja log   : {args.ninja_log}\n"
                 f"  compile db  : {args.compile_db}\n"
                 f"  object files in log: {n_objs}, entries in db: {n_db}")

    repo_root = os.path.abspath(args.repo_root)
    rows = []
    for src in sources:
        try:
            rel = os.path.relpath(src, repo_root)
        except ValueError:
            rel = src
        rows.append({
            "rel": "./" + rel.replace(os.sep, "/"),
            "sha1": sha1_of(src),
            "sha256": sha256_of(src),
            "license": license_of(src),
        })

    # SPDX 2.3 requires a package verification code: SHA1 over the sorted
    # concatenation of the member files' SHA1s.
    verification = hashlib.sha1(
        "".join(sorted(r["sha1"] for r in rows)).encode()).hexdigest()

    pkg_id = "SPDXRef-" + spdx_id_safe(args.name)
    namespace = args.namespace or (
        (args.purl or "https://github.com/telink-semi/tl_matter") + "/chip-gn")

    lines = [
        "SPDXVersion: SPDX-2.3",
        "DataLicense: CC0-1.0",
        "SPDXID: SPDXRef-DOCUMENT",
        f"DocumentName: {args.name}",
        f"DocumentNamespace: {namespace}",
        "Creator: Tool: gn_sources_to_spdx.py",
    ]
    import datetime
    lines.append("Created: " + datetime.datetime.now(
        datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    lines.append("")
    lines.append(f"Relationship: SPDXRef-DOCUMENT DESCRIBES {pkg_id}")
    lines.append("")
    lines.append(f"##### Package: {args.name}")
    lines.append(f"PackageName: {args.name}")
    lines.append(f"SPDXID: {pkg_id}")
    if args.version:
        lines.append(f"PackageVersion: {args.version}")
    if args.purl:
        lines.append(f"ExternalRef: PACKAGE_MANAGER purl {args.purl}")
    lines.append("PackageDownloadLocation: " + (args.purl or "NOASSERTION"))
    lines.append("FilesAnalyzed: true")
    lines.append(f"PackageVerificationCode: {verification}")
    lines.append("PackageLicenseConcluded: NOASSERTION")
    lines.append("PackageLicenseDeclared: NOASSERTION")
    lines.append("PackageCopyrightText: NOASSERTION")
    lines.append("")

    seen = {}
    for r in rows:
        fid = "SPDXRef-File-" + spdx_id_safe(os.path.basename(r["rel"]))
        # Disambiguate duplicate basenames, which are common in Matter
        # (every cluster directory has a CodegenIntegration.cpp).
        n = seen.get(fid, 0) + 1
        seen[fid] = n
        if n > 1:
            fid = f"{fid}-{n}"
        lines.append(f"FileName: {r['rel']}")
        lines.append(f"SPDXID: {fid}")
        lines.append(f"FileChecksum: SHA1: {r['sha1']}")
        lines.append(f"FileChecksum: SHA256: {r['sha256']}")
        lic = r["license"] or "NONE"
        lines.append(f"LicenseConcluded: {lic}")
        lines.append(f"LicenseInfoInFile: {lic}")
        lines.append("FileCopyrightText: NOASSERTION")
        lines.append("")

    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))

    licensed = sum(1 for r in rows if r["license"])
    print(f"objects in ninja log : {n_objs}")
    print(f"db entries           : {n_db}")
    print(f"sources emitted      : {len(rows)}")
    print(f"  with SPDX license  : {licensed}")
    print(f"  without            : {len(rows) - licensed}")
    print(f"verification code    : {verification}")
    print(f"written              : {args.out}")


if __name__ == "__main__":
    main()
