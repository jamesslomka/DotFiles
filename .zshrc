#########################
# CUSTOM
#########################

#Removes user @ hostname from PS1
USER=''

# NVM path
export NVM_DIR=~/.nvm
    source $(brew --prefix nvm)/nvm.sh

# BASIC
# reload config file
alias r='source ~/.zshrc'

# DOCKER / DOCKER COMPOSE
# Runs a docker command of your choice from anywhere.
#
# Usage: dc <command>
dc() {
        docker-compose --project-directory ~/Documents/Git/workspace -f  ~/Documents/Git/workspace/docker-compose.yml $@
}
# Docker-compose restart 
dcr() {
    dc kill "$1"
    dc up -d "$1"
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
# Docker stop all running containers
alias dsa='docker stop $(docker ps -a -q)'
alias d='docker'
alias dcu='dc up -d'
alias de='d exec -it'
alias dr='d run -it --rm -v $(pwd):$(pwd) -w $(pwd)'
alias dd='d kill $(d ps -a -q); d rm $(d ps -a -q)'
alias dp='d ps -a'
alias purgeDocker='d kill $(d ps -a -q); d rm $(d ps -a -q); d volume rm $(d volume ls -q); d network rm $(d network ls -q)'
alias purgeDockerImages='d rmi -f $(d images -f dangling=true -q)'

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
gr() {
    TRUNK=${1:-master}
    MSG=$(git log --oneline --abbrev-commit $TRUNK..HEAD --pretty=format:"%s" --reverse | head -1)
    git fetch origin "$TRUNK"
    git reset $(git merge-base origin/$TRUNK $(git rev-parse --abbrev-ref HEAD))
    git add -A
    git commit -m "${MSG}"
}

# OTHER PATHS
alias subl='sublime'

## OH-MY-ZSH

export PATH="$PATH:$HOME/.rvm/bin"

## ---------------ZSH CONFIG:--------------------------------------------------

export ZSH="/Users/james.slomka/.oh-my-zsh"
ZSH_THEME="agnoster"
plugins=(git)

source $ZSH/oh-my-zsh.sh

