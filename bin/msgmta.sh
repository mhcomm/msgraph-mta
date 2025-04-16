#!/bin/bash

# for detecting errors in pipes
#set -e
#set -o pipefail


mydir=$(unset cd ; cd $(dirname $0) ; pwd)

show_help() {
    cat << eot
usage $(basename $0) [-h|--help]


source $mydir/.env or $mydir/.envrc if existing
and call msgmta with the specified arguments

if the environment variable MSGMTA_GROUP is set, then mhadm will be run with this group.

options:
    -h|--help       show this help text
eot
}

bd=$(cd $(dirname $0) ; pwd)

# replace with 'standard' argument parser if any other switch will be added
if [[ $1 == "-h" || $1 == "--help" ]] ; then
    show_help
    exit
fi

if [[ -f $bd/.envrc ]] ; then
    source $bd/.envrc
elif [[ -f $bd/.env ]] ; then
    source $bd/.env
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
    exec sg $MSGMTA_GROUP -c "$cmd_w_args"
fi

