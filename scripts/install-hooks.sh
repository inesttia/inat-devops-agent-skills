#!/usr/bin/env bash
# Point this clone's git hooks at the versioned .githooks/ directory (one-time, per clone).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
chmod +x .githooks/*
git config core.hooksPath .githooks
echo "git hooks installed from .githooks/ (core.hooksPath). pre-push will run the IaC cost preview."
echo "Requires: python3 with boto3 and PyYAML, and AWS credentials that allow pricing:GetProducts."
