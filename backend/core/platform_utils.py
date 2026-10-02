from typing import Dict, Any


def _platform_vendor(platform: str) -> str:
    value = str(platform or '').strip().lower().replace('-', '_').replace(' ', '_')
    if value.startswith(('huawei', 'vrp')):
        return 'huawei'
    if value.startswith(('h3c', 'comware', 'hp_comware')):
        return 'h3c'
    if value.startswith(('ruijie', 'rgos')):
        return 'ruijie'
    if value.startswith(('zte', 'zxros')):
        return 'zte'
    if value.startswith('raisecom'):
        return 'raisecom'
    if value.startswith(('maipu', 'mypower')):
        return 'maipu'
    if value.startswith(('dptech', 'conplat')):
        return 'dptech'
    if value.startswith(('juniper', 'junos')):
        return 'juniper'
    if value.startswith(('hillstone', 'stoneos')):
        return 'hillstone'
    if value.startswith(('arista', 'eos')):
        return 'arista'
    if value.startswith(('cisco', 'ios', 'nxos', 'nexus', 'asa')):
        return 'cisco'
    return ''

def normalize_device_platform(vendor: str, platform: str) -> str:
    """
    Ensure vendor and platform are aligned and prevent silent fallback to Cisco
    when the vendor is H3C, Huawei, Ruijie, ZTE, Raisecom, Maipu, DCN,
    DPtech, FiberHome, Juniper, Arista, or Hillstone.
    """
    v = str(vendor or '').strip().lower()
    p = str(platform or '').strip().lower()
    
    # Map vendor names to vendor keys
    if 'huawei' in v or 'vrp' in v or '华为' in v:
        v_key = 'huawei'
    elif 'h3c' in v or 'comware' in v or 'hp' in v or '华三' in v:
        v_key = 'h3c'
    elif 'ruijie' in v or 'rgos' in v or '锐捷' in v:
        v_key = 'ruijie'
    elif 'zte' in v or 'zxros' in v or '中兴' in v:
        v_key = 'zte'
    elif 'raisecom' in v or '瑞斯康达' in v:
        v_key = 'raisecom'
    elif 'maipu' in v or '迈普' in v:
        v_key = 'maipu'
    elif 'dptech' in v or '迪普' in v:
        v_key = 'dptech'
    elif 'juniper' in v or 'junos' in v:
        v_key = 'juniper'
    elif 'hillstone' in v or 'stoneos' in v or '山石' in v:
        v_key = 'hillstone'
    elif 'arista' in v or 'eos' in v:
        v_key = 'arista'
    elif 'cisco' in v or 'ios' in v:
        v_key = 'cisco'
    else:
        v_key = ''

    # Keep the transport/parser family aligned with an explicit vendor. Older
    # device rows can contain a different vendor's platform (or a server OS),
    # and preserving that value sends the selected vendor's command to the
    # wrong Netmiko driver. Compatible version-specific platform names remain
    # intact below.
    vendor_default = {
        'huawei': 'huawei_vrp',
        'h3c': 'h3c_comware',
        'ruijie': 'ruijie_rgos',
        'zte': 'zte_zxros',
        'raisecom': 'raisecom_ros',
        'maipu': 'maipu',
        'dptech': 'dptech_ios',
        'juniper': 'juniper_junos',
        'arista': 'arista_eos',
        'hillstone': 'hillstone_stoneos',
        'cisco': 'cisco_ios',
    }
    if v_key and _platform_vendor(p) != v_key:
        if v_key == 'dptech' and ('fw' in p or 'firewall' in p):
            return 'dptech_conplat_fw'
        return vendor_default[v_key]

    # The persisted parser/transport family is one H3C Comware key.  Concrete
    # V3/V5/V7/V9 command differences belong to Platform Profile releases, not to
    # another device platform string.
    explicit_platforms = {
        'huawei_vrp', 'huawei_vrpv8', 'vrp5', 'vrpv5', 'vrp8', 'vrpv8',
        'h3c_comware', 'h3c_comware_v3', 'h3c_comware_v5', 'h3c_comware_v7', 'h3c_comware_v9',
        'ruijie_rgos', 'ruijie_os', 'zte_zxros', 'maipu', 'maipu_network', 'maipu_mypower',
        'dptech_ios', 'dptech', 'dptech_conplat', 'dptech_conplat_fw',
        'raisecom_ros', 'raisecom_ros5', 'raisecom_ros_5',
        'hillstone_stoneos',
    }
    if p in explicit_platforms:
        if p in {'vrp8', 'vrpv8'}:
            return 'huawei_vrpv8'
        if p in {'vrp5', 'vrpv5'}:
            return 'huawei_vrp'
        if p in {'h3c_comware', 'h3c_comware_v3', 'h3c_comware_v5', 'h3c_comware_v7', 'h3c_comware_v9'}:
            return 'h3c_comware'
        if p in {'ruijie_os', 'ruijie_rgos'}:
            return 'ruijie_rgos'
        if p in {'maipu_network', 'maipu_mypower'}:
            return 'maipu'
        if p in {'dptech_conplat', 'dptech_conplat_fw'}:
            return p
        if p in {'dptech', 'dptech_ios'}:
            return 'dptech_ios'
        return p

    # If platform is empty or generic/cisco but vendor is specific, override it
    if v_key == 'huawei':
        if not p or 'cisco' in p or p == 'generic':
            return 'huawei_vrp'
    elif v_key == 'h3c':
        if not p or 'cisco' in p or p == 'generic':
            return 'h3c_comware'
    elif v_key == 'ruijie':
        if not p or 'cisco' in p or p == 'generic':
            return 'ruijie_rgos'
    elif v_key == 'zte':
        if not p or 'cisco' in p or p == 'generic':
            return 'zte_zxros'
    elif v_key == 'raisecom':
        if not p or 'cisco' in p or p == 'generic':
            return 'raisecom_ros'
    elif v_key == 'maipu':
        if not p or 'cisco' in p or p == 'generic':
            return 'maipu'
    elif v_key == 'dptech':
        if not p or 'cisco' in p or p == 'generic':
            if 'fw' in p or 'firewall' in p:
                return 'dptech_conplat_fw'
            return 'dptech_ios'
    elif v_key == 'juniper':
        if not p or 'cisco' in p or p == 'generic':
            return 'juniper_junos'
    elif v_key == 'arista':
        if not p or 'cisco' in p or p == 'generic':
            return 'arista_eos'

    # Normalization of platform aliases
    if 'huawei' in p or 'vrp' in p or '华为' in p:
        return 'huawei_vrp'
    elif 'h3c' in p or 'comware' in p or '华三' in p:
        return 'h3c_comware'
    elif 'ruijie' in p or 'rgos' in p or '锐捷' in p:
        return 'ruijie_rgos'
    elif 'zte' in p or 'zxros' in p or '中兴' in p:
        return 'zte_zxros'
    elif 'raisecom' in p or '瑞斯康达' in p:
        return 'raisecom_ros'
    elif 'maipu' in p or '迈普' in p or 'mypower' in p:
        return 'maipu'
    elif 'dptech' in p or 'conplat' in p or '迪普' in p:
        return 'dptech_ios'
    elif 'juniper' in p or 'junos' in p:
        return 'juniper_junos'
    elif 'hillstone' in p or 'stoneos' in p or '山石' in p:
        return 'hillstone_stoneos'
    elif 'arista' in p or 'eos' in p:
        return 'arista_eos'
    elif 'nxos' in p or 'nexus' in p:
        return 'cisco_nxos'
        
    return platform or 'cisco_ios'
