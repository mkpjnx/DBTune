#!/usr/bin/env bash
BENCHBASE_DIR=/home/peijingx/repos/noisepage-pilot/artifacts/benchbase

config_path=$(realpath ${2})
summary_file=$(realpath ${3})
tempdir=$(dirname $summary_file)/tempresults

mkdir -p $tempdir

pushd $BENCHBASE_DIR
echo $pwd
java -jar benchbase.jar -b ${1} -c $config_path --execute=true -d $tempdir #> /dev/null
# java -jar benchbase.jar -b ${1} -c $config_path --create=true --load=true #> /dev/null
summary=$(find $tempdir/*summary* -maxdepth 1 -type f -exec stat -c '%X %n' {} \; | sort -nr | awk  --field-separator=' ' '{print $2}' | head -n 1)
echo $summary
mv $summary $summary_file
popd

rm -r $tempdir