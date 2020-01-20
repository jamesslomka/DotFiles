
#Removes user @ hostname from PS1, shows path from home dir
PS1='[\w] ~ '
# NVM path
export NVM_DIR=~/.nvm
    source $(brew --prefix nvm)/nvm.sh

# WORKSPACE
alias uiweb='cd Documents/Git/workspace/services/ui-website'
alias workspace='cd Documents/Git/workspace'
alias services='cd Documents/Git/workspace/services'

# BASIC
# reload config file
alias r='source ~/.bash_profile'

# GIT

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

# DOCKER / DOCKER COMPOSE
# Runs a docker command of your choice from anywhere.
#
# Usage: dc <command>
dc() {
        docker-compose --project-directory ~/Documents/Git/workspace -f  ~/Documents/Git/workspace/docker-compose.yml $@
}

# Docker Compose Restart.
# Restart a container by name.
#
# Usage: dcr <name>
dcr() {
    dc kill "$1"
    dc up -d "$1"
}

dcr() {
    dc kill "$1"
    dc up -d "$1"
}
# Docker stop all running containers
alias dsa='docker stop $(docker ps -a -q)'

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
alias d='docker'
alias dcu='dc up -d'
alias de='d exec -it'
alias dr='d run -it --rm -v $(pwd):$(pwd) -w $(pwd)'
alias dd='d kill $(d ps -a -q); d rm $(d ps -a -q)'
alias dp='d ps -a'
alias purgeDocker='d kill $(d ps -a -q); d rm $(d ps -a -q); d volume rm $(d volume ls -q); d network rm $(d network ls -q)'
alias purgeDockerImages='d rmi -f $(d images -f dangling=true -q)'
alias removeAllImages='d rmi -f $(d images -a -q)'

# SSENSE
alias migrate='g; dcu ssense-phinx; dce ssense-phinx ./vendor/bin/phinx migrate -e development; dcr ssense-phinx'
alias startStack='g; dcr aws-localstack; dcu ui-website'
alias cleanHooks='rm -rf ~/projects/workspace/services/hq-central/.git/hooks/*'

# PROJECT SPECIFICS
alias ui-website='g; dce ui-website'
alias hqm='g; dce hq-central'

# OTHER PATHS
alias subl='sublime'

# ------------------------
# PERSONAL
# ------------------------

alias xquarts="open -a XQuartz"
alias sshmcgill="ssh jslomk@mimi.cs.mcgill.ca"
alias http="python -m SimpleHTTPServer 8080"
alias venv="source env/bin/activate"
alias update="brew update && brew upgrade"

# Add RVM to PATH for scripting. Make sure this is the last PATH variable change.
export PATH="$PATH:$HOME/.rvm/bin"

