from binascii import hexlify, unhexlify
from time import time
from struct import pack
from hashlib import sha1, sha256
from os import urandom
from card_const import KEY_ATTRIBUTES_RSA2K

def build_privkey_template_for_remove(openpgp_keyno):
    if openpgp_keyno == 1:
        keyspec = b'\xb6'
    elif openpgp_keyno == 2:
        keyspec = b'\xb8'
    else:
        keyspec = b'\xa4'
    return b'\x4d\x02' + keyspec + b'\x00'

# egcd and modinv are from wikibooks
# https://en.wikibooks.org/wiki/Algorithm_Implementation/Mathematics/Extended_Euclidean_algorithm

def egcd(a, b):
    if a == 0:
        return (b, 0, 1)
    else:
        g, y, x = egcd(b % a, a)
        return (g, x - (b // a) * y, y)

def modinv(a, m):
    g, x, y = egcd(a, m)
    if g != 1:
        raise Exception('modular inverse does not exist')
    else:
        return x % m

def pkcs1_pad_for_sign(digestinfo):
    byte_repr = b'\x00' + b'\x01' + bytes.ljust(b'', 256 - 19 - 32 - 3, b'\xff') \
        + b'\x00' + digestinfo
    return int(hexlify(byte_repr), 16)

def pkcs1_pad_for_crypt(msg):
    padlen = 256 - 3 - len(msg)
    byte_repr = b'\x00' + b'\x02' \
        + bytes.replace(urandom(padlen), b'\x00', b'\x01') + b'\x00' + msg
    return int(hexlify(byte_repr), 16)

def integer_to_bytes_256(i):
    return i.to_bytes(256, byteorder='big')


class PK_Crypto(object):
    @staticmethod
    def pk_from_pk_info(pk_info):
        return pk_info[9:9+256]

    @staticmethod
    def compute_digestinfo(msg):
        digest = sha256(msg).digest()
        prefix = b'\x30\x31\x30\x0d\x06\x09\x60\x86\x48\x01\x65\x03\x04\x02\x01\x05\x00\x04\x20'
        return prefix + digest
    @staticmethod
    def enc_data(enc_info):
        return enc_info[1]

    @staticmethod
    def enc_check(enc_info, s):
        return enc_info[0] == s


    def __init__(self, keyno=None, pk_info=None, data=None):
        if keyno == None:
            # Just for name space
            return

        self.keyno = keyno
        self.timestamp = pack('>I', int(time()))
        if pk_info:
            # Public part only (no private data)
            self.bytes_n = pk_info[9:9+256]
            self.bytes_e = pk_info[9+256+2:]
            self.e = int.from_bytes(self.bytes_e, "big")
            self.n = int.from_bytes(self.bytes_n, "big")
        else:
            # Public/Private part from data
            self.bytes_e = data[0]
            self.bytes_n = data[1]
            self.bytes_p = data[2]
            self.bytes_q = data[3]
            self.e = int.from_bytes(self.bytes_e, "big")
            self.n = int.from_bytes(self.bytes_n, "big")
            self.p = int.from_bytes(self.bytes_p, "big")
            self.q = int.from_bytes(self.bytes_q, "big")
            if self.n != self.p * self.q:
                raise ValueError("wrong key", self.p, self.q, self.n)
        self.fpr = self.calc_fpr()

    def calc_fpr(self):
        m_len = 6 + 2 + 256 + 2 + 4
        m = b'\x99' + pack('>H', m_len) + b'\x04' + self.timestamp + b'\x01' + \
            pack('>H', 2048) + self.bytes_n + pack('>H', 17) + self.bytes_e
        return sha1(m).digest()

    def build_privkey_template(self, is_yubikey):
        openpgp_keyno = self.keyno + 1
        if openpgp_keyno == 1:
            keyspec = b'\xb6'
        elif openpgp_keyno == 2:
            keyspec = b'\xb8'
        else:
            keyspec = b'\xa4'

        key_template = b'\x91' + (b'\x03' if is_yubikey else b'\x04') \
                               + b'\x92\x81\x80' + b'\x93\x81\x80' 
        exthdr = keyspec + b'\x00' + b'\x7f\x48' + b'\x08' + key_template
        suffix = b'\x5f\x48' + b'\x82\x01' + (b'\x03' if is_yubikey else b'\x04')
        return b'\x4d' + b'\x82\x01' + (b'\x15' if is_yubikey else b'\x16') \
                       + exthdr + suffix \
                       + (b'' if is_yubikey else b'\x00') + self.bytes_e \
                       + self.bytes_p + self.bytes_q

    def compute_signature(self, digestinfo):
        p1 = self.p - 1
        q1 = self.q - 1
        h = p1 * q1
        d = modinv(self.e, h)
        dp = d % p1
        dq = d % q1
        qp = modinv(self.q, self.p)
        input = pkcs1_pad_for_sign(digestinfo)
        t1 = pow(input, dp, self.p)
        t2 = pow(input, dq, self.q)
        t = ((t1 - t2) * qp) % self.p
        sig = t2 + t * self.q
        return sig.to_bytes(int((sig.bit_length()+7)/8), byteorder='big')

    def verify_signature(self, digestinfo, sig_bytes):
        sig = int(hexlify(sig_bytes),16)
        di_pkcs1 = pow(sig, self.e, self.n)
        m = pkcs1_pad_for_sign(digestinfo)
        return di_pkcs1 == m

    def encrypt(self, plaintext):
        m = pkcs1_pad_for_crypt(plaintext)
        return (plaintext, b'\x00' + integer_to_bytes_256(pow(m, self.e, self.n)))

    def get_fpr(self):
        return self.fpr

    def get_timestamp(self):
        return self.timestamp

    def get_pk(self):
        return self.bytes_n

key0_data = (
    b'\x01\x00\x01',
    b'\xc6\xc8\x77\xdf\xd3\xb4\x41\xf8\xfb\x1b\x8d\xc5\x04\x09\x3a\x51'
    b'\xc2\xef\xe4\x88\x3f\xe0\xa6\x37\x92\x05\xac\xc6\xe6\x73\x70\x99'
    b'\x05\xe4\xd7\x67\xdd\xf4\x61\x43\xc5\x35\xcc\x6d\x7f\x10\xb6\x16'
    b'\xf5\x20\xd8\x34\x63\x20\xef\x69\xff\x4a\x2c\x4f\x4a\x14\x8e\xdc'
    b'\x65\xf7\xad\x24\xed\x7d\x4f\xe2\x3b\xb8\x62\xa0\xae\x71\xf4\xf7'
    b'\x90\x4a\xba\xc0\x39\x7a\xbf\x32\x13\xdf\x91\x32\x6b\x1a\x25\x55'
    b'\x4b\x3b\x18\xcf\x54\x58\x4d\x8b\xf2\x20\x16\x9f\xc9\x2b\x2a\xa5'
    b'\x11\xe8\x31\x39\x83\xe7\x2b\x4c\x91\x10\xb3\xa1\xae\xa0\x87\xae'
    b'\xbe\xf9\x58\x73\x86\x56\x08\xe8\xfa\xea\x9e\xf1\x0e\x7f\x7f\x3a'
    b'\x66\xca\x8d\xef\x2d\x49\x9c\x31\x49\xc1\x27\x49\x1e\x0e\x43\x39'
    b'\xfd\x6a\xbe\x10\xbf\xc6\xc1\x3e\x43\xd5\x22\x00\x4f\x14\x85\x76'
    b'\x73\x28\xea\xbe\x35\xd6\xff\xa8\xdf\x4c\x15\xf0\xfb\xcd\x4e\xb1'
    b'\xc0\x7c\xc6\xd8\x5e\x27\x51\x39\xac\x69\xe2\x96\x22\x73\xae\x98'
    b'\x72\x36\x92\x6d\xd6\xc1\x14\x4f\xce\x3e\x7a\xe5\x67\xfa\x58\xea'
    b'\x60\x62\x0d\xfa\xfc\x52\xf9\x52\x99\xfe\xa6\x01\x73\x9f\xce\x27'
    b'\xee\x71\xee\xa9\x78\xd0\x07\x4f\x21\xe7\x08\x6f\x60\xba\x83\x31',
    b'\xcc\x36\x5b\x57\x02\x71\x4b\xf2\x03\xe8\xc4\x9b\x0b\x8a\xfa\x8d'
    b'\xad\x58\x6e\x92\x9c\xf5\xed\xca\x38\xad\x07\xfa\x45\xef\xd5\xc2'
    b'\xd8\x90\x22\xd2\x9f\x40\x28\x3a\x57\xe5\x0c\xa2\x4c\x5f\x28\xc8'
    b'\xe9\x11\xa7\x4f\xaa\xf7\x96\xf1\x12\xe7\xe4\x81\x95\x95\x6f\x9a'
    b'\x4d\xf7\x66\x8a\x53\x42\x52\x3b\x27\x17\x9c\xec\x95\x8f\x36\x32'
    b'\x11\xee\x11\xd0\xec\x0e\x0e\x1b\x92\xca\x00\x7a\x61\xe8\xc9\xac'
    b'\x14\xe0\x02\x29\xb9\xa7\x62\x48\x50\x19\x9e\x66\x67\xaf\xa1\xa4'
    b'\x4d\xb8\xf3\xc5\xde\x0a\x8e\xef\x0e\x6d\xe0\x50\xac\x0a\xc6\x33',
    b'\xf9\x31\xa3\xc1\x2f\x0e\x3a\x52\x76\xf7\x12\xb7\x70\x65\x90\xba'
    b'\x02\xe1\x4a\x97\xff\x9b\x8c\xe3\x15\x2a\xf0\xfc\x4d\x9c\xdc\x69'
    b'\x0e\xa9\xbc\x4c\x82\xcb\x16\xc7\xd2\x31\x36\xcb\xda\xb5\x8f\xbe'
    b'\xc6\x98\x80\xa8\x8b\xca\x85\xc4\x21\x4d\xf0\x10\x45\x08\x2c\xbe'
    b'\x9f\x41\x92\xe3\xe3\x9c\x79\x89\x65\x33\xc3\x7d\xad\x9e\xb9\xe7'
    b'\x3c\x26\x43\xb9\xc0\xa7\x04\xa4\xf9\x3d\x81\x57\x35\x37\x96\x3d'
    b'\x6b\x6e\x51\x40\xa2\x4c\x70\x2d\x9f\x26\xe0\x6a\x20\x95\xde\x90'
    b'\x6d\xaa\x88\x24\x17\x2a\x6b\x39\xf5\x63\xb7\x15\x39\x07\x05\x0b'
)
key1_data = (
    b'\x01\x00\x01',
    b'\xd3\x92\x71\x4c\x29\x73\x8a\xac\x63\x72\xf2\xc8\x65\x4a\x08\xc2'
    b'\x5a\x12\x99\xfe\xd7\x00\x4b\xd5\x12\xcd\x24\x52\xb5\x03\xeb\xad'
    b'\x63\x01\x13\x08\x16\xac\x52\x5b\xa5\x28\xdc\x15\x5b\xe6\x34\x7a'
    b'\x5c\x70\x40\x7f\xb4\xfb\xda\xed\x75\x1d\xfc\x0a\x7c\xd5\xe3\x91'
    b'\x02\x72\xff\x23\x6c\x4e\xd1\xce\x5d\xe6\x62\x0b\x19\x1a\x17\x2e'
    b'\x5b\x24\x73\x47\xb8\xca\xb7\x3a\x43\xd7\x92\x21\x70\x87\x55\xc9'
    b'\x59\xa2\xf8\x3f\x48\x64\x39\xda\x30\x91\x73\x84\x55\x43\x31\x53'
    b'\x2a\xab\xc8\x32\x6d\xb4\x88\x66\xf8\xc9\x11\x98\x83\x4a\x86\xab'
    b'\x94\x67\x9f\x61\x75\xdb\x73\x7b\xdf\x39\x9e\x3f\x0b\x73\x7d\xcb'
    b'\x1f\x42\x08\x27\x9d\x3e\x1c\xc6\x94\xe7\x86\x86\x78\x5e\x4f\x36'
    b'\x3a\x37\x7d\xec\x91\x2b\x7c\x2f\x75\x7b\x14\x22\xd8\x66\xfb\x9f'
    b'\xa8\x5c\x96\xb8\x3a\xdf\xd6\xa2\x23\x98\x9a\x9a\x02\x98\x8b\xde'
    b'\xe8\x1a\xd1\x7e\xff\x63\x85\xe7\xb3\x8c\xec\x86\x11\xfd\xf3\x67'
    b'\xba\x4a\xc8\xe9\x0d\x5f\x48\xac\x77\x15\xc5\xf4\x7a\xea\x06\xa4'
    b'\xa3\x7c\xda\xa3\x02\x9c\xe5\x9d\x29\xbc\x66\x85\x3b\xf6\x75\x8e'
    b'\xf4\xa7\xda\x5a\x59\x53\xf5\xe5\x57\xa5\xa2\x2f\x67\xc3\x68\xc3',
    b'\xda\xe0\x85\x95\x2c\x5b\xee\xe3\x8f\x25\xf0\x9b\xc3\x7a\x4c\xa2'
    b'\x43\x4c\x31\xf7\x80\x55\x46\x9d\x0d\x5f\x0b\xf3\x33\x7e\x3a\x70'
    b'\xba\x6c\x91\x73\x4f\x19\x5b\x74\x2e\x21\x1a\x5f\xe2\x83\xbe\xfd'
    b'\xf6\x68\x20\x00\x8e\x6e\xf2\xc8\xca\x54\xa9\x19\x22\x83\x8f\xce'
    b'\x07\xd9\xe3\x3a\x33\x1c\xe2\x0d\xac\x36\x80\x3e\x77\x7d\x5e\xe2'
    b'\x19\x5e\xd2\x8d\x6a\x40\x45\xe2\x86\x23\xa6\xa6\x0b\x06\x61\xe4'
    b'\x5f\x7c\x4f\x84\xae\x2b\x1d\xfa\xd0\xcf\x1e\xc3\x06\x05\x15\x83'
    b'\x23\x38\x2a\x81\x9e\x73\x0c\x09\xa3\x3f\xad\x70\x4d\xd6\x75\x01',
    b'\xf7\x74\xbe\x43\xea\x19\x8a\xa2\xf0\x89\x27\x4e\x4f\xff\xd7\xd0'
    b'\x09\x2e\xe7\xb3\x5a\x1d\x2f\x85\x4c\xdb\x16\x6f\x69\x8c\xaa\xb7'
    b'\x2f\xde\xb0\x99\xe6\x90\xe7\x84\x38\xb2\xe0\x43\xe4\x52\xd4\xd2'
    b'\xf1\x9d\x7f\x44\xba\x6b\x28\x66\x42\xf0\xce\x52\x04\x96\x6f\xf9'
    b'\x8e\xcd\x9e\x3b\x44\x88\x77\x32\x46\x31\x36\x5d\xc8\x60\x79\x74'
    b'\x29\xb9\x41\x4a\x21\xa7\xe1\x66\xd5\x04\xca\xce\x15\x65\x88\xb9'
    b'\xa1\x45\x65\x7e\xeb\x1a\xfb\x43\xb8\xff\x65\xd8\xd6\xd9\x3c\xea'
    b'\x2b\xa4\xef\x8a\xab\x04\x78\x85\xc4\xde\x64\xff\xef\x0b\x49\xc3'
)
key2_data = (
    b'\x01\x00\x01',
    b'\x9c\xf7\x19\x2b\x51\xa5\x74\xd1\xad\x3c\xcb\x08\xba\x09\xb8\x7f'
    b'\x22\x85\x73\x89\x3e\xee\x35\x55\x29\xff\x24\x3e\x90\xfd\x4b\x86'
    b'\xf7\x9a\x82\x09\x7c\xc7\x92\x2c\x04\x85\xbe\xd1\x61\x6b\x16\x56'
    b'\xa9\xb0\xb1\x9e\xf7\x8e\xa8\xec\x34\xc3\x84\x01\x9a\xdc\x5d\x5b'
    b'\xf4\xdb\x2d\x2a\x0a\x2d\x9c\xf1\x42\x77\xbd\xcb\x70\x56\xf4\x8b'
    b'\x81\x21\x4e\x3f\x7f\x77\x42\x23\x1e\x29\x67\x39\x66\xf9\xb1\x10'
    b'\x68\x62\x11\x2c\xc7\x98\xdb\xa8\xd4\xa1\x38\xbb\x5a\xbf\xc6\xd4'
    b'\xc1\x2d\x53\xa5\xd3\x9b\x2f\x78\x3d\xa9\x16\xda\x20\x85\x2e\xe1'
    b'\x39\xbb\xaf\xda\x61\xd4\x29\xca\xf2\xa4\xf3\x08\x47\xce\x7e\x7a'
    b'\xe3\x2a\xb4\x06\x1e\x27\xdd\x9e\x4d\x00\xd6\x09\x10\x24\x9d\xb8'
    b'\xd8\x55\x9d\xd8\x5f\x7c\xa5\x96\x59\xef\x40\x0c\x8f\x63\x18\x70'
    b'\x0f\x4e\x97\xf0\xc6\xf4\x16\x5d\xe8\x06\x41\x49\x04\x33\xc8\x8d'
    b'\xa8\x68\x2b\xef\xe6\x8e\xb3\x11\xf5\x4a\xf2\xb0\x7d\x97\xac\x74'
    b'\xed\xb5\x39\x9c\xf0\x54\x76\x42\x11\x69\x4f\xbb\x8d\x1d\x33\x3f'
    b'\x32\x69\xf2\x35\xab\xe0\x25\x06\x7f\x81\x1f\xf8\x3a\x22\x24\x82'
    b'\x62\x19\xb3\x09\xea\x3e\x6c\x96\x8f\x42\xb3\xe5\x2f\x24\x5d\xc9',
    b'\xb5\xab\x7b\x15\x92\x20\xb1\x8e\x36\x32\x58\xf6\x1e\xbd\xe0\x8b'
    b'\xae\x83\xd6\xce\x2d\xbf\xe4\xad\xc1\x43\x62\x8c\x52\x78\x87\xac'
    b'\xde\x9d\xe0\x9b\xf9\xb4\x9f\x43\x80\x19\x00\x4d\x71\x85\x5f\x30'
    b'\xc2\xd6\x9b\x6c\x29\xbb\x98\x82\xab\x64\x1b\x33\x87\x40\x9f\xe9'
    b'\x19\x94\x64\xa7\xfa\xa4\xb5\x23\x0c\x56\xd9\xe1\x7c\xd9\xed\x07'
    b'\x4b\xc0\x01\x80\xeb\xed\x62\xba\xe3\xaf\x28\xe6\xff\x2a\xc2\x65'
    b'\x4a\xd9\x68\x83\x4c\x5d\x5c\x88\xf8\xd9\xd3\xcc\x5e\x16\x7b\x10'
    b'\x45\x3b\x04\x9d\x4e\x45\x4a\x57\x61\xfb\x0a\xc7\x17\x18\x59\x07',
    b'\xdd\x2f\xff\xa9\x81\x42\x96\x15\x6a\x69\x26\xcd\x17\xb6\x55\x64'
    b'\x18\x7e\x42\x4d\xca\xdc\xe9\xb0\x32\x24\x6a\xd7\xe4\x64\x48\xbb'
    b'\x0f\x9e\x0f\xf3\xc6\x4f\x98\x74\x24\xb1\xa4\x0b\xc6\x94\xe2\xe9'
    b'\xac\x4f\xb1\x93\x0d\x16\x35\x82\xd7\xac\xf2\x06\x53\xa1\xc4\x4b'
    b'\x97\x84\x6c\x1c\x5f\xd8\xa7\xb1\x9b\xb2\x25\xfb\x39\xc3\x0e\x25'
    b'\x41\x04\x83\xde\xaf\x8c\x25\x38\xd2\x22\xb7\x48\xc4\xd8\x10\x3b'
    b'\x11\xce\xc0\x4f\x66\x6a\x5c\x0d\xbc\xbf\x5d\x5f\x62\x5f\x15\x8f'
    b'\x65\x74\x6c\x3f\xaf\xe6\x41\x81\x45\xf7\xcf\xfa\x5f\xad\xee\xaf'
)

key = [
    PK_Crypto(keyno=0, data=key0_data),
    PK_Crypto(keyno=1, data=key1_data),
    PK_Crypto(keyno=2, data=key1_data)
]

PLAIN_TEXT0=b"This is a test message."
PLAIN_TEXT1=b"RSA decryption is as easy as pie."
PLAIN_TEXT2=b"This is another test message.\nMultiple lines.\n"
ENCRYPT_TEXT0 = b"encrypt me please"

test_vector = {
    'sign_0' : PLAIN_TEXT0,
    'sign_1' : PLAIN_TEXT1,
    'auth_0' : PLAIN_TEXT0,
    'auth_1' : PLAIN_TEXT1,
    'decrypt_0' : PLAIN_TEXT0,
    'decrypt_1' : PLAIN_TEXT1,
    'encrypt_0' : ENCRYPT_TEXT0,
}

rsa_pk = PK_Crypto()
rsa_pk.test_vector = test_vector
rsa_pk.key_list = key
rsa_pk.key_attr_list = [KEY_ATTRIBUTES_RSA2K, KEY_ATTRIBUTES_RSA2K, KEY_ATTRIBUTES_RSA2K]
rsa_pk.PK_Crypto = PK_Crypto