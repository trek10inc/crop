import boto3
import os
import sys

def handler(event, context):
    scClient = boto3.client('servicecatalog')
    cfClient = boto3.client('cloudformation')
    
    product_id = os.environ['ProductId']
    provisioned_product_id = '-'.join(os.environ['StackName'].split('-')[2:])

    print("INFO: Checking Product %s for updates on Provisioned Product %s" % (product_id, provisioned_product_id))
    
    try:
        product = scClient.describe_product(Id=product_id)
    except:
        # We probably don't have permissions because SC is dumb and
        # describe_product_as_admin doesn't give us what we need...
        # allocate ourselves to the portfolio
        # next run the describe_product call should work
        portfolio_association = scClient.associate_principal_with_portfolio(
            PortfolioId=os.environ['PortfolioId'],
            PrincipalARN=os.environ['AutoUpdaterRoleARN'],
            PrincipalType='IAM'
        )
        print("Self assigning AutoUpdater to portfolio so it can call things needed")
        sys.exit(0)
    
    # Check stack created / updated at & status
    stack = cfClient.describe_stacks(StackName=os.environ['StackName'])['Stacks'][0]
    
    if stack['StackStatus'] not in ['CREATE_COMPLETE', 'UPDATE_COMPLETE', 'UPDATE_ROLLBACK_COMPLETE']:
        print("Stack is currently updating... skipping further checks")
        sys.exit(0)
    
    last_action = stack['CreationTime']
    if 'LastUpdatedTime' in stack:
        last_action = stack['LastUpdatedTime']

    latest_artifact = product['ProvisioningArtifacts'][-1]

    if latest_artifact['CreatedTime'] > last_action:
        print('Execute an AutoUpdate')
        
        params = []
        for param in stack['Parameters']:
            params.append({
                'Key': param['ParameterKey'],
                'UsePreviousValue': True
            })

        response = scClient.update_provisioned_product(
            ProvisionedProductId=provisioned_product_id,
            ProductId=product_id,
            ProvisioningArtifactId=latest_artifact['Id'],
            ProvisioningParameters=params
        )
    
    