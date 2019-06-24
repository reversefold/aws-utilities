#!/bin/bash -ex
poetry install
poetry run pip freeze | grep -v aws-utilities | tee requirements.txt
