#!/usr/bin/env python

import logging
import time
from urllib.parse import urljoin

import requests
from relay_sdk import Interface, Dynamic as D

relay = Interface()

relay_api_url = relay.get(D.connection.relayAPIURL)
relay_api_token = relay.get(D.connection.token)

def get_or_default(path, default=None):
    try:
        return relay.get(path)
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 422:
            return default
        raise

data = {
    'type': 'task-run',
    'environment': get_or_default(D.environment),
    'scope': relay.get(D.scope),
    'name': relay.get(D.name),
    'params': get_or_default(D.params, {}),
    'noop': get_or_default(D.noop, False),
    'targets': get_or_default(D.targets, []),
}

headers = {'Authorization': f'Bearer {relay_api_token}'}

r = requests.post(
    urljoin(relay_api_url, '_puppet/runs'),
    json=data,
    headers=headers,
)
r.raise_for_status()

run = r.json()

relay.outputs.set('id', run['id'])

logging.info('Waiting for task run {} to start...'.format(run['id']))

while run['state']['status'] == 'pending':
    time.sleep(5)

    r = requests.get(urljoin(relay_api_url, '_puppet/runs/{}'.format(run['id'])), headers=headers)
    r.raise_for_status()

    run = r.json()

logging.info('Task run dispatched to Puppet server successfully!')

if run['state'].get('job_id'):
    relay.outputs.set('jobID', run['state']['job_id'])
    relay.outputs.set('results', run)

    logging.info('The Puppet Enterprise console may have more information for the job: {}'.format(run['state']['job_id']))

if get_or_default(D.wait_for_results, True):
    while True:
        r = requests.get(urljoin(relay_api_url, '_puppet/runs/{}'.format(run['id'])), headers=headers)
        r.raise_for_status()

        run = r.json()
        if run['state']['status'] != 'complete':
            # XXX: FIXME: We need to take into account next_update_before to handle
            # this properly.
            logging.info('Run is not yet complete (currently {}), waiting...'.format(run['state']['status']))

            time.sleep(5)
            continue

        if run['state'].get('job_id'):
            relay.outputs.set('jobID', run['state']['job_id'])

        if run['state'].get('outcome'):
            relay.outputs.set('outcome', run['state']['outcome'])

        if run['state'].get('run_results'):
            relay.outputs.set('results', run['state']['run_results'])

        if run['state'].get('outcome') == 'failed':
            logging.error('Run complete with outcome {}'.format(run['state'].get('outcome', '(unknown)')))
            if get_or_default(D.fail_on_fail, True):
                raise "Failure in task. Check task output for errors."

        else:
            logging.info('Run complete with outcome {}'.format(run['state'].get('outcome', '(unknown)')))

        break
