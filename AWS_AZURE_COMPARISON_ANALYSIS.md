# AWS vs Azure Adapter - Implementation Gap Analysis

## Executive Summary

This document compares the AWS adapter implementation with the Azure adapter to identify missing features, implementation differences, and required changes for Azure to achieve feature parity.

---

## 1. RPC Methods Comparison

### ✅ Implemented in Both
- `GetStatus` - Health check
- `GroupExists` - Check if group exists
- `CreateGroupWithLeaders` - Create group with leaders
- `CreateUsersForGroup` - Add users to existing group
- `GetTotalCostForGroup` - Get cost for specific group
- `GetTotalCostsForAllGroups` - Get costs for all groups
- `GetTotalCost` - Get total subscription/account cost
- `GetGroupCostWithServiceBreakdown` - Get cost breakdown by service
- `RemoveGroup` - Remove group and its users
- `CleanupGroupResources` - Clean up resources tagged with group

### ❌ Missing in Azure (Present in AWS)
1. **`GetAvailableServices`**
   - **Purpose**: Returns list of available services based on policy files
   - **AWS Implementation**: Uses `PolicyManager.get_available_services()` to scan policy files
   - **Azure Equivalent**: Should return available resource types (e.g., "vm", "storage", "database")
   - **Priority**: Medium (useful for frontend to show available options)

2. **`GetResourceCount`**
   - **Purpose**: Returns count of resources with tag `Group=<groupName>` for specific resource type
   - **AWS Implementation**: Uses `find_resources_by_group()` and filters by service type
   - **Azure Equivalent**: Should use `ResourceFinder` to count resources by type
   - **Priority**: Medium (useful for monitoring resource usage)

3. **`GetTotalCostWithServiceBreakdown`**
   - **Purpose**: Get total cost with service breakdown (not group-specific)
   - **AWS Implementation**: Uses `limits_manager.get_total_cost_with_service_breakdown()`
   - **Azure Status**: Method exists but returns stub (0.0)
   - **Priority**: High (needs actual Azure Cost Management integration)

4. **`GetGroupCostsLast6MonthsByService`**
   - **Purpose**: Get group costs for last 6 months grouped by service
   - **AWS Implementation**: Uses `limits_manager.get_group_cost_last_6_months_by_service()`
   - **Azure Status**: Not implemented
   - **Priority**: Medium (nice-to-have for historical analysis)

5. **`GetGroupMonthlyCostsLast6Months`**
   - **Purpose**: Get monthly costs for last 6 months (time series)
   - **AWS Implementation**: Uses `limits_manager.get_group_monthly_costs_last_6_months()`
   - **Azure Status**: Not implemented
   - **Priority**: Medium (nice-to-have for trend analysis)

---

## 2. Proto File Differences

### Current State
- **AWS Proto**: Only has 8 RPCs defined (missing RemoveGroup, CleanupGroupResources, and the 5 additional methods)
- **Azure Proto**: Has 10 RPCs (includes RemoveGroup and CleanupGroupResources)

### Required Proto Updates
Azure proto needs to add:
1. `GetAvailableServices` RPC and `GetAvailableServicesResponse` message
2. `GetResourceCount` RPC with `ResourceCountRequest` and `ResourceCountResponse` messages
3. `GetTotalCostWithServiceBreakdown` RPC (already exists, but verify message format)
4. `GetGroupCostsLast6MonthsByService` RPC with `GroupCostMapRequest` and `GroupCostMapResponse` messages
5. `GetGroupMonthlyCostsLast6Months` RPC with `GroupMonthlyCostsRequest` and `GroupMonthlyCostsResponse` messages

### Request Format Differences

#### CreateGroupWithLeaders
- **AWS**: Uses `request.resourceTypes` (plural, repeated string) - supports multiple resource types
- **Azure**: Uses `request.resourceType` (singular, string) - only one resource type
- **Issue**: AWS proto shows `resourceType` (singular) but code uses `resourceTypes` (plural)
- **Action Required**: Verify which format backend expects, then align both adapters

---

## 3. Cost Monitoring Implementation

### AWS Implementation (Fully Functional)
- ✅ Uses AWS Cost Explorer API (`boto3.client('ce')`)
- ✅ Filters by tag `Group=<groupName>`
- ✅ Supports service breakdown
- ✅ Supports historical data (6 months)
- ✅ Supports monthly granularity
- ✅ Handles date ranges properly

### Azure Implementation (Stubs Only)
- ❌ All cost methods return 0.0 or empty responses
- ❌ No Azure Cost Management API integration
- ❌ No tag-based filtering
- ❌ No service breakdown
- ❌ No historical data support

