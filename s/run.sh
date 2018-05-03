#!/bin/bash
set -u -e -o pipefail

echo "building"
go build -o blog_app -ldflags "-X main.sha1ver=`git rev-parse HEAD`"
#go build -o blog_app *.go
echo "running in `pwd`"
sudo ./blog_app -production
rm blog_app
