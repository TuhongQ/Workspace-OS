#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/common.sh"; run_cli audit --workspace "${1:-$HOME/Workspace}"

