#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

GIT_SHA="${GIT_SHA:-$(git rev-parse --short=12 HEAD)}"
REGISTRY="${REGISTRY:-harbor.local:30080/library}"
APP_IMAGE="${APP_IMAGE:-${REGISTRY}/llm-serving:${GIT_SHA}}"
MOCK_IMAGE="${MOCK_IMAGE:-${REGISTRY}/llm-serving-mock:${GIT_SHA}}"
SEMGREP_BIN="${SEMGREP_BIN:-$(command -v semgrep || true)}"

PYTHON_BIN="${PYTHON_BIN:-python3}"
"$PYTHON_BIN" -m venv .venv-ci
./.venv-ci/bin/python -m pip install --disable-pip-version-check -r requirements.txt
PYTHONPATH=. ./.venv-ci/bin/python -m pytest -q

for source_path in app tests pilot scripts Dockerfile Jenkinsfile.ci Jenkinsfile.cd requirements.txt; do
  if [[ -e "$source_path" ]]; then
    gitleaks dir --no-banner --redact --exit-code 1 "$source_path"
  fi
done

if [[ -n "$SEMGREP_BIN" && -x "$SEMGREP_BIN" ]]; then
  SEMGREP_ENABLE_VERSION_CHECK=0 SEMGREP_SEND_METRICS=off \
    "$SEMGREP_BIN" scan --config p/python --metrics=off --quiet --error app
else
  echo "ERROR: semgrep is not installed; refusing to mark source scan complete" >&2
  exit 1
fi

docker build --pull \
  --label "org.opencontainers.image.revision=$GIT_SHA" \
  --label "org.opencontainers.image.source=https://github.com/lglgl/llm-serving" \
  -t "$APP_IMAGE" -f Dockerfile .
docker build --pull -t "$MOCK_IMAGE" -f pilot/Dockerfile.mock pilot

trivy image --scanners vuln --severity CRITICAL --exit-code 1 "$APP_IMAGE"
trivy image --scanners vuln --severity CRITICAL --exit-code 1 "$MOCK_IMAGE"

NETWORK="llm-serving-ci-${GIT_SHA}"
MOCK_NAME="llm-serving-ci-mock-${GIT_SHA}"
APP_NAME="llm-serving-ci-api-${GIT_SHA}"
cleanup() {
  docker rm -f "$APP_NAME" "$MOCK_NAME" >/dev/null 2>&1 || true
  docker network rm "$NETWORK" >/dev/null 2>&1 || true
}
trap cleanup EXIT
docker network create "$NETWORK" >/dev/null
docker run -d --name "$MOCK_NAME" --network "$NETWORK" --network-alias mock-vllm "$MOCK_IMAGE" >/dev/null
docker run -d --name "$APP_NAME" --network "$NETWORK" \
  -p "127.0.0.1::8000" \
  -e VLLM_API_BASE=http://mock-vllm:8001/v1 \
  -e VLLM_MODEL=Qwen/Qwen3-8B \
  -e DEFAULT_MODEL=qwen3:8b \
  "$APP_IMAGE" >/dev/null

BOUND_PORT="$(docker port "$APP_NAME" 8000/tcp | sed 's/.*://')"
echo "CI smoke using dynamically assigned Docker host port ${BOUND_PORT}"
"./.venv-ci/bin/python" scripts/smoke_api.py "http://127.0.0.1:${BOUND_PORT}"

printf 'CI_PILOT_RESULT=passed\nAPP_IMAGE=%s\nMOCK_IMAGE=%s\nGIT_SHA=%s\n' \
  "$APP_IMAGE" "$MOCK_IMAGE" "$GIT_SHA"
