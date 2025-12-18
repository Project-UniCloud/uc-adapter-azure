#!/bin/bash
# Generate protobuf files for Azure adapter
# Files are generated into protos/ directory

set -e

PROTO_DIR="protos"
PROTO_FILE="${PROTO_DIR}/adapter_interface.proto"
OUT_DIR="${PROTO_DIR}"

echo "Generating protobuf files from ${PROTO_FILE}..."
echo "Output directory: ${OUT_DIR}"

python -m grpc_tools.protoc -I="${PROTO_DIR}" \
  --python_out="${OUT_DIR}" \
  --grpc_python_out="${OUT_DIR}" \
  "${PROTO_FILE}"

if [ $? -ne 0 ]; then
  echo "❌ ERROR: Failed to generate protobuf files"
  echo "Make sure grpcio-tools is installed: pip install grpcio-tools"
  exit 1
fi

echo ""
echo "✅ Successfully generated protobuf files to ${OUT_DIR}"
echo ""
echo "NOTE: After generation, you may need to fix the import in adapter_interface_pb2_grpc.py:"
echo "  Change: import adapter_interface_pb2 as adapter__interface__pb2"
echo "  To:     from protos import adapter_interface_pb2 as adapter__interface__pb2"

