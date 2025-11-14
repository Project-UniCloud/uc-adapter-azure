# main.py

from concurrent import futures

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

    # ========== CreateUsersForGroup ==========

    def CreateUsersForGroup(self, request, context):
        """
        Tworzy użytkowników i dodaje ich do istniejącej grupy.

        request:
          - groupName: nazwa grupy w Entra ID
          - users: repeated string (loginy użytkowników)
        """
        group_name = request.groupName
        users = list(request.users)

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

            created = []  # lista (login, user_id) do rollbacku

            for login in users:
                # 2. Utwórz użytkownika
                try:
                    user_id = self.user_manager.create_user(
                        login=login,
                        display_name=login,
                        initial_password=group_name,  # analog do AWS
                    )
                except Exception:
                    # rollback na już utworzonych userach
                    for created_login, _ in created:
                        self.user_manager.delete_user(created_login)
                    raise

                # 3. Dodaj do grupy
                try:
                    self.group_manager.add_member(group_id, user_id)
                except Exception:
                    # rollback usera + poprzednich
                    self.user_manager.delete_user(login)
                    for created_login, _ in created:
                        self.user_manager.delete_user(created_login)
                    raise

                created.append((login, user_id))

            # 4. Sukces
            response = pb2.CreateUsersForGroupResponse()
            response.message = (
                f"Created {len(users)} users in group '{group_name}'"
            )
            return response

        except Exception as e:
            print(f"Error in CreateUsersForGroup: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.CreateUsersForGroupResponse()

    # ========== CreateGroupWithLeaders ==========

    def CreateGroupWithLeaders(self, request, context):
        """
        Tworzy grupę + liderów, zapisuje ich jako członków grupy.

        request:
          - groupName: nazwa grupy
          - leaders: repeated string
        """
        group_name = request.groupName
        leaders = list(request.leaders)

        try:
            # 1. Tworzenie grupy
            group_id = self.group_manager.create_group(name=group_name)

            created_leaders = []  # do rollbacku

            # 2. Tworzenie liderów + przypisywanie do grupy
            for leader_login in leaders:
                try:
                    leader_id = self.user_manager.create_user(
                        login=leader_login,
                        display_name=leader_login,
                        initial_password=group_name,
                    )
                except Exception:
                    # rollback – usuń grupę + dotychczasowych liderów
                    for login, _id in created_leaders:
                        self.user_manager.delete_user(login)
                    self.group_manager.delete_group(group_id)
                    raise

                try:
                    self.group_manager.add_member(group_id, leader_id)
                except Exception:
                    # rollback
                    self.user_manager.delete_user(leader_login)
                    for login, _id in created_leaders:
                        self.user_manager.delete_user(login)
                    self.group_manager.delete_group(group_id)
                    raise

                created_leaders.append((leader_login, leader_id))

            # 3. Sukces
            response = pb2.GroupCreatedResponse()
            response.groupName = group_name
            return response

        except Exception as e:
            print(f"Error in CreateGroupWithLeaders: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.GroupCreatedResponse()


def serve():
    validate_config()  # sprawdzi, czy wszystkie AZURE_* są ustawione

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    pb2_grpc.add_CloudAdapterServicer_to_server(
        CloudAdapterServicer(), server
    )
    server.add_insecure_port("[::]:50053")
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
