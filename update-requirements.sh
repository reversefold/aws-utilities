#!/bin/bash -ex
pip-compile --upgrade
pip-compile --upgrade build-requirements.in -o build-requirements.txt
pip-compile --upgrade setup.py dev-requirements.in build-requirements.in -o dev-requirements.txt
