#!/bin/bash
# Regenerate the opcua, opcua-gpos and opcua-autoid packs: the structured DataTypes of three
# OPC UA namespaces in the OPC UA binary encoding, one pack per namespace.
#
# Usage: tools/gen/opcua-run.sh [--check] <checkout> <sources>
#
# <sources> is a checkout of github.com/OPCFoundation/UA-Nodeset at tag UA-1.05.07-2026-07-30
# (commit 6338cced8e6cc2fa2c3816bc6b3bad5daee3f101). The files read:
#   Schema/Opc.Ua.NodeSet2.xml              namespace 0 (model 1.05.07)
#   DI/Opc.Ua.Di.NodeSet2.xml               DI, which AutoID requires
#   GPOS/Opc.Ua.GPOS.NodeSet2.xml           GPOS
#   AutoID/Opc.Ua.AutoID.NodeSet2.xml       AutoID
# Each file carries the OPC Foundation MIT License 1.00 in its header. They are not kept in this
# repository; each pack's PROVENANCE.md has their SHA-256. With --check nothing is written: each
# run compares what it would write with the files in <checkout> and the exit status is 1 when one
# differs.
set -euo pipefail
CHECK=()
if [ "${1:-}" = "--check" ]; then
  CHECK=(--check)
  shift
fi
if [ "$#" -ne 2 ]; then
  echo "usage: $0 [--check] <checkout> <sources>" >&2
  exit 2
fi
ROOT="$(cd "$1" && pwd)"
SRC="$(cd "$2" && pwd)"
GEN="$(cd "$(dirname "$0")" && pwd)"
TAG=UA-1.05.07-2026-07-30
COMMIT=6338cced8e6cc2fa2c3816bc6b3bad5daee3f101
LIC="OPC Foundation MIT License 1.00, in the header of each NodeSet file; this pack restates names, numbers and types only"
NS0="$SRC/Schema/Opc.Ua.NodeSet2.xml"
STATUS=0

python3 -I "$GEN/opcua2pack.py" --out "$ROOT" ${CHECK[@]+"${CHECK[@]}"} \
  --nodeset "$NS0" --namespace http://opcfoundation.org/UA/ --format opcua --module opcua \
  --source "OPC UA NodeSet, namespace 0: github.com/OPCFoundation/UA-Nodeset tag $TAG (commit $COMMIT), Schema/Opc.Ua.NodeSet2.xml" \
  --source "OPC 10000-6 (OPC UA Part 6), section 5.2, the binary encoding: reference.opcfoundation.org/Core/Part6/v105/docs/5.2" \
  --source "$LIC" \
  --notes-file "$GEN/notes/opcua.md" > /dev/null || STATUS=1

python3 -I "$GEN/opcua2pack.py" --out "$ROOT" ${CHECK[@]+"${CHECK[@]}"} \
  --nodeset "$NS0" "$SRC/GPOS/Opc.Ua.GPOS.NodeSet2.xml" \
  --namespace http://opcfoundation.org/UA/GPOS/ --format opcua-gpos --module opcuagpos \
  --source "OPC UA GPOS NodeSet: github.com/OPCFoundation/UA-Nodeset tag $TAG (commit $COMMIT), GPOS/Opc.Ua.GPOS.NodeSet2.xml, with Schema/Opc.Ua.NodeSet2.xml" \
  --source "OPC 10000-6 (OPC UA Part 6), section 5.2, the binary encoding: reference.opcfoundation.org/Core/Part6/v105/docs/5.2" \
  --source "$LIC" \
  --notes-file "$GEN/notes/opcua-gpos.md" > /dev/null || STATUS=1

python3 -I "$GEN/opcua2pack.py" --out "$ROOT" ${CHECK[@]+"${CHECK[@]}"} \
  --nodeset "$NS0" "$SRC/DI/Opc.Ua.Di.NodeSet2.xml" "$SRC/AutoID/Opc.Ua.AutoID.NodeSet2.xml" \
  --namespace http://opcfoundation.org/UA/AutoID/ --format opcua-autoid --module opcuaautoid \
  --time-ms Timestamp \
  --source "OPC UA AutoID NodeSet: github.com/OPCFoundation/UA-Nodeset tag $TAG (commit $COMMIT), AutoID/Opc.Ua.AutoID.NodeSet2.xml, with Schema/Opc.Ua.NodeSet2.xml and DI/Opc.Ua.Di.NodeSet2.xml" \
  --source "OPC 10000-6 (OPC UA Part 6), section 5.2, the binary encoding: reference.opcfoundation.org/Core/Part6/v105/docs/5.2" \
  --source "$LIC" \
  --notes-file "$GEN/notes/opcua-autoid.md" > /dev/null || STATUS=1

exit $STATUS
