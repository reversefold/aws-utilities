# aws-utilities

This package includes various command-line utilities for use with aws.

To set up a local checkout with [pyenv](https://github.com/pyenv/pyenv) run these commands:
```
git clone https://github.com/reversefold/aws-utilities.git
cd aws-utilities
pyenv virtualenv 3.6.5 aws-utilities
pyenv local aws-utilities
pip install -r dev-requirements.txt
./sync-requirements.sh
```


## tail_cloudwatch_logs.py

Get the last `n` lines of a cloudwatch log group and follow the output in realtime as it is written to CloudWatch Logs. Has the ability to use any profile set up in your `~/.aws/credentials` so working across multiple accounts is easy.

Inspired by [cw](https://github.com/lucagrulla/cw).


## tail_stack_events.py

Get the last `n` events for a CloudFormation stack and all of its nested stacks and follow the events in realtime. This utility can give you a view into all of the events happening in any size CloudFormation stack, even if it has multiple levels of nested stacks. When this script is started up it finds all nested stacks and follows their events as well if the stack is in any status which includes IN_PROGRESS. When following stack events, nested stacks will be dynamically added to and removed from the set of stacks being queried for events as nested stacks go into the various `IN_PROGRESS` and `COMPLETE` states. This lets you get a complete picture of what is going on while also making the minimum number of API calls.

In postmortem mode this script will find the events that caused the last stack update to fail. It will follow nested stack failures until it finds the specific resource that caused the failure.

Originally inspired by [tail-stack-events](https://github.com/tmont/tail-stack-events) and [cfn-tail](https://github.com/taimos/cfn-tail).


## aws_switch.py

A quick and dirty script to make any one of your configured aws profiles the default profile. Useful when you're using tools which don't support profiles or when you work in distinct profiles at distinct times.


## wait_for_stack_complete.py

A simple script for running on an ec2 instance. No parameters are taken. Finds the CloudFormation stack that the instance resides in and polls until the stack is in a `COMPLETE` state. If the stack has a parent stack it will watch that one instead. Has retries with exponential backoff (up to 5m) for all API calls so as to not overload the AWS APIs when used in a large environment. This script is particularly useful for UserData or cfn-init scripts which need to wait for other resources to be created and attached, such as EBS volumes not included in the instance's BlockDeviceMapping.
