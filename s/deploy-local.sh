#!/usr/bin/env bash
source $HOME/.profile && cd $GOPATH/src/github.com/3cham/blog && git checkout master && git pull && ./s/run.sh