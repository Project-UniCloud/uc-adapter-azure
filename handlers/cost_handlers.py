"""
Cost monitoring handlers.
Handles all cost-related RPC methods using Azure Cost Management API.
"""

import logging
import re

import grpc

from cost_monitoring import limit_manager as cost_manager
from protos import adapter_interface_pb2 as pb2

logger = logging.getLogger(__name__)


class CostHandlers:
    """Handlers for cost-related RPC methods."""
    
    def __init__(self):
        pass
    
    def _safe_denormalize_group_name(self, normalized_name: str) -> str:
        """
        Safely denormalizes group name (dashes -> spaces) ONLY for standard format with semester.
        
        Backend expects format "AI 2024L" (with spaces) for GroupUniqueName.fromString().
        However, we must NOT denormalize names that legitimately contain dashes.
        
        Rules:
        1. Only denormalize if name matches standard format: "Name-YYYYZ/L" (with semester suffix)
        2. For names like "A-B" (without semester), return as-is to prevent corruption
        3. This is a best-effort approach - exact mapping would require additional tag storage
        
        Examples:
        - "AI-2024L" -> "AI 2024L" (safe: matches semester pattern)
        - "Test-Group-2024L" -> "Test Group 2024L" (safe: matches semester pattern)
        - "A-B" -> "A-B" (preserved: does NOT match semester pattern)
        - "My-Group" -> "My-Group" (preserved: does NOT match semester pattern)
        
        TODO: For exact mapping, use additional tag "UniCloudGroupName" when creating resources.
        """
        # Pattern: name ending with semester suffix (YYYYZ or YYYYL)
        semester_pattern = r'^(.+)-(\d{4}[ZL])$'
        match = re.match(semester_pattern, normalized_name)
        
        if match:
            # Matches standard format with semester - safe to denormalize
            name_part = match.group(1)
            semester = match.group(2)
            denormalized_name = name_part.replace('-', ' ') + ' ' + semester
            logger.debug(
                f"[_safe_denormalize_group_name] Denormalized '{normalized_name}' -> '{denormalized_name}' "
                "(matches semester pattern)"
            )
            return denormalized_name
        else:
            # Does NOT match standard format - preserve original to prevent corruption
            logger.warning(
                f"[_safe_denormalize_group_name] Preserving '{normalized_name}' as-is "
                "(does not match semester pattern - may legitimately contain dashes)"
            )
            return normalized_name
    
    def get_total_cost_for_group(self, request, context):
        """
        Returns total cost for a group for the specified period.
        Uses Azure Cost Management API.
        """
        try:
            cost = cost_manager.get_total_cost_for_group(
                group_tag_value=request.groupName,
                start_date=request.startDate,
                end_date=request.endDate or None
            )
            resp = pb2.CostResponse()
            resp.amount = cost
            return resp
        except Exception as e:
            logger.error(f"[GetTotalCostForGroup] Error: {e}", exc_info=True)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.CostResponse()
    
    def get_total_costs_for_all_groups(self, request, context):
        """
        Returns costs for all groups.
        Uses Azure Cost Management API.
        
        IMPORTANT: Backend expects format "AI 2024L" (with spaces) for GroupUniqueName.fromString().
        Azure Cost Management API returns group names from tags, which may be normalized (with dashes).
        
        We use SAFE denormalization that only works for standard format with semester suffix:
        - "AI-2024L" -> "AI 2024L" (safe: matches pattern with semester)
        - "A-B" -> "A-B" (preserved: does NOT match semester pattern, so we don't denormalize)
        
        This prevents corrupting group names that legitimately contain dashes.
        
        TODO: For exact mapping, consider using an additional tag (e.g., "UniCloudGroupName")
        to store the original group name when creating resources.
        """
        try:
            costs_dict = cost_manager.get_total_costs_for_all_groups(
                start_date=request.startDate,
                end_date=request.endDate or None
            )
            resp = pb2.AllGroupsCostResponse()
            
            # Map normalized names back to original format (with spaces) ONLY for standard format
            for normalized_group, cost in costs_dict.items():
                original_name = self._safe_denormalize_group_name(normalized_group)
                
                group_cost = resp.groupCosts.add()
                group_cost.groupName = original_name
                group_cost.amount = cost
            return resp
        except Exception as e:
            logger.error(f"[GetTotalCostsForAllGroups] Error: {e}", exc_info=True)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.AllGroupsCostResponse()
    
    def get_total_cost(self, request, context):
        """
        Returns total Azure subscription cost.
        Uses Azure Cost Management API.
        """
        try:
            cost = cost_manager.get_total_azure_cost(
                start_date=request.startDate,
                end_date=request.endDate or None
            )
            resp = pb2.CostResponse()
            resp.amount = cost
            return resp
        except Exception as e:
            logger.error(f"[GetTotalCost] Error: {e}", exc_info=True)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.CostResponse()
    
    def get_group_cost_with_service_breakdown(self, request, context):
        """
        Returns group cost with service breakdown.
        Uses Azure Cost Management API.
        """
        try:
            breakdown = cost_manager.get_group_cost_with_service_breakdown(
                group_tag_value=request.groupName,
                start_date=request.startDate,
                end_date=request.endDate or None
            )
            resp = pb2.GroupServiceBreakdownResponse()
            resp.total = breakdown['total']
            for service_name, amount in breakdown['by_service'].items():
                service_cost = resp.breakdown.add()
                service_cost.serviceName = service_name
                service_cost.amount = amount
            return resp
        except Exception as e:
            logger.error(f"[GetGroupCostWithServiceBreakdown] Error: {e}", exc_info=True)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.GroupServiceBreakdownResponse()
    
    def get_total_cost_with_service_breakdown(self, request, context):
        """
        Returns total Azure cost with service breakdown.
        Uses Azure Cost Management API.
        """
        try:
            result = cost_manager.get_total_cost_with_service_breakdown(
                start_date=request.startDate,
                end_date=request.endDate or None
            )
            resp = pb2.GroupServiceBreakdownResponse()
            resp.total = result['total']
            for service_name, amount in result['by_service'].items():
                entry = resp.breakdown.add()
                entry.serviceName = service_name
                entry.amount = amount
            return resp
        except Exception as e:
            logger.error(f"[GetTotalCostWithServiceBreakdown] Error: {e}", exc_info=True)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.GroupServiceBreakdownResponse()
    
    def get_group_costs_last_6_months_by_service(self, request, context):
        """
        Returns group costs for last 6 months grouped by service.
        Uses Azure Cost Management API.
        """
        group_name = (request.groupName or '').strip()
        if not group_name:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("Pole groupName nie może być puste.")
            return pb2.GroupCostMapResponse()
        
        try:
            costs = cost_manager.get_group_cost_last_6_months_by_service(group_tag_value=group_name)
            resp = pb2.GroupCostMapResponse()
            for k, v in costs.items():
                resp.costs[k] = v
            return resp
        except Exception as e:
            logger.error(f"[GetGroupCostsLast6MonthsByService] Error: {e}", exc_info=True)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.GroupCostMapResponse()
    
    def get_group_monthly_costs_last_6_months(self, request, context):
        """
        Returns monthly costs for last 6 months for a group.
        Uses Azure Cost Management API.
        """
        group_name = (request.groupName or '').strip()
        if not group_name:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("Pole groupName nie może być puste.")
            return pb2.GroupMonthlyCostsResponse()
        
        try:
            costs = cost_manager.get_group_monthly_costs_last_6_months(group_tag_value=group_name)
            resp = pb2.GroupMonthlyCostsResponse()
            for month, amount in costs.items():
                resp.monthCosts[month] = amount
            return resp
        except Exception as e:
            logger.error(f"[GetGroupMonthlyCostsLast6Months] Error: {e}", exc_info=True)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.GroupMonthlyCostsResponse()

