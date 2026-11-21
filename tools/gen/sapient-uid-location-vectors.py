#!/usr/bin/env python3

"""The expected values of packs/sapient/vectors/02 to 07 and
packs/cot-xml/vectors/45 (the SAPIENT uid derivation and the detection kinds by
coordinate system), worked by hand without an engine. Standard library only.
Prints each vector's input and expected bytes; it writes nothing."""
# Hand encoder for the SAPIENT detection-report vectors. Standard library only.
import struct
def varint(n):
    out=b''
    while True:
        b=n&0x7f; n>>=7
        if n: out+=bytes([b|0x80])
        else: return out+bytes([b])
def key(f,wt): return varint((f<<3)|wt)
def ld(f,payload): return key(f,2)+varint(len(payload))+payload
def dbl(f,x): return key(f,1)+struct.pack('<d',x)
def vi(f,n): return key(f,0)+varint(n)
OID=b'01ARZ3NDEKTSV4RRFFQ69G5FAV'
def loc(x,y,z,cs=None,datum=None):
    p=dbl(1,x)+dbl(2,y)+dbl(3,z)
    if cs is not None: p+=vi(7,cs)
    if datum is not None: p+=vi(8,datum)
    return ld(6,p)
def det(location=b'',oid=OID):
    return ld(7,(ld(2,oid) if oid else b'')+location)
v={}
v['02-input-check']=det(loc(-85.95,30.009,12.5))
v['03-cs1']=det(loc(-85.95,30.009,12.5,1,1))
v['04-utm']=det(loc(-85.95,30.009,12.5,5,1))
v['06-rad']=det(loc(-1.5,0.5,12.5,2,1))
v['07-noloc']=det(b'')
# cot-xml -> sapient: time 2021-02-27T20:00:00.000Z
import datetime
ms=int(datetime.datetime(2021,2,27,20,0,0,tzinfo=datetime.timezone.utc).timestamp())*1000
sec=ms//1000; nsec=(ms-1000*(ms//1000))*1000000
v['cot']=ld(1,vi(1,sec)+vi(2,nsec))+ld(7,loc(float('-85.9578182'),float('30.0090027'),float('-42.6'),1,1))
print('ms',ms,'sec',sec,'nsec',nsec)
for k,b in v.items(): print(k,b.hex())
# decode check of the existing 02 input
inp=bytes.fromhex('3a39121a303141525a334e44454b54535634525246465136394735464156321b09cdcccccccc7c55c011fca9f1d24d023e40190000000000002940')
print('02 input equals hand build:', inp==v['02-input-check'])
for off in (32,41,50):
    print(struct.unpack('<d',inp[off:off+8])[0], repr(struct.unpack('<d',inp[off:off+8])[0]))
