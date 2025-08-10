# ------------------------------------------------------------------------------
# ----------------------------------DOCKER--------------------------------------
# ------------------------------------------------------------------------------

export DOCKER_DEFAULT_PLATFORM=linux/arm64
export COMPOSE_BAKE=true

# Set the path to your docker-compose.yml file here:
DOCKER_COMPOSE_PATH='workspace'

# Runs a docker-compose command of your choice from anywhere.
# Usage: dc <service>
dc() {
    docker-compose --project-directory ~/$DOCKER_COMPOSE_PATH -f  ~/$DOCKER_COMPOSE_PATH/docker-compose.yml $@
}

# Docker-compose restart
# Usage: dcr <service>
dcr() {
    dc kill "$1"
    dc up -d "$1"
}

## Docker logs - for services ran with just Docker run
dl() {
    d logs --tail "100" -f "$1"
}

# Docker Compose Logs.
#
# Inspect the logs in real-time of a container by name.
# Defaults to all containers if no name is specified.
#
# Usage: dcl
# Usage: dcl <name>
dcl() {
    dc logs --tail "100" -f "$1"
}

# Docker-compose up logs - starts a container and tails its logs
dcul() {
    dc up -d "$1"
    dcl "$1"
}

# Docker-compose restart logs - will restart container and bring up its logs
dcrl() {
    dc kill "$1"
    dc up -d "$1"
    dcl "$1"
}

# Docker stop all running containers
alias dsa='docker stop $(docker ps -a -q)'
alias d='docker'
alias dcu='dc up -d'
alias de='dc exec'
alias dr='d run -it --rm -v $(pwd):$(pwd) -w $(pwd)'
alias dd='d kill $(d ps -a -q); d rm $(d ps -a -q)'
alias dp='d ps -a'
alias purgeDocker='d kill $(d ps -a -q); d rm $(d ps -a -q); d volume rm $(d volume ls -q); d network rm $(d network ls -q)'
alias purgeDockerImages='d rmi -f $(d images -f dangling=true -q)'

# Docker Cleanup.
# Deletes all containers and images.
#
# Usage: dcleanup
dcleanup() {
    docker rm $(docker ps -q -f 'status=exited')
    docker rmi $(docker images -q -f "dangling=true")
    docker run --rm -v /var/run/docker.sock:/var/run/docker.sock -v /etc:/etc spotify/docker-gc
}

# ------------------------------------------------------------------------------
# ---------------------------------- GIT----------------------------------------
# ------------------------------------------------------------------------------

# Git Pull
#
# Will pull all branches in children directories:
# to do all individually
# ls | xargs -I{} git -C {} pull
# to do all in parallel
alias pullall='ls | xargs -P10 -I{} git -C {} pull'

# Undo commit but keep all changes staged
alias reset='git reset --soft HEAD~;'


# Git Rebase.
#
# Rebases the specified branch onto the current branch,
# squashing the commits into a single one,
# using the first message as the final commit message.
#
# If no branches are specified, the master branch is used.
#
# Usage: gr
# Usage: gr <trunk>
# gr(){
#     TRUNK=${1:-master}
#     MSG=$(git log --oneline --abbrev-commit $TRUNK..HEAD --pretty=format:"%s" --reverse | head -1)
#     git fetch origin "$TRUNK"
#     git reset $(git merge-base origin/$TRUNK $(git rev-parse --abbrev-ref HEAD))
#     git add -A
#     git commit -m "${MSG}"
# }


# ------------------------------------------------------------------------------
# -------------------------------ZSH CONFIG:------------------------------------
# ------------------------------------------------------------------------------

source ~/.zsh/zsh-autosuggestions/zsh-autosuggestions.zsh

fpath+=("$(brew --prefix)/share/zsh/site-functions")

plugins=(
  git
  node
  npm
  cp
  zsh-autosuggestions
  zsh-syntax-highlighting # needs to always be the last plugin
)
# autoload -U compinit; compinit -y

