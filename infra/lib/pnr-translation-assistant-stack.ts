import * as path from 'path';
import * as fs from 'fs';
import * as cdk from 'aws-cdk-lib';
import { Duration, RemovalPolicy, Stack, StackProps } from 'aws-cdk-lib';
import * as apigwv2 from 'aws-cdk-lib/aws-apigatewayv2';
import * as authorizers from 'aws-cdk-lib/aws-apigatewayv2-authorizers';
import * as integrations from 'aws-cdk-lib/aws-apigatewayv2-integrations';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as kms from 'aws-cdk-lib/aws-kms';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import { Construct } from 'constructs';

export class PnrTranslationAssistantStack extends Stack {
  constructor(scope: Construct, id: string, props?: StackProps) {
    super(scope, id, props);

    const primaryModelId = new cdk.CfnParameter(this, 'PrimaryModelId', {
      type: 'String',
      default: 'moonshotai.kimi-k2.5',
      description: 'Amazon Bedrock Kimi model used for the main translation path.',
    });

    const reviewModelId = new cdk.CfnParameter(this, 'ReviewModelId', {
      type: 'String',
      default: 'moonshot.kimi-k2-thinking',
      description: 'Amazon Bedrock Kimi model used for complex review path.',
    });

    const autoExecutionEnabled = new cdk.CfnParameter(this, 'AutoExecutionEnabled', {
      type: 'String',
      default: 'false',
      allowedValues: ['true', 'false'],
      description: 'Enable automatic execution for low-risk allowlisted intents.',
    });

    const dataKey = new kms.Key(this, 'PnrDataKey', {
      enableKeyRotation: true,
      alias: 'alias/pnr-translation-assistant-data',
      removalPolicy: RemovalPolicy.DESTROY,
    });

    const translationsTable = new dynamodb.Table(this, 'TranslationsTable', {
      partitionKey: { name: 'translation_id', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'tenant_id', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
      encryptionKey: dataKey,
      pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
      removalPolicy: RemovalPolicy.DESTROY,
    });

    translationsTable.addGlobalSecondaryIndex({
      indexName: 'tenant-created-index',
      partitionKey: { name: 'tenant_id', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'created_at', type: dynamodb.AttributeType.NUMBER },
    });

    const executionsTable = new dynamodb.Table(this, 'ExecutionsTable', {
      partitionKey: { name: 'idempotency_key', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
      encryptionKey: dataKey,
      pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
      removalPolicy: RemovalPolicy.DESTROY,
    });

    const commandBucket = new s3.Bucket(this, 'SecureCommandBucket', {
      encryption: s3.BucketEncryption.KMS,
      encryptionKey: dataKey,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      versioned: true,
      lifecycleRules: [
        {
          id: 'expire-secure-command-payloads',
          prefix: 'secure-commands/',
          expiration: Duration.days(7),
          noncurrentVersionExpiration: Duration.days(7),
        },
      ],
      removalPolicy: RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    });

    const fnLogGroup = new logs.LogGroup(this, 'PnrTranslationFunctionLogGroup', {
      retention: logs.RetentionDays.ONE_MONTH,
      removalPolicy: RemovalPolicy.DESTROY,
    });

    const fn = new lambda.Function(this, 'PnrTranslationFunction', {
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'pnr_service.handler.lambda_handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../../src')),
      timeout: Duration.seconds(30),
      memorySize: 512,
      logGroup: fnLogGroup,
      environment: {
        PRIMARY_MODEL_ID: primaryModelId.valueAsString,
        REVIEW_MODEL_ID: reviewModelId.valueAsString,
        TRANSLATIONS_TABLE: translationsTable.tableName,
        EXECUTIONS_TABLE: executionsTable.tableName,
        COMMAND_BUCKET: commandBucket.bucketName,
        COMMAND_PREFIX: 'secure-commands/',
        AUTO_EXECUTION_ENABLED: autoExecutionEnabled.valueAsString,
      },
    });

    translationsTable.grantReadWriteData(fn);
    executionsTable.grantReadWriteData(fn);
    commandBucket.grantReadWrite(fn);
    dataKey.grantEncryptDecrypt(fn);
    fn.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream'],
        resources: [
          Stack.of(this).formatArn({
            service: 'bedrock',
            region: Stack.of(this).region,
            account: '',
            resource: 'foundation-model',
            resourceName: primaryModelId.valueAsString,
          }),
          Stack.of(this).formatArn({
            service: 'bedrock',
            region: Stack.of(this).region,
            account: '',
            resource: 'foundation-model',
            resourceName: reviewModelId.valueAsString,
          }),
        ],
      }),
    );
    const integration = new integrations.HttpLambdaIntegration('PnrLambdaIntegration', fn);
    const userPool = new cognito.UserPool(this, 'PnrUserPool', {
      selfSignUpEnabled: false,
      signInAliases: { email: true },
      removalPolicy: RemovalPolicy.DESTROY,
    });
    const userPoolClient = new cognito.UserPoolClient(this, 'PnrUserPoolClient', {
      userPool,
      generateSecret: false,
      authFlows: { userPassword: true, userSrp: true },
    });
    for (const groupName of ['translator', 'executor', 'reviewer', 'admin', 'auditor']) {
      new cognito.CfnUserPoolGroup(this, `Pnr${groupName}Group`, {
        userPoolId: userPool.userPoolId,
        groupName,
      });
    }
    const jwtAuthorizer = new authorizers.HttpUserPoolAuthorizer('PnrJwtAuthorizer', userPool, {
      userPoolClients: [userPoolClient],
    });

    const api = new apigwv2.HttpApi(this, 'PnrApi', {
      apiName: 'pnr-translation-assistant-api',
      description: 'Natural-language to PNR command translation API.',
      corsPreflight: {
        // Demo scope: the EC2 test UI origin is only known post-deploy, so all
        // origins are allowed. The API is JWT-bearer only (no cookies), so this
        // does not expose ambient-credential CSRF. In production, restrict this
        // to the known web origin(s).
        allowOrigins: ['*'],
        allowMethods: [
          apigwv2.CorsHttpMethod.OPTIONS,
          apigwv2.CorsHttpMethod.POST,
        ],
        allowHeaders: ['authorization', 'content-type'],
        maxAge: Duration.days(1),
      },
    });

    api.addRoutes({
      path: '/',
      methods: [apigwv2.HttpMethod.GET],
      integration,
    });
    api.addRoutes({
      path: '/v1/pnr/translate',
      methods: [apigwv2.HttpMethod.POST],
      integration,
      authorizer: jwtAuthorizer,
    });
    api.addRoutes({
      path: '/v1/pnr/execute',
      methods: [apigwv2.HttpMethod.POST],
      integration,
      authorizer: jwtAuthorizer,
    });
    api.addRoutes({
      path: '/v1/pnr/reviews/{review_id}/approve',
      methods: [apigwv2.HttpMethod.POST],
      integration,
      authorizer: jwtAuthorizer,
    });
    api.addRoutes({
      path: '/v1/pnr/reviews/{review_id}/reject',
      methods: [apigwv2.HttpMethod.POST],
      integration,
      authorizer: jwtAuthorizer,
    });

    const webVpc = new ec2.Vpc(this, 'WebVpc', {
      maxAzs: 1,
      natGateways: 0,
      subnetConfiguration: [
        {
          name: 'public',
          subnetType: ec2.SubnetType.PUBLIC,
          cidrMask: 24,
        },
      ],
    });
    const webSecurityGroup = new ec2.SecurityGroup(this, 'WebSecurityGroup', {
      vpc: webVpc,
      allowAllOutbound: true,
      description: 'Allow HTTP access to the PNR test web UI.',
    });
    webSecurityGroup.addIngressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(80), 'HTTP');

    const webInstance = new ec2.Instance(this, 'WebInstance', {
      vpc: webVpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PUBLIC },
      securityGroup: webSecurityGroup,
      instanceType: ec2.InstanceType.of(ec2.InstanceClass.T3, ec2.InstanceSize.MICRO),
      machineImage: ec2.MachineImage.latestAmazonLinux2023(),
      requireImdsv2: true,
      userDataCausesReplacement: false,
    });
    const webInstanceResource = webInstance.node.defaultChild as ec2.CfnInstance;
    webInstanceResource.overrideLogicalId('WebInstanceF774E10D603b593bd8cf42fa');
    webInstance.role.addManagedPolicy(
      iam.ManagedPolicy.fromAwsManagedPolicyName('AmazonSSMManagedInstanceCore'),
    );
    const webDir = path.join(__dirname, '../../web');
    webInstance.userData.addCommands(
      'for i in 1 2 3 4 5 6; do dnf install -y nginx && break || sleep 10; done',
      'test -f /usr/lib/systemd/system/nginx.service',
      'systemctl enable nginx',
      'mkdir -p /usr/share/nginx/html',
      renderFileCommand('/usr/share/nginx/html/index.html', fs.readFileSync(path.join(webDir, 'index.html'), 'utf8')),
      renderFileCommand('/usr/share/nginx/html/styles.css', fs.readFileSync(path.join(webDir, 'styles.css'), 'utf8')),
      renderFileCommand('/usr/share/nginx/html/app.js', fs.readFileSync(path.join(webDir, 'app.js'), 'utf8')),
      renderFileCommand('/usr/share/nginx/html/config.js', `window.PNR_APP_CONFIG = { apiUrl: "${api.apiEndpoint}" };\n`),
      'systemctl restart nginx',
    );
    fn.addEnvironment('WEB_URL', `http://${webInstance.instancePublicDnsName}`);

    new cdk.CfnOutput(this, 'ApiUrl', {
      value: api.apiEndpoint,
      description: 'HTTP API endpoint.',
    });
    new cdk.CfnOutput(this, 'TranslationsTableName', {
      value: translationsTable.tableName,
    });
    new cdk.CfnOutput(this, 'ExecutionsTableName', {
      value: executionsTable.tableName,
    });
    new cdk.CfnOutput(this, 'SecureCommandBucketName', {
      value: commandBucket.bucketName,
    });
    new cdk.CfnOutput(this, 'UserPoolId', {
      value: userPool.userPoolId,
    });
    new cdk.CfnOutput(this, 'UserPoolClientId', {
      value: userPoolClient.userPoolClientId,
    });
    new cdk.CfnOutput(this, 'WebUrl', {
      value: `http://${webInstance.instancePublicDnsName}`,
      description: 'EC2-hosted web test UI.',
    });
  }
}

function renderFileCommand(target: string, content: string): string {
  return `cat > ${target} <<'PNR_WEB_EOF'\n${content}\nPNR_WEB_EOF`;
}
