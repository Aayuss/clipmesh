#!/usr/bin/env python3
"""Deterministic security-vector and tamper tests for nearby clipboard pairing."""
import base64, hashlib, hmac

def h(key, data): return hmac.new(key, data, hashlib.sha256).digest()
def expand(prk, info, count):
    out=b''; previous=b''; counter=1
    while len(out)<count:
        previous=h(prk,previous+info+bytes([counter]));out+=previous;counter+=1
    return out[:count]
def keys(agreement_secret, transcript):
    material=expand(h(hashlib.sha256(transcript).digest(),agreement_secret),b'clipmesh-nearby-pair-v1',64)
    return material[:32],material[32:]
def seal(plain, secret, transcript, nonce):
    enc,mac=keys(secret,transcript);stream=b'';counter=0
    while len(stream)<len(plain):
        stream+=h(enc,b'stream\n'+nonce+counter.to_bytes(4,'big'));counter+=1
    cipher=bytes(a^b for a,b in zip(plain,stream));tag=h(mac,b'payload\n'+transcript+nonce+cipher)
    return cipher,tag
def code(secret, transcript):
    mac=keys(secret,transcript)[1]
    return f'{int.from_bytes(h(mac,b"sas\n"+transcript)[:4],"big")%1_000_000:06d}'
def u(value): return base64.urlsafe_b64encode(value).decode().rstrip('=')

# The cross-platform managers receive SHA-256(raw P-256 ECDH) as agreement_secret.
agreement_secret=hashlib.sha256(bytes(range(32))).digest()
transcript=b'ClipMesh-Pair-v1\n11111111-2222-3333-4444-555555555555\nrequestnonce\ninitiator-fingerprint\nresponder-fingerprint\nBBDUMMYINIT\nBBRESponder'
nonce=bytes(range(16,32));plain=b'clipmesh://pair?v=1&space=test&key=secret'
cipher,tag=seal(plain,agreement_secret,transcript,nonce)
assert code(agreement_secret,transcript)=='446202'
assert u(cipher)=='rYLbMooZ9Q1aZoN_4m_TqhhS8pabx6OUY-ymHHujNsRDoF3MJi-rKoA'
assert u(tag)=='WdCyZGQjuxvAVVgABco0XmeCSQvqFuhwnGksDjChV-g'

# Transcript substitution (the relevant active-MITM case) must change the SAS,
# and any ciphertext/tag change must fail authentication.
assert code(agreement_secret,transcript+b' attacker') != '446202'
tampered=bytearray(cipher);tampered[0]^=1
assert not hmac.compare_digest(tag,h(keys(agreement_secret,transcript)[1],b'payload\n'+transcript+nonce+tampered))
bad_tag=bytearray(tag);bad_tag[-1]^=1
assert not hmac.compare_digest(tag,bad_tag)
print('ClipMesh nearby pairing KDF, SAS, encryption and tamper vectors passed')
