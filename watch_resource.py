#!/usr/bin/env python
"""Usage:
    watch_resource.py [--profile=<p>] <arn>...
"""
import collections
import time

import boto3
import docopt


class Error(Exception):
    pass


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
    Descriptor(
        'ec2',
        'volume',
        lambda arn: boto3.client('ec2').describe_volumes(VolumeIds=[arn.split(':')[-1].split('/')[-1]]),
        'Volumes',
        'State',
        lambda arn: boto3.client('ec2').describe_volumes(VolumeIds=[arn.split(':')[-1].split('/')[-1]])['Volumes'][0]['State'],
    ),
]


ARNMAP = {}


for _ in DESCRIPTORS:
    ARNMAP.setdefault(_.service, {})[_.resourcetype] = _


def main():
    args = docopt.docopt(__doc__)
    if args['--profile']:
        boto3.setup_default_session(profile_name=args['--profile'])
    arn_strs = args['<arn>']
    descriptors = []
    for arn_str in arn_strs:
        arn_parts = arn_str.split(':')
        # Some ARNs (such as for EBS volumes) have 5 colon-separated pieces with the resource type separated from the
        # id with a slash in the last piece.
        if len(arn_parts) == 6:
            (arn_parts[-1], part) = arn_parts[-1].split('/')
            arn_parts.append(part)
        # Other ARNs have 6 colons.
        if len(arn_parts) != 7:
            raise Error('ARN %s does not have the right number of pieces' % (arn_str,))
        arn = Arn(*arn_parts)
        descriptors.append(ARNMAP[arn.service][arn.resourcetype])
    try:
        while True:
            for descriptor in descriptors:
                status = descriptor.status_func(arn_str)
                print(arn_str, status)
            time.sleep(5)
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
