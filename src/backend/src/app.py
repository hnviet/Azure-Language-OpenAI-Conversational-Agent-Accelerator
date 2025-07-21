# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
import os
import json
import logging
import pii_redacter
from typing import Any, Dict, List
from fastapi import Body,FastAPI, HTTPException
from fastapi.concurrency import asynccontextmanager
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel
from semantic_kernel_orchestrator import SemanticKernelOrchestrator
from azure.identity.aio import DefaultAzureCredential
from semantic_kernel.agents import AzureAIAgent
from utils import get_azure_credential
from aoai_client import AOAIClient, get_prompt
from azure.search.documents import SearchClient
from azure.communication.sms.aio import SmsClient

# Run locally with `uvicorn app:app --reload --host 127.0.0.1 --port 7000`
# Comment out for local testing:
# from dotenv import load_dotenv
# load_dotenv()


# Initialize structure for holding chat requests
class ChatRequest(BaseModel):
    message: str


# Environment variables
PROJECT_ENDPOINT = os.environ.get("AGENTS_PROJECT_ENDPOINT")
MODEL_NAME = os.environ.get("AOAI_DEPLOYMENT")
CONFIG_DIR = os.environ.get("CONFIG_DIR", ".")
config_file = os.path.join(CONFIG_DIR, "config.json")

# Read config.json file from the config directory
if os.path.exists(config_file):
    with open(config_file, "r") as f:
        AGENT_IDS = json.load(f)
else:
    AGENT_IDS = {}

# Comment out for local testing:
# AGENT_IDS = {
#     "TRIAGE_AGENT_ID": os.environ.get("TRIAGE_AGENT_ID"),
#     "HEAD_SUPPORT_AGENT_ID": os.environ.get("HEAD_SUPPORT_AGENT_ID"),
#     "ORDER_STATUS_AGENT_ID": os.environ.get("ORDER_STATUS_AGENT_ID"),
#     "ORDER_CANCEL_AGENT_ID": os.environ.get("ORDER_CANCEL_AGENT_ID"),
#     "ORDER_REFUND_AGENT_ID": os.environ.get("ORDER_REFUND_AGENT_ID"),
# }

# Check if all required agent IDs are present
required_agents = [
    "TRIAGE_AGENT_ID",
    "HEAD_SUPPORT_AGENT_ID",
    "ORDER_STATUS_AGENT_ID",
    "ORDER_CANCEL_AGENT_ID",
    "ORDER_REFUND_AGENT_ID"
]

missing_agents = [agent for agent in required_agents if not AGENT_IDS.get(agent)]
if missing_agents:
    error_msg = f"Missing required agent IDs: {', '.join(missing_agents)}"
    logging.error(error_msg)
    raise ValueError(error_msg)

DIST_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "dist"))
# log dist_dir
print(f"DIST_DIR: {DIST_DIR}")

# Initialize the Azure Search client
search_client = SearchClient(
    endpoint=os.environ.get("SEARCH_ENDPOINT"),
    index_name=os.environ.get("SEARCH_INDEX_NAME"),
    credential=get_azure_credential()
)
print("Search client initialized.")

# RAG AOAI client:
rag_client = AOAIClient(
    endpoint=os.environ.get("AOAI_ENDPOINT"),
    deployment=os.environ.get("AOAI_DEPLOYMENT"),
    use_rag=True,
    search_client=search_client
)
print("RAG client initialized.")

# Extract-utterances AOAI client:
extract_prompt = get_prompt("extract_utterances.txt")
extract_client = AOAIClient(
    endpoint=os.environ.get("AOAI_ENDPOINT"),
    deployment=os.environ.get("AOAI_DEPLOYMENT"),
    system_message=extract_prompt
)

# PII:
PII_ENABLED = os.environ.get("PII_ENABLED", "false").lower() == "true"
print(f"PII_ENABLED: {PII_ENABLED}")

# after you’ve loaded your other env‐vars:
SMS_CONN_STR    = os.environ["ACS_CONNECTION_STRING"]
ACS_PHONE_NUMBER= os.environ["ACS_PHONE_NUMBER"]

# create a long‐lived client
sms_client = SmsClient.from_connection_string(SMS_CONN_STR)

# Fallback function (RAG) definition:
def fallback_function(
    query: str,
    language: str,
    id: int
) -> str:
    """
    Call RAG client for grounded chat completion.
    """
    if PII_ENABLED:
        # Redact PII:
        query = pii_redacter.redact(
            text=query,
            id=id,
            language=language,
            cache=True
        )

    return rag_client.chat_completion(query)


