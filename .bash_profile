# ---------------CUSTOM PREFERNECES:-------------------

# Important that you set the path to your docker-compose.yml file here
DOCKER_COMPOSE_PATH='Documents/Git/workspace'

#Removes user @ hostname from PS1, shows path from home dir
PS1='[\w] ~ '

# PYTHON
alias python="python3"
alias pip="pip3"

# WORKSPACE
alias gh='cd Documents/git'
alias uiweb='cd $DOCKER_COMPOSE_PATH/services/ui-website'
alias workspace='cd $DOCKER_COMPOSE'
alias services='cd $DOCKER_COMPOSE/services'

# Git Pull
#
# Will pull all branches in children directories:
# to do all individually
# ls | xargs -I{} git -C {} pull
# to do all in parallel
alias pullall='ls | xargs -P10 -I{} git -C {} pull'

# reload this config file on changes
alias r='source ~/.zshrc'

# NVM path
export NVM_DIR=~/.nvm
    source $(brew --prefix nvm)/nvm.sh

# OTHER PATHS
alias update='brew update && brew upgrade'
alias pgstart='pg_ctl -D /usr/local/var/postgres start'
alias pgstop='pg_ctl -D /usr/local/var/postgres stop'
alias subl="/Applications/Sublime\ Text.app/Contents/SharedSupport/bin/subl"

alias xquarts="open -a XQuartz"
alias sshmcgill="ssh jslomk@mimi.cs.mcgill.ca"
alias http="python -m SimpleHTTPServer 8080"
alias venv="source env/bin/activate"
alias update="brew update && brew upgrade"

# Add RVM to PATH for scripting. Make sure this is the last PATH variable change.
export PATH="$PATH:$HOME/.rvm/bin"

# ---------------DOCKER/DOCKER COMPOSE:-------------------

# Runs a docker command of your choice from anywhere.
#
# Usage: dc <command>
dc() {
        docker-compose --project-directory ~/$DOCKER_COMPOSE_PATH -f  ~/$DOCKER_COMPOSE_PATH/docker-compose.yml $@
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
