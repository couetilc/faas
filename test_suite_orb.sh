#!/usr/bin/env bash
VM_NAME=faasvm
VM_IMAGE=images/faasvm.tar.zst

set -euo pipefail

# setup
orbctl import -n $VM_NAME $VM_IMAGE
# teardown
trap "orbctl delete -f $VM_NAME" EXIT

# test suite
orbctl run \
    -m $VM_NAME \
    -w $PWD \
    ls -al
