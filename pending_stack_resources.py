#!/usr/bin/env python
"""Usage:
    tail_stack_events.py [--depth=<d>] [--max-column-length=<x>] [--profile=<profile>] <stack>

Options:
    -p <p> --profile=<profile>      The aws profile to use.
    -d <d> --depth=<d>              The maximum depth to get events for. Use -1 for unlimited depth. [default: 2]
    -x <x> --max-col-length=<x>     The maximum columns length for tabular output.
                                    Defaults to 200 for postmortem, 40 otherwise.
    <stack>                         The top-level stack to get events for.
"""
import collections
import logging
import math
import sys

import eventlet
eventlet.monkey_patch()

import ansiwrap
import botocore.exceptions
import boto3
import colorama
import docopt
import eventlet.greenpool
import tenacity


STACK_TYPE = 'AWS::CloudFormation::Stack'
ELLIPSIS = u'\u2026'

LOG = logging.getLogger(__name__)


def retry(func):
    tretry = tenacity.retry(
        wait=(
            tenacity.wait_random_exponential(multiplier=1, min=0.1, max=10)
        ),
        after=tenacity.after_log(LOG, logging.WARNING),
    )
    def log_exc(*a, **k):
        try:
            return func(*a, **k)
        except Exception:
            LOG.exception('Exception calling %r' % (func,))
            raise
    return tretry(log_exc)


class Column(object):
    def __init__(self, mvl, ml):
        self.max_value_length = mvl
        self.max_length = ml


@retry
def get_stack(stack_name_or_arn):
    cf = boto3.resource('cloudformation')
    stack = cf.Stack(stack_name_or_arn)
    # Switch to the ARN if a stack name was passed in
    if stack.stack_id != stack_name_or_arn:
        stack = cf.Stack(stack.stack_id)
    return stack


def update_columns(columns, events):
    for event in events:
        for column in columns.keys():
            columns[column].max_value_length = max(columns[column].max_value_length, len(str(getattr(event, column))))


def format_column(column_name, column, value):
    text = str(value)
    if column_name == 'resource_status':
        uvalue = value.upper()
        if 'FAIL' in uvalue:
            color = colorama.Fore.RED
        elif 'ROLLBACK' in uvalue:
            color = colorama.Fore.YELLOW
        elif 'IN_PROGRESS' in uvalue:
            color = colorama.Fore.BLUE
        elif uvalue == 'DELETE_COMPLETE':
            color = colorama.Fore.LIGHTBLACK_EX
        elif 'COMPLETE' in uvalue:
            color = colorama.Fore.GREEN
        else:
            color = colorama.Fore.WHITE
        text = '%s%s%s' % (color, value, colorama.Style.RESET_ALL)
    if ansiwrap.ansilen(text) > column.max_length:
        half_length = (column.max_length - 1) / 2.0
        output_text = '%s%s%s' % (
            text[:int(math.floor(half_length))],
            ELLIPSIS,
            text[-int(math.ceil(half_length)):],
        )
    else:
        output_text = text
    padding = ' ' * max(0, min(column.max_value_length, column.max_length) - ansiwrap.ansilen(output_text))
    return '%s%s' % (
        padding,
        output_text,
    )


def output_events(columns, events):
    for e in events:
        fmt = '  '.join('%s' for _ in columns.values())
        print(fmt % tuple([
            format_column(n, c, getattr(e, n)) for n, c in columns.items()
        ]))


@retry
def next_page(pages):
    try:
        return list(next(pages))
    except botocore.exceptions.ClientError:
        return None
        # traceback.print_exc()
    except StopIteration:
        return None


def short_stack_name(name):
    if ':' not in name:
        return name
    name = name.split(':')[-1]
    if '/' not in name:
        return name
    return name.split('/')[1]


def get_pending_resources(stack):
    pending_resources = []
    for sub in stack.resource_summaries.all():
        if (
            ('IN_PROGRESS' not in sub.resource_status and 'FAILED' not in sub.resource_status)
            or 'COMPLETE' in sub.resource_status
        ):
            continue
        sub.short_stack_name = short_stack_name(sub.stack_name)
        pending_resources.append(sub)
        if sub.resource_type == STACK_TYPE:
            pending_resources.extend(get_pending_resources(get_stack(sub.physical_resource_id)))
    return pending_resources


def main():
    args = docopt.docopt(__doc__)
    if args['--profile']:
        boto3.setup_default_session(profile_name=args['--profile'])

    max_column_length = args['--max-column-length']
    if max_column_length is None:
        max_column_length = 200

    columns = collections.OrderedDict([
        ('short_stack_name', Column(0, max_column_length)),
        ('logical_resource_id', Column(0, max_column_length)),
        # ('stack_id', Column(0, max_column_length)),
        ('resource_type', Column(0, max_column_length)),
        ('resource_status', Column(0, max_column_length)),
        ('resource_status_reason', Column(0, max_column_length)),
    ])
    headers = collections.namedtuple('Headers', columns.keys())(*[
        colorama.Style.BRIGHT + t + colorama.Style.RESET_ALL
        for t in [
            'Stack Name',
            'Logical Resource ID',
            # 'Stack ID',
            'Resource Type',
            'Status',
            'Reason',
        ]
    ])
    update_columns(columns, [headers])

    print('Getting stack...')
    main_stack = get_stack(args['<stack>'])

    pending_resources = get_pending_resources(main_stack)
    if not pending_resources:
        print('None')
        sys.exit(0)

    update_columns(columns, pending_resources)

    output_events(columns, [headers])
    output_events(columns, pending_resources)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
