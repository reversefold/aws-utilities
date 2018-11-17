#!/usr/bin/env python
import os
import sys


CREDFILE = os.path.expanduser('~/.aws/credentials')


with open(CREDFILE, 'r') as f:
    text = f.read()

creds = {}
for group in text.split('['):
    if not group.strip():
        continue
    name, rest = group.strip().split(']')
    creds[name.strip()] = {
        k.strip(): v.strip()
        for k, v in (
            line.split('=')
            for line in rest.strip().split('\n')
            if line and '=' in line
        )
    }

if len(sys.argv) != 2:
    print('Available profiles:\n%s' % ('\n'.join('* %s' % (profile) for profile in creds.keys() if profile != 'default')))
    sys.exit()
profile = sys.argv[1]
wanted = creds[profile]

creds['default'] = wanted

text = '\n\n'.join(
    '[%s]\n%s' % (name, '\n'.join('%s=%s' % (k, v) for k, v in values.items()))
    for name, values in creds.items()
)
with open(CREDFILE, 'w') as f:
    f.write(text)

print('Made %s default' % (profile,))
