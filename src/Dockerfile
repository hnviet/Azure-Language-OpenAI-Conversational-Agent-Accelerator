# → first stage
FROM mcr.microsoft.com/cbl-mariner/base/nodejs:18 AS build-ui
WORKDIR /app

# before (wrong):
# COPY src/frontend/package.json src/frontend/vite.config.js src/frontend/index.html ./

# after (correct):
COPY frontend/package.json frontend/vite.config.js frontend/index.html ./
COPY frontend/src/ /app/src

RUN npm install
RUN npm run build

# → final stage
FROM python:3.11-slim AS runtime

# install azure-cli so that `az` is available at runtime
RUN apt-get update \
 && apt-get install -y curl apt-transport-https lsb-release gnupg \
 && curl -sL https://aka.ms/InstallAzureCLIDeb | bash

WORKDIR /app

# bring in the built UI
COPY --from=build-ui /app/dist /app/dist

# bring in your backend
COPY backend/src/ /app
COPY backend/requirements.txt /app

RUN pip install -r requirements.txt
EXPOSE 7000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7000"]
