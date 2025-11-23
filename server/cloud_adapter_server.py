# server/cloud_adapter_server.py

from concurrent import futures
from typing import List

import grpc

from config.settings import validate_config
from identity.user_manager import AzureUserManager
from identity.group_manager import AzureGroupManager
from protos import adapter_interface_pb2 as pb2
from protos import adapter_interface_pb2_grpc as pb2_grpc


class CloudAdapterServicer(pb2_grpc.CloudAdapterServicer):
    """
    Implementacja serwisu gRPC dla adaptera Azure.

    To jest odpowiednik AWS-owego CloudAdapterServicer, ale oparty
    o AzureUserManager i AzureGroupManager.
    """

    def __init__(self) -> None:
        self.user_manager = AzureUserManager()
        self.group_manager = AzureGroupManager()

    # ========= RPC: CreateUsersForGroup =========

    def CreateUsersForGroup(self, request, context):
        """
        Tworzy wielu użytkowników i dodaje ich do istniejącej grupy.

        request:
          - groupName: nazwa istniejącej grupy w Entra ID
          - users: repeated string – loginy użytkowników (bez domeny)

        response:
          - message: prosty komunikat tekstowy
        """
        group_name: str = request.groupName
        users: List[str] = list(request.users)

        try:
            # 1. Sprawdź, czy grupa istnieje
            group = self.group_manager.get_group_by_name(group_name)
            if not group:
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details(
                    f"Group '{group_name}' does not exist in Azure AD"
                )
                return pb2.CreateUsersForGroupResponse()

            group_id = group["id"]

            created: List[tuple[str, str]] = []  # (login, user_id) do rollbacku

            # 2. Tworzenie użytkowników + dodawanie do grupy
            for login in users:
                # 2.1 utworzenie użytkownika
                try:
                    user_id = self.user_manager.create_user(
                        login=login,
                        display_name=login,
                        initial_password=group_name,  # analog do AWS – hasło = nazwa grupy
                    )
                except Exception as e:
                    # rollback – usuń już utworzonych użytkowników
                    for created_login, _uid in created:
                        try:
                            self.user_manager.delete_user(created_login)
                        except Exception:
                            # tutaj tylko logujemy – nie przerywamy kolejnych prób rollbacku
                            print(
                                f"[CreateUsersForGroup] rollback delete_user({created_login}) failed"
                            )
                    print(f"[CreateUsersForGroup] create_user({login}) failed: {e}")
                    raise

                # 2.2 dodanie do grupy
                try:
                    self.group_manager.add_member(group_id, user_id)
                except Exception as e:
                    # rollback – usuń bieżącego i wszystkich dotychczas utworzonych
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

            # 3. Sukces – budujemy odpowiedź
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

    # ========= RPC: CreateGroupWithLeaders =========

    def CreateGroupWithLeaders(self, request, context):
        """
        Tworzy grupę oraz użytkowników-liderów i dodaje ich do tej grupy.

        request:
          - groupName: nazwa tworzonej grupy
          - leaders: repeated string – loginy liderów

        response:
          - groupName: nazwa utworzonej grupy
        """
        group_name: str = request.groupName
        leaders: List[str] = list(request.leaders)

        try:
            # 1. Tworzenie grupy
            group_id = self.group_manager.create_group(name=group_name)

            created_leaders: List[tuple[str, str]] = []  # (login, user_id)

            # 2. Tworzenie liderów + przypisanie do grupy
            for leader_login in leaders:
                # 2.1 utworzenie użytkownika
                try:
                    leader_id = self.user_manager.create_user(
                        login=leader_login,
                        display_name=leader_login,
                        initial_password=group_name,
                    )
                except Exception as e:
                    # rollback – usuń dotychczasowych liderów + grupę
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

                # 2.2 dodanie lidera do grupy
                try:
                    self.group_manager.add_member(group_id, leader_id)
                except Exception as e:
                    # rollback – usuń bieżącego lidera, wcześniejszych liderów i grupę
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

            # 3. Sukces
            response = pb2.GroupCreatedResponse()
            response.groupName = group_name
            return response

        except Exception as e:
            print(f"[CreateGroupWithLeaders] Error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.GroupCreatedResponse()


def serve(port: int = 50051) -> None:
    """
    Tworzy i uruchamia serwer gRPC adaptera Azure.
    """
    validate_config()

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    pb2_grpc.add_CloudAdapterServicer_to_server(
        CloudAdapterServicer(),
        server,
    )
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    print(f"[AzureAdapter] gRPC server started on port {port}")
    server.wait_for_termination()
