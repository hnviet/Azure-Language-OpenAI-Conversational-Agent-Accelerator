using 'main.bicep'

param gpt_model_name = readEnvironmentVariable('AZURE_ENV_GPT_MODEL_NAME', 'gpt-4o-mini')
param gpt_deployment_capacity = int(readEnvironmentVariable('AZURE_ENV_GPT_MODEL_CAPACITY', '100'))
param gpt_deployment_type = readEnvironmentVariable('AZURE_ENV_GPT_MODEL_DEPLOYMENT_TYPE', 'GlobalStandard')

param embedding_model_name = readEnvironmentVariable('AZURE_ENV_EMBEDDING_MODEL_NAME', 'text-embedding-ada-002')
param embedding_deployment_capacity = int(readEnvironmentVariable('AZURE_ENV_EMBEDDING_MODEL_CAPACITY', '100'))
param embedding_deployment_type = readEnvironmentVariable('AZURE_ENV_EMBEDDING_MODEL_DEPLOYMENT_TYPE', 'GlobalStandard')

// Name of your Azure Container Registry for role assignments
param acr_name = readEnvironmentVariable('AZURE_ENV_ACR_NAME', 'hnvietacr')

// Tag of the image to deploy
param image_tag = readEnvironmentVariable('AZURE_ENV_IMAGE_TAG', 'latest')

param acs_connection_string = readEnvironmentVariable('AZURE_ENV_ACS_CONNECTION', '')
