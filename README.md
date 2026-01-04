# Azure Cloud Adapter

## Introduction

The Azure Cloud Adapter is a gRPC service that provides a unified interface for managing Azure resources, identities, and cost monitoring operations. It acts as an integration layer between the UniCloud backend system and Microsoft Azure cloud services, specifically Microsoft Entra ID (formerly Azure Active Directory) and Azure Resource Manager.

The adapter implements the Adapter pattern, translating domain-specific operations from the backend into Azure-specific API calls while maintaining a consistent interface compatible with other cloud provider adapters in the system.

## Purpose and Scope

### Primary Objectives

The adapter addresses the following engineering problems:

1. **Identity Management Abstraction**: Provides a unified interface for user and group management operations in Microsoft Entra ID, abstracting away Graph API complexity and handling eventual consistency challenges inherent in distributed identity systems.

2. **RBAC Policy Mapping**: Maps abstract resource type permissions (e.g., "vm", "storage", "network") to concrete Azure RBAC role assignments at the subscription level, ensuring proper access control for group-based resource management.

3. **Cost Monitoring Integration**: Enables programmatic querying of Azure cost data through the Cost Management API, supporting group-based cost allocation using resource tagging strategies.

4. **Resource Lifecycle Management**: Implements resource discovery and cleanup mechanisms using Azure resource tags, providing deterministic resource grouping and teardown capabilities.

### Scope of Responsibility

**In scope:**
- Microsoft Entra ID group and user lifecycle management
- Azure RBAC role assignment at subscription scope
- Azure Cost Management API queries (cost aggregation, service breakdown)
- Resource discovery and deletion based on tags
- Name normalization for cross-adapter compatibility
- Idempotent operations with retry mechanisms for eventual consistency

**Out of scope:**
- Resource creation (delegated to end users with assigned RBAC roles)
- Network configuration and security rules
- Resource tagging enforcement (tagging is performed by users)
- Multi-subscription or multi-tenant scenarios
- Authentication token management beyond initial credential setup

## Architecture

### Component Structure

The adapter follows a layered architecture with clear separation of concerns:

```
┌─────────────────────────────────────────────────┐
│          gRPC Service Layer                     │
│    (CloudAdapterServicer - main.py)             │
└──────────────┬──────────────────────────────────┘
               │
       ┌───────┴───────┬──────────────┐
       │               │              │
┌──────▼──────┐ ┌──────▼──────┐ ┌─────▼──────┐
│  Identity   │ │    Cost     │ │  Resource  │
│  Handlers   │ │  Handlers   │ │  Handlers  │
└──────┬──────┘ └──────┬──────┘ └─────┬──────┘
       │               │              │
┌──────▼───────────────▼──────────────▼──────┐
│         Domain Managers                     │
│  - AzureUserManager                         │
│  - AzureGroupManager                        │
│  - AzureRBACManager                         │
│  - ResourceFinder                           │
│  - ResourceDeleter                          │
│  - LimitManager (cost queries)              │
└──────┬──────────────────────────────────────┘
       │
┌──────▼──────────────────────────────────────┐
│      Azure SDK Client Factory               │
│      (azure_clients.py)                     │
│  - GraphClient (Entra ID)                   │
│  - ResourceManagementClient                 │
│  - AuthorizationManagementClient (RBAC)     │
│  - CostManagementClient                     │
│  - ComputeManagementClient                  │
└──────┬──────────────────────────────────────┘
       │
┌──────▼──────────────────────────────────────┐
│      Microsoft Azure Services               │
│  - Microsoft Entra ID (Graph API)           │
│  - Azure Resource Manager                   │
│  - Azure Cost Management API                │
└─────────────────────────────────────────────┘
```

### Data Flow

**Identity Management Flow:**
1. Backend sends gRPC request (e.g., `CreateGroupWithLeaders`)
2. Handler validates input and normalizes group name
3. Domain manager (e.g., `AzureGroupManager`) calls Graph API
4. RBAC manager assigns roles at subscription scope
5. Response returned via gRPC

**Cost Query Flow:**
1. Backend sends cost query request with date range and optional group filter
2. Cost handler formats query using Azure Cost Management API models
3. Query executed at subscription scope with tag-based filtering
4. Results aggregated and normalized for backend consumption
5. Response returned via gRPC

