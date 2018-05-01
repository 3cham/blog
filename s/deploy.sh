#!/bin/bash

ssh blogger@3cham.io 'cd /home/blogger/gopath/src/github.com/3cham/blog && git checkout master && git pull && ./s/deploy-local.sh'