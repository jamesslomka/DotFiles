

#########################
# CUSTOM
#########################

#Removes user @ hostname from PS1
USER=''

# WORKSPACE
alias uiweb='cd Documents/Git/workspace/services/ui-website'
alias workspace='cd Documents/Git/workspace'
alias services='cd Documents/Git/workspace/services'


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
# Docker-compose restart logs - will restart container and bring up its logs
dcrl() {
    dc kill "$1"
    dc up -d "$1"
    dcl "$1"
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
".zshrc" 104L, 2595C
