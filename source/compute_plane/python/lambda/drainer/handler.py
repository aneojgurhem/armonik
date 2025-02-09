# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
# Licensed under the Apache License, Version 2.0 https://aws.amazon.com/apache-2-0/

import boto3
import base64
import logging
import os.path
import re
import yaml

from botocore.signers import RequestSigner
import kubernetes as k8s
from kubernetes.client.rest import ApiException

from k8s_utils import (abandon_lifecycle_action, cordon_node, node_exists, remove_all_pods)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

KUBE_FILEPATH = '/tmp/kubeconfig'
region = os.environ.get('AWS_REGION', None)

eks = boto3.client('eks', region_name=region)
ec2 = boto3.client('ec2', region_name=region)
asg = boto3.client('autoscaling', region_name=region)
s3 = boto3.client('s3', region_name=region)


def create_kube_config(eks, cluster_name):
    """Creates the Kubernetes config file required when instantiating the API client."""
    cluster_info = eks.describe_cluster(name=cluster_name)['cluster']
    certificate = cluster_info['certificateAuthority']['data']
    endpoint = cluster_info['endpoint']

    kube_config = {
        'apiVersion': 'v1',
        'clusters': [
            {
                'cluster':
                    {
                        'server': endpoint,
                        'certificate-authority-data': certificate
                    },
                'name': 'k8s'

            }],
        'contexts': [
            {
                'context':
                    {
                        'cluster': 'k8s',
                        'user': 'aws'
                    },
                'name': 'aws'
            }],
        'current-context': 'aws',
        'Kind': 'config',
        'users': [
            {
                'name': 'aws',
                'user': 'lambda'
            }]
    }

    with open(KUBE_FILEPATH, 'w') as f:
        yaml.dump(kube_config, f, default_flow_style=False)


def get_bearer_token(cluster, region):
    """Creates the authentication to token required by AWS IAM Authenticator. This is
    done by creating a base64 encoded string which represents a HTTP call to the STS
    GetCallerIdentity Query Request (https://docs.aws.amazon.com/STS/latest/APIReference/API_GetCallerIdentity.html).
    The AWS IAM Authenticator decodes the base64 string and makes the request on behalf of the user.
    """
    STS_TOKEN_EXPIRES_IN = 60
    session = boto3.session.Session()

    client = session.client('sts', region_name=region)
    service_id = client.meta.service_model.service_id

    signer = RequestSigner(
        service_id,
        region,
        'sts',
        'v4',
        session.get_credentials(),
        session.events
    )

    params = {
        'method': 'GET',
        'url': 'https://sts.{}.amazonaws.com/?Action=GetCallerIdentity&Version=2011-06-15'.format(region),
        'body': {},
        'headers': {
            'x-k8s-aws-id': cluster
        },
        'context': {}
    }

    signed_url = signer.generate_presigned_url(
        params,
        region_name=region,
        expires_in=STS_TOKEN_EXPIRES_IN,
        operation_name=''
    )

    base64_url = base64.urlsafe_b64encode(signed_url.encode('utf-8')).decode('utf-8')

    # need to remove base64 encoding padding:
    # https://github.com/kubernetes-sigs/aws-iam-authenticator/issues/202
    return 'k8s-aws-v1.' + re.sub(r'=*', '', base64_url)


def _lambda_handler(env, k8s_config, k8s_client, event):
    kube_config_bucket = env['kube_config_bucket']
    cluster_name = env['cluster_name']

    if not os.path.exists(KUBE_FILEPATH):
        if kube_config_bucket:
            logger.info('No kubeconfig file found. Downloading...')
            s3.download_file(kube_config_bucket, env['kube_config_object'], KUBE_FILEPATH)
        else:
            logger.info('No kubeconfig file found. Generating...')
            create_kube_config(eks, cluster_name)

    lifecycle_hook_name = event['detail']['LifecycleHookName']
    auto_scaling_group_name = event['detail']['AutoScalingGroupName']

    instance_id = event['detail']['EC2InstanceId']
    logger.info('Instance ID: ' + instance_id)
    instance = ec2.describe_instances(InstanceIds=[instance_id])['Reservations'][0]['Instances'][0]

    node_name = instance['PrivateDnsName']
    logger.info('Node name: ' + node_name)

    # Configure
    k8s_config.load_kube_config(KUBE_FILEPATH)
    configuration = k8s_client.Configuration()
    if not kube_config_bucket:
        configuration.api_key['authorization'] = get_bearer_token(cluster_name, region)
        configuration.api_key_prefix['authorization'] = 'Bearer'
    # API
    api = k8s_client.ApiClient(configuration)
    v1 = k8s_client.CoreV1Api(api)

    try:
        if not node_exists(v1, node_name):
            logger.error('Node not found.')
            abandon_lifecycle_action(asg, auto_scaling_group_name, lifecycle_hook_name, instance_id)
            return

        cordon_node(v1, node_name)

        remove_all_pods(v1, node_name)
        print("all pods terminated")
        logger.info("all pods terminated")
        asg.complete_lifecycle_action(LifecycleHookName=lifecycle_hook_name,
                                      AutoScalingGroupName=auto_scaling_group_name,
                                      LifecycleActionResult='CONTINUE',
                                      InstanceId=instance_id)
        print("lifecycling hooks over")
        logger.info("lifecycling hooks over")
    except ApiException:
        logger.exception('There was an error removing the pods from the node {}'.format(node_name))
        abandon_lifecycle_action(asg, auto_scaling_group_name, lifecycle_hook_name, instance_id)


def lambda_handler(event, _):
    env = {
        'cluster_name': os.environ.get('CLUSTER_NAME'),
        'kube_config_bucket': os.environ.get('KUBE_CONFIG_BUCKET'),
        'kube_config_object': os.environ.get('KUBE_CONFIG_OBJECT')
    }
    return _lambda_handler(env, k8s.config, k8s.client, event)
