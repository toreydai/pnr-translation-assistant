import * as cdk from 'aws-cdk-lib';
import { PnrTranslationAssistantStack } from '../lib/pnr-translation-assistant-stack';

const app = new cdk.App();

new PnrTranslationAssistantStack(app, 'PnrTranslationAssistantStack', {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: process.env.CDK_DEFAULT_REGION || 'us-east-1',
  },
});