# Function to handle processing and orchestrating a chat message with utterance extraction, fallback handling, and PII redaction
async def orchestrate_chat(message: str, orchestrator: SemanticKernelOrchestrator, chat_id: int) -> list[str]:
    responses = []
    print(f"Processing message: {message} with chat_id: {chat_id}")
    try:
        # Handle PII redaction if enabled
        if PII_ENABLED:
            print(f"Redacting PII for message: {message} with chat_id: {chat_id}")
            message = pii_redacter.redact(
                text=message,
                id=chat_id,
                cache=True
            )

        try:
            # Try semantic kernel orchestration first
            orchestrator = app.state.orchestrator
            response = await orchestrator.process_message(message)
            if isinstance(response, dict) and response.get("error"):
                # If semantic kernel fails, use fallback
                print(f"Semantic kernel failed, using fallback for: {message}")
                response = fallback_function(
                    message,
                    "en",  # Assuming English for simplicity, adjust as needed
                    chat_id
                )
            responses.append(response)

        except Exception as e:
            logging.error(f"Error processing utterance: {e}")
            responses.append("I encountered an error processing part of your message.")

    except Exception as e:
        logging.error(f"Error in message processing: {e}")
        responses = ["I apologize, but I'm having trouble processing your request. Please try again."]

    finally:
        # Clean up PII cache if enabled
        if PII_ENABLED:
            pii_redacter.remove(id=chat_id)
    return responses


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Setup app
    try:
        logging.basicConfig(level=logging.WARNING)

        print("Setting up Azure credentials and client...")
        print(f"Using PROJECT_ENDPOINT: {PROJECT_ENDPOINT}")
        print(f"Using MODEL_NAME: {MODEL_NAME}")

        async with DefaultAzureCredential(exclude_interactive_browser_credential=False) as creds:
            async with AzureAIAgent.create_client(credential=creds, endpoint=PROJECT_ENDPOINT) as client:
                orchestrator = SemanticKernelOrchestrator(
                    client,
                    MODEL_NAME,
                    PROJECT_ENDPOINT,
                    AGENT_IDS,
                    fallback_function,
                    3
                )
                await orchestrator.create_agent_group_chat()

                # Store in app state
                app.state.creds = creds
                app.state.client = client
                app.state.orchestrator = orchestrator

                # Yield control back to FastAPI lifespan
                yield

    except Exception as e:
        logging.error(f"Error during setup: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")

# Create FastAPI app with lifespan
app = FastAPI(lifespan=lifespan)
app.mount("/assets", StaticFiles(directory=os.path.join(DIST_DIR, "assets")), name="assets")

# In order to test uvicorn app locally:
# 1) run `npm run build` in the frontend directory to generate the static files
# 2) move the `dist` directory to `src/backend/src/`
@app.get("/")
async def serve_frontend():
    return FileResponse(os.path.join(DIST_DIR, "index.html"))


# Define the chat endpoint
@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    try:
        # Grab the orchestrator from app state and orchestrate chat message
        orchestrator = app.state.orchestrator
        responses = await orchestrate_chat(request.message, orchestrator, chat_id=0)
        return JSONResponse(content={"messages": responses}, status_code=200)

    except Exception as e:
        logging.error(f"Error in chat endpoint: {e}")
        return JSONResponse(
            content={"error": "An unexpected error occurred"},
            status_code=500
        )


@app.post(
    "/sms",
    include_in_schema=True,
    summary="SMS-received webhook",
    tags=["SMS"]
)
async def sms_event_handler(
    events: List[Dict[str, Any]] = Body(
        ...,
        example=[
            {
                "eventType": "Microsoft.EventGrid.SubscriptionValidationEvent",
                "data": { "validationCode": "YOUR_VALIDATION_CODE" }
            },
            {
                "eventType": "Microsoft.Communication.SMSReceived",
                "data": {
                    "from": "+15551234567",
                    "to": "+15557654321",
                    "message": "hello!"
                }
            }
        ]
    )
):
    # 1) Handle the validation handshake
    first = events[0]
    if first.get("eventType") == "Microsoft.EventGrid.SubscriptionValidationEvent":
        return JSONResponse(
            status_code=200,
            content={ "validationResponse": first["data"]["validationCode"] }
        )

    # 2) Process real SMSReceived events
    for ev in events:
        if ev.get("eventType") == "Microsoft.Communication.SMSReceived":
            sms     = ev["data"]
            from_nr = sms["from"]
            text    = sms["message"]

            # get bot replies
            responses = await orchestrate_chat(text, app.state.orchestrator, chat_id=0)

            # send each response back as SMS
            for reply in responses:
                await sms_client.send(
                    from_=ACS_PHONE_NUMBER,
                    to=from_nr,
                    message=reply,
                    enable_delivery_report=True
                )

    # 3) Acknowledge delivery
    return JSONResponse(status_code=200, content={})