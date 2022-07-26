#!/bin/bash

# Setup git pre push hook to prevent unwanted push to self-defined protected branches
mkdir ~/.githooks
cp scripts/pre-push ~/.githooks
git config --global core.hooksPath ~/.githooks-test/
