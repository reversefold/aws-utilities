#!/usr/bin/env python2
# START magicreq imports
import os
import sys
import urllib2
# END magicreq imports


REQUIREMENTS = [
    'boto3',
    'ec2-metadata',
    'functools32',
    'tenacity',
    # urllib3 1.24+ causes import errors on Ubuntu 14.04
    'urllib3<1.24',
]


# START magicreq
try:
    import pkg_resources
    pkg_resources.require(REQUIREMENTS)

# We're expecting ImportError or pkg_resources.ResolutionError but since pkg_resources might not be importable,
# we're just catching Exception.
except Exception:
    if __name__ != '__main__':
        raise
    try:
        import magicreq
        magicreq.magic(
            REQUIREMENTS,
        )
    except ImportError:
        url = 'https://raw.githubusercontent.com/reversefold/magicreq/0.5.0/magicreq/bootstrap.py'
        bootstrap_script = os.path.join(os.getcwd(), '.magicreq_bootstrap.py')
        with open(bootstrap_script, 'wb') as outfile:
            outfile.write(urllib2.urlopen(url).read())
        cmd = [
            sys.executable,
            bootstrap_script,
        ] + sys.argv
        os.execv(sys.executable, cmd)
# END magicreq


import logging
import os
import sys
import time

import boto3
import ec2_metadata
import functools32
import tenacity


LOG = logging.getLogger(__name__)


_SENTINEL_ = object()


retry = tenacity.retry(
    wait=(
        tenacity.wait_random_exponential(multiplier=1, min=5, max=300)
    ),
    before_sleep=tenacity.before_sleep_log(LOG, logging.WARN),
)


@functools32.lru_cache()
@retry
def get_instance_metadata():
    return ec2_metadata.ec2_metadata


@functools32.lru_cache()
def init_boto3():
    meta = get_instance_metadata()
    boto3.setup_default_session(region_name=meta.region)


@functools32.lru_cache()
@retry
def get_this_instance():
    init_boto3()
    meta = get_instance_metadata()
    ec2 = boto3.resource('ec2')
    return ec2.Instance(meta.instance_id)


@retry
def get_stack(stack_id):
    cf = boto3.resource('cloudformation')
    stack = cf.Stack(stack_id)
    # NOTE: boto3 resources are dynamic so we call load() here to make sure the API call has happened
    stack.load()
    return stack


def get_tag(tags, key, default=_SENTINEL_):
    try:
        return next(tag['Value'] for tag in tags if tag['Key'] == key)
    except StopIteration:
        if default is _SENTINEL_:
            raise
        return default


def main():
    my_stack = get_stack(get_tag(get_this_instance().tags, 'aws:cloudformation:stack-id'))
    LOG.info('My stack is %s', my_stack.stack_id)
    # We watch to watch the parent stack as it might add disks to the instance
    if my_stack.parent_id:
        stack = get_stack(my_stack.parent_id)
        LOG.info('Watching parent stack %s', stack.stack_id)
    else:
        # If we don't have a parent stack, just watch our stack to make sure any extra resources
        # are created and attached.
        stack = my_stack

    while 'COMPLETE' not in stack.stack_status:
        LOG.info(
            'Stack %s status is %s, waiting for a complete status',
            stack.stack_id, stack.stack_status
        )
        # stack.reload makes API calls, retry it if needed
        retry(lambda: stack.reload())()
        time.sleep(15)
    LOG.info('Stack %s status is %s', stack.stack_id, stack.stack_status)


if __name__ == '__main__':
    if hasattr(sys.stdout, 'fileno'):
        # Force stdout to be line-buffered
        sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', 1)
        logging.basicConfig(format='%(asctime)s %(levelname)s: %(message)s', level=logging.INFO)
    main()
