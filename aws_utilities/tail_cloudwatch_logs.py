#!/usr/bin/env python
"""Usage:
    tail_cloudwatch_logs.py [--follow] [--profile=<profile>] [--number=<n>] <log_group>

Options:
    -f --follow                    Follow the log events and output new ones as they are received.
    -p <p> --profile=<profile>     The aws profile to use.
    -n <n> --number=<n>            The number of lines to display. [default: 10]
    <log_group>                    The log group to get log events for.
"""
import datetime
import sys
import time
import traceback

import eventlet
eventlet.monkey_patch()

import botocore.exceptions
import boto3
import docopt
import eventlet
import eventlet.greenpool


def main():
    args = docopt.docopt(__doc__)
    if args['--profile']:
        boto3.setup_default_session(profile_name=args['--profile'])
    num = int(args['--number'])
    log_group = args['<log_group>']

    cwl = boto3.client('logs')

    def get_log_streams(log_group):
        log_streams = [
            ls['logStreamName'] for ls in
            cwl.describe_log_streams(
                logGroupName=log_group,
                orderBy='LastEventTime',
                descending=True,
                limit=10
            )['logStreams']
        ]
        return log_streams

    log_streams = set(get_log_streams(log_group))

    def get_stream_events(log_group, log_stream, num, start_time):
        try:
            events = []
            for event in cwl.get_log_events(
                logGroupName=log_group, logStreamName=log_stream, limit=num, startTime=start_time
            )['events']:
                event['log_group'] = log_group
                event['log_stream'] = log_stream
                events.append(event)
            return events
        except botocore.exceptions.ClientError:
            return []

    def get_events(log_group, log_streams, start_time=0):
        all_events = []
        pool = eventlet.greenpool.GreenPool(5)
        # for log_stream in log_streams:
        #     events = cwl.get_log_events(
        #         logGroupName=log_group,
        #         logStreamName=log_stream,
        #         limit=num,
        #         startTime=start_time
        #     )
        for events in pool.starmap(
            get_stream_events,
            [
                (log_group, log_stream, num, start_time)
                for log_stream in log_streams
            ]
        ):
            all_events.extend(events)
        all_events.sort(key=lambda e: e['timestamp'])
        return all_events

    events = get_events(log_group, log_streams)

    def print_events(events):
        for e in events[-num:]:
            print(
                '%s %s %s' % (
                    datetime.datetime.fromtimestamp(e['timestamp'] / 1000.0),
                    e['log_stream'],
                    e['message'].rstrip('\n')
                )
            )

    print_events(events)
    # print(events[-1].keys())

    if not args['--follow']:
        return

    def log_stream_updater():
        while True:
            try:
                log_streams.update(get_log_streams(log_group))
            except botocore.exceptions.ClientError:
                time.sleep(5)
            time.sleep(5)

    eventlet.spawn(log_stream_updater)

    while True:
        try:
            time.sleep(1)
            new_events = get_events(log_group, log_streams, start_time=events[-1]['timestamp'] + 1)
            if new_events:
                events = new_events
                print_events(events)
            # else:
            #     print('...')
        except Exception:
            traceback.print_exc()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
