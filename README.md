# uc-adapter-azure

Azure cloud adapter for UniCloud project.

## Docker Setup

### Build the Docker image

```bash
docker build -t uc-adapter-azure:latest .
```

### Run the container

```bash
docker run -d \
  --name azure-adapter \
  -p 50053:50053 \
  -e AZURE_TENANT_ID=your-tenant-id \
  -e AZURE_CLIENT_ID=your-client-id \
  -e AZURE_CLIENT_SECRET=your-client-secret \
  -e AZURE_SUBSCRIPTION_ID=your-subscription-id \
  -e AZURE_UDOMAIN=your-domain.onmicrosoft.com \
  uc-adapter-azure:latest
```

### Using docker-compose

Create a `docker-compose.yml`:

```yaml
version: '3.8'

services:
  azure-adapter:
    build: .
    ports:
      - "50053:50053"
    environment:
      - AZURE_TENANT_ID=${AZURE_TENANT_ID}
      - AZURE_CLIENT_ID=${AZURE_CLIENT_ID}
      - AZURE_CLIENT_SECRET=${AZURE_CLIENT_SECRET}
      - AZURE_SUBSCRIPTION_ID=${AZURE_SUBSCRIPTION_ID}
      - AZURE_UDOMAIN=${AZURE_UDOMAIN}
    restart: unless-stopped
```

Then run:
```bash
docker-compose up -d
```

## Environment Variables

Required environment variables:
- `AZURE_TENANT_ID` - Azure AD Tenant ID
- `AZURE_CLIENT_ID` - Azure AD Application (Client) ID
- `AZURE_CLIENT_SECRET` - Azure AD Application Secret
- `AZURE_SUBSCRIPTION_ID` - Azure Subscription ID
- `AZURE_UDOMAIN` - Azure AD Domain (e.g., `yourdomain.onmicrosoft.com`)

## Testing

The adapter exposes gRPC on port 50053. Test with:

```bash
python client_test.py
```

## Port

Default port: **50053**
