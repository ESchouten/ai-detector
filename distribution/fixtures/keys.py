"""Public RFC 8032 test vector; never a production signing credential."""

import base64

PRIVATE_KEY = base64.b64encode(
    bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
).decode()
PUBLIC_KEY = base64.b64encode(
    bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
).decode()
