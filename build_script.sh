#!/bin/bash

set -e	# Exit on failure of any of the following commands

echo "Running build script"

echo "Executing first g++ command"
g++ source/main1.cpp source/source_file1.cpp -o bin/binary1
echo "Finished executing first g++ command"

echo "Executing second g++ command"
g++ source/main2.cpp -o bin/binary2
echo "Finished executing second g++ command"

echo "Finished running build script successfully"