**Resource Cleanup Flow:**
1. Backend sends `CleanupGroupResources` request
2. Resource finder queries all resources by Group tag
3. Resource deleter invokes appropriate Azure SDK client based on resource type
4. Fallback to Resource Group deletion if no tagged resources found
5. Response contains deletion summary

### External Service Integration

- **Microsoft Graph API** (`msgraph-core`): Entra ID identity operations (users, groups, membership)
- **Azure Resource Manager** (`azure-mgmt-resource`): Resource discovery, Resource Group management
- **Azure Authorization** (`azure-mgmt-authorization`): RBAC role assignment and enumeration
- **Azure Cost Management** (`azure-mgmt-costmanagement`): Cost queries and aggregation
- **Azure Compute/Network/Storage** (`azure-mgmt-*`): Resource type-specific deletion operations

## Design Assumptions

### Security Assumptions

1. **Service Principal Authentication**: The adapter uses Azure Service Principal credentials (Client ID + Secret) for all operations. The principal must have sufficient permissions in the target subscription and Entra ID tenant.

2. **HTTPS Enforcement**: All Azure API endpoints use HTTPS. The adapter validates URL schemes and scope formats to prevent insecure connections.

3. **Scope Limitation**: RBAC assignments are performed at subscription scope only. Resource group or resource-level assignments are not supported.

4. **Credential Storage**: Credentials are provided via environment variables at runtime. The adapter does not manage credential rotation or storage.

### Runtime Environment Assumptions

1. **Single Subscription**: The adapter operates within a single Azure subscription, identified by `AZURE_SUBSCRIPTION_ID`.

2. **Single Tenant**: All operations target a single Entra ID tenant, identified by `AZURE_TENANT_ID`.

3. **Eventual Consistency**: The adapter implements retry mechanisms with exponential backoff to handle Azure AD replication delays and transient API failures.

4. **Container Deployment**: The adapter is designed for containerized deployment (Docker) with environment-based configuration.

### Adapter Pattern Rationale

The adapter pattern is used to:

1. **Abstract Provider Differences**: Provides a consistent interface regardless of the underlying cloud provider (Azure, AWS, GCP), enabling backend code to remain provider-agnostic.

2. **Encapsulate Provider-Specific Logic**: Hides Azure-specific concepts (e.g., Entra ID, RBAC roles, Cost Management API) behind domain-agnostic operations.

3. **Enable Multi-Provider Support**: Allows the system to support multiple cloud providers simultaneously without modifying backend code.

4. **Facilitate Testing**: Enables mocking of cloud provider APIs for unit and integration testing of backend components.

## Technologies and Dependencies

### Language and Runtime

- **Python 3.11+**: Required for type hints, modern async features, and library compatibility.

### Key Libraries

- **gRPC** (`grpcio>=1.76.0`): RPC framework for service communication
- **Protocol Buffers** (`protobuf>=6.31.1`): Serialization format for gRPC messages
- **Azure SDK for Python**: 
  - `azure-identity`: Authentication (ClientSecretCredential)
  - `azure-mgmt-resource`: Resource Manager operations
  - `azure-mgmt-authorization`: RBAC role management
  - `azure-mgmt-costmanagement`: Cost queries
  - `azure-mgmt-compute`, `azure-mgmt-network`, `azure-mgmt-storage`: Resource type-specific operations
- **Microsoft Graph SDK** (`msgraph-core==0.2.2`): Entra ID operations via Graph API
- **python-dotenv**: Environment variable loading for local development

## Configuration

### Environment Variables

All configuration is provided via environment variables at runtime:

| Variable | Description | Example |
|----------|-------------|---------|
| `AZURE_TENANT_ID` | Azure AD Tenant ID (GUID) | `12345678-1234-1234-1234-123456789012` |
| `AZURE_CLIENT_ID` | Azure AD Application (Service Principal) Client ID | `87654321-4321-4321-4321-210987654321` |
| `AZURE_CLIENT_SECRET` | Azure AD Application Secret | `secret-value` |
| `AZURE_SUBSCRIPTION_ID` | Azure Subscription ID (GUID) | `11111111-2222-3333-4444-555555555555` |
| `AZURE_UDOMAIN` | Entra ID domain for user UPN construction | `yourdomain.onmicrosoft.com` |

### Configuration Validation

The adapter validates all required environment variables at startup via `config.settings.validate_config()`. Missing or empty variables result in a runtime error, preventing the service from starting with incomplete configuration.

