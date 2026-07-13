from typing import Dict, Any

def normalize_device_platform(vendor: str, platform: str) -> str:
    """
    Ensure vendor and platform are aligned and prevent silent fallback to Cisco
    when the vendor is H3C, Huawei, Ruijie, Juniper, or Arista.
    """
    v = str(vendor or '').strip().lower()
    p = str(platform or '').strip().lower()
    
    # Map vendor names to vendor keys
    if 'huawei' in v or 'vrp' in v:
        v_key = 'huawei'
    elif 'h3c' in v or 'comware' in v or 'hp' in v:
        v_key = 'h3c'
    elif 'ruijie' in v or 'rgos' in v:
        v_key = 'ruijie'
    elif 'juniper' in v or 'junos' in v:
        v_key = 'juniper'
    elif 'arista' in v or 'eos' in v:
        v_key = 'arista'
    elif 'cisco' in v or 'ios' in v:
        v_key = 'cisco'
    else:
        v_key = ''

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
    elif v_key == 'juniper':
        if not p or 'cisco' in p or p == 'generic':
            return 'juniper_junos'
    elif v_key == 'arista':
        if not p or 'cisco' in p or p == 'generic':
            return 'arista_eos'

    # Normalization of platform aliases
    if 'huawei' in p or 'vrp' in p:
        return 'huawei_vrp'
    elif 'h3c' in p or 'comware' in p:
        return 'h3c_comware'
    elif 'ruijie' in p or 'rgos' in p:
        return 'ruijie_rgos'
    elif 'juniper' in p or 'junos' in p:
        return 'juniper_junos'
    elif 'arista' in p or 'eos' in p:
        return 'arista_eos'
    elif 'nxos' in p or 'nexus' in p:
        return 'cisco_nxos'
        
    return platform or 'cisco_ios'
