#!/usr/bin/env python
"""Usage:
    tail_stack_events.py [--follow] [--number=<n>] [--depth=<d>] [--max-column-length=<x>] [--profile=<profile>] <stack>
    tail_stack_events.py [--postmortem] [--find-last-failure] [--show-all-failures] [--max-column-length=<x>] [--profile=<profile>] <stack>

Options:
    -f --follow                     Follow the stack events and output new ones as they are received.
    -p <p> --profile=<profile>      The aws profile to use.
    -n <n> --number=<n>             The number of lines to display. [default: 10]
    -d <d> --depth=<d>              The maximum depth to get events for. Use -1 for unlimited depth. [default: 2]
    -m --postmortem                 Find the failures in the last stack update.
    --find-last-failure             Search for the last rollback and show the failures from that update.
                                    By default --postmortem only looks at the latest stack update.
    -x <x> --max-column-length=<x>  The maximum column length for tabular output.
                                    Defaults to 200 for postmortem, 40 otherwise.
    --show-all-failures             Show all failures for the stack update, not just the one that caused the rollback.
    <stack>                         The top-level stack to get events for.
"""
import collections
import logging
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


# TODO: make the retries per-api-call rather than on this function to reduce repeated API calls
@retry
def get_nested_stacks(stack_name_or_arn, depth=None, status_check=None):
    stack = get_stack(stack_name_or_arn)
    stacks = {stack.stack_id: stack}
    if depth == 0:
        return stacks
    for sub in stack.resource_summaries.all():
        if sub.resource_type != STACK_TYPE:
            continue
        if status_check is not None and status_check(sub.resource_status):
            stacks.update(
                get_nested_stacks(
                    sub.physical_resource_id,
                    depth - 1 if depth is not None else None,
                    status_check
                )
            )
    return stacks


def get_stack_events(stack, limit=5, _mem={}):
    # TODO: preload _mem with the timestamp of the first event in the parent stack that caused us to add the stack
    pages = stack.events.pages()
    events = next_page(pages)
    if not events:
        if stack.stack_id in _mem:
            del _mem[stack.stack_id]
        return []
    events.sort(key=lambda e: e.timestamp)
    if stack.stack_id in _mem:
        while events[0].timestamp > _mem[stack.stack_id]:
            more = list(next(pages))
            if not more:
                break
            more.sort(key=lambda e: e.timestamp)
            events = more + events
    _mem[stack.stack_id] = events[-1].timestamp
    if stack.stack_id not in _mem:
        return events[-limit:]
    return events


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


def update_stacks_from_events(stacks, events, main_stack, max_depth=None):
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
                if not event.physical_resource_id:
                    LOG.debug('stack event has an empty physical_resource_id: %r', event)
                    continue
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
        if (
            stack_id not in stacks
            and (
                max_depth is None
                or len(stack_id.split('-')) - 1 <= max_depth
            )
        ):
            stack = cf.Stack(stack_id)
            # Force loading with a retry as it can incur a potentially-failing API call
            retry(lambda: stack.stack_id)()
            # try:
            #     get_stack_events(stack, 1)
            # except botocore.exceptions.ClientError:
            #     continue
            stacks[stack_id] = stack


def do_tail_stack_events(main_stack, num, columns, headers, max_depth, follow):
    stacks = get_nested_stacks(main_stack.stack_id, status_check=lambda status: 'IN_PROGRESS' in status)

    print('Getting events...')
    events = get_events(stacks, limit=num)
    outputted = set(e.id for e in events)
    update_columns(columns, events[-num:])

    update_stacks_from_events(stacks, events, main_stack, max_depth=max_depth)

    output_events(columns, [headers])
    output_events(columns, events[-num:])

    last_event_timestamp = events[-1].timestamp

    if not follow:
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
                # Don't re-ouput events and don't output events older than the latest event shown (not doing this means
                # we can get events from the previous stack updates, which we don't want).
                if event.id in outputted or event.timestamp < last_event_timestamp:
                    continue
                new_events.append(event)
            if not new_events:
                continue
            last_event_timestamp = new_events[-1].timestamp

            update_stacks_from_events(stacks, events, main_stack, max_depth=max_depth)

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


@retry
def next_page(pages):
    try:
        return list(next(pages))
    except botocore.exceptions.ClientError:
        return None
        # traceback.print_exc()
    except StopIteration:
        return None


