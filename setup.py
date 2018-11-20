import os
from setuptools import setup, find_packages

VERSION = '0.1.1'

DESCRIPTION = 'Utilities for use with aws.'

README_PATH = os.path.join(os.path.dirname(__file__), 'README.md')


if os.path.exists(README_PATH):
    with open(README_PATH, 'r') as f:
        LONG_DESCRIPTION = f.read()
else:
    LONG_DESCRIPTION = DESCRIPTION


setup(
    name='aws-utilities',
    version=VERSION,
    author='Justin Patrin',
    author_email='papercrane@reversefold.com',
    maintainer='Justin Patrin',
    maintainer_email='papercrane@reversefold.com',
    description=DESCRIPTION,
    long_description=LONG_DESCRIPTION,
    packages=find_packages(),
    install_requires=[
        'ansiwrap',
        'boto3',
        'colorama',
        'docopt',
        'eventlet',
    ],
    scripts=[
        'tail_stack_events.py',
        'tail_cloudwatch_logs.py',
    ],
    url='https://github.com/reversefold/aws-utilities',
)
