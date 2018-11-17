from setuptools import setup, find_packages

VERSION = '0.1.0'

setup(
    name='aws-utilities',
    version=VERSION,
    author='Justin Patrin',
    author_email='papercrane@reversefold.com',
    maintainer='Justin Patrin',
    maintainer_email='papercrane@reversefold.com',
    description='Utilities for use with aws.',
    long_description="""...""",
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
    url='',
)