def get_stack_failure_events(stack, columns, headers, start_func=None):
    pages = stack.events.pages()
    events = []
    end = False
    ready = start_func is None
    first = True
    while not end:
        page = next_page(pages)
        # update_columns(columns, page)
        # output_events(columns, [headers])
        # output_events(columns, page)
        # print(page)
        # print(stack.stack_id)
        if not page:
            break
        for event in page:
            events.append(event)
            if not ready:
                if start_func(event):
                    ready = True
                continue
            elif (
                event.resource_type == STACK_TYPE
                and event.resource_status.upper().endswith('COMPLETE')
                and event.physical_resource_id == stack.stack_id
                and (not first or event.resource_status.upper() != 'UPDATE_ROLLBACK_COMPLETE')
            ):
                end = True
                break
            first = False
    # update_columns(columns, events)
    # output_events(columns, [headers])
    # output_events(columns, events)
    events = sorted(
        (event for event in events if 'FAIL' in event.resource_status.upper()),
        key=lambda e: e.timestamp
    )
    # update_columns(columns, events)
    # output_events(columns, [headers])
    # output_events(columns, events)
    return events


def do_postmortem(stack, columns, headers, search_for_failure=False, show_all_failures=False):
    print('Getting events...')
    start_func = (
        (
            lambda event: (
                event.resource_type == STACK_TYPE
                and event.resource_status.upper() == 'UPDATE_ROLLBACK_COMPLETE'
                and event.physical_resource_id == stack.stack_id
            )
        )
        if search_for_failure else None
    )
    top_level = True
    events = []
    while True:
        new_events = get_stack_failure_events(
            stack,
            columns,
            headers,
            start_func=start_func
        )
        if not new_events:
            if top_level:
                print('The last stack update succeeded or there is an ongoing update which has no failures yet.')
                sys.exit(1)
            else:
                print('No failure events found in nested stack %r.' % (stack,))
                break
        if not show_all_failures:
            new_events = [new_events[0]]
        events.extend(new_events)
        fail_event = new_events[0]
        if (
            fail_event.resource_type != STACK_TYPE
            or 'failed to' not in fail_event.resource_status_reason.lower()
        ):
            break
        start_func = lambda event: event.timestamp <= fail_event.timestamp
        stack = get_stack(fail_event.physical_resource_id)

    events.sort(key=lambda e: e.timestamp, reverse=show_all_failures)
    update_columns(columns, events)
    output_events(columns, [headers])
    output_events(columns, events)


def main():
    args = docopt.docopt(__doc__)
    if args['--profile']:
        boto3.setup_default_session(profile_name=args['--profile'])
    postmortem = args['--postmortem']

    max_column_length = args['--max-column-length']
    if max_column_length is None:
        max_column_length = 200 if postmortem else 40
    max_column_length = int(max_column_length)

    columns = collections.OrderedDict([
        ('timestamp', Column(0, max_column_length)),
        ('stack_name', Column(0, max_column_length)),
        # ('stack_id', Column(0, max_column_length)),
        ('resource_type', Column(0, max_column_length)),
        ('logical_resource_id', Column(0, max_column_length)),
        # ('physical_resource_id', Column(0, max_column_length)),
        ('resource_status', Column(0, max_column_length)),
        ('resource_status_reason', Column(0, max_column_length)),
    ])
    headers = collections.namedtuple('Headers', columns.keys())(*[
        colorama.Style.BRIGHT + t + colorama.Style.RESET_ALL
        for t in [
            'Timestamp',
            'Stack Name',
            # 'Stack ID',
            'Resource Type',
            'Logical Resource ID',
            # 'Physical Resource ID',
            'Status',
            'Reason',
        ]
    ])
    update_columns(columns, [headers])

    print('Getting stack...')
    main_stack = get_stack(args['<stack>'])

    if postmortem:
        do_postmortem(main_stack, columns, headers, search_for_failure=args['--find-last-failure'], show_all_failures=args['--show-all-failures'])
    else:
        num = int(args['--number'])
        max_depth = int(args['--depth'])
        if max_depth == -1:
            max_depth = None
        do_tail_stack_events(main_stack, num, columns, headers, max_depth, args['--follow'])


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
