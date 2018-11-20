#!/bin/bash -ex
pip-compile --upgrade requirements.in -o requirements.txt
pip-compile --upgrade build-requirements.in -o build-requirements.txt
pip-compile --upgrade requirements.in dev-requirements.in build-requirements.in -o dev-requirements.txt
