# uc-adapter-azure

Azure cloud adapter for UniCloud project. Provides gRPC interface for managing Azure resources, identities, and cost monitoring.

## Features

- **Identity Management**: Create and manage Azure AD groups and users
- **RBAC Management**: Assign Azure RBAC roles to groups based on resource types
- **Cost Monitoring**: Query Azure costs by group, service, and time period
- **Resource Management**: Find, count, and cleanup Azure resources by tags
- **gRPC Interface**: Standardized gRPC API compatible with UniCloud backend

## Architecture

The adapter is organized into modular handlers:

- `handlers/identity_handlers.py` - Identity and RBAC operations
- `handlers/cost_handlers.py` - Cost monitoring and queries
- `handlers/resource_handlers.py` - Resource discovery and cleanup
- `identity/` - Azure AD user and group management
- `clean_resources/` - Resource finding and deletion
- `cost_monitoring/` - Cost limit management
- `config/settings.py` - Configuration (reads from environment variables)

## Prerequisites

- Python 3.11+
- Azure AD Application with required permissions
- Azure Subscription
- Docker (for containerized deployment)

## Configuration

### Environment Variables

All configuration is done through environment variables.

Required environment variables:
- `AZURE_TENANT_ID` - Azure AD Tenant ID
- `AZURE_CLIENT_ID` - Azure AD Application (Client) ID
- `AZURE_CLIENT_SECRET` - Azure AD Application Secret
- `AZURE_SUBSCRIPTION_ID` - Azure Subscription ID
- `AZURE_UDOMAIN` - Azure AD Domain (e.g., `yourdomain.onmicrosoft.com`)

## Installation

### Local Setup

1. Create a virtual environment:
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Generate protobuf files (if needed):
```bash
# On Linux/Mac:
./generate_proto.sh

# On Windows:
generate_proto.bat
```

4. Set environment variables (see Configuration section)

5. Run the adapter:
```bash
python main.py
```

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

The project includes a `docker-compose.yml` for local testing:

```bash
docker-compose up -d
```

For production deployment, use the main `uc-docker/docker-compose.yml` which includes the Azure adapter service.

## Testing

The adapter exposes gRPC on port **50053**. Test scripts are located in the `tests/` directory:

```bash
# Basic connectivity test
python tests/client_test.py

# Backend compatibility test
python tests/test_backend_connection.py

# Status check
python tests/test_get_status.py

# Cost monitoring tests
python tests/test_get_total_costs_for_all_groups.py

# Required methods verification
python tests/test_required_methods.py

# Smoke tests
python tests/smoke_test.py
python tests/limit_smoke_test.py
```

## Protobuf

The adapter uses Protocol Buffers for gRPC communication. The proto definition is in `protos/adapter_interface.proto`.

To regenerate Python files from the proto definition:

```bash
# Linux/Mac
./generate_proto.sh

# Windows
generate_proto.bat
```

**Note**: The generated files (`adapter_interface_pb2.py` and `adapter_interface_pb2_grpc.py`) are already included in the repository.

## gRPC API

The adapter implements the `CloudAdapter` service with the following RPC methods:

### Identity Management
- `GetStatus` - Health check
- `GroupExists` - Check if group exists
- `CreateGroupWithLeaders` - Create group with leaders and assign RBAC roles
- `CreateUsersForGroup` - Create users and add them to a group
- `RemoveGroup` - Remove group and all its members
- `AssignPolicies` - Assign RBAC policies to group or user

### Cost Monitoring
- `GetTotalCostForGroup` - Get total cost for a group
- `GetTotalCostsForAllGroups` - Get costs for all groups
- `GetTotalCost` - Get total Azure subscription cost
- `GetGroupCostWithServiceBreakdown` - Get group cost with service breakdown
- `GetTotalCostWithServiceBreakdown` - Get total cost with service breakdown
- `GetGroupCostsLast6MonthsByService` - Get group costs for last 6 months by service
- `GetGroupMonthlyCostsLast6Months` - Get monthly costs for last 6 months

### Resource Management
- `GetAvailableServices` - Get list of available resource types
- `GetResourceCount` - Get count of resources for a group
- `CleanupGroupResources` - Remove all resources associated with a group

## Port

Default gRPC port: **50053**

## Security Notes

- **Never commit credentials** to the repository
- All configuration values are read from environment variables
- The `.env` file is in `.gitignore`
- Docker containers should receive credentials via environment variables or secrets management

## License

See [LICENSE] file for details.
