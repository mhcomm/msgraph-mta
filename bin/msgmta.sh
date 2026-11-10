#!/bin/bash

# for detecting errors in pipes
#set -e
#set -o pipefail


mydir=$(unset cd ; cd "$(dirname "$0")" ; pwd)
bd=$(cd "$mydir" ; cd .. || true ; pwd)

show_help() {
    cat << eot
usage $(basename "$0") [-h|--help]


source $bd/.envrc or $bd/.env if existing
and call msgmta with the specified arguments

The file is only sourced if it belongs to root or to the calling user
and if neither the group nor others can write to it.

if the environment variable MSGMTA_GROUP is set, then mhadm will be run with this group.

options:
    -h|--help       show this help text
eot
}


# replace with 'standard' argument parser if any other switch will be added
if [[ $1 == "-h" || $1 == "--help" ]] ; then
    show_help
    exit
fi

# The sourced file is executed with the rights of the calling user.
# So refuse files, that could have been modified by somebody else.
source_env_file() {
    local env_file="$1"
    local owner perms
    owner=$(stat -L -c '%u' "$env_file") || exit 1
    perms=$(stat -L -c '%a' "$env_file") || exit 1
    if [[ $owner != 0 && $owner != "$(id -u)" ]] ; then
        echo "refusing $env_file: must belong to root or to you" >&2
        exit 1
    fi
    if (( (8#$perms & 8#022) != 0 )) ; then
        echo "refusing $env_file: writable by group or others" >&2
        exit 1
    fi
    source "$env_file"
}

if [[ -f $bd/.envrc ]] ; then
    source_env_file "$bd/.envrc"
elif [[ -f $bd/.env ]] ; then
    source_env_file "$bd/.env"
fi


if [[ $MSGMTA_GROUP = "" ]] ; then
    exec msgmta "$@"
else
    # change group prior to executing the mhadm command
    args=()
    for arg in "$@" ; do
        args+=("$(printf "%q" "$arg")")
    done
    cmd_w_args="msgmta ${args[*]}"
    exec sg "$MSGMTA_GROUP" -c "$cmd_w_args"
fi

