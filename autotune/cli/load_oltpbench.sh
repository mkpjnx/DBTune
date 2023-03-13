#!/usr/bin/env bash
BENCHBASE_DIR=/home/peijingx/repos/noisepage-pilot/artifacts/benchbase

config_path=$(realpath ${2})
pushd $BENCHBASE_DIR
echo $pwd
java -jar benchbase.jar -b ${1} -c $config_path --create=true --load=true #> /dev/null
popd
