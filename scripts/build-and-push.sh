#!/usr/bin/env bash
# Build the batcontrol image with podman and push it to the local registry.
#
#   scripts/build-and-push.sh              # build + push <sha>, latest
#   NO_PUSH=1 scripts/build-and-push.sh    # build only
#   PLATFORM=linux/arm64 scripts/build-and-push.sh
#
# Tags: the short commit SHA (with -dirty for uncommitted changes), the git
# tag of HEAD if there is one, and latest.
set -euo pipefail

REGISTRY="${REGISTRY:-192.168.178.63:32768}"
IMAGE="${IMAGE:-batcontrol}"
PLATFORM="${PLATFORM:-linux/amd64}"

cd "$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"

SHA="$(git rev-parse --short HEAD)"
TAG="$SHA"
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  TAG="${SHA}-dirty"
  echo "warning: uncommitted changes, tagging as ${TAG}" >&2
fi
GIT_TAG="$(git describe --tags --exact-match HEAD 2>/dev/null || true)"
VERSION="${GIT_TAG:-$TAG}"

REF="${REGISTRY}/${IMAGE}"
TAGS=("${REF}:${TAG}" "${REF}:latest")
[ -n "$GIT_TAG" ] && [ "$TAG" = "$SHA" ] && TAGS+=("${REF}:${GIT_TAG}")

echo "Building ${REF}:${TAG} (${PLATFORM})"
podman build \
  --platform "$PLATFORM" \
  --build-arg VERSION="$VERSION" \
  --build-arg GIT_SHA="$(git rev-parse HEAD)" \
  $(printf -- '--tag %s ' "${TAGS[@]}") \
  .

if [ -n "${NO_PUSH:-}" ]; then
  echo "NO_PUSH set, not pushing: ${TAGS[*]}"
  exit 0
fi

# The registry speaks plain HTTP.
for ref in "${TAGS[@]}"; do
  echo "Pushing ${ref}"
  podman push --tls-verify=false "$ref"
done

echo "Done. Pull on the NAS with: ${REF}:${TAG}"
