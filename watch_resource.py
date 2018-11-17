#!/usr/bin/env python
"""Usage:
    watch_resource.py [--profile=<p>] <arn>
"""
import collections
import time

import boto3
import docopt


Descriptor = collections.namedtuple(
    'Descriptor',
    ('service', 'resourcetype', 'desc_func', 'respkey', 'statuskey', 'status_func')
)


Arn = collections.namedtuple(
    'Arn',
    ('arn', 'partition', 'service', 'region', 'account_id', 'resourcetype', 'resource')
)


DESCRIPTORS = [
    Descriptor(
        'rds',
        'db',
        lambda arn: boto3.client('rds').describe_db_instances(DBInstanceIdentifier=arn),
        'DBInstances',
        'DBInstanceStatus',
        lambda arn: boto3.client('rds').describe_db_instances(DBInstanceIdentifier=arn)['DBInstances'][0]['DBInstanceStatus'],
    ),
]


ARNMAP = {}


for _ in DESCRIPTORS:
    ARNMAP.setdefault(_.service, {})[_.resourcetype] = _


def main():
    args = docopt.docopt(__doc__)
    if args['--profile']:
        boto3.setup_default_session(profile_name=args['--profile'])
    arn_str = args['<arn>']
    arn = Arn(*arn_str.split(':'))
    descriptor = ARNMAP[arn.service][arn.resourcetype]
    try:
        while True:
            status = descriptor.status_func(arn_str)
            print(arn_str, status)
            time.sleep(5)
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
