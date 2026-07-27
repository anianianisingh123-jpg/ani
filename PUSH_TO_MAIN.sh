#!/bin/bash
# Fixes corrupted agents.py/tools.py on GitHub main by force-pushing the good local commit.
set -euo pipefail
cd "$(dirname "$0")"
echo "Local commit with full rework:"
git log -1 --oneline 13add07
echo
echo "Remote main is currently broken (agents/tools are placeholders)."
echo "Pushing local good commit to origin/main..."
git push --force-with-lease origin 13add07:main
echo
echo "Verify:"
git fetch origin
echo -n "agents.py bytes on remote: "
git show origin/main:mas_sector_system/agents.py | wc -c
echo -n "tools.py bytes on remote: "
git show origin/main:mas_sector_system/tools.py | wc -c
git log -1 --oneline origin/main
echo "Done."