### Required Implementation
1. **Azure Cost Management API Integration**
   - Use `azure-mgmt-costmanagement` SDK
   - Query costs using Query API
   - Filter by tags (requires proper tagging setup)

2. **Tag-Based Cost Filtering**
   - Resources must be tagged with group name
   - Use tag filters in cost queries
   - Map Azure service names to short names (like AWS does)

3. **Service Breakdown**
   - Group costs by Azure service (e.g., "Virtual Machines", "Storage Accounts")
   - Map to short names: "vm", "storage", "database", etc.

4. **Historical Data**
   - Implement 6-month lookback
   - Monthly granularity
   - Proper date range handling

---

## 4. Policy/RBAC Management

### AWS Implementation
- ✅ **PolicyManager**: Scans policy files in `config/policies/`
- ✅ **Policy Files**: JSON IAM policies for each service (leader/student variants)
- ✅ **Policy Assignment**: Attaches policies to IAM groups during group creation
- ✅ **GetAvailableServices**: Returns services that have both leader and student policies

### Azure Implementation
- ✅ **RBAC Manager**: Exists but uses hardcoded role IDs
- ⚠️ **Role Mapping**: Limited to "vm" resource type
- ❌ **No Policy Manager Equivalent**: No file-based policy system
- ❌ **No GetAvailableServices**: Can't dynamically discover available services

### Required Implementation
1. **Service Discovery**
   - Create Azure equivalent of PolicyManager
   - Map resource types to Azure RBAC roles
   - Return available resource types based on configured roles

2. **Role Configuration**
   - Move from hardcoded role IDs to configurable mapping
   - Support multiple resource types (vm, storage, database, etc.)
   - Store role mappings in config file or environment variables

---

## 5. Resource Management

### AWS Implementation
- ✅ **Resource Finding**: Uses AWS Resource Groups Tagging API
- ✅ **Resource Deletion**: Handles EC2, S3, IAM users
- ✅ **Tag-Based Search**: Filters by `Group` tag
- ✅ **Service Type Detection**: Extracts service from ARN

### Azure Implementation
- ✅ **ResourceFinder**: Exists but basic implementation
- ✅ **ResourceDeleter**: Exists with support for VMs, NICs, IPs, VNets, NSGs, Storage
- ⚠️ **Tag Filtering**: Uses OData filter (may need optimization)
- ⚠️ **Resource Type Detection**: Basic implementation

### Improvements Needed
1. **Resource Finding Optimization**
   - Consider Azure Resource Graph for better performance
   - Support more resource types
   - Better error handling

2. **Resource Deletion**
   - Add support for more Azure resource types
   - Handle dependencies (e.g., delete VMs before NICs)
   - Better error recovery

---

## 6. Request/Response Format Issues

### Group Name Format
- **Backend Expects**: `"AI 2024L"` (with space, format: "Name YYYYZ/L")
- **Azure Returns**: `"AI-2024L"` (normalized, spaces → dashes)
- **Issue**: Backend calls `GroupUniqueName.fromString(response.getGroupName())` which expects exact format
- **Impact**: Backend may fail to parse group names from Azure responses
- **Action Required**: 
  - Option 1: Return original group name (with spaces) in responses
  - Option 2: Update backend to handle normalized names
  - Option 3: Store both normalized (for Azure) and original (for backend) names

### RemoveGroup Response
- **AWS**: Returns `RemoveGroupResponse` with `success`, `removedUsers`, `message`
- **Azure**: Returns `RemoveGroupResponse` with only `message`
- **Issue**: Proto file shows only `message` field, but AWS code expects `success` and `removedUsers`
- **Action Required**: Update proto file to include `success` (bool) and `removedUsers` (repeated string)

### CleanupGroupResources Response
- **AWS**: Returns `CleanupGroupResponse` with `success`, `deletedResources`, `message`
- **Azure**: Returns `CleanupGroupResponse` with only `message`
- **Issue**: Proto file shows only `message` field, but AWS code expects `success` and `deletedResources`
- **Action Required**: Update proto file to include `success` (bool) and `deletedResources` (repeated string)

---

## 7. Cost Monitoring Module Structure

### AWS Structure
```
cost_monitoring/
  └── limit_manager.py
      ├── get_total_cost_for_group()
      ├── get_group_cost_with_service_breakdown()
      ├── get_total_costs_for_all_groups()
      ├── get_total_aws_cost()
      ├── get_total_cost_with_service_breakdown()
      ├── get_group_cost_last_6_months_by_service()
      └── get_group_monthly_costs_last_6_months()
```

