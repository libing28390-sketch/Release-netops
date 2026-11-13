"""
OUI (Organizationally Unique Identifier) 厂商查询模块。

根据 MAC 地址前 6 位（OUI 前缀）识别设备厂商。
内置常见网络设备和终端的 OUI 数据库，覆盖大部分企业网络场景。
"""

# 常见 OUI 前缀 → 厂商名（前 6 位 hex，小写无分隔）
# 覆盖主流网络设备厂商 + 常见终端/虚拟化厂商
_OUI_DB: dict[str, str] = {
    # ── Cisco ──
    '000c29': 'VMware', '005056': 'VMware', '000569': 'VMware',
    '0050f2': 'Microsoft', '000d3a': 'Microsoft',
    '00005e': 'IANA', '01005e': 'IANA(Multicast)',
    # Cisco
    '000c85': 'Cisco', '000dec': 'Cisco', '001795': 'Cisco',
    '001e13': 'Cisco', '001e49': 'Cisco', '002155': 'Cisco',
    '00264a': 'Cisco', '0026cb': 'Cisco', '002cc8': 'Cisco',
    '00508b': 'Cisco', '009027': 'Cisco', '00a0c5': 'Cisco',
    '00e014': 'Cisco', '00e04f': 'Cisco', '00e08f': 'Cisco',
    '243ab7': 'Cisco', '286f7f': 'Cisco', '2c3124': 'Cisco',
    '382056': 'Cisco', '40f4ec': 'Cisco', '4c4e35': 'Cisco',
    '5835d9': 'Cisco', '587eea': 'Cisco', '58971e': 'Cisco',
    '5c5015': 'Cisco', '6073e0': 'Cisco', '6817294': 'Cisco',
    '7069e6': 'Cisco', '7c0e ce': 'Cisco', '881dfc': 'Cisco',
    '8875b4': 'Cisco', 'a4b1c1': 'Cisco', 'b4a4e3': 'Cisco',
    'bad7f3': 'Cisco', 'c800e0': 'Cisco', 'cc16e0': 'Cisco',
    'd0a5a6': 'Cisco', 'e4d3f1': 'Cisco', 'f02929': 'Cisco',
    'f84f57': 'Cisco', 'fc5b39': 'Cisco', '008030': 'Cisco',
    '000142': 'Cisco', '000143': 'Cisco', '000164': 'Cisco',
    '0001c7': 'Cisco', '000196': 'Cisco', '0001c9': 'Cisco',
    # Huawei
    '000e8f': 'Huawei', '001e10': 'Huawei', '002568': 'Huawei',
    '0025a0': 'Huawei', '0034fe': 'Huawei', '00464b': 'Huawei',
    '00e0fc': 'Huawei', '041320': 'Huawei', '04bd70': 'Huawei',
    '04f938': 'Huawei', '0819a6': 'Huawei', '087a4c': 'Huawei',
    '08632a': 'Huawei', '0c37dc': 'Huawei', '0cd6bd': 'Huawei',
    '101b54': 'Huawei', '104780': 'Huawei', '107b44': 'Huawei',
    '14b968': 'Huawei', '1c1d67': 'Huawei', '2008ed': 'Huawei',
    '200bc7': 'Huawei', '203db2': 'Huawei', '206bf3': 'Huawei',
    '2400ba': 'Huawei', '2469a5': 'Huawei', '247f3c': 'Huawei',
    '28a6db': 'Huawei', '28b448': 'Huawei', '2cc553': 'Huawei',
    '2cfda1': 'Huawei', '3055e7': 'Huawei', '306bd3': 'Huawei',
    '30d17e': 'Huawei', '34cdbe': 'Huawei', '380e4d': 'Huawei',
    '38f889': 'Huawei', '3cfb18': 'Huawei', '4007c0': 'Huawei',
    '4c1fcc': 'Huawei', '54a51b': 'Huawei', '58605f': 'Huawei',
    '5c09e1': 'Huawei', '5c7d5e': 'Huawei', '607e04': 'Huawei',
    '60e701': 'Huawei', '64a2f9': 'Huawei', '680715': 'Huawei',
    '6c7220': 'Huawei', '707be8': 'Huawei', '7486e2': 'Huawei',
    '7c6097': 'Huawei', '80fb06': 'Huawei', '843dc6': 'Huawei',
    '88ceb4': 'Huawei', '8c34fd': 'Huawei', '8ce748': 'Huawei',
    '9017ac': 'Huawei', '9c28ef': 'Huawei', 'a08cf8': 'Huawei',
    'a4ba76': 'Huawei', 'ac853d': 'Huawei', 'b4a9fc': 'Huawei',
    'c8d15e': 'Huawei', 'cc96a0': 'Huawei', 'd0659e': 'Huawei',
    'd065ca': 'Huawei', 'd46aa8': 'Huawei', 'dc094c': 'Huawei',
    'e0247f': 'Huawei', 'e0cc7a': 'Huawei', 'e4a7c5': 'Huawei',
    'f4c714': 'Huawei', 'f4e3fb': 'Huawei', 'f80113': 'Huawei',
    'f83dff': 'Huawei', 'fce33c': 'Huawei',
    # H3C / HPE (H3C branded)
    '00188b': 'H3C', '001fe1': 'H3C', '002389': 'H3C',
    '003c10': 'H3C', '00e0b1': 'H3C', '040a83': 'H3C',
    '084f0a': 'H3C', '08b2a3': 'H3C', '10e0e1': 'H3C',
    '14b31f': 'H3C', '1c4d66': 'H3C', '2016d8': 'H3C',
    '24798a': 'H3C', '2c4427': 'H3C', '3003e0': 'H3C',
    '3c8c40': 'H3C', '3cfc71': 'H3C', '508789': 'H3C',
    '586ab1': 'H3C', '701a04': 'H3C', '7822e4': 'H3C',
    '80a235': 'H3C', '84d9c8': 'H3C', 'b86cda': 'H3C',
    'bc052b': 'H3C', 'cc3ae5': 'H3C', 'e8e875': 'H3C',
    # Arista
    '001c73': 'Arista', '048a15': 'Arista', '28990b': 'Arista',
    '2cc260': 'Arista', '444ca8': 'Arista',
    # Juniper
    '002283': 'Juniper', '0005860': 'Juniper', '000585': 'Juniper',
    '0010db': 'Juniper', '001baa': 'Juniper', '0019e2': 'Juniper',
    '002197': 'Juniper', '002688': 'Juniper', '00268b': 'Juniper',
    '003146': 'Juniper', '4c9614': 'Juniper', '5c5e1f': 'Juniper',
    '54e032': 'Juniper', '784858': 'Juniper', '80ac0b': 'Juniper',
    '88e0f3': 'Juniper', '9ce574': 'Juniper', 'f01c2d': 'Juniper',
    # Ruijie / 锐捷
    '001a64': 'Ruijie', '5869b4': 'Ruijie', '0014e5': 'Ruijie',
    '588679': 'Ruijie', 'c0b8e6': 'Ruijie', '000f89': 'Ruijie',
    # Dell
    '000c29': 'VMware',  # already set above
    '001422': 'Dell', '0024e8': 'Dell', '00215e': 'Dell',
    '00188b': 'Dell', '18db14': 'Dell', '245a4c': 'Dell',
    '348870': 'Dell', '5c260a': 'Dell', 'b82a72': 'Dell',
    'f48e38': 'Dell', 'f8b156': 'Dell',
    # HP / HPE
    '001635': 'HP', '001708': 'HP', '001a4b': 'HP',
    '0021f2': 'HP', '002655': 'HP', '00265a': 'HP',
    '08002b': 'HP', '0c8bfd': 'HP', '14022e': 'HP',
    '3863bb': 'HP', '3ca82a': 'HP', '443192': 'HP',
    '5065f3': 'HP', '705a0f': 'HP', '78acc0': 'HP',
    '80c16e': 'HP', '98e7f4': 'HP', 'a0d3c1': 'HP',
    'c83a35': 'HP', 'f0921c': 'HP', 'fc15b4': 'HP',
    # Apple
    '000502': 'Apple', '000a27': 'Apple', '001451': 'Apple',
    '0025bc': 'Apple', '04f7e4': 'Apple', '0c8910': 'Apple',
    '109add': 'Apple', '14109f': 'Apple', '18ee69': 'Apple',
    '1c36bb': 'Apple', '28cf e9': 'Apple', '2c3361': 'Apple',
    '34363b': 'Apple', '38c986': 'Apple', '4860bc': 'Apple',
    '503237': 'Apple', '54ae27': 'Apple', '58b035': 'Apple',
    '60c547': 'Apple', '643803': 'Apple', '685b35': 'Apple',
    '706bcd': 'Apple', '78886d': 'Apple', '80e650': 'Apple',
    '843835': 'Apple', '8866a5': 'Apple', '8c8590': 'Apple',
    '90b21f': 'Apple', 'a860b6': 'Apple', 'acbc32': 'Apple',
    'b8e856': 'Apple', 'c8d083': 'Apple', 'dc2b2a': 'Apple',
    'e0c767': 'Apple', 'f0989d': 'Apple', 'f4f951': 'Apple',
    # Intel
    '000e0c': 'Intel', '001517': 'Intel', '001b21': 'Intel',
    '001e64': 'Intel', '002314': 'Intel', '003676': 'Intel',
    '0050f1': 'Intel', '4851b7': 'Intel', '60f262': 'Intel',
    '804971': 'Intel', '8c8d28': 'Intel', 'a0369f': 'Intel',
    'a44cc8': 'Intel', 'b4a8b9': 'Intel', 'c8f750': 'Intel',
    'f8633f': 'Intel',
    # Samsung
    '000d70': 'Samsung', '0012fb': 'Samsung', '001c43': 'Samsung',
    '002567': 'Samsung', '14f42a': 'Samsung', '188331': 'Samsung',
    '18227e': 'Samsung', '24db96': 'Samsung', '2c4401': 'Samsung',
    '3416a6': 'Samsung', '4018d8': 'Samsung', '50017f': 'Samsung',
    '5c3c27': 'Samsung', '6077e2': 'Samsung', '7825ad': 'Samsung',
    '84119e': 'Samsung', '94350a': 'Samsung', 'a0cbfd': 'Samsung',
    'b49691': 'Samsung', 'c44619': 'Samsung', 'f4428f': 'Samsung',
    'f8042e': 'Samsung',
    # Lenovo
    '000e9b': 'Lenovo', '00060d': 'Lenovo', '0021cc': 'Lenovo',
    'c80aa9': 'Lenovo', 'e8b1fc': 'Lenovo', '54ee75': 'Lenovo',
    '8cec4b': 'Lenovo', '2c8a72': 'Lenovo', '284c6a': 'Lenovo',
    # TP-Link
    '001d0f': 'TP-Link', '50fa84': 'TP-Link', '740827': 'TP-Link',
    '848dc7': 'TP-Link', '88253b': 'TP-Link', 'b0a7b9': 'TP-Link',
    'c006c3': 'TP-Link', 'e84dd0': 'TP-Link', 'f4f26d': 'TP-Link',
    '000b57': 'TP-Link', '14cf92': 'TP-Link', '54c80f': 'TP-Link',
    # QEMU / KVM
    '525400': 'QEMU/KVM',
    # Proxmox / Linux bridge
    'fe5400': 'Proxmox',
    # Xiaomi
    '0013e0': 'Xiaomi', '00ec0a': 'Xiaomi', '286c07': 'Xiaomi',
    '640980': 'Xiaomi', '7c1104': 'Xiaomi', '8cbfa6': 'Xiaomi',
    'f08a76': 'Xiaomi', 'f80377': 'Xiaomi', '50d2f5': 'Xiaomi',
    '64b473': 'Xiaomi', '3478d7': 'Xiaomi', '2482f4': 'Xiaomi',
    # Supermicro
    '003048': 'Supermicro', '0cc47a': 'Supermicro', 'ac1f6b': 'Supermicro',
    # ZTE
    '000afe': 'ZTE', '001ac4': 'ZTE', '001e73': 'ZTE',
    '002293': 'ZTE', '0026ed': 'ZTE', '049300': 'ZTE',
    '284867': 'ZTE', '546c0e': 'ZTE', '7c3953': 'ZTE',
    'a0f479': 'ZTE', 'c864c7': 'ZTE',
    # Hikvision 海康威视
    '28572c': 'Hikvision', '44a842': 'Hikvision', 'c0564d': 'Hikvision',
    'c4cb6b': 'Hikvision', 'e0aa96': 'Hikvision', '202564': 'Hikvision',
    # Dahua 大华
    '3459c0': 'Dahua', '6003c5': 'Dahua', 'a081bf': 'Dahua',
    'b0c2c3': 'Dahua', 'e0500a': 'Dahua',
    # Fortinet
    '000e8e': 'Fortinet', '001e8c': 'Fortinet', '009b6a': 'Fortinet',
    '084f1d': 'Fortinet', '70544f': 'Fortinet', '90ece4': 'Fortinet',
    # Palo Alto
    '00860c': 'PaloAlto', 'b4ffe4': 'PaloAlto',
    # Ubiquiti
    '0418d6': 'Ubiquiti', '24a43c': 'Ubiquiti', '44d9e7': 'Ubiquiti',
    '788a20': 'Ubiquiti', '802aa8': 'Ubiquiti', 'b4fbe4': 'Ubiquiti',
    'dc9fdb': 'Ubiquiti', 'e063da': 'Ubiquiti', 'f09fc2': 'Ubiquiti',
    # MikroTik
    '000c42': 'MikroTik', '002722': 'MikroTik', 'd4ca6d': 'MikroTik',
    'e4011b': 'MikroTik', '6c3b6b': 'MikroTik',
    # Broadcom-based virtual MACs (commonly used)
    'aabbcc': 'Virtual/Lab',
    '005079': 'Broadcom',
    '0050f6': 'Microsoft(HyperV)',
    # Linux bridge default
    'fefefe': 'Linux-Bridge',
    # Docker default
    '020000': 'Docker',
    '020042': 'Docker',
}


def lookup_vendor(mac_12hex: str) -> str:
    """
    根据 12 位 hex MAC 地址查找厂商名。
    优先匹配前 6 位（OUI），未命中返回空字符串。

    参数:
        mac_12hex: 小写无分隔符的 12 位 hex MAC 地址
    返回:
        厂商名字符串，未命中返回空字符串
    """
    if not mac_12hex or len(mac_12hex) < 6:
        return ''
    prefix = mac_12hex[:6].lower()
    return _OUI_DB.get(prefix, '')
