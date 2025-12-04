# Azure Adapter Implementation Guide

## Overview
This guide explains how to implement the fixes for critical issues found in the Azure adapter analysis.

## Critical Issues Fixed

### ✅ Issue #1: Group Name Normalization
**Problem**: Azure doesn't normalize group names like AWS does (spaces → dashes)

**Solution**: 
- Create `identity/utils.py` with `normalize_name()` function
- Modify `group_manager.py` to use normalized names
- Update `main.py` to normalize before creating/looking up groups

**Files to modify**:
- `identity/group_manager.py` - Add normalization to `create_group()` and `get_group_by_name()`
- `main.py` - Normalize group names in all methods

---

### ✅ Issue #2: ResourceType Not Used
**Problem**: Azure ignores `resourceType` parameter (AWS uses it for policies)

**Solution**:
- Create `identity/rbac_manager.py` for Azure RBAC role assignments
- Map resource types to Azure RBAC roles
- Assign roles to groups based on resourceType

**Files to create**:
- `identity/rbac_manager.py` - NEW FILE

**Files to modify**:
- `main.py` - Use `resourceType` in `CreateGroupWithLeaders()`

---

### ✅ Issue #3: Username Format Mismatch
**Problem**: Azure creates usernames as `{user}` but AWS uses `{user}-{group}`

**Solution**:
- Add `build_username_with_group_suffix()` to `identity/utils.py`
- Modify user creation to include group suffix
- Update both `CreateGroupWithLeaders()` and `CreateUsersForGroup()`

**Files to modify**:
- `identity/user_manager.py` - Add `create_user_with_group_suffix()` method
- `main.py` - Use group suffix in user creation

---

### ✅ Issue #4: Password Handling Inconsistency
**Problem**: Azure uses default password, AWS uses group name

**Solution**:
- Set password = normalized group name (like AWS)
- Pass password explicitly in user creation

**Files to modify**:
- `main.py` - Pass normalized group name as password

---

### ✅ Issue #5: Missing Methods
**Problem**: Backend expects `RemoveGroup()` and `CleanupGroupResources()` but Azure doesn't implement them

**Solution**:
- Implement `RemoveGroup()` - deletes group and all users
- Implement `CleanupGroupResources()` - finds and deletes Azure resources
- Complete `resource_finder.py` and `resource_deleter.py`

**Files to create/modify**:
- `protos/adapter_interface.proto` - Add RemoveGroup and CleanupGroup messages
- `clean_resources/resource_finder.py` - Complete implementation
- `clean_resources/resource_deleter.py` - Complete implementation
- `identity/group_manager.py` - Add `delete_group_and_users()` method
- `main.py` - Add `RemoveGroup()` and `CleanupGroupResources()` methods

---

### ✅ Issue #6: Logging vs Print
**Problem**: Azure uses `print()` instead of proper logging

**Solution**:
- Replace all `print()` with `logging` calls
- Configure logging at module level

**Files to modify**:
- `main.py` - Add logging configuration, replace print()
- `identity/group_manager.py` - Replace print() with logging
- `identity/user_manager.py` - Replace print() with logging

---

## Implementation Steps

### Step 1: Create Utility File
1. Create `identity/utils.py`
2. Copy `normalize_name()` and `build_username_with_group_suffix()` functions

### Step 2: Update Proto File
1. Open `protos/adapter_interface.proto`
2. Add `RemoveGroup` and `CleanupGroupResources` RPC definitions
3. Add message definitions for these RPCs
4. Regenerate Python files:
   ```bash
   python -m grpc_tools.protoc -I protos --python_out=protos --grpc_python_out=protos protos/adapter_interface.proto
   ```

### Step 3: Create RBAC Manager
1. Create `identity/rbac_manager.py`
2. Copy `AzureRBACManager` class
3. Update role IDs with your Azure subscription's actual role IDs

### Step 4: Update Group Manager
1. Modify `identity/group_manager.py`:
   - Add normalization to `create_group()`
   - Add normalization to `get_group_by_name()`
   - Add `delete_group_and_users()` method
   - Replace `print()` with `logging`

### Step 5: Update User Manager
1. Modify `identity/user_manager.py`:
   - Add `create_user_with_group_suffix()` method
   - Add `delete_user_by_username()` method
   - Remove debug `print()` statements

### Step 6: Complete Resource Finder
1. Replace `clean_resources/resource_finder.py` with complete implementation
2. Test resource finding by tags

### Step 7: Complete Resource Deleter
1. Replace `clean_resources/resource_deleter.py` with complete implementation
2. Test resource deletion

### Step 8: Update Main Adapter
1. Modify `main.py`:
   - Add imports for new utilities
   - Configure logging
   - Update `__init__` to include new managers
   - Fix `CreateGroupWithLeaders()` - use resourceType, normalization, group suffix
   - Fix `CreateUsersForGroup()` - use group suffix, proper password
   - Fix `GroupExists()` - use normalized names
   - Add `RemoveGroup()` method
   - Add `CleanupGroupResources()` method
   - Replace all `print()` with `logging`

### Step 9: Update Requirements
1. Add to `requirements.txt`:
   ```
   azure-mgmt-authorization
   azure-mgmt-storage
   ```

### Step 10: Testing
1. Test group creation with normalized names
2. Test user creation with group suffix
3. Test RBAC role assignment
4. Test group removal
5. Test resource cleanup

---

## Key Differences from AWS

| Feature | AWS | Azure (After Fix) |
|---------|-----|------------------|
| Group Name | Normalized (spaces→dashes) | Normalized (spaces→dashes) ✅ |
| Username Format | `{user}-{group}` | `{user}-{group}` ✅ |
| Password | Group name | Normalized group name ✅ |
| ResourceType Usage | IAM Policies | RBAC Roles ✅ |
| Group Removal | `RemoveGroup()` | `RemoveGroup()` ✅ |
| Resource Cleanup | `CleanupGroupResources()` | `CleanupGroupResources()` ✅ |

---

## Notes

1. **RBAC Role IDs**: You need to look up actual role definition IDs from your Azure subscription. The ones in `rbac_manager.py` are examples.

2. **Tagging**: Ensure Azure resources are tagged with `Group` tag for cleanup to work.

3. **Testing**: Test each fix individually before combining them.

4. **Backward Compatibility**: Existing groups created without normalization will need to be migrated or handled separately.

---

## Quick Reference

- **Normalization**: `identity/utils.py` → `normalize_name()`
- **Username Format**: `identity/utils.py` → `build_username_with_group_suffix()`
- **RBAC Roles**: `identity/rbac_manager.py` → `AzureRBACManager`
- **Resource Finding**: `clean_resources/resource_finder.py` → `ResourceFinder`
- **Resource Deletion**: `clean_resources/resource_deleter.py` → `ResourceDeleter`
- **Group Removal**: `identity/group_manager.py` → `delete_group_and_users()`

