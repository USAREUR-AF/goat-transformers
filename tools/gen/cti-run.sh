#!/bin/bash
# Regenerate the cve-record, osv-record, cisa-kev-catalog and cisa-kev-vulnerability packs.
#
# Usage: tools/gen/cti-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources> holds git checkouts (the script checks each commit):
#   cve-schema  https://github.com/CVEProject/cve-schema  ce5f5c865f14dc40a6548d36b74751abca1c588a (CC0-1.0)
#               reads schema/docs/CVE_Record_Format_bundled.json
#   osv-schema  https://github.com/ossf/osv-schema        091feabc002e5c0a038639a765cded0448eeb202 (Apache-2.0)
#               reads validation/schema.json
#   kev-data    https://github.com/cisagov/kev-data       9c564f4dfa6dab393748a3b37038cde6a11b3585 (CC0-1.0)
#               reads known_exploited_vulnerabilities_schema.json
#   misp-rfc    https://github.com/MISP/misp-rfc           9ee0b9ce5313dabc82724980064016d44f756030 (Internet-Draft, IETF Trust)
#               not read by the run: tools/gen/misp-core-schema.json restates misp-core-format/raw.md
#   OpenIOC_1.1 https://github.com/mandiant/OpenIOC_1.1    f4973b80d4fcf9ae067a09df656ce6dd2d6899ba (Apache-2.0)
#               reads schemas/ioc.xsd
set -euo pipefail
CHECK=""
if [ "${1:-}" = "--check" ]; then CHECK="--check"; shift; fi
[ "$#" -eq 2 ] || { echo "usage: $0 [--check] <sources> <checkout>" >&2; exit 2; }
SRC="$(cd "$1" && pwd)"
W="$(cd "$2" && pwd)"
GEN="$W/tools/gen"
want() { got="$(git -C "$SRC/$1" rev-parse HEAD)"; [ "$got" = "$2" ] || { echo "$1 is at $got, not $2" >&2; exit 1; }; }
want cve-schema ce5f5c865f14dc40a6548d36b74751abca1c588a
want osv-schema 091feabc002e5c0a038639a765cded0448eeb202
want kev-data 9c564f4dfa6dab393748a3b37038cde6a11b3585
want misp-rfc 9ee0b9ce5313dabc82724980064016d44f756030
want OpenIOC_1.1 f4973b80d4fcf9ae067a09df656ce6dd2d6899ba
cd "$W"
C="$SRC/cve-schema/schema/docs/CVE_Record_Format_bundled.json"
python3 -I "$GEN/jsonschema2pack.py" --schema "$C" \
  --message "published=$C#/oneOf/0" --message "rejected=$C#/oneOf/1" \
  --kind-when "published:cveMetadata.state=PUBLISHED" --kind-when "rejected:cveMetadata.state=REJECTED" \
  --format cve-record --module cverecord --title "CVE JSON record format 5.x (CVEProject/cve-schema)" \
  --license "CC0-1.0 schema (CVEProject/cve-schema); structure restated: Apache-2.0" \
  --source "https://github.com/CVEProject/cve-schema at commit ce5f5c865f14dc40a6548d36b74751abca1c588a, schema/docs/CVE_Record_Format_bundled.json" \
  --map "*:cveMetadata.cveId=uid" \
  --evidence "*:cveMetadata.cveId=the CVE identifier the record pertains to, unique by the schema's definition of cveId" \
  --out "$W" --model-dir "$W/model" --names-file "$GEN/names/cve-record.json" \
  --notes-file "$GEN/notes/cve-record.md" ${CHECK:+"$CHECK"} > /dev/null
O="$SRC/osv-schema/validation/schema.json"
python3 -I "$GEN/jsonschema2pack.py" --schema "$O" --message "entry=$O" \
  --format osv-record --module osvrecord --title "OSV schema (ossf/osv-schema)" \
  --license "Apache-2.0, ossf/osv-schema" \
  --source "https://github.com/ossf/osv-schema at commit 091feabc002e5c0a038639a765cded0448eeb202, validation/schema.json" \
  --map "entry:id=uid" --map "entry:modified=time_ms" \
  --evidence "entry:id=the entry's identifier, unique within its database prefix" \
  --evidence "entry:modified=docs/schema.md: the time the entry was last modified, RFC 3339 in UTC; of two entries with one id the newer is chosen" \
  --out "$W" --model-dir "$W/model" --names-file "$GEN/names/osv-record.json" \
  --notes-file "$GEN/notes/osv-record.md" ${CHECK:+"$CHECK"} > /dev/null
