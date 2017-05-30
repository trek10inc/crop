# -*- coding: utf-8 -*-
# Author: Ryan Scott Brown <sb@ryansb.com>
# License: Apache v2.0

import os
import six
from .logging import log

def pop_bucket(template):
    """Remove CFN resources that create the bucket for serverless artifacts"""
    template['Resources'].pop('ServerlessDeploymentBucket')
    template['Outputs'].pop('ServerlessDeploymentBucketName')
    log.debug('filters.pop_bucket', popped='ServerlessDeploymentBucket,ServerlessDeploymentBucketName')
    return template


def replace_function_artifacts(template, asset_bucket, asset_key_map):
    """Replace the code bucket/key with the public CROP bucket on AWS::Lambda::Function types

    template: dict CFN template
    asset_bucket: str name of the S3 bucket that consumers of the product will be able to access
    asset_key_map: dict of the keys/artifacts to be replaced and a string or 2-tuple of key&version
    """
    for logical_id, resource in template['Resources'].items():
        if resource["Type"] != "AWS::Lambda::Function":
            # then the resource doesn't have a code type, so we needn't modify it
            continue

        asset_name = os.path.basename(resource['Properties']['Code']['S3Key'])

        # Find the right asset key/version information
        new_code = {'S3Bucket': asset_bucket}

        if isinstance(asset_key_map[asset_name], six.text_type):
            key = asset_key_map[asset_name]
            new_code['S3Key'] = key
        else:
            key, version = asset_key_map[asset_name]
            new_code['S3Key'] = key
            new_code['S3ObjectVersion'] = version

        # Modify the Lambda function to get its code from the distribution bucket
        resource['Properties']['Code'] = new_code
        log.debug('filters.replace_function_artifacts', logical_resource=logical_id, resource=resource)

    return template


def inject_autoupdate(template, catalog_id, product_id, force=False, interval=15):
    """Inject a Lambda Function (and possible CF Param) for auto updating the
    service based on polling. You can either force this update, or allow it to be optional,
    in which case it is set by a CF dropdown parameter when the user starts the stack from
    the service catalog.

    template: dict CloudFormation template

    product_id: str product ID to take updates from. This will be injected into the
                updater function environment variables.

    force: bool should the template update be forced or optional

    interval: int the number of minutes between autoupdate checks
    """


    if any((x in template['Resources'] for x in (
            'CROPAutoUpdaterRole',
            'CROPAutoUpdaterEvent',
            'CROPAutoUpdaterEventPermission',
            'CROPAutoUpdaterFunction'
        ))):
        raise ValueError('Resource logical IDs conflict with keys used by CROP')

    if 'AutoUpdates' in template['Parameters']:
        raise ValueError('Param IDs conflict with Param IDs used by CROP')

    if ('Conditions' in template.keys()) and ('CROPAutoUpdating' in template['Conditions']):
        raise ValueError('Condition IDs conflict with Conditions IDs used by CROP')

    # role
    template['Resources']['CROPAutoUpdaterRole'] = {
        'Type':'AWS::IAM::Role',
        'Properties': {
            # Add update policy
            'AssumeRolePolicyDocument': {
                'Version': '2012-10-17',
                'Statement': [
                    {
                        'Action': ['sts:AssumeRole'],
                        'Effect': 'Allow',
                        'Principal': {
                            'Service': [
                                'lambda.amazonaws.com'
                            ]
                        }
                    }
                ],
            },
            'Policies': [{
                'PolicyName': 'AutoUpdateServiceCatalog',
                'PolicyDocument': {
                    'Version': '2012-10-17',
                    'Statement': [{
                        'Action': ['*'],
                        'Effect': 'Allow',
                        'Resource': ['*']
                    }],
                }
            }]
        }
    }

    if interval < 1:
        raise ValueError('Cannot specify an interval less than 1 (minute)')

    if interval == 1:
        interval_string = '1 minute'
    else:
        interval_string = '{} minutes'.format(interval)

    # event
    template['Resources']['CROPAutoUpdaterEvent'] = {
        'Type':'AWS::Events::Rule',
        'Properties': {
            'ScheduleExpression': 'rate({})'.format(interval_string),
            'State': 'ENABLED',
            'Targets': [{
                'Arn': {'Fn::GetAtt': ['CROPAutoUpdaterFunction', 'Arn']},
                'Id': 'autoUpdaterSchedule'
            }]
        }
    }

    # allow aws to invoke lambda with event
    template['Resources']['CROPAutoUpdaterEventPermission'] = {
        'Type': 'AWS::Lambda::Permission',
        'Properties': {
            'Action': 'lambda:InvokeFunction',
            'FunctionName': {'Fn::GetAtt': ['CROPAutoUpdaterFunction', 'Arn']},
            'Principal': 'events.amazonaws.com',
            'SourceArn': {'Fn::GetAtt': ['CROPAutoUpdaterEvent', 'Arn']}
        }
    }

    basepath = os.path.dirname(__file__)
    autoupdater_path = os.path.abspath(os.path.join(basepath, "autoupdater.py"))
    with open(autoupdater_path) as auto_update_file:
        compiled_autoupdater = []
        content = auto_update_file.readlines()
        for line in content:
            compiled_autoupdater.append(line.rstrip())

    template['Resources']['CROPAutoUpdaterFunction'] = {
        'Type':'AWS::Lambda::Function',
        'Properties': {
            'Code': {
                'ZipFile': {"Fn::Join" : ["\n", compiled_autoupdater]}
            },
            'Description': 'AutoUpdater for ServiceCatalog Function',
            'Handler': 'index.handler',
            'MemorySize': '256',
            'Environment': {
                'Variables': {
                    'PortfolioId': catalog_id,
                    'StackName': {'Ref': 'AWS::StackName'},
                    'AutoUpdaterRoleARN': {'Fn::GetAtt': ['CROPAutoUpdaterRole', 'Arn']},
                    'ProductId': product_id
                }
            },
            'Role': {'Fn::GetAtt': ['CROPAutoUpdaterRole', 'Arn']},
            'Runtime': 'python2.7',
            'Timeout': 30
        }
    }

    if not force:
        template.setdefault('Parameters', {})
        template['Parameters']['AutoUpdates'] = {
            'Type': 'String',
            'Description': ('Allow the service to automatically update itself when'
                            'an update is available, otherwise you must manually approve updates.'),
            'AllowedValues': ['Enable', 'Disable'],
            'Default': 'Enable'
        }

        # conditionals on roles / event / lambda
        template.setdefault('Conditions', {})
        template['Conditions']['CROPAutoUpdating'] = {'Fn::Equals' : [{'Ref' : 'AutoUpdates'}, 'Enable']}
        template['Resources']['CROPAutoUpdaterFunction']['Condition'] = 'CROPAutoUpdating'
        template['Resources']['CROPAutoUpdaterEventPermission']['Condition'] = 'CROPAutoUpdating'
        template['Resources']['CROPAutoUpdaterEvent']['Condition'] = 'CROPAutoUpdating'
        template['Resources']['CROPAutoUpdaterRole']['Condition'] = 'CROPAutoUpdating'


    log.debug('filters.inject_autoupdate', template=template)
    return template
