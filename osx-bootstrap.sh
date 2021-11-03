#!/usr/bin/env bash

# Inspired by https://gist.github.com/codeinthehole/26b37efa67041e1307db
#
# This should be idempotent so it can be run multiple times.

echo "Starting installation..."

echo "Checking for Homebrew"
if test ! $(which brew); then
    echo "Installing homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/master/install.sh)"
    echo "Done installing homebrew."
fi

echo "Running brew update'..."
brew update

echo "Installing oh-my-zsh"
if test ! [ -d ".oh-my-zsh" ]; then
    echo "Installing oh-my-zsh..."
    sh -c "$(curl -fsSL https://raw.github.com/ohmyzsh/ohmyzsh/master/tools/install.sh)"
else
    echo "oh-my-zsh already installed"
fi


PACKAGES=(
    awscli
    cask
    pure
    python3
    vim
    wget
    zsh-autosuggestions
    zsh-syntax-highlighting
    kubectl
)

echo "Installing brew packages..."
brew install ${PACKAGES[@]}

echo "Installing powerline fonts"
pip3 install --user powerline-status

CASKS=(
    sublime-text
    atom
    webstorm
    datagrip
    ngrok
    lens
)

echo "Installing cask apps..."
brew install --cask ${CASKS[@]}

echo "Checking for docker"
if test ! $(which docker); then
    echo "Installing docker..."
    brew install --cask docker
    echo "Done installing docker"
else
    echo "`docker --version` already installed"
fi

echo "Checking for nodejs"
if test ! $(which node); then
    echo "Installing node..."
    brew install node
    echo "Done installing node"
else
    echo "nodejs `node --version` already installed"
fi

echo "Checking for npm"
if test ! $(which npm); then
    echo "Installing npm..."
    brew install npm
    echo "Done installing npm"
else
    echo "npm `npm --version` already installed"
fi

echo "Installing node packages..."
NODE_PACKAGES=(
    typescript
)

npm install -g ${NODE_PACKAGES[@]}

echo "Installing Python packages..."
PYTHON_PACKAGES=(
    virtualenv
    virtualenvwrapper
)

pip3 install ${PYTHON_PACKAGES[@]}

echo "Cleaning up..."
brew cleanup

echo "Bootstrapping complete!"