K="$SRC/kev-data/known_exploited_vulnerabilities_schema.json"
python3 -I "$GEN/jsonschema2pack.py" --schema "$K" --message "catalog=$K" \
  --format cisa-kev-catalog --module cisakevcatalog --title "CISA Known Exploited Vulnerabilities catalog (cisagov/kev-data)" \
  --license "CC0-1.0 (cisagov/kev-data), a work of the United States Government; structure restated: Apache-2.0" \
  --source "https://github.com/cisagov/kev-data at commit 9c564f4dfa6dab393748a3b37038cde6a11b3585, known_exploited_vulnerabilities_schema.json" \
  --map "catalog:dateReleased=time_ms" \
  --evidence "catalog:dateReleased=the date and time the catalog was released, in the form YYYY-MM-DDTHH:mm:ss.sssZ" \
  --out "$W" --model-dir "$W/model" --names-file "$GEN/names/cisa-kev-catalog.json" \
  --notes-file "$GEN/notes/cisa-kev.md" ${CHECK:+"$CHECK"} > /dev/null
python3 -I "$GEN/jsonschema2pack.py" --schema "$K" --message "vulnerability=$K#/\$defs/vulnerability" \
  --format cisa-kev-vulnerability --module cisakevvuln --title "CISA KEV catalog entry (cisagov/kev-data)" \
  --license "CC0-1.0 (cisagov/kev-data), a work of the United States Government; structure restated: Apache-2.0" \
  --source "https://github.com/cisagov/kev-data at commit 9c564f4dfa6dab393748a3b37038cde6a11b3585, known_exploited_vulnerabilities_schema.json" \
  --map "vulnerability:cveID=uid" \
  --evidence "vulnerability:cveID=the CVE ID of the vulnerability" \
  --out "$W" --model-dir "$W/model" --names-file "$GEN/names/cisa-kev-vulnerability.json" \
  --notes-file "$GEN/notes/cisa-kev.md" ${CHECK:+"$CHECK"} > /dev/null
M="$GEN/misp-core-schema.json"
python3 -I "$GEN/jsonschema2pack.py" --schema "$M" --message "event=$M" \
  --format misp-core-event --module mispcore --title "MISP core format event (restated in tools/gen/misp-core-schema.json)" \
  --license "Internet-Draft draft-dulaunoy-misp-core-format (IETF Trust, BCP 78); members restated: Apache-2.0" \
  --source "https://github.com/MISP/misp-rfc at commit 9ee0b9ce5313dabc82724980064016d44f756030, misp-core-format/raw.md (draft-20)" \
  --source "tools/gen/misp-core-schema.json of this repository: the restated members" \
  --map "event:Event.uuid=uid" \
  --evidence "event:Event.uuid=the event's UUID, which must be preserved for every update or transfer of the same event" \
  --out "$W" --model-dir "$W/model" --names-file "$GEN/names/misp-core-event.json" \
  --notes-file "$GEN/notes/misp-core-event.md" ${CHECK:+"$CHECK"} > /dev/null
python3 -I "$GEN/xsd2pack.py" --xsd "$SRC/OpenIOC_1.1/schemas/ioc.xsd" --message OpenIOC \
  --format openioc-1-1 --module openioc --title "OpenIOC 1.1 schema (mandiant/OpenIOC_1.1)" \
  --source "https://github.com/mandiant/OpenIOC_1.1 at commit f4973b80d4fcf9ae067a09df656ce6dd2d6899ba, schemas/ioc.xsd" \
  --public-statement "Copyright 2013 Mandiant Corporation; licensed under the Apache 2.0 license (header comment of ioc.xsd)" \
  --map "OpenIOC:@id=uid" \
  --out "$W" --model-dir "$W/model" --names-file "$GEN/names/openioc-1-1.json" \
  --notes-file "$GEN/notes/openioc-1-1.md" ${CHECK:+"$CHECK"} > /dev/null
python3 -I "$GEN/cti-provenance.py" "$W" ${CHECK:+"$CHECK"}
[ -n "$CHECK" ] || echo cti
