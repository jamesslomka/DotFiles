#!/bin/bash

# General
git config --global user.name "James Slomka"
git config --global user.email james.slomka@gmail.com

# Avoid needing to specify the upstream remote branch
git config --global --add --bool push.autoSetupRemote true

# Setup git pre push hook to prevent unwanted push to self-defined protected branches
mkdir ~/.githooks
cp scripts/pre-push ~/.githooks
git config --global core.hooksPath ~/.githooks-test/
