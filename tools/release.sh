#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# release.sh: tag an SDK release. Refuses a dirty tree, a development version or an existing tag,
# runs the tests, then creates the local annotated tag <version> (the version number alone, as 0.1.0's). It pushes nothing.
set -euo pipefail
cd "$(dirname "$0")/.."

version="$(python3 -c 'import sys; sys.path.insert(0, "python"); import bollardeck; print(bollardeck.__version__)')"
tag="${version}"

if [[ "${version}" == *dev* ]]; then
  echo "release: ${version} is a development version; set the release version in python/bollardeck/_version.py, js/bollardeck.js and c/bollardeck.h first" >&2
  exit 1
fi
if [[ -n "$(git status --porcelain)" ]]; then
  echo "release: the working tree is not clean" >&2
  exit 1
fi
if git rev-parse -q --verify "refs/tags/${tag}" >/dev/null; then
  echo "release: ${tag} already exists" >&2
  exit 1
fi

python3 tools/sync_spec.py check
python3 -m unittest discover -s tests

git tag -a "${tag}" -m "Bollawax Bollard SDK ${version}"
echo "release: created ${tag}. Push it yourself: git push origin ${tag}"
