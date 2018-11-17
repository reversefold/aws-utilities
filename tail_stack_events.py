#!/usr/bin/env python
"""Usage:
    tail_stack_events.py [--follow] [--profile=<profile>] [--number=<n>] <stack>

Options:
    -f --follow                    Follow the stack events and output new ones as they are received.
    -p <p> --profile=<profile>     The aws profile to use.
    -n <n> --number=<n>            The number of lines to display. [default: 10]
    <stack>                        The top-level stack to get events for.

"""
import collections
import math
import sys
import time
import traceback

import eventlet
eventlet.monkey_patch()

import ansiwrap
import botocore.exceptions
import boto3
import colorama
import docopt
import eventlet.greenpool


STACK_TYPE = 'AWS::CloudFormation::Stack'
ELLIPSIS = u'\u2026'


class Column(object):
    def __init__(self, mvl, ml):
        self.max_value_length = mvl
        self.max_length = ml


def get_nested_stacks(stack_name_or_arn, depth=None, status_check=None):
    cf = boto3.resource('cloudformation')
    stack = cf.Stack(stack_name_or_arn)
    # Switch to the ARN if a stack name was passed in
    if stack.stack_id != stack_name_or_arn:
        stack = cf.Stack(stack.stack_id)
    stacks = {stack.stack_id: stack}
    if depth == 0:
        return stacks
    for sub in stack.resource_summaries.all():
        if sub.resource_type != STACK_TYPE:
            continue
        if status_check is not None and status_check(sub.resource_status):
            stacks.update(get_nested_stacks(sub.physical_resource_id, depth - 1 if depth is not None else None, status_check))
    return stacks


def get_stack_events(stack, limit):
    # TODO: keep track of the last found event and go further back if we don't find the previous event
    try:
        return list(stack.events.limit(limit))
    except botocore.exceptions.ClientError:
        pass
        # traceback.print_exc()


def get_events(stacks, limit=5):
    all_events = []
    pool = eventlet.greenpool.GreenPool(5)
    remove_stacks = set()
    for stack_id, events in zip(
        list(stacks.keys()),
        pool.starmap(
            get_stack_events,
            ((s, limit) for s in list(stacks.values()))
        )
    ):
        if not events:
            remove_stacks.add(stack_id)
            continue
        all_events.extend(events)
    for stack_id in remove_stacks:
        del stacks[stack_id]
    all_events.sort(key=lambda e: e.timestamp)
    return all_events


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
        output_text = '%s%s%s' % (
            text[:(column.max_length - 1) // 2],
            ELLIPSIS,
            text[-math.ceil((column.max_length - 1) / 2.0):],
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


def update_stacks_from_events(stacks, events, main_stack):
    cf = boto3.resource('cloudformation')
    to_remove = set()
    to_add = set()

    # NOTE: Assuming that events are in proper order here
    for event in events:
        if event.resource_type == STACK_TYPE:
            if event.resource_status.endswith('COMPLETE'):
                # print('Stack %s COMPLETE' % (event.physical_resource_id,))
                if event.physical_resource_id in to_add:
                    to_add.remove(event.physical_resource_id)
                to_remove.add(event.physical_resource_id)
                # if event.physical_resource_id not in stacks:
                #     print('Stack %s COMPLETE but not in stack list' % (event.physical_resource_id,))
            else:
                if event.physical_resource_id in to_remove:
                    to_remove.remove(event.physical_resource_id)
                to_add.add(event.physical_resource_id)
                # if event.physical_resource_id not in stacks:
                #     print('Found new substack %s' % (event.physical_resource_id,))

    for stack_id in to_remove:
        if stack_id != main_stack.stack_id and stack_id in stacks:
            if len(stacks) != 1:
                del stacks[stack_id]
            # else:
            #     print('Final stack COMPLETE')
    for stack_id in to_add:
        if stack_id not in stacks:
            stack = cf.Stack(stack_id)
            # try:
            #     get_stack_events(stack, 1)
            # except botocore.exceptions.ClientError:
            #     continue
            stacks[stack_id] = stack


def main():
    args = docopt.docopt(__doc__)
    if args['--profile']:
        boto3.setup_default_session(profile_name=args['--profile'])
    num = int(args['--number'])

    columns = collections.OrderedDict([
        ('timestamp', Column(0, 40)),
        ('stack_name', Column(0, 40)),
        ('resource_type', Column(0, 40)),
        ('logical_resource_id', Column(0, 40)),
        ('resource_status', Column(0, 40)),
        ('resource_status_reason', Column(0, 40)),
    ])
    headers = collections.namedtuple('Headers', columns.keys())(*[
        colorama.Style.BRIGHT + t + colorama.Style.RESET_ALL
        for t in [
            'Timestamp',
            'Stack Name',
            'Resource Type',
            'Resource ID',
            'Status',
            'Reason',
        ]
    ])
    update_columns(columns, [headers])

    cf = boto3.resource('cloudformation')

    print('Getting stacks...')
    main_stack = cf.Stack(args['<stack>'])
    stacks = get_nested_stacks(main_stack.stack_id, status_check=lambda status: 'IN_PROGRESS' in status)

    print('Getting events...')
    events = get_events(stacks, limit=num)
    outputted = set(e.id for e in events)
    update_columns(columns, events[-num:])

    update_stacks_from_events(stacks, events, main_stack)

    output_events(columns, [headers])
    output_events(columns, events[-num:])

    last_event_timestamp = events[-1].timestamp

    if not args['--follow']:
        return

    # TODO: Keep track of last updated timestamp for each stack and don't ask for more events
    # if it hasn't changed?
    # This would require updating the stack every time, though, which means adding another API call.

    while True:
        try:
            time.sleep(5)
            events = get_events(stacks)
            new_events = []
            for event in events:
                # Don't re-ouput events and don't output events older than the latest event shown (not doing this means we can get events from the previous stack updates, which we don't want).
                if event.id in outputted or event.timestamp < last_event_timestamp:
                    continue
                new_events.append(event)
            if not new_events:
                continue
            last_event_timestamp = new_events[-1].timestamp

            update_stacks_from_events(stacks, events, main_stack)

            # TODO: If an event for a stack comes in that isn't in stacks, add it to stacks.
            # TODO: Remove a stack from stacks if there is an "end" event? DELETE_COMPLETE or UPDATE_COMPLETE perhaps?
            #       If adding a stack is implemented this should be fine.
            update_columns(columns, new_events)

            # TODO: Only output headers if the column width has changed or we've output more than X rows since the last
            # header.
            output_events(columns, [headers])
            output_events(columns, new_events)
            for event in new_events:
                # TODO: outputted grows constantly over time, it needs to be culled at some point.
                # Potential fix: outputted is replaced each time we loop with only the ids from the loop.
                outputted.add(event.id)
        except Exception:
            traceback.print_exc()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
