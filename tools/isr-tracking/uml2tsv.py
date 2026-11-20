#!/usr/bin/env python3
"""uml2tsv.py: list the attributes of the classes of the AEDP-12 data model.

Reads the text of the document (pdftotext -layout) and prints class, attribute,
type and multiplicity, one per line, from the class attribute tables of sections
2.5 and 2.6. The output, with a header, is tools/isr-tracking/model.tsv.

Usage: pdftotext -layout NATO_AEDP-12_EdB_V2.pdf t.txt; python3 -I uml2tsv.py t.txt
"""
import re,sys
T=open(sys.argv[1]).read().split("\n")
start=[i for i,l in enumerate(T) if re.match(r'^2\.5\.1\s+NITSRoot\s*$',l)][0]
end=[i for i,l in enumerate(T) if i>start and 'ANNEX A REPORTING TRACKS' in l][0]
L=T[start:end]
cls=None; out=[]; i=0; intable=False
mult=re.compile(r'^\[0\.\.1\]$|^(0|1)(\.\.(\*|1|[0-9]+))?$|^\*$|^[0-9]\.\.\*$')
while i<len(L):
    l=L[i]
    m=re.match(r'\s*Table 2\.[56]\.\d+-1: (\w+?)(?: Class Attributes| Attributes|Attributes)?\s*$',l)
    if m: cls=m.group(1); intable=True; i+=1; continue
    if re.match(r'\s*Table 2\.[56]\.\d+-[2-9]',l) or re.match(r'^2\.[56]\.\d+\s',l): intable=False
    if intable:
        # first column token
        tok=re.split(r'\s{2,}',l.strip())[:1] if l.strip() else []
        if tok and ' ' not in tok[0] and i+2<len(L):
            t2=L[i+1].split()[:1] or ['']; t3=L[i+2].split()[:1] or ['']
            if ' ' not in t2[0] and mult.match(t3[0]) and re.match(r'^[a-z]\w*$',tok[0]):
                out.append((cls,tok[0],t2[0],t3[0])); i+=3; continue
    i+=1
for o in out: print("\t".join(o))
