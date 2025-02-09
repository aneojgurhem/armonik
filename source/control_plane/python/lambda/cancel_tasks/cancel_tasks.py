# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
# Licensed under the Apache License, Version 2.0 https://aws.amazon.com/apache-2-0/

import json

import base64
import os
import traceback

from utils.state_table_common import TASK_STATUS_PENDING, TASK_STATUS_PROCESSING, TASK_STATUS_RETRYING

import logging

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(filename)s - %(funcName)s  - %(lineno)d - %(message)s",
                    datefmt='%H:%M:%S', level=logging.INFO)

from api.state_table_manager import state_table_manager

state_table = state_table_manager(grid_state_table_service=os.environ.get('TASKS_STATUS_TABLE_SERVICE', None),
                                  grid_state_table_config=os.environ.get('TASKS_STATUS_TABLE_CONFIG', None),
                                  tasks_state_table_name=os.environ.get('TASKS_STATUS_TABLE_NAME', None),
                                  endpoint_url=os.environ.get('DB_ENDPOINT_URL', None),
                                  region=os.environ.get('REGION', None))

task_states_to_cancel = [TASK_STATUS_RETRYING, TASK_STATUS_PENDING, TASK_STATUS_PROCESSING]


def cancel_tasks_by_status(session_id, task_state):
    """
    Cancel tasks of in the specific state within a session.

    Args:
        string: session_id
        string: task_state

    Returns:
        dict: results

    """

    response = state_table.get_tasks_by_status(session_id, task_state)
    print(response)

    for row in response:
        state_table.update_task_status_to_cancelled(row['task_id'])

    return response


def cancel_session(session_id):
    """
    Cancel all tasks within a session

    Args:
        string: session_id

    Returns:
        dict: results

    """

    lambda_response = {}

    all_cancelled_tasks = []
    for state in task_states_to_cancel:
        res = cancel_tasks_by_status(session_id, state)
        print("Cancelling session: {} status: {} result: {}".format(
            session_id, state, res))

        lambda_response["cancelled_{}".format(state)] = len(res)

        all_cancelled_tasks += res

    lambda_response["tatal_cancelled_tasks"] = len(all_cancelled_tasks)

    return (lambda_response)


def lambda_handler(event, context):
    print("event : " + str(event))
    try:

        lambda_response = {}
        if 'body' in event:
            session2cancel = json.loads(event['body']).get("session_id")
        else:
            session2cancel = event.get("session_id")

        lambda_response = cancel_session(session2cancel)

        if os.environ['API_GATEWAY_SERVICE'] == "APIGateway":
            res = {
                'statusCode': 200,
                'body': json.dumps(lambda_response)
            }
        elif os.environ['API_GATEWAY_SERVICE'] == "NGINX":
            res = lambda_response
        else:
            raise NotImplementedError()

        print("response output : ", res)
        return res

    except Exception as e:
        print('Lambda cancel_tasks error: {} trace: {}'.format(e, traceback.format_exc()))

        logging.error('Lambda cancel_tasks error: {} trace: {}'.format(e, traceback.format_exc()))
        if os.environ['API_GATEWAY_SERVICE'] == "APIGateway":
            res = {
                'statusCode': 542,
                'body': "{}".format(e)
            }
        elif os.environ['API_GATEWAY_SERVICE'] == "NGINX":
            res = "{}".format(e)
        else:
            raise NotImplementedError()
        return res
