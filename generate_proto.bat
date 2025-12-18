@echo off
REM Generate protobuf files for Azure adapter
REM Files are generated into protos/ directory

set PROTO_DIR=protos
set PROTO_FILE=%PROTO_DIR%\adapter_interface.proto
set OUT_DIR=%PROTO_DIR%

echo Generating protobuf files from %PROTO_FILE%...
echo Output directory: %OUT_DIR%

python -m grpc_tools.protoc -I=%PROTO_DIR% --python_out=%OUT_DIR% --grpc_python_out=%OUT_DIR% %PROTO_FILE%

IF %ERRORLEVEL% NEQ 0 (
    echo ERROR: Failed to generate protobuf files
    echo Make sure grpcio-tools is installed: pip install grpcio-tools
    exit /b %ERRORLEVEL%
)

echo.
echo Successfully generated protobuf files to %OUT_DIR%
echo.
echo NOTE: After generation, you may need to fix the import in adapter_interface_pb2_grpc.py:
echo   Change: import adapter_interface_pb2 as adapter__interface__pb2
echo   To:     from protos import adapter_interface_pb2 as adapter__interface__pb2