### Client Initialization

Azure SDK clients are initialized using the factory pattern in `azure_clients.py`, with singleton instances cached using `@lru_cache`. All clients share a single `ClientSecretCredential` instance, ensuring efficient credential reuse.

## Integration and Usage

### Service Interface

The adapter exposes a gRPC service (`CloudAdapter`) on port **50053** (insecure channel). The service interface is defined in `protos/adapter_interface.proto` and includes methods for:

- **Identity Operations**: `GetStatus`, `GroupExists`, `CreateGroupWithLeaders`, `CreateUsersForGroup`, `RemoveGroup`, `AssignPolicies`, `UpdateGroupLeaders`
- **Cost Queries**: `GetTotalCostForGroup`, `GetTotalCostsForAllGroups`, `GetTotalCost`, `GetGroupCostWithServiceBreakdown`, `GetTotalCostWithServiceBreakdown`, `GetGroupCostsLast6MonthsByService`, `GetGroupMonthlyCostsLast6Months`
- **Resource Management**: `GetAvailableServices`, `GetResourceCount`, `CleanupGroupResources`

### Integration Pattern

The backend system connects to the adapter via gRPC and invokes methods as needed. The adapter operates as a stateless service, with each request containing all necessary context. State is maintained in Azure services (Entra ID, Resource Manager), not within the adapter.

### Deployment

The adapter is deployed as a Docker container. The container image is built from the provided `Dockerfile` and configured via environment variables. For local development, `docker-compose.yml` provides a convenient setup. Production deployment uses the main `uc-docker` orchestration.

## Limitations

### Current Implementation Limitations

1. **Subscription-Scope RBAC Only**: Role assignments are performed only at subscription scope. Resource group or resource-level assignments are not supported.

2. **Single Resource Type per Group**: While `AssignPolicies` supports multiple resource types, the initial group creation (`CreateGroupWithLeaders`) assigns only the first resource type from the request.

3. **Tag-Based Resource Discovery**: Resource cleanup relies on the "Group" tag being present on resources. Resources created without proper tagging may not be discoverable for cleanup.

4. **Cost Query Latency**: Azure Cost Management API data may have up to 48-hour latency. Real-time cost queries are not supported.

5. **User Deletion Strategy**: User deletion during group teardown requires UPN-based fallback search when group membership enumeration fails due to replication delays.

6. **Name Normalization**: Group names are normalized (spaces → dashes) for compatibility, which may cause collisions if names differ only by whitespace.

### Design Trade-offs

1. **Eventual Consistency Handling**: The adapter uses polling and retries rather than webhooks, trading latency for implementation simplicity.

2. **Client Caching**: Azure SDK clients are cached as singletons, reducing initialization overhead but preventing per-request credential rotation.

3. **Synchronous Operations**: All operations are synchronous, blocking the gRPC thread. Async operations would improve throughput but add complexity.

## Future Development Directions

### Potential Extensions

1. **Resource Group Scope Support**: Extend RBAC assignment to support resource group and resource-level scopes in addition to subscription scope.

2. **Async gRPC Operations**: Refactor handlers to use async/await patterns for improved concurrency and throughput.

3. **Webhook-Based Consistency**: Implement webhook listeners for Azure AD change notifications to reduce polling delays.

4. **Multi-Subscription Support**: Extend the adapter to operate across multiple subscriptions within a single tenant.

5. **Resource Tagging Enforcement**: Add proactive tagging mechanisms to ensure resources are tagged at creation time.

6. **Cost Budget Alerts**: Integrate Azure Budget API to provide proactive cost threshold alerts.

7. **Audit Logging**: Enhanced logging and audit trail generation for compliance and debugging.

### Non-Goals

- Support for multiple Azure tenants (cross-tenant scenarios)
- Direct resource creation (remains user responsibility)
- Real-time cost monitoring (latency is inherent to Cost Management API)
- Custom RBAC role definition creation (uses built-in Azure roles only)

## Academic Context

This adapter is developed as part of an engineering thesis project. It serves as a demonstration of:

- Integration pattern implementation in distributed systems
- Cloud provider API abstraction techniques
- Handling of eventual consistency in cloud identity systems
- Cost monitoring integration in multi-tenant cloud environments

The adapter is evaluated based on correctness of implementation, architectural decisions, error handling, and integration with the broader system architecture.