### Azure Structure
```
cost_monitoring/
  └── limit_manager.py
      └── (Only has LimitManager class for user/VM counting)
      └── (No cost-related functions)
```

### Required Implementation
Create cost-related functions in Azure `limit_manager.py`:
1. `get_total_cost_for_group()` - Azure Cost Management API
2. `get_group_cost_with_service_breakdown()` - With service grouping
3. `get_total_costs_for_all_groups()` - Tag-based grouping
4. `get_total_azure_cost()` - Total subscription cost
5. `get_total_cost_with_service_breakdown()` - Total with breakdown
6. `get_group_cost_last_6_months_by_service()` - Historical by service
7. `get_group_monthly_costs_last_6_months()` - Monthly time series

---

## 8. Configuration and Policy Management

### AWS
- ✅ Policy files in `config/policies/`
- ✅ PolicyManager scans and validates policies
- ✅ Dynamic service discovery

### Azure
- ❌ No equivalent policy file system
- ❌ Hardcoded RBAC role IDs
- ❌ No service discovery mechanism

### Required Implementation
1. **Create Policy/Role Configuration System**
   - Config file: `config/azure_roles.json` or similar
   - Map resource types to Azure RBAC role IDs
   - Support for leader vs student roles

2. **Create PolicyManager Equivalent**
   - `config/policy_manager.py` or `identity/policy_manager.py`
   - Scan available roles from config
   - Return available resource types

---

## 9. Additional Features in AWS

### Auto-Tagging
- AWS has `config/automation/auto-tagging/` with Lambda function
- Automatically tags resources with Group name
- **Azure Equivalent**: Could use Azure Policy or Automation Account

### Resource Cleanup
- AWS uses Resource Groups Tagging API for efficient resource finding
- **Azure Equivalent**: Should use Azure Resource Graph for better performance

---

## 10. Priority Implementation Order

### High Priority (Critical for Backend Compatibility)
1. ✅ Fix `RemoveGroup` and `CleanupGroupResources` response format (add `success` and list fields)
2. ✅ Fix group name format issue (return original format or handle normalization)
3. ⚠️ Implement actual cost monitoring (replace stubs with Azure Cost Management API)
4. ⚠️ Verify `CreateGroupWithLeaders` request format (`resourceType` vs `resourceTypes`)

### Medium Priority (Feature Parity)
5. Implement `GetAvailableServices` RPC
6. Implement `GetResourceCount` RPC
7. Implement `GetTotalCostWithServiceBreakdown` (actual implementation)
8. Create PolicyManager equivalent for Azure
9. Improve ResourceFinder/ResourceDeleter

### Low Priority (Nice-to-Have)
10. Implement `GetGroupCostsLast6MonthsByService`
11. Implement `GetGroupMonthlyCostsLast6Months`
12. Add auto-tagging support
13. Optimize resource finding with Azure Resource Graph

---

## 11. Summary of Missing Components

### RPC Methods (5 missing)
1. `GetAvailableServices`
2. `GetResourceCount`
3. `GetTotalCostWithServiceBreakdown` (stub exists, needs implementation)
4. `GetGroupCostsLast6MonthsByService`
5. `GetGroupMonthlyCostsLast6Months`

### Cost Monitoring Functions (7 missing)
1. `get_total_cost_for_group()` - Azure Cost Management integration
2. `get_group_cost_with_service_breakdown()` - With service breakdown
3. `get_total_costs_for_all_groups()` - Tag-based grouping
4. `get_total_azure_cost()` - Total subscription cost
5. `get_total_cost_with_service_breakdown()` - Total with breakdown
6. `get_group_cost_last_6_months_by_service()` - Historical by service
7. `get_group_monthly_costs_last_6_months()` - Monthly time series

### Configuration/Management (2 missing)
1. PolicyManager equivalent (service discovery)
2. Configurable RBAC role mapping

### Proto File Updates (5 messages needed)
1. `GetAvailableServicesResponse`
2. `ResourceCountRequest` / `ResourceCountResponse`
3. `GroupCostMapRequest` / `GroupCostMapResponse`
4. `GroupMonthlyCostsRequest` / `GroupMonthlyCostsResponse`
5. Update `RemoveGroupResponse` and `CleanupGroupResponse` to include `success` and list fields

---

## 12. Notes

- AWS adapter uses `resourceTypes` (plural) in code but proto shows `resourceType` (singular) - verify which is correct
- Azure normalizes group names but backend expects original format - needs resolution
- AWS has extensive cost monitoring, Azure has only stubs
- AWS uses file-based policies, Azure uses RBAC roles (different approach, both valid)
- Both adapters have resource cleanup, but Azure needs optimization