# ---- Pure Theme Settings ----
autoload -U promptinit; promptinit
# change the color for both `prompt:success` and `prompt:error`
zstyle ':prompt:pure:git:branch' color white
# turn on git stash status
zstyle :prompt:pure:git:stash show yes
# Prompt icon: >
zstyle ':prompt:pure:prompt:*' color grey
# Path colour
zstyle :prompt:pure:path color '#4192d8'
# Git *when branch has changes from remote
zstyle :prompt:pure:git:dirty color '#7a7a7a'
PURE_GIT_DOWN_ARROW=↓
prompt pure

# ------------------------------------------------------------------------------
# -----------------------------CUSTOM CONFIG:-----------------------------------
# ------------------------------------------------------------------------------

# Remove "last login" message from terminal
if [ ! -e ~/.hushlogin ]
then
    touch .hushlogin
fi

# rbenv for ap-mobile
eval "$(rbenv init -)"
export VOLTA_HOME="$HOME/.volta"
export PATH="$VOLTA_HOME/bin:$PATH"

# NVM path
export NVM_DIR=~/.nvm
    source $(brew --prefix nvm)/nvm.sh

# OTHER PATHS
export PATH="$PATH:$HOME/.rvm/bin"

# tfswitch = https://github.com/warrensbox/terraform-switcher/issues/219#issuecomment-1105757975
 export PATH=$PATH:/Users/james.slomka/bin

# React Native
export ANDROID_HOME=$HOME/Library/Android/sdk
export PATH=$PATH:$ANDROID_HOME/emulator
export PATH=$PATH:$ANDROID_HOME/tools
export PATH=$PATH:$ANDROID_HOME/tools/bin
export PATH=$PATH:$ANDROID_HOME/platform-tools

# reload this config file on changes
alias r='source ~/.zshrc'
alias uiweb='cd $DOCKER_COMPOSE_PATH/services/ui-website'
alias apweb='cd $DOCKER_COMPOSE_PATH/services/ap-website'
alias workspace='cd $DOCKER_COMPOSE_PATH'
alias services='cd $DOCKER_COMPOSE_PATH/services'
alias morning='update && workspace && make login-sso'
alias update='brew update && brew upgrade'
alias pgstart='pg_ctl -D /usr/local/var/postgres start'
alias pgstop='pg_ctl -D /usr/local/var/postgres stop'
alias subl="/Applications/Sublime\ Text.app/Contents/SharedSupport/bin/subl"
alias python="python3"
alias pip="pip3"
alias grok="ngrok http http://localhost:8080 --host-header="localhost:8080""
alias awssso="aws sso login --profile "$1""
alias localip="ipconfig getifaddr en0"
alias kube="kubectl"
alias refresh-alias='curl -sS https://raw.githubusercontent.com/jamesslomka/DotFiles/master/.zshrc >> ~/.zshrc'
alias tunnel="cloudflared tunnel --url http://localhost:8787 --http-host-header="localhost""
alias eks-qa="kubectl config use-context arn:aws:eks:us-west-2:897347678622:cluster/main-eks-qa"
alias eks-prod="kubectl config use-context arn:aws:eks:us-west-2:546249166250:cluster/main-eks-prod"
alias login="cd ~/$DOCKER_COMPOSE_PATH && make login"
alias jumphost="aws ssm start-session --profile oncallsupport --target i-06a12dd598478761b --region us-west-2 --document-name SSM-SessionManagerRunShell"
alias mtr='sudo mtr' # https://github.com/traviscross/mtr/issues/204
alias flushdns="sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder"
alias ccusage="bunx ccusage"


renamebranch() {
    current_branch=$(git rev-parse --abbrev-ref HEAD)
    git branch -m $current_branch $1
    git push origin --delete $current_branch
    git push origin -u $1
} 

n() {
  if [[ -f package-lock.json ]]; then
    command npm "$@"
  elif [[ -f pnpm-lock.yaml ]]; then
    command pnpm "$@"
  elif [[ -f yarn.lock ]]; then
    command yarn "$@"
  elif [[ -f bun.lockb ]]; then
    command bun "$@"
  else
    command npm "$@"
  fi
}

# Shopify Hydrogen alias to local projects
alias h2='$(npm prefix -s)/node_modules/.bin/shopify hydrogen'

. "$HOME/.local/bin/env"
export PATH="$HOME/.local/bin:$PATH"
