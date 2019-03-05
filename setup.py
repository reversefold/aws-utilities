import os
import pkg_resources
import platform
import setuptools


VERSION = '0.4.3'

DESCRIPTION = 'Utilities for use with aws.'

README_PATH = os.path.join(os.path.dirname(__file__), 'README.md')


if os.path.exists(README_PATH):
    with open(README_PATH, 'r') as f:
        LONG_DESCRIPTION = f.read()
else:
    LONG_DESCRIPTION = DESCRIPTION

REQ_FILE = os.path.join(os.path.dirname(__file__), 'requirements.in')
with open(REQ_FILE, 'r') as f:
    REQUIREMENTS = f.read().split('\n')


try:
    (dist_name, dist_version, dist_codename) = platform.linux_distribution()
    if dist_name == 'Ubuntu':
        distv = pkg_resources.parse_version(dist_version)
        if distv < pkg_resources.parse_version('16.04'):
            # Ubuntu 14.04 has import errors with urllib3 1.24+
            REQUIREMENTS.append('urllib3<1.24')
except Exception:
    pass


setuptools.setup(
    name='aws-utilities',
    version=VERSION,
    author='Justin Patrin',
    author_email='papercrane@reversefold.com',
    maintainer='Justin Patrin',
    maintainer_email='papercrane@reversefold.com',
    description=DESCRIPTION,
    long_description=LONG_DESCRIPTION,
    long_description_content_type='text/markdown',
    packages=setuptools.find_packages(),
    install_requires=REQUIREMENTS,
    scripts=[
        'tail_stack_events.py',
        'tail_cloudwatch_logs.py',
        'wait_for_stack_complete.py',
    ],
    url='https://github.com/reversefold/aws-utilities',
)
