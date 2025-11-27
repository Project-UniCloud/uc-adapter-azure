# main.py

from concurrent import futures
from typing import List

import grpc

from config.settings import validate_config
from identity.user_manager import AzureUserManager
from identity.group_manager import AzureGroupManager
from protos import adapter_interface_pb2 as pb2
from protos import adapter_interface_pb2_grpc as pb2_grpc


class CloudAdapterServicer(pb2_grpc.CloudAdapterServicer):
    def __init__(self) -> None:
        self.user_manager = AzureUserManager()
        self.group_manager = AzureGroupManager()
        # docelowo tutaj dodajemy LimitManager od kosztów

    # ========== GetStatus ==========

    def GetStatus(self, request, context):
        resp = pb2.StatusResponse()
        resp.isHealthy = True
        return resp

    # ========== GroupExists ==========

    def GroupExists(self, request, context):
        """
        Sprawdza, czy grupa o podanej nazwie istnieje w Entra ID.
        """
        group_name: str = request.groupName

        try:
            group = self.group_manager.get_group_by_name(group_name)
            resp = pb2.GroupExistsResponse()
            resp.exists = group is not None
            return resp
        except Exception as e:
            print(f"[GroupExists] Error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.GroupExistsResponse()

    # ========== CreateUsersForGroup ==========

    def CreateUsersForGroup(self, request, context):
        """
        Tworzy użytkowników i dodaje ich do istniejącej grupy.

        request:
          - groupName: nazwa grupy w Entra ID
          - users: repeated string (loginy użytkowników)
        """
        group_name: str = request.groupName
        users: List[str] = list(request.users)

        try:
            group = self.group_manager.get_group_by_name(group_name)
            if not group:
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details(
                    f"Group '{group_name}' does not exist in Azure AD"
                )
                return pb2.CreateUsersForGroupResponse()

            group_id = group["id"]
            created: List[tuple[str, str]] = []

            for login in users:
                # Tworzymy użytkownika z domyślnym hasłem z AzureUserManager
                try:
                    user_id = self.user_manager.create_user(
                        login=login,
                        display_name=login,
                    )
                except Exception as e:
                    # rollback utworzonych do tej pory użytkowników
                    for created_login, _uid in created:
                        try:
                            self.user_manager.delete_user(created_login)
                        except Exception:
                            print(
                                f"[CreateUsersForGroup] rollback delete_user({created_login}) failed"
                            )
                    print(f"[CreateUsersForGroup] create_user({login}) failed: {e}")
                    raise

                # Dodajemy do grupy
                try:
                    self.group_manager.add_member(group_id, user_id)
                except Exception as e:
                    # rollback bieżącego i wszystkich poprzednich
                    try:
                        self.user_manager.delete_user(login)
                    except Exception:
                        print(
                            f"[CreateUsersForGroup] rollback delete_user({login}) failed"
                        )
                    for created_login, _uid in created:
                        try:
                            self.user_manager.delete_user(created_login)
                        except Exception:
                            print(
                                f"[CreateUsersForGroup] rollback delete_user({created_login}) failed"
                            )
                    print(
                        f"[CreateUsersForGroup] add_member failed for login={login}, group_id={group_id}: {e}"
                    )
                    raise

                created.append((login, user_id))

            response = pb2.CreateUsersForGroupResponse()
            response.message = (
                f"Created {len(users)} users in group '{group_name}' (Azure AD)."
            )
            return response

        except Exception as e:
            print(f"[CreateUsersForGroup] Error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.CreateUsersForGroupResponse()

    # ========== CreateGroupWithLeaders ==========

    def CreateGroupWithLeaders(self, request, context):
        """
        Tworzy grupę + liderów, zapisuje ich jako członków grupy.
        """
        group_name: str = request.groupName
        leaders: List[str] = list(request.leaders)

        try:
            group_id = self.group_manager.create_group(name=group_name)
            created_leaders: List[tuple[str, str]] = []

            for leader_login in leaders:
                # Tworzymy lidera z domyślnym hasłem z AzureUserManager
                try:
                    leader_id = self.user_manager.create_user(
                        login=leader_login,
                        display_name=leader_login,
                    )
                except Exception as e:
                    # rollback liderów + grupy
                    for login, _uid in created_leaders:
                        try:
                            self.user_manager.delete_user(login)
                        except Exception:
                            print(
                                f"[CreateGroupWithLeaders] rollback delete_user({login}) failed"
                            )
                    try:
                        self.group_manager.delete_group(group_id)
                    except Exception:
                        print(
                            f"[CreateGroupWithLeaders] rollback delete_group({group_id}) failed"
                        )
                    print(
                        f"[CreateGroupWithLeaders] create_user({leader_login}) failed: {e}"
                    )
                    raise

                # Dodajemy lidera do grupy
                try:
                    self.group_manager.add_member(group_id, leader_id)
                except Exception as e:
                    # rollback bieżącego lidera, wcześniejszych liderów i grupy
                    try:
                        self.user_manager.delete_user(leader_login)
                    except Exception:
                        print(
                            f"[CreateGroupWithLeaders] rollback delete_user({leader_login}) failed"
                        )
                    for login, _uid in created_leaders:
                        try:
                            self.user_manager.delete_user(login)
                        except Exception:
                            print(
                                f"[CreateGroupWithLeaders] rollback delete_user({login}) failed"
                            )
                    try:
                        self.group_manager.delete_group(group_id)
                    except Exception:
                        print(
                            f"[CreateGroupWithLeaders] rollback delete_group({group_id}) failed"
                        )
                    print(
                        f"[CreateGroupWithLeaders] add_member failed for leader={leader_login}, group_id={group_id}: {e}"
                    )
                    raise

                created_leaders.append((leader_login, leader_id))

            response = pb2.GroupCreatedResponse()
            response.groupName = group_name
            return response

        except Exception as e:
            print(f"[CreateGroupWithLeaders] Error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.GroupCreatedResponse()

    # ========== Metody kosztowe – na razie atrapy ==========

    def GetTotalCostForGroup(self, request, context):
        """
        Zwraca koszt grupy za zadany okres.
        Na razie atrapa – zawsze 0.0 (do późniejszej integracji z Azure Cost Management).
        """
        try:
            resp = pb2.CostResponse()
            resp.amount = 0.0
            return resp
        except Exception as e:
            print(f"[GetTotalCostForGroup] Error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.CostResponse()

    def GetTotalCostsForAllGroups(self, request, context):
        """
        Zwraca koszty wszystkich grup.
        Na razie atrapa – pusta lista.
        """
        try:
            resp = pb2.AllGroupsCostResponse()
            # docelowo tutaj wypełnimy resp.groupCosts
            return resp
        except Exception as e:
            print(f"[GetTotalCostsForAllGroups] Error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.AllGroupsCostResponse()

    def GetTotalCost(self, request, context):
        """
        Całkowity koszt subskrypcji.
        Na razie atrapa – 0.0.
        """
        try:
            resp = pb2.CostResponse()
            resp.amount = 0.0
            return resp
        except Exception as e:
            print(f"[GetTotalCost] Error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.CostResponse()

    def GetGroupCostWithServiceBreakdown(self, request, context):
        """
        Koszt grupy z podziałem na usługi.
        Na razie atrapa – total = 0.0, brak breakdown.
        """
        try:
            resp = pb2.GroupServiceBreakdownResponse()
            resp.total = 0.0
            # resp.breakdown pozostaje puste
            return resp
        except Exception as e:
            print(f"[GetGroupCostWithServiceBreakdown] Error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.GroupServiceBreakdownResponse()


def serve():
    validate_config()  # sprawdzi zmienne środowiskowe

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    pb2_grpc.add_CloudAdapterServicer_to_server(CloudAdapterServicer(), server)
    # port możesz zostawić 50053 albo dostosować do backendu
    server.add_insecure_port("[::]:50053")
    print("[AzureAdapter] gRPC server started on port 50053")
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
