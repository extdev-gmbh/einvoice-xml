#!/bin/sh
# Install the e-invoice validator of the test gate: a Java runtime and Mustang-CLI.
#
# Mustang checks a ZUGFeRD/Factur-X PDF as a whole: PDF/A-3 (veraPDF), the embedded XML
# against the schema and against the EN 16931 rules. tests/test_validator.py runs it on
# the generated files; it finds the jar through EINVOICE_VALIDATOR_JAR.
#
# Called by the CI `test` jobs and by scripts/test.sh, so all install the same, pinned
# validator. Needs a Debian image with Python (python:*-slim) and, to install
# Java, root.
#
#   scripts/install-einvoice-validator.sh [directory]   # default: /opt/einvoice-validator
#
# The jar is downloaded once per directory: a file with the pinned checksum is kept.
set -eu

MUSTANG_VERSION="2.26.0"
MUSTANG_SHA256="42d7868cb68264874a7b8cab4c3587b03b23ccc7cd72373da917f66758bb9736"
MUSTANG_URL="https://repo1.maven.org/maven2/org/mustangproject/Mustang-CLI/$MUSTANG_VERSION/Mustang-CLI-$MUSTANG_VERSION.jar"

target="${1:-/opt/einvoice-validator}"
jar="$target/Mustang-CLI.jar"

if ! command -v java >/dev/null 2>&1; then
    apt-get update
    apt-get install --yes --no-install-recommends default-jre-headless
    rm -rf /var/lib/apt/lists/*
fi

verified() {
    [ -f "$jar" ] && echo "$MUSTANG_SHA256  $jar" | sha256sum --check --status
}

if ! verified; then
    mkdir -p "$target"
    python3 -c 'import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])' "$MUSTANG_URL" "$jar"
    if ! verified; then
        echo "install-einvoice-validator.sh: checksum of $jar does not match Mustang-CLI $MUSTANG_VERSION" >&2
        rm -f "$jar"
        exit 1
    fi
fi

echo "install-einvoice-validator.sh: Mustang-CLI $MUSTANG_VERSION at $jar"
